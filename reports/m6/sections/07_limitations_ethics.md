# Limitations, ethics and threats to validity

## Label and data limitations

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

## Threats to validity

- val chose the model in M3; val numbers are optimistic. val-B is held out from calibration and
  thresholds only. The test split, read once after the freeze, is the unbiased estimate.
- Every baseline run uses one seed (42); no mean ± std over seeds.
- The random split was built but never modelled, so its overstatement is unknown.
- Latency numbers come from one machine (in process, local API and local container) and one run
  each; there is no public deployment, so cloud latency and cold starts were never measured.
- The error categories were labelled by the team without inter-annotator agreement.

## Privacy and safety

- Regex PII scrub only: names and street addresses are not detected. CFPB pre-redaction limits
  the risk in the training data, not in new input.
- No raw text in logs or the audit store, only a keyed hash; tests check this through the API.
- The free Space is public, including aggregate `/metrics`.

## Ethics

The system is decision support. It never decides a complaint's outcome, never contacts a
customer and never triggers an adverse customer outcome (SPEC A7, C10). Uncertain, low-quality and
non-English inputs go to a person with a stated reason, and agents can correct every prediction.
Performance differs by class and slice (payday loans, long narratives), so automatic routing
should be monitored per product, and the gate threshold is a business decision on the
coverage-precision curve, not a technical constant.
