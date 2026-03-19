"""FastAPI wrapper for Tripletex AI agent. DO NOT MODIFY — all logic goes in solve.py."""

from fastapi import FastAPI, Request, Header
from solve import solve
import os

app = FastAPI(title="Tripletex AI Agent")

API_KEY = os.environ.get("API_KEY", "")


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/solve")
async def solve_endpoint(request: Request, authorization: str = Header(default="")):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        return {"error": "unauthorized"}, 401

    body = await request.json()
    result = await solve(body)
    return result
