# ComplaintIQ: technical report

Financial complaint triage on CFPB consumer complaints. NLP Industry Track, team of four: Kalash (data), Dally (baseline and experiments), Udita (modeling and evaluation), Aman (deployment). Assembled by `python scripts/build_report.py` from `reports/m6/sections/`; every number is checked against the source files (`reports/m6/number_check.md`).

Number labels: **val** (validation, also used to choose the model), **val-B** (held-out half of val), **test** (read once after the freeze), **[target]** and **[assumption]** (not results).

## Contents

1. Summary
2. Problem, users and scope
3. Data
4. Experiments (M3)
5. Modeling, calibration and optimization (M4)
6. Evaluation (M4)
7. Deployment, failure handling and monitoring (M5)
8. Limitations, ethics and threats to validity
9. Conclusion and project status

## Summary

ComplaintIQ reads the free-text narrative of a consumer financial complaint and returns a
product, the three most likely issues, a priority flag and a destination team, with calibrated
confidence. Complaints the model is unsure about go to a human review queue with a stated
reason. It is decision support: a person handles every complaint.

**Data.** CFPB complaints from an archived CC0 mirror: 4,707,579 raw rows, of which 1,689,593
have a narrative; 1,253,594 remain after cleaning and de-duplication. Labels: 10 product classes,
34 issue classes and a priority proxy (HIGH rate 0.137 in train, 0.086 in val, 0.093 in test).
A strict time split (train 2015-03 to 2022-09, val to 2023-05, test to 2024-02) exposes a large
label shift: credit reporting is 0.405 of train and 0.605 of val.

**Model.** The shipped model is a class-weighted TF-IDF (word 1-2 grams, 200,000 features)
with linear SGD classifiers for product, issue and priority. It won every M3 comparison on val
(product macro-F1 0.782, issue 0.507). A DistilBERT pipeline was built but only smoke-tested on
CPU, so the M3 criterion that a transformer beats the baseline was **not met**.

**Calibration and gate.** Temperature scaling lowers product ECE from 0.0540 to 0.0149 on
val-B. The gate threshold tau = 0.803 auto-routes 0.7582 of val-B complaints at precision 0.9498.

**Test (read once, after the freeze).** Product macro-F1 0.701 (95% CI 0.6971-0.7059), issue
macro-F1 0.498, issue top-3 0.845, gate coverage 0.7261 at precision 0.9356, HIGH-priority
recall 0.834 at precision 0.268. Most of the product drop from val comes from one class with no
training rows; without it, test product macro-F1 is 0.773 (derived).

**Errors.** In 240 hand-labelled val errors, label ambiguity and taxonomy mismatch explain
0.617 of issue errors and 0.691 of product errors; genuine model errors are 0.142 and 0.092.

**System.** A FastAPI service scrubs PII before inference, checks input quality, runs the
model under a timeout, applies the gate and logs an audit row without text. In the local Docker
container it answers with a p95 of 13.0 ms for one client and 82.6 ms for ten concurrent clients
(300 ms [target]), with zero errors, and passed 16 of 16 failure tests. It was not deployed publicly:
Hugging Face Docker Spaces required a paid plan, so the M5 goal of a public URL was not met. A drift
replay over nine validation months shows the known label shift against the training labels but
stable traffic month to month.

**Business case.** At test coverage, an illustrative 5,000 complaints a day and 1.5 minutes saved
per triage [assumption] give about 90.8 agent-hours a day (derived; two of three inputs are
assumptions).

## Problem, users and scope

### Problem

Banks, lenders and fintechs receive large volumes of free-text complaints. Each must be
categorized, routed to the right team and answered within regulatory timelines. Manual or
keyword triage fails in three ways (SPEC A1): misrouting adds days of internal handoffs; urgent
cases (fraud, unauthorized transactions, harassing collection) wait in the same queue as routine
ones; and agents spend minutes reading long narratives before acting. Cleaned narratives have a
median of 136 words and a 90th percentile of 421 words (reports/m2_data_stats.md).

### Task framing

| Sub-task | Type | Output |
|---|---|---|
| Product | single-label, 10 classes | product category |
| Issue | single-label, long-tailed, 34 classes | issue, top 3 with probabilities |
| Priority | binary on a derived proxy label | HIGH / NORMAL with a score |
| Routing | deterministic table (configs/routing.yaml) | destination team |
| Confidence gate | calibrated probability vs threshold | AUTO or HUMAN_REVIEW with a reason |

