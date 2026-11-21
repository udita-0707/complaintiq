# M4 final TEST results (one-shot)

Generated once by `scripts/final_test_eval.py` after the model freeze. These are the only test-split numbers of the project; nothing was tuned on them.

- git commit `345ef9a`
- data_version `80a3ba969565`
- model id `baseline/tfidf_sgd_alpha2e-6_conv`, model_version `baseline-tfidf_sgd_alpha2e-6_conv-80a3ba969565`
- frozen on 2026-11-21; thresholds {"tau": 0.803386, "temperature_product": 0.787111, "temperature_issue": 0.83484, "priority_threshold": 0.384091}
- test rows 188,001; run_ids product `b37449397551`, issue `ba29389d35c3`, priority `c6f1dfcbac84`

| task | macro-F1 | 95% CI | weighted-F1 | accuracy | top-3 | ECE (calibrated) |
|---|---|---|---|---|---|---|
| product | 0.7013 | 0.6971-0.7059 | 0.8555 | 0.8535 | 0.9736 | 0.0211 |
| issue | 0.4979 | 0.4944-0.5016 | 0.5629 | 0.5611 | 0.8448 | 0.0516 |

Gate at tau=0.8034: coverage 0.7261, precision 0.9356.

Priority: PR-AUC 0.4462 (base rate 0.0933); at threshold 0.3841: precision 0.2677, recall 0.8337.

Per-class tables and slices: `reports/m4/results/test_results.json`.
