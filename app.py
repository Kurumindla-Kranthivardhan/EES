import os
import time
import httpx
import streamlit as st
from typing import Any, Dict, Optional
from datetime import datetime

# Configuration from environment variables
SERVICE_INSTANCE_URL = os.getenv("YOUR_INSTANCE_URL", "https://api.example.com")
IAM_API_KEY = os.getenv("YOUR_IBM_CLOUD_API_KEY", "")
DEFAULT_AGENT_ID = os.getenv("YOUR_AGENT_ID", "your_agent_id")

TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"


def get_bearer_token_sync(api_key: str) -> str:
    data = {
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": api_key
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    with httpx.Client() as client:
        resp = client.post(TOKEN_URL, data=data, headers=headers, timeout=30.0)
        resp.raise_for_status()
        return resp.json().get("access_token")


def _extract_agent_message_from_run(run_json: Any) -> Optional[str]:
    def find_message(obj):
        if isinstance(obj, dict):
            if obj.get("role") == "assistant":
                content = obj.get("content") or obj.get("message") or obj.get("text")
                if isinstance(content, str):
                    return content
                if isinstance(content, (dict, list)):
                    return find_message(content)
            for k in ("message", "messages", "content", "output", "text", "result"):
                if k in obj:
                    v = obj[k]
                    if isinstance(v, str):
                        return v
                    candidate = find_message(v)
                    if candidate:
                        return candidate
            for v in obj.values():
                candidate = find_message(v)
                if candidate:
                    return candidate
        elif isinstance(obj, list):
            for item in obj:
                candidate = find_message(item)
                if candidate:
                    return candidate
        return None

    return find_message(run_json)


def fetch_run_and_extract_message_sync(run_id: str, headers: Dict[str, str], max_wait_seconds: int = 60,
                                       poll_interval: float = 0.5):
    run_url = f"{SERVICE_INSTANCE_URL}/v1/orchestrate/runs/{run_id}"
    with httpx.Client(timeout=30.0) as client:
        elapsed = 0.0
        while True:
            resp = client.get(run_url, headers=headers)
            if resp.status_code != 200:
                return None, {"error": True, "status_code": resp.status_code, "detail": resp.text}
            run_json = resp.json()
            status = None
            if isinstance(run_json, dict):
                status = run_json.get("status") or run_json.get("state") or run_json.get("run_status")
                if isinstance(status, str):
                    status = status.lower()
            if not status or status != "running":
                message = _extract_agent_message_from_run(run_json)
                return message, run_json
            if elapsed >= max_wait_seconds:
                return None, {"error": True, "status": "timeout",
                              "detail": f"Run {run_id} still running after {max_wait_seconds}s",
                              "last_run": run_json}
            time.sleep(poll_interval)
            elapsed += poll_interval


def start_orchestrate_run_sync(message: str, agent_id: str, thread_id: Optional[str], token: str):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}
    if IAM_API_KEY:
        headers["IAM-API_KEY"] = IAM_API_KEY
    orchestrate_url = f"{SERVICE_INSTANCE_URL}/v1/orchestrate/runs?stream=false"
    payload = {
        "message": {"role": "user", "content": message},
        "agent_id": agent_id,
    }
    if thread_id:
        payload["thread_id"] = thread_id
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(orchestrate_url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json(), headers


# Streamlit UI
st.set_page_config(page_title="watsonx Orchestrate — Chat", layout="centered")

# Use configured agent id internally (do not display)
agent_id = DEFAULT_AGENT_ID

# Session-only conversation (cleared on full page reload)
if "initialized" not in st.session_state:
    st.session_state["history"] = []
    st.session_state["thread_id"] = None
    st.session_state["message_input"] = ""
    st.session_state["last_error"] = ""
    st.session_state["initialized"] = True

# Show thread id if present
if st.session_state.get("thread_id"):
    st.info(f"Thread ID: {st.session_state['thread_id']}")

# Display any last error from callback
if st.session_state.get("last_error"):
    st.error(st.session_state["last_error"])
    st.session_state["last_error"] = ""
st.title("watsonx Orchestrate Chat with Agent(Employee Engagement Survey)")
# Conversation area (oldest first so newest appears at bottom)
st.header("Conversation")
history = st.session_state.get("history", [])
for item in history:
    st.markdown(f"**You ({item.get('timestamp')}):**")
    st.write(item.get("user_message"))
    assistant_text = item.get("agent_message") or "_No agent message available_"
    st.markdown("**Agent:**")
    st.write(assistant_text)

# Anchor to bottom so last message is visible
st.markdown("<div id='chat_end'></div><script>var el=document.getElementById('chat_end'); if(el) el.scrollIntoView();</script>", unsafe_allow_html=True)

# Input area (stays at bottom)
st.text_area("Message", height=120, key="message_input", value=st.session_state.get("message_input", ""))


def _send_callback():
    msg = st.session_state.get("message_input", "").strip()
    if not msg:
        st.session_state["last_error"] = "Please enter a message."
        return

    try:
        token = get_bearer_token_sync(IAM_API_KEY)
    except Exception:
        st.session_state["last_error"] = "Failed to obtain IAM token."
        return

    try:
        orchestrate_resp, headers = start_orchestrate_run_sync(msg, agent_id, st.session_state.get("thread_id"), token)
    except Exception:
        st.session_state["last_error"] = "Failed to start run."
        return

    returned_thread_id = orchestrate_resp.get("thread_id") or orchestrate_resp.get("threadId")
    if returned_thread_id and not st.session_state.get("thread_id"):
        st.session_state["thread_id"] = returned_thread_id

    run_id = orchestrate_resp.get("run_id") or orchestrate_resp.get("runId")
    agent_message = None
    if run_id:
        agent_message, _ = fetch_run_and_extract_message_sync(run_id, headers, max_wait_seconds=5, poll_interval=0.5)

    interaction = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "thread_id": st.session_state.get("thread_id"),
        "run_id": run_id,
        "user_message": msg,
        "agent_message": agent_message
    }
    st.session_state["history"].append(interaction)

    # clear the text area (safe because this is inside callback)
    st.session_state["message_input"] = ""


st.button("Send", on_click=_send_callback)

# Keep UI minimal: no run details shown