"""
Dashboard logger — writes JSON logs compatible with Elias's frontend dashboard.

Writes to arian/logs/ in two formats:
  logs/rounds/{round_id}.json  — live run logs (queries, submissions, actions)
  logs/offline/{round_id}.json — offline backtest results
  logs/index.json              — index of live rounds
  logs/offline/index.json      — index of offline backtests

Usage (live runs):
    from dashboard_logger import log_action, log_query, log_submission

    log_action(round_id, "start_round", {"map_size": "40x40"})
    log_query(round_id, seed_index=0, viewport={"x":0,"y":0,"w":15,"h":15},
              grid=[[...]], budget_remaining=49)
    log_submission(round_id, seed_index=0, result={"status": "accepted"})

Usage (offline backtests):
    from dashboard_logger import log_offline_backtest

    log_offline_backtest(round_id, round_number=2, round_score=75.3,
                         n_sims=200, seeds=[...], config={...})
"""
import json
import os
from datetime import datetime, timezone

# Write to elias/logs/ — that's where the active dashboard at localhost:5174 reads from
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_THIS_DIR, "..", "elias", "logs")
INDEX_FILE = os.path.join(LOG_DIR, "index.json")
OFFLINE_DIR = os.path.join(LOG_DIR, "offline")
OFFLINE_INDEX = os.path.join(OFFLINE_DIR, "index.json")


# ============================================================
# Live round logs (for Simulation + Run Logs tabs)
# ============================================================

def _load_index():
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"rounds": []}


def _save_index(index):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2)


def _round_file(round_id):
    return os.path.join(LOG_DIR, "rounds", f"{round_id}.json")


def _load_round(round_id):
    path = _round_file(round_id)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def _save_round(round_id, round_data):
    path = _round_file(round_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(round_data, f, indent=2)


def _ensure_round(round_id, map_width=40, map_height=40):
    index = _load_index()
    if round_id not in [r["id"] for r in index["rounds"]]:
        index["rounds"].append({
            "id": round_id,
            "started_at": _now(),
        })
        _save_index(index)

    round_data = _load_round(round_id)
    if round_data is None:
        round_data = {
            "started_at": _now(),
            "map_width": map_width,
            "map_height": map_height,
            "queries": [],
            "submissions": [],
            "actions": [],
        }
        _save_round(round_id, round_data)
    return round_data


def log_action(round_id, action, details=None, map_width=40, map_height=40):
    """Log a pipeline action (fetch, build_prediction, error, etc.)."""
    round_data = _ensure_round(round_id, map_width, map_height)
    round_data["actions"].append({
        "timestamp": _now(),
        "action": action,
        "details": details or {},
    })
    _save_round(round_id, round_data)


def log_query(round_id, seed_index, viewport, grid, budget_remaining,
              settlements=None, map_width=40, map_height=40):
    """Log a simulate viewport query."""
    round_data = _ensure_round(round_id, map_width, map_height)
    entry = {
        "timestamp": _now(),
        "seed_index": seed_index,
        "viewport": viewport,
        "grid": grid,
        "budget_remaining": budget_remaining,
    }
    if settlements:
        entry["settlements"] = settlements
    round_data["queries"].append(entry)
    _save_round(round_id, round_data)


def log_submission(round_id, seed_index, result, map_width=40, map_height=40):
    """Log a prediction submission."""
    round_data = _ensure_round(round_id, map_width, map_height)
    round_data["submissions"].append({
        "timestamp": _now(),
        "seed_index": seed_index,
        "result": result,
    })
    _save_round(round_id, round_data)


def log_prediction(round_id, seed_index, prediction, map_width=40, map_height=40):
    """Log the prediction tensor (for visualization in dashboard)."""
    round_data = _ensure_round(round_id, map_width, map_height)
    round_data["actions"].append({
        "timestamp": _now(),
        "action": "build_prediction",
        "details": {
            "seed_index": seed_index,
            "prediction": prediction if isinstance(prediction, list) else prediction.tolist(),
        },
    })
    _save_round(round_id, round_data)


# ============================================================
# Offline backtest logs (for Offline tab)
# ============================================================

def _load_offline_index():
    if os.path.exists(OFFLINE_INDEX):
        try:
            with open(OFFLINE_INDEX) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"backtests": []}


def _save_offline_index(index):
    os.makedirs(OFFLINE_DIR, exist_ok=True)
    with open(OFFLINE_INDEX, "w") as f:
        json.dump(index, f, indent=2)


def log_offline_backtest(round_id, round_number, round_score, n_sims,
                         seeds, config=None, label=None):
    """
    Log an offline backtest result.

    seeds: list of dicts with keys:
        seed_index, score, initial_grid, prediction (argmax H×W),
        ground_truth (argmax H×W), per_class_counts (optional)
    """
    bt_id = label or round_id
    timestamp = _now()

    # Save full backtest data
    data = {
        "round_id": round_id,
        "round_number": round_number,
        "timestamp": timestamp,
        "n_sims": n_sims,
        "round_score": round_score,
        "seeds": seeds,
    }
    if config:
        data["config"] = config

    filepath = os.path.join(OFFLINE_DIR, f"{bt_id}.json")
    os.makedirs(OFFLINE_DIR, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    # Update index
    index = _load_offline_index()
    entry = {
        "id": bt_id,
        "round_id": round_id,
        "round_number": round_number,
        "timestamp": timestamp,
        "round_score": round_score,
        "n_sims": n_sims,
    }
    if config:
        entry["config"] = config

    # Replace existing entry with same id, or append
    index["backtests"] = [b for b in index["backtests"] if b.get("id") != bt_id]
    index["backtests"].append(entry)
    _save_offline_index(index)

    print(f"  [log] Offline backtest saved: {bt_id} (score={round_score:.1f})")


def _now():
    return datetime.now(timezone.utc).isoformat()