Summarization was a stretch goal and was not attempted.

### Users

- **Complaint-handling agent** (primary): the complaint should arrive in the right queue.
- **Queue manager**: urgent cases should surface first.
- **Compliance officer**: every decision must be auditable (model version, scores, route).

### Objective and success metrics

Reduce the time to the first correct assignment and surface high-priority complaints earlier,
while a person stays in control of uncertain cases (SPEC A4). Model targets (SPEC A5, all
[target]): product macro-F1 at least 5 points above the TF-IDF baseline, issue top-3 accuracy at
least 85%, HIGH recall at least 85%, ECE below 0.05 after temperature scaling. System targets:
auto-route coverage at least 60% at 95% precision, p95 latency at most 300 ms on CPU. Section 5
reports each against the measured values.

### Scope

In scope: classification, priority, routing, confidence fallback, REST API, monitoring,
Docker deployment, a reviewer UI. Out of scope: automated customer replies, outcome or
compensation decisions, non-English complaints, real company integration, any automated adverse
action (SPEC A7).

## Data

Full details: docs/data_card.md (from docs/data_provenance.md and reports/m2_data_stats.md).

### Source and provenance

The CFPB Consumer Complaint Database stopped publishing narratives in Aug 2026, so the project
uses an archived CC0 mirror on Hugging Face (`BEE-spoke-data/consumer-finance-complaints`,
complaints received 2011-12-01 to 2024-02-17). The raw export has 4,707,579 rows and 18 columns;
1,689,593 rows (35.9%) have a narrative. SHA-256 checksums of every input file are recorded in
docs/data_provenance.md. Only nine columns are ever read.

### Cleaning funnel

| step | rows |
|---|---|
| non-empty narrative | 1,689,593 |
| Consumer Loan excluded (mixed vehicle, installment, title and pawn loans) | 1,680,132 |
| at least 20 words | 1,609,093 |
| duplicate Complaint ID drop | 1,609,093 |
| duplicate normalized narrative drop (keep earliest) | 1,253,594 |

De-duplication removed 355,499 rows (derived): 103,762 groups of identical normalized text
(459,261 rows) were each kept once. Near-duplicates that differ by more than case, whitespace or
placeholders are not caught (no MinHash). Runs of CFPB `XXXX` placeholders become one
`[REDACTED]` token. Narrative length after cleaning: mean 203.571 words, median 136, 90th
percentile 421, 99th percentile 1,088.

### Labels

- **Product**: 10 classes after harmonizing the taxonomy across years
  (configs/product_mapping.yaml). Card and prepaid stay one class because the 2017-2023
  product cannot be split without the sub-product.
- **Issue**: 34 classes: the most frequent harmonized issues plus OTHER
  (configs/issue_mapping.yaml, reviewed in reports/m2_mapping_review.md).
- **Priority (proxy, SPEC B5)**: HIGH if the raw issue is on a 14-entry severity list, or the
  company response was "Closed with monetary relief", or the response was not timely.

| split | rows | HIGH rate | severity rule | monetary rule | untimely rule |
|---|---|---|---|---|---|
| train | 877,895 | 0.137 | 0.072 | 0.052 | 0.021 |
| val | 187,698 | 0.086 | 0.042 | 0.038 | 0.009 |
| test | 188,001 | 0.093 | 0.044 | 0.042 | 0.010 |

The two outcome fields are used only to derive this label and are dropped from every output
file; an assertion in `make data` checks it.

### Splits

Primary: a time split with no shuffling (rows of one date stay together).

| split | rows | first date | last date |
|---|---|---|---|
| train | 877,895 | 2015-03-19 | 2022-09-12 |
| val | 187,698 | 2022-09-13 | 2023-05-05 |
| test | 188,001 | 2023-05-06 | 2024-02-09 |

Assertions: no Complaint ID or normalized-text overlap across splits, strict date ordering. A
stratified random split (877,522 / 188,039 / 188,033 rows) was built for comparison, but no model
was trained on it, so the project cannot say how much random splitting overstates results.

### Shift, imbalance and noise

