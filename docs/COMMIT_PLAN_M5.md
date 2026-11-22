# M5 commit plan (deployment and monitoring)

All M5 files were produced in one shared working session on top of the M4 close-out
(`origin/main` = tag `m4-final`, commit `f61cae3`, the BASE_REF of this plan). Only two people
build, commit and review M5: **P3 Udita (@udita-0707)** and **P4 Aman (@AmanKumar1411)**. The
reviewer is always the other person. Each person commits only their own files under their own
`git config user.name` / `user.email`, using `scripts/commit_plan_m5/pN.sh <stage>`. No script
pushes, uses `--author` or `--force`. The process is the same as `docs/COMMIT_PLAN_M4.md`.

## Before you start

- **The M4 close-out must be on `main`.** Every M5 script checks that
  `reports/m4/test_results.md` and `docs/COMMIT_PLAN_M4.md` are on `origin/main` and stops
  otherwise.
- **Each stage checks its dependencies.** A stage refuses to run until the files of the
  stages it depends on are on `origin/main`, so merge in the order below.

## How it works

1. **Udita builds the import branch once, on her Mac** (the only clone with `data/` and
   `models/`):
   1. `git switch main && git pull origin main && git switch -c import/m5-files`
   2. Copy the M5 files into the clone (the handoff zip's `apply_m5_files.sh` does this and
      checks that exactly the 58 listed files changed).
   3. Run everything in `docs/deployment.md` section 1 (tests, lint, drift replay, Space
      staging with the model manifest, pip-audit, local container load test, failure tests,
      local deployment record). The runs overwrite the TODO placeholders under
      `reports/m5/` and append rows to `reports/experiments/m5/*.csv`.
   4. `git add` the listed files only, check that `git status --short` shows no `data/`,
      `models/`, `build/`, `runtime/`, `*.sqlite`, `*.db`, `.env` or `*_LOCAL.csv`, then
      commit once and `git push -u origin import/m5-files`. This branch is never merged; it is
      only a source of files.
2. **Aman deploys from the import branch** (`docs/deployment.md` sections 2-5) and pushes one
   more commit to `import/m5-files` with the public deployment record and the public load
   test. Stages 1-5 do not need to wait for this; stage 6 does.
3. The stages below are merged into `main` in order. Each stage branches from the latest
   `origin/main` and takes only its owner's files from `origin/import/m5-files`
   (`git checkout origin/import/m5-files -- <files>`), prints them and commits them with the
   messages below. Every branch passes `make test` and `make lint` on its own once the
   earlier stages are merged.
4. Copy `scripts/commit_plan_m5/` outside the clone (`cp -r scripts/commit_plan_m5 /tmp/`)
   and run `/tmp/commit_plan_m5/pN.sh <stage>` with your clone as the current directory. The
   scripts only reach `main` in step 7. Then run `make test` and `make lint`, push, and open
   a pull request: the script prints the exact commands for
   https://github.com/udita-0707/complaintiq.
5. `BLOCKED_EMAIL_DOMAINS` (default `valura.ai`) stops a commit under a work email. Override it
   with `BLOCKED_EMAIL_DOMAINS="a.com b.com"`.

**Co-authors.** Where someone helped on another person's file, add a
`Co-authored-by: Name <email>` trailer: set `COAUTHOR="Name <email>"` when running the script,
or amend the message before pushing. P1 Kalash or P2 Dally may be added as co-authors only if
they really helped; they own no M5 files but must be able to explain M5 in the viva.

**Experiment runs** in `reports/experiments/m5/*.csv` carry `owner=team-m5-session`. They come
from one shared session and are not attributed to individuals. They live in a subdirectory so
`scripts/compare_runs.py` (which reads only `reports/experiments/*.csv`) never ranks them.

## Merge order

| Step | Owner | Branch | Command | Depends on step | Reviewer |
|---|---|---|---|---|---|
| 1 | P4 Aman | `chore/m5-gitignore-config` | `p4.sh m5-gitignore-config` | M4 close-out | P3 Udita |
| 2 | P3 Udita | `feat/m5-input-safety` | `p3.sh m5-input-safety` | 1 (order) | P4 Aman |
| 3 | P3 Udita | `feat/m5-request-log` | `p3.sh m5-request-log` | 1 (`config.resolve_path`), 2 | P4 Aman |
| 4 | P3 Udita | `feat/m5-drift-monitoring` | `p3.sh m5-drift` | 1 (`config.resolve_path`) | P4 Aman |
| 5 | P4 Aman | `feat/m5-runtime-metrics` | `p4.sh m5-runtime` | 2, 3 (`app.py` wires both) | P3 Udita |
| 6 | P4 Aman | `feat/m5-ui-deploy-loadtest` | `p4.sh m5-ui-deploy` | 5; public results pushed to the import branch | P3 Udita |
| 7 | P4 Aman | `docs/m5-commit-plan` | `p4.sh m5-commit-plan`, then `git tag m5` | 6 | P3 Udita |

