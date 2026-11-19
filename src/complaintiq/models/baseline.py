"""TF-IDF + linear baseline for product, issue and priority (SPEC C5).

Model input is ONLY the ``narrative`` column. Training reads the train split, evaluates
on val and appends one row per (variant, task) to the experiment log. The test split is
never read here.

CLI::

    python -m complaintiq.models.baseline train [--variants a,b] [--max-train N]
    python -m complaintiq.models.baseline eval  [--variant NAME]
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import time
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import polars as pl
import scipy.sparse as sp
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.naive_bayes import ComplementNB

from complaintiq.config import load_config
from complaintiq.data.load import resolve
from complaintiq.data.training_data import (
    LABEL_COLS,
    data_version,
    load_split,
    sample_train,
    severity_mask,
)
from complaintiq.eval import metrics
from complaintiq.eval.tracking import log_run, read_runs
from complaintiq.serving.predictor import Prediction

logger = logging.getLogger("complaintiq.models.baseline")

TEXT_COL = "narrative"
HIGH = "HIGH"
OWNER = "team-m3-session"
METRIC_TAG = "fixed label set"  # every row logged with the current macro-F1 definition


# --------------------------------------------------------------------------- config


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_baseline_config() -> dict[str, Any]:
    """``configs/baseline.yaml`` with ``configs/model.yaml: baseline`` keys merged in."""
    cfg = load_config("baseline")
    base = load_config("model").get("baseline", {})
    cfg["base"] = {
        "ngram_range": list(base.get("ngram_range", [1, 2])),
        "max_features": base.get("max_features"),
        "class_weight": base.get("class_weight"),
    }
    return cfg


def variant_params(cfg: dict[str, Any], variant: str) -> dict[str, Any]:
    """Resolved hyperparameters for one variant (base + features + classifier + overrides)."""
    if variant not in cfg["variants"]:
        raise ValueError(f"unknown variant '{variant}'; known: {sorted(cfg['variants'])}")
    params = {
        **cfg["base"],
        "features": dict(cfg["features"]),
        "classifier": dict(cfg["classifier"]),
    }
    over = copy.deepcopy(cfg["variants"][variant] or {})
    clf_over = over.get("classifier", {})
    if clf_over.get("type", "sgd") != "sgd":
        params["classifier"] = {}  # a different model family: do not inherit SGD keys
    return _deep_merge(params, over)


def feature_key(params: dict[str, Any]) -> str:
    """Variants with equal feature settings share one fitted vectorizer."""
    keys = {k: params[k] for k in ("ngram_range", "max_features")}
    return json.dumps({**keys, **params["features"]}, sort_keys=True)


# --------------------------------------------------------------------------- model


def build_vectorizer(params: dict[str, Any]) -> TfidfVectorizer:
    """Word n-gram TF-IDF from resolved params."""
    f = params["features"]
    return TfidfVectorizer(
        ngram_range=tuple(params["ngram_range"]),
        max_features=params["max_features"],
        sublinear_tf=f["sublinear_tf"],
        min_df=f["min_df"],
        max_df=f["max_df"],
        lowercase=f["lowercase"],
        dtype=np.float32,
    )


def build_classifier(params: dict[str, Any], seed: int) -> SGDClassifier | ComplementNB:
    """Classifier from resolved params: SGD linear model (default) or Complement NB.

    ComplementNB has no class_weight; it is designed for imbalanced text classes.
    """
    c = params["classifier"]
    kind = c.get("type", "sgd")
    if kind == "complement_nb":
        return ComplementNB(alpha=c["alpha"], norm=c.get("norm", False))
    if kind != "sgd":
        raise ValueError(f"unknown classifier type '{kind}'")
    return SGDClassifier(
        loss=c["loss"],
        alpha=c["alpha"],
        max_iter=c["max_iter"],
        tol=c["tol"],
        n_jobs=c.get("n_jobs"),
        class_weight=params["class_weight"],
        random_state=seed,
    )


def transform_chunked(
    vec: TfidfVectorizer, texts: pl.Series, chunk_rows: int
) -> sp.csr_matrix:
    """Transform a text column chunk by chunk to bound peak memory."""
    parts = [
        vec.transform(texts.slice(i, chunk_rows).to_list())
        for i in range(0, len(texts), chunk_rows)
    ]
    return sp.vstack(parts, format="csr")


@dataclass
class BaselineModel:
    """A fitted vectorizer plus one classifier per task."""

    vectorizer: TfidfVectorizer
    classifiers: dict[str, SGDClassifier]
    meta: dict[str, Any] = field(default_factory=dict)

    def scores(self, task: str, X: sp.spmatrix) -> tuple[list[str], np.ndarray]:
        """Class labels and probability matrix for ``task``."""
        clf = self.classifiers[task]
        return [str(c) for c in clf.classes_], clf.predict_proba(X)

    def save(self, model_dir: str | Path) -> None:
        """Write ``vectorizer.joblib``, ``<task>.joblib`` and ``meta.json``."""
        d = Path(model_dir)
        d.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.vectorizer, d / "vectorizer.joblib")
        for task, clf in self.classifiers.items():
            joblib.dump(clf, d / f"{task}.joblib")
        (d / "meta.json").write_text(json.dumps(self.meta, indent=2, sort_keys=True))

    @classmethod
    def load(cls, model_dir: str | Path) -> BaselineModel:
        """Load a model saved with :meth:`save` (only trusted, locally built artifacts)."""
        d = Path(model_dir)
        meta = json.loads((d / "meta.json").read_text())
        clfs = {t: joblib.load(d / f"{t}.joblib") for t in meta["tasks"]}
        return cls(joblib.load(d / "vectorizer.joblib"), clfs, meta)


class BaselinePredictor:
    """Serving ``Predictor`` backed by a saved :class:`BaselineModel`.

    Optional M4 calibration: ``temperatures`` (``{"product": T, "issue": T}``) rescale the
    probabilities with temperature scaling, and ``priority_threshold`` overrides the value
    in ``meta.json``. With the defaults the output is identical to M3.
    """

    def __init__(
        self,
        model_dir: str | Path,
        temperatures: dict[str, float] | None = None,
        priority_threshold: float | None = None,
    ) -> None:
        self.model = BaselineModel.load(model_dir)
        missing = {"product", "issue", "priority"} - set(self.model.classifiers)
        if missing:
            raise ValueError(f"baseline artifact lacks tasks {sorted(missing)}")
        self.temperatures = {k: float(v) for k, v in (temperatures or {}).items()}
        self.priority_threshold = float(
            priority_threshold
            if priority_threshold is not None
            else self.model.meta.get("priority_threshold", 0.5)
        )

    @property
    def calibrated(self) -> bool:
        """True when any temperature differs from 1."""
        return any(t != 1.0 for t in self.temperatures.values())

    @property
    def model_version(self) -> str:
        base = str(self.model.meta.get("model_version", "baseline"))
        return f"{base}-cal" if self.calibrated else base

    def _scores(self, task: str, X: sp.spmatrix) -> tuple[list[str], np.ndarray]:
        labels, prob = self.model.scores(task, X)
        t = self.temperatures.get(task, 1.0)
        if t != 1.0:
            from complaintiq.models.calibrate import apply_temperature

            prob = apply_temperature(prob, t)
        return labels, prob

    def predict(self, text: str) -> Prediction:
        X = self.model.vectorizer.transform([text])
        p_labels, p_prob = self._scores("product", X)
        i_labels, i_prob = self._scores("issue", X)
        r_labels, r_prob = self.model.scores("priority", X)
        top = int(np.argmax(p_prob[0]))
        order = np.argsort(-i_prob[0])[:3]
        high = float(r_prob[0][r_labels.index(HIGH)])
        return Prediction(
            product=p_labels[top],
            product_confidence=float(p_prob[0][top]),
            issue_top3=[(i_labels[j], float(i_prob[0][j])) for j in order],
            priority=HIGH if high >= self.priority_threshold else "NORMAL",
            priority_score=high,
        )


def fit_model(
    texts: Sequence[str],
    labels: dict[str, Sequence[str]],
    params: dict[str, Any],
    seed: int = 42,
) -> BaselineModel:
    """Fit vectorizer and one classifier per task in memory (small data / tests)."""
    vec = build_vectorizer(params)
    X = vec.fit_transform(list(texts))
    clfs = {t: build_classifier(params, seed).fit(X, np.asarray(y)) for t, y in labels.items()}
    return BaselineModel(vec, clfs, {"tasks": list(labels), "model_version": "baseline-test"})


# --------------------------------------------------------------------------- evaluation


def task_metrics(task: str, y_true: np.ndarray, labels: list[str], prob: np.ndarray) -> dict:
    """Logged val metrics for one task (no threshold tuning; argmax predictions)."""
    pred = np.asarray(labels)[prob.argmax(axis=1)]
    m = metrics.compute_metrics(y_true, pred, labels, y_score=prob if task != "priority" else None)
    out = {
        "val_macro_f1": m["macro_f1"],
        "val_macro_f1_all_labels": m["macro_f1_all_labels"],
        "val_weighted_f1": m["weighted_f1"],
    }
    if task == "priority":
        out["val_pr_auc"] = metrics.priority_metrics(
            (y_true == HIGH).astype(int), prob[:, labels.index(HIGH)], threshold=0.5
        )["pr_auc"]
    else:
        out["val_top3"] = m["top3"]
    return out


# --------------------------------------------------------------------------- training


def _model_dir(cfg: dict[str, Any], variant: str, max_train: int | None) -> Path:
    name = variant if max_train is None else f"{variant}-n{max_train}"
    return resolve(cfg["artifacts_dir"]) / name


def fit_with_convergence(
    clf: SGDClassifier | ComplementNB, X: sp.spmatrix, y: np.ndarray
) -> dict[str, Any]:
    """Fit ``clf`` and report ``n_iter`` (max over one-vs-rest fits) and ``converged``.

    ``converged`` is False when sklearn raised a ConvergenceWarning (iteration cap hit
    before the tolerance stop); ``None`` for models that are not iterative.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        clf.fit(X, y)
    if not hasattr(clf, "n_iter_"):
        return {"n_iter": None, "converged": None}
    hit_cap = any(issubclass(w.category, ConvergenceWarning) for w in caught)
    return {"n_iter": int(np.max(clf.n_iter_)), "converged": not hit_cap}


