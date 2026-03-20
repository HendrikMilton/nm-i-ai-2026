================================================================================================ OVERVIEW ================================================================================================
Tripletex — AI Accounting Agent
Build an AI agent that completes accounting tasks in Tripletex. You receive a task prompt (in one of 7 languages), use the Tripletex API to execute it, and get scored on correctness and efficiency.
How It Works

Submit your HTTPS endpoint URL on the platform
We provision a fresh Tripletex sandbox account
We send a randomly selected accounting task to your /solve endpoint
Your agent reads the prompt, optionally processes attached files (PDFs, images)
Your agent calls the Tripletex API via a proxy to complete the task
We verify the result field-by-field against expected values
Your score updates on the rolling leaderboard

Each submission gets a brand new Tripletex account — you always start from scratch.
Key Facts









Task types
30 different accounting tasks


Variants
56 per task (7 languages × 8 data sets)


Language
Prompts in Norwegian, English, Spanish, Portuguese, Nynorsk, German, French


Timeout
5 minutes per submission


API
Tripletex v2 REST API via authenticated proxy


Scoring
Field-by-field checks + efficiency bonus, best score per task kept


Score range
0.0 (failed) — up to 6.0 (perfect Tier 3 + best efficiency)


Files
Some tasks include PDF or image attachments



Quick Start

Build a /solve endpoint that accepts POST requests with a task prompt and Tripletex credentials
Use an LLM to interpret the Norwegian prompt and decide which API calls to make
Call the Tripletex API using the provided proxy URL and session token
Return {"status": "completed"} when done
Submit your endpoint URL at https://app.ainm.no/submit/tripletex

Task Categories
Your agent will encounter tasks like:

Employees — Create employees, set roles, update contact info
Customers & Products — Register customers, create products
Invoicing — Create invoices, register payments, issue credit notes
Travel Expenses — Register or delete travel expense reports
Projects — Create projects linked to customers
Corrections — Delete or reverse incorrect entries
Departments — Create departments, enable accounting modules

Tasks range from simple single-API-call operations to multi-step workflows requiring several resources to be created and linked together.
================================================================================================ SANDBOX ACCOUNT ================================================================================================
Tripletex — Sandbox Account
Every team gets a free Tripletex sandbox account to explore the API and web interface before submitting to the competition.
Getting Your Sandbox

Go to the Tripletex submission page on the platform
Click "Get Sandbox Account"
Your sandbox is provisioned instantly

You'll receive:

Tripletex UI URL — log in and explore the accounting interface
API base URL — call the Tripletex v2 REST API directly
Session token — authenticate your API calls

Logging Into the Web UI

Go to https://kkpqfuj-amager.tripletex.dev
Enter the email shown on your sandbox card
Click "Forgot password" to set up your Visma Connect account (first time only)
Set a password and log in

Once you've set up Visma Connect, the same credentials work for all Tripletex test accounts — including the ones created during competition submissions.
Using the API
Authenticate with Basic Auth using 0 as username and the session token as password:
import requests

BASE_URL = "https://kkpqfuj-amager.tripletex.dev/v2"
SESSION_TOKEN = "your-session-token-here"

# List employees
response = requests.get(
f"{BASE_URL}/employee",
auth=("0", SESSION_TOKEN),
params={"fields": "id,firstName,lastName,email"}
)
print(response.json())

# Create a customer
response = requests.post(
f"{BASE_URL}/customer",
auth=("0", SESSION_TOKEN),
json={
"name": "Test Customer AS",
"email": "test@example.com",
"isCustomer": True,
}
)
print(response.json())
# curl example
curl -u "0:your-session-token-here" \
"https://kkpqfuj-amager.tripletex.dev/v2/employee?fields=id,firstName,lastName"
What You Can Do
The sandbox is a full Tripletex test environment. Use it to:

Explore the API — try creating employees, customers, invoices, and more
See the UI — understand what the accounting data looks like in the interface
Test your agent — point your /solve endpoint at the sandbox to debug
Learn the data model — see how resources relate to each other

Key Differences from Competition




Sandbox
Competition




Account
Persistent, yours to keep
Fresh account per submission


API access
Direct to Tripletex
Via authenticated proxy


Data
Accumulates over time
Starts empty each time


Scoring
None
Automated field-by-field



Tips

Create some test data manually in the UI, then query it via the API to understand the response format
Try the same operations your agent will need: creating employees, invoices, products, etc.
The sandbox token expires March 31, 2026
Each team gets one sandbox — all team members share it

================================================================================================ ENDPOINT SPEC ================================================================================================
Tripletex — Endpoint Specification
Your agent must expose a single HTTPS endpoint that accepts POST requests.
/solve Endpoint
Method: POST
Content-Type: application/json
Timeout: 300 seconds (5 minutes)
Request Format
{
"prompt": "Opprett en ansatt med navn Ola Nordmann, ola@example.org. Han skal være kontoadministrator.",
"files": [
{
"filename": "faktura.pdf",
"content_base64": "JVBERi0xLjQg...",
"mime_type": "application/pdf"
}
],
"tripletex_credentials": {
"base_url": "https://<provided-per-submission>/v2",
"session_token": "abc123..."
}
}



