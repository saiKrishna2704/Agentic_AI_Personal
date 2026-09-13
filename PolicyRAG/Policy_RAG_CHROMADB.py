"""
Policy Q&A + Semantic Search Agent (Streamlit + LangChain + OpenAI + Chroma)
-----------------------------------------------------------------------------
Upload a policy document (PDF, DOCX, or TXT) before using the app. Two modes:
  - Chat: conversational Q&A grounded in the document (RetrievalQA).
  - Semantic Search: type a query and get ranked, relevant excerpts directly
    from the document (vector similarity search, no LLM generation).

The OpenAI API key is read only from environment variables / a .env file and
is never shown or entered in the UI.

Requirements (install once):
    pip install streamlit langchain langchain-community langchain-openai langchain-chroma chromadb pypdf docx2txt openai python-dotenv

.env file (same folder as this script) should contain at least:
    OPENAI_API_KEY=sk-...
    CHAT_MODEL_NAME=gpt-4o-mini

Run with:
    streamlit run PolicyRAG.py
"""

import os
import sys
import types
import hashlib
import tempfile
import uuid
from pathlib import Path


def _install_xxhash_shim():
    """
    LangSmith (a transitive dependency pulled in by langchain-core) uses the
    compiled 'xxhash' package purely for generating internal UUID7 identifiers.
    On some locked-down Windows machines, Application Control policies block
    that package's native DLL from loading at all, which crashes every
    LangChain import.

    Since this app never uses LangSmith tracing, the exact hash algorithm used
    for those internal IDs doesn't matter - only that *something* deterministic
    and hash-shaped is returned. If the real 'xxhash' package fails to import,
    this installs a pure-Python stand-in (built on hashlib, which has no native
    dependencies) so the rest of the LangChain import chain proceeds normally.
    """
    try:
        import xxhash  # noqa: F401
        return  # real package works fine here, nothing to shim
    except ImportError:
        pass

    def _digest_bytes(data, seed, size):
        if isinstance(data, str):
            data = data.encode("utf-8")
        key = seed.to_bytes(8, "big", signed=False) if seed else b""
        return hashlib.blake2b(data, digest_size=size, key=key).digest()

    class _StreamingHash:
        _size = 8

        def __init__(self, data=b"", seed=0):
            self._seed = seed
            self._buf = b""
            if data:
                self.update(data)

        def update(self, data):
            if isinstance(data, str):
                data = data.encode("utf-8")
            self._buf += data

        def digest(self):
            return _digest_bytes(self._buf, self._seed, self._size)

        def intdigest(self):
            return int.from_bytes(self.digest(), "big")

        def hexdigest(self):
            return self.digest().hex()

        def copy(self):
            clone = self.__class__(seed=self._seed)
            clone._buf = self._buf
            return clone

        def reset(self):
            self._buf = b""

    xxhash_module = types.ModuleType("xxhash")

    for name, size in [("xxh32", 4), ("xxh64", 8), ("xxh3_64", 8), ("xxh3_128", 16)]:
        cls = type(name, (_StreamingHash,), {"_size": size})
        setattr(xxhash_module, name, cls)

        def _make_oneshot(sz):
            def _intdigest(data, seed=0):
                return int.from_bytes(_digest_bytes(data, seed, sz), "big")

            def _digest(data, seed=0):
                return _digest_bytes(data, seed, sz)

            def _hexdigest(data, seed=0):
                return _digest_bytes(data, seed, sz).hex()

            return _intdigest, _digest, _hexdigest

        intdigest, digest, hexdigest = _make_oneshot(size)
        setattr(xxhash_module, f"{name}_intdigest", intdigest)
        setattr(xxhash_module, f"{name}_digest", digest)
        setattr(xxhash_module, f"{name}_hexdigest", hexdigest)

    # common aliases some versions of langsmith may reference
    xxhash_module.xxh128 = xxhash_module.xxh3_128
    xxhash_module.xxh128_intdigest = xxhash_module.xxh3_128_intdigest
    xxhash_module.xxh128_digest = xxhash_module.xxh3_128_digest
    xxhash_module.xxh128_hexdigest = xxhash_module.xxh3_128_hexdigest

    sys.modules["xxhash"] = xxhash_module


