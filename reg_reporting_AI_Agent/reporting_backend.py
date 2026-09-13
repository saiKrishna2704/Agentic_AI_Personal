"""
Regulatory Reporting AI Assistant — Backend (FastAPI)

Responsibilities:
- Accept an uploaded regulatory report (CSV or XLSX).
- Parse it into a compact, LLM-friendly summary (shape, columns, dtypes,
  null counts, numeric stats, top categorical values, sample rows).
- Cache the most recently uploaded report in memory so the user can ask
  several follow-up questions without re-attaching the file each time.
- Answer natural-language questions about the report (or general
  regulatory-reporting questions) using the OpenAI Chat Completions API.

Environment variables (read from .env):
    OpenAI_API_KEY   - required, your OpenAI API key
    Model_name       - optional, defaults to "gpt-4o-mini"
    Environment      - optional, "development" | "production" (default "development")
"""

import io
import logging
import os
from typing import Optional

import pandas as pd
from docx import Document
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI

# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------

load_dotenv()

OPENAI_API_KEY = os.getenv("OpenAI_API_KEY")
MODEL_NAME = os.getenv("Model_name", "gpt-4o-mini")
ENVIRONMENT = os.getenv("Environment", "development")

logging.basicConfig(
    level=logging.DEBUG if ENVIRONMENT.lower() == "development" else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("reporting_backend")

client: Optional[OpenAI] = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
if client is None:
    logger.warning(
        "OpenAI_API_KEY is not set. /ask_report/ will return an error until it is configured."
    )

app = FastAPI(title="Regulatory Reporting AI Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory cache of the most recently uploaded report. Since this app is
# designed to run as a single local backend for one Streamlit session,
# a simple module-level cache (rather than a per-user session store) is
# enough. Extend this to a dict keyed by session id for multi-user use.
REPORT_CACHE = {
    "filename": None,      # str | None
    "context": None,       # str | None  -- LLM-ready text summary
    "sheet_count": 0,
}

MAX_CONTEXT_CHARS = 12000  # keep the prompt bounded regardless of file size
SAMPLE_ROWS = 10
MAX_SHEETS = 5

SYSTEM_PROMPT = """You are the Regulatory Reporting AI Assistant, a careful, precise \
analyst that helps risk, treasury, and compliance teams understand regulatory and \
liquidity reports (e.g. LCR, NSFR, Basel III/IV returns, capital and liquidity \
disclosures, and similar submissions).

Rules:
- When report data is provided in the context below, ground every specific figure, \
column name, or trend you mention in that data. Do not invent numbers that are not \
present or derivable from the provided summary/sample.
- If the question requires report data that isn't visible in the provided sample or \
summary (e.g. because the file was truncated), say so plainly and explain what \
additional detail would be needed, rather than guessing.
- If no report has been uploaded, you are still a fully capable assistant: answer \
the user's question normally and helpfully, drawing on your general knowledge \
(including general regulatory-reporting expertise, but not limited to it). Only \
mention that no report is loaded if the question genuinely depends on data from a \
specific report the user hasn't provided yet — and even then, answer what you can \
first before asking for the report.
- Be concise, use plain language, and use tables or bullet points for multi-figure \
answers.
"""


# --------------------------------------------------------------------------
# Report parsing helpers
# --------------------------------------------------------------------------

def _summarize_dataframe(df: pd.DataFrame, label: str) -> str:
    """Build a compact, information-dense text summary of a single dataframe."""
    lines = [f"### {label}", f"- Shape: {df.shape[0]} rows x {df.shape[1]} columns"]

    # Columns + dtypes + null counts
    lines.append("- Columns (name: dtype, nulls):")
    for col in df.columns:
        null_count = int(df[col].isna().sum())
        lines.append(f"  - {col}: {df[col].dtype} ({null_count} nulls)")

    # Numeric summary stats
    numeric_df = df.select_dtypes(include="number")
    if not numeric_df.empty:
        stats = numeric_df.describe().T[["min", "mean", "max"]].round(4)
        lines.append("- Numeric column stats (min / mean / max):")
        for col, row in stats.iterrows():
            lines.append(f"  - {col}: {row['min']} / {row['mean']} / {row['max']}")

    # Top values for low-cardinality categorical columns
    categorical_df = df.select_dtypes(exclude="number")
    for col in categorical_df.columns:
        unique_count = df[col].nunique(dropna=True)
        if 0 < unique_count <= 20:
            top_values = df[col].value_counts(dropna=True).head(5)
            formatted = ", ".join(f"{idx} ({count})" for idx, count in top_values.items())
            lines.append(f"- Top values in '{col}': {formatted}")

    # Sample rows
    lines.append(f"- Sample rows (first {min(SAMPLE_ROWS, len(df))}):")
    lines.append(df.head(SAMPLE_ROWS).to_markdown(index=False))

    return "\n".join(lines)


def parse_report(file_bytes: bytes, filename: str) -> str:
    """Parse an uploaded CSV/XLSX/DOCX file into an LLM-ready text context.

    Raises ValueError with a user-facing message on parse failure.
    """
    lower_name = filename.lower()

    try:
        if lower_name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
            sheets = {"Sheet1": df}
        elif lower_name.endswith(".xlsx"):
            sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
        elif lower_name.endswith(".docx"):
            # Parse Word document (python-docx only supports the modern
            # .docx/OOXML format, not the legacy binary .doc format)
            doc = Document(io.BytesIO(file_bytes))
            text_content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            # Create a single-column dataframe with the document text
            df = pd.DataFrame({"Content": [text_content]})
            sheets = {"Document": df}
        else:
            raise ValueError("Unsupported file type. Please upload a .csv, .xlsx, or .docx file.")
    except ValueError:
        raise
    except Exception as exc:  # pandas/openpyxl/python-docx parsing errors
        logger.exception("Failed to parse uploaded report %s", filename)
        raise ValueError(f"Could not read '{filename}': {exc}") from exc

    if not sheets:
        raise ValueError(f"'{filename}' does not contain any readable data.")

    sheet_items = list(sheets.items())[:MAX_SHEETS]
    skipped = len(sheets) - len(sheet_items)

    summaries = [_summarize_dataframe(df, f"Sheet: {name}") for name, df in sheet_items]
    context = f"Report file: {filename}\n\n" + "\n\n".join(summaries)

    if skipped > 0:
        context += f"\n\n(Note: {skipped} additional sheet(s) were not summarized to keep the context concise.)"

    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n(Note: context truncated due to size.)"

    return context, len(sheet_items)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "environment": ENVIRONMENT, "model": MODEL_NAME}


@app.get("/report_status/")
def report_status():
    return {
        "report_loaded": REPORT_CACHE["context"] is not None,
        "filename": REPORT_CACHE["filename"],
    }


@app.delete("/reset/")
def reset_report():
    REPORT_CACHE["filename"] = None
    REPORT_CACHE["context"] = None
    REPORT_CACHE["sheet_count"] = 0
    return {"status": "cleared"}


@app.post("/ask_report/")
async def ask_report(question: str = Form(...), file: Optional[UploadFile] = File(None)):
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="OpenAI_API_KEY is not configured on the server. Add it to your .env file and restart the backend.",
        )

    if not question or not question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    # If a new file was attached, parse it and refresh the cache.
    if file is not None:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        try:
            context, sheet_count = parse_report(file_bytes, file.filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        REPORT_CACHE["filename"] = file.filename
        REPORT_CACHE["context"] = context
        REPORT_CACHE["sheet_count"] = sheet_count
        logger.info("Cached new report: %s (%d sheet(s))", file.filename, sheet_count)

    if REPORT_CACHE["context"]:
        report_block = (
            f"--- REPORT CONTEXT (source: {REPORT_CACHE['filename']}) ---\n"
            f"{REPORT_CACHE['context']}\n"
            f"--- END REPORT CONTEXT ---"
        )
    else:
        report_block = "No report has been uploaded yet."

    user_message = f"{report_block}\n\nQuestion: {question.strip()}"

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        answer = completion.choices[0].message.content
    except Exception as exc:
        logger.exception("OpenAI request failed")
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {exc}")

    return {
        "answer": answer,
        "report_loaded": REPORT_CACHE["context"] is not None,
        "filename": REPORT_CACHE["filename"],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)