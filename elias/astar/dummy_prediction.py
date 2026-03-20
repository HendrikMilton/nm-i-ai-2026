import json

ROUND_ID = "71451d74-be9f-471f-aacd-a41f3b68a9cd"
HEIGHT = 40
WIDTH = 40
CLASSES = 6

p = 1 / CLASSES
prediction = [[[p] * CLASSES for _ in range(WIDTH)] for _ in range(HEIGHT)]

body = {
    "round_id": ROUND_ID,
    "seed_index": 0,
    "prediction": prediction,
}

with open("astar/dummy_prediction.json", "w") as f:
    json.dump(body, f, indent=2)

print("Wrote astar/dummy_prediction.json")
