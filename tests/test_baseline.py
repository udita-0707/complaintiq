"""Tests for complaintiq.models.baseline (synthetic text only; no data files)."""

from pathlib import Path

import numpy as np
import pytest

from complaintiq.models import baseline
from complaintiq.serving.predictor import Predictor

TEXTS = {
    ("Debt collection", "Attempts to collect debt not owed", "HIGH"): (
        "collector keeps calling about a debt i do not owe and threatens to sue"
    ),
    ("Mortgage", "Struggling to pay mortgage", "NORMAL"): (
        "mortgage servicer refused my loan modification and payment plan request"
    ),
    ("Credit reporting or credit repair", "Incorrect information on your report", "NORMAL"): (
        "credit report shows an account that is not mine and the bureau ignores disputes"
    ),
}


def synthetic(n_per: int = 20) -> tuple[list[str], dict[str, list[str]]]:
    texts: list[str] = []
    labels: dict[str, list[str]] = {"product": [], "issue": [], "priority": []}
    for (prod, issue, prio), text in TEXTS.items():
        for i in range(n_per):
            texts.append(f"{text} case {i}")
            labels["product"].append(prod)
            labels["issue"].append(issue)
            labels["priority"].append(prio)
    return texts, labels


@pytest.fixture(scope="module")
def params() -> dict:
    cfg = baseline.load_baseline_config()
    p = baseline.variant_params(cfg, cfg["default_variant"])
    p["features"]["min_df"] = 1
    p["features"]["max_df"] = 1.0
    return p


def test_variant_params_merge() -> None:
    cfg = baseline.load_baseline_config()
    base = baseline.variant_params(cfg, "tfidf_sgd")
    assert base["class_weight"] == "balanced"
    assert base["ngram_range"] == [1, 2]
    assert baseline.variant_params(cfg, "tfidf_sgd_unweighted")["class_weight"] is None
    mh = baseline.variant_params(cfg, "tfidf_sgd_modhuber")
    assert mh["classifier"]["loss"] == "modified_huber"
    assert mh["classifier"]["alpha"] == base["classifier"]["alpha"]
    assert baseline.feature_key(mh) == baseline.feature_key(base)
    with pytest.raises(ValueError):
        baseline.variant_params(cfg, "nope")


def test_fit_save_load_predict(tmp_path: Path, params: dict) -> None:
    texts, labels = synthetic()
    model = baseline.fit_model(texts, labels, params)
    model.save(tmp_path)
    pred = baseline.BaselinePredictor(tmp_path)
    assert isinstance(pred, Predictor)
    out = pred.predict("the debt collector threatens to sue me over a debt i do not owe")
    assert out.product == "Debt collection"
    assert out.issue_top3[0][0] == "Attempts to collect debt not owed"
    assert len(out.issue_top3) == 3
    assert 0.0 <= out.product_confidence <= 1.0
    assert out.priority in {"HIGH", "NORMAL"}


def test_task_metrics_keys(params: dict) -> None:
    texts, labels = synthetic()
    model = baseline.fit_model(texts, labels, params)
    X = model.vectorizer.transform(texts)
    for task, keys in [("issue", {"val_top3"}), ("priority", {"val_pr_auc"})]:
        lbls, prob = model.scores(task, X)
        m = baseline.task_metrics(task, np.asarray(labels[task]), lbls, prob)
        assert keys <= set(m)
        assert m["val_macro_f1"] > 0.9


def test_complement_nb_variant(params: dict) -> None:
    cfg = baseline.load_baseline_config()
    cnb = baseline.variant_params(cfg, "tfidf_cnb")
    assert cnb["classifier"] == {"type": "complement_nb", "alpha": 1.0, "norm": False}
    assert cnb["tasks"] == ["product", "issue"]
    texts, labels = synthetic()
    p = {**params, "classifier": cnb["classifier"]}
    model = baseline.fit_model(texts, {"issue": labels["issue"]}, p)
    X = model.vectorizer.transform(texts)
    lbls, prob = model.scores("issue", X)
    assert baseline.task_metrics("issue", np.asarray(labels["issue"]), lbls, prob)[
        "val_macro_f1"
    ] > 0.9


def test_fit_with_convergence_flags(params: dict) -> None:
    texts, labels = synthetic()
    X = baseline.build_vectorizer(params).fit_transform(texts)
    y = np.asarray(labels["issue"])
    capped = {**params, "classifier": {**params["classifier"], "max_iter": 1, "tol": 1e-12}}
    out = baseline.fit_with_convergence(baseline.build_classifier(capped, 0), X, y)
    assert out == {"n_iter": 1, "converged": False}
    loose = {**params, "classifier": {**params["classifier"], "max_iter": 200, "tol": 1e-1}}
    out = baseline.fit_with_convergence(baseline.build_classifier(loose, 0), X, y)
    assert out["converged"] is True and out["n_iter"] < 200
    cnb = {**params, "classifier": {"type": "complement_nb", "alpha": 1.0}}
    assert baseline.fit_with_convergence(baseline.build_classifier(cnb, 0), X, y) == {
        "n_iter": None, "converged": None,
    }


def test_predictor_defaults_reproduce_m3_and_calibration_options(
    tmp_path: Path, params: dict
) -> None:
    texts, labels = synthetic()
    model = baseline.fit_model(texts, labels, params)
    model.meta["priority_threshold"] = 0.5
    model.save(tmp_path)
    q = "the debt collector threatens to sue me over a debt i do not owe"
    m3 = baseline.BaselinePredictor(tmp_path)
    same = baseline.BaselinePredictor(
        tmp_path, temperatures={"product": 1.0}, priority_threshold=None
    )
    X = model.vectorizer.transform([q])
    _, p = model.scores("product", X)
    assert m3.predict(q) == same.predict(q)
    assert m3.predict(q).product_confidence == pytest.approx(float(p.max()))
    assert m3.model_version == same.model_version == "baseline-test"
    cal = baseline.BaselinePredictor(
        tmp_path, temperatures={"product": 4.0}, priority_threshold=1.0
    )
    out = cal.predict(q)
    assert out.product == m3.predict(q).product
    assert out.product_confidence < m3.predict(q).product_confidence
    assert out.priority == "NORMAL" and cal.model_version == "baseline-test-cal"
