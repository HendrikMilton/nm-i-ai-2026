import json
import os
import time
import urllib.request
import urllib.error

BASE_URL = "https://api.ainm.no/astar-island"

# Load token from .env file if present
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

TOKEN = os.environ.get("AINM_TOKEN", "")


def _headers():
    h = {"Content-Type": "application/json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def call_api(method, path, body=None):
    """Generic API caller. Returns parsed JSON response."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"API {e.code}: {error_body}") from e


# --- Public endpoints ---

def get_rounds():
    """List all rounds."""
    return call_api("GET", "/rounds")


def get_round(round_id):
    """Get round details + initial states."""
    return call_api("GET", f"/rounds/{round_id}")


def get_leaderboard():
    """Get the leaderboard."""
    return call_api("GET", "/leaderboard")


# --- Team endpoints ---

def get_budget():
    """Get query budget for the active round."""
    return call_api("GET", "/budget")


def get_my_rounds():
    """Get rounds with your scores, rank, budget."""
    return call_api("GET", "/my-rounds")


def get_my_predictions(round_id):
    """Get your predictions with argmax/confidence."""
    return call_api("GET", f"/my-predictions/{round_id}")


def get_analysis(round_id, seed_index):
    """Post-round ground truth comparison."""
    return call_api("GET", f"/analysis/{round_id}/{seed_index}")


def simulate(round_id, seed_index, viewport_x, viewport_y, viewport_w=15, viewport_h=15):
    """Run a simulation query through a viewport. Returns terrain grid + settlements."""
    return call_api("POST", "/simulate", {
        "round_id": round_id,
        "seed_index": seed_index,
        "viewport_x": viewport_x,
        "viewport_y": viewport_y,
        "viewport_w": viewport_w,
        "viewport_h": viewport_h,
    })


def submit(round_id, seed_index, prediction):
    """Submit a prediction tensor (H x W x 6). Each cell's 6 probs must sum to 1."""
    return call_api("POST", "/submit", {
        "round_id": round_id,
        "seed_index": seed_index,
        "prediction": prediction,
    })


# --- Helpers ---

def get_active_round():
    """Find the currently active round, or None."""
    for r in get_rounds():
        if r.get("status") == "active":
            return r
    return None


def uniform_prediction(width=40, height=40, n_classes=6):
    """Create a uniform prediction tensor (safe baseline)."""
    p = 1.0 / n_classes
    return [[[p] * n_classes for _ in range(width)] for _ in range(height)]


def floor_and_normalize(prediction, floor=0.01):
    """Apply probability floor and renormalize to avoid KL infinity."""
    for row in prediction:
        for cell in row:
            for i in range(len(cell)):
                cell[i] = max(cell[i], floor)
            total = sum(cell)
            for i in range(len(cell)):
                cell[i] /= total
    return prediction


def submit_all_uniform(round_id, width=40, height=40):
    """Submit uniform predictions for all 5 seeds (better than scoring 0)."""
    pred = uniform_prediction(width, height)
    results = []
    for seed_index in range(5):
        r = submit(round_id, seed_index, pred)
        results.append(r)
    return results
