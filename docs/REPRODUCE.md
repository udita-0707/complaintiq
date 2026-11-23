# Reproduce ComplaintIQ

Every step is one `make` target; seeds are fixed in configs. Run with `PYTHON=.venv/bin/python` if
the venv is not active. The test split is read only by step 8, once.

| step | command | output |
|---|---|---|
| 0 | `pip install -e ".[dev,data,serve,ui]"` | environment (Python 3.11, pinned versions) |
| 1 | `make raw-data INPUT=<mirror files>` | `data/raw/`, `docs/data_provenance.md` (checksums) |
| 2 | `make data` | `data/processed/{time,random}/`, `reports/m2_data_stats.md` |
| 3 | `make train-baseline BASELINE_VARIANTS=tfidf_sgd_alpha2e-6_conv` | `models/baseline/...`, run rows in `reports/experiments/baseline.csv` |
| 4 | `make add-priority` | priority head on the primary model |
| 5 | `make calibrate` | `configs/thresholds.yaml`, `reports/m4/calibration_report.md` |
| 6 | `make eval-report error-sample robustness iterations benchmark` | `reports/m4/*.md` |
| 7 | `make error-summary` | human error categories (after labelling the LOCAL sample) |
| 8 | `CIQ_ALLOW_TEST=1 make final-eval CONFIRM=yes` | `reports/m4/test_results.md` (**once only**, after freezing `configs/final_model.yaml`) |
| 9 | `make drift`, `make space`, local container runs | `reports/m5/` (docs/deployment.md) |
| 10 | `make report` | `reports/m6/technical_report.md`, `reports/m6/number_check.md` |

Check that the logged `data_version` is `80a3ba969565`: it hashes the three split files, so a
different value means different data. The transformer (optional): `make train-transformer` on a GPU,
see reports/m3/transformer_notes.md.

Do not commit `data/`, `models/`, `build/`, `runtime/`, `*.sqlite` or `reports/m4/*_LOCAL.csv`.
