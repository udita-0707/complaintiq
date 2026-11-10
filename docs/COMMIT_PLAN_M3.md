# M3 commit plan (baseline and model development)

All M3 files were produced in one shared working session. Each person now commits only their own files under their own `git config user.name` / `user.email`, using `scripts/commit_plan_m3/pN.sh <stage>`. No script pushes, uses `--author` or `--force`. The process is the same as `docs/COMMIT_PLAN.md`.

## How it works

1. One person pushes the full M3 working tree once to the branch `import/m3-files`. It is never merged; it is only a source of files. Never add `data/` or `models/` (both are gitignored).
2. The stages below are merged into `main` in order. Each stage branches from the latest `origin/main` and takes only its owner's files from `origin/import/m3-files` (`git checkout origin/import/m3-files -- <files>`). It prints the files, then commits them with the suggested messages. Every branch passes `make test` and `make lint` on its own once the earlier stages are merged.
3. Copy `scripts/commit_plan_m3/` outside the clone (`cp -r scripts/commit_plan_m3 /tmp/`) and run `/tmp/commit_plan_m3/pN.sh <stage>` with your clone as the current directory. The scripts only reach `main` in step 6. Then run `make test` and `make lint`, push, and open a pull request: the script prints the exact commands for https://github.com/udita-0707/complaintiq.
4. `BLOCKED_EMAIL_DOMAINS` (default `valura.ai`) stops a commit under a work email. Override it with `BLOCKED_EMAIL_DOMAINS="a.com b.com"`.

**Co-authors.** Where someone helped on another person's file, add a `Co-authored-by: Name <email>` trailer: set `COAUTHOR="Name <email>"` when running the script, or amend the message before pushing. Only assign a file to someone who worked on it and can explain it in the viva. If the owners below do not match who really did the work, change this plan and the scripts before anyone runs them.

**Experiment runs** in `reports/experiments/*.csv` carry `owner=team-m3-session`. They came from one shared session and are not attributed to individuals.

## Merge order

| Step | Owner | Branch | Command | Depends on step | Reviewer |
|---|---|---|---|---|---|
| 1 | P1 Kalash | `feat/m3-training-data` | `p1.sh m3-data` | nothing | P2 Dally |
| 2 | P2 Dally | `feat/m3-metrics` | `p2.sh m3-metrics` | 1 (order only; no code dependency) | P1 Kalash |
| 3 | P2 Dally | `feat/m3-baseline` | `p2.sh m3-baseline` | 1 (`training_data`), 2 (`metrics`, `tracking`) | P3 Udita |
| 4 | P3 Udita | `feat/m3-transformer` | `p3.sh m3-transformer` | 1, 2 (`transformer.py` imports `training_data`, `metrics`, `tracking`) | P2 Dally |
| 5 | P4 Aman | `feat/m3-serving` | `p4.sh m3-serving` | 3 (test loads `models.baseline`; Makefile targets), 4 (`TransformerPredictor`, `train-transformer`) | P1 Kalash |
| 6 | P4 Aman | `docs/m3-commit-plan` | `p4.sh m3-commit-plan` | 5 | P3 Udita |

## Files, owners and commit messages

