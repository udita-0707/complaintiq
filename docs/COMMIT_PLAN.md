# Commit plan (P1 to P4)

Every file in the repo has exactly one owner and one milestone. Each person commits only their own files, under their own `git config user.name` / `user.email`, with the script in `scripts/commit_plan/`. No script pushes, uses `--author` or `--force`.

## How it works

1. Someone pushes the full current tree once to a branch `import/all-files` (it is never merged; it is only a source of files).
2. Stages are merged into `main` in the order below. Each stage branches from the latest `origin/main`, takes only its owner's files from `origin/import/all-files`, and commits them. Because each stage only needs what earlier stages merged, every branch builds and its tests pass on its own.
3. The owner runs `scripts/commit_plan/pN.sh <stage>`, runs `make test` and `make lint`, pushes and opens a pull request (the script prints the exact commands). Copy `scripts/commit_plan/` outside the clone first and run it with the clone as the current directory, because the scripts only reach `main` in step 8. After the merge, the next stage starts from the updated `main`.
4. `BLOCKED_EMAIL_DOMAINS` (default `valura.ai`) stops a commit under a work email. Override with `BLOCKED_EMAIL_DOMAINS="a.com b.com"`.

**Co-authors.** Where a teammate helped on someone else's file, add a `Co-authored-by: Name <email>` trailer (set `COAUTHOR="Name <email>"` when running the script, or amend the message before pushing). Only assign a file to someone who actually worked on it and can explain it in the viva. If the owners below do not match who really wrote a file, change this plan and the scripts before anyone runs them.

## Merge order

| Step | Owner | Milestone | Branch | Command | Depends on step |
|---|---|---|---|---|---|
| 1 | P2 | M1 | `feat/spec-docs` | `scripts/commit_plan/p2.sh m1` | nothing |
| 2 | P3 | M1 | `feat/model-config` | `scripts/commit_plan/p3.sh m1` | nothing |
| 3 | P4 | M1 | `feat/scaffold` | `scripts/commit_plan/p4.sh m1` | 1 (Dockerfile copies README.md), 2 (API reads model.yaml, thresholds.yaml) |
| 4 | P1 | M2 | `feat/data-core` | `scripts/commit_plan/p1.sh m2-core` | 3 |
| 5 | P3 | M2 | `feat/privacy` | `scripts/commit_plan/p3.sh m2` | 3 |
| 6 | P2 | M2 | `feat/data-analysis` | `scripts/commit_plan/p2.sh m2-analysis` | 4 (stats.py and figures.py import data.split) |
| 7 | P1 | M2 | `feat/data-tests` | `scripts/commit_plan/p1.sh m2-tests` | 4 and 6 (two tests in test_data.py import data.analysis) |
| 8 | P4 | M2 | `feat/data-pipeline` | `scripts/commit_plan/p4.sh m2` | 4, 5, 6 (build.py imports analysis, figures, stats and privacy.pii) |
| 9 | P2 | M2 | `feat/m2-reports` | `scripts/commit_plan/p2.sh m2-reports` | 8 (reports are outputs of make data) |

## M1: brief, spec and walking skeleton

