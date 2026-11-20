"""Classification metrics for model development (SPEC C5, C6).

**Macro-F1 definition.** ``macro_f1`` averages per-class F1 over a fixed label set: the
classes with support in ``y_true`` (for M3, the classes present in val). A class that is
predicted but has no true rows (e.g. product OTHER, absent from val) does not enter it.
``macro_f1_all_labels`` is the older definition (true and predicted labels) and is
reported separately. All functions take plain label arrays and never see complaint text.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import polars as pl
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_recall_fscore_support,
)


def compute_metrics(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    labels: Sequence[str],
    y_score: np.ndarray | None = None,
) -> dict[str, Any]:
    """Core multi-class metrics.

    Args:
        y_true, y_pred: label strings.
        labels: class order; columns of ``y_score`` and rows/cols of the confusion matrix.
        y_score: optional ``(n, len(labels))`` score matrix; enables top-3 accuracy.

    Returns:
        dict with ``macro_f1``, ``weighted_f1``, ``accuracy``, ``top3`` (or ``None``),
        ``per_class`` (polars DataFrame: label, support, precision, recall, f1) and
        ``confusion`` (``len(labels)`` x ``len(labels)`` int array, rows = true).
        ``macro_f1`` is macro over the classes with support in ``y_true``;
        ``macro_f1_all_labels`` is macro over true and predicted labels.
    """
    labels = list(labels)
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    supported = support_labels(yt)
    union = sorted(set(yt.tolist()) | set(yp.tolist()))
    p, r, f, s = precision_recall_fscore_support(
        yt, yp, labels=labels, zero_division=0.0
    )
    per_class = pl.DataFrame(
        {"label": labels, "support": s.astype(int), "precision": p, "recall": r, "f1": f}
    )
    top3 = None
    if y_score is not None:
        top3 = top_k_accuracy(yt, np.asarray(y_score), labels, k=3)
    return {
        "macro_f1": float(
            f1_score(yt, yp, labels=supported, average="macro", zero_division=0.0)
        ),
        "macro_f1_all_labels": float(
            f1_score(yt, yp, labels=union, average="macro", zero_division=0.0)
        ),
        "weighted_f1": float(
            f1_score(yt, yp, labels=labels, average="weighted", zero_division=0.0)
        ),
        "accuracy": float(accuracy_score(yt, yp)),
        "top3": top3,
        "per_class": per_class,
        "confusion": confusion_matrix(yt, yp, labels=labels),
    }


def support_labels(y_true: Sequence[str] | np.ndarray) -> list[str]:
    """The fixed macro-F1 label set: sorted classes with at least one true row."""
    return sorted(set(np.asarray(y_true).tolist()))


def top_k_accuracy(
    y_true: np.ndarray, y_score: np.ndarray, labels: Sequence[str], k: int = 3
) -> float:
    """Share of rows whose true label is among the ``k`` highest-scoring labels."""
    index = {lbl: i for i, lbl in enumerate(labels)}
    idx = np.array([index.get(y, -1) for y in y_true])
    k = min(k, y_score.shape[1])
    topk = np.argpartition(-y_score, kth=k - 1, axis=1)[:, :k]
    return float((topk == idx[:, None]).any(axis=1).mean())


def _macro_f1_from_codes(t: np.ndarray, p: np.ndarray, k: int, fixed: np.ndarray) -> float:
    """Macro-F1 over the class codes in ``fixed`` (F1 = 0 when a class has no rows)."""
    cm = np.bincount(t * k + p, minlength=k * k).reshape(k, k)
    tp = np.diag(cm).astype(float)
    denom = (cm.sum(axis=1) + cm.sum(axis=0)).astype(float)
    f1 = np.divide(2 * tp, denom, out=np.zeros_like(tp), where=denom > 0)
    return float(f1[fixed].mean())


def bootstrap_macro_f1_ci(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    n_boot: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Percentile bootstrap CI for macro-F1 (rows resampled with replacement).

    The label set is fixed once from the full ``y_true`` (classes with support) and kept
    for every resample. Returns ``{"macro_f1", "lo", "hi", "n_boot"}``.
    """
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    classes, codes = np.unique(np.concatenate([yt, yp]), return_inverse=True)
    t, p = codes[: len(yt)], codes[len(yt):]
    k = len(classes)
    fixed = np.unique(t)
    rng = np.random.default_rng(seed)
    n = len(t)
    stats = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        stats[b] = _macro_f1_from_codes(t[idx], p[idx], k, fixed)
    return {
        "macro_f1": _macro_f1_from_codes(t, p, k, fixed),
        "lo": float(np.quantile(stats, alpha / 2)),
        "hi": float(np.quantile(stats, 1 - alpha / 2)),
        "n_boot": float(n_boot),
    }


def slice_metrics(
    df: pl.DataFrame, y_true_col: str, y_pred_col: str, slice_col: str
) -> pl.DataFrame:
    """Per-slice n, accuracy, macro-F1 and weighted-F1, sorted by slice value.

    Macro-F1 uses the classes with support in that slice (same rule as ``compute_metrics``).
    """
    rows = []
    for (value,), part in df.group_by([slice_col]):
        yt, yp = part[y_true_col].to_numpy(), part[y_pred_col].to_numpy()
        present = support_labels(yt)
        rows.append(
            {
                slice_col: str(value),
                "n": part.height,
                "accuracy": float(accuracy_score(yt, yp)),
                "macro_f1": float(
                    f1_score(yt, yp, labels=present, average="macro", zero_division=0.0)
                ),
                "weighted_f1": float(f1_score(yt, yp, average="weighted", zero_division=0.0)),
            }
        )
    return pl.DataFrame(rows).sort(slice_col)


def priority_metrics(
    y_true: Sequence[int] | np.ndarray,
    y_score: Sequence[float] | np.ndarray,
    threshold: float | None = None,
) -> dict[str, float]:
    """Binary metrics for the HIGH flag (``y_true`` 1 = HIGH).

    If ``threshold`` is ``None`` it is chosen as the score that maximizes F1 on the
    given data (call this on validation only). Returns ``pr_auc`` (average precision),
    ``threshold``, ``precision``, ``recall``, ``f1``, ``base_rate``.
    """
    yt = np.asarray(y_true).astype(int)
    ys = np.asarray(y_score, dtype=float)
    if threshold is None:
        prec, rec, thr = precision_recall_curve(yt, ys)
        f1 = np.divide(2 * prec * rec, prec + rec, out=np.zeros_like(prec), where=(prec + rec) > 0)
        best = int(np.argmax(f1[:-1])) if len(thr) else 0
        threshold = float(thr[best]) if len(thr) else 0.5
    pred = ys >= threshold
    tp = int((pred & (yt == 1)).sum())
    precision = tp / pred.sum() if pred.sum() else 0.0
    recall = tp / (yt == 1).sum() if (yt == 1).sum() else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "pr_auc": float(average_precision_score(yt, ys)) if yt.any() else float("nan"),
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "base_rate": float(yt.mean()),
    }


def recall_at(y_true: np.ndarray, y_score: np.ndarray, threshold: float) -> float:
    """Recall of the positive class at a fixed threshold (NaN if no positives)."""
    yt = np.asarray(y_true).astype(bool)
    if not yt.any():
        return float("nan")
    return float((np.asarray(y_score)[yt] >= threshold).mean())
