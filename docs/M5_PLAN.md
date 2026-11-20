# M5 plan: deployment and monitoring

SPEC C13: **M5 (weeks 10-11)**: deployed API, performance measurements, monitoring plan, failure handling. **Definition of done:** the public URL works; the load test and failure tests are documented.

**Team for M5 and M6:** only **P3 Udita (@udita-0707)** and **P4 Aman (@AmanKumar1411)** build, commit and review. Each always reviews the other's pull requests. P1 Kalash and P2 Dally own no M5 files, but they must still be able to explain M5 in the viva (M6 crib sheets).

## Step 0: close M4 first (Udita and Aman, on Udita's Mac)

M5 serves the frozen model, so M4 must be closed before the M5 session starts. Run everything in `~/Desktop/complaintiq`, Udita's clone: it is the only clone with `data/` and `models/`.

### 0.1 Label the error sample (both of you, about 1-2 hours)

`reports/m4/error_sample_LOCAL.csv` (gitignored; it contains narratives) has 240 rows: 120 `issue` errors and 120 `product` errors. Fill the `error_category` column of every row with exactly one of:

`label ambiguity` · `multi-topic narrative` · `short or uninformative` · `taxonomy mismatch` · `genuine model error`

Suggested split: Udita labels the `issue` rows and Aman labels the `product` rows. Open the file in Numbers or Excel, save it as CSV under the same name, and do not change any other column. Then:

```bash
cd ~/Desktop/complaintiq && source .venv/bin/activate
make error-summary          # rewrites the human-category section of reports/m4/error_analysis.md
```

The summary rejects any category outside the list.

### 0.2 Decide about the M4 improvement iterations

The three iterations improved val-B macro-F1 when measured alone (`reports/m4/improvement_iterations.md`). **Decided: freeze the current model as it is and report the iterations as measured improvements and future work.** (Not chosen: Adopting any of them means retraining or re-scoring, re-running `make calibrate`, `make eval-report` and `make benchmark`, and updating `configs/final_model.yaml`, all before the freeze.)

### 0.3 Freeze (Udita commits, Aman reviews)

```bash
cd ~/Desktop/complaintiq
git switch main && git pull origin main
git switch -c chore/m4-freeze
# edit configs/final_model.yaml: frozen_date: <YYYY-MM-DD>   frozen_by: "Udita, Aman"
git add configs/final_model.yaml reports/m4/error_analysis.md docs/M5_PLAN.md docs/M6_PLAN.md
git commit -m "chore(m4): freeze the final model, add error categories and M5/M6 plans"
make test && make lint
git push -u origin chore/m4-freeze
# PR: https://github.com/udita-0707/complaintiq/compare/main...chore/m4-freeze   reviewer: Aman
```

### 0.4 One-shot test evaluation (Udita, after 0.3 is merged)

```bash
cd ~/Desktop/complaintiq
git switch main && git pull origin main
git status --short                     # must print NOTHING (the script refuses on a dirty tree)
CIQ_ALLOW_TEST=1 make final-eval CONFIRM=yes
git switch -c docs/m4-test-results
git add reports/m4/test_results.md reports/m4/results/test_results.json reports/experiments/m4/final_test.csv
git commit -m "docs(m4): add one-shot test results for the frozen model"
git push -u origin docs/m4-test-results
# PR: .../compare/main...docs/m4-test-results   reviewer: Aman. After merge:
git switch main && git pull origin main && git tag m4-final && git push origin m4-final
```

This runs **once**. If it fails, do not delete `reports/m4/test_results.md` and run it again; tell the team what failed. The script refuses to run while the report exists.

## Where we start (state after M4)

| Area | Already there | Missing for M5 |
|---|---|---|
| API | `/v1/triage`, `/v1/feedback`, `/health`, `/v1/model`; calibrated gate (tau, temperatures from `configs/thresholds.yaml`); router | `/metrics` (FR6); PII scrub is not called in `/v1/triage` (FR2, TODO in `app.py`) |
| Failure handling | 400 on length, 422 schema, 503 without a model, generic 500 | fallback chain, 2 s timeout → HUMAN_REVIEW, quality and language check, log-store-down buffering (C8) |
| Audit and feedback | feedback kept in memory | request log (US5), persistent feedback and correction rate (US4) |
| Monitoring | empty `monitoring/` package | Prometheus metrics, drift job, monitoring plan (C9) |
| UI | none | reviewer UI (FR7) |
| Packaging | Dockerfile with core dependencies only; `models/` is dockerignored | image that actually serves the frozen model; public deployment |
| CI | lint + Docker build | tests + `pip-audit` (C10, C11) |
| Performance | in-process benchmark and local API latency (M4) | concurrent load test against the deployed URL |

