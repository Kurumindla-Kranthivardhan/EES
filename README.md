# watsonx Orchestrate — Streamlit Chat (Employee Engagement Survey)

Small Streamlit app that forwards user messages to a watsonx Orchestrate agent, saves the thread on first interaction, polls the run until completion (max 60s) and shows the agent reply. Conversation is kept in session memory and cleared on full page reload.

## Quick start
1. Set environment variables:
   - YOUR_INSTANCE_URL — your Orchestrate instance base URL
   - YOUR_IBM_CLOUD_API_KEY — IBM Cloud API key
   - YOUR_AGENT_ID — default agent id to use internally

2. Run locally:
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

3. Or build/run with Docker (pass secrets as env or build-args).

## List Agents (use API or UI)
Instead of providing curl command examples, use the Orchestrate web UI for manual inspection, or use a short Python httpx snippet to list agents programmatically. The code below shows how to obtain an IAM bearer token and call the Orchestrate "agents list" endpoint (GET /v1/orchestrate/agents). Replace placeholders with your values.

Python example (httpx):
```python

import os
import httpx

TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
INSTANCE_URL = os.getenv("YOUR_INSTANCE_URL")
API_KEY = os.getenv("YOUR_IBM_CLOUD_API_KEY")

def get_bearer_token(api_key: str) -> str:
    data = {
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": api_key
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    with httpx.Client() as client:
        r = client.post(TOKEN_URL, data=data, headers=headers, timeout=30.0)
        r.raise_for_status()
        return r.json().get("access_token")

def list_agents():
    token = get_bearer_token(API_KEY)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    agents_url = f"{INSTANCE_URL}/v1/orchestrate/agents"
    with httpx.Client() as client:
        resp = client.get(agents_url, headers=headers, timeout=30.0)
        resp.raise_for_status()
        return resp.json()

if __name__ == "__main__":
    agents = list_agents()
    # typical fields: id, name, status, created_at (inspect JSON to confirm)
    print(agents)
```

Notes:
- The exact agents list endpoint path can vary by Orchestrate API version; if GET /v1/orchestrate/agents returns 404, consult your instance API docs or the Orchestrate UI to confirm the exact path.
- The response is JSON; inspect keys to find agent id and name. Use id to start runs or import mappings.

## Importing / deploying agents from YAML
- Recommended: use the Orchestrate web UI Import feature to upload agent YAML exports (manual one-off).
- For automation: upload YAML via the instance API (POST file upload). After import, configure any external connectors or secrets referenced by the agent (these are not part of YAML for security).
- After import, verify agent appears in the UI or via the agents-list API.

## Example: start run and poll for result (concept)
- POST to: {YOUR_INSTANCE_URL}/v1/orchestrate/runs?stream=false with JSON:
  { "message": {"role":"user","content":"..."} , "agent_id": "<AGENT_ID>" }
- From response read run_id and thread_id.
- Poll GET {YOUR_INSTANCE_URL}/v1/orchestrate/runs/{run_id} until status != "running", then extract agent message from the returned JSON.

## Troubleshooting
- 401/403: check API key and token retrieval.
- No agents listed: ensure you are using the correct instance URL and have sufficient permissions.
- Long-running runs: increase polling timeout when debugging.

## Security
- Never commit API keys to version control. Use environment variables or a secrets manager.

## Useful links

- https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=api-getting-endpoint
- https://developer.watson-orchestrate.ibm.com/apis/orchestrate-agent/get-orchestrate-assistant-run
- https://developer.ibm.com/tutorials/getting-started-with-watsonx-orchestrate/