Steps 3 and 4 are independent of each other once 1 and 2 are merged.

## Files, owners and commit messages

| Step | File | Owner | Commit message |
|---|---|---|---|
| 1 | `.gitignore` | P4 | `chore: gitignore the M5 request log and runtime directory` |
| 1 | `pyproject.toml` | P4 | `build: add the serve extra and move prometheus-client into core` |
| 1 | `src/complaintiq/config.py` | P4 | `feat(config): resolve config paths from COMPLAINTIQ_ROOT for the container` |
| 2 | `src/complaintiq/privacy/pii.py` | P3 | `feat(privacy): count redactions and residual PII hits; import polars lazily` |
| 2 | `src/complaintiq/serving/input_quality.py` | P3 | `feat(serving): add input quality check for short, gibberish and non-English text` |
| 2 | `src/complaintiq/serving/security.py` | P3 | `feat(serving): add body size limit, per-client rate limit and CORS origin checks` |
| 2 | `configs/safety.yaml` | P3 | `feat(config): add input safety and security settings` |
| 2 | `tests/test_input_safety.py` | P3 | `test(serving): cover scrub counts, quality reasons and security middlewares` |
| 2 | `docs/security.md` | P3 | `docs: add security and privacy notes (human in the loop, no adverse outcomes)` |
| 3 | `src/complaintiq/serving/request_log.py` | P3 | `feat(serving): add SQLite audit log with feedback, correction rate and store-down buffer` |
| 3 | `configs/request_log.yaml` | P3 | `feat(config): add request log settings` |
| 3 | `tests/test_request_log.py` | P3 | `test(serving): cover audit rows, feedback linking, correction rate and failure injection` |
| 4 | `src/complaintiq/monitoring/drift.py` | P3 | `feat(monitoring): add PSI/KL, confidence and input drift with a month-by-month val replay` |
| 4 | `src/complaintiq/monitoring/__init__.py` | P3 | (same commit as drift.py) |
| 4 | `configs/monitoring.yaml` | P3 | `feat(config): add drift monitoring thresholds and replay settings` |
| 4 | `tests/test_drift.py` | P3 | `test(monitoring): cover drift statistics and a synthetic replay` |
| 4 | `docs/monitoring_plan.md` | P3 | `docs: add monitoring plan with signals, thresholds, owners and playbooks` |
| 4 | `reports/m5/drift_report.md` | P3 | `docs(m5): add drift replay report and run log` |
| 4 | `reports/m5/results/drift.json` | P3 | (same commit) |
| 4 | `reports/experiments/m5/drift.csv` | P3 | (same commit) |
| 5 | `src/complaintiq/monitoring/metrics.py` | P4 | `feat(monitoring): add Prometheus metrics and request middleware` |
| 5 | `src/complaintiq/serving/runtime.py` | P4 | `feat(serving): add inference timeout, runtime fallback and env-gated failure hooks` |
| 5 | `src/complaintiq/serving/predictor.py` | P4 | `feat(serving): load-time fallback chain, COMPLAINTIQ_PREDICTOR override, no stub in deployment` |
| 5 | `src/complaintiq/serving/schemas.py` | P4 | `feat(serving): add optional reason field to the triage response` |
| 5 | `src/complaintiq/serving/app.py` | P4 | `feat(serving): wire scrub, quality check, guarded inference, audit log, metrics and security` |
| 5 | `configs/serving.yaml` | P4 | `feat(config): serve the frozen baseline with a 2 s timeout and no stub fallback` |
| 5 | `configs/model.yaml` | P4 | (same commit) |
| 5 | `tests/test_api.py` | P4 | `test(serving): select the stub explicitly and expect the reason field` |
| 5 | `tests/test_serving_calibrated.py` | P4 | (same commit) |
| 5 | `tests/test_api_runtime.py` | P4 | `test(serving): cover PII-free logs, quality routing, timeout, fallback, metrics, 429, 413, store down` |
| 6 | `docker/Dockerfile` | P4 | `build: serve the stub explicitly in the dev/CI image` |
| 6 | `docker/docker-compose.serve.yml` | P4 | `build: add the Hugging Face Space image for the frozen model` |
| 6 | `deploy/hf_space/Dockerfile` | P4 | (same commit) |
| 6 | `deploy/hf_space/README.md` | P4 | (same commit) |
| 6 | `ui/app.py` | P4 | `feat(ui): add Streamlit reviewer console and its Space image` |
| 6 | `ui/ciq_client.py` | P4 | (same commit) |
| 6 | `ui/.streamlit/config.toml` | P4 | (same commit) |
| 6 | `deploy/hf_ui_space/Dockerfile` | P4 | (same commit) |
| 6 | `deploy/hf_ui_space/README.md` | P4 | (same commit) |
| 6 | `scripts/build_space.py` | P4 | `feat(scripts): stage the Spaces with model manifest checks` |
| 6 | `scripts/load_test_remote.py` | P4 | `feat(scripts): add concurrent load test` |
| 6 | `scripts/failure_tests.py` | P4 | `feat(scripts): add C8 failure tests and the deployment record` |
| 6 | `scripts/deployment_report.py` | P4 | (same commit) |
| 6 | `tests/test_deploy_scripts.py` | P4 | `test(scripts): cover Space staging, load test, failure scenarios, deployment record and UI client` |
| 6 | `.github/workflows/ci.yml` | P4 | `ci: run tests, pip-audit and a Space image smoke test` |
| 6 | `Makefile` | P4 | `build: add M5 Makefile targets` |
| 6 | `docs/deployment.md` | P4 | `docs: add deployment guide with exact commands` |
| 6 | `reports/m5/load_test.md` | P4 | `docs(m5): add load test report and run log` |
| 6 | `reports/m5/results/load_test_local.json` | P4 | (same commit) |
| 6 | `reports/m5/results/load_test_public.json` | P4 | (same commit) |
| 6 | `reports/experiments/m5/load_test.csv` | P4 | (same commit) |
| 6 | `reports/m5/failure_tests.md` | P4 | `docs(m5): add failure test report and run log` |
| 6 | `reports/m5/results/failure_tests.json` | P4 | (same commit) |
| 6 | `reports/experiments/m5/failure_tests.csv` | P4 | (same commit) |
| 6 | `reports/m5/deployment.md` | P4 | `docs(m5): add deployment record and model manifest` |
| 6 | `reports/m5/results/deployment_local.json` | P4 | (same commit) |
| 6 | `reports/m5/results/deployment_public.json` | P4 | (same commit) |
| 6 | `reports/m5/results/model_manifest.json` | P4 | (same commit) |
| 7 | `docs/COMMIT_PLAN_M5.md` | P4 | `docs: add M5 commit plan and per-person scripts` |
| 7 | `scripts/commit_plan_m5/p3.sh` | P4 | (same commit) |
| 7 | `scripts/commit_plan_m5/p4.sh` | P4 | (same commit) |

