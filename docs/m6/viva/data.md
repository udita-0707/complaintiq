# Crib sheet: data (M2, Kalash)

**What.** CFPB complaints from an archived CC0 mirror (CFPB stopped publishing narratives in Aug
2026). 4,707,579 raw rows; 1,689,593 with a narrative; 1,253,594 after cleaning.

**Why each step.** Consumer Loan excluded (it mixed vehicle, installment, title and pawn loans);
at least 20 words (too short to classify); exact duplicate narratives dropped (keep earliest) so no
text appears in two splits: 355,499 rows removed (derived). `XXXX` runs become `[REDACTED]`.

**Labels.** 10 product classes and 34 issue classes after harmonizing the taxonomy across years
(versioned mappings in configs/). Priority is a proxy: severity list (14 entries), monetary relief
or untimely response. HIGH rate 0.137 train, 0.086 val, 0.093 test.

**Splits.** Time split: train 877,895 (to 2022-09-12), val 187,698 (to 2023-05-05), test 188,001
(to 2024-02-09). No ID or text overlap; strict date order. Random split built (877,522 / 188,039 /
188,033) but never modelled.

**Key facts.** Credit reporting 0.405 of train, 0.605 of val, 0.566 of test. Imbalance ratio in
val: 47.584 product, 176.145 issue. Median narrative 136 words. Residual PII per 100,000 rows:
email 17.2, card 1.0. Channel is Web for every row.

**Likely questions.**
- *Leakage?* Outcome fields only derive priority and are dropped from every output (asserted).
- *Near-duplicates?* Only exact normalized text; no MinHash (limitation).
- *Why a time split?* The future is what production sees; the shift above proves it matters.
- *Why did test product drop?* A product new in 2023-08 has no training rows (taxonomy change on
  2023-08-25, inside test).
