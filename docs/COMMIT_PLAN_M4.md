# M4 commit plan (evaluation and optimization)

All M4 files were produced in one shared working session, stacked on the M3 files. Each person now commits only their own files under their own `git config user.name` / `user.email`, using `scripts/commit_plan_m4/pN.sh <stage>`. No script pushes, uses `--author` or `--force`. The process is the same as `docs/COMMIT_PLAN_M3.md`.

## Before you start

- **Run these scripts only after every M3 stage in `docs/COMMIT_PLAN_M3.md` is merged into `main`.** Every M4 script checks that `docs/COMMIT_PLAN_M3.md` (added by the last M3 stage) is on `origin/main` and stops otherwise.
- M4 code imports M3 code (`models/baseline.py`, `eval/metrics.py`, `eval/tracking.py`, `data/training_data.py`), so a stage cannot pass its tests on a `main` without M3.

## How it works

1. One person pushes the full M4 working tree once to the branch `import/m4-files` (based on `origin/import/m3-files`). It is never merged; it is only a source of files. Never add `data/`, `models/` or `reports/m4/*_LOCAL.csv` (all gitignored; the LOCAL error sample contains complaint narratives).
2. The stages below are merged into `main` in order. Each stage branches from the latest `origin/main` and takes only its owner's files from `origin/import/m4-files` (`git checkout origin/import/m4-files -- <files>`). It prints the files, then commits them with the suggested messages. Every branch passes `make test` and `make lint` on its own once the earlier stages are merged.
3. Copy `scripts/commit_plan_m4/` outside the clone (`cp -r scripts/commit_plan_m4 /tmp/`) and run `/tmp/commit_plan_m4/pN.sh <stage>` with your clone as the current directory. The scripts only reach `main` in step 7. Then run `make test` and `make lint`, push, and open a pull request: the script prints the exact commands for https://github.com/udita-0707/complaintiq.
4. `BLOCKED_EMAIL_DOMAINS` (default `valura.ai`) stops a commit under a work email. Override it with `BLOCKED_EMAIL_DOMAINS="a.com b.com"`.

**Co-authors.** Where someone helped on another person's file, add a `Co-authored-by: Name <email>` trailer: set `COAUTHOR="Name <email>"` when running the script, or amend the message before pushing. Only assign a file to someone who worked on it and can explain it in the viva. If the owners below do not match who really did the work, change this plan and the scripts before anyone runs them.

**Experiment runs** in `reports/experiments/m4/*.csv` carry `owner=team-m4-session`. They came from one shared session and are not attributed to individuals. They live in a subdirectory on purpose: `scripts/compare_runs.py` reads only `reports/experiments/*.csv`, so M4 rows (robustness, calibration, iterations) never enter the M3 model ranking.

## Merge order

| Step | Owner | Branch | Command | Depends on step | Reviewer |
|---|---|---|---|---|---|
| 1 | P4 Aman | `chore/m4-gitignore` | `p4.sh m4-gitignore` | all M3 stages | P1 Kalash |
| 2 | P3 Udita | `feat/m4-calibration` | `p3.sh m4-calibration` | 1 (order only) | P2 Dally |
| 3 | P1 Kalash | `feat/m4-error-analysis` | `p1.sh m4-error-analysis` | 1 (`.gitignore` for the LOCAL sample), 2 (`configs/eval.yaml`) | P3 Udita |
| 4 | P2 Dally | `feat/m4-evaluation` | `p2.sh m4-evaluation` | 2 (`calibrate`: val-A/val-B split, `apply_temperature`, `binary_at`), 3 (`error_analysis.length_bucket`) | P4 Aman |
| 5 | P3 Udita | `feat/m4-inference-benchmark` | `p3.sh m4-benchmark` | 4 (`BaselinePredictor` temperatures) | P1 Kalash |
| 6 | P4 Aman | `feat/m4-serving-freeze` | `p4.sh m4-serving` | 2 (`thresholds.yaml`, `calibrate`), 4 (`BaselinePredictor` options); the Makefile targets call code from 2-5 | P3 Udita |
| 7 | P4 Aman | `docs/m4-commit-plan` | `p4.sh m4-commit-plan` | 6 | P2 Dally |

Reviewers are always a different person from the owner. `.github/CODEOWNERS` was not changed in M4; it requests P2 on everything under `/reports/` and `/docs/`, and P3 on `configs/thresholds.yaml` and `models/calibrate.py`, in addition to the reviewer above.

## Files, owners and commit messages