## Decisions to make before pasting the prompt

The recommended option is first.

| Decision | Recommended | Alternative |
|---|---|---|
| Host (**decided**) | Hugging Face Spaces, Docker SDK: free CPU, model files go into the Space repo via git-lfs and never into GitHub | Render or Fly.io: the model has to come from a release asset or a bucket |
| How the image gets the model (**decided**) | A Space-only build context that copies the frozen `models/...` directory | Download from a private HF model repo at startup, with a token in env |
| New dependencies | Move scikit-learn, numpy, scipy, joblib into a `serve` extra; use `prometheus-client` and `streamlit` from the existing pinned extras | Add `slowapi` or `langdetect` (new, needs approval) |
| Rate limiting and language check | Small in-repo implementations: a token bucket, and an ASCII/stopword English heuristic | Libraries |
| Timeout reason in the response | Optional nullable `reason` field (additive; old clients still work) | Keep schemas frozen and log the reason only |

## Owners (two people)

| Owner | Area | Main files |
|---|---|---|
| P3 Udita | Privacy and input safety; audit log and feedback; drift monitoring and monitoring plan | PII scrub before inference and logging, post-scrub PII counter, quality heuristic (gibberish or non-English → human review), CORS and rate limiting from config, `docs/security.md`; `serving/request_log.py` (SQLite: request hash, labels, scores, version, route, reason; no text), persistent `/v1/feedback`, correction rate, buffered writes when the store is down; `monitoring/drift.py`, val replayed month by month, `reports/m5/drift_report.md`, `docs/monitoring_plan.md` |
| P4 Aman | Runtime, metrics, deployment, performance, reviewer UI | `monitoring/metrics.py` and `/metrics`, fallback chain (transformer → baseline → 503), 2 s timeout → HUMAN_REVIEW, Docker image that serves the model, CI running tests and `pip-audit`, deployment files and `docs/deployment.md`, concurrent load test, failure tests, `ui/app.py` (Streamlit), `reports/m5/deployment.md` |

## Stage order (reviewer is always the other person)

| Step | Owner | Branch | Depends on | Reviewer |
|---|---|---|---|---|
| 1 | Aman (P4) | `chore/m5-gitignore-config` (`*.sqlite`, `*.db`, `.env`, M5 config keys) | Step 0 merged | Udita |
| 2 | Udita (P3) | `feat/m5-input-safety` | 1 | Aman |
| 3 | Udita (P3) | `feat/m5-request-log` | 1, 2 (only scrubbed text reaches logging) | Aman |
| 4 | Udita (P3) | `feat/m5-drift-monitoring` | 1 | Aman |
| 5 | Aman (P4) | `feat/m5-runtime-metrics` | 2, 3 (metrics read their counters) | Udita |
| 6 | Aman (P4) | `feat/m5-ui-deploy-loadtest` | 5 | Udita |
| 7 | Aman (P4) | `docs/m5-commit-plan` → tag `m5` | 6 | Udita |

## Design notes

- **Test split:** M5 stays closed to it. The only test numbers are the M4 one-shot results (`reports/m4/test_results.md`).
- **Drift replay:** val is replayed month by month as stand-in production traffic, so drift can be shown without a live user base.
- **Deploy commands:** the session prepares the deployment but doesn't push or deploy. Aman runs the printed commands under his own account.
- **Base branch:** `main` equals the M4 tree after Step 0, so `import/m5-files` branches from `origin/main`. The M5 commit plan covers the files that differ from that commit.

## M5 prompt

Paste this into a new Claude Code session after Step 0 is merged and Udita has run `git switch main && git pull origin main && git switch -c import/m5-files` in `~/Desktop/complaintiq`. Host and model delivery are already decided below.

