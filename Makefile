.PHONY: install raw-data data-mappings data train eval serve test lint docker-build docker-up \
	train-baseline eval-baseline train-transformer eval-transformer compare-runs

PYTHON ?= python3.11
HOST ?= 0.0.0.0
PORT ?= 8000
INPUT ?=# zip or Parquet files/dir; empty uses raw.default_zip from configs/data.yaml

install:  ## Install package with dev tools (editable)
	$(PYTHON) -m pip install -e ".[dev]"

raw-data:  ## Build data/raw/complaints.csv and docs/data_provenance.md (needs .[data])
	$(PYTHON) scripts/prepare_raw_data.py $(INPUT)

data-mappings:  ## Regenerate configs/issue_mapping.yaml + reports/m2_mapping_review.md (review first)
	$(PYTHON) -m complaintiq.data.pipeline propose-mappings

data:  ## Build data/processed/{time,random}/ splits and reports/m2_data_stats.md (M2)
	$(PYTHON) -m complaintiq.data.pipeline build

train:  ## Train baseline / transformer models (M3): use the targets below
	@echo "use make train-baseline or make train-transformer"; exit 1

BASELINE_VARIANTS ?= tfidf_sgd
TRAIN_ARGS ?=# e.g. --smoke, or --max-train 50000

train-baseline:  ## Fit TF-IDF baseline(s) on train, score on val, log runs (BASELINE_VARIANTS=a,b)
	$(PYTHON) -m complaintiq.models.baseline train --variants $(BASELINE_VARIANTS) $(TRAIN_ARGS)

eval-baseline:  ## Full val report for the baseline -> reports/m3/baseline_val_report.md
	$(PYTHON) -m complaintiq.models.baseline eval

train-transformer:  ## Fine-tune DistilBERT (GPU; TRAIN_ARGS=--smoke for a CPU check)
	$(PYTHON) -m complaintiq.models.transformer train $(TRAIN_ARGS)

eval-transformer:  ## Re-score saved transformer checkpoints on val and log runs
	$(PYTHON) -m complaintiq.models.transformer eval

compare-runs:  ## Merge reports/experiments/*.csv into reports/m3/model_comparison.md
	$(PYTHON) scripts/compare_runs.py

eval:  ## Evaluate models on the test split (M4)
	@echo "make eval: not implemented yet (M4)"; exit 1

serve:  ## Run the API locally with auto-reload
	$(PYTHON) -m uvicorn complaintiq.serving.app:app --host $(HOST) --port $(PORT) --reload

test:  ## Run the test suite
	$(PYTHON) -m pytest

lint:  ## Lint with ruff
	$(PYTHON) -m ruff check .

docker-build:  ## Build the API image
	docker compose -f docker/docker-compose.yml build

docker-up:  ## Run the API in Docker on port 8000
	docker compose -f docker/docker-compose.yml up --build
