"""Statistical analysis for the M2 report (SPEC C4): label-shift tests and lexical overlap.

Aggregates only. Lexical overlap reports vocabulary terms, never narrative text.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
from scipy.stats import chi2_contingency  # installed via the pinned scikit-learn
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer


def _counts(df: pl.DataFrame, label: str, a: str, b: str) -> tuple[np.ndarray, np.ndarray]:
    """Aligned class-count vectors for splits ``a`` and ``b`` (classes seen in either)."""
    c = (
        df.filter(pl.col("split").is_in([a, b]))
        .group_by(label)
        .agg(
            (pl.col("split") == a).sum().alias("a"),
            (pl.col("split") == b).sum().alias("b"),
        )
        .sort(label)
    )
    return c["a"].to_numpy().astype(float), c["b"].to_numpy().astype(float)


def jensen_shannon(p: np.ndarray, q: np.ndarray) -> float:
    """Jensen-Shannon divergence (base 2, in [0, 1]) between two count vectors."""
    p, q = p / p.sum(), q / q.sum()
    m = 0.5 * (p + q)

    def kl(x: np.ndarray) -> float:
        nz = x > 0
        return float(np.sum(x[nz] * np.log2(x[nz] / m[nz])))

    return 0.5 * kl(p) + 0.5 * kl(q)


def shift_tests(df: pl.DataFrame, labels: list[str], ref: str = "train") -> pl.DataFrame:
    """JSD and chi-square homogeneity test of each label's distribution, ``ref`` vs val/test.

    Cramér's V is reported as the effect size: with ~10^5-10^6 rows every p-value is tiny,
    so V and JSD carry the information.
    """
    rows = []
    for label in labels:
        for other in ("val", "test"):
            a, b = _counts(df, label, ref, other)
            table = np.vstack([a, b])
            chi2, p, dof, _ = chi2_contingency(table, correction=False)
            n = table.sum()
            v = float(np.sqrt(chi2 / (n * (min(table.shape) - 1))))
            rows.append(
                {
                    "label": label,
                    "comparison": f"{ref} vs {other}",
                    "classes": int((table.sum(axis=0) > 0).sum()),
                    "jsd": jensen_shannon(a, b),
                    "chi2": float(chi2),
                    "dof": int(dof),
                    "p_value": f"{p:.2e}",
                    "cramers_v": v,
                }
            )
    return pl.DataFrame(rows)


def confusable_issue_classes(df: pl.DataFrame, cfg: dict[str, Any]) -> list[str]:
    """The ``k`` largest non-OTHER issue classes of the configured product class in train."""
    lc = cfg["analysis"]["lexical"]
    return (
        df.filter(
            (pl.col("split") == "train")
            & (pl.col("product_class") == lc["product_class"])
            & (pl.col("issue_class") != cfg["taxonomy"]["other_label"])
        )
        .group_by("issue_class")
        .agg(n=pl.len())
        .sort(["n", "issue_class"], descending=[True, False])
        .head(int(lc["n_classes"]))["issue_class"]
        .to_list()
    )


def lexical_overlap(
    df: pl.DataFrame, cfg: dict[str, Any], seed: int
) -> tuple[pl.DataFrame, pl.DataFrame, list[str]]:
    """Top-N TF-IDF terms per class and pairwise Jaccard overlap of those term sets.

    TF-IDF is fit on a seeded per-class sample of training rows. A class's terms are ranked
    by mean TF-IDF weight over its rows. Returns (pairwise Jaccard, distinctive terms per
    class, terms shared by all classes).
    """
    lc = cfg["analysis"]["lexical"]
    classes = confusable_issue_classes(df, cfg)
    sample = pl.concat(
        [
            df.filter((pl.col("split") == "train") & (pl.col("issue_class") == c))
            .select("issue_class", "narrative")
            .sample(n=int(lc["sample_per_class"]), seed=seed, shuffle=True)
            for c in classes
        ]
    )
    stop = list(ENGLISH_STOP_WORDS | set(lc["extra_stop_words"]))
    vec = TfidfVectorizer(
        stop_words=stop,
        min_df=int(lc["min_df"]),
        sublinear_tf=True,
        lowercase=True,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]+\b",  # alphabetic terms only, no digits
    )
    x = vec.fit_transform(sample["narrative"].to_list())
    vocab = np.asarray(vec.get_feature_names_out())
    labels = sample["issue_class"].to_numpy()
    top_n = int(lc["top_terms"])
    terms: dict[str, list[str]] = {}
    for c in classes:
        mean = np.asarray(x[labels == c].mean(axis=0)).ravel()
        terms[c] = vocab[np.argsort(-mean, kind="stable")[:top_n]].tolist()
    pairs = []
    for i, a in enumerate(classes):
        for b in classes[i + 1 :]:
            sa, sb = set(terms[a]), set(terms[b])
            pairs.append(
                {
                    "class_a": a,
                    "class_b": b,
                    "shared_terms": len(sa & sb),
                    "jaccard": len(sa & sb) / len(sa | sb),
                }
            )
    shared_all = set.intersection(*(set(t) for t in terms.values()))
    per_class = pl.DataFrame(
        {
            "issue_class": classes,
            "sampled_rows": [int((labels == c).sum()) for c in classes],
            "distinctive_terms (top-N, not shared with the other classes)": [
                ", ".join(t for t in terms[c] if all(t not in terms[o] for o in classes if o != c))
                for c in classes
            ],
        }
    )
    return pl.DataFrame(pairs), per_class, sorted(shared_all)