- **Label shift**: credit reporting is 0.405 of train, 0.605 of val and 0.566 of test;
  "Improper use of your report" is 0.063, 0.177 and 0.174. Cramér's V train vs val: product
  0.173, issue 0.211, priority 0.058.
- **Imbalance**: largest-to-smallest class ratio 24.359 (product) and 62.965 (issue, excluding
  OTHER) in train; 47.584 and 176.145 in val.
- **Label noise**: among duplicate-text groups, 1,254 (1.2%) carry more than one product class
  and 3,262 (3.1%) more than one issue class.
- **Taxonomy change**: the 2023-08-25 CFPB taxonomy change falls entirely inside the test split.
- **Confusable classes**: the largest credit-reporting issues share most top terms (Jaccard
  0.538).
- **Channel**: `submitted_via` is Web for every narrative row, so the channel slice is unusable.

### Privacy

Narratives were redacted by CFPB. Residual regex hits per 100,000 rows: email 17.2, SSN 0.0,
Luhn-valid card 1.0, phone 2.1, long digit runs 5.2 (314 rows with any hit). Names are not
detected (regex only), so name leaks are not measured. Raw text is never logged; reports hold
aggregates and complaint IDs only.

## Experiments (M3)

### Setup

Every run is logged as one CSV row (SPEC C5 schema: run ID, git commit, data version, model,
hyperparameters, seed, val metrics, train time, owner, notes) in reports/experiments/. The
comparison report (reports/m3/model_comparison.md) is generated from those logs. Model input is
the narrative only. All selection uses val; the test split was closed during M3 (the loader
refuses it without an explicit environment flag).

Metric definition: val macro-F1 is the mean F1 over the classes with val support (a fixed label
set). Product OTHER has no val rows, so the older "all labels" definition, which also counted
classes that are only predicted, understated product macro-F1 (0.704 vs 0.782 for the chosen
model). Rows logged before the fix were re-scored on the same saved models and are listed as
superseded.

### Baseline variants (full train, 877,895 rows)

| variant | product macro-F1 | issue macro-F1 | converged |
|---|---|---|---|
| Complement NB | 0.663 | 0.283 | n/a |
| SGD, no class weights | 0.737 | 0.402 | no (hit cap) |
| SGD, balanced class weights (M3 baseline) | 0.771 | 0.487 | no (hit cap) |
| SGD, modified Huber | 0.781 | 0.487 | yes (rerun) |
| SGD, alpha 2e-6 (chosen) | 0.782 | 0.507 | yes (rerun) |

- Class weighting is the largest single effect: +0.034 product and +0.085 issue macro-F1 over
  the unweighted model (derived).
- Two variants hit the iteration cap; they were rerun to convergence (`_conv` runs; the chosen
  product model stopped at 24 of 45 iterations) and the converged runs replace the capped ones.
- Vectorization is shared by all variants (263 s); fitting the chosen product model took 87.4 s.
- reports/experiments/baseline.csv holds 39 logged baseline runs, including smoke runs and
  superseded rows.

### Transformer

`src/complaintiq/models/transformer.py` fine-tunes `distilbert-base-uncased` per task with
head+tail truncation (256 tokens), a class-weighted loss, early stopping on val macro-F1 and
fixed seeds (42, 43, 44 configured for mean ± std). It ran only as a CPU smoke test (about 2,000
training rows, 1 epoch): product val macro-F1 0.487 and issue 0.021 on 1,000-row val samples,
numbers that only show the pipeline runs end to end. The full GPU run on a 150k-row sample was
never done. **The M3 definition of done, "at least one transformer beats the baseline on val",
was not met.** The baseline therefore became the primary model, which is also the serving
fallback the spec asked for (SPEC C5).

### Selection

The converged SGD variant with alpha 2e-6 (`baseline/tfidf_sgd_alpha2e-6_conv`) was chosen on
val and later frozen in configs/final_model.yaml. Because val chose it, val numbers are
optimistic; section 5 reports the held-out val-B and the one-shot test numbers.

Not done from SPEC C5: focal loss and oversampling comparisons, mean ± std over three seeds for
the final candidates (every baseline run uses seed 42), and the optional hierarchical model.

## Modeling, calibration and optimization (M4)

### Frozen model

