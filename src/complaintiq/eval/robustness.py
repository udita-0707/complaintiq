"""Robustness of the primary model to text perturbations (SPEC C6, M4).

Each perturbation is applied to the same seeded, stratified val subsample; product and
issue macro-F1 (over the fixed label set of that subsample) are compared with the clean
text. Every (task, perturbation) is logged with ``log_run`` (notes start "robustness").
The test split is never read; perturbed text is never printed or logged.

CLI::

    python -m complaintiq.eval.robustness run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import zlib
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import polars as pl

from complaintiq.config import load_config
from complaintiq.data.load import resolve

logger = logging.getLogger("complaintiq.eval.robustness")

_LETTERS = "abcdefghijklmnopqrstuvwxyz"
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


# --------------------------------------------------------------------------- perturbations


def add_typos(text: str, rate: float, rng: np.random.Generator) -> str:
    """Edit about ``rate`` of the letters: delete, substitute, swap with next, or insert."""
    chars = list(text)
    pos = [i for i, c in enumerate(chars) if c.isalpha()]
    if not pos or rate <= 0:
        return text
    hit = np.asarray(pos)[rng.random(len(pos)) < rate]
    ops = rng.integers(0, 4, size=len(hit))
    subs = rng.integers(0, 26, size=len(hit))
    for i, op, s in zip(hit[::-1], ops[::-1], subs[::-1], strict=True):  # right to left
        if op == 0:
            del chars[i]
        elif op == 1:
            chars[i] = _LETTERS[s]
        elif op == 2 and i + 1 < len(chars):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        else:
            chars.insert(i, _LETTERS[s])
    return "".join(chars)


def truncate_words(text: str, n: int) -> str:
    """Keep the first ``n`` whitespace-separated words."""
    return " ".join(text.split()[:n])


def shuffle_sentences(text: str, rng: np.random.Generator) -> str:
    """Shuffle sentences (split after . ! ?); a single sentence is returned unchanged."""
    parts = _SENT_SPLIT.split(text.strip())
    if len(parts) < 2:
        return text
    order = rng.permutation(len(parts))
    return " ".join(parts[i] for i in order)


def add_boilerplate(text: str, prefix: str, suffix: str) -> str:
    """Wrap the narrative in generic, label-free boilerplate."""
    return f"{prefix} {text} {suffix}"


def redact_more(text: str, frac: float, rng: np.random.Generator, token: str) -> str:
    """Replace about ``frac`` of the words that are not already ``token`` with ``token``."""
    words = text.split()
    hit = rng.random(len(words)) < frac
    return " ".join(token if h and w != token else w for w, h in zip(words, hit, strict=True))


def perturbations(cfg: dict[str, Any], token: str) -> dict[str, Callable[[str, Any], str]]:
    """Name -> ``f(text, rng)`` for every configured perturbation (fixed order)."""
    out: dict[str, Callable[[str, Any], str]] = {}
    for r in cfg["typo_rates"]:
        out[f"typos_{round(r * 100)}pct"] = lambda t, g, r=r: add_typos(t, r, g)
    for n in cfg["truncate_words"]:
        out[f"truncate_first_{n}_words"] = lambda t, g, n=n: truncate_words(t, n)
    out["sentence_shuffle"] = shuffle_sentences
    out["added_boilerplate"] = lambda t, g: add_boilerplate(
        t, cfg["boilerplate_prefix"], cfg["boilerplate_suffix"]
    )
    out["lowercase"] = lambda t, g: t.lower()
    frac = cfg["redact_extra_frac"]
    out[f"redacted_plus_{round(frac * 100)}pct"] = lambda t, g: redact_more(t, frac, g, token)
    return out


def apply(texts: Sequence[str], fn: Callable[[str, Any], str], seed: int, name: str) -> list[str]:
    """Apply ``fn`` to every text with one generator seeded by (seed, name)."""
    rng = np.random.default_rng([seed, zlib.crc32(name.encode())])
    return [fn(t, rng) for t in texts]


def drop_table(clean: dict[str, float], perturbed: dict[str, dict[str, float]]) -> pl.DataFrame:
    """Rows of perturbation, macro_f1, drop vs clean (clean minus perturbed)."""
    rows = [{"perturbation": "clean", "macro_f1": clean["macro_f1"], "drop": 0.0,
             "accuracy": clean["accuracy"], "flip_rate": 0.0}]
    for name, m in perturbed.items():
        rows.append({"perturbation": name, "macro_f1": m["macro_f1"],
                     "drop": clean["macro_f1"] - m["macro_f1"], "accuracy": m["accuracy"],
                     "flip_rate": m["flip_rate"]})
    return pl.DataFrame(rows)


# --------------------------------------------------------------------------- run


def run() -> dict[str, Any]:
    """Score clean and perturbed val text, log every run, write the report."""
    from complaintiq.data.training_data import LABEL_COLS, load_split, sample_train
    from complaintiq.eval.metrics import compute_metrics
    from complaintiq.eval.tracking import log_run
    from complaintiq.models.baseline import (
        TEXT_COL,
        BaselineModel,
        load_baseline_config,
        transform_chunked,
    )

    ecfg = load_config("eval")
    cfg = ecfg["robustness"]
    seed = int(ecfg["seed"])
    token = load_config("data")["clean"]["placeholder_token"]
    chunk = load_baseline_config()["features"]["transform_chunk_rows"]
    model = BaselineModel.load(resolve(ecfg["primary_model_dir"]))
    meta = model.meta
    tasks = cfg["tasks"]
    cols = list(dict.fromkeys([TEXT_COL, *(LABEL_COLS[t] for t in tasks), "issue_class"]))
    val = load_split("val", columns=cols)
    sub = sample_train(val, "issue_class", max_rows=cfg["n_rows"], seed=seed)
    texts = sub[TEXT_COL].to_list()
    y = {t: sub[LABEL_COLS[t]].to_numpy() for t in tasks}

    def score(txts: list[str]) -> dict[str, dict[str, Any]]:
        X = transform_chunked(model.vectorizer, pl.Series(txts), chunk)
        out = {}
        for t in tasks:
            labels, prob = model.scores(t, X)
            pred = np.asarray(labels)[prob.argmax(axis=1)]
            m = compute_metrics(y[t], pred, labels, y_score=prob)
            out[t] = {"macro_f1": m["macro_f1"], "weighted_f1": m["weighted_f1"],
                      "accuracy": m["accuracy"], "top3": m["top3"], "pred": pred}
        return out

    clean = score(texts)
    results: dict[str, Any] = {
        "n_rows": sub.height, "seed": seed, "model_id": ecfg["primary_model_id"],
        "model_version": meta["model_version"], "data_version": meta["data_version"],
        "clean": {t: {k: v for k, v in clean[t].items() if k != "pred"} for t in tasks},
        "perturbed": {t: {} for t in tasks}, "run_ids": {},
    }
    exp_dir = resolve(ecfg["experiments_dir"])
    for name, fn in perturbations(cfg, token).items():
        pert = score(apply(texts, fn, seed, name))
        for t in tasks:
            p = pert[t]
            flip = float((p["pred"] != clean[t]["pred"]).mean())
            entry = {k: v for k, v in p.items() if k != "pred"} | {"flip_rate": flip}
            results["perturbed"][t][name] = entry
            drop = clean[t]["macro_f1"] - p["macro_f1"]
            rid = log_run(
                "robustness", exp_dir, data_version=meta["data_version"],
                model=ecfg["primary_model_id"], task=LABEL_COLS[t],
                hyperparams={"perturbation": name, "n_rows": sub.height, "seed": seed,
                             "robustness": {k: cfg[k] for k in cfg if k != "report_path"}},
                seed=seed, n_train=meta["n_train"], owner=ecfg["owner"],
                val_macro_f1=p["macro_f1"], val_weighted_f1=p["weighted_f1"], val_top3=p["top3"],
                notes=(f"robustness; perturbation={name}; val subsample n={sub.height};"
                       f" clean_macro_f1={clean[t]['macro_f1']:.6f}; drop={drop:.6f};"
                       f" flip_rate={flip:.4f}; fixed label set of the subsample"),
            )
            results["run_ids"][f"{t}/{name}"] = rid
        logger.info("%s done", name)
    out_json = resolve(ecfg["reports_dir"]) / "results" / "robustness.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=2, sort_keys=True))
    write_report(results, cfg, resolve(cfg["report_path"]))
    return results


def write_report(results: dict[str, Any], cfg: dict[str, Any], path: Any) -> None:
    """Markdown robustness report from :func:`run` results."""
    out = [
        "# M4 robustness (validation split)",
        "",
        "Generated by `python -m complaintiq.eval.robustness run` (`make robustness`). The"
        " test split was not read.",
        "",
        f"- Model `{results['model_id']}` (model_version `{results['model_version']}`,"
        f" data_version `{results['data_version']}`).",
        f"- Rows: a seeded (seed {results['seed']}) val subsample of {results['n_rows']:,} rows,"
        " stratified on issue_class (every class kept). Clean and perturbed scores use the same"
        " rows and the same label set (classes with support in the subsample), so the drop is"
        " paired.",
        "- drop = clean macro-F1 minus perturbed macro-F1 (positive = worse). flip_rate = share"
        " of rows whose predicted label changed.",
        "- Every row below is a logged run in `reports/experiments/m4/robustness.csv`"
        " (notes start with `robustness`).",
        "",
        "Perturbations: typos edit the given share of letters (delete, substitute, swap,"
        " insert); truncation keeps the first N words; sentence shuffle permutes sentences;"
        f" boilerplate adds a fixed prefix (\"{cfg['boilerplate_prefix']}\") and suffix"
        f" (\"{cfg['boilerplate_suffix']}\"); lowercase lowercases (the vectorizer already"
        " lowercases, so this is a sanity check that should show zero drop); redaction replaces"
        f" {cfg['redact_extra_frac']:.0%} of the remaining words with the placeholder.",
        "",
        "Not run (SPEC C6 lists them): paraphrase (needs a paraphrase model) and unseen"
        " company names (narratives rarely name the company after CFPB redaction). TODO.",
        "",
    ]
    for t, per in results["perturbed"].items():
        tbl = drop_table(results["clean"][t], per).with_columns(
            run_id=pl.Series([""] + [results["run_ids"][f"{t}/{n}"] for n in per])
        )
        out += [f"## {t}", "", _md(tbl, 4), ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n")


def _md(df: pl.DataFrame, digits: int) -> str:
    def cell(v: Any) -> str:
        if isinstance(v, float):
            return f"{v:.{digits}f}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)

    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * len(df.columns)
    return "\n".join([head, sep, *("| " + " | ".join(cell(v) for v in r) + " |"
                                   for r in df.iter_rows())])


def main(argv: Sequence[str] | None = None) -> None:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m complaintiq.eval.robustness")
    ap.add_argument("cmd", choices=["run"])
    ap.parse_args(argv)
    res = run()
    print(json.dumps({t: {n: round(m["macro_f1"], 4) for n, m in per.items()}
                      for t, per in res["perturbed"].items()}, indent=2))


if __name__ == "__main__":
    main()
