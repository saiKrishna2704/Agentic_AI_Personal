"""
Policy Q&A Agent (Streamlit + LangChain + OpenAI)
---------------------------------------------------
Upload a policy document (PDF, DOCX, or TXT) before asking questions. Uses
LangChain document loaders, a text splitter, FAISS for vector search, and
OpenAI for embeddings + the chat model, wired together with a RetrievalQA chain.

The OpenAI API key is read only from environment variables / a .env file and
is never shown or entered in the UI.

Requirements (install once):
    pip install streamlit langchain langchain-community langchain-openai pypdf docx2txt faiss-cpu openai python-dotenv

.env file (same folder as this script) should contain at least:
    OPENAI_API_KEY=sk-...
    CHAT_MODEL_NAME=gpt-4o-mini

Run with:
    streamlit run PolicyRAG.py
"""

import os
import tempfile

from dotenv import load_dotenv
import streamlit as st

load_dotenv()  # reads OPENAI_API_KEY, CHAT_MODEL_NAME, etc. from a .env file in this folder

from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.chains import RetrievalQA

# ---------------- Configuration ----------------
API_KEY = os.getenv("OPENAI_API_KEY")
CHAT_MODEL = os.getenv("CHAT_MODEL_NAME", "gpt-4o-mini")
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
TOP_K_CHUNKS = 4
SUPPORTED_TYPES = ["pdf", "docx", "txt"]
# -------------------------------------------------

st.set_page_config(page_title="Policy Q&A Agent", page_icon="📄", layout="wide")


# ---------------- Session state ----------------

if "qa_chain" not in st.session_state:
    st.session_state.qa_chain = None
if "doc_name" not in st.session_state:
    st.session_state.doc_name = None
if "messages" not in st.session_state:
    st.session_state.messages = []


# ---------------- Helpers ----------------

def load_documents(file_path: str, filename: str):
    """Pick the right LangChain loader based on file extension."""
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext == ".docx":
        loader = Docx2txtLoader(file_path)
    elif ext == ".txt":
        loader = TextLoader(file_path, encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    return loader.load()


def build_qa_chain(file_path: str, filename: str) -> RetrievalQA:
    documents = load_documents(file_path, filename)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(documents)

    embeddings = OpenAIEmbeddings(api_key=API_KEY)
    vectorstore = FAISS.from_documents(chunks, embeddings)

    llm = ChatOpenAI(model=CHAT_MODEL, temperature=0.2, api_key=API_KEY)

    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=vectorstore.as_retriever(search_kwargs={"k": TOP_K_CHUNKS}),
        return_source_documents=True,
    )
    return qa_chain


# ---------------- Sidebar ----------------

with st.sidebar:
    st.header("Policy Document")

    uploaded_file = st.file_uploader(
        "Attach a policy document (PDF, DOCX, or TXT)",
        type=SUPPORTED_TYPES,
    )

    if uploaded_file is not None:
        if st.session_state.doc_name != uploaded_file.name:
            with st.spinner("Reading and indexing the document..."):
                try:
                    suffix = os.path.splitext(uploaded_file.name)[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name

                    st.session_state.qa_chain = build_qa_chain(tmp_path, uploaded_file.name)
                    st.session_state.doc_name = uploaded_file.name
                    st.session_state.messages = []  # reset chat for new document
                    st.success(f"Indexed '{uploaded_file.name}'.")

                    os.remove(tmp_path)
                except Exception as e:
                    st.error(f"Failed to process document: {e}")

    if st.session_state.doc_name:
        st.info(f"Active document: **{st.session_state.doc_name}**")
        if st.button("Remove document / start over"):
            st.session_state.qa_chain = None
            st.session_state.doc_name = None
            st.session_state.messages = []
            st.rerun()


# ---------------- Main area ----------------

st.title("📄 Policy Q&A Agent")
st.caption("Ask questions and get answers grounded in your uploaded policy document.")

if not API_KEY:
    st.error(
        "OPENAI_API_KEY is not set. Add it to a .env file in this folder "
        "(OPENAI_API_KEY=sk-...) and restart the app."
    )
    st.stop()

if st.session_state.qa_chain is None:
    st.info("👈 Please attach a policy document (PDF, DOCX, or TXT) in the sidebar before asking questions.")
    st.stop()

# Show chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat input
question = st.chat_input("Ask a question about the policy document...")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Searching the policy document..."):
            try:
                result = st.session_state.qa_chain.invoke({"query": question})
                answer = result["result"]
                sources = result.get("source_documents", [])

                st.markdown(answer)

                if sources:
                    with st.expander("Show source excerpts used"):
                        for i, doc in enumerate(sources, 1):
                            page = doc.metadata.get("page")
                            label = f"page {page}" if page is not None else "excerpt"
                            st.markdown(f"**Source {i} ({label}):**\n\n{doc.page_content}")

                st.session_state.messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                st.error(f"Something went wrong: {e}")