`baseline/tfidf_sgd_alpha2e-6_conv`, model_version `baseline-tfidf_sgd_alpha2e-6_conv-80a3ba969565`,
data_version `80a3ba969565`, frozen on 2026-11-21 by Udita and Aman (configs/final_model.yaml).
One TF-IDF vectorizer (word 1-2 grams, 200,000 features) feeds three class-weighted SGD
classifiers: product, issue and priority. The priority head was fitted on the same vectorizer in
M4 (reports/experiments/m4/training.csv).

### Validation design

val (187,698 rows) is split once, seeded and stratified on issue, into val-A (93,848 rows) and
val-B (93,850 rows). Temperatures, the gate threshold and the priority threshold are fitted on
val-A; every number labelled val-B is held out from those choices (but not from M3 model
selection, which used all of val).

### Temperature scaling

`softmax(log p / T)` with T minimizing NLL on val-A; ECE uses 15 equal-width bins. The argmax
never changes, so accuracy and F1 are unchanged.

| task | T | ECE val-B before | ECE val-B after | NLL val-B before | NLL val-B after |
|---|---|---|---|---|---|
| product | 0.787 | 0.0540 | 0.0149 | 0.418 | 0.397 |
| issue | 0.835 | 0.0690 | 0.0425 | 1.315 | 1.286 |

Both meet the ECE < 0.05 [target] on val-B. T < 1 means the raw SGD probabilities were
under-confident. Reliability diagrams: reports/m4/figures/.

### Confidence gate

Routing follows the product (SPEC B6), so the gate compares calibrated product confidence with
tau. tau = 0.803386 is the smallest threshold with val-A precision of at least 0.95 (at least 200
rows): val-A coverage 0.7578 at precision 0.9500; **val-B coverage 0.7582 at precision 0.9498**,
0.0002 under the 0.95 target, as expected when a threshold tuned exactly on one half is applied
to the other. The full coverage-precision curve is in reports/m4/calibration_report.md (for
example 0.6449 coverage at 0.9677 precision with a threshold of 0.90). Temperature scaling is
monotone, so calibration changes the meaning of tau (a probability), not which rows pass.

### Priority threshold

Chosen on val-A as the highest threshold with HIGH recall of at least 0.85: 0.384091. On val-B:
recall 0.8520, precision 0.2720, F1 0.4124, 0.2709 of complaints flagged (base rate 0.0865,
PR-AUC 0.4599). The max-F1 threshold (0.6393) would give precision 0.3939 at recall 0.6005; the
team kept the recall target because missing urgent cases is the costly error (SPEC A5).

### Optimization and inference cost

The SPEC C6 optimization step (ONNX export and int8 quantization of a transformer, with the
FP32-vs-int8 agreement check of SPEC C11) was **not done**: there is no trained transformer, and
`onnx`/`onnxruntime` were never installed. Instead, M4 measured the served model and a smaller
vocabulary (reports/m4/inference_benchmark.md; one laptop, one run, so indicative):

| model | product val macro-F1 | issue val macro-F1 | size MB | single p50 ms | single p95 ms |
|---|---|---|---|---|---|
| 200,000 features (served) | 0.7819 | 0.5068 | 40.7 | 10.56 | 11.48 |
| 100,000 features | 0.7805 | 0.5057 | 20.3 | 5.45 | 6.30 |
| 50,000 features | 0.7789 | 0.5031 | 10.1 | 3.00 | 3.49 |

The served model as called by the API (vectorize, three heads, temperatures): single-request p50
10.77 ms, p95 11.51 ms, p99 12.22 ms, 92.3 requests per second; batches of 8 at p95 13.88 ms
(643.4 requests per second). 41.5 MB on disk, 187 MB of extra RSS when loaded, 0.9 s to load.
For comparison, DistilBERT FP32 on the same CPU (three heads, smoke weights; latency depends on
the architecture, not the weights): p50 154.2 ms, p95 200.0 ms, 766 MB. Cost per 1,000 requests
is 10.83 CPU-seconds at the mean latency; a price per CPU-hour was never agreed, so no money
figure is given.

## Evaluation (M4)

Sources: reports/m4/evaluation_report.md (val), reports/m4/test_results.md (test),
reports/m4/error_analysis.md, reports/m4/robustness_report.md,
reports/m4/improvement_iterations.md. 95% CIs are percentile bootstrap (1,000 resamples,
seed 42).

