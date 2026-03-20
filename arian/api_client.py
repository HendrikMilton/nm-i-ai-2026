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


def get_my_rounds() -> list[dict]:
    """Return all rounds with team scores, rank, budget info."""
    resp = requests.get(f"{BASE_URL}/my-rounds", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def get_analysis(round_id: str, seed_index: int) -> dict:
    """
    Fetch post-round analysis: our prediction vs ground truth.
    Only available for completed/scoring rounds.
    Returns {prediction, ground_truth, score, width, height, initial_grid}.
    """
    resp = requests.get(
        f"{BASE_URL}/analysis/{round_id}/{seed_index}",
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()


def get_budget() -> dict:
    """Check remaining query budget for active round."""
    resp = requests.get(f"{BASE_URL}/budget", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def simulate_viewport(
    round_id: str, seed_index: int,
    vx: int, vy: int, vw: int = 15, vh: int = 15,
) -> dict:
    """
    Observe one stochastic simulation via viewport. Costs 1 query.
    Returns {grid, settlements, viewport, queries_used, queries_max}.
    """
    resp = requests.post(f"{BASE_URL}/simulate", headers=_headers(), json={
        "round_id": round_id,
        "seed_index": seed_index,
        "viewport_x": vx,
        "viewport_y": vy,
        "viewport_w": vw,
        "viewport_h": vh,
    })
    resp.raise_for_status()
    return resp.json()
