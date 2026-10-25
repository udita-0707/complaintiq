"""`make data`: apply reviewed mappings, derive priority, split, check PII, write outputs."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import polars as pl

from complaintiq.config import config_dir
from complaintiq.data import analysis, figures, stats, taxonomy
from complaintiq.data.load import resolve
from complaintiq.data.pipeline import md_table, run_clean
from complaintiq.data.priority import assert_no_forbidden, derive_priority, severity_issues
from complaintiq.data.split import (
    SPLITS,
    assert_no_overlap,
    assert_time_order,
    random_split_expr,
)
from complaintiq.data.taxonomy import load_yaml
from complaintiq.privacy.pii import leak_report

OUTPUT_COLUMNS = [
    "complaint_id",
    "date_received",
    "narrative",
    "product",
    "product_class",
    "issue",
    "issue_class",
    "priority",
    "company",
    "submitted_via",
    "n_words",
]


def write_cutoffs(cutoffs: dict[str, date]) -> None:
    """Write the time-split cutoffs into configs/data.yaml in place (keeps comments)."""
    path = config_dir() / "data.yaml"
    text = path.read_text(encoding="utf-8")
    block = (
        "  cutoffs:  # written by the pipeline: last date of train and of val\n"
        f"    train_end: '{cutoffs['train_end']}'\n"
        f"    val_end: '{cutoffs['val_end']}'\n"
    )
    pattern = r"  cutoffs:.*\n(?:    .*\n)*"
    if not re.search(pattern, text):
        raise ValueError("split.cutoffs not found in configs/data.yaml")
    path.write_text(re.sub(pattern, block, text, count=1), encoding="utf-8")


def check_train_coverage(df: pl.DataFrame, other: str) -> None:
    """Fail if any non-OTHER class has zero training rows."""
    for col in ("product_class", "issue_class"):
        present = set(df[col].unique().to_list())
        trained = set(df.filter(pl.col("split") == "train")[col].unique().to_list())
        missing = sorted(present - trained - {other})
        if missing:
            raise AssertionError(f"{col} without training rows: {missing}")


def write_splits(df: pl.DataFrame, processed_dir: str, name: str) -> None:
    """Write ``<processed_dir>/<name>/{train,val,test}.parquet``."""
    out = resolve(processed_dir) / name
    out.mkdir(parents=True, exist_ok=True)
    for s in SPLITS:
        df.filter(pl.col("split") == s).select(OUTPUT_COLUMNS).write_parquet(out / f"{s}.parquet")


def build(cfg: dict[str, Any]) -> None:
    """Run the full M2 build."""
    other = cfg["taxonomy"]["other_label"]
    seed = int(cfg["seed"])

    res, cutoffs = run_clean(cfg)
    pmap, imap = taxonomy.product_map(cfg), taxonomy.issue_map(cfg)
    severity = severity_issues(cfg)
    df = derive_priority(taxonomy.apply_mappings(res.df.lazy(), cfg), cfg, severity).collect()
    assert_no_forbidden(df.columns, cfg)
    check_train_coverage(df, other)
    assert_time_order(df)
    assert_no_overlap(df)

    rnd = df.drop("split").with_columns(random_split_expr(cfg, seed))
    assert_no_overlap(rnd)

    write_cutoffs(cutoffs)
    write_splits(df, cfg["processed_dir"], "time")
    write_splits(rnd, cfg["processed_dir"], "random")

    report = render_report(cfg, res, cutoffs, df, rnd, pmap, imap)
    path = resolve(cfg["report_path"])
    path.write_text(report, encoding="utf-8")
    print(f"wrote {cfg['processed_dir']}/{{time,random}}/*.parquet and {cfg['report_path']}")


def render_report(
    cfg: dict[str, Any],
    res: Any,
    cutoffs: dict[str, date],
    df: pl.DataFrame,
    rnd: pl.DataFrame,
    pmap: dict[str, str],
    imap: dict[str, str],
) -> str:
    """Build the Markdown statistics report (aggregates only)."""
    other = cfg["taxonomy"]["other_label"]
    c = res.counts
    funnel = pl.DataFrame(
        {
            "step": [
                "non-empty narrative",
                "after excluding products: " + ", ".join(taxonomy.product_excluded(cfg)),
                f"after min_words >= {cfg['min_words']}",
                "after duplicate Complaint ID drop",
                "after duplicate normalized-narrative drop (keep earliest)",
            ],
            "rows": [
                c["narrative_rows"],
                c["after_exclude_products"],
                c["after_min_words"],
                c["after_dedup_id"],
                c["after_dedup_text"],
            ],
        }
    )
    sizes = pl.DataFrame(
        {
            "split": list(SPLITS),
            "time_rows": [df.filter(pl.col("split") == s).height for s in SPLITS],
            "time_first": [df.filter(pl.col("split") == s)["date_received"].min() for s in SPLITS],
            "time_last": [df.filter(pl.col("split") == s)["date_received"].max() for s in SPLITS],
            "random_rows": [rnd.filter(pl.col("split") == s).height for s in SPLITS],
        }
    )
    slices = stats.slice_exprs(df, cfg)
    sl = df.with_columns(**slices)
    pri_time = stats.priority_rates(df, "split")
    pri_year = stats.priority_rates(
        df.with_columns(year=pl.col("date_received").dt.year().cast(pl.String)), "year"
    )
    high = {s: pri_time.filter(pl.col("split") == s)["high_rate"][0] for s in SPLITS}
    year_df = df.with_columns(year=pl.col("date_received").dt.year().cast(pl.String))
    sev = load_yaml(cfg["taxonomy"]["severity_issues_path"])["issues"]
    sev_rows = (
        df.filter(pl.col("rule_severity"))
        .group_by("issue")
        .agg(n=pl.len())
        .with_columns(share=pl.col("n") / pl.col("n").sum())
        .sort("n", descending=True)
    )
    top_sev = sev_rows.row(0, named=True)
    improper = stats.class_share_by_split(df, "issue_class", "Improper use of your report")
    dup = stats.duplicate_conflicts(res.dup_groups, pmap, imap)
    via = df.group_by("submitted_via").agg(n=pl.len()).sort("n", descending=True)
    leaks = leak_report(df, cfg, "split")
    figs = figures.write_figures(df, resolve(cfg["figures_dir"]), other)
    shift = analysis.shift_tests(df, list(cfg["analysis"]["shift_labels"]))
    lex_pairs, lex_terms, lex_shared = analysis.lexical_overlap(df, cfg, int(cfg["seed"]))
    lc = cfg["analysis"]["lexical"]
    pii_cols = [col for col in leaks.columns if col.startswith("pii_")]
    leaks_per_100k = leaks.with_columns(
        (pl.col("pii_any") * pl.col("rows")).round(0).cast(pl.Int64).alias("rows_with_any_hit"),
        *[(pl.col(col) * 100_000).round(1).alias(f"{col}_per_100k") for col in pii_cols],
    ).select("split", "rows", "rows_with_any_hit", *[f"{col}_per_100k" for col in pii_cols])

    o: list[str] = [
        "# M2 data statistics",
        "",
        "Generated by `make data` (`python -m complaintiq.data.pipeline build`). Aggregates "
        "only; no complaint text. Source: Hugging Face mirror of the CFPB database "
        "(see docs/data_provenance.md).",
        "",
        "## 1. Cleaning funnel",
        "",
        md_table(funnel),
        "",
        f"Duplicate normalized-narrative groups: {c['duplicate_text_groups']:,} "
        f"({int(res.dup_groups['n'].sum()):,} rows before the drop). The hash key is the "
        "lowercased normalized text, so near-duplicates that differ by more than case, "
        "whitespace or placeholders are not caught (no MinHash).",
        "",
        "## 2. Splits",
        "",
        f"Time split cutoffs (also in `configs/data.yaml`): train <= {cutoffs['train_end']}, "
        f"val <= {cutoffs['val_end']}, test after. Rows of one date stay together. "
        "Assertions passed: no Complaint ID or normalized-text overlap across splits (both "
        "splits), strict date ordering (time split), no outcome columns in outputs. "
        f"Secondary split: stratified random on `{cfg['split']['random_stratify_on']}`, "
        f"seed {cfg['seed']}.",
        "",
        md_table(sizes),
        "",
        "## 3. Label distributions (time split)",
        "",
        "### Product class",
        "",
        md_table(stats.distribution(df, "product_class")),
        "",
        "### Issue class",
        "",
        md_table(stats.distribution(df, "issue_class")),
        "",
        "### Priority",
        "",
        md_table(stats.distribution(df, "priority")),
        "",
        "### Random split for comparison: product class",
        "",
        md_table(stats.distribution(rnd, "product_class")),
        "",
        "## 4. Imbalance ratios (largest / smallest class)",
        "",
        "Product class (excluding OTHER):",
        "",
        md_table(stats.imbalance(df, "product_class", other)),
        "",
        "Issue class (excluding OTHER):",
        "",
        md_table(stats.imbalance(df, "issue_class", other)),
        "",
        "Priority (HIGH vs NORMAL):",
        "",
        md_table(stats.imbalance(df, "priority")),
        "",
        "## 5. Narrative length (words, after normalization)",
        "",
        md_table(stats.length_stats(df, None)),
        "",
        md_table(stats.length_stats(df, "split")),
        "",
        "### Per product class",
        "",
        md_table(stats.length_stats(df, "product_class")),
        "",
        "### Per issue class",
        "",
        md_table(stats.length_stats(df, "issue_class")),
        "",
        f"### Effect of the min_words = {cfg['min_words']} cutoff per product class",
        "",
        "Counted on narrative rows before deduplication.",
        "",
        md_table(stats.min_words_effect(res.short_by_product, pmap)),
        "",
        "## 6. Duplicate narratives with conflicting labels (label-noise estimate)",
        "",
        "Among duplicate-text groups (identical normalized narrative, kept the earliest row), "
        "the groups whose members carry more than one label. Raw-label conflicts include "
        "taxonomy renames; class-level conflicts are the better noise estimate.",
        "",
        md_table(dup),
        "",
        "### Duplicate group sizes (class-level conflicts)",
        "",
        md_table(stats.dup_size_buckets(res.dup_groups, pmap, imap)),
        "",
        "## 7. Temporal label drift (share per year)",
        "",
        "### Product class",
        "",
        md_table(stats.by_year_share(df, "product_class")),
        "",
        "### Issue class",
        "",
        md_table(stats.by_year_share(df, "issue_class")),
        "",
        "## 8. Priority stability",
        "",
        "HIGH rate and the share of rows firing each B5 rule (rules overlap, so rule shares "
        "do not sum to the HIGH rate).",
        "",
        "### Per split (time)",
        "",
        md_table(pri_time),
        "",
        "### Per year",
        "",
        md_table(pri_year),
        "",
        "### Rule components per split (mutually exclusive; sums to the HIGH rate)",
        "",
        md_table(stats.priority_components(df, "split")),
        "",
        "### Rule components per year",
        "",
        md_table(stats.priority_components(year_df, "year")),
        "",
        f"**Limitation: base-rate shift.** HIGH is {high['train']:.1%} in train vs "
        f"{high['val']:.1%} in val vs {high['test']:.1%} in test. Rules 2 and 3 are "
        "company outcomes (monetary relief, untimely response) whose rates change over "
        "time with company behaviour and CFPB processes, and rule 1 depends on issue "
        "wording that changed in 2017 and 2023. A "
        "classifier tuned on train will see a different prior at test time; thresholds "
        "should be set on validation and the shift reported with every priority metric. "
        "Priority is a proxy label, not urgency judged at intake (SPEC B5).",
        "",
        "## 9. Residual PII (regex) leak rate",
        "",
        "Rows with at least one hit per pattern, per 100,000 rows. `pii_card` is the raw "
        "13-19 digit candidate; `pii_card_luhn` keeps only Luhn-valid ones; `pii_any` "
        "excludes raw card candidates. Email hits include business addresses, so rates are "
        "upper bounds.",
        "",
        md_table(leaks_per_100k),
        "",
        "**Limitation:** detection is regex only. Personal names are not detected, so "
        "residual name leaks are not measured. `complaintiq.privacy.pii.scrub` is the "
        "inference-time scrubber.",
        "",
        "## 10. Slices",
        "",
        "`submitted_via` is kept in the outputs but is unusable as a slice:",
        "",
        md_table(via),
        "",
        "Suggested slices instead:",
        "",
        "### Year",
        "",
        md_table(stats.slice_counts(sl, "year")),
        "",
        "### Narrative length bucket (words)",
        "",
        md_table(stats.slice_counts(sl, "length_bucket")),
        "",
        f"### Company size (top {cfg['slices']['top_companies']} by training rows vs rest)",
        "",
        md_table(stats.slice_counts(sl, "company_size")),
        "",
        "## 11. Data card notes",
        "",
        "### Priority severity list (SPEC B5 rule 1, matched on raw Issue)",
        "",
        md_table(
            pl.DataFrame({"issue": [e["name"] for e in sev], "reason": [e["reason"] for e in sev]})
        ),
        "",
        f"- **{top_sev['issue']}** is the largest contributor to the severity rule "
        f"({top_sev['n']:,} rows, {top_sev['share']:.1%} of severity-rule rows). It is a weak "
        "urgency signal: it covers harassing contact in general (repeated calls, abusive "
        "language), not only threats, so it inflates HIGH with complaints that are not "
        "urgent at intake.",
        "- Rule 1 makes priority partly a function of the issue label, and rules 2 and 3 are "
        "company outcomes, not urgency judged at intake. Outcome columns are dropped from all "
        "outputs.",
        "",
        "### Taxonomy caveats",
        "",
        '- **"Managing an account" merge noise.** The pre-2017 issue "Account opening, '
        'closing, or management" (and "Deposits and withdrawals", "Using a debit or ATM '
        'card") is merged into "Managing an account". The old issue also covered opening '
        'and closing, which since 2017 are separate classes ("Opening an account", '
        '"Closing an account"), so these pre-2017 training rows add label noise to all three '
        "classes. Sources of the class:",
        "",
        md_table(stats.class_sources(df, "issue_class", "Managing an account", "issue")),
        "",
        '- **"Improper use of your report" shift.** Its share is '
        f"{improper['train']:.1%} of train vs {improper['val']:.1%} of val and "
        f"{improper['test']:.1%} of test. The class prior moves sharply after the train "
        "cutoff, so time-split metrics for it reflect drift, not only model quality.",
        '- **Consumer Loan excluded.** Pre-2017 "Consumer Loan" mixed vehicle, installment, '
        "title and pawn loans and cannot be assigned to one class without Sub-product; "
        f"{c['narrative_rows'] - c['after_exclude_products']:,} narrative rows were dropped.",
        '- Card and prepaid are one class: the 2017-2023 product "Credit card or prepaid '
        'card" cannot be split without Sub-product.',
        "- The 2023-08-25 taxonomy change falls entirely in the test split; renamed values are "
        "merged in configs/product_mapping.yaml and configs/issue_mapping.yaml.",
        "",
        "## 12. Figures",
        "",
        f"![Product class share per split]({figs['product_class_by_split']})",
        "",
        f"![Narrative length histogram, log x]({figs['narrative_length_hist']})",
        "",
        f"![HIGH rate per year]({figs['high_rate_by_year']})",
        "",
        f"![Top-15 issue shares, train vs test]({figs['top15_issues_train_vs_test']})",
        "",
        "## 13. Label-distribution shift tests (time split)",
        "",
        "Jensen-Shannon divergence (base 2, 0 = identical, 1 = disjoint) and a chi-square "
        "test of homogeneity on the 2 x K table of class counts (no continuity correction). "
        "With ~10^5-10^6 rows every p-value is effectively 0, so read the effect sizes: "
        "Cramér's V (about 0.1 small, 0.3 medium, 0.5 large) and JSD.",
        "",
        md_table(shift),
        "",
        "## 14. Lexical overlap between confusable credit-reporting issues",
        "",
        f"The {lc['n_classes']} largest issue classes of `{lc['product_class']}` in train "
        "(the classes most likely to be confused). TF-IDF (sublinear tf, English stop words "
        f"plus the placeholder, alphabetic terms, min_df={lc['min_df']}) is fit on a seeded "
        f"sample of {lc['sample_per_class']:,} training rows per class; each class's top "
        f"{lc['top_terms']} terms by mean TF-IDF are compared with Jaccard similarity.",
        "",
        md_table(lex_pairs),
        "",
        md_table(lex_terms),
        "",
        f"Terms in the top {lc['top_terms']} of all three classes: " + ", ".join(lex_shared),
        "",
    ]
    return "\n".join(o)
