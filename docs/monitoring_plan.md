# Monitoring plan (M5)

SPEC C9 and B3 US6. Owners: P3 Udita (drift, privacy, audit log, quality) and P4 Aman
(runtime, latency, availability, deployment). Numbers come from the M4 reports named in each
row; thresholds marked **[assumption]** are team choices, not measured results. Measured M5
values are in `reports/m5/` (TODO until the runs in `docs/deployment.md` are done).

## Sources

- **`GET /metrics`** (Prometheus text, `src/complaintiq/monitoring/metrics.py`): live
  counters and histograms since the process started.
- **Drift job** (`make drift`, `src/complaintiq/monitoring/drift.py`): PSI/KL of predicted
  classes vs the training labels, confidence, input length and out-of-vocabulary rate per
  period. In M5 it replays the val split month by month as stand-in production traffic
  (`reports/m5/drift_report.md`); in production it would run weekly on the logged
  predictions.
- **Request log** (`make request-log-stats`, `src/complaintiq/serving/request_log.py`): route
  mix and the correction rate from agent feedback.

**What is not deployed.** No Prometheus server, dashboard or pager runs in M5. Thresholds are
checked by reading `/metrics`, running the drift job and the request-log stats. On the free
Space every counter and the request log restart empty after a restart or sleep, so trends
need a scraper that stores history (future work).

## Signals

| C9 signal | Source | Threshold | Owner | Response |
|---|---|---|---|---|
| Latency p95 | `ciq_request_latency_seconds{endpoint="/v1/triage"}` | p95 > 500 ms (C9) | P4 | Playbook A |
| Error rate | `ciq_errors_total` / `ciq_requests_total` | > 1% of triage requests over 15 min **[assumption]** | P4 | Playbook A |
| Model unavailable | `/health` status `degraded`; `ciq_model_errors_total` | any | P4 | Playbook B |
| Timeouts | `ciq_inference_timeouts_total`; `ciq_triage_route_total{reason="timeout"}` | > 1% of triage requests **[assumption]** | P4 | Playbook A |
| Fallback (human review) rate | `ciq_triage_route_total` by `route` and `reason` | human-review share 10 points above its reference for a day **[assumption]**; reference 0.242 on val-B and 0.274 on test (1 minus auto-route coverage 0.7582 and 0.7261, reports/m4/calibration_report.md and test_results.md) | P3 | Playbook C |
| Predicted class distribution | drift job: product and issue PSI vs training labels; live: `ciq_predicted_product_total` | PSI > 0.2 (C9) | P3 | Playbook D |
| Confidence distribution | drift job: mean and quantiles of calibrated product confidence; live: `ciq_product_confidence` | mean drops > 10% vs the reference period (C9) | P3 | Playbook D |
| Input drift | drift job: narrative-length PSI vs train; OOV rate vs the frozen vectorizer | length PSI > 0.2 (same rule as C9); OOV rate reported only | P3 | Playbook D |
| Quality | request log: correction rate (share of logged requests whose feedback changed a predicted field) | rising for 2 consecutive weeks **[assumption]** | P3 | Playbook E |
| PII after scrub | `ciq_pii_residual_total` | > 0 | P3 | Playbook F |
| Audit log health | `ciq_request_log_buffer_rows`, `ciq_request_log_dropped_rows` | buffer > 0 for 5 min, or any dropped row **[assumption]** | P3 | Playbook G |
| Abuse | `ciq_rate_limited_total` | sudden spike (reported, no number) | P4 | Playbook H |
| Model identity | `ciq_model_info{model_version,predictor}` | differs from `configs/final_model.yaml` or carries `-fallback` | P4 | Playbook B |

Reference values from M4 for comparison: calibrated product ECE 0.0149 on val-B and 0.0211
on test; issue ECE 0.0425 on val-B and 0.0516 on test; local API p95 12.3 ms over 200
sequential requests (reports/m4/api_latency.md); in-process single-request p95 11.51 ms
(reports/m4/inference_benchmark.md).

## Known, expected drift

M2 measured a label shift between train and val: credit reporting is 0.405 of train and
0.605 of val (reports/m2_data_stats.md, used in reports/m4/improvement_iterations.md). The
product PSI vs the training labels is therefore expected to exceed 0.2 in the replay without
any input problem. The drift report also shows PSI vs the first replayed period, which
isolates change inside production traffic; read the two together before acting.

## Playbooks

- **A. Slow or failing requests (P4).** Check `/health`, the Space logs and
  `process_resident_memory_bytes`. The free tier shares CPU, so compare with the local
  container numbers in `reports/m5/load_test.md` before blaming the code. If timeouts or
  errors persist, restart the Space; if they follow a deployment, roll back (docs/deployment.md).
- **B. Model unavailable or unexpected model (P4).** `/health` `degraded` means the model did
  not load: check that the Space repo holds the real joblib files (git-lfs) and that
  `make space` verified the manifest. Never re-enable the stub in deployment.
- **C. Human-review rate jump (P3).** Split by `reason`: `timeout` goes to playbook A;
  `non_english`, `short_text` or `low_quality_text` means the input mix changed (e.g. a new
  intake form); `low_confidence` means drift: run the drift job (playbook D).
- **D. Drift alert (P3).** Run `make drift` on recent logged traffic, compare PSI vs train and
  vs the reference period, look at the largest share changes, and sample corrections in the
  request log. One flagged period is a watch item; a sustained alert starts the retraining
  review below.
- **E. Correction rate rising (P3).** Break corrections down by field
  (`corrected_by_field`) and product. If one class dominates, check the taxonomy mapping and
  the routing table first; otherwise start the retraining review.
- **F. Residual PII (P3).** Treat as an incident: the scrub missed a pattern overlap. The text
  was still never logged; find the pattern with synthetic examples, fix
  `privacy/pii.py`, add a test.
- **G. Audit log down (P3).** Responses keep flowing and rows wait in a bounded buffer
  (1,000 rows, `configs/request_log.yaml`). Check disk space and the log path; rows beyond the
  buffer are dropped and counted, which breaks the audit trail for that window: record the
  time range.
- **H. Rate-limit spike (P4).** Look for a single client hammering the API; lower the limit
  in `configs/safety.yaml` and restart if needed.

## Retraining trigger

C9: sustained drift or a correction rate above a set level leads to a manual review, then
retraining. Concretely **[assumption]**: product or issue PSI vs the reference period above
0.2 in 3 consecutive periods, or a mean confidence drop above 10% in 2 consecutive periods,
or the correction-rate trigger in playbook E. The review checks the labelled corrections,
decides whether the taxonomy changed, and only then retrains, recalibrates (`make calibrate`
on fresh validation data), re-freezes `configs/final_model.yaml` and redeploys. Retraining is
never automatic.
