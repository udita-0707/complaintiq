"""Tests for complaintiq.data.training_data (synthetic frames only)."""

from pathlib import Path

import polars as pl
import pytest

from complaintiq.data import training_data as td


def make_frame() -> pl.DataFrame:
    labels = ["A"] * 900 + ["B"] * 90 + ["C"] * 9 + ["D"]
    return pl.DataFrame({"complaint_id": list(range(len(labels))), "y": labels})


def write_splits(root: Path) -> None:
    d = root / "time"
    d.mkdir(parents=True)
    for i, s in enumerate(("train", "val", "test")):
        pl.DataFrame({"x": [i, i + 1]}).write_parquet(d / f"{s}.parquet")


@pytest.mark.parametrize(
    ("cap", "max_rows"), [(None, 50), (5, None), (20, 30), (None, None), (None, 3)]
)
def test_sampling_keeps_all_classes(cap: int | None, max_rows: int | None) -> None:
    df = make_frame()
    out = td.sample_train(df, "y", cap_per_class=cap, max_rows=max_rows, seed=1)
    assert set(out["y"]) == set(df["y"])
    if cap is not None:
        assert out.group_by("y").len()["len"].max() <= cap
    if max_rows is not None:
        assert out.height <= max_rows + df["y"].n_unique()


def test_sampling_large_counts_no_overflow() -> None:
    df = pl.DataFrame({"y": ["A"] * 200_000 + ["B"] * 1_000})
    out = td.sample_train(df, "y", max_rows=50_000)
    counts = dict(out.group_by("y").len().iter_rows())
    assert counts["A"] == 49_751  # floor(200000 * 50000 / 201000); u32 math would overflow
    assert counts["B"] == 248


def test_sampling_is_seeded() -> None:
    df = make_frame()
    a = td.sample_train(df, "y", max_rows=100, seed=7)["complaint_id"].sort()
    b = td.sample_train(df, "y", max_rows=100, seed=7)["complaint_id"].sort()
    c = td.sample_train(df, "y", max_rows=100, seed=8)["complaint_id"].sort()
    assert a.equals(b)
    assert not a.equals(c)


def test_priors_sum_to_one() -> None:
    priors = td.class_priors(make_frame(), "y")
    assert sum(priors.values()) == pytest.approx(1.0)
    assert priors["A"] == pytest.approx(0.9)


def test_test_split_guard_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_splits(tmp_path)
    monkeypatch.delenv(td.TEST_ENV_VAR, raising=False)
    with pytest.raises(PermissionError):
        td.load_split("test", processed_dir=tmp_path)
    monkeypatch.setenv(td.TEST_ENV_VAR, "0")
    with pytest.raises(PermissionError):
        td.load_split("test", processed_dir=tmp_path)
    with pytest.raises(ValueError):
        td.load_split("holdout", processed_dir=tmp_path)
    assert td.load_split("val", processed_dir=tmp_path).height == 2


def test_data_version_changes_with_file(tmp_path: Path) -> None:
    write_splits(tmp_path)
    v1 = td.data_version(processed_dir=tmp_path)
    assert len(v1) == 12
    assert td.data_version(processed_dir=tmp_path) == v1
    pl.DataFrame({"x": [9, 9, 9]}).write_parquet(tmp_path / "time" / "val.parquet")
    assert td.data_version(processed_dir=tmp_path) != v1


def test_severity_mask() -> None:
    s = pl.Series(["Fraud or scam", "Managing an account", None])
    assert td.severity_mask(s).to_list() == [True, False, False]