### Validation headline

| task | split | macro-F1 | 95% CI | weighted-F1 | accuracy | top-3 |
|---|---|---|---|---|---|---|
| product | full val | 0.7819 | 0.7788-0.7850 | 0.8785 | 0.8756 | 0.9804 |
| product | val-B | 0.7823 | 0.7777-0.7868 | 0.8786 | 0.8757 | 0.9803 |
| issue | full val | 0.5068 | 0.5032-0.5104 | 0.6124 | 0.6094 | 0.8671 |
| issue | val-B | 0.5046 | 0.4992-0.5097 | 0.6120 | 0.6088 | 0.8672 |

Priority PR-AUC 0.4605 on full val (HIGH base rate 0.0862). **Significance** (paired bootstrap on
full val, same resampled rows for both models) against the M3 baseline `baseline/tfidf_sgd`:
product +0.0110 (+0.0095 to +0.0125), issue +0.0195 (+0.0177 to +0.0213); no resample showed a
loss.

### Test (one-shot, after the freeze)

`scripts/final_test_eval.py` read the test split once, from a clean tree at commit `345ef9a`,
after the freeze; nothing was tuned on it. 188,001 rows.

| task | macro-F1 | 95% CI | weighted-F1 | accuracy | top-3 | ECE (calibrated) |
|---|---|---|---|---|---|---|
| product | 0.7013 | 0.6971-0.7059 | 0.8555 | 0.8535 | 0.9736 | 0.0211 |
| issue | 0.4979 | 0.4944-0.5016 | 0.5629 | 0.5611 | 0.8448 | 0.0516 |

Gate at tau 0.8034: coverage 0.7261, precision 0.9356. Priority PR-AUC 0.4462 (base rate
0.0933); at threshold 0.3841, precision 0.2677 and recall 0.8337.

**Why product drops from val to test.** The test split contains product OTHER, which there comes
from "Debt or credit management", a product that only appears from 2023-08 and has no training
rows (configs/product_mapping.yaml). It has 267 test rows and F1 0.053. Macro-F1 averages over
classes, so this one class pulls the mean down; the other nine classes average 0.773 (derived).
Issue holds (0.498 on test vs 0.507 on val).

### Against the targets

| target (SPEC A5) | measured | status |
|---|---|---|
| product macro-F1 at least 5 points over the TF-IDF baseline | +0.011 (val) | not met: the best model is itself TF-IDF |
| issue top-3 at least 85% | 0.867 (val), 0.845 (test) | met on val, missed on test |
| HIGH recall at least 85% | 0.852 (val-B), 0.834 (test) | met on val-B, missed on test |
| ECE below 0.05 | product 0.0149 / issue 0.0425 (val-B); 0.0211 / 0.0516 (test) | met on val-B; issue missed on test |
| coverage at least 60% at 95% precision | 0.7582 at 0.9498 (val-B); 0.7261 at 0.9356 (test) | coverage met; precision just missed |
| p95 at most 300 ms on CPU | 11.51 ms in process, 12.3 ms local API | met (M4, one laptop) |

### Where it struggles (val)

- Product F1 ranges from 0.937 (credit reporting) and 0.903 (mortgage) down to 0.557 (payday,
  title or personal loan), 0.703 (vehicle loan) and 0.706 (money transfer).
- The weakest issues: unauthorized transactions 0.234, false statements 0.264, threatened to
  contact someone 0.301. The largest confusions are among the three credit-reporting issues
  (6,418, 5,624 and 4,776 val rows for the top three pairs).
- Slices: issue error rate 0.3535 at 100-199 words vs 0.4660 at 400 words or more; 0.3704 in
  2022 vs 0.4061 in 2023. Company size: issue macro-F1 0.477 for other companies and 0.478 for the
  top 20 companies.

### Error analysis

120 issue and 120 product errors from val (seeded, stratified by true class; SPEC C6 asks for at
least 100), each labelled by hand with one SPEC category:

| category | issue | product |
|---|---|---|
| label ambiguity | 0.400 | 0.508 |
| taxonomy mismatch | 0.217 | 0.183 |
| multi-topic narrative | 0.192 | 0.117 |
| short or uninformative | 0.050 | 0.100 |
| genuine model error | 0.142 | 0.092 |

