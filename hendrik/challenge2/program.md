# Autoresearch — Challenge 2

## Task
<!-- Fill in after kickoff -->

## Metric
<!-- What metric to optimize, lower/higher is better? -->

## Evaluation
<!-- How to evaluate: e.g. `python evaluate.py` → prints "score: X.XX" -->

## Constraints
- Only modify `solve.py`
- Must respond within timeout (check challenge spec)
- Commit after every change, never force push
- If experiment is worse: commit a revert with the result in the message
- If experiment is better: commit with the result in the message

## Loop
1. Read current `solve.py` and recent results in git log
2. Think of an improvement to try
3. Edit `solve.py`
4. `git add solve.py && git commit -m "experiment: <description>"`
5. Run evaluation
6. If score improved: `git commit -m "result: score=X.XX, KEEP (prev=Y.YY)"`
7. If score worse/equal: revert solve.py to previous version, `git commit -m "revert: score=X.XX, DISCARD (prev=Y.YY)"`
8. Go to 1. Never stop. Assume the human is asleep.
