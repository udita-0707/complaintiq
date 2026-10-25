# ComplaintIQ: Financial Complaint Triage Engine

**NLP Industry Track \| Team of 4 \| Contains: Part A (M1 Problem Brief), Part B (PRD), Part C (Tech Spec)**

> Numbers marked **\[target\]** are hypotheses to validate and revise, not results. Numbers marked **\[assumption\]** must be stated as assumptions in your report. Never put a target on your resume as if it were a result.

------------------------------------------------------------------------

# Part A: M1 Problem Brief

## A1. Problem statement

Banks, lenders, and fintechs receive large volumes of free-text customer complaints. Each must be categorized, routed to the right team, and answered within regulatory timelines. Manual or keyword-rule triage causes three failures: (1) misrouting, which adds days of internal handoffs; (2) urgent cases (fraud, unauthorized transactions, collection harassment) waiting in the same queue as routine ones; (3) agents spending minutes reading long narratives before acting.

## A2. NLP task framing

| Sub-task                | Type                                                          | Output                     |
|-------------------------|---------------------------------------------------------------|----------------------------|
| Product classification  | Single-label multi-class (~10-18 classes after harmonization) | Product category           |
| Issue classification    | Single-label multi-class, long-tailed (50-100+ classes)       | Issue type                 |
| Priority prediction     | Binary (High / Normal) on a derived proxy label               | Priority + score           |
| Routing                 | Deterministic mapping from product/issue/priority             | Destination team           |
| Confidence gating       | Calibrated probability + threshold                            | Auto-route vs human review |
| Summarization (stretch) | Abstractive or extractive, 2-3 sentences                      | Agent-facing summary       |

## A3. Users

| User                                   | Need                                                        | Pain today                                                |
|----------------------------------------|-------------------------------------------------------------|-----------------------------------------------------------|
| **Complaint-handling agent** (primary) | Complaint arrives in the right queue with a short summary   | Reads long narratives, re-routes wrongly assigned tickets |
| **Team lead / queue manager**          | Urgent cases surface first; balanced queues                 | No early signal of fraud or harassment cases              |
| **Compliance officer**                 | Audit trail, timeliness, no mishandled regulated complaints | Hard to prove consistent handling                         |
| **Customer** (indirect)                | Faster, correct resolution                                  | Bounced between departments                               |

## A4. Business objective

Reduce time-to-first-correct-assignment and surface high-priority complaints earlier, while keeping a human in control of uncertain cases.

## A5. Success metrics

**Model metrics**

| Metric                          | Why                                       | Target                                               |
|---------------------------------|-------------------------------------------|------------------------------------------------------|
| Product macro-F1                | Handles class imbalance                   | ≥ +5 pts over TF-IDF+LR baseline **\[target\]**      |
| Issue macro-F1 / top-3 accuracy | Long-tail difficulty                      | Report both; top-3 ≥ 85% **\[target\]**              |
| High-priority recall            | Missing urgent cases is the costly error  | ≥ 85% at acceptable precision **\[target\]**         |
| Calibration (ECE)               | Confidence must be trustworthy for gating | ECE \< 0.05 after temperature scaling **\[target\]** |

**System metrics**

| Metric                                         | Target                                          |
|------------------------------------------------|-------------------------------------------------|
| Auto-route coverage at ≥ 95% precision         | ≥ 60% of complaints **\[target\]**              |
| p95 latency (CPU, 256 tokens, quantized model) | ≤ 300 ms **\[target\]**                         |
| Fallback rate                                  | Tracked, reported as a coverage/precision curve |

**Business metric (estimated, not measured)** `agent-minutes saved/day = complaints/day × auto-route coverage × minutes saved per manual triage` Illustrative **\[assumption\]**: 5,000/day × 0.60 × 1.5 min = 4,500 min (~75 agent-hours/day). State all three inputs as assumptions.

## A6. Feasibility analysis