def train(
    variants: Iterable[str],
    tasks: Iterable[str] | None = None,
    max_train: int | None = None,
    notes: str = "",
) -> dict[str, dict[str, str]]:
    """Fit each variant on train, evaluate on val, log every (variant, task) run.

    Returns ``{variant: {task: run_id}}``.
    """
    cfg = load_baseline_config()
    seed = int(cfg["seed"])
    tasks = list(tasks or cfg["tasks"])
    label_cols = [LABEL_COLS[t] for t in tasks]
    dv = data_version()

    train_df = load_split("train", columns=[TEXT_COL, *set(label_cols + [cfg["stratify_col"]])])
    if max_train is not None:
        train_df = sample_train(train_df, cfg["stratify_col"], max_rows=max_train, seed=seed)
    val_df = load_split("val", columns=[TEXT_COL, *label_cols])
    logger.info("train rows=%d val rows=%d data_version=%s", train_df.height, val_df.height, dv)

    by_features: dict[str, list[str]] = {}
    for v in variants:
        by_features.setdefault(feature_key(variant_params(cfg, v)), []).append(v)

    run_ids: dict[str, dict[str, str]] = {}
    for group in by_features.values():
        params0 = variant_params(cfg, group[0])
        f = params0["features"]
        t0 = time.perf_counter()
        vec = build_vectorizer(params0)
        n_vocab = min(f["vocab_fit_rows"], train_df.height)
        vocab_texts = train_df[TEXT_COL].sample(n=n_vocab, seed=seed, shuffle=True).to_list()
        vec.fit(vocab_texts)
        del vocab_texts
        X_train = transform_chunked(vec, train_df[TEXT_COL], f["transform_chunk_rows"])
        X_val = transform_chunked(vec, val_df[TEXT_COL], f["transform_chunk_rows"])
        vec_seconds = time.perf_counter() - t0
        logger.info("vectorized in %.0fs, vocab=%d", vec_seconds, len(vec.vocabulary_))

        for variant in group:
            params = variant_params(cfg, variant)
            clfs: dict[str, SGDClassifier | ComplementNB] = {}
            run_ids[variant] = {}
            v_tasks = [t for t in tasks if t in params.get("tasks", tasks)]
            for task in v_tasks:
                col = LABEL_COLS[task]
                y = train_df[col].to_numpy()
                t1 = time.perf_counter()
                clf = build_classifier(params, seed)
                conv = fit_with_convergence(clf, X_train, y)
                fit_seconds = time.perf_counter() - t1
                clfs[task] = clf
                labels = [str(c) for c in clf.classes_]
                m = task_metrics(task, val_df[col].to_numpy(), labels, clf.predict_proba(X_val))
                hp = {
                    **params,
                    "variant": variant,
                    "max_train": max_train,
                    "stratify_col": cfg["stratify_col"] if max_train else None,
                    "vocab_size": len(vec.vocabulary_),
                    **conv,
                }
                run_ids[variant][task] = log_run(
                    cfg["experiment_log"],
                    data_version=dv,
                    model=f"baseline/{variant}",
                    task=LABEL_COLS[task],
                    hyperparams=hp,
                    seed=seed,
                    n_train=train_df.height,
                    train_seconds=round(fit_seconds, 1),
                    owner=OWNER,
                    notes=(
                        f"{notes} metric: {METRIC_TAG}; vectorize_seconds={vec_seconds:.0f}"
                        " (shared by variants); val metrics at argmax, no threshold tuning"
                    ).strip(),
                    **m,
                )
                logger.info("%s/%s fit %.0fs %s", variant, task, fit_seconds, m)
            model = BaselineModel(
                vec,
                clfs,
                {
                    "variant": variant,
                    "tasks": v_tasks,
                    "data_version": dv,
                    "model_version": f"baseline-{variant}-{dv}",
                    "n_train": train_df.height,
                    "max_train": max_train,
                    "run_ids": run_ids[variant],
                    "priority_threshold": 0.5,
                    "hyperparams": params,
                },
            )
            model.save(_model_dir(cfg, variant, max_train))
        del X_train, X_val
    return run_ids