Label ambiguity plus taxonomy mismatch account for 0.617 of issue and 0.691 of product errors
(derived). Better models alone will not remove most errors; label review and the taxonomy matter
as much. No inter-annotator agreement was measured.

### Robustness (seeded val subsample, 39,983 rows, paired)

| perturbation | product drop | issue drop |
|---|---|---|
| typos 1% / 3% / 5% of letters | 0.0063 / 0.0183 / 0.0324 | 0.0057 / 0.0197 / 0.0320 |
| first 50 words only | 0.0431 | 0.0610 |
| first 100 words only | 0.0193 | 0.0267 |
| sentences shuffled | 0.0003 | -0.0005 |
| boilerplate added | 0.0083 | -0.0041 |
| 10% more redaction | 0.0030 | 0.0045 |

Shuffling changes almost nothing (a bag-of-words model); truncation hurts most. Paraphrase and
unseen company names (SPEC C6) were not run.

### Improvement iterations (chosen on val-A, reported on val-B)

| iteration | hypothesis | product macro-F1 | issue macro-F1 |
|---|---|---|---|
| prior correction (lambda 0.25) | balanced weights ignore the label shift | 0.7823 to 0.7923 | 0.5046 to 0.5219 |
| class weights balanced to the power 0.5 | full balancing over-predicts small classes | 0.7823 to 0.7940 | 0.5046 to 0.5282 |
| issue restricted to the predicted product | 0.3105 of issue errors pick an issue never seen with the true product | unchanged | 0.5046 to 0.5191 |

Each was measured alone; the combination was not run. The team froze the model without them
(docs/M5_PLAN.md, step 0.2), because adopting one means retraining or re-scoring and
recalibrating before the freeze. They are the cheapest next improvements.

## Deployment, failure handling and monitoring (M5)

Details: docs/deployment.md, docs/security.md, docs/monitoring_plan.md. Measured results:
reports/m5/ (merged and tagged `m5`). **Status:** the service was built, containerized and measured
on a local machine: load test, failure tests, deployment record and drift replay are complete.
**There is no public deployment:** the team found that Hugging Face Docker Spaces require a paid plan,
so the local container run is the deployment record (reports/m5/deployment.md). The M5 definition of
done, "public URL works", is therefore not met.

### Service

FastAPI, one process. `POST /v1/triage` runs, in order:

1. the FR1 length check (400 outside 20-10,000 characters);
2. the PII scrub (emails, US phone numbers, SSNs, Luhn-valid card numbers, digit runs of 9 or
   more), so the model, the logs and the audit store only ever see scrubbed text (FR2);
3. an input quality heuristic: fewer than 20 words (the training minimum), mostly junk tokens, no
   English function words, or Spanish/French function words outweighing English ones send the
   case to human review with a reason (it is still scored);
4. the model in a thread pool with a 2-second timeout; a timeout returns HUMAN_REVIEW with reason
   `timeout`;
5. the confidence gate (tau 0.803386 on calibrated product confidence) and the routing table,
   with the fraud override for HIGH-priority fraud or identity issues;
6. an audit row in SQLite (hash of the scrubbed text, labels, scores, model version, route,
   reason, latency; never text) and Prometheus metrics.

The response is the SPEC C7 schema plus one additive optional field, `reason`
(`low_confidence`, `short_text`, `low_quality_text`, `non_english` or `timeout`). `POST
/v1/feedback` links an agent's correction to the request; corrections for unknown request IDs are
stored and flagged rather than rejected. `GET /health`, `/v1/model` and `/metrics` complete FR6.

### Failure handling (SPEC C8)

| failure | behaviour |
|---|---|
| empty, too short or too long text | 400 |
| short, gibberish or non-English text | HUMAN_REVIEW with a reason |
| model slower than 2 s | HUMAN_REVIEW, reason `timeout` |
| transformer fails (not deployed) | baseline answers, model_version flagged `-fallback` |
| baseline missing or failing | 503; the deployed image never serves fixed dummy labels |
| audit log unavailable | the response is served; rows wait in a bounded buffer (1,000 rows) |
| PII after the scrub | counted (`ciq_pii_residual_total`), never logged |
| too many requests | 429 with Retry-After (per-IP token bucket, 60 a minute, bursts of 20) |
| request body over 131,072 bytes | 413 before parsing |

