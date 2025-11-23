import os
import httpx
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Configuration from environment variables
SERVICE_INSTANCE_URL = os.getenv("YOUR_INSTANCE_URL", "https://api.example.com")
IAM_API_KEY = os.getenv("YOUR_IBM_CLOUD_API_KEY", "your_api_key")
DEFAULT_AGENT_ID = os.getenv("YOUR_AGENT_ID", "your_agent_id")

class ChatRequest(BaseModel):
    message: str
    agent_id: str = DEFAULT_AGENT_ID
    thread_id: str | None = None  # Optional: continue a conversation

async def get_bearer_token(api_key: str) -> str:
    """Generates a Bearer token from the IBM Cloud API Key."""
    token_url = "https://iam.cloud.ibm.com/identity/token"
    data = {
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": api_key
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data, headers=headers)
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            raise HTTPException(status_code=response.status_code, detail="Could not generate IAM token")
        


async def _extract_agent_message_from_run(run_json):
    """
    Try to find a textual agent message inside the run JSON.
    This performs a shallow recursive search for common keys.
    """
    def find_message(obj):
        if isinstance(obj, dict):
            # common conversational structure
            if obj.get("role") == "assistant":
                # content can be string or nested dict
                content = obj.get("content") or obj.get("message") or obj.get("text")
                if isinstance(content, str):
                    return content
                # if content is nested, search inside it
                if isinstance(content, (dict, list)):
                    return find_message(content)
            # direct keys often used by APIs
            for k in ("message", "messages", "content", "output", "text", "result"):
                if k in obj:
                    v = obj[k]
                    if isinstance(v, str):
                        return v
                    candidate = find_message(v)
                    if candidate:
                        return candidate
            # fallback: search all values
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
        
# ...existing code...
async def _fetch_run_and_extract_message(run_id: str, headers: dict, max_wait_seconds: int = 120, poll_interval: float = 1.0):
    """
    Poll the orchestrate run until its status is not 'running' or until timeout.
    Returns (agent_message, run_json) on success, or (None, error_dict) on failure/timeout.
    """
    run_url = f"{SERVICE_INSTANCE_URL}/v1/orchestrate/runs/{run_id}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        elapsed = 0.0
        while True:
            resp = await client.get(run_url, headers=headers)
            if resp.status_code != 200:
                return None, {"error": True, "status_code": resp.status_code, "detail": resp.text}
            run_json = resp.json()

            # Status keys vary by APIs; check common ones
            status = None
            if isinstance(run_json, dict):
                status = run_json.get("status") or run_json.get("state") or run_json.get("run_status")

            # Treat missing status as non-running (attempt to extract message)
            if not status or (isinstance(status, str) and status.lower() != "running"):
                message = await _extract_agent_message_from_run(run_json)
                return message, run_json

            # Still running -> check timeout
            if elapsed >= max_wait_seconds:
                return None, {
                    "error": True,
                    "status": "timeout",
                    "detail": f"Run {run_id} still running after {max_wait_seconds}s",
                    "last_run": run_json
                }

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
# ...existing code...

@app.post("/chat")
async def chat_with_agent(request: ChatRequest):
    """
    Endpoint to send a message to a watsonx Orchestrate agent and receive a response.
    """
    token = await get_bearer_token(IAM_API_KEY)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "IAM-API_KEY": IAM_API_KEY
    }
    orchestrate_url = f"{SERVICE_INSTANCE_URL}/v1/orchestrate/runs?stream=false"

    payload = {
        "message": {
            "role": "user",
            "content": request.message
        },
        "agent_id": request.agent_id,
    }
    
    # **FIX:** Only include thread_id in the payload if it is provided by the user
    if request.thread_id:
        payload["thread_id"] = request.thread_id
    # If thread_id is None, the API will create a new thread and return its ID in the response

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(orchestrate_url, json=payload, headers=headers)

        if response.status_code == 200:
            resp_json = response.json()
            run_id = resp_json.get("run_id") or resp_json.get("runId")
            agent_message = None
            run_details = None
            if run_id:
                agent_message, run_details = await _fetch_run_and_extract_message(run_id, headers)
            return {
                "orchestrate_response": resp_json,
                "agent_message": agent_message,
                "run_details": run_details
            }
        else:
            # Re-raise the IBM error details in the FastAPI response for clarity
            error_detail = response.json() if response.text else "Unknown error from Orchestrate API"
            print(f"Error response: {response.text}")
            raise HTTPException(status_code=response.status_code, detail=error_detail)




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
