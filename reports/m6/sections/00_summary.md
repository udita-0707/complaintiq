# Summary

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
