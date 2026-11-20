"""Confidence calibration, gate threshold and priority threshold (SPEC C5, C6; M4).

Protocol: val is split once into val-A and val-B (seeded, stratified; ``configs/eval.yaml:
val_split``). The temperature, the gate threshold tau and the priority threshold are fit
on **val-A**; every number reported as held-out is computed on **val-B**. The test split
is never read here. Never prints or logs complaint text.

CLI::

    python -m complaintiq.models.calibrate run [--no-write-config]
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from complaintiq.config import config_dir, load_config
from complaintiq.data.load import resolve

logger = logging.getLogger("complaintiq.models.calibrate")

EPS = 1e-12
SERIES_1 = "#2a78d6"  # categorical slot 1 (blue)
SERIES_2 = "#eb6834"  # categorical slot 2 (orange)
INK = "#3d3d3a"
GRID = "#e4e3dd"


# --------------------------------------------------------------------------- val-A / val-B


def split_val_ab(labels: Sequence[str] | np.ndarray, frac_a: float, seed: int) -> np.ndarray:
    """Boolean mask, True = val-A. Seeded and stratified on ``labels``.

    Every class is shuffled with the seed and its first ``round(n_class * frac_a)`` rows go
    to val-A, so both halves keep the class mix. Same inputs give the same mask.
    """
    y = np.asarray(labels)
    df = pl.DataFrame({"y": y}).with_row_index("_i")
    shuffled = df.sample(fraction=1.0, shuffle=True, seed=seed)
    ranked = shuffled.with_columns(
        _r=pl.int_range(pl.len()).over("y"), _n=pl.len().over("y")
    ).with_columns(_a=pl.col("_r") < (pl.col("_n") * frac_a).round())
    mask = np.zeros(len(y), dtype=bool)
    idx = ranked.filter(pl.col("_a"))["_i"].to_numpy()
    mask[idx] = True
    return mask


# --------------------------------------------------------------------------- temperature


def apply_temperature(prob: np.ndarray, temperature: float) -> np.ndarray:
    """Temperature-scale a probability matrix: ``softmax(log p / T)`` per row.

    ``T = 1`` returns the row-normalized input; ``T > 1`` softens, ``T < 1`` sharpens.
    The argmax never changes.
    """
    p = np.asarray(prob, dtype=np.float64)
    if temperature == 1.0:
        return p / p.sum(axis=1, keepdims=True)
    z = np.log(np.clip(p, EPS, None)) / temperature
    z -= z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def nll(prob: np.ndarray, y_idx: np.ndarray) -> float:
    """Mean negative log-likelihood of the true class."""
    return float(-np.log(np.clip(prob[np.arange(len(y_idx)), y_idx], EPS, None)).mean())


def fit_temperature(
    prob: np.ndarray, y_idx: np.ndarray, bounds: tuple[float, float] = (0.05, 20.0)
) -> float:
    """Temperature minimizing the NLL of ``apply_temperature(prob, T)`` (bounded search)."""
    res = minimize_scalar(
        lambda t: nll(apply_temperature(prob, t), y_idx),
        bounds=bounds,
        method="bounded",
        options={"xatol": 1e-4},
    )
    return float(res.x)


# --------------------------------------------------------------------------- reliability


def reliability_bins(
    confidence: np.ndarray, correct: np.ndarray, n_bins: int = 15
) -> pl.DataFrame:
    """Equal-width confidence bins: ``bin_lo, bin_hi, n, mean_conf, accuracy``."""
    conf = np.asarray(confidence, dtype=float)
    ok = np.asarray(correct, dtype=bool)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    b = np.clip(np.digitize(conf, edges[1:-1], right=True), 0, n_bins - 1)
    rows = []
    for i in range(n_bins):
        m = b == i
        n = int(m.sum())
        rows.append(
            {
                "bin_lo": float(edges[i]),
                "bin_hi": float(edges[i + 1]),
                "n": n,
                "mean_conf": float(conf[m].mean()) if n else float("nan"),
                "accuracy": float(ok[m].mean()) if n else float("nan"),
            }
        )
    return pl.DataFrame(rows)


def expected_calibration_error(
    confidence: np.ndarray, correct: np.ndarray, n_bins: int = 15
) -> float:
    """ECE: sum over bins of (bin share) * |accuracy - mean confidence| (top-1 label)."""
    bins = reliability_bins(confidence, correct, n_bins).filter(pl.col("n") > 0)
    n = int(bins["n"].sum())
    if n == 0:
        return float("nan")
    gap = (bins["accuracy"] - bins["mean_conf"]).abs()
    return float((bins["n"] * gap).sum() / n)


# --------------------------------------------------------------------------- thresholds


def coverage_precision(
    confidence: np.ndarray, correct: np.ndarray, thresholds: Sequence[float]
) -> pl.DataFrame:
    """For each threshold t: coverage = share with conf >= t, precision = accuracy there."""
    conf = np.asarray(confidence, dtype=float)
    ok = np.asarray(correct, dtype=bool)
    rows = []
    for t in thresholds:
        m = conf >= t
        n = int(m.sum())
        rows.append(
            {
                "threshold": float(t),
                "coverage": float(n / len(conf)) if len(conf) else float("nan"),
                "n_auto": n,
                "precision": float(ok[m].mean()) if n else float("nan"),
            }
        )
    return pl.DataFrame(rows)


def choose_tau(
    confidence: np.ndarray,
    correct: np.ndarray,
    target_precision: float = 0.95,
    min_rows: int = 1,
) -> dict[str, float] | None:
    """Smallest threshold whose auto-routed rows reach ``target_precision`` (max coverage).

    Candidates are the observed confidences; a candidate must keep at least ``min_rows``
    rows. Returns ``{"tau", "precision", "coverage", "n_auto"}`` or ``None`` if no
    threshold reaches the target.
    """
    conf = np.asarray(confidence, dtype=float)
    ok = np.asarray(correct, dtype=bool)
    order = np.argsort(-conf, kind="stable")
    c, k = conf[order], ok[order]
    cum_ok = np.cumsum(k)
    n_at = np.arange(1, len(c) + 1)
    prec = cum_ok / n_at
    # Only the last position of a run of equal confidences is a valid cut (ties included).
    last_of_tie = np.r_[c[1:] != c[:-1], True]
    valid = last_of_tie & (prec >= target_precision) & (n_at >= min_rows)
    if not valid.any():
        return None
    i = int(np.flatnonzero(valid).max())
    return {
        "tau": float(c[i]),
        "precision": float(prec[i]),
        "coverage": float(n_at[i] / len(c)),
        "n_auto": int(n_at[i]),
    }


def choose_priority_threshold(
    y_true: np.ndarray, score: np.ndarray, target_recall: float = 0.85
) -> float:
    """Highest score threshold whose HIGH recall is at least ``target_recall``."""
    yt = np.asarray(y_true).astype(bool)
    pos = np.sort(np.asarray(score, dtype=float)[yt])[::-1]
    if len(pos) == 0:
        raise ValueError("no positive rows")
    k = int(np.ceil(target_recall * len(pos)))  # need at least k positives above threshold
    return float(pos[max(k, 1) - 1])


def binary_at(y_true: np.ndarray, score: np.ndarray, threshold: float) -> dict[str, float]:
    """Precision, recall, F1 and flagged share of ``score >= threshold``."""
    yt = np.asarray(y_true).astype(bool)
    pred = np.asarray(score) >= threshold
    tp = int((pred & yt).sum())
    precision = tp / pred.sum() if pred.sum() else 0.0
    recall = tp / yt.sum() if yt.sum() else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "flagged_share": float(pred.mean()),
    }


# --------------------------------------------------------------------------- figures


def _style(ax: Any) -> None:
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK, labelsize=9)


def plot_reliability(
    before: pl.DataFrame, after: pl.DataFrame, title: str, path: str | Path
) -> None:
    """Reliability diagram (accuracy vs mean confidence per bin), before and after."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.2, 4.6), dpi=150)
    _style(ax)
    ax.plot([0, 1], [0, 1], color="#a3a29a", linewidth=1, linestyle="--", label="perfect")
    for df, color, name in ((before, SERIES_2, "before"), (after, SERIES_1, "after")):
        d = df.filter(pl.col("n") > 0)
        ax.plot(d["mean_conf"], d["accuracy"], color=color, linewidth=2, marker="o",
                markersize=4, label=name)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("mean confidence in bin", color=INK, fontsize=9)
    ax.set_ylabel("accuracy in bin", color=INK, fontsize=9)
    ax.set_title(title, color=INK, fontsize=10, loc="left")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left")
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def plot_coverage_precision(
    curve: pl.DataFrame, tau: float | None, target: float, title: str, path: str | Path
) -> None:
    """Coverage (x) vs precision (y) on val-B as the threshold sweeps; tau marked."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.2, 4.2), dpi=150)
    _style(ax)
    d = curve.filter(pl.col("n_auto") > 0)
    ax.plot(d["coverage"], d["precision"], color=SERIES_1, linewidth=2)
    ax.axhline(target, color="#a3a29a", linewidth=1, linestyle="--")
    ax.text(0.01, target + 0.003, f"target precision {target:.2f}", color=INK, fontsize=8)
    if tau is not None:
        row = curve.filter(pl.col("threshold") == tau)
        if row.height:
            x, y = float(row["coverage"][0]), float(row["precision"][0])
            ax.plot([x], [y], "o", color=SERIES_1, markersize=8, markeredgecolor="white")
            ax.annotate(f"tau={tau:.4f}\ncoverage {x:.4f}\nprecision {y:.4f}", (x, y),
                        xytext=(-96, -48), textcoords="offset points", color=INK, fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_xlabel("coverage (share auto-routed)", color=INK, fontsize=9)
    ax.set_ylabel("precision of auto-routed product", color=INK, fontsize=9)
    ax.set_title(title, color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


# --------------------------------------------------------------------------- config output


def render_thresholds_yaml(values: dict[str, Any], source: str) -> str:
    """Text for ``configs/thresholds.yaml``; keeps the ``tau`` key, adds the new ones."""
    return (
        "# Confidence gate (SPEC B4 FR4, C5) and calibration (M4).\n"
        f"# Written by `python -m complaintiq.models.calibrate run` ({source}).\n"
        "# Fit on val-A (seeded stratified half of val, configs/eval.yaml: val_split);\n"
        "# held-out numbers are on val-B in reports/m4/calibration_report.md.\n"
        "# tau: smallest calibrated product confidence with val-A precision >= "
        f"{values['target_precision']} (max coverage).\n"
        f"tau: {values['tau']:.6f}\n"
        "# Temperature scaling on log-probabilities (1.0 = uncalibrated M3 behaviour).\n"
        f"temperature_product: {values['temperature_product']:.6f}\n"
        f"temperature_issue: {values['temperature_issue']:.6f}\n"
        "# Priority HIGH threshold on P(HIGH): highest with val-A recall >= "
        f"{values['priority_target_recall']}.\n"
        f"priority_threshold: {values['priority_threshold']:.6f}\n"
    )


# --------------------------------------------------------------------------- run


def _md(df: pl.DataFrame, digits: int = 3) -> str:
    def cell(v: Any) -> str:
        if isinstance(v, float):
            return "" if np.isnan(v) else f"{v:.{digits}f}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)

    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * len(df.columns)
    return "\n".join([head, sep, *("| " + " | ".join(cell(v) for v in r) + " |"
                                   for r in df.iter_rows())])


def run(write_config: bool = True) -> dict[str, Any]:
    """Fit calibration on val-A, report on val-B, write report, figures and thresholds."""
    from complaintiq.data.training_data import LABEL_COLS, load_split
    from complaintiq.eval.metrics import priority_metrics
    from complaintiq.eval.tracking import log_run
    from complaintiq.models.baseline import (
        HIGH,
        TEXT_COL,
        BaselineModel,
        load_baseline_config,
        transform_chunked,
    )

    ecfg = load_config("eval")
    ccfg = ecfg["calibration"]
    vs = ecfg["val_split"]
    model_dir = resolve(ecfg["primary_model_dir"])
    model = BaselineModel.load(model_dir)
    meta = model.meta
    for t in ("product", "issue", "priority"):
        if t not in model.classifiers:
            raise ValueError(f"{model_dir} lacks task {t}; run baseline add-tasks first")

    val = load_split("val", columns=[TEXT_COL, *LABEL_COLS.values()])
    mask_a = split_val_ab(val[vs["stratify_col"]].to_numpy(), vs["frac_a"], vs["seed"])
    X = transform_chunked(
        model.vectorizer, val[TEXT_COL], load_baseline_config()["features"]["transform_chunk_rows"]
    )
    res: dict[str, Any] = {
        "model_id": ecfg["primary_model_id"],
        "model_version": meta["model_version"],
        "data_version": meta["data_version"],
        "n_val": val.height,
        "n_val_a": int(mask_a.sum()),
        "n_val_b": int((~mask_a).sum()),
    }
    figs = resolve(ccfg["figures_dir"])
    nb = ccfg["n_bins"]
    for task in ("product", "issue"):
        labels, prob = model.scores(task, X)
        y = val[LABEL_COLS[task]].to_numpy()
        index = {lbl: i for i, lbl in enumerate(labels)}
        y_idx = np.array([index[v] for v in y])
        T = fit_temperature(prob[mask_a], y_idx[mask_a], tuple(ccfg["temperature_bounds"]))
        cal = apply_temperature(prob, T)
        raw = prob / prob.sum(axis=1, keepdims=True)
        correct = raw.argmax(axis=1) == y_idx
        r: dict[str, Any] = {"temperature": T}
        for name, part in (("val_a", mask_a), ("val_b", ~mask_a)):
            r[name] = {
                "accuracy": float(correct[part].mean()),
                "ece_before": expected_calibration_error(raw[part].max(1), correct[part], nb),
                "ece_after": expected_calibration_error(cal[part].max(1), correct[part], nb),
                "nll_before": nll(raw[part], y_idx[part]),
                "nll_after": nll(cal[part], y_idx[part]),
            }
        rb_before = reliability_bins(raw[~mask_a].max(1), correct[~mask_a], nb)
        rb_after = reliability_bins(cal[~mask_a].max(1), correct[~mask_a], nb)
        r["bins_before_b"], r["bins_after_b"] = rb_before, rb_after
        plot_reliability(rb_before, rb_after, f"{task}: reliability on val-B (T={T:.3f})",
                         figs / f"reliability_{task}.png")
        if task == "product":
            conf = cal.max(axis=1)
            choice = choose_tau(conf[mask_a], correct[mask_a], ccfg["target_precision"],
                                ccfg["min_auto_rows"])
            r["tau_choice_val_a"] = choice
            tau = choice["tau"] if choice else 1.0
            grid = sorted({*np.round(np.arange(0.30, 1.0, 0.05), 2).tolist(), 0.99, tau})
            r["curve_b"] = coverage_precision(conf[~mask_a], correct[~mask_a], grid)
            fine = sorted({*np.linspace(0.0, 1.0, 201).tolist(), tau})
            fine_curve = coverage_precision(conf[~mask_a], correct[~mask_a], fine)
            plot_coverage_precision(fine_curve, tau, ccfg["target_precision"],
                                    "product gate: coverage vs precision on val-B",
                                    figs / "coverage_precision_product.png")
            r["tau"] = tau
            r["at_tau_b"] = r["curve_b"].filter(pl.col("threshold") == tau).to_dicts()[0]
            r["at_tau_a"] = coverage_precision(conf[mask_a], correct[mask_a], [tau]).to_dicts()[0]
        res[task] = r

    labels, prob = model.scores("priority", X)
    y_bin = (val[LABEL_COLS["priority"]].to_numpy() == HIGH).astype(int)
    score = prob[:, labels.index(HIGH)]
    thr = choose_priority_threshold(y_bin[mask_a], score[mask_a], ccfg["priority_target_recall"])
    res["priority"] = {
        "threshold": thr,
        "at_thr_a": binary_at(y_bin[mask_a], score[mask_a], thr),
        "at_thr_b": binary_at(y_bin[~mask_a], score[~mask_a], thr),
        "at_0_5_b": binary_at(y_bin[~mask_a], score[~mask_a], 0.5),
        "pr_auc_b": priority_metrics(y_bin[~mask_a], score[~mask_a], 0.5)["pr_auc"],
        "base_rate_b": float(y_bin[~mask_a].mean()),
    }
    maxf1_a = priority_metrics(y_bin[mask_a], score[mask_a])["threshold"]
    res["priority"]["maxf1_threshold_a"] = maxf1_a
    res["priority"]["at_maxf1_b"] = binary_at(y_bin[~mask_a], score[~mask_a], maxf1_a)

    values = {
        "tau": res["product"]["tau"],
        "target_precision": ccfg["target_precision"],
        "temperature_product": res["product"]["temperature"],
        "temperature_issue": res["issue"]["temperature"],
        "priority_threshold": thr,
        "priority_target_recall": ccfg["priority_target_recall"],
    }
    exp_dir = resolve(ecfg["experiments_dir"])
    hp_base = {"model_id": ecfg["primary_model_id"], "val_split": vs, "calibration": ccfg}
    run_ids = {}
    for task in ("product", "issue"):
        r = res[task]
        b = r["val_b"]
        extra = ""
        if task == "product":
            extra = (f"; tau={r['tau']:.4f} val-B coverage={r['at_tau_b']['coverage']:.4f}"
                     f" precision={r['at_tau_b']['precision']:.4f}")
        run_ids[task] = log_run(
            "calibration", exp_dir, data_version=meta["data_version"],
            model=ecfg["primary_model_id"], task=LABEL_COLS[task],
            hyperparams={**hp_base, "temperature": r["temperature"]}, seed=vs["seed"],
            n_train=meta["n_train"], owner=ecfg["owner"],
            notes=(f"calibration: temperature fit on val-A (n={res['n_val_a']}), reported on"
                   f" val-B (n={res['n_val_b']}); T={r['temperature']:.4f};"
                   f" ECE val-B {b['ece_before']:.4f} -> {b['ece_after']:.4f};"
                   f" NLL val-B {b['nll_before']:.4f} -> {b['nll_after']:.4f}{extra}"),
        )
    p = res["priority"]
    run_ids["priority"] = log_run(
        "calibration", exp_dir, data_version=meta["data_version"],
        model=ecfg["primary_model_id"], task="priority",
        hyperparams={**hp_base, "priority_threshold": thr}, seed=vs["seed"],
        n_train=meta["n_train"], owner=ecfg["owner"], val_pr_auc=p["pr_auc_b"],
        notes=(f"calibration: priority threshold {thr:.4f} chosen on val-A for recall >="
               f" {ccfg['priority_target_recall']}; val-B precision"
               f" {p['at_thr_b']['precision']:.4f} recall {p['at_thr_b']['recall']:.4f};"
               " val_pr_auc is val-B"),
    )
    res["run_ids"] = run_ids
    if write_config:
        (config_dir() / "thresholds.yaml").write_text(
            render_thresholds_yaml(values, f"run_ids {', '.join(run_ids.values())}")
        )
    _save_json(res, resolve(ecfg["reports_dir"]) / "results" / "calibration.json")
    write_report(res, values, ccfg, resolve(ccfg["report_path"]))
    return res


def _save_json(res: dict[str, Any], path: Path) -> None:
    def conv(v: Any) -> Any:
        if isinstance(v, pl.DataFrame):
            return v.to_dicts()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(conv(res), indent=2, sort_keys=True))


def write_report(
    res: dict[str, Any], values: dict[str, Any], ccfg: dict[str, Any], path: Path
) -> None:
    """Markdown calibration report (val-A fitted, val-B held-out)."""
    pr, iss, pri = res["product"], res["issue"], res["priority"]
    ch = pr["tau_choice_val_a"]
    out = [
        "# M4 calibration, confidence gate and priority threshold",
        "",
        "Generated by `python -m complaintiq.models.calibrate run` (`make calibrate`)."
        " The test split was not read.",
        "",
        f"- Model: `{res['model_id']}` (model_version `{res['model_version']}`,"
        f" data_version `{res['data_version']}`).",
        f"- val ({res['n_val']:,} rows) is split once into **val-A** ({res['n_val_a']:,}) and"
        f" **val-B** ({res['n_val_b']:,}), seeded and stratified on issue_class"
        " (`configs/eval.yaml: val_split`).",
        "- **Fit on val-A:** temperatures, tau, priority threshold. **Held-out = val-B:** every"
        " number in a column or row labelled val-B. val-A numbers are in-sample for the fitted"
        " value and are shown only for reference.",
        "- Caveat: val was also used in M3 to choose this model among the variants, so val-B is"
        " held out from calibration and threshold choice, not from model selection.",
        "- Experiment log: `reports/experiments/m4/calibration.csv`, run_ids "
        + ", ".join(f"{t} `{r}`" for t, r in res["run_ids"].items()) + ".",
        "",
        "## Temperature scaling (product and issue)",
        "",
        "Method: `softmax(log p / T)` on the model's probabilities, T minimizing NLL on val-A."
        f" ECE uses {ccfg['n_bins']} equal-width bins on the top-1 confidence. The argmax is"
        " unchanged, so accuracy and F1 are unchanged.",
        "",
        "| task | T (val-A) | accuracy val-B | ECE val-B before | ECE val-B after |"
        " NLL val-B before | NLL val-B after | ECE val-A before | ECE val-A after |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for task, r in (("product", pr), ("issue", iss)):
        a, b = r["val_a"], r["val_b"]
        out.append(
            f"| {task} | {r['temperature']:.3f} | {b['accuracy']:.3f} | {b['ece_before']:.4f} |"
            f" {b['ece_after']:.4f} | {b['nll_before']:.3f} | {b['nll_after']:.3f} |"
            f" {a['ece_before']:.4f} | {a['ece_after']:.4f} |"
        )
    target = 0.05
    out += [
        "",
        f"SPEC A5 target: ECE < {target} after temperature scaling. val-B: product "
        f"{'meets' if pr['val_b']['ece_after'] < target else 'misses'} it"
        f" ({pr['val_b']['ece_after']:.4f}), issue "
        f"{'meets' if iss['val_b']['ece_after'] < target else 'misses'} it"
        f" ({iss['val_b']['ece_after']:.4f}).",
        "",
        "Reliability diagrams on val-B (before = raw model probabilities, after = temperature):",
        "",
        "![product reliability](figures/reliability_product.png)",
        "![issue reliability](figures/reliability_issue.png)",
        "",
        "Product reliability bins on val-B:",
        "",
        _md(pr["bins_before_b"].rename({"mean_conf": "conf_before", "accuracy": "acc_before"})
            .with_columns(conf_after=pr["bins_after_b"]["mean_conf"],
                          acc_after=pr["bins_after_b"]["accuracy"],
                          n_after=pr["bins_after_b"]["n"])),
        "",
        "## Confidence gate tau (product)",
        "",
        "Auto-route precision = product accuracy among complaints with calibrated product"
        " confidence >= tau (routing is decided by product, SPEC B6).",
        "",
    ]
    if ch is None:
        out += [f"No threshold reaches precision {values['target_precision']} on val-A; tau"
                " set to 1.0 (everything goes to human review).", ""]
    else:
        a, b = pr["at_tau_a"], pr["at_tau_b"]
        out += [
            f"tau = **{pr['tau']:.4f}**: the smallest threshold with val-A precision >="
            f" {values['target_precision']} (at least {ccfg['min_auto_rows']} rows).",
            "",
            "| split | role | coverage | n auto-routed | precision |",
            "|---|---|---|---|---|",
            f"| val-A | chosen here | {a['coverage']:.4f} | {a['n_auto']:,} |"
            f" {a['precision']:.4f} |",
            f"| val-B | **held-out** | **{b['coverage']:.4f}** | {b['n_auto']:,} |"
            f" **{b['precision']:.4f}** |",
            "",
            "SPEC A5 target: auto-route coverage >= 0.60 at >= 0.95 precision. On val-B,"
            f" coverage {b['coverage']:.4f} {'meets' if b['coverage'] >= 0.6 else 'misses'}"
            f" the 0.60 target; precision {b['precision']:.4f}"
            f" {'meets' if b['precision'] >= 0.95 else 'misses'} the 0.95 target"
            f" (difference {b['precision'] - 0.95:+.4f}). A threshold chosen to hit 0.95"
            " exactly on val-A lands on either side of it on held-out data.",
            "",
            "Temperature scaling is monotone, so the same rows are auto-routed as with an"
            " uncalibrated threshold at the matching raw confidence; calibration changes the"
            " meaning of tau (a probability), not the ranking.",
            "",
        ]
    out += [
        "Coverage-precision curve on val-B (held-out):",
        "",
        "![coverage vs precision](figures/coverage_precision_product.png)",
        "",
        _md(pr["curve_b"], 4),
        "",
        "## Priority threshold",
        "",
        f"Chosen on val-A: the highest threshold on P(HIGH) with HIGH recall >="
        f" {values['priority_target_recall']} (SPEC A5: recall >= 0.85 at acceptable"
        f" precision). Threshold **{pri['threshold']:.4f}**. val-B HIGH base rate"
        f" {pri['base_rate_b']:.4f}, val-B PR-AUC **{pri['pr_auc_b']:.4f}**.",
        "",
        "| threshold | how chosen | split | precision | recall | F1 | flagged share |",
        "|---|---|---|---|---|---|---|",
    ]
    rows = [
        ("recall >= target on val-A", "val-A", pri["at_thr_a"]),
        ("recall >= target on val-A", "val-B (held-out)", pri["at_thr_b"]),
        ("max F1 on val-A", "val-B (held-out)", pri["at_maxf1_b"]),
        ("fixed 0.5 (M3 default)", "val-B (held-out)", pri["at_0_5_b"]),
    ]
    for how, split, m in rows:
        out.append(f"| {m['threshold']:.4f} | {how} | {split} | {m['precision']:.4f} |"
                   f" {m['recall']:.4f} | {m['f1']:.4f} | {m['flagged_share']:.4f} |")
    out += [
        "",
        "Priority is a proxy label (SPEC B5); rules 2 and 3 are company outcomes the narrative"
        " cannot fully reveal, so low precision at high recall is expected.",
        "",
        "## Values written to configs/thresholds.yaml",
        "",
        "| key | value |",
        "|---|---|",
        *(f"| {k} | {v:.6f} |" if isinstance(v, float) else f"| {k} | {v} |"
          for k, v in values.items()),
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out))


def main(argv: Sequence[str] | None = None) -> None:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m complaintiq.models.calibrate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fit on val-A, report on val-B, update thresholds.yaml")
    r.add_argument("--no-write-config", action="store_true")
    args = ap.parse_args(argv)
    res = run(write_config=not args.no_write_config)
    print(json.dumps({"run_ids": res["run_ids"], "tau": res["product"]["tau"]}, indent=2))


if __name__ == "__main__":
    main()
