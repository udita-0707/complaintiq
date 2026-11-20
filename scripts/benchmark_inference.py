"""CPU inference benchmark and vocabulary-size study for the primary model (SPEC C6, M4).

Subcommands::

    python scripts/benchmark_inference.py vocab-train --size 100000   # one model per call
    python scripts/benchmark_inference.py run                         # benchmark + report

``vocab-train`` refits the TF-IDF vocabulary with ``max_features=size`` exactly as M3 did
(same seeded 200k-row vocabulary sample), trains product and issue with the primary
model's classifier settings, scores them on val and logs the run. ``run`` measures
single-request and batch-8 latency (p50/p95/p99), throughput, memory and size of the
primary model as served (calibrated ``BaselinePredictor``), compares vocabulary sizes, and
times the transformer smoke checkpoint (latency only). Requests are val narratives; text
is never printed. The test split is never read.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import psutil

from complaintiq.config import load_config
from complaintiq.data.load import resolve

logger = logging.getLogger("benchmark_inference")
MB = 1024 * 1024


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / MB


def _peak_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / MB if sys.platform == "darwin" else peak / 1024  # bytes on macOS, KB on Linux


def percentiles(ms: list[float]) -> dict[str, float]:
    """p50/p95/p99/mean of a list of latencies in milliseconds."""
    a = np.asarray(ms)
    return {"p50_ms": float(np.percentile(a, 50)), "p95_ms": float(np.percentile(a, 95)),
            "p99_ms": float(np.percentile(a, 99)), "mean_ms": float(a.mean()), "n": len(a)}


def time_calls(fn: Any, items: list[Any], warmup: int) -> list[float]:
    """Call ``fn(item)`` for each item after ``warmup`` untimed calls; return ms per call."""
    for it in items[:warmup]:
        fn(it)
    out = []
    for it in items:
        t = time.perf_counter()
        fn(it)
        out.append((time.perf_counter() - t) * 1000)
    return out


def dir_size_mb(d: Path, names: list[str]) -> float:
    """Total size of the named files in ``d`` (MB)."""
    return sum((d / n).stat().st_size for n in names if (d / n).exists()) / MB


def _val_texts(n: int, seed: int) -> list[str]:
    from complaintiq.data.training_data import load_split

    val = load_split("val", columns=["narrative"])
    return val["narrative"].sample(n=n, seed=seed, shuffle=True).to_list()


# --------------------------------------------------------------------------- vocab study


def vocab_train(size: int) -> dict[str, Any]:
    """Fit a ``max_features=size`` vocabulary + product/issue classifiers; save and log."""
    from complaintiq.data.training_data import LABEL_COLS, load_split
    from complaintiq.eval.tracking import log_run
    from complaintiq.models.baseline import (
        TEXT_COL,
        BaselineModel,
        build_classifier,
        build_vectorizer,
        fit_with_convergence,
        task_metrics,
        transform_chunked,
    )

    ecfg = load_config("eval")
    bcfg = ecfg["benchmark"]
    primary = BaselineModel.load(resolve(ecfg["primary_model_dir"]))
    params = {**primary.meta["hyperparams"], "max_features": int(size)}
    params.pop("tasks", None)
    seed = int(load_config("baseline")["seed"])
    f = params["features"]
    tasks = ("product", "issue")
    train = load_split("train", columns=[TEXT_COL, *(LABEL_COLS[t] for t in tasks)])
    val = load_split("val", columns=[TEXT_COL, *(LABEL_COLS[t] for t in tasks)])
    t0 = time.perf_counter()
    vec = build_vectorizer(params)
    n_vocab = min(f["vocab_fit_rows"], train.height)
    vec.fit(train[TEXT_COL].sample(n=n_vocab, seed=seed, shuffle=True).to_list())
    X_train = transform_chunked(vec, train[TEXT_COL], f["transform_chunk_rows"])
    X_val = transform_chunked(vec, val[TEXT_COL], f["transform_chunk_rows"])
    vec_s = time.perf_counter() - t0
    clfs, run_ids, metrics = {}, {}, {}
    for task in tasks:
        col = LABEL_COLS[task]
        clf = build_classifier(params, seed)
        t1 = time.perf_counter()
        conv = fit_with_convergence(clf, X_train, train[col].to_numpy())
        fit_s = time.perf_counter() - t1
        labels = [str(c) for c in clf.classes_]
        m = task_metrics(task, val[col].to_numpy(), labels, clf.predict_proba(X_val))
        metrics[task] = m
        run_ids[task] = log_run(
            "benchmark", resolve(ecfg["experiments_dir"]),
            data_version=primary.meta["data_version"],
            model=f"{ecfg['primary_model_id']}@vocab{size}", task=col,
            hyperparams={**params, "vocab_size": len(vec.vocabulary_), **conv},
            seed=seed, n_train=train.height, train_seconds=round(fit_s, 1),
            owner=ecfg["owner"],
            notes=(f"vocabulary study: max_features={size}; vectorize_seconds={vec_s:.0f};"
                   " full val, argmax; metric: fixed label set"),
            **m,
        )
        clfs[task] = clf
    out_dir = resolve(bcfg["vocab_study_dir"]) / f"v{size}"
    BaselineModel(vec, clfs, {
        "variant": f"{primary.meta['variant']}@vocab{size}", "tasks": list(tasks),
        "data_version": primary.meta["data_version"], "n_train": train.height,
        "model_version": f"vocab{size}", "run_ids": run_ids, "hyperparams": params,
    }).save(out_dir)
    return {"size": size, "run_ids": run_ids, "metrics": metrics, "dir": str(out_dir)}


# --------------------------------------------------------------------------- benchmark


def _baseline_bench(model_dir: Path, texts: list[str], warmup: int, batch: int,
                    tasks: tuple[str, ...]) -> dict[str, Any]:
    """Latency of vectorize + predict_proba for ``tasks`` at batch 1 and ``batch``."""
    from complaintiq.models.baseline import BaselineModel

    gc.collect()
    r0 = _rss_mb()
    t = time.perf_counter()
    m = BaselineModel.load(model_dir)
    load_s = time.perf_counter() - t
    r1 = _rss_mb()

    def infer(txts: list[str]) -> None:
        X = m.vectorizer.transform(txts)
        for task in tasks:
            m.classifiers[task].predict_proba(X)

    single = percentiles(time_calls(lambda x: infer([x]), texts, warmup))
    batches = [texts[i: i + batch] for i in range(0, len(texts) - batch + 1, batch)]
    b = percentiles(time_calls(infer, batches, max(1, warmup // batch)))
    files = ["vectorizer.joblib", *(f"{t}.joblib" for t in tasks)]
    return {
        "load_seconds": load_s, "rss_load_delta_mb": r1 - r0,
        "size_mb": dir_size_mb(model_dir, files),
        "vocab": len(m.vectorizer.vocabulary_), "single": single, "batch": b,
        "throughput_single_rps": 1000 / single["mean_ms"],
        "throughput_batch_rps": batch * 1000 / b["mean_ms"],
    }


def run() -> dict[str, Any]:
    """Benchmark the served primary model, the vocabulary study and the transformer."""
    from complaintiq.eval.tracking import log_run
    from complaintiq.models.baseline import BaselinePredictor

    ecfg = load_config("eval")
    bcfg = ecfg["benchmark"]
    seed = int(ecfg["seed"])
    th = load_config("thresholds")
    model_dir = resolve(ecfg["primary_model_dir"])
    res: dict[str, Any] = {
        "machine": {"platform": platform.platform(), "processor": platform.processor(),
                    "cpu_count": psutil.cpu_count(),
                    "ram_gb": psutil.virtual_memory().total / 2**30,
                    "python": platform.python_version()},
        "model_id": ecfg["primary_model_id"],
    }
    # 1. Served path, measured before loading val so the RSS delta is the model's.
    gc.collect()
    r0 = _rss_mb()
    t = time.perf_counter()
    pred = BaselinePredictor(
        model_dir,
        temperatures={"product": th.get("temperature_product", 1.0),
                      "issue": th.get("temperature_issue", 1.0)},
        priority_threshold=th.get("priority_threshold"),
    )
    load_s = time.perf_counter() - t
    rss_model = _rss_mb() - r0
    texts = _val_texts(bcfg["n_texts"], seed)
    single = percentiles(time_calls(pred.predict, texts, bcfg["warmup"]))
    m = pred.model
    bs = bcfg["batch_size"]

    def batch_infer(txts: list[str]) -> None:
        X = m.vectorizer.transform(txts)
        for task in ("product", "issue", "priority"):
            m.classifiers[task].predict_proba(X)

    batches = [texts[i: i + bs] for i in range(0, len(texts) - bs + 1, bs)]
    batch = percentiles(time_calls(batch_infer, batches, max(1, bcfg["warmup"] // bs)))
    files = ["vectorizer.joblib", "product.joblib", "issue.joblib", "priority.joblib"]
    res["served"] = {
        "model_version": pred.model_version, "load_seconds": load_s, "rss_model_mb": rss_model,
        "size_mb": dir_size_mb(model_dir, files), "single": single, "batch": batch,
        "batch_size": bs, "throughput_single_rps": 1000 / single["mean_ms"],
        "throughput_batch_rps": bs * 1000 / batch["mean_ms"],
        "n_words_mean": float(np.mean([len(x.split()) for x in texts])),
    }
    gc.collect()

    # 2. Vocabulary study (product + issue only, so every size is timed the same way).
    study = []
    for size in bcfg["vocab_sizes"]:
        d = model_dir if size == 200000 else resolve(bcfg["vocab_study_dir"]) / f"v{size}"
        if not (d / "meta.json").exists():
            study.append({"size": size, "status": "TODO: run vocab-train --size " + str(size)})
            continue
        b = _baseline_bench(d, texts, bcfg["warmup"], bs, ("product", "issue"))
        study.append({"size": size, "dir": str(d.relative_to(resolve("."))), **b})
        gc.collect()
    res["vocab_study"] = study

    # 3. Transformer smoke checkpoint: FP32 CPU latency only (weights are a smoke run).
    tdir = resolve(bcfg["transformer_dir"])
    res["transformer"] = {"status": "missing"}
    if all((tdir / t / "ciq_meta.json").exists() for t in ("product", "issue", "priority")):
        try:
            import torch

            from complaintiq.models.transformer import TransformerPredictor

            torch.set_num_threads(psutil.cpu_count(logical=False) or 1)
            gc.collect()
            r0 = _rss_mb()
            tp = TransformerPredictor(tdir)
            trss = _rss_mb() - r0
            tt = texts[: bcfg["transformer_n_texts"]]
            lat = percentiles(time_calls(tp.predict, tt, 5))
            metas = {t: json.loads((tdir / t / "ciq_meta.json").read_text()) for t in
                     ("product", "issue", "priority")}
            res["transformer"] = {
                "status": "measured", "device": tp.device, "rss_model_mb": trss,
                "size_mb": sum(dir_size_mb(tdir / t, ["model.safetensors"]) for t in metas),
                "single": lat, "run_ids": {t: m_["run_id"] for t, m_ in metas.items()},
                "max_len": metas["product"]["max_len"], "torch_threads": torch.get_num_threads(),
            }
            del tp
        except ImportError as exc:  # torch/transformers not installed
            res["transformer"] = {"status": f"skipped: {exc}"}
    res["peak_rss_mb"] = _peak_mb()

    s = res["served"]
    res["run_id"] = log_run(
        "benchmark", resolve(ecfg["experiments_dir"]),
        data_version=json.loads((model_dir / "meta.json").read_text())["data_version"],
        model=ecfg["primary_model_id"], task="inference_benchmark",
        hyperparams={"benchmark": bcfg, "machine": res["machine"]}, seed=seed,
        owner=ecfg["owner"],
        notes=(f"benchmark: CPU single p50={s['single']['p50_ms']:.2f}ms"
               f" p95={s['single']['p95_ms']:.2f}ms p99={s['single']['p99_ms']:.2f}ms;"
               f" batch{bs} p95={s['batch']['p95_ms']:.2f}ms;"
               f" results=reports/m4/results/benchmark.json"),
    )
    out = resolve(ecfg["reports_dir"]) / "results" / "benchmark.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True))
    write_report(res, bcfg)
    return res


def _vocab_metrics() -> dict[int, dict[str, str]]:
    """val macro-F1 per vocabulary size from the experiment logs (M3 log for 200k)."""
    from complaintiq.eval.tracking import read_runs

    ecfg = load_config("eval")
    out: dict[int, dict[str, str]] = {}
    for r in read_runs(resolve(ecfg["experiments_dir"])):
        if "@vocab" in r["model"]:
            size = int(r["model"].split("@vocab")[1])
            out.setdefault(size, {})[r["task"]] = (r["val_macro_f1"], r["run_id"])
    for r in read_runs():  # M3 log: the primary model's own product/issue runs
        if r["model"] == ecfg["primary_model_id"] and r["task"] in ("product_class", "issue_class"):
            out.setdefault(200000, {})[r["task"]] = (r["val_macro_f1"], r["run_id"])
    return out


def write_report(res: dict[str, Any], bcfg: dict[str, Any]) -> None:
    """Markdown benchmark report."""
    s, mc = res["served"], res["machine"]
    out = [
        "# M4 inference benchmark (CPU)",
        "",
        "Generated by `python scripts/benchmark_inference.py run` (`make benchmark`); raw"
        " numbers in `reports/m4/results/benchmark.json`, run logged in"
        f" `reports/experiments/m4/benchmark.csv` (run_id `{res['run_id']}`). Requests are"
        f" {s['single']['n']} val narratives (seeded sample, mean {s['n_words_mean']:.0f} words);"
        " in-process timing, no HTTP (see `reports/m4/api_latency.md` for the API).",
        "",
        f"Machine: {mc['platform']}, {mc['cpu_count']} logical CPUs, {mc['ram_gb']:.0f} GB RAM,"
        f" Python {mc['python']}. Single machine, single run: treat as indicative.",
        "",
        f"## Primary model as served: `{res['model_id']}` (`{s['model_version']}`)",
        "",
        "Calibrated `BaselinePredictor.predict` (vectorize + product, issue, priority +"
        " temperature) for single requests; vectorize + 3x predict_proba for batches.",
        "",
        "| mode | p50 ms | p95 ms | p99 ms | mean ms | throughput (req/s) |",
        "|---|---|---|---|---|---|",
        f"| single (batch 1) | {s['single']['p50_ms']:.2f} | {s['single']['p95_ms']:.2f} |"
        f" {s['single']['p99_ms']:.2f} | {s['single']['mean_ms']:.2f} |"
        f" {s['throughput_single_rps']:.1f} |",
        f"| batch {s['batch_size']} (per batch) | {s['batch']['p50_ms']:.2f} |"
        f" {s['batch']['p95_ms']:.2f} | {s['batch']['p99_ms']:.2f} | {s['batch']['mean_ms']:.2f}"
        f" | {s['throughput_batch_rps']:.1f} |",
        "",
        f"- Model size on disk: **{s['size_mb']:.1f} MB** (vectorizer + 3 classifiers, joblib).",
        f"- RSS increase when loading: **{s['rss_model_mb']:.0f} MB**; load time"
        f" {s['load_seconds']:.1f} s. Peak RSS of the benchmark process (includes val text and"
        f" the other models): {res['peak_rss_mb']:.0f} MB.",
        f"- SPEC B7 target p95 <= 300 ms on CPU: single-request p95 {s['single']['p95_ms']:.2f} ms"
        f" ({'meets' if s['single']['p95_ms'] <= 300 else 'misses'}).",
        f"- Cost per 1k requests (assumption-based): {s['single']['mean_ms']:.2f} ms mean CPU time"
        f" per request = {s['single']['mean_ms']:.2f} CPU-seconds per 1k requests on one core;"
        " a price per CPU-hour is needed to turn this into money (TODO: team assumption).",
        "",
        "## Vocabulary-size study (product + issue)",
        "",
        "Same seeded vocabulary sample, n-grams and classifier settings; only max_features"
        " changes. Latency is vectorize + product + issue predict_proba (no priority) so every"
        " size is timed the same way. val macro-F1 is full val from the logged runs.",
        "",
        "Memory is compared by on-disk size: RSS deltas of models loaded one after another in"
        " one process are dominated by allocator reuse and are not reported per size.",
        "",
        "| max_features | product val macro-F1 | issue val macro-F1 | size MB |"
        " single p50 ms | single p95 ms | batch-8 p95 ms | run_ids |",
        "|---|---|---|---|---|---|---|---|",
    ]
    vm = _vocab_metrics()
    for row in res["vocab_study"]:
        size = row["size"]
        mets = vm.get(size, {})
        pf, pid = mets.get("product_class", ("", ""))
        if_, iid = mets.get("issue_class", ("", ""))
        if "status" in row:
            out.append(f"| {size:,} | {pf} | {if_} | | | | | {row['status']} |")
            continue
        fmt = (lambda v: f"{float(v):.4f}" if v else "TODO")  # noqa: E731
        out.append(
            f"| {size:,} | {fmt(pf)} | {fmt(if_)} | {row['size_mb']:.1f} |"
            f" {row['single']['p50_ms']:.2f} |"
            f" {row['single']['p95_ms']:.2f} | {row['batch']['p95_ms']:.2f} |"
            f" `{pid}`, `{iid}` |"
        )
    t = res["transformer"]
    out += ["", "## Transformer (DistilBERT) FP32 vs ONNX int8", ""]
    if t.get("status") == "measured":
        out += [
            "Only the **CPU smoke checkpoints** exist locally (run_ids "
            + ", ".join(f"{k} `{v}`" for k, v in t["run_ids"].items())
            + "; trained on about 2k rows). Their accuracy is meaningless, but latency, size and"
            " memory depend on the architecture, not the weights, so FP32 CPU latency is"
            " reported. Three checkpoints (product, issue, priority) run per request.",
            "",
            "| variant | device | threads | max_len | single p50 ms | single p95 ms |"
            " single p99 ms | size MB (3 models) | RSS load MB |",
            "|---|---|---|---|---|---|---|---|---|",
            f"| FP32 PyTorch | {t['device']} | {t['torch_threads']} | {t['max_len']} |"
            f" {t['single']['p50_ms']:.1f} | {t['single']['p95_ms']:.1f} |"
            f" {t['single']['p99_ms']:.1f} | {t['size_mb']:.0f} | {t['rss_model_mb']:.0f} |",
            "| ONNX int8 | TODO | | | | | | | |",
            "",
            f"n = {t['single']['n']} requests. **TODO:** ONNX export + int8 quantization needs"
            " `onnx`/`onnxruntime` (and an exporter such as `optimum`), which are not installed;"
            " not installed without approval. Accuracy drop and the >= 98% agreement check"
            " (SPEC C11) need the GPU-trained checkpoint (TODO).",
        ]
    else:
        out += [f"TODO: transformer not benchmarked ({t.get('status')})."]
    path = resolve(bcfg["report_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n")


def main() -> None:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="scripts/benchmark_inference.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vocab-train", help="fit one vocabulary-size model (product, issue)")
    v.add_argument("--size", type=int, required=True)
    sub.add_parser("run", help="benchmark and write reports/m4/inference_benchmark.md")
    args = ap.parse_args()
    if args.cmd == "vocab-train":
        r = vocab_train(args.size)
        print(json.dumps({"size": r["size"], "run_ids": r["run_ids"]}, indent=2))
    else:
        r = run()
        print(json.dumps({"run_id": r["run_id"], "single": r["served"]["single"]}, indent=2))


if __name__ == "__main__":
    main()
