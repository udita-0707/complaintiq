# Deployment (M5)

SPEC C2 (deployment), C8, C11, C13 M5. Owner: P4 (Aman). Host: Hugging Face Spaces, Docker
SDK, free CPU. Two Spaces:

| Space | What | Port | Built from |
|---|---|---|---|
| `<hf-user>/complaintiq` | the API with the frozen model | 7860 | `make space` -> `build/hf_space/` |
| `<hf-user>/complaintiq-ui` | Streamlit reviewer console | 8501 | `make ui-space` -> `build/hf_ui_space/` |

Replace `<hf-user>` with Aman's Hugging Face username everywhere below. Public URLs follow
the pattern `https://<hf-user>-complaintiq.hf.space` and
`https://<hf-user>-complaintiq-ui.hf.space`.

The model files go **only** into the API Space repo (git-lfs), never into GitHub. The staging
directory `build/` is gitignored.

## Prerequisites

- Docker Desktop running; `git lfs` installed (`brew install git-lfs`, then `git lfs install`).
- Python 3.11 venv. Udita: `.venv/bin/pip install -e ".[dev,data,serve,ui]"` (the drift job
  needs the data extra). Aman: `.venv/bin/pip install -e ".[dev,serve,ui]"`.
- Run every `make` target with `PYTHON=.venv/bin/python` (or activate the venv).
- A Hugging Face account for Aman with an access token that has **write** scope. Git asks for
  it as the password on the first push; do not put it in a file or a command line.

## Environment variables

| Variable | Where | Meaning |
|---|---|---|
| `COMPLAINTIQ_ROOT` | image (`/app`) | base for relative paths in configs (models, runtime) |
| `COMPLAINTIQ_CONFIG_DIR` | image (`/app/configs`) | configs directory |
| `COMPLAINTIQ_PREDICTOR` | dev/CI image (`stub`), tests | overrides `configs/model.yaml: predictor` |
| `COMPLAINTIQ_REQUEST_LOG` | optional | request-log path (`:memory:` for tests) |
| `COMPLAINTIQ_LOG_SALT` | Space **secret** | HMAC key for the text hash in the audit log |
| `COMPLAINTIQ_LOADTEST_TOKEN` | Space **secret**, compose env | lets load tests skip the rate limit |
| `CIQ_LOADTEST_TOKEN` | your shell | the same token, sent by `scripts/load_test_remote.py` |
| `CIQ_API_URL` | UI Space **variable** | API base URL the reviewer UI calls |
| `COMPLAINTIQ_ENABLE_TEST_HOOKS` | failure tests only | enables injected delay/failure; never on the Space |

## 1. Local runs (Udita, in `~/Desktop/complaintiq` on `import/m5-files`)

Only this clone has `data/` and `models/`. Every result below is written under `reports/m5/`
and `reports/experiments/m5/` and is committed with the import branch.

```bash
cd ~/Desktop/complaintiq
make test lint PYTHON=.venv/bin/python
make drift PYTHON=.venv/bin/python               # several minutes: reports/m5/drift_report.md
make space PYTHON=.venv/bin/python               # checks the freeze, writes the model manifest
make audit PYTHON=.venv/bin/python               # pip-audit of the image's dependencies

# Run the deployable image (same Dockerfile as the Space) on localhost:8000, in the background
export COMPLAINTIQ_LOADTEST_TOKEN=$(openssl rand -hex 16)
export CIQ_LOADTEST_TOKEN=$COMPLAINTIQ_LOADTEST_TOKEN
docker compose -f docker/docker-compose.serve.yml up --build -d
curl -s http://127.0.0.1:8000/health          # repeat until "model_loaded":true

make load-test-remote URL=http://127.0.0.1:8000 LABEL=local PYTHON=.venv/bin/python
make failure-tests URL=http://127.0.0.1:8000 IMAGE=complaintiq-serve:local PYTHON=.venv/bin/python
make deployment-report LABEL=local IMAGE=complaintiq-serve:local PYTHON=.venv/bin/python
make ui URL=http://127.0.0.1:8000 PYTHON=.venv/bin/python   # optional: the UI on :8501, Ctrl+C to stop
docker compose -f docker/docker-compose.serve.yml down
```

`make space` writes `reports/m5/results/model_manifest.json` (SHA-256 of each model file) the
first time. Commit it: every later `make space`, on any machine, must match it.

If a run fails, do not edit its report by hand; fix the cause and run it again, or leave the
TODO and say why in the pull request.

## 2. Get the model to Aman

Pick one:

- **A (simplest).** Aman deploys from Udita's Mac. He types his own Hugging Face token when git
  asks; nothing is stored if the macOS keychain prompt is declined.
