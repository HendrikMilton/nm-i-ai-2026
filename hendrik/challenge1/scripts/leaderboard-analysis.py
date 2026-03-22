#!/usr/bin/env python3
"""
Fetches per-task scores for the top 5 teams and computes average score per task.
Usage: ACCESS_TOKEN=xxx python3 scripts/leaderboard-analysis.py
"""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor

TOKEN = os.environ.get("ACCESS_TOKEN")
if not TOKEN:
    print("ERROR: ACCESS_TOKEN env var required", file=sys.stderr)
    sys.exit(1)

BASE = "https://api.ainm.no/tripletex"


def fetch_json(url: str):
    req = Request(url, headers={"Cookie": f"access_token={TOKEN}"})
    with urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    out = []  # collect all lines, write to both stdout and file

    def w(line=""):
        print(line)
        out.append(line)

    # 1. Get full leaderboard
    leaderboard = fetch_json(f"{BASE}/leaderboard")
    top5 = leaderboard[:5]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    w(f"# Leaderboard Analysis — Top 5 Teams")
    w(f"*Generated {now}*")
    w()

    w("## Top 5 Teams")
    w()
    w("| Rank | Score | Tasks | Team |")
    w("|------|------:|------:|------|")
    for t in top5:
        w(f"| #{t['rank']} | {t['total_score']:.2f} | {t['tasks_touched']} | {t['team_name']} |")

    # 2. Fetch per-task scores for each top-20 team (parallel)
    print(f"\nFetching per-task scores for {len(top5)} teams...")

    def fetch_team_tasks(team):
        tasks = fetch_json(f"{BASE}/leaderboard/{team['team_id']}")
        return (team, tasks)

    with ThreadPoolExecutor(max_workers=10) as pool:
        team_tasks = list(pool.map(fetch_team_tasks, top5))

    # 3. Aggregate: average score per task across top 20
    task_scores: dict[str, list[float]] = {}
    for team, tasks in team_tasks:
        for t in tasks:
            tid = t["tx_task_id"]
            task_scores.setdefault(tid, []).append(t["best_score"])

    sorted_task_ids = sorted(task_scores.keys(), key=lambda x: int(x))

    w()
    w("## Average Score Per Task (Top 5 Teams)")
    w()
    w("| Task | Avg | Max | Min | Teams w/ score |")
    w("|------|----:|----:|----:|:--------------:|")

    total_avg = 0
    for tid in sorted_task_ids:
        scores = task_scores[tid]
        non_zero = [s for s in scores if s > 0]
        avg = sum(scores) / len(scores)
        mx = max(scores)
        mn = min(scores)
        total_avg += avg
        w(f"| {tid} | {avg:.2f} | {mx:.2f} | {mn:.2f} | {len(non_zero)}/{len(scores)} |")

    w(f"| **Total** | **{total_avg:.2f}** | | | |")

    # 4. Score matrix: top 20 × tasks
    w()
    w("## Score Matrix (Top 5 x Tasks)")
    w()
    header = "| Team |" + "|".join(f" {tid} " for tid in sorted_task_ids) + "|"
    sep = "|------|" + "|".join("----:" for _ in sorted_task_ids) + "|"
    w(header)
    w(sep)

    for team, tasks in team_tasks:
        task_map = {t["tx_task_id"]: t["best_score"] for t in tasks}
        cells = []
        for tid in sorted_task_ids:
            score = task_map.get(tid, 0)
            cells.append(f" {score:.1f} " if score > 0 else " - ")
        w(f"| {team['team_name'][:28]} |" + "|".join(cells) + "|")

    # Write to markdown file
    script_dir = Path(__file__).resolve().parent
    outfile = script_dir / "leaderboard-analysis.md"
    outfile.write_text("\n".join(out) + "\n")
    print(f"\nWritten to {outfile}")


if __name__ == "__main__":
    main()
