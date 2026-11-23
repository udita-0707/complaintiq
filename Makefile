.PHONY: install raw-data data-mappings data train eval serve test lint docker-build docker-up \
	train-baseline eval-baseline train-transformer eval-transformer compare-runs \
	add-priority calibrate error-sample error-summary robustness eval-report iterations \
	iterations-class-weight vocab-train benchmark load-test final-eval \
	install-serve drift request-log-stats audit space space-ci ui-space serve-image serve-up \
	ui load-test-remote failure-tests deployment-report report check-numbers

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

# ---------------------------------------------------------------- M4 (validation split only)
M4_MODEL ?= tfidf_sgd_alpha2e-6_conv
VOCAB_SIZE ?= 100000

add-priority:  ## Fit priority into the primary variant with its own vectorizer (M4 preflight)
	$(PYTHON) -m complaintiq.models.baseline add-tasks --model $(M4_MODEL) --tasks priority \
		--owner team-m4-session

calibrate:  ## Temperature, tau, priority threshold on val-A; report on val-B; writes thresholds.yaml
	$(PYTHON) -m complaintiq.models.calibrate run

error-sample:  ## Error statistics + LOCAL error sample for labelling (gitignored, has narratives)
	$(PYTHON) -m complaintiq.eval.error_analysis auto

error-summary:  ## Category counts from the labelled LOCAL sample -> reports/m4/error_analysis.md
	$(PYTHON) -m complaintiq.eval.error_analysis summarize

robustness:  ## Perturbation drops for product and issue on a val subsample (logged)
	$(PYTHON) -m complaintiq.eval.robustness run

eval-report:  ## M4 evaluation report on val -> reports/m4/evaluation_report.md
	$(PYTHON) -m complaintiq.eval.evaluation run

iterations:  ## Improvement iterations 1 and 3 (no retraining)
	$(PYTHON) -m complaintiq.models.iterations run --only prior,consistency

iterations-class-weight:  ## Improvement iteration 2 (retrains product and issue, ~10 min)
	$(PYTHON) -m complaintiq.models.iterations run --only class_weight

vocab-train:  ## Vocabulary-study model for VOCAB_SIZE (100000 or 50000; ~10 min each)
	$(PYTHON) scripts/benchmark_inference.py vocab-train --size $(VOCAB_SIZE)

benchmark:  ## CPU latency/throughput/memory/size + vocabulary study -> reports/m4/inference_benchmark.md
	$(PYTHON) scripts/benchmark_inference.py run

load-test:  ## 200 sequential /v1/triage requests against a local API -> reports/m4/api_latency.md
	$(PYTHON) scripts/load_test.py

final-eval:  ## ONE-SHOT test evaluation after the freeze (CONFIRM=yes and CIQ_ALLOW_TEST=1)
	@echo "WARNING: final-eval reads the TEST split ONCE and writes reports/m4/test_results.md."
	@echo "Run it only after configs/final_model.yaml is frozen (frozen_date filled) and committed."
	@if [ "$(CONFIRM)" != "yes" ]; then \
		echo "Refusing: re-run as  CIQ_ALLOW_TEST=1 make final-eval CONFIRM=yes"; exit 1; fi
	$(PYTHON) scripts/final_test_eval.py --confirm-final-test-eval

# ---------------------------------------------------------------- M5 (deployment, monitoring)
URL ?= http://127.0.0.1:8000
LABEL ?= local
IMAGE ?= complaintiq-serve:local
UI_URL ?=

install-serve:  ## Install with dev tools and the serve extra (what M5 scripts need)
	$(PYTHON) -m pip install -e ".[dev,serve]"

drift:  ## Drift replay: train reference, val by month -> reports/m5/drift_report.md (needs data, model)
	$(PYTHON) -m complaintiq.monitoring.drift replay

request-log-stats:  ## Request counts, routes and correction rate from the local SQLite log
	$(PYTHON) -m complaintiq.serving.request_log stats

audit:  ## pip-audit the dependencies of the deployed image (core + serve pins)
	@mkdir -p build
	$(PYTHON) scripts/build_space.py requirements > build/serve-requirements.txt
	$(PYTHON) -m pip_audit -r build/serve-requirements.txt --progress-spinner off

space:  ## Stage build/hf_space with the FROZEN model (checks freeze, thresholds, manifest)
	$(PYTHON) scripts/build_space.py api

space-ci:  ## Stage build/hf_space with a tiny synthetic model (CI smoke only, never deploy)
	$(PYTHON) scripts/build_space.py api --synthetic-model

ui-space:  ## Stage build/hf_ui_space (Streamlit reviewer UI)
	$(PYTHON) scripts/build_space.py ui

serve-image:  ## Build the deployable image from build/hf_space (run make space first)
	docker build -t $(IMAGE) build/hf_space

serve-up:  ## Run the deployable image on localhost:8000 (run make space first)
	docker compose -f docker/docker-compose.serve.yml up --build

ui:  ## Reviewer UI on localhost:8501 against API_URL (default: local API)
	CIQ_API_URL=$(URL) $(PYTHON) -m streamlit run ui/app.py

load-test-remote:  ## Concurrent load test at 1/5/10 -> reports/m5/load_test.md (URL=, LABEL=local|public)
	$(PYTHON) scripts/load_test_remote.py $(URL) --label $(LABEL)

failure-tests:  ## C8 failure tests over HTTP and in fresh containers -> reports/m5/failure_tests.md
	$(PYTHON) scripts/failure_tests.py --url $(URL) --docker-image $(IMAGE)

deployment-report:  ## Deployment record -> reports/m5/deployment.md (LABEL=local IMAGE=... | LABEL=public URL=...)
	@if [ "$(LABEL)" = "public" ]; then \
		$(PYTHON) scripts/deployment_report.py --label public --url $(URL) $(if $(UI_URL),--ui-url $(UI_URL)); \
	else \
		$(PYTHON) scripts/deployment_report.py --label local --docker-image $(IMAGE); fi

# ---------------------------------------------------------------- M6 (report)
report:  ## Derived numbers + assembled technical report + number check -> reports/m6/
	$(PYTHON) scripts/build_report.py

check-numbers:  ## Every number in the M6 documents must trace to a source file
	$(PYTHON) scripts/check_numbers.py --report reports/m6/number_check.md

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
