# Deployment, failure handling and monitoring (M5)

Details: docs/deployment.md, docs/security.md, docs/monitoring_plan.md. Measured results:
reports/m5/ (merged and tagged `m5`). **Status:** the service was built, containerized and measured
on a local machine: load test, failure tests, deployment record and drift replay are complete.
**There is no public deployment:** the team found that Hugging Face Docker Spaces require a paid plan,
so the local container run is the deployment record (reports/m5/deployment.md). The M5 definition of
done, "public URL works", is therefore not met.

## Service

FastAPI, one process. `POST /v1/triage` runs, in order:

1. the FR1 length check (400 outside 20-10,000 characters);
2. the PII scrub (emails, US phone numbers, SSNs, Luhn-valid card numbers, digit runs of 9 or
   more), so the model, the logs and the audit store only ever see scrubbed text (FR2);
3. an input quality heuristic: fewer than 20 words (the training minimum), mostly junk tokens, no
   English function words, or Spanish/French function words outweighing English ones send the
   case to human review with a reason (it is still scored);
4. the model in a thread pool with a 2-second timeout; a timeout returns HUMAN_REVIEW with reason
   `timeout`;
5. the confidence gate (tau 0.803386 on calibrated product confidence) and the routing table,
   with the fraud override for HIGH-priority fraud or identity issues;
6. an audit row in SQLite (hash of the scrubbed text, labels, scores, model version, route,
   reason, latency; never text) and Prometheus metrics.

The response is the SPEC C7 schema plus one additive optional field, `reason`
(`low_confidence`, `short_text`, `low_quality_text`, `non_english` or `timeout`). `POST
/v1/feedback` links an agent's correction to the request; corrections for unknown request IDs are
stored and flagged rather than rejected. `GET /health`, `/v1/model` and `/metrics` complete FR6.

## Failure handling (SPEC C8)

| failure | behaviour |
|---|---|
| empty, too short or too long text | 400 |
| short, gibberish or non-English text | HUMAN_REVIEW with a reason |
| model slower than 2 s | HUMAN_REVIEW, reason `timeout` |
| transformer fails (not deployed) | baseline answers, model_version flagged `-fallback` |
| baseline missing or failing | 503; the deployed image never serves fixed dummy labels |
| audit log unavailable | the response is served; rows wait in a bounded buffer (1,000 rows) |
| PII after the scrub | counted (`ciq_pii_residual_total`), never logged |
| too many requests | 429 with Retry-After (per-IP token bucket, 60 a minute, bursts of 20) |
| request body over 131,072 bytes | 413 before parsing |

## Deployment

The service is packaged as two Docker images prepared for Hugging Face Spaces: the API, with the
frozen model delivered through the Space repo with git-lfs (never through GitHub; a SHA-256 manifest
of the five model files is checked before every build), and a Streamlit reviewer console that calls
the API from its server, so CORS stays closed. Neither was published, because Docker Spaces required a
paid plan; the identical image was run locally with docker compose and measured there. The reviewer
console runs locally with `make ui`. CI runs ruff, the test suite on synthetic data, `pip-audit` on the
image's dependencies, the dev image build and a smoke test of the real Space image built with a tiny
synthetic model.

**Local container record** (reports/m5/deployment.md, one machine):

| measurement | value |
|---|---|
| public API and UI URLs | not deployed (paid plan required) |
| cold start (`docker run` to healthy, model loaded) | 3.4 s |
| resident memory | 313.7 MB |
| image size | 704.3 MB |
| model_version served | `baseline-tfidf_sgd_alpha2e-6_conv-80a3ba969565-cal` (tau 0.8034) |

**Load test** (reports/m5/load_test.md): closed loop, 200 synthetic requests per level after 10
warm-up requests, against the local container.

| concurrent clients | client p50 ms | client p95 ms | client p99 ms | server p95 ms | requests/s | errors |
|---|---|---|---|---|---|---|
| 1 | 12.1 | 13.0 | 13.5 | 10.0 | 82.0 | 0 |
| 5 | 24.7 | 36.8 | 46.1 | 24.0 | 195.3 | 0 |
| 10 | 54.4 | 82.6 | 100.5 | 41.0 | 176.8 | 0 |

The worst client p95 (82.6 ms at 10 clients) is well inside the 300 ms [target]. Throughput peaks
around five clients; at ten, requests queue behind the single worker process, so latency grows while
throughput does not.

**Failure tests** (reports/m5/failure_tests.md): 11 of 11 HTTP scenarios and 5 of 5 injected
container failures passed. Highlights: four synthetic PII strings were redacted with 0 residual and
nothing echoed; a 200 KB body got 413; the first 429 arrived after 11 rapid requests; a missing model
gave 503 with `/health` degraded; an injected 3-second delay returned HUMAN_REVIEW with reason
`timeout` after 2018 ms; with the audit log unwritable the API kept answering and buffered the rows;
the container logs contained none of the planted strings.

## Monitoring (SPEC C9)

| signal | source | alert |
|---|---|---|
| latency p95, error rate | `/metrics` | p95 above 500 ms |
| human-review (fallback) rate | `ciq_triage_route_total` by reason | rise above its reference (0.242 on val-B, 0.274 on test, derived) |
| predicted class distribution | drift job, PSI vs training labels | PSI above 0.2 |
| confidence | drift job, mean calibrated confidence | drop above 10% |
| input drift | drift job, length PSI and out-of-vocabulary rate | length PSI above 0.2 |
| quality | request log, correction rate | rising trend |
| residual PII | `ciq_pii_residual_total` | any |

**Drift replay** (reports/m5/drift_report.md): val replayed month by month (9 months, 2022-09 to
2023-05) against the training reference. Every month was flagged, but the pattern shows why both
comparisons are needed:

- **Against the training labels**, issue PSI was 0.320 to 0.416 (above 0.2 in all 9 months) and
  product PSI 0.162 to 0.242 (above 0.2 in 2022-11, 2022-12 and 2023-04). This is the label shift
  already measured in M2: in 2023-05 the model predicts credit reporting for 0.572 of complaints
  against a training share of 0.405, and "Improper use of your report" for 0.180 against 0.063.
- **Against the first replayed month**, product PSI stayed at or below 0.022: the incoming traffic
  itself was stable over the nine months.
- **Confidence** stayed between 0.867 and 0.882 (no drop near the 10% alert), the auto-route share
  between 0.743 and 0.772, the out-of-vocabulary rate between 0.1085 and 0.1135 (train sample 0.1160),
  and length PSI at or below 0.012.

In production the PSI-vs-train alert would therefore fire from day one and should be re-based on a
recent reference period, while the period-over-period PSI and the confidence signal carry the real
drift information. No Prometheus server or pager was deployed. Retraining is a manual decision after
sustained drift or a rising correction rate (docs/monitoring_plan.md).
