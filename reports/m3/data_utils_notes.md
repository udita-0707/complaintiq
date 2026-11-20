# M3 training-data utilities (`src/complaintiq/data/training_data.py`)

- `load_split(split, scheme="time", columns=None)` reads `data/processed/<scheme>/<split>.parquet`.
  Only `train` and `val` are allowed in M3; `load_split("test")` raises `PermissionError` unless
  `CIQ_ALLOW_TEST=1` (reserved for final M4 reporting; no M3 code or run sets it).
- `LABEL_COLS` maps tasks to label columns: product → `product_class`, issue → `issue_class`,
  priority → `priority`. The only model input is `narrative`; company, date, `submitted_via`,
  `n_words` and the raw `product`/`issue` columns are used for slices only.
- `sample_train(df, label_col, cap_per_class=None, max_rows=None, seed=42)`: seeded, stratified,
  never drops a class. Step 1 clips each class to `cap_per_class`; step 2 scales every class by
  `max_rows / total` (floor, minimum 1 row). The 50k smoke sample stratified on `issue_class` has
  49,981 rows (experiment log, n_train of the smoke runs).
- **How capping changes class proportions.** `max_rows` alone keeps train proportions (up to
  rounding; tiny classes keep at least 1 row, so they are slightly over-represented). A
  `cap_per_class` flattens the distribution: every class above the cap is cut to the cap, so large
  classes lose share and small classes gain it. Example from the M2 label table: credit reporting is
  40.5% of train; with a cap the trained prior moves towards uniform, which is closer to neither the
  train (40.5%) nor the val (60.5%) prior. Models trained on capped data therefore need prior
  correction or a val-tuned threshold before their probabilities are read as calibrated.
- A bug was found and fixed during M3: polars returns `u32` class counts, and `count * max_rows`
  overflowed for the largest classes. The first smoke run (n_train 35,304) is flagged INVALID in
  `reports/m3/model_comparison.md`; a regression test covers it.
- `class_priors(df, label_col)` returns class shares summing to 1 (used for prior correction).
- `data_version()` = first 12 hex of SHA-256 over the bytes of the three time-split files (the test
  file is hashed, never parsed). Every experiment-log row stores it.
- `severity_mask(raw_issue)` reuses `priority.severity_issues` (B5 rule 1) to split HIGH rows into
  severity-rule HIGH and outcome-only HIGH for evaluation. It is never a feature.
