import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from solve import predict

app = FastAPI(title="Challenge 3")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

LOG_FILE = os.path.join(os.path.dirname(__file__), "requests.jsonl")


@app.get("/")
def health():
    return {"status": "ok", "challenge": 3}


@app.get("/api")
def info():
    return {"status": "ok", "challenge": 3}


@app.post("/predict")
async def predict_endpoint(request: Request):
    body = await request.json()
    t0 = time.time()
    result = predict(body)
    elapsed = time.time() - t0

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps({"ts": t0, "elapsed": elapsed, "request": body, "response": result}) + "\n")

    return JSONResponse(content=result)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4003)