| Step | File | Owner | Suggested commit message |
|---|---|---|---|
| 1 | `src/complaintiq/data/training_data.py` | P1 | `feat(data): add M3 split loader with test guard, stratified sampling and data version` |
| 1 | `tests/test_training_data.py` | P1 | `test(data): cover sampling, test-split guard, priors and data version` |
| 1 | `reports/m3/data_utils_notes.md` | P1 | `docs(m3): add training-data utility notes` |
| 2 | `src/complaintiq/eval/metrics.py` | P2 | `feat(eval): add metrics with fixed-label-set macro-F1, bootstrap CI, slices and priority metrics` |
| 2 | `src/complaintiq/eval/tracking.py` | P2 | `feat(eval): add CSV experiment log with header migration` |
| 2 | `tests/test_metrics.py` | P2 | `test(eval): add metrics and experiment-log tests` |
| 3 | `configs/baseline.yaml` | UNASSIGNED → P2 (proposed) | `feat(models): add TF-IDF baseline with SGD variants, Complement NB and val rescoring` |
| 3 | `src/complaintiq/models/baseline.py` | P2 | `feat(models): add TF-IDF baseline with SGD variants, Complement NB and val rescoring` |
| 3 | `tests/test_baseline.py` | P2 | `test(models): add baseline, Complement NB and convergence tests on synthetic text` |
| 3 | `scripts/compare_runs.py` | P2 | `feat(scripts): add experiment-log comparison with superseded rows and ranking` |
| 3 | `reports/experiments/baseline.csv` | P2 | `docs(m3): add experiment logs, baseline val report and model comparison` |
| 3 | `reports/experiments/transformer.csv` | P2 | `docs(m3): add experiment logs, baseline val report and model comparison` |
| 3 | `reports/m3/baseline_val_report.md` | P2 | `docs(m3): add experiment logs, baseline val report and model comparison` |
| 3 | `reports/m3/model_comparison.md` | P2 | `docs(m3): add experiment logs, baseline val report and model comparison` |
| 4 | `configs/model.yaml` | P3 | `feat(config): add DistilBERT hyperparameters to model config` |
| 4 | `src/complaintiq/models/transformer.py` | P3 | `feat(models): add DistilBERT fine-tuning with head+tail truncation and prior correction` |
| 4 | `tests/test_transformer.py` | P3 | `test(models): add transformer pure-function tests` |
| 4 | `reports/m3/transformer_notes.md` | P3 | `docs(m3): add GPU run instructions for the transformer` |
| 5 | `configs/serving.yaml` | P4 | `feat(serving): select stub, baseline or transformer predictor from config with stub fallback` |
| 5 | `src/complaintiq/serving/predictor.py` | P4 | same as above |
| 5 | `src/complaintiq/serving/app.py` | P4 | same as above |
| 5 | `tests/test_serving_predictor.py` | P4 | `test(serving): load a tiny baseline through config and test stub fallback` |
| 5 | `Makefile` | P4 | `build: add M3 train/eval Makefile targets and pin scipy in the data extra` |
| 5 | `pyproject.toml` | P4 | same as above |
| 6 | `docs/COMMIT_PLAN_M3.md` | P4 | `docs: add M3 commit plan and per-person scripts` |
| 6 | `scripts/commit_plan_m3/p1.sh` … `p4.sh` | P4 | same as above |

## Counts

| Owner | Files |
|---|---|
| P1 Kalash | 3 |
| P2 Dally | 10 (+1 UNASSIGNED proposed: `configs/baseline.yaml`) |
| P3 Udita | 4 |
| P4 Aman | 11 |
| Files with two owners | 0 |

## Unassigned and flags

- `configs/baseline.yaml` is not on any list in the M3 brief. It is proposed for **P2** because it holds only baseline and candidate hyperparameters. It is a separate file so that the baseline (step 3) does not depend on `configs/model.yaml` changes, which merge later in step 4.
- **Mixed-area test:** `tests/test_serving_predictor.py` (P4) fits a tiny P2 baseline inside the test to check serving's config loading. It must merge after step 3.
- `tests/test_baseline.py` (P2) imports the serving `Predictor` protocol, which is already on `main`. `tests/test_metrics.py` covers both `metrics.py` and `tracking.py`, which have the same owner.
- `.github/CODEOWNERS` assigns all of `/reports/` to P2, so P2 is requested as a reviewer on the P1 and P3 notes under `reports/m3/`. It was not changed in M3.
- `reports/experiments/transformer.csv` holds only the CPU smoke run and its rescore rows. Rows from the GPU run are added later to the same file (see `reports/m3/transformer_notes.md`).
- **Metric definition change (stage 2):** `val_macro_f1` is now macro over the classes with val support, and a new column `val_macro_f1_all_labels` was added to the experiment log. Rows logged before the change are kept unedited and marked superseded by `rescored: fixed label set` rows. `tracking.log_run` migrates an older CSV header in place: old values are kept and the new column is blank for them.