| Dimension         | Assessment                                                                                                                                                                                                      |
|-------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Data**          | CFPB Consumer Complaint Database: public, free, well over 1M complaints with consumer narratives (verify current count at download). Labels (product, issue) included.                                          |
| **Labels**        | Product/issue labels come from the data, but the taxonomy changed over time (products were consolidated around 2023). You must harmonize categories. Priority is **not** provided and must be derived (see B5). |
| **Compute**       | Free Colab/Kaggle GPU is enough if fine-tuning on a stratified 100-200k subsample with a small model.                                                                                                           |
| **Skills**        | Team covers data, classical ML, transformers, and backend deployment.                                                                                                                                           |
| **Time**          | Scope is achievable if summarization stays a stretch goal.                                                                                                                                                      |
| **Legal/ethical** | Public, consumer-consented, pre-redacted data. Residual PII check still required. Model is decision support only.                                                                                               |
| **Main risks**    | Noisy/ambiguous issue labels, derived priority labels, taxonomy drift, long-tail classes. See C12.                                                                                                              |

**Verdict:** Feasible. Highest risks are label quality and scope creep, both controllable.

## A7. Scope

**In scope:** product/issue classification, priority flag, routing, confidence fallback, REST API, monitoring plan, Docker deployment, demo UI. **Stretch:** summarization. **Out of scope:** automated customer replies, resolution prediction, non-English complaints, real company integration, any automated adverse action.

------------------------------------------------------------------------

# Part B: Product Requirements Document (PRD)

## B1. Overview

**Product:** ComplaintIQ, an API and reviewer UI that ingests a complaint narrative and returns product, issue, priority, destination team, confidence, and (optionally) a summary. Low-confidence items go to a human review queue.

## B2. Goals and non-goals

| Goals                               | Non-goals                                   |
|-------------------------------------|---------------------------------------------|
| Accurate, calibrated classification | Replacing human agents                      |
| Surface high-priority cases early   | Deciding complaint outcomes or compensation |
| Transparent confidence and fallback | Multilingual support                        |
| Reproducible, versioned pipeline    | Real-time streaming at scale                |

## B3. User stories and acceptance criteria

| ID            | Story                                                         | Acceptance criteria                                                |
|---------------|---------------------------------------------------------------|--------------------------------------------------------------------|
| US1           | As an agent, I submit a complaint and get a category and team | Response contains product, issue, team, confidence; p95 ≤ 300 ms   |
| US2           | As a queue manager, I see high-priority items flagged         | `priority=HIGH` returned with score; recall measured on test set   |
| US3           | As an agent, uncertain cases go to me for manual review       | Confidence \< τ returns `route=HUMAN_REVIEW`                       |
| US4           | As an agent, I correct a wrong prediction                     | `/feedback` stores the correction linked to the request ID         |
| US5           | As a compliance officer, every decision is auditable          | Each request logged with model version, scores, route (no raw PII) |
| US6           | As a lead, I monitor system health                            | `/metrics` exposes latency, fallback rate, class distribution      |
| US7 (stretch) | As an agent, I get a short summary                            | Summary ≤ 60 words, faithful to the source                         |

## B4. Functional requirements

- **FR1** Accept text of 20-10,000 chars; reject/flag outside range.
- **FR2** Run PII scrub before inference and before any logging.
- **FR3** Return product, issue (top-3 with probabilities), priority, team, confidence.
- **FR4** Apply confidence gate with a configurable threshold loaded from config.
- **FR5** Version every response with `model_version`.
- **FR6** Provide `/health`, `/metrics`, `/feedback`.
- **FR7** Reviewer UI (Streamlit or simple web page) for demo: paste text, see results, submit correction.

## B5. Priority label definition (document this carefully)

Priority is a **proxy label**, not ground truth. Derive from fields that are **excluded from model inputs**:

`HIGH` if any of:

1.  Issue/sub-issue in a **severity list** you define (e.g., fraud or scam, unauthorized transactions, identity theft, threatening/harassing collection, account takeover).
2.  Company response is "Closed with monetary relief".
3.  "Timely response?" = No.

Otherwise `NORMAL`. Publish the severity list in the data card. Limitation to state openly: rules 2 and 3 reflect outcomes that correlate with urgency, not urgency judged at intake.

## B6. Routing table (example, define your own)