- **B.** Udita zips `models/baseline/tfidf_sgd_alpha2e-6_conv/` (about 42 MB) and shares it
  privately (a private drive link, never GitHub or a public chat). Aman unzips it to the
  same path in his clone. `make space` then verifies every file against the committed
  manifest and refuses if one differs.

## 3. Deploy the API Space (Aman)

1. On https://huggingface.co/new-space create `complaintiq`: SDK **Docker**, template
   **Blank**, hardware **CPU basic (free)**, visibility Public.
2. In the Space: Settings, Variables and secrets, add two **secrets**:
   `COMPLAINTIQ_LOG_SALT` and `COMPLAINTIQ_LOADTEST_TOKEN`, each a random value
   (`openssl rand -hex 16`). Keep the token value for the load test.
3. Push the staged directory:

```bash
cd ~/Desktop/complaintiq                       # or Aman's clone with the model (option B)
git switch import/m5-files && git pull
make space PYTHON=.venv/bin/python             # must print "manifest": "verified"
git clone https://huggingface.co/spaces/<hf-user>/complaintiq ../hf-space-api
rsync -a --delete --exclude .git --exclude .ciq_space_staging build/hf_space/ ../hf-space-api/
cd ../hf-space-api
git lfs install
git add -A
git lfs ls-files                               # must list the five model files
git commit -m "Deploy ComplaintIQ API (baseline-tfidf_sgd_alpha2e-6_conv-80a3ba969565)"
git push                                       # username: <hf-user>, password: the token
```

4. Watch the Space's Logs tab until the build finishes, then:

```bash
curl -s https://<hf-user>-complaintiq.hf.space/health
# {"status":"ok","model_loaded":true,"model_version":"baseline-tfidf_sgd_alpha2e-6_conv-80a3ba969565-cal"}
```

`"status":"degraded"` means the model did not load; the usual cause is git-lfs pointer files
instead of the real joblib files (`git lfs ls-files` empty). Fix and push again.

## 4. Deploy the reviewer UI Space (Aman)

1. Create `complaintiq-ui`: SDK **Docker**, template **Blank**, CPU basic, Public.
2. Settings, Variables and secrets, add the **variable** `CIQ_API_URL` =
   `https://<hf-user>-complaintiq.hf.space`.
3. Push:

```bash
cd ~/Desktop/complaintiq
make ui-space PYTHON=.venv/bin/python
git clone https://huggingface.co/spaces/<hf-user>/complaintiq-ui ../hf-space-ui
rsync -a --delete --exclude .git --exclude .ciq_space_staging build/hf_ui_space/ ../hf-space-ui/
cd ../hf-space-ui && git add -A && git commit -m "Deploy ComplaintIQ reviewer UI" && git push
```

Open `https://<hf-user>-complaintiq-ui.hf.space`, load an example, triage it and send a
correction.

## 5. Public measurements (Aman)

Restart the API Space (Settings, Factory reboot), then immediately:

```bash
cd ~/Desktop/complaintiq
make deployment-report LABEL=public URL=https://<hf-user>-complaintiq.hf.space \
  UI_URL=https://<hf-user>-complaintiq-ui.hf.space PYTHON=.venv/bin/python
export CIQ_LOADTEST_TOKEN=<the COMPLAINTIQ_LOADTEST_TOKEN secret value>
make load-test-remote URL=https://<hf-user>-complaintiq.hf.space LABEL=public PYTHON=.venv/bin/python
```

Optional HTTP failure tests against the public URL (the rate-limit scenario throttles your IP
for a minute): `.venv/bin/python scripts/failure_tests.py --url https://<hf-user>-complaintiq.hf.space`.

Commit the regenerated files to the import branch so step 6 of `docs/COMMIT_PLAN_M5.md` picks
them up:

```bash
git add reports/m5/deployment.md reports/m5/results/deployment_public.json \
  reports/m5/load_test.md reports/m5/results/load_test_public.json \
  reports/experiments/m5/load_test.csv
git commit -m "docs(m5): add public deployment record and public load test"
git push origin import/m5-files
```

Report the numbers as measured, including a missed latency target on the free tier.

## Rollback and pause

- Roll back: in the Space repo, `git revert HEAD && git push` (rebuilds the previous version).
- Pause: Space Settings, Pause. The free tier also sleeps after inactivity; the first request
  after that waits for a cold start (measured in `reports/m5/deployment.md`).

## CI

`.github/workflows/ci.yml` runs on every pull request: ruff, pytest (synthetic data only),
`pip-audit` on the image's dependencies, the dev/CI image build (stub predictor), and the real
Space image built with a tiny synthetic model (`make space-ci`) plus a smoke test of
`/health`, `/v1/triage` and `/metrics`. CI never has the frozen model, `data/` or the test
split.
