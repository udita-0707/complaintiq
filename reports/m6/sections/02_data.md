# Data

Full details: docs/data_card.md (from docs/data_provenance.md and reports/m2_data_stats.md).

## Source and provenance

The CFPB Consumer Complaint Database stopped publishing narratives in Aug 2026, so the project
uses an archived CC0 mirror on Hugging Face (`BEE-spoke-data/consumer-finance-complaints`,
complaints received 2011-12-01 to 2024-02-17). The raw export has 4,707,579 rows and 18 columns;
1,689,593 rows (35.9%) have a narrative. SHA-256 checksums of every input file are recorded in
docs/data_provenance.md. Only nine columns are ever read.

## Cleaning funnel

| step | rows |
|---|---|
| non-empty narrative | 1,689,593 |
| Consumer Loan excluded (mixed vehicle, installment, title and pawn loans) | 1,680,132 |
| at least 20 words | 1,609,093 |
| duplicate Complaint ID drop | 1,609,093 |
| duplicate normalized narrative drop (keep earliest) | 1,253,594 |

De-duplication removed 355,499 rows (derived): 103,762 groups of identical normalized text
(459,261 rows) were each kept once. Near-duplicates that differ by more than case, whitespace or
placeholders are not caught (no MinHash). Runs of CFPB `XXXX` placeholders become one
`[REDACTED]` token. Narrative length after cleaning: mean 203.571 words, median 136, 90th
percentile 421, 99th percentile 1,088.

## Labels

- **Product**: 10 classes after harmonizing the taxonomy across years
  (configs/product_mapping.yaml). Card and prepaid stay one class because the 2017-2023
  product cannot be split without the sub-product.
- **Issue**: 34 classes: the most frequent harmonized issues plus OTHER
  (configs/issue_mapping.yaml, reviewed in reports/m2_mapping_review.md).
- **Priority (proxy, SPEC B5)**: HIGH if the raw issue is on a 14-entry severity list, or the
  company response was "Closed with monetary relief", or the response was not timely.

| split | rows | HIGH rate | severity rule | monetary rule | untimely rule |
|---|---|---|---|---|---|
| train | 877,895 | 0.137 | 0.072 | 0.052 | 0.021 |
| val | 187,698 | 0.086 | 0.042 | 0.038 | 0.009 |
| test | 188,001 | 0.093 | 0.044 | 0.042 | 0.010 |

The two outcome fields are used only to derive this label and are dropped from every output
file; an assertion in `make data` checks it.

## Splits

Primary: a time split with no shuffling (rows of one date stay together).

| split | rows | first date | last date |
|---|---|---|---|
| train | 877,895 | 2015-03-19 | 2022-09-12 |
| val | 187,698 | 2022-09-13 | 2023-05-05 |
| test | 188,001 | 2023-05-06 | 2024-02-09 |

Assertions: no Complaint ID or normalized-text overlap across splits, strict date ordering. A
stratified random split (877,522 / 188,039 / 188,033 rows) was built for comparison, but no model
was trained on it, so the project cannot say how much random splitting overstates results.

## Shift, imbalance and noise

- **Label shift**: credit reporting is 0.405 of train, 0.605 of val and 0.566 of test;
  "Improper use of your report" is 0.063, 0.177 and 0.174. Cramér's V train vs val: product
  0.173, issue 0.211, priority 0.058.
- **Imbalance**: largest-to-smallest class ratio 24.359 (product) and 62.965 (issue, excluding
  OTHER) in train; 47.584 and 176.145 in val.
- **Label noise**: among duplicate-text groups, 1,254 (1.2%) carry more than one product class
  and 3,262 (3.1%) more than one issue class.
- **Taxonomy change**: the 2023-08-25 CFPB taxonomy change falls entirely inside the test split.
- **Confusable classes**: the largest credit-reporting issues share most top terms (Jaccard
  0.538).
- **Channel**: `submitted_via` is Web for every narrative row, so the channel slice is unusable.

## Privacy

Narratives were redacted by CFPB. Residual regex hits per 100,000 rows: email 17.2, SSN 0.0,
Luhn-valid card 1.0, phone 2.1, long digit runs 5.2 (314 rows with any hit). Names are not
detected (regex only), so name leaks are not measured. Raw text is never logged; reports hold
aggregates and complaint IDs only.
