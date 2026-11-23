# Crib sheet: modeling and evaluation (M4, Udita)

**Frozen model.** `baseline/tfidf_sgd_alpha2e-6_conv`, frozen 2026-11-21. One vectorizer, three
SGD heads (product, issue, priority).

**val-A / val-B.** val split once (93,848 / 93,850 rows). Everything fitted on val-A; val-B is held
out from calibration and thresholds.

**Calibration.** Temperature scaling, T = 0.787 (product), 0.835 (issue). val-B ECE: product 0.0540
to 0.0149, issue 0.0690 to 0.0425 (target below 0.05: met).

**Gate.** tau = 0.803386, the smallest threshold with val-A precision of at least 0.95. val-B:
coverage 0.7582, precision 0.9498 (0.0002 short, derived). Test: 0.7261 at 0.9356.

**Priority.** Threshold 0.384091 for recall of at least 0.85 on val-A; val-B recall 0.8520 at
precision 0.2720; test recall 0.8337 at precision 0.2677.

**Test (once, after the freeze).** Product macro-F1 0.7013, issue 0.4979, issue top-3 0.8448, ECE
0.0211 / 0.0516. The product drop: one class with no training rows (267 rows, F1 0.053); without
it 0.773 (derived).

**Errors (240 labelled val errors).** Label ambiguity 0.400 issue / 0.508 product; taxonomy
mismatch 0.217 / 0.183; genuine model error 0.142 / 0.092.

**Robustness.** 5% typos cost 0.0324 (product) and 0.0320 (issue); first 50 words only cost 0.0431
and 0.0610; shuffling costs nothing. Paraphrase and unseen companies not run.

**Iterations (val-B).** Prior correction 0.7923 / 0.5219; softer class weights 0.7940 / 0.5282;
issue restricted to product 0.5191 (base 0.7823 / 0.5046). Measured alone, not adopted.

**Optimization.** ONNX int8 not done. Vocabulary study: 100,000 features halve size and p50 latency
for 0.7819 to 0.7805 product macro-F1.

**Likely questions.**
- *Why T < 1?* The SGD probabilities were under-confident; sharpening fixed it.
- *Why recall-first for priority?* Missing urgent cases is the costly error (SPEC A5).
- *Why not adopt the iterations?* They needed recalibration before the freeze; future work.