| Product group                                        | Team                             |
|------------------------------------------------------|----------------------------------|
| Credit reporting / credit repair                     | Credit Bureau Disputes           |
| Debt collection                                      | Collections Compliance           |
| Mortgage / student loan / vehicle loan               | Lending Servicing                |
| Credit card / prepaid card                           | Card Operations                  |
| Checking/savings / money transfer / virtual currency | Deposits and Payments            |
| Any `HIGH` with fraud/identity issue                 | Fraud and Risk (overrides above) |
| Confidence \< τ                                      | Human Review Queue               |

## B7. Non-functional requirements

| Area            | Requirement                                                                        |
|-----------------|------------------------------------------------------------------------------------|
| Latency         | p95 ≤ 300 ms **\[target\]** on CPU                                                 |
| Availability    | Demo-grade; graceful degradation (fallback to baseline model if transformer fails) |
| Privacy         | No raw narratives in logs; hashed request IDs; PII scrub                           |
| Reproducibility | Pinned dependencies, seeds, data versions, one-command training                    |
| Explainability  | Top-3 labels with probabilities; optional token attributions in the UI             |
| Fairness        | Report performance by slice (product, length, channel, time)                       |

## B8. Risks and mitigations

See C12.

------------------------------------------------------------------------

# Part C: Technical Specification

## C1. Architecture

``` mermaid
flowchart LR
    U[Reviewer UI / API client] --> G[FastAPI Gateway]
    G --> V[Validation + PII Scrub]
    V --> M[Inference Service: ONNX int8 model]
    V --> B[Fallback: TF-IDF + LR]
    M --> C[Calibration + Confidence Gate]
    B --> C
    C -->|conf >= tau| R[Router: team mapping]
    C -->|conf < tau| H[Human Review Queue]
    M -.stretch.-> S[Summarizer]
    R --> L[(Request Log: SQLite/Postgres)]
    H --> L
    L --> D[Drift + Metrics: Prometheus / Evidently]
    U --> F[Feedback endpoint] --> L
```

**Offline pipeline:** raw CFPB CSV → cleaning → PII check → label harmonization → derived priority → time-based split → features/tokenization → training (baseline, transformer) → calibration → threshold selection → ONNX export → registry → container.

## C2. Tech stack

| Layer        | Choice                                                                    |
|--------------|---------------------------------------------------------------------------|
| Language     | Python 3.11                                                               |
| Data         | pandas / polars, scikit-learn, DVC (or dated parquet snapshots)           |
| PII          | Regex rules + Microsoft Presidio (optional)                               |
| Baseline     | scikit-learn: TF-IDF (1-2 grams) + LogisticRegression / LinearSVC         |
| Transformers | Hugging Face Transformers + PyTorch: DistilBERT, DeBERTa-v3-small/base    |
| Tracking     | MLflow or Weights & Biases (or CSV log as minimum)                        |
| Optimization | ONNX Runtime, dynamic int8 quantization                                   |
| Serving      | FastAPI + Uvicorn, Pydantic schemas                                       |
| UI           | Streamlit                                                                 |
| Packaging    | Docker, docker-compose                                                    |
| Deployment   | Hugging Face Spaces, Render, or Fly.io (must be actually deployed for M5) |
| Monitoring   | Prometheus client + Evidently drift report (or a lighter custom script)   |
| CI           | GitHub Actions: lint (ruff), tests (pytest), build image                  |

## C3. Repository structure

    complaintiq/
    ├── README.md
    ├── pyproject.toml / requirements.txt
    ├── Makefile                # make data | train | eval | serve | test
    ├── configs/                # yaml: data, model, thresholds, routing
    ├── data/                   # (gitignored) raw/ interim/ processed/ + DVC
    ├── notebooks/              # EDA only
    ├── src/complaintiq/
    │   ├── data/               # load, clean, harmonize, split, priority rules
    │   ├── privacy/            # pii scrub + leak checks
    │   ├── models/             # baseline.py, transformer.py, calibrate.py
    │   ├── eval/               # metrics, slices, robustness, error taxonomy
    │   ├── serving/            # app.py, schemas.py, router.py, gate.py
    │   └── monitoring/         # drift.py, metrics.py
    ├── tests/
    ├── docker/                 # Dockerfile, compose
    ├── reports/                # m1..m6 docs, figures
    └── .github/workflows/