Field
Type
Description




prompt
string
The task in Norwegian natural language


files
array
Attachments (PDFs, images) — may be empty


files[].filename
string
Original filename


files[].content_base64
string
Base64-encoded file content


files[].mime_type
string
MIME type (application/pdf, image/png, etc.)


tripletex_credentials.base_url
string
Proxy API URL — use this instead of the standard Tripletex URL


tripletex_credentials.session_token
string
Session token for authentication



Response Format
Return this JSON when your agent has finished executing the task:
{
"status": "completed"
}
Authentication
Your agent authenticates with the Tripletex API using Basic Auth:

Username: 0 (zero)
Password: the session_token value from the request

import requests

response = requests.get(
f"{base_url}/employee",
auth=("0", session_token),
params={"fields": "id,firstName,lastName,email"}
)
API Key (Optional)
If you set an API key when submitting your endpoint, we send it as a Bearer token:
Authorization: Bearer <your-api-key>

Use this to protect your endpoint from unauthorized access.
Requirements

Endpoint must be HTTPS
Must respond within 5 minutes (300 seconds)
Must return {"status": "completed"} with HTTP 200
All Tripletex API calls must go through the provided base_url (proxy)

Tripletex API Reference
All standard Tripletex v2 endpoints are available through the proxy. Common endpoints:



Endpoint
Methods
Description




/employee
GET, POST, PUT
Manage employees


/customer
GET, POST, PUT
Manage customers


/product
GET, POST
Manage products


/invoice
GET, POST
Create and query invoices


/order
GET, POST
Manage orders


/travelExpense
GET, POST, PUT, DELETE
Travel expense reports


/project
GET, POST
Manage projects


/department
GET, POST
Manage departments


/ledger/account
GET
Query chart of accounts


/ledger/posting
GET
Query ledger postings


/ledger/voucher
GET, POST, DELETE
Manage vouchers



API Tips

Use the fields parameter to select specific fields: ?fields=id,firstName,lastName,*
Use count and from for pagination: ?from=0&count=100
POST/PUT requests take JSON body
DELETE requests use the ID in the URL path: DELETE /employee/123
List responses are wrapped: {"fullResultSize": N, "values": [...]}

================================================================================================ SCORING ================================================================================================
Tripletex — Scoring
Field-by-Field Verification (Correctness)
After your agent responds, we query the Tripletex API to verify what was created or modified. Each task has specific checks worth different point values.
Example for a "Create employee" task (max 10 points):



Check
Points




Employee found
2


Correct first name
1


Correct last name
1


Correct email
1


Administrator role assigned
5



The raw score is normalized to 0–1: correctness = points_earned / max_points (e.g., 8/10 = 0.8).
Tier Multiplier
Each task has a difficulty tier that multiplies your correctness score:



Tier
Multiplier
Example tasks




Tier 1
×1
Create employee, create customer


Tier 2
×2
Create invoice, register payment


Tier 3
×3
Complex multi-step workflows



So a perfect score on a Tier 2 task = 1.0 × 2 = 2.0 base score.
Efficiency Bonus
If your agent achieves a perfect correctness score (1.0), you receive an efficiency bonus that can up to double your tier score.
Two factors determine the bonus:
Call efficiency — How many API calls did your agent make compared to the best known solution for this task? Fewer calls = higher bonus.
Error cleanliness — How many of your API calls resulted in 4xx errors (400, 404, 422, etc.)? Errors reduce the bonus. An agent that gets it right without trial-and-error is rewarded.



Scenario (Tier 2 task)
Score




Failed all checks
0.0


80% of checks passed
1.6


Perfect, but many errors and extra calls
~2.1


Perfect, efficient, a few errors
~2.6


Perfect, best-in-class efficiency, zero errors
4.0



The efficiency bonus only applies to perfect submissions. Non-perfect submissions score correctness × tier.
Efficiency benchmarks are recalculated periodically. As teams find more efficient solutions, the bar rises for everyone. Your best score per task is recalculated against current benchmarks every 12 hours.
Best Score Per Task
Your score per task is your all-time best. Bad runs never lower your score — only improvements count.

One good run is enough to lock in a score
You can always improve by submitting again
Focus on building a better agent, not grinding to recover from bad luck
Each of the 30 tasks tracks independently

Leaderboard
Total leaderboard score = sum of best scores across all task types.
The more task types your agent handles well, the higher your potential score.
Task Assignment
Each submission receives one task, weighted toward tasks you've attempted less. Over many submissions, you'll encounter all task types. Tasks are grouped into three tiers:

Tier 1 — foundational tasks (e.g., create employee, create customer, create invoice)
Tier 2 — multi-step workflows (e.g., invoice with payment, credit notes, project billing)
Tier 3 — complex scenarios (e.g., bank reconciliation from CSV, error correction in ledger, year-end closing)

