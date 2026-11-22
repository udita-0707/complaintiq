"""Drift monitoring (SPEC C9; M5): pure functions plus a replay CLI.

Signals, each per period:

- predicted product / issue distribution vs the **training label** distribution: PSI and
  KL (C9 "Predicted class distribution", alert PSI > 0.2), and PSI vs the first replayed
  period (change inside "production", reported only);
- calibrated product confidence: mean and quantiles, and the relative drop of the mean vs the
  reference period (C9 "Confidence distribution", alert drop > 10%); the auto-route share
  (calibrated confidence >= tau) is reported alongside;
- input drift: narrative length distribution (PSI vs train) and the out-of-vocabulary rate
  of unigram tokens against the frozen vectorizer (C9 "Input drift").

The CLI replays the **val** split calendar month by calendar month as stand-in production
traffic, with **train** as the reference, and writes ``reports/m5/drift_report.md``. The test
split is never read. Only aggregates are printed or written; no complaint text.

CLI::

    python -m complaintiq.monitoring.drift replay      # make drift
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import numpy as np

from complaintiq.config import load_config, resolve_path

logger = logging.getLogger("complaintiq.monitoring.drift")

LABEL_COLS = {"product": "product_class", "issue": "issue_class"}

# --------------------------------------------------------------------------- pure functions


def distribution(labels: Iterable[str]) -> dict[str, float]:
    """Share of each label (sums to 1); empty input gives an empty dict."""
    counts = Counter(str(x) for x in labels)
    n = sum(counts.values())
    return {k: v / n for k, v in sorted(counts.items())} if n else {}


def _aligned(ref: dict[str, float], cur: dict[str, float], eps: float) -> tuple[np.ndarray, ...]:
    keys = sorted(set(ref) | set(cur))
    r = np.array([max(ref.get(k, 0.0), eps) for k in keys])
    c = np.array([max(cur.get(k, 0.0), eps) for k in keys])
    return r, c


def psi(ref: dict[str, float], cur: dict[str, float], eps: float = 1e-4) -> float:
    """Population stability index ``sum((cur - ref) * ln(cur / ref))``; empty bins get ``eps``."""
    if not ref or not cur:
        return math.nan
    r, c = _aligned(ref, cur, eps)
    return float(np.sum((c - r) * np.log(c / r)))


def kl(cur: dict[str, float], ref: dict[str, float], eps: float = 1e-4) -> float:
    """KL divergence ``KL(cur || ref)`` in nats; empty bins get ``eps``."""
    if not ref or not cur:
        return math.nan
    r, c = _aligned(ref, cur, eps)
    return float(np.sum(c * np.log(c / r)))


def confidence_stats(conf: Sequence[float] | np.ndarray,
                     quantiles: Sequence[float] = (0.1, 0.5, 0.9)) -> dict[str, float]:
    """Mean and quantiles of a confidence vector (``q10``, ``q50`` ... keys)."""
    a = np.asarray(conf, dtype=float)
    if a.size == 0:
        return {"mean": math.nan, **{f"q{round(q * 100)}": math.nan for q in quantiles}}
    return {"mean": float(a.mean()),
            **{f"q{round(q * 100)}": float(np.quantile(a, q)) for q in quantiles}}


def relative_drop(reference: float, current: float) -> float:
    """``(reference - current) / reference``; positive = the current value is lower."""
    if not reference or math.isnan(reference) or math.isnan(current):
        return math.nan
    return (reference - current) / reference


def bucket_label(n_words: int, edges: Sequence[int]) -> str:
    """Word-count bucket with the M2-M4 labels (``<100``, ``100-199`` ..., ``>=400``)."""
    if n_words < edges[0]:
        return f"<{edges[0]}"
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        if n_words < hi:
            return f"{lo}-{hi - 1}"
    return f">={edges[-1]}"


def length_distribution(n_words: Iterable[int], edges: Sequence[int]) -> dict[str, float]:
    """Share of rows per word-count bucket."""
    return distribution(bucket_label(int(n), edges) for n in n_words)


def unigram_vocabulary(vectorizer: Any) -> frozenset[str]:
    """Unigram features kept by a fitted scikit-learn text vectorizer."""
    return frozenset(t for t in vectorizer.vocabulary_ if " " not in t)


def oov_rate(texts: Iterable[str], analyzer: Callable[[str], list[str]],
             vocabulary: frozenset[str]) -> float:
    """Share of unigram tokens (as the vectorizer tokenizes them) outside ``vocabulary``."""
    total = missing = 0
    for text in texts:
        for tok in analyzer(text):
            if " " in tok:  # bigrams from an ngram_range (1, 2) analyzer
                continue
            total += 1
            missing += tok not in vocabulary
    return missing / total if total else math.nan


def top_shifts(ref: dict[str, float], cur: dict[str, float], k: int = 3) -> list[dict[str, Any]]:
    """The ``k`` labels whose share changed most (absolute), largest first."""
    keys = set(ref) | set(cur)
    rows = [{"label": lbl, "reference": ref.get(lbl, 0.0), "current": cur.get(lbl, 0.0),
             "change": cur.get(lbl, 0.0) - ref.get(lbl, 0.0)} for lbl in keys]
    return sorted(rows, key=lambda r: (-abs(r["change"]), r["label"]))[:k]


def period_flags(stats: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """Alert names for one period (none for periods below ``min_rows_per_period``)."""
    if stats["n"] < int(cfg["min_rows_per_period"]):
        return []
    th = cfg["thresholds"]
    flags = []
    for task in cfg["tasks"]:
        v = stats[task]["psi_vs_train"]
        if not math.isnan(v) and v > float(th["psi_alert"]):
            flags.append(f"{task} PSI")
    drop = stats["confidence"]["drop_vs_reference"]
    if not math.isnan(drop) and drop > float(th["confidence_drop_alert"]):
        flags.append("confidence drop")
    lp = stats["length"]["psi_vs_train"]
    if not math.isnan(lp) and lp > float(th["length_psi_alert"]):
        flags.append("length PSI")
    return flags


# --------------------------------------------------------------------------- replay


def _calibrated(prob: np.ndarray, temperature: float) -> np.ndarray:
    if temperature == 1.0:
        return prob
    from complaintiq.models.calibrate import apply_temperature

    return apply_temperature(prob, temperature)


def replay_frames(train: Any, val: Any, model: Any, thresholds: dict[str, Any],
                  cfg: dict[str, Any]) -> dict[str, Any]:
    """Replay ``val`` period by period against the ``train`` reference.

    ``train`` needs ``product_class``, ``issue_class``, ``n_words``, ``narrative``; ``val``
    needs ``date_received``, ``n_words``, ``narrative``. ``model`` is a loaded
    ``BaselineModel``. Returns JSON-ready results (aggregates only).
    """
    import polars as pl

    from complaintiq.models.baseline import transform_chunked

    eps = float(cfg["psi_epsilon"])
    edges = list(cfg["length_bucket_edges"])
    seed = int(cfg["seed"])
    n_oov = int(cfg["oov_sample_rows"])
    tau = float(thresholds["tau"])
    vec = model.vectorizer
    analyzer = vec.build_analyzer()
    vocab = unigram_vocabulary(vec)

    ref = {
        "n": train.height,
        **{task: distribution(train[LABEL_COLS[task]].to_list()) for task in cfg["tasks"]},
        "length": length_distribution(train["n_words"].to_list(), edges),
        "oov_rate": oov_rate(
            train.sample(n=min(n_oov, train.height), seed=seed)["narrative"].to_list(),
            analyzer, vocab),
    }

    val = val.with_columns(period=pl.col("date_received").dt.strftime("%Y-%m")).sort(
        "date_received")
    X = transform_chunked(vec, val["narrative"], int(cfg["vectorize_chunk_rows"]))
    probs: dict[str, tuple[list[str], np.ndarray]] = {}
    for task in cfg["tasks"]:
        labels, p = model.scores(task, X)
        probs[task] = (labels, _calibrated(p, float(thresholds.get(f"temperature_{task}", 1.0))))
    periods_col = np.asarray(val["period"].to_list())
    n_words_col = np.asarray(val["n_words"].to_list())

    periods: list[dict[str, Any]] = []
    ref_pred: dict[str, dict[str, float]] = {}
    ref_conf: float | None = None
    for period in sorted(set(periods_col.tolist())):
        idx = np.flatnonzero(periods_col == period)
        stats: dict[str, Any] = {"period": period, "n": int(idx.size)}
        big_enough = idx.size >= int(cfg["min_rows_per_period"])
        for task in cfg["tasks"]:
            labels, p = probs[task]
            pred = [labels[j] for j in p[idx].argmax(axis=1)]
            dist = distribution(pred)
            if task not in ref_pred and big_enough:
                ref_pred[task] = dist  # the first full period is the reference
            stats[task] = {
                "psi_vs_train": psi(ref[task], dist, eps),
                "kl_vs_train": kl(dist, ref[task], eps),
                "psi_vs_reference_period": (psi(ref_pred[task], dist, eps)
                                            if task in ref_pred else math.nan),
                "top_shifts_vs_train": top_shifts(ref[task], dist),
            }
        conf = probs["product"][1][idx].max(axis=1)
        cstats = confidence_stats(conf, cfg["confidence_quantiles"])
        if ref_conf is None and big_enough:
            ref_conf = cstats["mean"]
        cstats["drop_vs_reference"] = (relative_drop(ref_conf, cstats["mean"])
                                       if ref_conf is not None else math.nan)
        cstats["auto_share"] = float(np.mean(conf >= tau)) if idx.size else math.nan
        stats["confidence"] = cstats
        lens = n_words_col[idx]
        sample = idx if idx.size <= n_oov else np.random.default_rng(seed).choice(
            idx, size=n_oov, replace=False)
        stats["length"] = {
            "mean_words": float(lens.mean()) if lens.size else math.nan,
            "psi_vs_train": psi(ref["length"], length_distribution(lens.tolist(), edges), eps),
        }
        stats["oov_rate"] = oov_rate((val["narrative"][int(i)] for i in sample), analyzer, vocab)
        stats["flags"] = period_flags(stats, cfg)
        periods.append(stats)

    return {
        "reference": {"split": "train", "n": ref["n"], "oov_rate": ref["oov_rate"],
                      "length": ref["length"],
                      **{f"{t}_classes": len(ref[t]) for t in cfg["tasks"]}},
        "confidence_reference_period": next(
            (p["period"] for p in periods if p["n"] >= int(cfg["min_rows_per_period"])), None),
        "tau": tau,
        "periods": periods,
        "flagged_periods": [p["period"] for p in periods if p["flags"]],
        "thresholds": cfg["thresholds"],
    }


# --------------------------------------------------------------------------- report


def _f(v: Any, digits: int = 3) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def render_report(res: dict[str, Any], meta: dict[str, Any]) -> str:
    """Markdown drift report from :func:`replay_frames` results."""
    th = res["thresholds"]
    ref = res["reference"]
    lines = [
        "# M5 drift report (train reference, val replayed by month)",
        "",
        "Generated by `python -m complaintiq.monitoring.drift replay` (`make drift`). The test "
        "split was not read. Aggregates only; no complaint text.",
        "",
        f"- Model `{meta['model_id']}` (model_version `{meta['model_version']}`, data_version "
        f"`{meta['data_version']}` as recorded in configs/final_model.yaml); calibrated with "
        f"configs/thresholds.yaml (tau {res['tau']:.4f}).",
        f"- Reference: train, {ref['n']:,} rows, label distributions of product_class and "
        "issue_class, length buckets, and the OOV rate of a seeded sample. Each val calendar "
        "month is one period.",
        f"- Alerts (SPEC C9): predicted-class PSI vs train > {th['psi_alert']}, mean calibrated "
        f"product confidence drop > {th['confidence_drop_alert']:.0%} vs the reference period "
        f"(`{res['confidence_reference_period']}`), length PSI > {th['length_psi_alert']}. "
        "Periods below the minimum row count are listed but never flagged.",
        f"- Run logged in `reports/experiments/m5/drift.csv` (run_id `{meta.get('run_id', '')}`).",
        "",
        "## Per period",
        "",
        "| period | n | product PSI vs train | product KL | product PSI vs ref period | "
        "issue PSI vs train | issue KL | mean conf | conf drop | auto share | mean words | "
        "length PSI | OOV rate | flags |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in res["periods"]:
        lines.append(
            f"| {p['period']} | {p['n']:,} | {_f(p['product']['psi_vs_train'])} | "
            f"{_f(p['product']['kl_vs_train'])} | {_f(p['product']['psi_vs_reference_period'])} | "
            f"{_f(p['issue']['psi_vs_train'])} | {_f(p['issue']['kl_vs_train'])} | "
            f"{_f(p['confidence']['mean'])} | {_f(p['confidence']['drop_vs_reference'])} | "
            f"{_f(p['confidence']['auto_share'])} | {_f(p['length']['mean_words'], 1)} | "
            f"{_f(p['length']['psi_vs_train'])} | {_f(p['oov_rate'], 4)} | "
            f"{', '.join(p['flags']) or '-'} |")
    lines += ["", f"Reference OOV rate (train sample): {_f(ref['oov_rate'], 4)}.", ""]
    if res["periods"]:
        last = res["periods"][-1]
        lines += [f"## Largest predicted-share changes vs train labels ({last['period']})", "",
                  "| task | label | train share | predicted share | change |",
                  "|---|---|---|---|---|"]
        for task in ("product", "issue"):
            for s in last[task]["top_shifts_vs_train"]:
                lines.append(f"| {task} | {s['label']} | {_f(s['reference'])} | "
                             f"{_f(s['current'])} | {s['change']:+.3f} |")
        lines.append("")
    flagged = res["flagged_periods"]
    lines += [
        "## Reading the flags",
        "",
        (f"Flagged periods: {', '.join(flagged)}." if flagged else "No period was flagged."),
        "PSI vs train compares the model's predicted distribution with the training labels, so "
        "it mixes real input change with the model's own bias and with the label shift between "
        "train and val already measured in M2 (reports/m2_data_stats.md). PSI vs the reference "
        "period isolates change inside the replayed traffic. The response playbook for each "
        "alert is in docs/monitoring_plan.md.",
        "",
    ]
    return "\n".join(lines)


def _json_ready(obj: Any) -> Any:
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_ready(v) for v in obj]
    return obj


def run(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load the frozen model, train and val; replay; write the report, JSON and run log."""
    from complaintiq.data.training_data import load_split
    from complaintiq.eval.tracking import log_run
    from complaintiq.models.baseline import BaselineModel

    c = cfg if cfg is not None else load_config("monitoring")
    final = load_config("final_model")
    thresholds = load_config("thresholds")
    if not final.get("frozen_date"):
        raise SystemExit("configs/final_model.yaml is not frozen; drift needs the frozen model")
    model_dir = resolve_path(c["model_dir"])
    model = BaselineModel.load(model_dir)
    train = load_split("train", columns=["product_class", "issue_class", "n_words", "narrative"])
    val = load_split("val", columns=["date_received", "n_words", "narrative"])
    res = replay_frames(train, val, model, thresholds, c)
    meta = {"model_id": final["model_id"], "model_version": model.meta.get("model_version"),
            "data_version": final["data_version"]}
    flagged = res["flagged_periods"]
    meta["run_id"] = log_run(
        c["experiment_log"], experiments_dir=resolve_path(c["experiments_dir"]),
        data_version=final["data_version"], model=final["model_id"], task="drift_replay",
        hyperparams={k: c[k] for k in ("period", "min_rows_per_period", "thresholds",
                                       "oov_sample_rows", "psi_epsilon")},
        seed=c["seed"], n_train=res["reference"]["n"], owner=c["owner"],
        notes=f"drift replay; periods={len(res['periods'])}; "
              f"flagged={';'.join(flagged) if flagged else 'none'}",
    )
    out = resolve_path(c["results_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_json_ready({**meta, **res}), indent=2, sort_keys=True) + "\n")
    rep = resolve_path(c["report_path"])
    rep.write_text(render_report(res, meta))
    logger.info("drift replay: %d periods, flagged %s", len(res["periods"]), flagged or "none")
    return res


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Drift replay (SPEC C9)")
    ap.add_argument("cmd", choices=["replay"])
    ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = run()
    print(f"periods={len(res['periods'])} flagged={res['flagged_periods'] or 'none'}")


if __name__ == "__main__":
    main()
