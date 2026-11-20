"""Tests for complaintiq.eval.metrics and complaintiq.eval.tracking (synthetic labels)."""

import csv
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from sklearn.metrics import f1_score

from complaintiq.eval import metrics, tracking

LABELS = ["a", "b", "c"]
Y_TRUE = ["a", "a", "b", "b", "c", "c", "a", "b"]
Y_PRED = ["a", "b", "b", "b", "c", "a", "a", "c"]


def test_compute_metrics_matches_sklearn() -> None:
    m = metrics.compute_metrics(Y_TRUE, Y_PRED, LABELS)
    assert m["macro_f1"] == pytest.approx(f1_score(Y_TRUE, Y_PRED, average="macro"))
    assert m["accuracy"] == pytest.approx(5 / 8)
    assert m["top3"] is None
    assert m["confusion"].sum() == len(Y_TRUE)
    assert m["per_class"]["support"].to_list() == [3, 3, 2]


def test_macro_f1_fixed_label_set() -> None:
    # "c" is predicted but has no true rows: it is excluded from macro_f1 only.
    yt = ["a", "a", "b", "b"]
    yp = ["a", "c", "b", "b"]
    m = metrics.compute_metrics(yt, yp, LABELS)
    assert m["macro_f1"] == pytest.approx(f1_score(yt, yp, labels=["a", "b"], average="macro"))
    assert m["macro_f1_all_labels"] == pytest.approx(f1_score(yt, yp, average="macro"))
    assert m["macro_f1"] > m["macro_f1_all_labels"]
    ci = metrics.bootstrap_macro_f1_ci(yt, yp, n_boot=50, seed=0)
    assert ci["macro_f1"] == pytest.approx(m["macro_f1"])


def test_top3_with_scores() -> None:
    scores = np.array([[0.1, 0.2, 0.7], [0.5, 0.3, 0.2]])
    m = metrics.compute_metrics(["a", "c"], ["c", "a"], LABELS, y_score=scores)
    assert m["top3"] == 1.0
    assert metrics.top_k_accuracy(np.array(["a", "c"]), scores, LABELS, k=1) == 0.0


def test_bootstrap_ci_brackets_point() -> None:
    rng = np.random.default_rng(0)
    yt = rng.choice(LABELS, 500)
    yp = np.where(rng.random(500) < 0.7, yt, rng.choice(LABELS, 500))
    ci = metrics.bootstrap_macro_f1_ci(yt, yp, n_boot=200, seed=1)
    assert ci["lo"] <= ci["macro_f1"] <= ci["hi"]
    assert ci["macro_f1"] == pytest.approx(f1_score(yt, yp, average="macro"))
    assert metrics.bootstrap_macro_f1_ci(yt, yp, n_boot=200, seed=1) == ci


def test_slice_metrics() -> None:
    df = pl.DataFrame({"t": Y_TRUE, "p": Y_PRED, "s": ["x"] * 4 + ["y"] * 4})
    out = metrics.slice_metrics(df, "t", "p", "s")
    assert out["s"].to_list() == ["x", "y"]
    assert out["n"].sum() == len(Y_TRUE)
    assert out.filter(pl.col("s") == "x")["accuracy"][0] == pytest.approx(0.75)


def test_priority_metrics_threshold() -> None:
    yt = np.array([0, 0, 1, 1, 0, 1])
    ys = np.array([0.1, 0.4, 0.35, 0.8, 0.2, 0.9])
    chosen = metrics.priority_metrics(yt, ys)
    assert 0 < chosen["pr_auc"] <= 1
    fixed = metrics.priority_metrics(yt, ys, threshold=0.5)
    assert fixed["threshold"] == 0.5
    assert fixed["precision"] == 1.0
    assert fixed["recall"] == pytest.approx(2 / 3)
    assert chosen["f1"] >= fixed["f1"]
    assert metrics.recall_at(yt, ys, 0.5) == pytest.approx(2 / 3)


def test_log_run_appends_rows(tmp_path: Path) -> None:
    rid = tracking.log_run(
        "unit", experiments_dir=tmp_path, model="m", task="t", hyperparams={"a": 1},
        seed=42, val_macro_f1=0.5, owner="team-m3-session",
    )
    tracking.log_run("unit", experiments_dir=tmp_path, model="m2", task="t")
    with (tmp_path / "unit.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert [r["model"] for r in rows] == ["m", "m2"]
    assert rows[0]["run_id"] == rid
    assert rows[0]["hyperparams_json"] == '{"a": 1}'
    assert rows[1]["val_macro_f1"] == ""
    assert list(rows[0]) == list(tracking.COLUMNS)
    assert len(tracking.read_runs(tmp_path)) == 2
    with pytest.raises(ValueError):
        tracking.log_run("unit", experiments_dir=tmp_path, bogus=1)


def test_log_run_migrates_old_header(tmp_path: Path) -> None:
    old_cols = [c for c in tracking.COLUMNS if c != "val_macro_f1_all_labels"]
    with (tmp_path / "old.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old_cols)
        w.writeheader()
        w.writerow({c: "" for c in old_cols} | {"run_id": "r0", "val_macro_f1": "0.700000"})
    tracking.log_run("old", experiments_dir=tmp_path, model="m", val_macro_f1_all_labels=0.5)
    with (tmp_path / "old.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == list(tracking.COLUMNS)
    assert rows[0]["run_id"] == "r0" and rows[0]["val_macro_f1"] == "0.700000"
    assert rows[0]["val_macro_f1_all_labels"] == ""
    assert rows[1]["val_macro_f1_all_labels"] == "0.500000"
