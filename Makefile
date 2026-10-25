.PHONY: install raw-data data-mappings data train eval serve test lint docker-build docker-up

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

train:  ## Train baseline / transformer models (M3)
	@echo "make train: not implemented yet (M3)"; exit 1

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
