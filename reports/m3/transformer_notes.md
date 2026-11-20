# M3 transformer (DistilBERT): how to run on a GPU

`src/complaintiq/models/transformer.py` fine-tunes `distilbert-base-uncased` separately for each task, in this order: issue_class, product_class, priority. All settings are in `configs/model.yaml: transformer`:

- Input is the narrative only. Each narrative is cut to 256 tokens (head+tail): [CLS] + the first 128 + the last 126 content tokens + [SEP].
- Training uses a class-weighted cross-entropy loss and a stratified sample of 150k training rows.
- Mixed precision is used on CUDA only. The device is picked automatically: cuda, then mps, then cpu.
- Early stopping uses val macro-F1 on a stratified 20k-row val sample (patience 1). The best checkpoint is then scored on all val rows.
- Seeds are fixed: 42 by default, with `--seed 43` and `--seed 44` for the mean ± std.
- `--prior-correction` is optional. At inference it subtracts the log training prior from the logits.

The test split is never read.

## Smoke run on this machine (CPU)

`python -m complaintiq.models.transformer train --smoke` (2,000 train rows, 1,000 val rows, 1 epoch per task). Its only purpose is to check the pipeline end to end; its scores are not model quality. Results: see the smoke rows in `reports/experiments/transformer.csv` and `reports/m3/model_comparison.md`.

| run_id | task | n_train | val rows scored | val_macro_f1 | val_top3 | val_pr_auc | train_seconds |
|---|---|---|---|---|---|---|---|
| 64a8d6a00a0d | issue_class | 1,986 | 983 | 0.021 | 0.175 | | 728.2 |
| c8ac92a183f7 | product_class | 1,996 | 996 | 0.487 | 0.886 | | 606.0 |
| 59a9646aa101 | priority | 1,999 | 999 | 0.621 | | 0.249 | 587.2 |

These rows were rescored with the fixed-label-set macro-F1 (`rescored: fixed label set`: rescore run_ids 9cca00a09d18, 84bab3fffa0f and e35dab6a97fa, scored on the same 1,000-row val samples). The values are identical to the six decimals logged, so no class outside the val label set was predicted.

These ran on CPU (no CUDA; MPS is unavailable on this macOS 13 machine) with torch 2.11.0, the newest wheel available here; the pyproject `ml` extra pins 2.14.1. The pipeline worked end to end: sampling, head+tail encoding, weighted loss, early stopping, checkpointing, scoring and logging. The issue head did not learn (macro-F1 0.021: 34 classes, about 62 optimizer steps, mostly warmup). This is expected at smoke size and says nothing about DistilBERT on the full sample. Full-run results: TODO (GPU run).

## Full run: one command (Kaggle or Colab, GPU runtime)

```bash
git clone https://github.com/udita-0707/complaintiq && cd complaintiq && \
pip install -e ".[data,dev]" "torch==2.14.1" "transformers==5.20.2" && \
mkdir -p data/processed/time && cp /kaggle/input/<your-dataset>/{train,val,test}.parquet data/processed/time/ && \
python -m complaintiq.models.transformer train
```

- Run this after step 4 of `docs/COMMIT_PLAN_M3.md` is merged, so `main` has the transformer code. Before that, add `-b import/m3-files` to the clone.
- Upload `train.parquet`, `val.parquet` and `test.parquet` as a **private** Kaggle dataset (on Colab, copy them from Drive). `data_version()` hashes the bytes of all three files, and training stops at the start if one is missing. The test file is hashed, never parsed or loaded: `load_split("test")` raises unless `CIQ_ALLOW_TEST=1`, which no M3 command sets. Check that the logged `data_version` is `80a3ba969565`, the same as the local runs.
- More seeds: add `--seed 43`, then `--seed 44` (the same command again).
- Prior correction: `python -m complaintiq.models.transformer eval --prior-correction` re-scores the saved checkpoints and logs separate rows.
- Runtime on a T4 or P100 has not been measured: TODO, record it from `train_seconds` in the log.

## Bringing results back (nothing large is committed)

1. Checkpoints are written to `models/transformer/{issue,product,priority}/` (weights, tokenizer, `ciq_meta.json`). `models/` is gitignored. To serve them locally, zip that folder on Kaggle/Colab (`zip -r transformer.zip models/transformer`), download it, unzip it at the repo root, and set `predictor: transformer` in `configs/model.yaml`. Never commit the zip or the weights.
2. The run appends rows to `reports/experiments/transformer.csv` on the GPU machine. Download that file and replace the local copy: it already contains the local smoke rows, so check that they are still at the top. Then run `python scripts/compare_runs.py` locally.
3. Commit afterwards (P2 owns the logs and the comparison): `reports/experiments/transformer.csv` and `reports/m3/model_comparison.md`. P3 updates this file with the measured runtime. Do not commit `models/`, `data/` or any `.parquet`, `.safetensors` or `.zip` files.
