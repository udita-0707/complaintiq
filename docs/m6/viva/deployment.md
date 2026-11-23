# Crib sheet: deployment and monitoring (M5, Aman)

**Pipeline.** Length check (400) -> PII scrub (emails, phones, SSNs, Luhn-valid cards, 9+ digit
runs) -> quality check (short, gibberish, non-English -> human review with a reason) -> model with a
2-second timeout -> gate (tau 0.803386) and routing table -> audit row (hash of scrubbed text, no
text) and metrics.

**Endpoints.** `POST /v1/triage`, `POST /v1/feedback`, `GET /health`, `/v1/model`, `/metrics`.
One additive optional response field, `reason`.

**Failures (C8).** Timeout -> HUMAN_REVIEW; missing model -> 503 (never fake labels); audit log down
-> served, rows buffered (1,000-row buffer); abuse -> 429 (60 a minute per IP, bursts of 20); body
over 131,072 bytes -> 413.

**Deployment.** Packaged as two Docker images for Hugging Face Spaces (API with the frozen model
via git-lfs, manifest-checked; Streamlit reviewer UI). **Not published:** Docker Spaces required a
paid plan, so the local container is the deployment record and the M5 goal "public URL works" is not
met. CI: ruff, tests, pip-audit, image builds, Space smoke test.

**Numbers (local container).** Cold start 3.4 s, memory 313.7 MB, image 704.3 MB. Load test, 200
requests per level: p95 13.0 ms (1 client), 36.8 ms (5), 82.6 ms (10); 0 errors; throughput 82.0,
195.3 and 176.8 requests/s. Failure tests: 11 of 11 HTTP and 5 of 5 container scenarios passed
(timeout answered after 2018 ms; first 429 after 11 requests). M4 in-process p95 11.51 ms.

**Drift replay.** Issue PSI vs training labels 0.320 to 0.416 (above 0.2 in all 9 months: the known
label shift); product PSI vs the first month at most 0.022; confidence 0.867 to 0.882 (no drop).

**Monitoring.** /metrics (latency, errors, routes by reason, predicted products, confidence, PII
residual, audit buffer); drift job (PSI vs training labels above 0.2, confidence drop above 10%,
length PSI, OOV rate), val replayed by month. Correction rate from feedback.

**Likely questions.**
- *What if the model is slow?* 2-second timeout -> human review with reason `timeout`.
- *Why no stub fallback?* A deployed triage system must not invent labels; 503 is honest.
- *Why no public URL?* Hugging Face Docker Spaces required a paid plan; the identical image was run
  and measured locally. Publishing on any host that runs Docker images is the next step.
- *Is the audit log persistent?* Only as long as the container's disk; no persistent volume was set up.
- *What triggers retraining?* Sustained drift or a rising correction rate, then a manual review.
