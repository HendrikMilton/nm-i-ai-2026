"""
Offline replay — replays logged requests against solve.py and compares results.
Usage: python shared/replay.py challenge1/requests.jsonl
"""
import json, sys, time, importlib.util, os


def load_solve(challenge_dir):
    spec = importlib.util.spec_from_file_location("solve", os.path.join(challenge_dir, "solve.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.predict


def replay(log_path, score_fn=None):
    challenge_dir = os.path.dirname(os.path.abspath(log_path))
    predict = load_solve(challenge_dir)

    entries = []
    with open(log_path) as f:
        for line in f:
            entries.append(json.loads(line))

    print(f"Replaying {len(entries)} requests from {log_path}")
    print("-" * 60)

    total_time = 0
    for i, entry in enumerate(entries):
        t0 = time.time()
        result = predict(entry["request"])
        elapsed = time.time() - t0
        total_time += elapsed

        match = result == entry["response"]
        status = "SAME" if match else "DIFF"
        print(f"  [{i+1}/{len(entries)}] {elapsed:.3f}s {status}")

        if score_fn:
            score = score_fn(entry["request"], result)
            print(f"    score: {score}")

    print("-" * 60)
    print(f"Total: {total_time:.3f}s, Avg: {total_time/len(entries):.3f}s/req")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python shared/replay.py <challenge_dir>/requests.jsonl")
        sys.exit(1)
    replay(sys.argv[1])
