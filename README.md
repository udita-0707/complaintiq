# ComplaintIQ

[![CI](https://github.com/udita-0707/complaintiq/actions/workflows/ci.yml/badge.svg)](https://github.com/udita-0707/complaintiq/actions/workflows/ci.yml)

Triage engine for consumer financial complaints (CFPB). From a complaint narrative it predicts the
product, the three most likely issues and a priority flag, routes the complaint to a team, and sends
anything it is unsure about to a human review queue with a reason. Decision support only: a person
handles every complaint.

- **Technical report:** [reports/m6/technical_report.md](reports/m6/technical_report.md)
- **Deck:** [reports/m6/ComplaintIQ_deck.pptx](reports/m6/ComplaintIQ_deck.pptx)
- **Spec (brief, PRD, tech spec):** [docs/SPEC.md](docs/SPEC.md)
- **Live API and reviewer UI:** not deployed publicly (Hugging Face Docker Spaces required a paid
  plan); run both locally, see Quickstart and [docs/deployment.md](docs/deployment.md)

## Results

The shipped model is a class-weighted TF-IDF + linear SGD model (frozen in
`configs/final_model.yaml`). **test** = read once, after the freeze; **val-B** = held-out half of
validation.

| | product | issue |
|---|---|---|
| macro-F1, test | 0.701 | 0.498 |
| top-3 accuracy, test | 0.974 | 0.845 |
| ECE after temperature scaling, val-B | 0.0149 | 0.0425 |

- Confidence gate (tau 0.803): auto-routes 0.7261 of test complaints at precision 0.9356; the rest
  go to human review.
- Priority: HIGH recall 0.834 at precision 0.268 on test (proxy label).
- Latency (local Docker container, 200 requests per level): p95 13.0 ms with one client, 82.6 ms with
  ten concurrent clients, zero errors; 16 of 16 failure tests passed (reports/m5/).
- Not done: the full GPU transformer run and ONNX int8 (see report, sections 3 and 4).

## How it works

```
narrative -> length check -> PII scrub -> quality check -> model (2 s timeout)
          -> calibrated confidence gate -> team (AUTO) or Human Review Queue (with reason)
          -> audit row (hash of the text, never the text) + Prometheus metrics
```

Data: 1,253,594 cleaned narratives from an archived CC0 mirror of the CFPB database, 10 product and
34 issue classes, time split (train to 2022-09-12, val to 2023-05-05, test to 2024-02-09). See
[docs/data_card.md](docs/data_card.md).

## Quickstart

Requires Python 3.11.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
make install-serve                # pip install -e ".[dev,serve]"
make test lint
COMPLAINTIQ_PREDICTOR=stub make serve   # API on localhost, docs at /docs (stub model)
```

With the frozen model in `models/` (not in git), `make serve` serves it; `make ui` opens the
reviewer console. Full reproduction from the raw data: [docs/REPRODUCE.md](docs/REPRODUCE.md).
Deployment: [docs/deployment.md](docs/deployment.md).

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/triage` | classify, gate and route; text 20 to 10,000 characters |
| POST | `/v1/feedback` | store an agent's correction for a `request_id` |
| GET | `/health` | liveness and whether the model is loaded |
| GET | `/v1/model` | model version and thresholds |
| GET | `/metrics` | Prometheus metrics |

## Layout

```
configs/      data, model, thresholds, routing, serving, safety, request log, monitoring
src/complaintiq/
  data/       load, clean, taxonomy, priority, split, statistics
  privacy/    PII checks and scrubbing
  models/     baseline, transformer, calibration, iterations
  eval/       metrics, evaluation, error analysis, robustness, tracking
  serving/    API, schemas, gate, router, predictor chain, quality, security, request log
  monitoring/ Prometheus metrics, drift
ui/           Streamlit reviewer console
deploy/       Hugging Face Space images
scripts/      data prep, benchmarks, final test eval, load and failure tests, report tooling
reports/      milestone reports (m2-m6), experiment logs
docs/         spec, data card, plans, security, monitoring, deployment, viva material
```

`data/`, `models/`, `build/` and `runtime/` are gitignored.

## Team

| Person | Areas | Milestones |
|---|---|---|
| Kalash (@kkt04) | data loading, cleaning, taxonomy, priority labels, splits, provenance, data tests | M1, M2 |
| Dally (@astro-dally) | spec, statistics and shift analysis, baseline, metrics, experiment logging | M1-M3 |
| Udita (@udita-0707) | model and threshold configs, PII, transformer, calibration, evaluation; M5 input safety, audit log, drift; M6 report | M1-M6 |
| Aman (@AmanKumar1411) | scaffold, serving API, gate, router, Docker, CI; M5 runtime, metrics, deployment, UI; M6 repo and demo | M1-M6 |

## Licence

MIT (code). The data mirror is CC0.
