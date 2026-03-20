#!/bin/bash
# Test submission locally, mimicking the competition sandbox.
# Usage: ./test_submission.sh <run_name>
#   e.g. ./test_submission.sh baseline-yolov8x

set -e

RUN_NAME=${1:?Usage: ./test_submission.sh <run_name>}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNS_DIR="$SCRIPT_DIR/runs"
DATA_DIR="$SCRIPT_DIR/data"
SUBMISSION_DIR="$RUNS_DIR/$RUN_NAME/submission"

echo "============================================"
echo "Testing submission: $RUN_NAME"
echo "============================================"

# Find best weights
BEST_PT="$RUNS_DIR/$RUN_NAME/weights/best.pt"
if [ ! -f "$BEST_PT" ]; then
    echo "ERROR: Best weights not found at $BEST_PT"
    exit 1
fi

# Create submission directory
rm -rf "$SUBMISSION_DIR"
mkdir -p "$SUBMISSION_DIR"

# Check if ONNX model exists (for ONNX-based submissions)
ONNX_MODEL="$RUNS_DIR/$RUN_NAME/model.onnx"
if [ -f "$ONNX_MODEL" ]; then
    echo "Using ONNX submission"
    cp "$SCRIPT_DIR/run_onnx.py" "$SUBMISSION_DIR/run.py"
    cp "$ONNX_MODEL" "$SUBMISSION_DIR/model.onnx"
else
    echo "Using .pt submission"
    cp "$SCRIPT_DIR/run.py" "$SUBMISSION_DIR/run.py"
    cp "$BEST_PT" "$SUBMISSION_DIR/best.pt"
fi

# Show submission contents
echo ""
echo "Submission contents:"
ls -lh "$SUBMISSION_DIR/"
echo ""

# Check size
TOTAL_SIZE=$(du -sb "$SUBMISSION_DIR" | cut -f1)
MAX_SIZE=$((420 * 1024 * 1024))
echo "Total size: $(du -sh "$SUBMISSION_DIR" | cut -f1) / 420 MB"
if [ "$TOTAL_SIZE" -gt "$MAX_SIZE" ]; then
    echo "WARNING: Submission exceeds 420 MB limit!"
fi

# Run inference mimicking sandbox
echo ""
echo "Running inference on val images..."
OUTPUT_DIR="$RUNS_DIR/$RUN_NAME/test_output"
mkdir -p "$OUTPUT_DIR"

cd "$SUBMISSION_DIR"
time python3 run.py --input "$DATA_DIR/images/val" --output "$OUTPUT_DIR/predictions.json"

# Count predictions
cd "$SCRIPT_DIR"
PRED_COUNT=$(python3 -c "import json; print(len(json.load(open('$OUTPUT_DIR/predictions.json'))))")
echo ""
echo "Predictions: $PRED_COUNT"

# Evaluate
echo ""
echo "Running evaluation..."
cd "$SCRIPT_DIR"
python3 evaluate.py --predictions "$OUTPUT_DIR/predictions.json" --ground-truth "$DATA_DIR/val_annotations.json"

# Create zip for submission
echo ""
echo "Creating submission zip..."
cd "$SUBMISSION_DIR"
zip -r "$RUNS_DIR/$RUN_NAME/submission.zip" . -x ".*"
echo "Zip created: $RUNS_DIR/$RUN_NAME/submission.zip"
echo "Size: $(du -sh "$RUNS_DIR/$RUN_NAME/submission.zip" | cut -f1)"

echo ""
echo "============================================"
echo "Done! Submit $RUNS_DIR/$RUN_NAME/submission.zip"
echo "============================================"