| Step | File | Owner | Branch | Suggested commit message |
|---|---|---|---|---|
| 1 | `docs/SPEC.md` | P2 | `feat/spec-docs` | `docs: add M1 brief, PRD and tech spec` |
| 1 | `README.md` | P2 | `feat/spec-docs` | `docs: add README and contributor rules` |
| 1 | `CLAUDE.md` | P2 | `feat/spec-docs` | `docs: add README and contributor rules` |
| 1 | `notebooks/.gitkeep` | UNASSIGNED → P2 (proposed) | `feat/spec-docs` | `chore: add notebooks and reports placeholders` |
| 1 | `reports/.gitkeep` | P2 | `feat/spec-docs` | `chore: add notebooks and reports placeholders` |
| 2 | `configs/model.yaml` | P3 | `feat/model-config` | `feat(config): add predictor selector and confidence threshold tau` |
| 2 | `configs/thresholds.yaml` | P3 | `feat/model-config` | `feat(config): add predictor selector and confidence threshold tau` |
| 3 | `pyproject.toml` | P4 | `feat/scaffold` | `build: add pyproject, Makefile and ignore files` |
| 3 | `Makefile` | P4 | `feat/scaffold` | `build: add pyproject, Makefile and ignore files` |
| 3 | `.gitignore` | P4 | `feat/scaffold` | `build: add pyproject, Makefile and ignore files` |
| 3 | `.dockerignore` | P4 | `feat/scaffold` | `build: add pyproject, Makefile and ignore files` |
| 3 | `src/complaintiq/__init__.py` | P4 | `feat/scaffold` | `feat: add package skeleton and config loader` |
| 3 | `src/complaintiq/config.py` | P4 | `feat/scaffold` | `feat: add package skeleton and config loader` |
| 3 | `src/complaintiq/data/__init__.py` | P4 | `feat/scaffold` | `feat: add package skeleton and config loader` |
| 3 | `src/complaintiq/eval/__init__.py` | P4 | `feat/scaffold` | `feat: add package skeleton and config loader` |
| 3 | `src/complaintiq/models/__init__.py` | P4 | `feat/scaffold` | `feat: add package skeleton and config loader` |
| 3 | `src/complaintiq/monitoring/__init__.py` | P4 | `feat/scaffold` | `feat: add package skeleton and config loader` |
| 3 | `src/complaintiq/privacy/__init__.py` | P4 | `feat/scaffold` | `feat: add package skeleton and config loader` |
| 3 | `src/complaintiq/serving/__init__.py` | P4 | `feat/scaffold` | `feat(serving): add triage API with stub predictor, confidence gate and router` |
| 3 | `src/complaintiq/serving/app.py` | P4 | `feat/scaffold` | `feat(serving): add triage API with stub predictor, confidence gate and router` |
| 3 | `src/complaintiq/serving/schemas.py` | P4 | `feat/scaffold` | `feat(serving): add triage API with stub predictor, confidence gate and router` |
| 3 | `src/complaintiq/serving/predictor.py` | P4 | `feat/scaffold` | `feat(serving): add triage API with stub predictor, confidence gate and router` |
| 3 | `src/complaintiq/serving/gate.py` | P4 | `feat/scaffold` | `feat(serving): add triage API with stub predictor, confidence gate and router` |
| 3 | `src/complaintiq/serving/router.py` | P4 | `feat/scaffold` | `feat(serving): add triage API with stub predictor, confidence gate and router` |
| 3 | `configs/routing.yaml` | P4 | `feat/scaffold` | `feat(serving): add triage API with stub predictor, confidence gate and router` |
| 3 | `tests/test_gate.py` | UNASSIGNED → P4 (proposed) | `feat/scaffold` | `test(serving): add confidence gate and API tests` |
| 3 | `tests/test_api.py` | P4 | `feat/scaffold` | `test(serving): add confidence gate and API tests` |
| 3 | `docker/Dockerfile` | P4 | `feat/scaffold` | `ci: add Dockerfile, compose file and CI workflow` |
| 3 | `docker/docker-compose.yml` | P4 | `feat/scaffold` | `ci: add Dockerfile, compose file and CI workflow` |
| 3 | `.github/workflows/ci.yml` | P4 | `feat/scaffold` | `ci: add Dockerfile, compose file and CI workflow` |

## M2: data pipeline, privacy and data report

