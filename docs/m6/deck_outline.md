# Deck outline (reports/m6/ComplaintIQ_deck.pptx)

Owner: P4. 12 slides, three per presenter, about 20 minutes including the demo; full speaker notes
are in the deck. Slides name presenters only as Presenter 1-4. The M5 values on slides 10-12 come
from reports/m5/ (local container; there is no public deployment).

| slide | presenter | message | key numbers (split) |
|---|---|---|---|
| 1 | 1 | ComplaintIQ and the running order | |
| 2 | 1 | Urgent complaints wait in the wrong queue; one API call routes them | median narrative 136 words, 90th percentile 421 |
| 3 | 1 | Clean narratives, split by time to expose a real shift | 4,707,579 raw; 1,253,594 clean; 355,499 duplicates removed (derived); 877,895 / 187,698 / 188,001 rows; credit reporting 0.405 to 0.605 |
| 4 | 2 | Class-weighted TF-IDF won; the transformer stayed a smoke test | product 0.782, issue 0.507 (val); 39 logged runs; p95 11.51 ms |
| 5 | 2 | On validation, product is strong and issue is the hard task | 0.782 / 0.507 / PR-AUC 0.461 (val); bootstrap +0.011, +0.0195 |
| 6 | 2 | Errors cluster in credit-reporting issues and small loan products | payday 0.557; top confusion 6,418 rows (val) |
| 7 | 3 | Calibration lets the gate route 76% at about 95% precision | tau 0.803; coverage 0.7582, precision 0.9498 (val-B) |
| 8 | 3 | Most errors are label problems; the model shrugs off noise | 0.617 issue, 0.691 product (derived); typos 5%: 0.032; iterations up to 0.528 issue (val-B) |
| 9 | 3 | One look at the test set, and what its coverage is worth | product 0.701 (0.773 without the unseen class, derived), issue 0.498, coverage 0.7261 at 0.9356; 90.8 agent-hours (derived; two inputs are assumptions) |
| 10 | 4 | Every request is checked, scored and routed; failures fail safe | local container: p95 13.0 ms (1 client), 82.6 ms (10 clients), cold start 3.4 s, 16 of 16 failure tests; not deployed publicly |
| 11 | 4 | Monitored without raw text, then a live demo | drift: issue PSI vs train 0.320 to 0.416 in all 9 months, PSI vs first month at most 0.022; demo on the local reviewer UI |
| 12 | 4 | What we would fix next, and questions | no public deployment (paid plan required) |

Regenerating the deck needs Node.js and pptxgenjs, which are not project dependencies; edit the
amber tags directly in PowerPoint instead.
