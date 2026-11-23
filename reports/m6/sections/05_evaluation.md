# Evaluation (M4)

Sources: reports/m4/evaluation_report.md (val), reports/m4/test_results.md (test),
reports/m4/error_analysis.md, reports/m4/robustness_report.md,
reports/m4/improvement_iterations.md. 95% CIs are percentile bootstrap (1,000 resamples,
seed 42).

## Validation headline

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

## Test (one-shot, after the freeze)

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

## Against the targets

| target (SPEC A5) | measured | status |
|---|---|---|
| product macro-F1 at least 5 points over the TF-IDF baseline | +0.011 (val) | not met: the best model is itself TF-IDF |
| issue top-3 at least 85% | 0.867 (val), 0.845 (test) | met on val, missed on test |
| HIGH recall at least 85% | 0.852 (val-B), 0.834 (test) | met on val-B, missed on test |
| ECE below 0.05 | product 0.0149 / issue 0.0425 (val-B); 0.0211 / 0.0516 (test) | met on val-B; issue missed on test |
| coverage at least 60% at 95% precision | 0.7582 at 0.9498 (val-B); 0.7261 at 0.9356 (test) | coverage met; precision just missed |
| p95 at most 300 ms on CPU | 11.51 ms in process, 12.3 ms local API | met (M4, one laptop) |

## Where it struggles (val)

- Product F1 ranges from 0.937 (credit reporting) and 0.903 (mortgage) down to 0.557 (payday,
  title or personal loan), 0.703 (vehicle loan) and 0.706 (money transfer).
- The weakest issues: unauthorized transactions 0.234, false statements 0.264, threatened to
  contact someone 0.301. The largest confusions are among the three credit-reporting issues
  (6,418, 5,624 and 4,776 val rows for the top three pairs).
- Slices: issue error rate 0.3535 at 100-199 words vs 0.4660 at 400 words or more; 0.3704 in
  2022 vs 0.4061 in 2023. Company size: issue macro-F1 0.477 for other companies and 0.478 for the
  top 20 companies.

## Error analysis

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

## Robustness (seeded val subsample, 39,983 rows, paired)

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

## Improvement iterations (chosen on val-A, reported on val-B)

| iteration | hypothesis | product macro-F1 | issue macro-F1 |
|---|---|---|---|
| prior correction (lambda 0.25) | balanced weights ignore the label shift | 0.7823 to 0.7923 | 0.5046 to 0.5219 |
| class weights balanced to the power 0.5 | full balancing over-predicts small classes | 0.7823 to 0.7940 | 0.5046 to 0.5282 |
| issue restricted to the predicted product | 0.3105 of issue errors pick an issue never seen with the true product | unchanged | 0.5046 to 0.5191 |

Each was measured alone; the combination was not run. The team froze the model without them
(docs/M5_PLAN.md, step 0.2), because adopting one means retraining or re-scoring and
recalibrating before the freeze. They are the cheapest next improvements.
