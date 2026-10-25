# ComplaintIQ

Financial complaint triage engine for CFPB consumer complaints: product and issue
classification, a priority flag, team routing, and a confidence gate that sends
uncertain cases to human review. See [`docs/SPEC.md`](docs/SPEC.md) for the brief,
PRD and tech spec.

> **Status: walking skeleton.** The API runs end to end with a **stub predictor**
> that returns a fixed dummy prediction. Data processing, training, evaluation and
> monitoring aren't implemented yet.

## Layout

```
configs/            data.yaml, model.yaml, thresholds.yaml (tau), routing.yaml (B6 table)
src/complaintiq/
  data/ privacy/ models/ eval/ monitoring/   placeholders
  serving/          app.py, schemas.py, predictor.py, gate.py, router.py
tests/              gate, router and API tests
docker/             Dockerfile, docker-compose.yml
notebooks/          EDA only
reports/            milestone docs and figures
```

`data/`, `models/` and `mlruns/` are gitignored.

## Setup

Requires Python 3.11.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
make install                      # pip install -e ".[dev]"
```

Optional extras for later milestones: `pip install -e ".[data,ml,ui,monitoring]"`.

## Run

```bash
make serve                        # http://localhost:8000, docs at /docs
make test                         # pytest
make lint                         # ruff
make docker-up                    # same API in Docker on port 8000
```

`make data`, `make train` and `make eval` are placeholders that exit with an error until
M2 to M4.

Example request:

```bash
curl -s localhost:8000/v1/triage \
  -H 'content-type: application/json' \
  -d '{"text": "A debt collector keeps calling me about a debt I do not owe."}'
```

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/triage` | Classify, gate and route a complaint (text 20 to 10,000 chars, else 400) |
| POST | `/v1/feedback` | Store a correction for a `request_id` (in memory for now) |
| GET | `/health` | Liveness and whether a model is loaded |
| GET | `/v1/model` | Model version, predictor type, thresholds |

## Configuration

- `configs/thresholds.yaml`: `tau`. If product confidence is below `tau`, the
  response is `route=HUMAN_REVIEW, team="Human Review Queue"`.
- `configs/routing.yaml`: the B6 routing table. Product labels match by
  case-insensitive substring; the first match wins. HIGH priority with a fraud or
  identity issue routes to Fraud and Risk, overriding the product route.
- `configs/model.yaml`: `predictor: stub`. To plug in a real model, implement the
  `Predictor` protocol in `serving/predictor.py` and register it in `build_predictor`.
- `COMPLAINTIQ_CONFIG_DIR` overrides the config directory (the Docker image sets it to
  `/app/configs`).

## Contributions

Draft, to be filled in by the team (see [`docs/COMMIT_PLAN.md`](docs/COMMIT_PLAN.md)).

| Person | Modules | Milestones |
|---|---|---|
| P1 (Name, @P1-username) | Data loading, cleaning, taxonomy mappings, priority labels, splits, raw data preparation, data provenance, data tests | M2 |
| P2 (Name, @P2-username) | Spec, README, data statistics, shift analysis, figures, M2 reports; later baseline model, metrics, experiment logging | M1, M2, M3 |
| P3 (Name, @P3-username) | Model and threshold configs, PII scrubbing and tests; later transformer, calibration, robustness, ONNX | M1, M2, M3, M4 |
| P4 (Name, @P4-username) | Project scaffold, serving API, gate and router, Docker, CI, data pipeline glue; later monitoring, UI, deployment | M1, M2, M5 |
