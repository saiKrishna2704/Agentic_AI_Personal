import json
from urllib import response
import requests
import streamlit as st

Backend_URL = "http://127.0.0.1:8000/stream"  # Replace with your FastAPI backend URL
st.set_page_config(page_title="Agentic AI Streaming", page_icon="🤖", layout="wide")
st.title("Live AI Chat Stream")
st.write("Ask your questions and get live responses from the AI model!")
if "messages" not in st.session_state:
    st.session_state.messages = []
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
prompt = st.chat_input("Type your message here...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    with st.chat_message("assistant"):
        response_box = st.empty()
        full_response = ""
        try:
            response = requests.post(
                f"{Backend_URL}/chat/stream",
                json={"messages": st.session_state.messages},
                stream=True,
                timeout=60,
            )
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith(b"data:"):
                    data = line[len(b"data:"):].strip()
                    if data == b"[DONE]":
                        break
                    try:
                        data_str = data.decode("utf-8")
                        chunk = json.loads(data_str)
                        token = chunk.get("content", "")
                        full_response += token
                        response_box.markdown(full_response + "▌")
                    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                        continue
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            response_box.markdown(full_response)
        except requests.exceptions.RequestException as e:
            st.error(f"Error: {e}")
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")