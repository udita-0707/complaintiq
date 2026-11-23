# Experiments (M3)

## Setup

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

## Baseline variants (full train, 877,895 rows)

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

## Transformer

`src/complaintiq/models/transformer.py` fine-tunes `distilbert-base-uncased` per task with
head+tail truncation (256 tokens), a class-weighted loss, early stopping on val macro-F1 and
fixed seeds (42, 43, 44 configured for mean ± std). It ran only as a CPU smoke test (about 2,000
training rows, 1 epoch): product val macro-F1 0.487 and issue 0.021 on 1,000-row val samples,
numbers that only show the pipeline runs end to end. The full GPU run on a 150k-row sample was
never done. **The M3 definition of done, "at least one transformer beats the baseline on val",
was not met.** The baseline therefore became the primary model, which is also the serving
fallback the spec asked for (SPEC C5).

## Selection

The converged SGD variant with alpha 2e-6 (`baseline/tfidf_sgd_alpha2e-6_conv`) was chosen on
val and later frozen in configs/final_model.yaml. Because val chose it, val numbers are
optimistic; section 5 reports the held-out val-B and the one-shot test numbers.

Not done from SPEC C5: focal loss and oversampling comparisons, mean ± std over three seeds for
the final candidates (every baseline run uses seed 42), and the optional hierarchical model.