## Counts

| Owner | Files |
|---|---|
| P3 Udita | 17 |
| P4 Aman | 44 |
| UNASSIGNED | 0 |
| Files with two owners | 0 |
| Total (`git diff --name-status f61cae3` plus new files) | 61 |

P4 has more files because deployment produces many small files (Dockerfiles, Space cards,
report placeholders). By substance the split is closer: P3 owns the privacy, safety, audit
and drift logic; P4 owns the runtime, packaging, scripts and UI.

## Flags

- **`src/complaintiq/serving/app.py` (P4) wires P3's code.** One owner per file, and `app.py`
  imports P3's scrub, quality check, security middlewares and request log (steps 2-3), so it
  can only merge after them, in step 5. Udita reviews step 5 and should check that wiring.
  Between steps 2 and 5, `main` has P3's modules but `/v1/triage` does not call them yet.
- **`configs/model.yaml`** is a P3 file in `.github/CODEOWNERS`, but the M5 change
  (`predictor: baseline`) is part of the serving switch and goes with step 5 (P4). CODEOWNERS
  requests P3 as reviewer, who is step 5's reviewer anyway.
- **Run results committed by P4 but produced on Udita's Mac.** The local load test, failure
  tests, local deployment record and the model manifest (`make space`) are run in the shared
  session on Udita's clone, because only it has the model. They back P4's scripts, so they
  merge with step 6. The drift report backs P3's code and merges with step 4.
