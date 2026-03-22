import streamlit as st
import secrets
import json
from agent import chatbot  # Make sure agent.py is in the same directory or PYTHONPATH

# Page configuration must be the first Streamlit command
st.set_page_config(page_title="Sanskrit Heritage Chatbot", layout="wide")

# Inject custom CSS for larger font size only
st.markdown(
    """
    <style>
    html, body, [class*="css"]  {
        font-size: 24px !important;
    }
    .stMarkdown {
        font-size: 26px !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("Sanskrit Heritage Chatbot")

if "session_id" not in st.session_state:
    st.session_state.session_id = secrets.token_urlsafe(16)

user_id = "streamlit_user"

prompt = st.text_area("Enter your query:", height=100)

# ...existing code...
if st.button("Ask"):
    st.session_state.response_chunks = []
    st.session_state.api_debug = None  # Store API responses for debugging
    with st.spinner("Generating response..."):
        for chunk in chatbot(prompt, user_id, st.session_state.session_id):
            try:
                # Split chunk by newlines and parse each JSON object separately
                for line in chunk.strip().split('\n'):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except Exception as e:
                        st.error(f"Error parsing line: {e}")
                        continue
                    content = data.get("content", "")
                    event = data.get("event", "")
                    if event == "tool_response" and content:
                        try:
                            parsed = json.loads(content)
                            st.session_state.api_debug = parsed.get("debug_api")
                            content = parsed.get("results")
                            # immediately log the API responses so the user sees them
                            if st.session_state.api_debug:
                                st.subheader("API Responses (Debug)")
                                st.json(st.session_state.api_debug)
                        except Exception as e:
                            st.error(f"Error parsing heritage_lookup response: {e}")
                    if event == "SessionID":
                        st.session_state.session_id = content
                    elif event == "ToolParameters":
                        st.info(f"Tool called: {content}")
                    else:
                        st.session_state.response_chunks.append(str(content))
                        st.markdown(str(content))
            except Exception as e:
                st.error(f"Error parsing response: {e}")
# ...existing code...

# Optionally show the full response at the end
if "response_chunks" in st.session_state and st.session_state.response_chunks:
    st.subheader("Full Response")
    full_response = "\n".join([chunk for chunk in st.session_state.response_chunks if chunk is not None])
    st.markdown(full_response)

# Show API debug info if available
if "api_debug" in st.session_state and st.session_state.api_debug:
    st.subheader("API Responses (Debug)")
    st.json(st.session_state.api_debug)