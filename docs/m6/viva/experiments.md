# Crib sheet: experiments (M3, Dally)

**What.** Five TF-IDF variants on all 877,895 training rows, every run logged (run ID, git commit,
data version, settings, seed, val metrics) in reports/experiments/; 39 baseline rows in
baseline.csv. reports/m3/model_comparison.md is generated from the logs.

**Result (val macro-F1, product / issue).** Complement NB 0.663 / 0.283; SGD without class weights
0.737 / 0.402; SGD balanced (M3 baseline) 0.771 / 0.487; modified Huber 0.781 / 0.487; SGD alpha
2e-6, converged rerun (chosen) 0.782 / 0.507.

**Why it won.** Class weights matter most on the long tail (+0.085 issue, +0.034 product, derived).
A lower regularization (alpha 2e-6) fits the large vocabulary better. Capped runs were rerun to
convergence and replaced.

**Metric.** Macro-F1 over classes with val support (fixed label set): product OTHER has no val
rows, and the older all-labels definition would score the chosen model 0.704 instead of 0.782.

**Transformer.** DistilBERT pipeline built (head+tail 256 tokens, weighted loss, early stopping,
seeds 42/43/44 configured) but only a CPU smoke run (about 2,000 rows). The M3 criterion "a
transformer beats the baseline on val" was **not met**; the baseline ships and is also the fallback.

**Validation headline.** Product 0.782 (top-3 0.980), issue 0.507 (top-3 0.867), priority PR-AUC
0.461. Paired bootstrap vs the M3 baseline: +0.0110 product, +0.0195 issue, CIs exclude zero.

**Likely questions.**
- *Why macro-F1?* Imbalance; accuracy rewards the majority class.
- *Seeds?* One seed (42) for every baseline run; no mean ± std (limitation).
- *Focal loss, oversampling?* Not compared (listed in SPEC C5, not done).
- *Is val optimistic?* Yes, val chose the model; the test numbers are unbiased.