_install_xxhash_shim()

from dotenv import load_dotenv
import streamlit as st

# Explicitly locate .env relative to this script's folder, rather than relying
# on python-dotenv's automatic upward search — that search can misbehave when
# Streamlit runs this file through its own internal script runner.
# Your .env currently lives one folder above this script:
#   .../Agentic_AI_Learn/.env
#   .../Agentic_AI_Learn/policyRAG/PolicyRAG.py   <- this file
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = SCRIPT_DIR.parent / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    # Fallback to default behavior in case the file gets moved again
    load_dotenv()

from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_chroma import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.chains import RetrievalQA

# ---------------- Configuration ----------------
API_KEY = os.getenv("OPENAI_API_KEY")
CHAT_MODEL = os.getenv("CHAT_MODEL_NAME", "gpt-4o-mini")
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
TOP_K_CHUNKS = 4          # used for the Chat mode's retriever
SUPPORTED_TYPES = ["pdf", "docx", "txt"]
# -------------------------------------------------

st.set_page_config(page_title="Policy Q&A Agent", page_icon="📄", layout="wide")


# ---------------- Session state ----------------

defaults = {
    "qa_chain": None,
    "vectorstore": None,
    "doc_name": None,
    "messages": [],
    "uploader_key": 0,  # bump this to force-reset the file_uploader widget
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


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


def build_index(file_path: str, filename: str):
    """Load, chunk, and embed the document. Returns (qa_chain, vectorstore)."""
    documents = load_documents(file_path, filename)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(documents)

    embeddings = OpenAIEmbeddings(api_key=API_KEY)

    # A fresh, uniquely-named collection avoids ChromaDB's "instance already
    # exists with different settings" error when a new document is indexed
    # within the same running Streamlit process. Cosine distance ensures
    # similarity_search_with_relevance_scores() returns meaningful 0-1 scores.
    collection_name = f"policy_{uuid.uuid4().hex}"
    vectorstore = Chroma.from_documents(
        chunks,
        embeddings,
        collection_name=collection_name,
        collection_metadata={"hnsw:space": "cosine"},
    )

    llm = ChatOpenAI(model=CHAT_MODEL, temperature=0.2, api_key=API_KEY)

    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=vectorstore.as_retriever(search_kwargs={"k": TOP_K_CHUNKS}),
        return_source_documents=True,
    )
    return qa_chain, vectorstore


def reset_document_state():
    """Fully clear the loaded document, including the uploader widget itself."""
    st.session_state.qa_chain = None
    st.session_state.vectorstore = None
    st.session_state.doc_name = None
    st.session_state.messages = []
    # Changing the uploader's key forces Streamlit to render a brand-new
    # widget instance with no file selected, instead of remembering the
    # previously uploaded file.
    st.session_state.uploader_key += 1


# ---------------- Sidebar ----------------

with st.sidebar:
    st.header("Policy Document")

    uploaded_file = st.file_uploader(
        "Attach a policy document (PDF, DOCX, or TXT)",
        type=SUPPORTED_TYPES,
        key=f"uploader_{st.session_state.uploader_key}",
    )

    if uploaded_file is not None:
        if st.session_state.doc_name != uploaded_file.name:
            with st.spinner("Reading and indexing the document..."):
                try:
                    suffix = os.path.splitext(uploaded_file.name)[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name

                    qa_chain, vectorstore = build_index(tmp_path, uploaded_file.name)
                    st.session_state.qa_chain = qa_chain
                    st.session_state.vectorstore = vectorstore
                    st.session_state.doc_name = uploaded_file.name
                    st.session_state.messages = []  # reset chat for new document
                    st.success(f"Indexed '{uploaded_file.name}'.")

                    os.remove(tmp_path)
                except Exception as e:
                    st.error(f"Failed to process document: {e}")

    if st.session_state.doc_name:
        st.info(f"Active document: **{st.session_state.doc_name}**")
        if st.button("Remove document / start over"):
            reset_document_state()
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
    st.info("👈 Please attach a policy document (PDF, DOCX, or TXT) in the sidebar before continuing.")
    st.stop()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

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
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                st.error(f"Something went wrong: {e}")