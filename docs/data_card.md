# Data card: ComplaintIQ training data (CFPB complaint narratives)

This card closes the M2 data-card gap. Every number on it is copied from
`docs/data_provenance.md` (raw file) or `reports/m2_data_stats.md` (processed data, built by
`make data`). Sections of those files are cited as [prov] and [stats §N]. No complaint
text appears here.

## 1. Source and provenance

| Item | Value |
|---|---|
| Original source | CFPB Consumer Complaint Database, https://www.consumerfinance.gov/data-research/consumer-complaints/ [prov] |
| Copy actually used | Archived CC0 mirror on Hugging Face, `BEE-spoke-data/consumer-finance-complaints` [prov]. CFPB stopped publishing narratives in Aug 2026 (`configs/data.yaml`), so the mirror is the only narrative source. |
| Snapshot | Date received 2011-12-01 to 2024-02-17 [prov] |
| Prepared on | 2026-10-24 by `scripts/prepare_raw_data.py` (`make raw-data`) [prov] |
| Integrity | SHA-256 of the local CSV and of each of the 7 input Parquet files are listed in [prov] |
| Raw size | 4,707,579 rows, 18 columns; 1,689,593 rows (35.9%) have a non-empty narrative; 21 distinct Product values, 177 distinct Issue values [prov] |
| Licence | CC0 for the mirror (`configs/data.yaml`) |

Consumers consent to narrative publication; CFPB scrubs personal information before
publishing and replaces it with `XXXX` placeholders.

## 2. Schema

Columns read from the raw export (`configs/data.yaml: input_columns`): narrative, Product,
Issue, Date received, Company response to consumer, Timely response?, Complaint ID,
Submitted via, Company. Nothing else is read.

Processed split files (`data/processed/{time,random}/{train,val,test}.parquet`):

| column | role |
|---|---|
| `narrative` | **the only model input** (normalized text) |
| `product_class`, `issue_class` | labels (harmonized taxonomy) |
| `priority` | proxy label HIGH / NORMAL (section 5) |
| `product`, `issue` | raw labels, kept for audits and the severity rule |
| `date_received` | time split, drift and year slices |
| `company`, `submitted_via`, `n_words` | slices only, never model inputs |
| `complaint_id` | identifier for audits and error sampling |

