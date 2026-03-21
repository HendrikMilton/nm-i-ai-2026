## Logging Rules

Logs are split into multiple files to keep polling lightweight:

```
logs/
  index.json              # Round index (tiny, polled every 15s)
  rounds/
    <round_id>.json       # Full data per round (~2MB each)
```

### index.json

```json
{
  "rounds": [
    { "id": "<round_id>", "started_at": "ISO 8601" }
  ]
}
```

### rounds/<round_id>.json

```json
{
  "started_at": "ISO 8601",
  "map_width": 40,
  "map_height": 40,
  "queries": [],
  "submissions": [],
  "actions": []
}
```

### queries

Each simulate call. Must include the grid data so the frontend can render it.

| Field              | Type   | Description                                      |
|--------------------|--------|--------------------------------------------------|
| `timestamp`        | string | ISO 8601 UTC                                     |
| `seed_index`       | int    | 0–4                                              |
| `viewport`         | object | `{x, y, w, h}` — viewport coordinates            |
| `grid`             | array  | 2D terrain grid returned by the API              |
| `budget_remaining` | any    | Remaining query budget after this call            |

### submissions

Each prediction submission (up to 5 per round, one per seed).

| Field        | Type   | Description                        |
|--------------|--------|------------------------------------|
| `timestamp`  | string | ISO 8601 UTC                       |
| `seed_index` | int    | 0–4                                |
| `result`     | any    | API response from the submit call  |

### actions

General lifecycle events and full API responses. Includes:
- `fetch_round_details` with `raw_response` (full round data)
- `simulate_response` with `settlements` and `response_keys`
- `build_prediction` with the full `prediction` tensor
- `check_budget` / `check_budget_for_extras` with `raw_response`
- Errors: `simulate_error`, `submit_error`

Use `log_query()`, `log_submission()`, and `log_action()` helpers in `run.py`.
The log files persist across runs. Each round gets its own file.
