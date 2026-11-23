# Viva preparation (SPEC C14)

Owner: P3 (Udita). Every member should be able to give each answer. Numbers carry their split.

## 1. Why a time-based split? What did random splitting overstate, and by how much?

Production sees future complaints, so we train on the past and evaluate on later data: train
2015-03-19 to 2022-09-12, val to 2023-05-05, test to 2024-02-09 (docs/data_card.md). The time split
exposed a large shift: credit reporting is 0.405 of train and 0.605 of val. **We built a stratified
random split (877,522 / 188,039 / 188,033 rows) but never trained on it, so we cannot quantify the
overstatement.** Say this plainly; the expected direction is optimistic, because a random split
mixes post-shift complaints into training.

## 2. How was priority defined, and why is it only a proxy?

HIGH if the raw issue is on a 14-entry severity list, or the company gave monetary relief, or the
response was untimely (SPEC B5). Two rules are company outcomes, not urgency judged at intake, and
their rates drift (HIGH 0.207 in 2015 vs 0.091 in 2023). HIGH rate: 0.137 train, 0.086 val, 0.093
test.

## 3. How did you prevent outcome fields leaking into inputs?

The narrative is the only model input. The two outcome columns are read only to derive priority
and are dropped from every split file; `make data` asserts no outcome column is in the outputs. A
leakage test covers it (tests/test_data.py).

## 4. Why macro-F1 over accuracy? What does calibration add?

Imbalance: the largest-to-smallest class ratio in val is 47.584 (product) and 176.145 (issue).
Accuracy rewards predicting credit reporting; macro-F1 weights every class equally. Calibration
makes the confidence a usable probability: product ECE 0.0540 to 0.0149 and issue 0.0690 to 0.0425
on val-B, so a threshold means what it says.

## 5. How was tau chosen, and what does the coverage-precision trade-off mean for the business?

tau = 0.803386, the smallest calibrated product confidence with val-A precision of at least 0.95.
Held-out val-B: coverage 0.7582 at precision 0.9498; test: 0.7261 at 0.9356. Coverage is work taken
off agents; lost precision is misrouted complaints. The curve lets the business choose, for example
0.6449 coverage at 0.9677 precision with a threshold of 0.90 (val-B).

## 6. What did quantization cost in accuracy and gain in latency?

**Not done**: there is no trained transformer, so ONNX int8 was never run. What we measured instead:
a 100,000-feature vocabulary halves size (40.7 to 20.3 MB) and single-request p50 (10.56 to 5.45 ms)
for a product val macro-F1 change of 0.7819 to 0.7805. The served model's single-request p95 is 11.51
ms in process; DistilBERT FP32 on the same CPU is 200.0 ms.

## 7. What would you monitor in production, and what triggers retraining?

Latency p95 (alert above 500 ms), error rate, human-review share by reason, predicted-class PSI vs
training labels (above 0.2), mean calibrated confidence (drop above 10%), input length and
out-of-vocabulary rate, correction rate from agent feedback, residual PII. Retraining is manual:
sustained drift or a rising correction rate leads to a review, then retrain, recalibrate and
re-freeze (docs/monitoring_plan.md). The drift replay over nine val months showed why the reference
matters: issue PSI against the training labels was above 0.2 in every month (0.320 to 0.416, the
known label shift), while product PSI against the first replayed month stayed at or below 0.022 and
mean confidence stayed between 0.867 and 0.882.

## 8. Limitations and threats to validity?

Proxy priority label; taxonomy drift (a product new in 2023-08 has no training rows and costs most
of the test product drop: 0.701 vs 0.773 without it, derived); label noise; regex-only PII; val
chose the model; one seed; no transformer; random split not modelled; latency from one laptop
(technical report, section 7).

## Other likely questions

- **Why is test product macro-F1 lower than val?** One unseen class (267 test rows, F1 0.053) in a
  macro average; issue holds (0.498 test vs 0.507 val).
- **Which targets did you miss?** On test: issue ECE 0.0516, precision 0.9356 at the gate, HIGH
  recall 0.834, issue top-3 0.845. The +5-point gain over TF-IDF was not met (+0.011 on val).
- **Is it deployed?** Not publicly: Hugging Face Docker Spaces required a paid plan. The same image
  ran locally: cold start 3.4 s, p95 82.6 ms at ten concurrent clients, 16 of 16 failure tests passed.
  The M5 goal "public URL works" is not met.
- **What would you do with two more weeks?** Adopt the three measured iterations (each improved
  val-B macro-F1), recalibrate, then run the GPU transformer.
- **Is the significance real?** Paired bootstrap on val: product +0.0110 (+0.0095 to +0.0125),
  issue +0.0195 (+0.0177 to +0.0213); no resample showed a loss.