The outcome columns "Company response to consumer" and "Timely response?" are used only to
derive `priority` and are dropped from every output file [stats §2: "no outcome columns in
outputs" assertion passed].

## 3. Cleaning funnel [stats §1]

| step | rows |
|---|---|
| non-empty narrative | 1,689,593 |
| after excluding products: Consumer Loan | 1,680,132 |
| after min_words >= 20 | 1,609,093 |
| after duplicate Complaint ID drop | 1,609,093 |
| after duplicate normalized-narrative drop (keep earliest) | 1,253,594 |

- Normalization: whitespace and unicode normalized; runs of `XXXX` placeholders become one
  `[REDACTED]` token.
- Duplicates: 103,762 groups of identical normalized narratives (459,261 rows before the
  drop). The key is the lowercased normalized text, so near-duplicates that differ by more
  than case, whitespace or placeholders are not caught (no MinHash).
- Length after cleaning (words): mean 203.571, p10 45, median 136, p90 421, p99 1,088,
  max 6,178 [stats §5].

## 4. Label definitions

- **Product (`product_class`)**: 10 classes after harmonizing the product taxonomy across
  years (`configs/product_mapping.yaml`), including `OTHER` [stats §3]. Card and prepaid are
  one class because the 2017-2023 product "Credit card or prepaid card" cannot be split
  without Sub-product. Pre-2017 "Consumer Loan" mixed vehicle, installment, title and pawn
  loans and was excluded (9,461 narrative rows) [stats §11].
- **Issue (`issue_class`)**: 34 classes: the most frequent harmonized issues plus `OTHER`
  for the rest (`configs/issue_mapping.yaml`; shift tests list 34 classes) [stats §3, §13].
- Mappings are versioned in `configs/` and reviewed in `reports/m2_mapping_review.md`.

## 5. Priority proxy label (SPEC B5)

`HIGH` if any of: (1) the raw Issue is on the severity list (`configs/severity_issues.yaml`,
14 entries, reproduced in [stats §11]: fraud or scam, identity theft, unauthorized
transactions, threatened legal action, improper third-party contact, harassing collection
contact); (2) company response is "Closed with monetary relief"; (3) "Timely response?" is
"No". Otherwise `NORMAL`.

| split | rows | HIGH rate | severity rule | monetary rule | untimely rule |
|---|---|---|---|---|---|
| train | 877,895 | 0.137 | 0.072 | 0.052 | 0.021 |
| val | 187,698 | 0.086 | 0.042 | 0.038 | 0.009 |
| test | 188,001 | 0.093 | 0.044 | 0.042 | 0.010 |

[stats §8; rules overlap, so rule shares do not sum to the HIGH rate.]

Limitations, stated openly:
- It is a **proxy**, not urgency judged at intake. Rules 2 and 3 are company outcomes; their
  rates change over time with company behaviour and CFPB processes (HIGH 0.207 in 2015 vs
  0.091 in 2023) [stats §8].
- Rule 1 makes priority partly a function of the issue label.
- "Communication tactics" is the largest contributor to the severity rule (22,271 rows,
  28.1% of severity-rule rows) and is a weak urgency signal [stats §11].

## 6. Splits [stats §2]

Primary: **time split** (no shuffling; rows of one date stay together).

| split | rows | first date | last date |
|---|---|---|---|
| train | 877,895 | 2015-03-19 | 2022-09-12 |
| val | 187,698 | 2022-09-13 | 2023-05-05 |
| test | 188,001 | 2023-05-06 | 2024-02-09 |

Assertions passed in `make data`: no Complaint ID or normalized-text overlap across splits,
strict date ordering. Secondary: a stratified random split on `product_class` (seed 42;
877,522 / 188,039 / 188,033 rows) to measure how much random splitting overstates results.

Use: train for fitting; val for model selection, calibration and thresholds (M4 splits it
into val-A for fitting and val-B for held-out reporting); test is read once, after the
freeze, by `scripts/final_test_eval.py`. Code refuses to load test unless
`CIQ_ALLOW_TEST=1`.

## 7. Known issues

- **Label shift over time.** Credit reporting is 0.405 of train, 0.605 of val and 0.566 of
  test; "Improper use of your report" is 0.063 of train vs 0.177 of val and 0.174 of test
  [stats §3, §11]. Cramér's V train vs val: product 0.173, issue 0.211, priority 0.058
  [stats §13].
- **Imbalance.** Largest/smallest class ratio in train: product 24.359, issue 62.965
  (excluding OTHER); in val 47.584 and 176.145 [stats §4]. Product OTHER has 291 train rows
  and 0 val rows [stats §3].
- **Label noise.** Among duplicate-text groups, 1,254 groups (1.2%) carry more than one
  product_class and 3,262 groups (3.1%) more than one issue_class [stats §6].
- **Taxonomy merges.** Pre-2017 "Account opening, closing, or management" (6,224 train rows)
  and related issues were merged into "Managing an account", adding noise to the
  opening/closing classes; the 2023-08-25 taxonomy change falls entirely in the test split
  [stats §11].
- **Confusable classes.** The three largest credit-reporting issues share many top terms
  (Jaccard 0.538 between "Incorrect information on your report" and "Problem with a
  company's investigation into an existing problem") [stats §14].
- **Channel slice unusable.** `submitted_via` is "Web" for all 1,253,594 narrative rows
  [stats §10].

## 8. Privacy limits

- Narratives were redacted by CFPB before publication. Residual regex hits per 100,000 rows
  (all splits): email 17.2, SSN 0.0, Luhn-valid card 1.0, phone 2.1, long digit runs 5.2;
  314 rows with any hit [stats §9]. Email hits include business addresses, so these are
  upper bounds.
- **Personal names are not detected** (regex only, no NER), so name leaks are not measured.
- `complaintiq.privacy.pii.scrub` runs at inference. Raw complaint text is never logged;
  reports contain aggregates and complaint IDs only. The M4 error sample for human
  labelling (`reports/m4/*_LOCAL.csv`) contains narratives and is gitignored.
- The raw CSV, processed splits and models are not committed (`/data/`, `/models/` are
  gitignored).
