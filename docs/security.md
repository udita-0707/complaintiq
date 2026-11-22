# Security and privacy (M5)

SPEC C10, B4 FR1-FR2, B7 Privacy, C8. Owner: P3 (Udita). Settings live in
`configs/safety.yaml` and `configs/request_log.yaml`; the API reads them once at startup.

## Human in the loop

ComplaintIQ is decision support. It suggests a product, issue, priority and destination team;
a person handles every complaint. The system never decides a complaint's outcome, never
contacts a customer, and never triggers an adverse customer outcome (SPEC A7, B2). Every
uncertain or unusual case goes to the Human Review Queue with a stated reason, and agents can
correct any prediction through `POST /v1/feedback`.

## Complaint text and PII

- **Scrub first (FR2).** `/v1/triage` runs `privacy.pii.scrub_with_counts` before anything
  else touches the text. The model, the quality check, the audit log and the metrics only
  see the scrubbed text. Patterns: email addresses, US phone numbers, SSNs, Luhn-valid card
  numbers and digit runs of 9 or more. Each match becomes `[REDACTED]`.
- **Counted, never shown.** `ciq_pii_redactions_total` counts scrubbed spans. After scrubbing,
  every pattern runs again; any remaining hit increments `ciq_pii_residual_total` (C8 "PII
  detected post-scrub"), which should stay at 0 and is an immediate alert otherwise. Matched
  strings are never logged, stored or returned.
- **No raw text in logs.** Log lines carry the request ID, model version, route, reason, team
  and latency only. `tests/test_api_runtime.py` sends synthetic PII through the API and checks
  that none of it reaches the captured logs, the response, the model input or the SQLite
  file; `scripts/failure_tests.py` repeats the check on the container logs.
- **Audit log without text (US5).** `serving/request_log.py` stores a hash of the scrubbed
  text, labels, scores, model version, route, reason and latency. The hash is HMAC-SHA256
  keyed by the `COMPLAINTIQ_LOG_SALT` secret; without it the hash is plain SHA-256, which can
  be guessed for short texts, so the deployed Space must set the secret.
- **Known gap.** Person names and street addresses are not detected (regex only, no NER), so
  they are not scrubbed. CFPB narratives are pre-redacted by the CFPB, which limits but does
  not remove the risk for new, unredacted input. The reviewer UI asks users to paste
  synthetic or already-public text.

## Input controls

| Control | Behaviour | Config |
|---|---|---|
| Length (FR1) | fewer than 20 or more than 10,000 characters: 400 | `serving/schemas.py` |
| Schema | malformed body: 422 | Pydantic |
| Body size | bodies over 131,072 bytes: 413 before parsing | `security.max_body_bytes` |
| Quality heuristic (C8) | fewer than 20 words (`short_text`), mostly junk tokens or no English function words (`low_quality_text`), mostly non a-z letters or Spanish/French function words (`non_english`): still scored, but `route=HUMAN_REVIEW` with the reason | `input_quality` |

The quality check is a cheap heuristic in `serving/input_quality.py`, not a language model.
It can miss languages close to English and flags English keyword lists without function
words; both outcomes send the case to a person, never reject it.

## Abuse controls

- **Rate limit (C10).** A per-client-IP token bucket on `/v1/triage` and `/v1/feedback`:
  60 requests per minute, bursts of 20. Over the limit: 429 with `Retry-After`, counted in
  `ciq_rate_limited_total`. The bucket lives in process memory: it resets on restart and is
  per replica (one replica on the free Space).
- **Client IP behind the proxy.** The Space image runs uvicorn with `--proxy-headers`, so the
  client IP comes from `X-Forwarded-For`. A client that can set that header itself may evade
  the per-IP limit; acceptable for a demo, not for production.
- **Load-test bypass.** A request whose `x-ciq-loadtest-token` header equals the
  `COMPLAINTIQ_LOADTEST_TOKEN` env var skips the limit, so load tests measure latency instead
  of 429s. Unset variable = no bypass. The comparison is constant-time.
- **CORS.** `security.cors_origins` is empty: no CORS headers, so browsers on other origins
  cannot call the API from JavaScript. A wildcard is refused at startup. The reviewer UI calls
  the API from its server, so it needs no CORS entry.

## Secrets

Only environment variables, set as Hugging Face Space secrets; never in git, never in the
image, never in logs. `.env` files are gitignored.

| Secret | Used for |
|---|---|
| `COMPLAINTIQ_LOG_SALT` | HMAC key of the text hash in the audit log |
| `COMPLAINTIQ_LOADTEST_TOKEN` | load-test bypass of the rate limit |

## Errors and failure injection

Unhandled errors return a generic 500 without stack traces (C7). A missing or failing model
returns 503, never fixed dummy labels: `serving.yaml: allow_stub_fallback` is false in the
repo. The failure-test hooks in `serving/runtime.py` (injected delay or failure) are read only
when `COMPLAINTIQ_ENABLE_TEST_HOOKS=1`, which is never set on the Space; when active, the API
logs a warning at startup.

## Model artifacts

The baseline is stored as joblib files, which unpickle arbitrary objects on load. The API
only loads the locally built frozen model. Before every deployment, `scripts/build_space.py`
checks the files against the SHA-256 checksums in `reports/m5/results/model_manifest.json`
and refuses to stage anything that differs.

## Dependencies and containers

- Every dependency is pinned in `pyproject.toml`. CI runs `pip-audit` on the core and serve
  pins (the packages in the deployed image); `make audit` runs the same check locally.
- Images use `python:3.11-slim`, run as the non-root user with uid 1000, and contain no
  secrets.

## Free-tier limitations

The Space's disk is not persistent: the audit log and the metrics counters restart empty
after every restart or sleep. The Space is public, including `/metrics`, which exposes
aggregate counts only (no text, no request IDs).