**Git conventions:** feature branches, PRs with one reviewer, issue per checklist item, tag per milestone (`m1`…`m6`).

## C4. Data specification

**Source:** CFPB Consumer Complaint Database (CSV export). Key fields: date received, product, sub-product, issue, sub-issue, consumer complaint narrative, company, state, submitted via, company response, timely response.

| Field group                                        | Use                                                        |
|----------------------------------------------------|------------------------------------------------------------|
| Narrative                                          | **Model input**                                            |
| Product, issue                                     | **Labels**                                                 |
| Company response, timely response, issue/sub-issue | **Priority derivation only. Never model inputs** (leakage) |
| Date received                                      | Time-based split, drift analysis                           |
| Submitted via, narrative length, company           | Slice analysis only                                        |

**Cleaning steps**

1.  Keep rows with non-empty narratives; drop exact and near-duplicate narratives (hash + MinHash or normalized-text hash).
2.  Normalize whitespace, unicode, repeated `XXXX` placeholders (keep a single placeholder token such as `[REDACTED]`).
3.  Harmonize product and issue taxonomy across years via a mapping table (version it in `configs/`).
4.  Merge issue classes with fewer than N samples into `OTHER`, or evaluate on head + tail groups separately.
5.  Derive priority label (B5).
6.  Drop narratives under ~20 words (document threshold); document length distribution.

**Split (leak-free)**

| Split      | Rule                                          |
|------------|-----------------------------------------------|
| Train      | Oldest ~70% by date received                  |
| Validation | Next ~15% (threshold tuning, calibration)     |
| Test       | Newest ~15%, touched only for final reporting |

Also run a duplicate-overlap check between splits. Use a stratified random split as a secondary comparison to quantify how much random splitting overstates performance.

**Privacy:** CFPB pre-redacts PII, but run residual checks (email, phone, SSN/card-number patterns, names via NER), report the leak rate, scrub at inference, and never log raw text.

**Statistical analysis (M2 requirement):** label distributions, imbalance ratios, length distributions per class, lexical overlap between confusable classes, temporal label drift, bootstrap confidence intervals for later metrics.

## C5. Modeling plan

| Stage                  | Model                                                                  | Notes                                             |
|------------------------|------------------------------------------------------------------------|---------------------------------------------------|
| Baseline               | TF-IDF (1-2 gram, ≤200k features) + LR, class-weighted                 | Fast, strong reference, also the serving fallback |
| Candidate 1            | DistilBERT, max_len 256                                                | Cheap transformer                                 |
| Candidate 2            | DeBERTa-v3-small or base                                               | Likely best accuracy                              |
| Candidate 3 (optional) | Hierarchical: predict product first, then issue conditioned on product | Reduces the issue long tail                       |
| Priority               | Separate binary head or model                                          | Optimize for recall at fixed precision            |

**Training details**

- Stratified subsample of 100-200k training rows, capped per class for the largest classes.
- Head+tail truncation for long narratives (first ~128 + last ~128 tokens).
- Imbalance: class-weighted loss first; compare against focal loss and oversampling.
- Mixed precision, 3-4 epochs, early stopping on validation macro-F1, fixed seeds (report mean ± std over ≥3 seeds for the final candidates).
- **Calibration:** temperature scaling on validation set; report ECE and reliability diagram.
- **Gating:** pick τ on validation such that precision ≥ 95% **\[target\]**; report the full coverage-vs-precision curve.

**Experiment log schema:** `run_id, git_commit, data_version, model, hyperparams, seed, val_macroF1, val_ECE, train_time, notes`.

## C6. Evaluation plan (M4)

