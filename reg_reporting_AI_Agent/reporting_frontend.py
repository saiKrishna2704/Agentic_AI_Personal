import os
import re
import socket
import subprocess
import sys
import time

import requests
import streamlit as st

BACKEND_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Regulatory Reporting Assistant", page_icon="§", layout="centered")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "active_report" not in st.session_state:
    st.session_state.active_report = None  # filename of the report currently loaded on the backend


def is_backend_running():
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            return True
    except OSError:
        return False


def wait_for_backend(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(f"{BACKEND_URL}/health", timeout=2)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def start_backend():
    if is_backend_running():
        return

    backend_path = os.path.join(os.path.dirname(__file__), "reporting_backend.py")
    subprocess.Popen(
        [sys.executable, backend_path],
        cwd=os.path.dirname(__file__),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    if not wait_for_backend():
        raise RuntimeError("Backend did not start in time")


start_backend()

# --------------------------------------------------------------------------
# Visual identity: a navy "filing ledger" look built for a regulatory /
# risk-and-compliance audience, rather than a generic chat-app theme.
# --------------------------------------------------------------------------
st.markdown(
    """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,600;8..60,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

        :root {
            --ink: #10161F;
            --panel: #1A2431;
            --panel-2: #212D3D;
            --parchment: #E9E4D6;
            --muted: #8C97A8;
            --brass: #C7A045;
            --brass-dim: rgba(199, 160, 69, 0.32);
            --seal: #A2453D;
        }

        .stApp, div[data-testid="stAppViewContainer"] {
            background: var(--ink);
        }
        .stApp, .stApp p, .stApp span, .stApp label, .stApp li {
            font-family: 'IBM Plex Sans', sans-serif;
            color: var(--parchment);
        }
        div[data-testid="stHeader"] {
            background: transparent;
        }
        div[data-testid="stMainBlockContainer"] {
            padding-top: 2.2rem;
        }

        /* --- Letterhead ---------------------------------------------- */
        .letterhead h1 {
            font-family: 'Source Serif 4', serif;
            font-weight: 600;
            font-size: 2.1rem;
            color: var(--parchment);
            margin: 0 0 0.35rem 0;
            letter-spacing: 0.01em;
        }
        .letterhead p {
            font-size: 0.95rem;
            color: var(--muted);
            max-width: 58ch;
            margin: 0;
        }
        .ledger-rule {
            height: 2px;
            background: var(--brass);
            border: none;
            margin: 1rem 0 1.4rem 0;
            opacity: 0.85;
        }

        /* --- Report status readout ------------------------------------ */
        .report-tag {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.82rem;
            padding: 0.55rem 0.85rem;
            border-left: 3px solid var(--brass);
            background: var(--panel);
            color: var(--parchment);
        }
        .report-tag.empty {
            border-left-color: var(--muted);
            color: var(--muted);
        }

        /* --- Clear-report button (ghost style) ------------------------ */
        div[data-testid="column"]:nth-of-type(2) .stButton > button {
            background: transparent;
            color: var(--brass);
            border: 1px solid var(--brass-dim);
            border-radius: 4px;
            font-size: 0.8rem;
            padding: 0.5rem 0.7rem;
            width: 100%;
        }
        div[data-testid="column"]:nth-of-type(2) .stButton > button:hover {
            border-color: var(--brass);
            color: var(--parchment);
        }

        /* --- Chat transcript panel: fixed height, scrolls internally so
           the question form below it never moves as the chat grows -------- */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatMessage"]) {
            background: var(--panel);
            border: 1px solid rgba(140, 151, 168, 0.18);
            overflow: hidden;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatMessage"]) div[data-testid="stVerticalBlock"] {
            overflow-y: auto !important;
            padding-right: 0.4rem;
            scrollbar-width: thin;
            scrollbar-color: var(--brass-dim) var(--panel);
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatMessage"]) div[data-testid="stVerticalBlock"]::-webkit-scrollbar {
            width: 8px;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatMessage"]) div[data-testid="stVerticalBlock"]::-webkit-scrollbar-track {
            background: var(--panel);
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatMessage"]) div[data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb {
            background: var(--brass-dim);
            border-radius: 4px;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatMessage"]) div[data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb:hover {
            background: var(--brass);
        }

        .stChatMessage {
            background: transparent !important;
        }
        [data-testid="stChatMessageAvatarUser"] {
            background: var(--panel-2) !important;
            color: var(--parchment) !important;
        }
        [data-testid="stChatMessageAvatarAssistant"],
        [data-testid="stChatMessageAvatarCustom"],
        [data-testid="stChatMessageAvatarIcon"] {
            background: var(--brass) !important;
            color: var(--ink) !important;
        }
        div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]),
        div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarCustom"]),
        div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarIcon"]) {
            border-left: 2px solid var(--brass-dim);
            padding-left: 0.75rem;
            margin-left: 0.2rem;
        }

        /* --- Input form -------------------------------------------------- */
        .stForm {
            position: sticky;
            bottom: 0;
            background: var(--panel);
            border: 1px solid rgba(140, 151, 168, 0.18);
            border-radius: 6px;
            padding: 0.9rem 1rem;
        }
        .stTextArea textarea {
            background: var(--ink) !important;
            color: var(--parchment) !important;
            border: 1px solid rgba(140, 151, 168, 0.25) !important;
            border-radius: 4px !important;
            font-family: 'IBM Plex Sans', sans-serif !important;
        }
        .stTextArea textarea:focus {
            border-color: var(--brass) !important;
            box-shadow: 0 0 0 1px var(--brass-dim) !important;
        }
        .stTextArea textarea::placeholder {
            color: var(--muted) !important;
        }
        .stTextArea label {
            font-size: 0.85rem !important;
            color: var(--muted) !important;
        }

        /* File uploader - attractive styling */
        [data-testid="stFileUploader"] {
            margin-bottom: 1.5rem;
            background: linear-gradient(135deg, rgba(199, 160, 69, 0.1) 0%, rgba(199, 160, 69, 0.05) 100%);
            padding: 1.2rem;
            border: 2px dashed var(--brass);
            border-radius: 6px;
        }
        [data-testid="stFileUploader"] > section {
            display: flex !important;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 0.8rem;
        }
        [data-testid="stFileUploaderDropzone"] {
            display: flex !important;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 0.6rem;
        }
        /* Style the label */
        [data-testid="stFileUploader"] label {
            color: var(--parchment) !important;
            font-weight: 600 !important;
            font-size: 0.95rem !important;
            margin-bottom: 0.5rem !important;
        }
        /* Hide unwanted text but keep button */
        [data-testid="stFileUploaderDropzoneInstructions"] {
            display: none !important;
        }
        [data-testid="stFileUploaderFile"] {
            display: flex !important;
            align-items: center;
            gap: 0.5rem;
            margin-top: 0.4rem;
        }
        [data-testid="stFileUploader"] button {
            background: var(--brass) !important;
            color: var(--ink) !important;
            border: none !important;
            border-radius: 5px !important;
            padding: 0.7rem 1.8rem !important;
            font-size: 0.9rem !important;
            font-weight: 600 !important;
            cursor: pointer !important;
            transition: all 0.3s ease !important;
            box-shadow: 0 4px 6px rgba(199, 160, 69, 0.2) !important;
        }
        [data-testid="stFileUploader"] button:hover {
            background: #D9B355 !important;
            transform: translateY(-2px) !important;
            box-shadow: 0 6px 12px rgba(199, 160, 69, 0.3) !important;
        }
        [data-testid="stFileUploader"] button:active {
            transform: translateY(0) !important;
        }
        [data-testid="stFileUploaderFileName"] {
            color: var(--parchment) !important;
        }
        [data-testid="stFileUploaderFileData"] small {
            display: none;
        }

        /* Submit ("Ask") button — the one filled accent in the whole page */
        div[data-testid="stFormSubmitButton"] button {
            background: var(--brass) !important;
            color: var(--ink) !important;
            border: none !important;
            border-radius: 4px !important;
            font-weight: 600 !important;
            padding: 0.55rem 1.3rem !important;
        }
        div[data-testid="stFormSubmitButton"] button:hover {
            background: #D9B355 !important;
            color: var(--ink) !important;
        }

        /* Alerts (warnings / errors) kept on-palette */
        div[data-testid="stAlert"] {
            background: var(--panel) !important;
            border-left: 3px solid var(--seal) !important;
            border-radius: 2px;
        }
        div[data-testid="stAlert"] p {
            color: var(--parchment) !important;
        }

        .stCaption, [data-testid="stCaptionContainer"] {
            color: var(--muted) !important;
        }

        footer { visibility: hidden; }

        /* --- Empty-state welcome inside the transcript panel ------------ */
        .empty-state {
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: flex-start;
            gap: 0.6rem;
            padding: 1.5rem 1rem;
        }
        .empty-state .mark {
            font-family: 'Source Serif 4', serif;
            font-size: 1.6rem;
            color: var(--brass);
            border: 1px solid var(--brass-dim);
            width: 2.4rem;
            height: 2.4rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .empty-state h3 {
            font-family: 'Source Serif 4', serif;
            font-weight: 600;
            font-size: 1.15rem;
            color: var(--parchment);
            margin: 0.2rem 0 0 0;
        }
        .empty-state p {
            color: var(--muted);
            font-size: 0.88rem;
            max-width: 46ch;
            margin: 0;
        }
        .empty-state ul {
            margin: 0.3rem 0 0 0;
            padding-left: 1.1rem;
            color: var(--muted);
            font-size: 0.85rem;
        }
        .empty-state li {
            margin-bottom: 0.3rem;
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.8rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="letterhead">
        <h1>Regulatory Reporting Assistant</h1>
        <p>Ask questions about regulatory filings, grounded in the report you attach below.</p>
    </div>
    <hr class="ledger-rule" />
    """,
    unsafe_allow_html=True,
)


def fetch_report_status():
    try:
        response = requests.get(f"{BACKEND_URL}/report_status/", timeout=5)
        if response.status_code == 200:
            data = response.json()
            st.session_state.active_report = data.get("filename")
    except requests.RequestException:
        pass


fetch_report_status()

status_col, clear_col = st.columns([4, 1])
with status_col:
    if st.session_state.active_report:
        st.markdown(
            f'<div class="report-tag">Report loaded: {st.session_state.active_report}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="report-tag empty">Attach a CSV, XLSX, or DOCX below.</div>',
            unsafe_allow_html=True,
        )
with clear_col:
    if st.session_state.active_report and st.button("Clear report"):
        try:
            requests.delete(f"{BACKEND_URL}/reset/", timeout=5)
        except requests.RequestException as exc:
            st.error(f"Could not clear report: {exc}")
        else:
            st.session_state.active_report = None
            st.rerun()

st.write("")

message_container = st.container(height=420, border=True)
with message_container:
    if not st.session_state.chat_history:
        st.markdown(
            """
            <div class="empty-state">
                <div class="mark">§</div>
                <h3>Ask me anything</h3>
                <p>Attach a regulatory report to ask about its figures, or just start
                chatting — I can help without a report too.</p>
                <ul>
                    <li>What does the LCR measure?</li>
                    <li>Summarize the key figures in this report</li>
                    <li>Which line items changed most vs. last quarter?</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
    for entry in st.session_state.chat_history:
        with st.chat_message("user"):
            st.markdown(entry["question"])
        with st.chat_message("assistant", avatar="⚖️"):
            st.markdown(entry["answer"])

with st.form(key="question_form", clear_on_submit=True):
    uploaded_file = st.file_uploader(
        "Attach a report", type=["csv", "xlsx", "docx"], key="report_file",
        label_visibility="visible",
    )
    st.caption("CSV, XLSX, or DOCX, up to 200MB. Stays loaded until you clear it.")
    user_question = st.text_area("Ask a question about this report:", key="question_input")
    submitted = st.form_submit_button("Ask")

if submitted:
    if not user_question.strip():
        st.warning("Please enter a question before submitting.")
    else:
        with st.spinner("Generating answer..."):
            try:
                wait_for_backend()
                payload = {"question": user_question}
                files = {}
                if uploaded_file is not None:
                    files["file"] = (
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        uploaded_file.type or "application/octet-stream",
                    )
                response = requests.post(
                    f"{BACKEND_URL}/ask_report/", files=files, data=payload, timeout=60
                )
            except requests.RequestException as exc:
                st.error(f"Connection to backend failed: {exc}")
                st.stop()

        if response.status_code == 200:
            data = response.json()
            answer = re.sub(r"<[^>]+>", "", data["answer"])
            st.session_state.chat_history.append({"question": user_question, "answer": answer})
            st.session_state.active_report = data.get("filename")
            st.rerun()
        else:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            st.error(f"Error querying the backend: {detail}")