- **Mixed-area tests:**
  - `tests/test_api_runtime.py` (P4) exercises P3's scrub, quality routing, rate limit and
    request log through the wired app. It must merge after steps 2 and 3 (step 5).
  - `tests/test_deploy_scripts.py` (P4) imports helpers from `tests/test_api_runtime.py` and
    runs P3's quality check on the load-test texts. Step 6.
  - `tests/test_drift.py` (P3) fits a tiny P2 baseline (`models/baseline.py`, on `main` since
    M3).
  - `tests/test_api.py` and `tests/test_serving_calibrated.py` (M1/M4 tests, P4) change in step
    5: the repo config now serves the baseline, so they select the stub with
    `COMPLAINTIQ_PREDICTOR=stub` and expect the optional `reason` field.
- **Never committed:** `models/`, `data/`, `build/` (Space staging, contains the model),
  `runtime/` and `*.sqlite` (request log), `.env`, `reports/m4/*_LOCAL.csv`.
- **Test split:** M5 never reads it. Test numbers come only from `reports/m4/test_results.md`.

## Files changed in both M5 and an earlier milestone

The M5 owner commits the M5 version on top of what is on `main`.

| File | Earlier owner | M5 owner | M5 step |
|---|---|---|---|
| `.gitignore` | P4 (M1, M4) | P4 | 1 |
| `pyproject.toml` | P4 (M1) | P4 | 1 |
| `src/complaintiq/config.py` | P4 (M1) | P4 | 1 |
| `src/complaintiq/privacy/pii.py` | P3 (M2) | P3 | 2 |
| `src/complaintiq/monitoring/__init__.py` | P4 (M1 placeholder) | P3 | 4 |
| `src/complaintiq/serving/app.py` | P4 (M1, M3, M4) | P4 | 5 |
| `src/complaintiq/serving/predictor.py` | P4 (M1, M3, M4) | P4 | 5 |
| `src/complaintiq/serving/schemas.py` | P4 (M1) | P4 | 5 |
| `configs/serving.yaml` | P4 (M3, M4) | P4 | 5 |
| `configs/model.yaml` | P3 (M1) | P4 | 5 |
| `tests/test_api.py` | P4 (M1) | P4 | 5 |
| `tests/test_serving_calibrated.py` | P4 (M4) | P4 | 5 |
| `docker/Dockerfile` | P4 (M1) | P4 | 6 |
| `.github/workflows/ci.yml` | P4 (M1) | P4 | 6 |
| `Makefile` | P4 (M1-M4) | P4 | 6 |

## Deviations from docs/M5_PLAN.md

- **Config files ship with their feature**, not all in step 1: `safety.yaml` (step 2),
  `request_log.yaml` (3), `monitoring.yaml` (4), `serving.yaml` / `model.yaml` (5). Step 1
  carries `.gitignore`, `pyproject.toml` and the `COMPLAINTIQ_ROOT` path helper that steps
  3-6 need. Each owner commits the config they can explain.
- **Dependencies (approved in the M5 session):** new `serve` extra with scikit-learn, numpy,
  scipy, joblib and **polars** (`models/baseline.py` imports polars, so the plan's list was not
  enough); `prometheus-client` moved into core; `streamlit` stays in the `ui` extra. No
  `slowapi`, `langdetect` or `evidently`: the rate limit, language check and drift job are
  small in-repo implementations.
- **Schema:** one additive optional field, `reason`, in the triage response. Feedback for an
  unknown `request_id` is stored and flagged, not rejected with 404 (the free-tier log restarts
  empty, so a 404 would drop valid corrections).
- **UI deployment:** a second Docker Space (`complaintiq-ui`) that calls the API from its
  server, so the API keeps CORS closed.
- **Load test client:** `httpx2` (the pinned dev dependency that provides an asyncio client),
  as the plan's "httpx asyncio, no new deps" intended.
- **Short texts:** inputs under 20 words (the training minimum, `configs/data.yaml: min_words`)
  go to human review with reason `short_text`. Demo inputs need realistic paragraphs; the
  threshold is one value in `configs/safety.yaml`.

## After step 7

```bash
git switch main && git pull origin main && git tag m5 && git push origin m5
```