| Area                   | What to do                                                                                                                                                    |
|------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Core metrics           | Macro-F1, weighted-F1, per-class P/R/F1, top-k accuracy, confusion matrix                                                                                     |
| Confidence             | ECE, reliability diagram, coverage-precision curve                                                                                                            |
| Error analysis         | Sample ≥100 errors; categorize: label ambiguity, multi-topic narrative, short/uninformative, taxonomy mismatch, genuine model error. Report the share of each |
| Slices                 | By product, narrative length bucket, submission channel, year, company size                                                                                   |
| Robustness             | Typos/noise injection, truncation, sentence shuffling, added boilerplate, paraphrase, unseen-company names, `[REDACTED]` density                              |
| Improvement iterations | Each iteration = hypothesis, change, result, logged                                                                                                           |
| Significance           | Bootstrap CIs or paired test on baseline vs best model                                                                                                        |
| Optimization           | ONNX export + int8 quantization: report accuracy drop vs latency/size/cost per 1k requests                                                                    |
| Inference benchmark    | p50/p95/p99 latency, throughput, RAM at batch 1 and 8                                                                                                         |

## C7. API specification

**`POST /v1/triage`**

``` json
// request
{ "text": "string (20-10000 chars)", "request_id": "optional string", "include_summary": false }
```

``` json
// response 200
{
  "request_id": "a1b2...",
  "model_version": "deberta-small-int8-2026.10.1",
  "product": {"label": "Debt collection", "confidence": 0.94},
  "issue_top3": [{"label": "Attempts to collect debt not owed", "p": 0.71},
                 {"label": "Communication tactics", "p": 0.12},
                 {"label": "Written notification about debt", "p": 0.07}],
  "priority": {"label": "HIGH", "score": 0.83},
  "route": "AUTO",
  "team": "Collections Compliance",
  "summary": null,
  "latency_ms": 142
}
```

`route` is `AUTO` or `HUMAN_REVIEW`; when `HUMAN_REVIEW`, `team` is `"Human Review Queue"`.

**Other endpoints:** `POST /v1/feedback` (request_id, corrected labels), `GET /health`, `GET /metrics` (Prometheus format), `GET /v1/model` (version, thresholds).

**Errors:** `400` invalid/too short/too long text, `422` schema error, `503` model unavailable (triggers fallback first), `500` with generic message (no stack traces).

## C8. Failure handling (M5)

| Failure                              | Behavior                                                 |
|--------------------------------------|----------------------------------------------------------|
| Empty/short/gibberish text           | 400, or route to human if below a quality heuristic      |
| Non-English text                     | Language detection; route to human review                |
| Transformer load/inference error     | Fall back to TF-IDF+LR, flag `model_version` accordingly |
| Timeout (\> 2 s)                     | Return HUMAN_REVIEW with reason                          |
| Low confidence / out-of-distribution | HUMAN_REVIEW                                             |
| Log store down                       | Serve the response, buffer logs locally, alert           |
| PII detected post-scrub              | Redact, increment counter, never log raw                 |

## C9. Monitoring strategy (M5)

| Signal                       | Method                                               | Alert/threshold idea          |
|------------------------------|------------------------------------------------------|-------------------------------|
| Latency p95, error rate      | Prometheus                                           | p95 \> 500 ms                 |
| Fallback (human review) rate | Counter                                              | Sudden rise = drift or outage |
| Predicted class distribution | Weekly vs training distribution (PSI/KL)             | PSI \> 0.2                    |
| Confidence distribution      | Mean/quantiles over time                             | Drop \> 10%                   |
| Input drift                  | Length, vocabulary, embedding drift (Evidently)      | Weekly report                 |
| Quality                      | Feedback corrections as a proxy for accuracy         | Correction rate trend         |
| Retraining trigger           | Sustained drift or correction rate above a set level | Manual review, then retrain   |

## C10. Security and privacy

- No raw text in logs; store request hash, labels, scores, version.
- Input size limits, rate limiting, CORS restricted in deployment.
- Secrets via environment variables; none in git.
- Dependency pinning and `pip-audit` in CI.
- Human-in-the-loop by design; document that the system never triggers adverse customer outcomes.

## C11. Testing strategy

