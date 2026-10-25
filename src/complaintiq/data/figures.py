"""Static figures for reports/m2_data_stats.md (aggregates only, PNG via matplotlib Agg)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from complaintiq.data.split import SPLITS  # noqa: E402

# Categorical slots in fixed order (train, val, test), with recessive ink for text/grid.
SERIES = {"train": "#2a78d6", "val": "#eb6834", "test": "#1baf7a"}
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def _style(ax: plt.Axes) -> None:
    """Recessive axes: no top/right spines, light grid behind the marks."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=8)
    ax.set_axisbelow(True)


def _save(fig: plt.Figure, path: Path) -> None:
    fig.patch.set_facecolor(SURFACE)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _shares(df: pl.DataFrame, label: str) -> pl.DataFrame:
    """Share of each label value per split, wide (one column per split)."""
    return (
        df.group_by("split", label)
        .agg(n=pl.len())
        .with_columns(share=pl.col("n") / pl.col("n").sum().over("split"))
        .pivot(on="split", index=label, values="share")
        .fill_null(0.0)
    )


def _grouped_barh(ax: plt.Axes, labels: list[str], values: dict[str, list[float]]) -> None:
    """Horizontal grouped bars, one bar per split, with a small gap between bars."""
    y = np.arange(len(labels))
    h = 0.8 / len(values)
    for i, (split, vals) in enumerate(values.items()):
        ax.barh(
            y + (i - (len(values) - 1) / 2) * h,
            vals,
            height=h * 0.85,
            color=SERIES[split],
            label=split,
        )
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="lower right")


def product_by_split(df: pl.DataFrame, path: Path) -> None:
    """Product class share per split (time split)."""
    w = _shares(df, "product_class").sort("train", descending=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    _style(ax)
    _grouped_barh(ax, w["product_class"].to_list(), {s: w[s].to_list() for s in SPLITS})
    ax.set_title("Product class share per split (time split)", color=INK, fontsize=10, loc="left")
    _save(fig, path)


def length_histogram(df: pl.DataFrame, path: Path) -> None:
    """Narrative length (words) histogram with log-spaced bins and a log x axis."""
    w = df["n_words"].to_numpy()
    bins = np.logspace(np.log10(max(w.min(), 1)), np.log10(w.max()), 60)
    counts, edges = np.histogram(w, bins=bins)
    fig, ax = plt.subplots(figsize=(8, 4))
    _style(ax)
    ax.bar(edges[:-1], counts, width=np.diff(edges) * 0.9, align="edge", color=SERIES["train"])
    ax.set_xscale("log")
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_xlabel("words per narrative (log scale)", color=INK_2, fontsize=8)
    ax.set_ylabel("rows", color=INK_2, fontsize=8)
    med = float(np.median(w))
    ax.axvline(med, color=INK_2, linewidth=1, linestyle="--")
    ax.text(med * 1.05, counts.max() * 0.95, f"median {med:.0f}", color=INK_2, fontsize=8)
    ax.set_title("Narrative length, all splits", color=INK, fontsize=10, loc="left")
    _save(fig, path)


def high_rate_by_year(df: pl.DataFrame, path: Path) -> None:
    """HIGH priority rate per year of date received."""
    y = (
        df.group_by(year=pl.col("date_received").dt.year())
        .agg(rate=(pl.col("priority") == "HIGH").mean(), n=pl.len())
        .sort("year")
    )
    fig, ax = plt.subplots(figsize=(8, 4))
    _style(ax)
    ax.plot(y["year"], y["rate"], color=SERIES["train"], linewidth=2, marker="o", markersize=5)
    for yr, r in zip(y["year"].to_list(), y["rate"].to_list(), strict=True):
        ax.annotate(
            f"{r:.1%}",
            (yr, r),
            textcoords="offset points",
            xytext=(0, 6),
            ha="center",
            fontsize=7,
            color=INK_2,
        )
    ax.set_ylim(0, max(y["rate"]) * 1.25)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_xticks(y["year"].to_list())
    last = y["year"][-1]
    ax.set_title(
        f"HIGH priority rate per year ({last} is partial: data ends in February)",
        color=INK,
        fontsize=10,
        loc="left",
    )
    _save(fig, path)


def top_issues_train_vs_test(df: pl.DataFrame, path: Path, other: str, k: int = 15) -> None:
    """Top-k issue classes by train share: train vs test share."""
    w = (
        _shares(df, "issue_class")
        .filter(pl.col("issue_class") != other)
        .sort("train", descending=True)
        .head(k)
    )
    labels = [s if len(s) <= 48 else s[:45] + "..." for s in w["issue_class"].to_list()]
    fig, ax = plt.subplots(figsize=(8, 6))
    _style(ax)
    _grouped_barh(ax, labels, {s: w[s].to_list() for s in ("train", "test")})
    ax.set_title(
        f"Top {k} issue classes (by train share, excl. {other}): train vs test",
        color=INK,
        fontsize=10,
        loc="left",
    )
    _save(fig, path)


def write_figures(df: pl.DataFrame, out_dir: Path, other: str) -> dict[str, str]:
    """Write all M2 figures; returns {name: path relative to the reports/ folder}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = {
        "product_class_by_split": lambda p: product_by_split(df, p),
        "narrative_length_hist": lambda p: length_histogram(df, p),
        "high_rate_by_year": lambda p: high_rate_by_year(df, p),
        "top15_issues_train_vs_test": lambda p: top_issues_train_vs_test(df, p, other),
    }
    paths = {}
    for name, fn in jobs.items():
        path = out_dir / f"{name}.png"
        fn(path)
        paths[name] = f"{out_dir.name}/{path.name}"
    return paths
