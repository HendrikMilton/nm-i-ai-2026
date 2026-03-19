"""
API client for Astar Island.
Handles authentication, fetching round data, and submitting predictions.
"""
import os
import requests
import numpy as np

BASE_URL = "https://api.ainm.no/astar-island"


def _headers():
    token = os.environ["AINM_TOKEN"]
    return {"Authorization": f"Bearer {token}"}


def get_round(round_id: str) -> dict:
    """Fetch round details including initial_states for all seeds."""
    resp = requests.get(f"{BASE_URL}/rounds/{round_id}", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def get_active_round() -> dict | None:
    """Return the first active round, or None.
    GET /rounds is a public list endpoint — no query budget consumed.
    """
    resp = requests.get(f"{BASE_URL}/rounds", headers=_headers())
    resp.raise_for_status()
    rounds = resp.json()
    for r in rounds:
        if r["status"] == "active":
            return r
    return None


def submit_prediction(round_id: str, seed_index: int, prediction: np.ndarray) -> dict:
    """
    Submit a H×W×6 prediction tensor for one seed.
    prediction: numpy array shape (H, W, 6), values in [0,1], each row sums to 1.
    """
    payload = {
        "round_id": round_id,
        "seed_index": seed_index,
        "prediction": prediction.tolist(),
    }
    resp = requests.post(f"{BASE_URL}/submit", json=payload, headers=_headers())
    resp.raise_for_status()
    return resp.json()
