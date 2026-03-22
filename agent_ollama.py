import streamlit as st
import secrets
import json
from agent import chatbot

st.set_page_config(page_title="Sanskrit Heritage Chatbot", layout="wide")
st.title("Sanskrit Heritage Chatbot")

if "session_id" not in st.session_state:
    st.session_state.session_id = secrets.token_urlsafe(16)

user_id = "streamlit_user"

prompt = st.text_area("Enter your query:", height=100)

if st.button("Ask"):
    st.session_state.response_chunks = []
    full_text = ""
    response_placeholder = st.empty()
    with st.spinner("Generating response..."):
        for chunk in chatbot(prompt, user_id, st.session_state.session_id):
            try:
                data = json.loads(chunk)
                content = data.get("content", "")
                event = data.get("event", "")
                if event == "SessionID":
                    st.session_state.session_id = content
                elif event == "ToolParameters":
                    st.info(f"Tool called: {content}")
                elif isinstance(content, str) and content:
                    st.session_state.response_chunks.append(content)
                    full_text += content
                    response_placeholder.markdown(full_text)
            except Exception as e:
                st.error(f"Error parsing response: {e}")

# Optionally show the full response at the end
if "response_chunks" in st.session_state and st.session_state.response_chunks:
    st.subheader("Full Response")
    st.markdown("".join(st.session_state.response_chunks))