```text
PRIMARY MODEL: serve the model recorded in configs/final_model.yaml (model_dir, thresholds). If frozen_date is still null, stop and tell me; do not unfreeze, retrain or recalibrate.
Use /Users/udita/Desktop/complaintiq/.venv/bin/python for every Python command (e.g. `make test PYTHON=.venv/bin/python`). Confirm with `pwd` and `git branch --show-current` that you are in ~/Desktop/complaintiq on import/m5-files.
HOST: Hugging Face Spaces (Docker SDK)   MODEL DELIVERY: Space repo via git-lfs (the frozen models/ directory goes only into the Space repo, never into GitHub)
TEAM: M5 is built by two people only: P3 Udita (@udita-0707) and P4 Aman (@AmanKumar1411). Each reviews the other's pull requests.

Read CLAUDE.md and docs/SPEC.md (B3 US1-US6, B4 FR1-FR7, B7, C7, C8, C9, C10, C11, C13) and docs/M5_PLAN.md. Do NOT run git add, commit or push, and do NOT push images or deploy anything yourself: prepare everything, then print the exact deploy commands for Aman. Do not add or change dependencies without asking (ask before slowapi, langdetect, evidently, or moving packages into core/serve extras). Never print narratives or raw rows; aggregates and complaint_ids only. Never log raw request text, not even in tests' captured logs.

GOAL
Build ALL of M5 (Deployment and Monitoring) in this session. Checklist: deployed API, performance measurements, monitoring plan, failure handling. Definition of done: public URL works; load test and failure tests documented. Branch import/m5-files was created from origin/main after the M4 close-out (freeze + one-shot test results) was merged. Then produce a commit plan for the two owners covering only the M5 files.

PREFLIGHT (stop and tell me if any fails)
1. Branch is import/m5-files, `git diff origin/main` is empty, make test and make lint pass with PYTHON=.venv/bin/python. Record `git rev-parse --short origin/main` as BASE_REF.
2. configs/final_model.yaml has frozen_date and frozen_by filled; its thresholds equal configs/thresholds.yaml; model_dir exists locally with product, issue and priority; reports/m4/test_results.md exists. If test_results.md is missing, continue but mark every test-dependent statement TODO; never run final_test_eval.py yourself.
3. Read reports/m4/{calibration_report,inference_benchmark,api_latency,evaluation_report,test_results}.md, src/complaintiq/serving/*, src/complaintiq/privacy/pii.py, docker/*, .github/workflows/ci.yml, configs/*.yaml.

HARD RULES
- THE TEST SPLIT STAYS CLOSED. Nothing in M5 reads test.parquet or sets CIQ_ALLOW_TEST. Drift replay uses train (reference) and val (replayed month by month as "production weeks") only.
- Response schemas stay backward compatible: only additive, optional fields (e.g. a nullable `reason`) are allowed, and only if I chose that option above; flag them in the report.
- PII scrub runs before inference and before any logging (FR2). Logs and the request store hold request hash, labels, scores, model_version, route, reason, latency; never text.
- Every number comes from a script output saved under reports/m5/ or a logged run. Mark missing things TODO. No invented results. Report negative results (e.g. a missed latency target on the free tier).
- Config in configs/*.yaml (new keys allowed, never rename existing ones). Fixed seeds. Secrets only via env vars; none in git, none in the image.
- No file edits outside the owner lists below without saying so in the report.

BUILD BY OWNER
P3 (Udita): privacy and input safety, audit log and feedback, drift monitoring
- Call privacy.pii.scrub in /v1/triage before predict and before logging; count post-scrub residual hits (C8 "PII detected post-scrub") as a metric; never log matches.
- Input quality heuristic (config thresholds): too few alphabetic tokens / gibberish / likely non-English -> HUMAN_REVIEW with reason (not 400, except FR1 length limits). No new dependency unless I approve.
- Security (C10): CORS origins from config (no wildcard in deployment config), simple per-client rate limit from config (429), request body size limit, pip-audit target. Document "human-in-the-loop; never triggers adverse customer outcomes" in docs/security.md.
- src/complaintiq/serving/request_log.py: SQLite store (path from config) for US5 audit rows; feedback rows linked by request_id (US4); correction-rate query. If the store is unavailable: serve the response, buffer rows in a bounded in-memory/local file buffer, increment a counter, retry (C8 "log store down"). Wire /v1/feedback to the store; 404 for unknown request_id only if I approve that behaviour change, otherwise store and flag.
- src/complaintiq/monitoring/drift.py: PSI and KL of predicted product/issue distribution vs the training label distribution; confidence mean and quantiles; input length and vocabulary (out-of-vocabulary rate vs the frozen vectorizer) drift. Pure functions + a CLI that replays val month by month and writes reports/m5/drift_report.md (alert flags from the C9 thresholds: PSI > 0.2, confidence drop > 10%).
- docs/monitoring_plan.md: every C9 signal with its source (/metrics name or drift job), threshold, owner, response playbook and retraining trigger; only numbers from reports.
- tests/test_input_safety.py (synthetic; includes PII strings that must never appear in captured logs), tests/test_request_log.py (tmp SQLite, failure injection), tests/test_drift.py (synthetic).
P4 (Aman): runtime, metrics, deployment, performance, reviewer UI
- src/complaintiq/monitoring/metrics.py + GET /metrics (Prometheus text): request count, error count, latency histogram, route counts (fallback rate), predicted product counts, confidence histogram, PII-residual counter, log-buffer size, model_version info.
- Fallback chain (C8): configured predictor -> baseline -> 503; model_version flags fallback; inference timeout (2 s, config) -> HUMAN_REVIEW with reason. Tests with fake slow/failing predictors.
- Docker: a serve image that includes the frozen model (by the MODEL DELIVERY option above) and scikit-learn etc. via an approved extra; non-root; healthcheck; image size reported. Keep the stub image path working for CI.
- CI: run pytest (synthetic only) + ruff + pip-audit + docker build.
- Deployment files for HOST (e.g. Space README/Dockerfile, render.yaml or fly.toml) and docs/deployment.md with exact commands; do not deploy yourself.
- ui/app.py (Streamlit, FR7): paste text, see product/issue top-3/priority/route/team/confidence, submit a correction; talks to the API URL from env. Never stores text.
- scripts/load_test_remote.py: concurrent load (httpx asyncio, no new deps) at 1/5/10 concurrency against a URL from argv; p50/p95/p99, error rate, throughput -> reports/m5/load_test.md. Run it locally against docker compose now; leave the public-URL run as a command for Aman (TODO with placeholders until he runs it).
- scripts/failure_tests.py + reports/m5/failure_tests.md: every C8 row exercised against the local container (short text, gibberish, non-English sample, predictor failure via config, timeout via test hook, log store down, PII in input) with observed status/route/reason.
- reports/m5/deployment.md: URL (TODO until deployed), image digest, model_version, thresholds, cold-start time, memory.

RUNS (this machine)
Docker build and compose run locally; local load test and failure tests against the container; drift replay on train/val. Each run under 20 minutes. Log runs through log_run into reports/experiments/m5/ with owner "team-m5-session".

CHECKS
make test and make lint green; grep confirms nothing reads test.parquet except the M4 final_test_eval.py; grep confirms no logger call receives request text; `git status --short` shows no data, models, *_LOCAL.csv, .env or SQLite files (add *.sqlite / *.db to .gitignore via P4).

COMMIT PLAN
Write docs/COMMIT_PLAN_M5.md and scripts/commit_plan_m5/p3.sh (Udita) and p4.sh (Aman) in the same style as scripts/commit_plan_m4/*.sh, taking files from origin/import/m5-files. Cover ONLY files that differ from BASE_REF (`git diff --name-status BASE_REF` plus untracked), one owner each (P3 or P4 only), UNASSIGNED listed with a proposal, mixed-area tests flagged. List separately every file changed in BOTH M5 and an earlier milestone and say which of the two owners commits it. Use the stage order in docs/M5_PLAN.md (branch names, dependencies; the reviewer is always the other person). The scripts refuse to run until origin/main contains reports/m4/test_results.md and docs/COMMIT_PLAN_M4.md. Add the Co-authored-by note (Kalash or Dally may be added as co-authors only if they really helped) and the final `git tag m5` command.

FINAL REPORT
Files created and changed per owner, run results as numbers from reports (local latency at each concurrency, failure-test outcomes, drift flags, image size), TODOs (public URL run, anything awaiting dependency approval, transformer/ONNX path), deviations from this prompt, and the exact commands Udita and Aman should run next (including Aman's deploy and public load-test commands). Nothing committed or pushed.
```