| Level | Examples                                                                                 |
|-------|------------------------------------------------------------------------------------------|
| Unit  | PII scrub patterns, label harmonization, priority rules, gate logic, router mapping      |
| Data  | Split has no ID/text overlap, date ordering holds, no forbidden columns in model inputs  |
| Model | Smoke test on fixed samples, quantized vs FP32 prediction agreement ≥ 98% **\[target\]** |
| API   | Schema validation, all error paths, fallback path, load test (locust or hey)             |
| CI    | Lint + tests + Docker build on every PR                                                  |

## C12. Risks and mitigations

| Risk                               | Likelihood | Mitigation                                                                                                     |
|------------------------------------|------------|----------------------------------------------------------------------------------------------------------------|
| Priority label is a weak proxy     | High       | State as limitation; document the rule; evaluate recall, not just accuracy; optionally hand-verify 200 samples |
| Taxonomy drift corrupts labels     | High       | Version the mapping table; time-based split exposes it                                                         |
| Issue long tail hurts macro-F1     | High       | Hierarchical model, merge rare classes, report head/tail separately                                            |
| Transformer training too slow      | Medium     | Subsample, small model, Kaggle GPU, cache tokenization                                                         |
| Scope creep (summarizer, fancy UI) | Medium     | Stretch goals only after M4                                                                                    |
| Integration delays at M5           | Medium     | Build API skeleton with baseline model in M3                                                                   |
| Unequal workload                   | Medium     | Weekly check-in, issue board, everyone reviews one other module                                                |

## C13. Milestone plan, ownership, and Definition of Done

Adjust weeks to your actual deadlines.

| M      | Weeks (suggested) | Lead            | Deliverables (checklist mapping)                                                             | Definition of Done                                         |
|--------|-------------------|-----------------|----------------------------------------------------------------------------------------------|------------------------------------------------------------|
| **M1** | 1-2               | All (P1 writes) | Problem brief, users, objective, metrics, feasibility                                        | Part A approved, repo created, data downloaded             |
| **M2** | 3-4               | P1              | Data card, EDA, cleaning, stats analysis, split, privacy notes                               | Reproducible `make data`; no leakage tests passing         |
| **M3** | 5-6               | P2 (+P3)        | Baseline, candidate models, experiment log, version-controlled code                          | ≥1 transformer beats baseline on val; all runs logged      |
| **M4** | 7-9               | P3              | Evaluation report, error analysis, iterations, robustness, optimization, inference benchmark | Test-set results reported once; error taxonomy with counts |
| **M5** | 10-11             | P4              | Deployed API, performance measurements, monitoring plan, failure handling                    | Public URL working; load test and failure tests documented |
| **M6** | 12-13             | All             | Technical report, GitHub repo, live demo, business deck (PPT), viva                          | Demo rehearsed; every member can explain every stage       |

**Roles:** P1 Data lead \| P2 Baseline and experiment lead \| P3 Modeling and evaluation lead \| P4 Deployment and demo lead. Each person reviews one other person's pull requests. P4 should deliver an API skeleton with the baseline model by end of M3 so M5 is integration, not construction.

## C14. Viva preparation (questions to be ready for)

1.  Why time-based split? What did random splitting overstate, and by how much?
2.  How was priority defined, and why is it only a proxy?
3.  How did you prevent outcome fields leaking into inputs?
4.  Why macro-F1 over accuracy? What does calibration add?
5.  How was τ chosen, and what does the coverage/precision trade-off mean for the business?
6.  What did quantization cost in accuracy and gain in latency?
7.  What would you monitor in production, and what triggers retraining?
8.  What are the limitations and threats to validity?

## C15. Resume framing (use only measured numbers)

- Built an end-to-end NLP complaint triage system on CFPB complaints (N rows), classifying product/issue across K classes with **X macro-F1** (+Y over TF-IDF baseline) using a time-based split.
- Designed a calibrated confidence gate that auto-routes **Z%** of complaints at **P%** precision, routing the rest to human review.
- Deployed a Dockerized FastAPI service with **p95 N ms** latency after ONNX int8 quantization; added drift monitoring, PII scrubbing, and fallback handling.

------------------------------------------------------------------------

*Open items to decide as a team: severity list for HIGH priority, final class taxonomy, whether summarization is attempted, deployment platform, experiment tracker.*
