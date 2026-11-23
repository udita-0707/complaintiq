# Modeling, calibration and optimization (M4)

## Frozen model

`baseline/tfidf_sgd_alpha2e-6_conv`, model_version `baseline-tfidf_sgd_alpha2e-6_conv-80a3ba969565`,
data_version `80a3ba969565`, frozen on 2026-11-21 by Udita and Aman (configs/final_model.yaml).
One TF-IDF vectorizer (word 1-2 grams, 200,000 features) feeds three class-weighted SGD
classifiers: product, issue and priority. The priority head was fitted on the same vectorizer in
M4 (reports/experiments/m4/training.csv).

## Validation design

val (187,698 rows) is split once, seeded and stratified on issue, into val-A (93,848 rows) and
val-B (93,850 rows). Temperatures, the gate threshold and the priority threshold are fitted on
val-A; every number labelled val-B is held out from those choices (but not from M3 model
selection, which used all of val).

## Temperature scaling

`softmax(log p / T)` with T minimizing NLL on val-A; ECE uses 15 equal-width bins. The argmax
never changes, so accuracy and F1 are unchanged.

| task | T | ECE val-B before | ECE val-B after | NLL val-B before | NLL val-B after |
|---|---|---|---|---|---|
| product | 0.787 | 0.0540 | 0.0149 | 0.418 | 0.397 |
| issue | 0.835 | 0.0690 | 0.0425 | 1.315 | 1.286 |

Both meet the ECE < 0.05 [target] on val-B. T < 1 means the raw SGD probabilities were
under-confident. Reliability diagrams: reports/m4/figures/.

## Confidence gate

Routing follows the product (SPEC B6), so the gate compares calibrated product confidence with
tau. tau = 0.803386 is the smallest threshold with val-A precision of at least 0.95 (at least 200
rows): val-A coverage 0.7578 at precision 0.9500; **val-B coverage 0.7582 at precision 0.9498**,
0.0002 under the 0.95 target, as expected when a threshold tuned exactly on one half is applied
to the other. The full coverage-precision curve is in reports/m4/calibration_report.md (for
example 0.6449 coverage at 0.9677 precision with a threshold of 0.90). Temperature scaling is
monotone, so calibration changes the meaning of tau (a probability), not which rows pass.

## Priority threshold

Chosen on val-A as the highest threshold with HIGH recall of at least 0.85: 0.384091. On val-B:
recall 0.8520, precision 0.2720, F1 0.4124, 0.2709 of complaints flagged (base rate 0.0865,
PR-AUC 0.4599). The max-F1 threshold (0.6393) would give precision 0.3939 at recall 0.6005; the
team kept the recall target because missing urgent cases is the costly error (SPEC A5).

## Optimization and inference cost

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