### Deployment

The service is packaged as two Docker images prepared for Hugging Face Spaces: the API, with the
frozen model delivered through the Space repo with git-lfs (never through GitHub; a SHA-256 manifest
of the five model files is checked before every build), and a Streamlit reviewer console that calls
the API from its server, so CORS stays closed. Neither was published, because Docker Spaces required a
paid plan; the identical image was run locally with docker compose and measured there. The reviewer
console runs locally with `make ui`. CI runs ruff, the test suite on synthetic data, `pip-audit` on the
image's dependencies, the dev image build and a smoke test of the real Space image built with a tiny
synthetic model.

**Local container record** (reports/m5/deployment.md, one machine):

| measurement | value |
|---|---|
| public API and UI URLs | not deployed (paid plan required) |
| cold start (`docker run` to healthy, model loaded) | 3.4 s |
| resident memory | 313.7 MB |
| image size | 704.3 MB |
| model_version served | `baseline-tfidf_sgd_alpha2e-6_conv-80a3ba969565-cal` (tau 0.8034) |

**Load test** (reports/m5/load_test.md): closed loop, 200 synthetic requests per level after 10
warm-up requests, against the local container.

| concurrent clients | client p50 ms | client p95 ms | client p99 ms | server p95 ms | requests/s | errors |
|---|---|---|---|---|---|---|
| 1 | 12.1 | 13.0 | 13.5 | 10.0 | 82.0 | 0 |
| 5 | 24.7 | 36.8 | 46.1 | 24.0 | 195.3 | 0 |
| 10 | 54.4 | 82.6 | 100.5 | 41.0 | 176.8 | 0 |

The worst client p95 (82.6 ms at 10 clients) is well inside the 300 ms [target]. Throughput peaks
around five clients; at ten, requests queue behind the single worker process, so latency grows while
throughput does not.

**Failure tests** (reports/m5/failure_tests.md): 11 of 11 HTTP scenarios and 5 of 5 injected
container failures passed. Highlights: four synthetic PII strings were redacted with 0 residual and
nothing echoed; a 200 KB body got 413; the first 429 arrived after 11 rapid requests; a missing model
gave 503 with `/health` degraded; an injected 3-second delay returned HUMAN_REVIEW with reason
`timeout` after 2018 ms; with the audit log unwritable the API kept answering and buffered the rows;
the container logs contained none of the planted strings.

### Monitoring (SPEC C9)

| signal | source | alert |
|---|---|---|
| latency p95, error rate | `/metrics` | p95 above 500 ms |
| human-review (fallback) rate | `ciq_triage_route_total` by reason | rise above its reference (0.242 on val-B, 0.274 on test, derived) |
| predicted class distribution | drift job, PSI vs training labels | PSI above 0.2 |
| confidence | drift job, mean calibrated confidence | drop above 10% |
| input drift | drift job, length PSI and out-of-vocabulary rate | length PSI above 0.2 |
| quality | request log, correction rate | rising trend |
| residual PII | `ciq_pii_residual_total` | any |

**Drift replay** (reports/m5/drift_report.md): val replayed month by month (9 months, 2022-09 to
2023-05) against the training reference. Every month was flagged, but the pattern shows why both
comparisons are needed:

- **Against the training labels**, issue PSI was 0.320 to 0.416 (above 0.2 in all 9 months) and
  product PSI 0.162 to 0.242 (above 0.2 in 2022-11, 2022-12 and 2023-04). This is the label shift
  already measured in M2: in 2023-05 the model predicts credit reporting for 0.572 of complaints
  against a training share of 0.405, and "Improper use of your report" for 0.180 against 0.063.
- **Against the first replayed month**, product PSI stayed at or below 0.022: the incoming traffic
  itself was stable over the nine months.
- **Confidence** stayed between 0.867 and 0.882 (no drop near the 10% alert), the auto-route share
  between 0.743 and 0.772, the out-of-vocabulary rate between 0.1085 and 0.1135 (train sample 0.1160),
  and length PSI at or below 0.012.

In production the PSI-vs-train alert would therefore fire from day one and should be re-based on a
recent reference period, while the period-over-period PSI and the confidence signal carry the real
drift information. No Prometheus server or pager was deployed. Retraining is a manual decision after
sustained drift or a rising correction rate (docs/monitoring_plan.md).