Each task has 56 unique variants (7 languages × 8 data sets), so you'll rarely see the same prompt twice.
Tier Release Schedule
Tasks are released in tiers throughout the competition:

Tier 1 — open
Tier 2 — open
Tier 3 — opens early Saturday. Check this page for updates.

This gives you time to build a solid agent on simpler tasks before tackling the harder ones.
Rate Limits



Limit
Verified teams
Unverified teams




Concurrent submissions
3
1


Per task per day
10
3



================================================================================================ EXAMPLES ================================================================================================
Tripletex — Examples
Minimal /solve Endpoint
import base64
from pathlib import Path

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

@app.post("/solve")
async def solve(request: Request):
body = await request.json()
prompt = body["prompt"]
files = body.get("files", [])
creds = body["tripletex_credentials"]

    base_url = creds["base_url"]
    token = creds["session_token"]
    auth = ("0", token)
 
    for f in files:
        data = base64.b64decode(f["content_base64"])
        Path(f["filename"]).write_bytes(data)
 
    # TODO: Use an LLM to interpret the prompt and execute
    # the appropriate Tripletex API calls
 
    return JSONResponse({"status": "completed"})
Run with:
pip install fastapi uvicorn requests
uvicorn main:app --host 0.0.0.0 --port 8000
Expose locally via HTTPS for testing:
npx cloudflared tunnel --url http://localhost:8000
Tripletex API Examples
List employees
resp = requests.get(
f"{base_url}/employee",
auth=auth,
params={"fields": "id,firstName,lastName,email"}
)
employees = resp.json()["values"]
Create a customer
resp = requests.post(
f"{base_url}/customer",
auth=auth,
json={
"name": "Acme AS",
"email": "post@acme.no",
"isCustomer": True
}
)
customer_id = resp.json()["value"]["id"]
Create an invoice
today = "2026-03-03"
resp = requests.post(
f"{base_url}/invoice",
auth=auth,
json={
"invoiceDate": today,
"invoiceDueDate": today,
"customer": {"id": customer_id},
"orders": [{"id": order_id}]
}
)
Search for a specific entity
resp = requests.get(
f"{base_url}/customer",
auth=auth,
params={
"name": "Acme",
"fields": "id,name,email",
"count": 10
}
)
matches = resp.json()["values"]
Building an Effective Agent

Parse the prompt — Use an LLM to extract the task type, entity names, field values, and relationships from the Norwegian prompt
Handle files — Some tasks include PDFs with invoices, contracts, or expense reports. Decode from base64 and extract relevant data
Map to API calls — Determine which Tripletex endpoints to call and in what order. Some tasks require creating prerequisites first
Verify your work — After creating entities, query back to confirm they exist with correct values
Handle errors — Tripletex returns detailed error messages. Parse them to retry with corrections

Common Task Patterns



Pattern
Example
API Flow




Create single entity
"Create employee Ola Nordmann"
POST /employee


Create with linking
"Create invoice for customer"
GET /customer → POST /order → POST /invoice


Modify existing
"Add phone to contact"
GET /customer → PUT /customer/{id}


Delete/reverse
"Delete travel expense"
GET /travelExpense → DELETE /travelExpense/{id}


Multi-step setup
"Register payment"
POST /customer → POST /invoice → POST /payment



Common Errors



Error
Cause
Fix




401 Unauthorized
Wrong auth format
Use Basic Auth with username 0 and session token as password


404 Not Found
Wrong endpoint path
Check the Tripletex v2 API docs for correct paths


422 Validation Error
Missing required fields
Read error message — it specifies which fields are required


Empty values array
No results found
Check search parameters, try broader search


Timeout (5 min)
Agent too slow
Optimize API calls, reduce unnecessary requests



Tips

The Tripletex sandbox starts empty — you may need to create prerequisites (customer, product) before creating invoices
Use ?fields=* to see all available fields on an entity
Some tasks require enabling modules first (e.g., department accounting)
Norwegian characters (æ, ø, å) work fine in API requests — send as UTF-8
All API calls through the proxy are logged — use them for debugging in the submissions view
Prompts come in 7 languages (nb, en, es, pt, nn, de, fr) — your agent should handle all of them

Optimizing for Efficiency
Your score can go above 1.0 if you achieve perfect correctness with minimal API calls and zero errors. Higher-tier tasks have higher score ceilings (up to 6.0 for Tier 3). Tips:

Plan before calling — Parse the prompt fully before making API calls. Understand what needs to be created/modified before starting
Avoid trial-and-error — Every 4xx error (400, 404, 422) reduces your efficiency bonus. Validate inputs before sending
Minimize GET calls — Don't fetch entities you don't need. If you created something, you already know its ID from the response
Batch where possible — Some Tripletex endpoints accept lists. Use them instead of multiple individual calls
Read error messages — If a call fails, the Tripletex error message tells you exactly what's wrong. Fix it in one retry, not several