| Step | File | Owner | Branch | Suggested commit message |
|---|---|---|---|---|
| 4 | `configs/data.yaml` | P1 | `feat/data-core` | `feat(data): add data config and raw data preparation script` |
| 4 | `scripts/prepare_raw_data.py` | P1 | `feat/data-core` | `feat(data): add data config and raw data preparation script` |
| 4 | `docs/data_provenance.md` | P1 | `feat/data-core` | `feat(data): add data config and raw data preparation script` |
| 4 | `src/complaintiq/data/load.py` | P1 | `feat/data-core` | `feat(data): add column-limited loader and text cleaning` |
| 4 | `src/complaintiq/data/clean.py` | P1 | `feat/data-core` | `feat(data): add column-limited loader and text cleaning` |
| 4 | `src/complaintiq/data/taxonomy.py` | P1 | `feat/data-core` | `feat(data): add product and issue taxonomy mappings` |
| 4 | `configs/product_mapping.yaml` | P1 | `feat/data-core` | `feat(data): add product and issue taxonomy mappings` |
| 4 | `configs/issue_mapping.yaml` | P1 | `feat/data-core` | `feat(data): add product and issue taxonomy mappings` |
| 4 | `src/complaintiq/data/priority.py` | P1 | `feat/data-core` | `feat(data): add priority labels and time/random splits` |
| 4 | `configs/severity_issues.yaml` | P1 | `feat/data-core` | `feat(data): add priority labels and time/random splits` |
| 4 | `src/complaintiq/data/split.py` | P1 | `feat/data-core` | `feat(data): add priority labels and time/random splits` |
| 5 | `src/complaintiq/privacy/pii.py` | P3 | `feat/privacy` | `feat(privacy): add PII scrubbing and leak report` |
| 5 | `tests/test_privacy.py` | P3 | `feat/privacy` | `test(privacy): add scrubbing, Luhn and leak report tests` |
| 6 | `src/complaintiq/data/stats.py` | P2 | `feat/data-analysis` | `feat(data): add per-split statistics` |
| 6 | `src/complaintiq/data/analysis.py` | P2 | `feat/data-analysis` | `feat(data): add distribution shift analysis` |
| 6 | `src/complaintiq/data/figures.py` | P2 | `feat/data-analysis` | `feat(data): add report figures` |
| 7 | `tests/test_data.py` | P1 | `feat/data-tests` | `test(data): add cleaning, priority, split and taxonomy tests` |
| 8 | `src/complaintiq/data/pipeline.py` | P4 | `feat/data-pipeline` | `feat(data): add pipeline and build entry points for make data` |
| 8 | `src/complaintiq/data/build.py` | P4 | `feat/data-pipeline` | `feat(data): add pipeline and build entry points for make data` |
| 8 | `tests/test_router.py` | P4 | `feat/data-pipeline` | `test(serving): check routing covers every taxonomy product` |
| 8 | `.github/CODEOWNERS` | UNASSIGNED → P4 (proposed) | `feat/data-pipeline` | `chore: add CODEOWNERS and per-person commit scripts` |
| 8 | `scripts/commit_plan/p1.sh` | UNASSIGNED → P4 (proposed) | `feat/data-pipeline` | `chore: add CODEOWNERS and per-person commit scripts` |
| 8 | `scripts/commit_plan/p2.sh` | UNASSIGNED → P4 (proposed) | `feat/data-pipeline` | `chore: add CODEOWNERS and per-person commit scripts` |
| 8 | `scripts/commit_plan/p3.sh` | UNASSIGNED → P4 (proposed) | `feat/data-pipeline` | `chore: add CODEOWNERS and per-person commit scripts` |
| 8 | `scripts/commit_plan/p4.sh` | UNASSIGNED → P4 (proposed) | `feat/data-pipeline` | `chore: add CODEOWNERS and per-person commit scripts` |
| 9 | `reports/m2_data_stats.md` | P2 | `feat/m2-reports` | `docs(reports): add M2 data stats, mapping review and figures` |
| 9 | `reports/m2_mapping_review.md` | P2 | `feat/m2-reports` | `docs(reports): add M2 data stats, mapping review and figures` |
| 9 | `reports/figures/high_rate_by_year.png` | P2 | `feat/m2-reports` | `docs(reports): add M2 data stats, mapping review and figures` |
| 9 | `reports/figures/narrative_length_hist.png` | P2 | `feat/m2-reports` | `docs(reports): add M2 data stats, mapping review and figures` |
| 9 | `reports/figures/product_class_by_split.png` | P2 | `feat/m2-reports` | `docs(reports): add M2 data stats, mapping review and figures` |
| 9 | `reports/figures/top15_issues_train_vs_test.png` | P2 | `feat/m2-reports` | `docs(reports): add M2 data stats, mapping review and figures` |
| 9 | `docs/COMMIT_PLAN.md` | UNASSIGNED → P2 (proposed) | `feat/m2-reports` | `docs: add team commit plan` |