## Limitations, ethics and threats to validity

### Label and data limitations

- **Priority is a proxy.** Two of its three rules are company outcomes (monetary relief,
  untimely response), not urgency judged at intake, and their rates move with company behaviour
  (HIGH 0.207 in 2015 vs 0.091 in 2023). The third rule ties priority to the issue label.
  "Communication tactics" contributes 22,271 rows (28.1%) of the severity rule and is a weak
  urgency signal. The SPEC C12 mitigation, hand-checking 200 priority labels, was not done.
- **Taxonomy drift.** CFPB changed its taxonomy on 2023-08-25, inside the test split; a product
  that appears only from 2023-08 has no training rows and costs most of the test product
  macro-F1 drop.
- **Label noise.** 1.2% of duplicate-text groups carry two product labels and 3.1% two issue
  labels; label ambiguity is the largest error category (0.400 issue, 0.508 product).
- **Credit-reporting shift.** 0.405 of train vs 0.605 of val and 0.566 of test; prior correction
  would help (section 5) but was not adopted.
- **Channel slice.** Every narrative arrived via Web, so performance by channel cannot be reported.

### Threats to validity

- val chose the model in M3; val numbers are optimistic. val-B is held out from calibration and
  thresholds only. The test split, read once after the freeze, is the unbiased estimate.
- Every baseline run uses one seed (42); no mean ± std over seeds.
- The random split was built but never modelled, so its overstatement is unknown.
- Latency numbers come from one machine (in process, local API and local container) and one run
  each; there is no public deployment, so cloud latency and cold starts were never measured.
- The error categories were labelled by the team without inter-annotator agreement.

### Privacy and safety

- Regex PII scrub only: names and street addresses are not detected. CFPB pre-redaction limits
  the risk in the training data, not in new input.
- No raw text in logs or the audit store, only a keyed hash; tests check this through the API.
- The free Space is public, including aggregate `/metrics`.

### Ethics

The system is decision support. It never decides a complaint's outcome, never contacts a
customer and never triggers an adverse customer outcome (SPEC A7, C10). Uncertain, low-quality and
non-English inputs go to a person with a stated reason, and agents can correct every prediction.
Performance differs by class and slice (payday loans, long narratives), so automatic routing
should be monitored per product, and the gate threshold is a business decision on the
coverage-precision curve, not a technical constant.

## Conclusion and project status

ComplaintIQ turns a complaint narrative into a calibrated routing suggestion. On the one-shot
test split it auto-routes 0.7261 of complaints at precision 0.9356, keeps issue macro-F1 at 0.498
(close to val), and flags HIGH-priority complaints with recall 0.834. Most remaining errors come
from ambiguous labels and taxonomy changes rather than from the model.

### Status against each milestone's definition of done (SPEC C13)

| milestone | definition of done | status |
|---|---|---|
| M1 | Part A approved, repo created, data downloaded | done |
| M2 | reproducible `make data`; leakage tests pass | done |
| M3 | at least one transformer beats the baseline on val; all runs logged | **partly**: runs logged; transformer only smoke-tested, criterion not met |
| M4 | test results reported once; error taxonomy with counts | done (ONNX int8 and two robustness checks not done) |
| M5 | public URL works; load and failure tests documented | **partly**: load and failure tests documented on the local container (16 of 16 failure tests passed); no public URL (paid plan required) |
| M6 | demo rehearsed; every member can explain every stage | **open** until the rehearsal log in docs/m6/demo_script.md is filled |

### What would improve the system most

1. Adopt the measured iterations (prior correction, softer class weights, issue restricted to the
   predicted product), then recalibrate and re-freeze.
2. Run DistilBERT on a GPU with three seeds and, if it wins, export it to ONNX int8 with the
   agreement check of SPEC C11.
3. Review labels where the error analysis points (credit-reporting issues), hand-check 200
   priority labels, and add the 2023-08 taxonomy to training.
4. Publish the container on a host with a free or paid tier that runs Docker images, then give it a
   persistent audit log and a metrics scraper so drift and correction rates can be tracked over time;
   re-base the PSI alert on a recent reference period, since the replay shows the training reference
   fires every month.