| Step | File | Owner | Suggested commit message |
|---|---|---|---|
| 1 | `.gitignore` | P4 | `chore: gitignore M4 error samples that contain narratives` |
| 2 | `configs/eval.yaml` | UNASSIGNED → P3 (proposed) | `feat(config): add M4 evaluation config with val-A/val-B split and run settings` |
| 2 | `src/complaintiq/models/calibrate.py` | P3 | `feat(models): add temperature scaling, ECE, tau and priority threshold on val-A` |
| 2 | `tests/test_calibrate.py` | P3 | `test(models): cover calibration, val split, tau and threshold choice on synthetic data` |
| 2 | `configs/thresholds.yaml` | P3 | `feat(config): set tau, temperatures and priority threshold from val-A calibration` |
| 2 | `reports/m4/calibration_report.md` | P3 | `docs(m4): add calibration report, reliability and coverage figures, run log` |
| 2 | `reports/m4/figures/reliability_product.png` | P3 | `docs(m4): add calibration report, reliability and coverage figures, run log` |
| 2 | `reports/m4/figures/reliability_issue.png` | P3 | `docs(m4): add calibration report, reliability and coverage figures, run log` |
| 2 | `reports/m4/figures/coverage_precision_product.png` | P3 | `docs(m4): add calibration report, reliability and coverage figures, run log` |
| 2 | `reports/m4/results/calibration.json` | P3 | `docs(m4): add calibration report, reliability and coverage figures, run log` |
| 2 | `reports/experiments/m4/calibration.csv` | P3 | `docs(m4): add calibration report, reliability and coverage figures, run log` |
| 3 | `src/complaintiq/eval/error_analysis.py` | P1 | `feat(eval): add error sampling, confusion, per-class and slice error statistics` |
| 3 | `tests/test_error_analysis.py` | P1 | `test(eval): cover error sampling, category summary and report helpers` |
| 3 | `reports/m4/error_analysis.md` | P1 | `docs(m4): add automatic error analysis (human categories TODO)` |
| 3 | `docs/data_card.md` | P1 | `docs: add data card from M2 provenance and statistics` |
| 4 | `src/complaintiq/models/baseline.py` | P2 | `feat(models): add calibrated predictor options and add-tasks for saved variants` |
| 4 | `tests/test_baseline.py` | P2 | `test(models): check predictor defaults reproduce M3 and calibration options` |
| 4 | `src/complaintiq/eval/robustness.py` | P2 | `feat(eval): add perturbation robustness, val evaluation report and iterations` |
| 4 | `src/complaintiq/eval/evaluation.py` | P2 (not on the brief's list; proposed) | `feat(eval): add perturbation robustness, val evaluation report and iterations` |
| 4 | `src/complaintiq/models/iterations.py` | P2 (not on the brief's list; proposed) | `feat(eval): add perturbation robustness, val evaluation report and iterations` |
| 4 | `tests/test_robustness.py` | P2 | `test(eval): cover perturbations, paired bootstrap and iteration helpers` |
| 4 | `reports/m4/evaluation_report.md` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/m4/robustness_report.md` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/m4/improvement_iterations.md` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/m4/results/evaluation.json` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/m4/results/robustness.json` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/m4/results/iteration_prior.json` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/m4/results/iteration_consistency.json` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/m4/results/iteration_class_weight.json` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/experiments/m4/training.csv` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/experiments/m4/evaluation.csv` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/experiments/m4/robustness.csv` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 4 | `reports/experiments/m4/iterations.csv` | P2 | `docs(m4): add evaluation, robustness and improvement-iteration reports with run logs` |
| 5 | `scripts/benchmark_inference.py` | P3 | `feat(scripts): add CPU inference benchmark and vocabulary-size study` |
| 5 | `reports/m4/inference_benchmark.md` | P3 | `docs(m4): add inference benchmark report and run log` |
| 5 | `reports/m4/results/benchmark.json` | P3 | `docs(m4): add inference benchmark report and run log` |
| 5 | `reports/experiments/m4/benchmark.csv` | P3 | `docs(m4): add inference benchmark report and run log` |
| 6 | `configs/serving.yaml` | P4 | `feat(serving): gate on calibrated confidence with tau and temperatures from config` |
| 6 | `src/complaintiq/serving/predictor.py` | P4 | `feat(serving): gate on calibrated confidence with tau and temperatures from config` |
| 6 | `src/complaintiq/serving/app.py` | P4 | `feat(serving): gate on calibrated confidence with tau and temperatures from config` |
| 6 | `tests/test_serving_calibrated.py` | P4 | `test(serving): gate with tau on calibrated confidence; pin the M3 test to raw scores` |
| 6 | `tests/test_serving_predictor.py` | P4 | `test(serving): gate with tau on calibrated confidence; pin the M3 test to raw scores` |
| 6 | `configs/final_model.yaml` | P4 | `feat(scripts): add model freeze record and guarded one-shot test evaluation` |
| 6 | `scripts/final_test_eval.py` | P4 | `feat(scripts): add model freeze record and guarded one-shot test evaluation` |
| 6 | `tests/test_final_test_eval.py` | P4 | `test(scripts): cover every final-eval guard without reading the test split` |
| 6 | `scripts/load_test.py` | P4 | `feat(scripts): add local API load test` |
| 6 | `reports/m4/api_latency.md` | P4 | `feat(scripts): add local API load test` |
| 6 | `reports/m4/results/api_latency.json` | P4 | `feat(scripts): add local API load test` |
| 6 | `Makefile` | P4 | `build: add M4 Makefile targets with a confirmed final-eval` |
| 7 | `docs/COMMIT_PLAN_M4.md` | P4 | `docs: add M4 commit plan and per-person scripts` |
| 7 | `scripts/commit_plan_m4/p1.sh` | P4 | `docs: add M4 commit plan and per-person scripts` |
| 7 | `scripts/commit_plan_m4/p2.sh` | P4 | `docs: add M4 commit plan and per-person scripts` |
| 7 | `scripts/commit_plan_m4/p3.sh` | P4 | `docs: add M4 commit plan and per-person scripts` |
| 7 | `scripts/commit_plan_m4/p4.sh` | P4 | `docs: add M4 commit plan and per-person scripts` |

## Counts

| Owner | Files |
|---|---|
| P1 Kalash | 4 |
| P2 Dally | 18 |
| P3 Udita | 14 |
| P4 Aman | 18 |
| of which UNASSIGNED (proposed) | 1 (`configs/eval.yaml` → P3) |
| Files with two owners | 0 |
| Total (matches `git diff --name-status origin/import/m3-files` plus new files) | 54 |

## Unassigned and flags

- **UNASSIGNED → P3 (proposed): `configs/eval.yaml`.** Not on any owner list in the M4 brief. CLAUDE.md requires config in `configs/*.yaml`, and P1, P2 and P3 code all read it (val-A/val-B split, sample sizes, perturbations, benchmark and load-test settings). Proposed for P3 as the M4 lead (SPEC C13) and merged in step 2, the first stage that needs it.
- **Not on the owner lists but needed for P2's deliverables → P2:** `src/complaintiq/eval/evaluation.py` (generates `evaluation_report.md`) and `src/complaintiq/models/iterations.py` (runs and reports the improvement iterations). Both only read the primary model and val.
- **Run logs and machine-readable results** (`reports/experiments/m4/*.csv`, `reports/m4/results/*.json`) go with the report they back, so each owner's report numbers can be traced in the same pull request. `reports/experiments/m4/training.csv` (the priority model added to the primary variant) goes to P2, who owns `baseline.py` and its `add-tasks` command.
- **Mixed-area tests:**
  - `tests/test_serving_calibrated.py` (P4) fits a tiny P2 baseline and uses P3's `apply_temperature`. It must merge after steps 2 and 4.
  - `tests/test_baseline.py` (P2) now calls `BaselinePredictor` with a temperature, which imports P3's `calibrate.py` (step 2).
  - `tests/test_robustness.py` (P2) covers `robustness.py`, `evaluation.py` and `iterations.py`, which all belong to P2.
  - `tests/test_calibrate.py` (P3) imports the serving gate (on `main` since M1) to check that the generated `thresholds.yaml` keeps `tau`.
  - `tests/test_serving_predictor.py` (M3 test, P4) now passes `thresholds_config={"tau": 0.8}` so it keeps testing uncalibrated loading. It must merge together with the `predictor.py` change in step 6 (same stage): with the repo's calibrated `thresholds.yaml`, the version gains a `-cal` suffix.
  - `tests/test_final_test_eval.py` (P4) checks that `configs/final_model.yaml` (P4) matches `configs/thresholds.yaml` (P3, step 2).
- **`.gitignore` (P4, step 1)** adds `reports/m4/*_LOCAL.csv` before P1's error sampling merges.
- **Never committed:** `models/` (the primary model's `priority.joblib` was added in this session; vocabulary-study models in `models/baseline/vocab_study/`), `data/`, `reports/m4/error_sample_LOCAL.csv`.
- **Test split:** `scripts/final_test_eval.py` is committed but has not been run. `configs/final_model.yaml` has `frozen_date: null` and `frozen_by: null` until the team freezes the model; the script refuses to run until then.

## Files changed in both M3 and M4

These files are in the M3 plan and are changed again in M4. The M4 owner commits the M4 version on top of the merged M3 version.

| File | M3 owner | M4 owner (commits the M4 change) | M4 step |
|---|---|---|---|
| `Makefile` | P4 | P4 | 6 |
| `configs/serving.yaml` | P4 | P4 | 6 |
| `src/complaintiq/models/baseline.py` | P2 | P2 | 4 |
| `src/complaintiq/serving/app.py` | P4 | P4 | 6 |
| `src/complaintiq/serving/predictor.py` | P4 | P4 | 6 |
| `tests/test_baseline.py` | P2 | P2 | 4 |
| `tests/test_serving_predictor.py` | P4 | P4 | 6 |