## M3 (placeholder, files do not exist yet)

| File | Owner | Branch | Suggested commit message |
|---|---|---|---|
| `src/complaintiq/models/baseline.py` | P2 | `feat/baseline` | `feat(models): add TF-IDF + linear baseline` |
| `src/complaintiq/eval/metrics.py` | P2 | `feat/eval-metrics` | `feat(eval): add macro-F1, per-class and priority recall metrics` |
| `experiment logger (e.g. src/complaintiq/eval/tracking.py)` | P2 | `feat/experiment-logging` | `feat(eval): add MLflow experiment logging` |
| `src/complaintiq/models/transformer.py` | P3 | `feat/transformer` | `feat(models): add fine-tuned transformer classifier` |

## M4 (placeholder, files do not exist yet)

| File | Owner | Branch | Suggested commit message |
|---|---|---|---|
| `src/complaintiq/models/calibrate.py` | P3 | `feat/calibration` | `feat(models): add confidence calibration and tau selection` |
| `eval robustness scripts` | P3 | `feat/robustness` | `feat(eval): add robustness and shift evaluation` |
| `ONNX export script` | P3 | `feat/onnx-export` | `feat(models): add ONNX export and parity check` |

## M5 (placeholder, files do not exist yet)

| File | Owner | Branch | Suggested commit message |
|---|---|---|---|
| `src/complaintiq/monitoring/**` | P4 | `feat/monitoring` | `feat(monitoring): add drift and confidence monitoring` |
| `UI files` | P4 | `feat/ui` | `feat(ui): add triage review UI` |
| `deploy files` | P4 | `feat/deploy` | `build: add deployment configuration` |

## M6 (placeholder, files do not exist yet)

Nothing assigned yet. Add rows here when the M6 deliverables are defined in docs/SPEC.md.

## Counts

| Owner | M1 | M2 | Total |
|---|---|---|---|
| P1 | 0 | 12 | 12 |
| P2 | 5 | 10 | 15 |
| P3 | 2 | 2 | 4 |
| P4 | 23 | 8 | 31 |
| **All** | 30 | 32 | 62 |

## Unassigned and flags

Files not covered by the ownership rules, with the proposed owner used in the scripts (confirm before running):

- `notebooks/.gitkeep` → P2
- `tests/test_gate.py` → P4
- `.github/CODEOWNERS` → P4
- `docs/COMMIT_PLAN.md` → P2
- `scripts/commit_plan/p1.sh` → P4
- `scripts/commit_plan/p2.sh` → P4
- `scripts/commit_plan/p3.sh` → P4
- `scripts/commit_plan/p4.sh` → P4

Decisions and flags:

- `src/complaintiq/privacy/__init__.py` matches both "privacy/** (P3)" and "__init__ files (P4)". It is the M1 placeholder created with the other empty packages, so it is assigned to P4 in the scaffold. Move it to P3 if P3 wrote it.
- `tests/test_data.py` mixes areas: `test_jensen_shannon_bounds` and `test_shift_tests_detects_shift` test P2's `data/analysis.py`; the rest test P1's clean, priority, split and taxonomy code. Suggested split: move those two tests into a new `tests/test_analysis.py` owned by P2 and committed in step 6, then `tests/test_data.py` can move into P1's step 4. Until the split, `tests/test_data.py` is committed by P1 in its own step 7, after P2's analysis is merged.
- `tests/test_router.py` (P4) imports P1's `data.taxonomy`, so it is committed in M2 (step 8), not with the M1 scaffold.
- `pyproject.toml` and `Makefile` were created in M1 and extended in M2 (data extras, `make data` targets). They are committed once, in their current form, in the M1 scaffold.