def add_tasks(
    model_name: str,
    tasks: Iterable[str],
    experiments_dir: str | Path,
    log_name: str = "training",
    owner: str = OWNER,
    notes: str = "",
) -> dict[str, str]:
    """Fit missing tasks into a saved variant with its OWN saved vectorizer (M4).

    Used when a variant was trained for a subset of tasks (e.g. the converged reruns
    were product and issue only). Classifier settings come from ``meta.json``;
    ``data_version`` is the one recorded in ``meta.json`` (``data_version()`` would hash
    the test split file). Logs one row per task and updates ``meta.json``.
    """
    cfg = load_baseline_config()
    seed = int(cfg["seed"])
    d = resolve(cfg["artifacts_dir"]) / model_name
    model = BaselineModel.load(d)
    meta = model.meta
    if meta.get("max_train"):
        raise ValueError("add_tasks supports full-train variants only")
    tasks = [t for t in tasks if t not in model.classifiers]
    if not tasks:
        return {}
    params = meta["hyperparams"]
    label_cols = [LABEL_COLS[t] for t in tasks]
    chunk = params["features"]["transform_chunk_rows"]
    train_df = load_split("train", columns=[TEXT_COL, *label_cols])
    if train_df.height != meta["n_train"]:
        raise ValueError(f"train has {train_df.height} rows, model meta says {meta['n_train']}")
    val_df = load_split("val", columns=[TEXT_COL, *label_cols])
    t0 = time.perf_counter()
    X_train = transform_chunked(model.vectorizer, train_df[TEXT_COL], chunk)
    X_val = transform_chunked(model.vectorizer, val_df[TEXT_COL], chunk)
    vec_seconds = time.perf_counter() - t0
    out: dict[str, str] = {}
    for task in tasks:
        col = LABEL_COLS[task]
        t1 = time.perf_counter()
        clf = build_classifier(params, seed)
        conv = fit_with_convergence(clf, X_train, train_df[col].to_numpy())
        fit_seconds = time.perf_counter() - t1
        labels = [str(c) for c in clf.classes_]
        m = task_metrics(task, val_df[col].to_numpy(), labels, clf.predict_proba(X_val))
        out[task] = log_run(
            log_name,
            experiments_dir,
            data_version=meta["data_version"],
            model=f"baseline/{meta['variant']}",
            task=col,
            hyperparams={**params, "variant": meta["variant"], "max_train": None,
                         "vocab_size": len(model.vectorizer.vocabulary_), "added_task": True,
                         **conv},
            seed=seed,
            n_train=train_df.height,
            train_seconds=round(fit_seconds, 1),
            owner=owner,
            notes=(
                f"{notes} added task to saved variant with its saved vectorizer;"
                f" metric: {METRIC_TAG}; transform_seconds={vec_seconds:.0f};"
                " val metrics at argmax, no threshold tuning"
            ).strip(),
            **m,
        )
        model.classifiers[task] = clf
        joblib.dump(clf, d / f"{task}.joblib")
        logger.info("%s/%s fit %.0fs %s %s", model_name, task, fit_seconds, conv, m)
    meta["tasks"] = [*meta["tasks"], *tasks]
    meta.setdefault("run_ids", {}).update(out)
    meta["added_task_run_ids"] = {**meta.get("added_task_run_ids", {}), **out}
    (d / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    return out


# --------------------------------------------------------------------------- rescoring


def rescore(model_names: Iterable[str]) -> dict[str, dict[str, str]]:
    """Re-score saved models on val with the current metric definition (no retraining).

    Logs one row per (model, task) tagged ``rescored: fixed label set`` that names the
    superseded training run, and records the new run_ids in the model's ``meta.json``.
    """
    cfg = load_baseline_config()
    seed = int(cfg["seed"])
    dv = data_version()
    val = load_split("val", columns=[TEXT_COL, *LABEL_COLS.values()])
    logged = {r["run_id"]: r for r in read_runs()}
    out: dict[str, dict[str, str]] = {}
    for name in model_names:
        d = resolve(cfg["artifacts_dir"]) / name
        model = BaselineModel.load(d)
        meta = model.meta
        if meta["data_version"] != dv:
            raise ValueError(f"{name} was trained on data_version {meta['data_version']}, not {dv}")
        chunk = cfg["features"]["transform_chunk_rows"]
        X = transform_chunked(model.vectorizer, val[TEXT_COL], chunk)
        out[name] = {}
        for task in meta["tasks"]:
            orig_id = meta["run_ids"][task]
            orig = logged.get(orig_id)
            hp = json.loads(orig["hyperparams_json"]) if orig else dict(meta["hyperparams"])
            hp["rescore_of"] = orig_id
            labels, prob = model.scores(task, X)
            m = task_metrics(task, val[LABEL_COLS[task]].to_numpy(), labels, prob)
            out[name][task] = log_run(
                cfg["experiment_log"],
                data_version=dv,
                model=orig["model"] if orig else f"baseline/{meta['variant']}",
                task=LABEL_COLS[task],
                hyperparams=hp,
                seed=seed,
                n_train=meta["n_train"],
                owner=OWNER,
                notes=(
                    f"rescored: {METRIC_TAG}; rescore of {orig_id}; no retraining;"
                    " val metrics at argmax, no threshold tuning"
                    + ("; smoke" if meta.get("max_train") else "")
                ),
                **m,
            )
            logger.info("rescored %s/%s -> %s %s", name, task, out[name][task], m)
        meta["rescore_run_ids"] = out[name]
        (d / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
    return out


# --------------------------------------------------------------------------- full val report


def _length_bucket(edges: list[int]) -> pl.Expr:
    expr = pl.when(pl.col("n_words") < edges[0]).then(pl.lit(f"<{edges[0]}"))
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        expr = expr.when(pl.col("n_words") < hi).then(pl.lit(f"{lo}-{hi - 1}"))
    return expr.otherwise(pl.lit(f">={edges[-1]}")).alias("length_bucket")


def _md_table(df: pl.DataFrame, digits: int = 3) -> str:
    def cell(v: Any) -> str:
        if isinstance(v, float):
            return "" if np.isnan(v) else f"{v:.{digits}f}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)

    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * len(df.columns)
    rows = ["| " + " | ".join(cell(v) for v in r) + " |" for r in df.iter_rows()]
    return "\n".join([head, sep, *rows])


def evaluate(variant: str, max_train: int | None = None) -> dict[str, Any]:
    """Full val evaluation of a saved variant; writes the M3 baseline report.

    Chooses the priority threshold on val (max F1), stores it in ``meta.json`` for
    serving, and returns all computed numbers. No new experiment-log rows.
    """
    cfg = load_baseline_config()
    ecfg = cfg["eval"]
    data_cfg = load_config("data")
    d = _model_dir(cfg, variant, max_train)
    model = BaselineModel.load(d)

    val = load_split(
        "val",
        columns=[TEXT_COL, *LABEL_COLS.values(), "issue", "date_received", "n_words", "company"],
    )
    top_n = data_cfg["slices"]["top_companies"]
    top_companies = (
        load_split("train", columns=["company"])
        .group_by("company").len().sort(["len", "company"], descending=[True, False])
        .head(top_n)["company"]
    )
    val = val.with_columns(
        year=pl.col("date_received").dt.year().cast(pl.Utf8),
        company_size=pl.when(pl.col("company").is_in(top_companies.implode()))
        .then(pl.lit(f"top {top_n} companies")).otherwise(pl.lit("other companies")),
        severity=severity_mask(val["issue"]),
    ).with_columns(_length_bucket(data_cfg["slices"]["length_bucket_edges"]))
    X = transform_chunked(model.vectorizer, val[TEXT_COL], cfg["features"]["transform_chunk_rows"])

    results: dict[str, Any] = {"variant": variant, "meta": model.meta, "n_val": val.height}
    for task in model.meta["tasks"]:
        col = LABEL_COLS[task]
        labels, prob = model.scores(task, X)
        y_true = val[col].to_numpy()
        pred = np.asarray(labels)[prob.argmax(axis=1)]
        r: dict[str, Any] = {"labels": labels}
        if task == "priority":
            y_bin = (y_true == HIGH).astype(int)
            score = prob[:, labels.index(HIGH)]
            r["at_0_5"] = metrics.priority_metrics(y_bin, score, threshold=0.5)
            r["tuned"] = metrics.priority_metrics(y_bin, score)
            thr = r["tuned"]["threshold"]
            sev = val["severity"].to_numpy()
            r["recall_severity_high"] = metrics.recall_at(y_bin & sev, score, thr)
            r["recall_outcome_only_high"] = metrics.recall_at(y_bin & ~sev, score, thr)
            r["n_severity_high"] = int((y_bin & sev).sum())
            r["n_outcome_only_high"] = int((y_bin & ~sev).sum())
            pred = np.where(score >= thr, HIGH, "NORMAL")
            model.meta["priority_threshold"] = thr
        m = metrics.compute_metrics(
            y_true, pred, labels, y_score=None if task == "priority" else prob
        )
        r["metrics"] = m
        r["ci"] = metrics.bootstrap_macro_f1_ci(
            y_true, pred, n_boot=ecfg["n_boot"], seed=int(cfg["seed"])
        )
        frame = val.select("year", "length_bucket", "company_size").with_columns(
            t=pl.Series(y_true), p=pl.Series(pred)
        )
        r["slices"] = {
            s: metrics.slice_metrics(frame, "t", "p", s)
            for s in ("year", "length_bucket", "company_size")
        }
        results[task] = r
    (d / "meta.json").write_text(json.dumps(model.meta, indent=2, sort_keys=True))
    return results


def write_report(results: dict[str, Any], path: str | Path, thin: int, top_conf: int) -> None:
    """Render ``results`` from :func:`evaluate` as Markdown."""
    meta = results["meta"]
    out: list[str] = [
        "# M3 baseline: validation report",
        "",
        f"Generated by `python -m complaintiq.models.baseline eval --variant {results['variant']}`"
        " from the saved model. Every number below is computed on the **val** split"
        f" ({results['n_val']:,} rows); the test split was not read.",
        "",
        f"- Model: `baseline/{results['variant']}`, model_version `{meta['model_version']}`",
        f"- data_version `{meta['data_version']}`, n_train {meta['n_train']:,}",
        "- Training run_ids (reports/experiments/baseline.csv; their macro-F1 used the older"
        " definition and is superseded): "
        + ", ".join(f"{t} `{rid}`" for t, rid in meta["run_ids"].items()),
        "- Rescored run_ids (same model, fixed label set): "
        + (", ".join(f"{t} `{rid}`" for t, rid in meta.get("rescore_run_ids", {}).items())
           or "TODO (run `python -m complaintiq.models.baseline rescore`)"),
        "- Macro-F1 = mean F1 over the classes with val support (fixed label set);"
        " macro_f1_all_labels also counts classes that are only predicted.",
        "- Input: narrative only. Hyperparameters are in the run rows.",
        "",
    ]
    for task in meta["tasks"]:
        r = results[task]
        m, ci = r["metrics"], r["ci"]
        out += [f"## {LABEL_COLS[task]}", ""]
        if task == "priority":
            a, t = r["at_0_5"], r["tuned"]
            out += [
                f"PR-AUC (HIGH): **{t['pr_auc']:.3f}** (val HIGH base rate {t['base_rate']:.3f}).",
                "",
                "| threshold | how chosen | precision | recall | F1 |",
                "|---|---|---|---|---|",
                f"| {a['threshold']:.3f} | fixed 0.5 | {a['precision']:.3f} | {a['recall']:.3f}"
                f" | {a['f1']:.3f} |",
                f"| {t['threshold']:.3f} | max F1 on val (optimistic: tuned and scored on val)"
                f" | {t['precision']:.3f} | {t['recall']:.3f} | {t['f1']:.3f} |",
                "",
                f"Recall at the val-chosen threshold: severity-rule HIGH "
                f"**{r['recall_severity_high']:.3f}** (n={r['n_severity_high']:,}) vs "
                f"outcome-only HIGH **{r['recall_outcome_only_high']:.3f}**"
                f" (n={r['n_outcome_only_high']:,}). Outcome-only HIGH rows were labelled from"
                " company outcomes (monetary relief, untimely response), which the narrative"
                " cannot fully reveal.",
                "",
                "Below, macro-F1 and the per-class table use the val-chosen threshold.",
                "",
            ]
        top3 = f", top-3 accuracy **{m['top3']:.3f}**" if m["top3"] is not None else ""
        out += [
            f"Macro-F1 **{m['macro_f1']:.3f}** over the"
            f" {int((m['per_class']['support'] > 0).sum())} classes with val support"
            f" (95% bootstrap CI {ci['lo']:.3f}-{ci['hi']:.3f}, {int(ci['n_boot'])} resamples,"
            f" same fixed label set), macro_f1_all_labels {m['macro_f1_all_labels']:.3f},"
            f" weighted-F1 **{m['weighted_f1']:.3f}**, accuracy {m['accuracy']:.3f}{top3}.",
            "",
        ]
        pcm, cmat = m["per_class"], m["confusion"]
        ghost = [
            f"{lbl} ({int(cmat[:, i].sum())} predictions)"
            for i, lbl in enumerate(pcm["label"])
            if pcm["support"][i] == 0 and cmat[:, i].sum() > 0
        ]
        if ghost:
            out += [
                "Note: " + ", ".join(ghost) + " has no val rows but is predicted. It is outside"
                " the fixed label set, so it does not enter macro-F1; it does enter"
                " macro_f1_all_labels with F1 = 0.",
                "",
            ]
        out += [
            "### Per class",
            "",
        ]
        pc = m["per_class"].with_columns(
            thin=pl.when(pl.col("support") == 0).then(pl.lit("absent from val"))
            .when(pl.col("support") < thin).then(pl.lit(f"<{thin} val rows"))
            .otherwise(pl.lit(""))
        ).sort("support", descending=True)
        out += [_md_table(pc), ""]
        labels, cm = r["labels"], m["confusion"]
        if len(labels) <= 10:
            short = [lbl[:18] for lbl in labels]
            cmdf = pl.DataFrame(
                {"true \\ pred": short, **{s: cm[:, j].tolist() for j, s in enumerate(short)}}
            )
            out += ["### Confusion matrix (rows = true)", "", _md_table(cmdf), ""]
        else:
            off = cm.copy()
            np.fill_diagonal(off, 0)
            idx = np.dstack(np.unravel_index(np.argsort(-off, axis=None), off.shape))[0]
            pairs = [
                {
                    "true": labels[i],
                    "predicted": labels[j],
                    "n": int(off[i, j]),
                    "share_of_true": float(off[i, j] / max(cm[i].sum(), 1)),
                }
                for i, j in idx[:top_conf]
            ]
            out += [
                f"### Top {top_conf} confusions (full matrix is in the eval output)",
                "",
                _md_table(pl.DataFrame(pairs)),
                "",
            ]
        out += ["### Slices", ""]
        for name, sdf in r["slices"].items():
            out += [f"**{name}**", "", _md_table(sdf), ""]
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out).rstrip() + "\n")


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> None:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = load_baseline_config()
    ap = argparse.ArgumentParser(prog="python -m complaintiq.models.baseline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    tr = sub.add_parser("train", help="fit on train, evaluate on val, log runs")
    tr.add_argument("--variants", default=cfg["default_variant"], help="comma-separated")
    tr.add_argument("--tasks", default=",".join(cfg["tasks"]))
    tr.add_argument("--max-train", type=int, default=None, help="stratified subsample size")
    tr.add_argument("--smoke", action="store_true", help=f"--max-train {cfg['smoke_rows']}")
    tr.add_argument("--notes", default="")
    ev = sub.add_parser("eval", help="full val report for a saved variant")
    ev.add_argument("--variant", default=cfg["default_variant"])
    ev.add_argument("--max-train", type=int, default=None)
    ev.add_argument("--report", default=cfg["eval"]["report_path"])
    rs = sub.add_parser("rescore", help="re-score saved models on val (no retraining)")
    rs.add_argument("--models", required=True, help="comma-separated dirs under artifacts_dir")
    ad = sub.add_parser("add-tasks", help="fit missing tasks into a saved variant (M4)")
    ad.add_argument("--model", required=True, help="dir under artifacts_dir")
    ad.add_argument("--tasks", default="priority")
    ad.add_argument("--experiments-dir", default="reports/experiments/m4")
    ad.add_argument("--owner", default=OWNER)
    ad.add_argument("--notes", default="")
    args = ap.parse_args(argv)

    if args.cmd == "add-tasks":
        ids = add_tasks(args.model, args.tasks.split(","), resolve(args.experiments_dir),
                        owner=args.owner, notes=args.notes)
        print(json.dumps(ids, indent=2))
        return

    if args.cmd == "train":
        max_train = cfg["smoke_rows"] if args.smoke else args.max_train
        notes = ("smoke; " if args.smoke else "") + args.notes
        ids = train(args.variants.split(","), args.tasks.split(","), max_train, notes)
        print(json.dumps(ids, indent=2))
    elif args.cmd == "rescore":
        print(json.dumps(rescore(args.models.split(",")), indent=2))
    else:
        results = evaluate(args.variant, args.max_train)
        write_report(
            results, resolve(args.report), cfg["eval"]["thin_class_rows"],
            cfg["eval"]["top_confusions"],
        )
        print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
