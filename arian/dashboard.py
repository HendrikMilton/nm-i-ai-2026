"""
Astar Island Dashboard — local web server.

Collects data from the API + local observation caches and serves
an interactive dashboard for analyzing game state and metrics.

Usage:
    AINM_TOKEN=<token> python dashboard.py [--port 8050]
    # Then open http://localhost:8050
"""
import http.server
import json
import os
import sys
import glob
import traceback
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Add current dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import get_my_rounds, get_analysis, get_round, get_active_round, get_budget

PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8050
DATA_DIR = os.path.dirname(os.path.abspath(__file__))


def collect_data() -> dict:
    """Collect all available data from API + local files."""
    data = {
        "rounds": [],
        "observations": {},
        "analysis": {},
        "initial_states": {},
        "api_error": None,
    }

    # --- Load local observation caches ---
    for fpath in sorted(glob.glob(os.path.join(DATA_DIR, "observations*.json"))):
        try:
            with open(fpath) as f:
                cache = json.load(f)
            rid = cache.get("round_id", os.path.basename(fpath))
            data["observations"][rid] = cache.get("seeds", {})
            print(f"  Loaded observations: {os.path.basename(fpath)} ({rid[:8]}...)")
        except Exception as e:
            print(f"  Failed to load {fpath}: {e}")

    # --- Fetch from API ---
    token = os.environ.get("AINM_TOKEN", "")
    if not token:
        # Try to auto-detect from observe_and_resubmit.py
        try:
            obs_file = os.path.join(DATA_DIR, "observe_and_resubmit.py")
            with open(obs_file) as f:
                for line in f:
                    if line.strip().startswith("TOKEN"):
                        token = line.split('"')[1]
                        os.environ["AINM_TOKEN"] = token
                        print(f"  Auto-detected token from observe_and_resubmit.py")
                        break
        except Exception:
            pass
    if not token:
        data["api_error"] = "No AINM_TOKEN set. Dashboard will use local data only."
        print(f"  WARNING: {data['api_error']}")
        return data

    try:
        rounds = get_my_rounds()
        data["rounds"] = rounds
        print(f"  Fetched {len(rounds)} rounds from API")

        # Fetch initial states + analysis for completed rounds
        for r in rounds:
            rid = r["id"]
            status = r.get("status", "")

            # Fetch round details (initial states)
            try:
                round_detail = get_round(rid)
                data["initial_states"][rid] = {
                    "initial_states": round_detail.get("initial_states", []),
                    "map_width": round_detail.get("map_width", 40),
                    "map_height": round_detail.get("map_height", 40),
                    "seeds_count": round_detail.get("seeds_count", 5),
                }
                print(f"  Fetched initial states for round {r.get('round_number', '?')}")
            except Exception as e:
                print(f"  Failed to fetch round {rid[:8]}: {e}")

            # Fetch analysis for completed/scoring rounds
            if status in ("completed", "scoring"):
                n_seeds = r.get("seeds_count", 5)
                analysis = {}
                for si in range(n_seeds):
                    try:
                        a = get_analysis(rid, si)
                        analysis[str(si)] = a
                    except Exception:
                        pass
                if analysis:
                    data["analysis"][rid] = analysis
                    print(f"  Fetched analysis for round {r.get('round_number', '?')} ({len(analysis)} seeds)")

    except Exception as e:
        data["api_error"] = f"API error: {e}"
        print(f"  API error: {e}")
        traceback.print_exc()

    return data


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """Serve dashboard HTML + API data."""

    collected_data = None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/dashboard.html":
            self.serve_file("dashboard.html", "text/html")
        elif path == "/api/data":
            self.send_json(self.collected_data)
        elif path == "/api/refresh":
            print("\nRefreshing data...")
            DashboardHandler.collected_data = collect_data()
            self.send_json({"status": "ok"})
        else:
            self.send_error(404)

    def serve_file(self, filename, content_type):
        fpath = os.path.join(DATA_DIR, filename)
        try:
            with open(fpath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, f"{filename} not found")

    def send_json(self, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress noisy request logging
        pass


def main():
    print(f"Astar Island Dashboard")
    print(f"======================")
    print(f"Collecting data...")
    DashboardHandler.collected_data = collect_data()
    print(f"\nStarting server on http://localhost:{PORT}")
    print(f"Press Ctrl+C to stop.\n")

    server = http.server.HTTPServer(("", PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutdown.")
        server.server_close()


if __name__ == "__main__":
    main()
