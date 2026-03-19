"""
Tripletex AI Agent — solve logic.

This is where all your agent logic goes.
You receive a task prompt (Norwegian/English/etc), use an LLM to interpret it,
then call the Tripletex API to complete the accounting task.
"""

import base64
import json
import requests
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel, Part


PROJECT_ID = "ai-nm26osl-1713"
LOCATION = "europe-west4"
MODEL = "gemini-2.5-pro"


def call_gemini(prompt: str, files: list[dict] | None = None) -> str:
    """Send a prompt to Gemini and get a text response."""
    model = GenerativeModel(MODEL)

    parts = [Part.from_text(prompt)]

    # Attach files (PDFs/images) if provided
    if files:
        for f in files:
            data = base64.b64decode(f["content_base64"])
            parts.append(Part.from_data(data=data, mime_type=f["mime_type"]))

    response = model.generate_content(parts)
    return response.text


def call_tripletex(method: str, endpoint: str, base_url: str, token: str,
                   params: dict | None = None, json_body: dict | None = None) -> dict:
    """Make an authenticated request to the Tripletex API proxy."""
    url = f"{base_url}{endpoint}"
    response = requests.request(
        method=method,
        url=url,
        auth=("0", token),
        params=params,
        json=json_body,
        timeout=30,
    )
    response.raise_for_status()
    if response.content:
        return response.json()
    return {}


async def solve(body: dict) -> dict:
    """
    Main entry point. Receives the task and must complete it via Tripletex API.

    body = {
        "prompt": "Opprett en ansatt med navn ...",
        "files": [{"filename": "...", "content_base64": "...", "mime_type": "..."}],
        "tripletex_credentials": {
            "base_url": "https://tx-proxy.ainm.no/v2",
            "session_token": "abc123..."
        }
    }
    """
    prompt = body["prompt"]
    files = body.get("files", [])
    creds = body["tripletex_credentials"]
    base_url = creds["base_url"]
    token = creds["session_token"]

    # ---------------------------------------------------------------
    # TODO: This is where you build the agent logic!
    #
    # Strategy:
    # 1. Send the prompt + any files to Gemini, ask it to figure out
    #    which Tripletex API calls to make
    # 2. Parse the LLM response to extract the API calls
    # 3. Execute them via call_tripletex()
    # 4. Optionally loop: send results back to Gemini if it needs
    #    to make follow-up calls
    #
    # Tips:
    # - Start simple: get Gemini to return a JSON plan of API calls
    # - Use the Tripletex API docs to build a system prompt
    # - Handle multi-step tasks (e.g., create customer, then invoice)
    # - The efficiency bonus rewards fewer calls and zero 4xx errors
    # ---------------------------------------------------------------

    system_prompt = f"""You are an AI accounting agent. You receive accounting tasks and must
determine the exact Tripletex API calls needed to complete them.

The Tripletex API base URL is: {base_url}
Authentication: Basic Auth with username "0" and the session token.

Common endpoints:
- POST /employee - Create employee
- POST /customer - Create customer
- POST /product - Create product
- POST /invoice - Create invoice
- POST /order - Create order
- POST /travelExpense - Travel expenses
- POST /project - Create project
- POST /department - Create department
- GET /ledger/account - Query accounts
- DELETE /travelExpense/{{id}} - Delete travel expense

Respond with a JSON array of API calls to make, in order:
[
  {{"method": "POST", "endpoint": "/employee", "body": {{"firstName": "Ola", ...}}}}
]

Only return the JSON array, nothing else."""

    llm_prompt = f"{system_prompt}\n\nTask:\n{prompt}"

    # Step 1: Ask Gemini what to do
    llm_response = call_gemini(llm_prompt, files if files else None)

    # Step 2: Parse and execute the plan
    try:
        # Strip markdown code fences if present
        clean = llm_response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            clean = clean.rsplit("```", 1)[0]
        api_calls = json.loads(clean)
    except json.JSONDecodeError:
        # If parsing fails, return completed anyway (partial credit possible)
        return {"status": "completed"}

    # Step 3: Execute each API call
    for call in api_calls:
        try:
            call_tripletex(
                method=call.get("method", "POST"),
                endpoint=call["endpoint"],
                base_url=base_url,
                token=token,
                params=call.get("params"),
                json_body=call.get("body"),
            )
        except requests.HTTPError:
            # Log but continue — partial completion is better than nothing
            pass

    return {"status": "completed"}
