# Agentic Avengers — NM i AI 2026

Norwegian AI Championship (NM i AI), 69-hour hackathon, March 19–22, 2026.

## Team

4 members, each tackling different challenges autonomously with Claude Code as AI pair programmer.

| Member | Focus |
|--------|-------|
| Hendrik | Challenge 2 — NorgesGruppen (Object Detection) |
| Arian | Challenge 3 — Astar (Route Optimization) |
| Elias | Challenge 3 — Astar (Route Optimization) |
| Gabriel | Challenge 1 — Tripletex (Accounting/API) |

## Challenges

### Challenge 1 — Tripletex
Accounting/API challenge. See `gabriel/` for solution.

### Challenge 2 — NorgesGruppen Data: Object Detection
Detect and classify 356 grocery products on store shelves. Upload a zip with model weights + inference script to a sandboxed GPU environment.

**Best score: 0.9186** (3-model YOLO11x ensemble)

- Models & submissions: https://huggingface.co/SaulGoodmens/nm-ai-norgesgruppen
- Code: `hendrik/challenge2/`
- Approach: 3x YOLO11x trained at different scales (1600, 1280, 960), ensembled with Weighted Boxes Fusion, FP16 ONNX inference

### Challenge 3 — Astar: Route Optimization
Shortest path / routing challenge. See `arian/` and `elias/` for solutions.

## Repository Structure

```
agentic-avengers-nm-ai/
├── hendrik/              # Challenge 2 (NorgesGruppen) + shared infra
│   ├── challenge2/       # Object detection solution
│   │   ├── train.py      # YOLO training script
│   │   ├── evaluate.py   # Local evaluation (mAP scoring)
│   │   ├── run_ensemble3.py  # 3-model ensemble inference
│   │   ├── run_onnx.py   # Single model ONNX inference
│   │   └── prepare_data.py   # COCO → YOLO format conversion
│   ├── frontend/         # React dashboard (dataset viewer, training monitor)
│   └── challenge3/       # Challenge 3 attempt
├── arian/                # Challenge 3 (Astar)
├── elias/                # Challenge 3 (Astar)
└── gabriel/              # Challenge 1 (Tripletex)
```

## Tech Stack

- **ML**: PyTorch, Ultralytics (YOLO11x), ONNX Runtime
- **Ensemble**: ensemble-boxes (Weighted Boxes Fusion)
- **Frontend**: React, Bun, Tailwind CSS
- **Infra**: GCP (L4/A100 GPUs), Docker
- **AI Assistant**: Claude Code (Opus 4.6) for autonomous development

## License

MIT
