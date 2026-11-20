"""DistilBERT fine-tuning for issue, product and priority (SPEC C5, Candidate 1).

Config-driven from ``configs/model.yaml: transformer``. Input is ONLY ``narrative``.
Head+tail truncation, class-weighted loss, mixed precision on CUDA only, early stopping
on val macro-F1, fixed seeds, stratified train subsample, optional log-prior correction.
torch/transformers are imported lazily so the pure helpers work without the ml extra.
The test split is never read here.

CLI::

    python -m complaintiq.models.transformer train [--smoke] [--tasks issue,product]
    python -m complaintiq.models.transformer eval  [--prior-correction]
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import random
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from complaintiq.config import load_config
from complaintiq.data.load import resolve
from complaintiq.serving.predictor import Prediction

logger = logging.getLogger("complaintiq.models.transformer")

TEXT_COL = "narrative"
HIGH = "HIGH"
OWNER = "team-m3-session"


# --------------------------------------------------------------------------- pure helpers


def load_transformer_config() -> dict[str, Any]:
    """``configs/model.yaml: transformer`` plus the top-level seed."""
    cfg = load_config("model")
    t = copy.deepcopy(cfg["transformer"])
    t.setdefault("seed", cfg.get("seed", 42))
    return t


def content_budget(max_len: int, head_tokens: int, n_special: int = 2) -> tuple[int, int]:
    """Split ``max_len - n_special`` content tokens into (head, tail) counts."""
    budget = max_len - n_special
    head = min(head_tokens, budget)
    return head, budget - head


def head_tail_truncate(ids: Sequence[int], head: int, tail: int) -> list[int]:
    """Keep the first ``head`` and last ``tail`` tokens when ``ids`` is too long."""
    ids = list(ids)
    if len(ids) <= head + tail:
        return ids
    return ids[:head] + (ids[-tail:] if tail > 0 else [])


def build_label_maps(labels: Sequence[str]) -> tuple[dict[str, int], dict[int, str]]:
    """Deterministic (sorted) label <-> id maps."""
    uniq = sorted(set(labels))
    label2id = {lbl: i for i, lbl in enumerate(uniq)}
    return label2id, {i: lbl for lbl, i in label2id.items()}


def balanced_class_weights(y_ids: Sequence[int], n_classes: int) -> np.ndarray:
    """``n / (k * count_c)`` per class (sklearn 'balanced'); 0 for absent classes."""
    counts = np.bincount(np.asarray(y_ids), minlength=n_classes).astype(float)
    present = counts > 0
    w = np.zeros(n_classes)
    w[present] = counts.sum() / (present.sum() * counts[present])
    return w


def prior_correction(
    logits: np.ndarray, train_priors: np.ndarray, target_priors: np.ndarray | None = None
) -> np.ndarray:
    """Log-prior adjustment: ``logits - log p_train + log p_target`` (uniform target if None).

    With a uniform target this removes the training label prior from the scores.
    """
    eps = 1e-12
    adj = np.asarray(logits, dtype=float) - np.log(np.asarray(train_priors) + eps)
    if target_priors is not None:
        adj = adj + np.log(np.asarray(target_priors) + eps)
    return adj


def softmax(x: np.ndarray) -> np.ndarray:
    """Row-wise softmax."""
    z = x - x.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def select_device() -> str:
    """``cuda`` > ``mps`` > ``cpu``."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def set_seed(seed: int) -> None:
    """Seed python, numpy and torch."""
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# --------------------------------------------------------------------------- encoding


def encode(tokenizer: Any, texts: Sequence[str], max_len: int, head_tokens: int) -> list[list[int]]:
    """Tokenize without truncation, apply head+tail truncation, add [CLS]/[SEP]."""
    head, tail = content_budget(max_len, head_tokens)
    cls_id = tokenizer.cls_token_id
    cls_id = cls_id if cls_id is not None else tokenizer.bos_token_id
    sep_id = tokenizer.sep_token_id
    sep_id = sep_id if sep_id is not None else tokenizer.eos_token_id
    enc = tokenizer(list(texts), add_special_tokens=False, truncation=False)["input_ids"]
    return [[cls_id, *head_tail_truncate(ids, head, tail), sep_id] for ids in enc]


def _batches(seqs: list[list[int]], batch_size: int, pad_id: int, order: np.ndarray):
    import torch

    for i in range(0, len(order), batch_size):
        idx = order[i : i + batch_size]
        width = max(len(seqs[j]) for j in idx)
        ids = torch.full((len(idx), width), pad_id, dtype=torch.long)
        mask = torch.zeros((len(idx), width), dtype=torch.long)
        for r, j in enumerate(idx):
            ids[r, : len(seqs[j])] = torch.tensor(seqs[j])
            mask[r, : len(seqs[j])] = 1
        yield idx, ids, mask


def predict_logits(
    model: Any, seqs: list[list[int]], batch_size: int, pad_id: int, device: str
) -> np.ndarray:
    """Logits for pre-encoded sequences (sorted by length for speed, then restored)."""
    import torch

    model.eval()
    order = np.argsort([len(s) for s in seqs], kind="stable")
    out = np.zeros((len(seqs), model.config.num_labels), dtype=np.float32)
    use_amp = device == "cuda"
    with torch.no_grad():
        for idx, ids, mask in _batches(seqs, batch_size, pad_id, order):
            with torch.autocast("cuda", dtype=torch.float16, enabled=use_amp):
                logits = model(input_ids=ids.to(device), attention_mask=mask.to(device)).logits
            out[idx] = logits.float().cpu().numpy()
    return out


# --------------------------------------------------------------------------- metrics


def score_task(task: str, y_true: np.ndarray, labels: list[str], prob: np.ndarray) -> dict:
    """Logged val metrics (argmax; priority macro-F1 at 0.5 on P(HIGH))."""
    from complaintiq.eval import metrics

    if task == "priority":
        p_high = prob[:, labels.index(HIGH)]
        pred = np.where(p_high >= 0.5, HIGH, "NORMAL")
        m = metrics.compute_metrics(y_true, pred, labels)
        pm = metrics.priority_metrics((y_true == HIGH).astype(int), p_high, threshold=0.5)
        return {
            "val_macro_f1": m["macro_f1"],
            "val_macro_f1_all_labels": m["macro_f1_all_labels"],
            "val_weighted_f1": m["weighted_f1"],
            "val_pr_auc": pm["pr_auc"],
        }
    pred = np.asarray(labels)[prob.argmax(axis=1)]
    m = metrics.compute_metrics(y_true, pred, labels, y_score=prob)
    return {
        "val_macro_f1": m["macro_f1"],
        "val_macro_f1_all_labels": m["macro_f1_all_labels"],
        "val_weighted_f1": m["weighted_f1"],
        "val_top3": m["top3"],
    }


# --------------------------------------------------------------------------- training


def train_task(
    task: str,
    cfg: dict[str, Any],
    max_train: int | None = None,
    max_val: int | None = None,
    epochs: int | None = None,
    seed: int | None = None,
    notes: str = "",
) -> str:
    """Fine-tune one task, log the run and save the best checkpoint. Returns the run_id."""
    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        get_linear_schedule_with_warmup,
    )

    from complaintiq.data.training_data import (
        LABEL_COLS,
        class_priors,
        data_version,
        load_split,
        sample_train,
    )
    from complaintiq.eval.tracking import log_run

    dv = data_version()  # fail fast if a split file is missing (all three are hashed)
    seed = int(seed if seed is not None else cfg["seeds"][0])
    epochs = int(epochs if epochs is not None else cfg["epochs"])
    set_seed(seed)
    device = select_device()
    col = LABEL_COLS[task]
    n_train = max_train if max_train is not None else cfg["train_rows"]

    train_df = sample_train(
        load_split("train", columns=[TEXT_COL, col]), col,
        cap_per_class=cfg.get("cap_per_class"), max_rows=n_train, seed=seed,
    )
    val_all = load_split("val", columns=[TEXT_COL, col])
    es_rows = max_val if max_val is not None else cfg["early_stop_val_rows"]
    val_es = sample_train(val_all, col, max_rows=es_rows, seed=seed)
    val_final = val_all if (cfg["final_eval_full_val"] and max_val is None) else val_es

    label2id, id2label = build_label_maps(train_df[col].to_list())
    labels = [id2label[i] for i in range(len(id2label))]
    priors_map = class_priors(train_df, col)
    train_priors = np.array([priors_map[lbl] for lbl in labels])
    y_train = np.array([label2id[v] for v in train_df[col].to_list()])

    tok = AutoTokenizer.from_pretrained(cfg["name"])
    pad_id = tok.pad_token_id or 0
    t0 = time.perf_counter()
    x_train = encode(tok, train_df[TEXT_COL].to_list(), cfg["max_len"], cfg["head_tokens"])
    x_es = encode(tok, val_es[TEXT_COL].to_list(), cfg["max_len"], cfg["head_tokens"])
    logger.info("task=%s device=%s train=%d val_es=%d", task, device, len(x_train), len(x_es))

    model = AutoModelForSequenceClassification.from_pretrained(
        cfg["name"], num_labels=len(labels), id2label=id2label, label2id=label2id
    ).to(device)
    weight = (
        torch.tensor(balanced_class_weights(y_train, len(labels)), dtype=torch.float32)
        if cfg["class_weighted_loss"] else None
    )
    loss_fn = torch.nn.CrossEntropyLoss(weight=weight.to(device) if weight is not None else None)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    steps = epochs * ((len(x_train) + cfg["batch_size"] - 1) // cfg["batch_size"])
    sched = get_linear_schedule_with_warmup(opt, int(cfg["warmup_ratio"] * steps), steps)
    use_amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    rng = np.random.default_rng(seed)

    out_dir = resolve(cfg["artifacts_dir"]) / task
    best, best_epoch, bad = -1.0, 0, 0
    history: list[dict[str, float]] = []
    for epoch in range(1, epochs + 1):
        model.train()
        order = rng.permutation(len(x_train))
        for idx, ids, mask in _batches(x_train, cfg["batch_size"], pad_id, order):
            target = torch.tensor(y_train[idx], device=device)
            with torch.autocast("cuda", dtype=torch.float16, enabled=use_amp):
                logits = model(input_ids=ids.to(device), attention_mask=mask.to(device)).logits
            loss = loss_fn(logits.float(), target)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["grad_clip"])
            scaler.step(opt)
            scaler.update()
            sched.step()
        prob = _probs(predict_logits(model, x_es, cfg["eval_batch_size"], pad_id, device),
                      train_priors, cfg["prior_correction"])
        f1 = score_task(task, val_es[col].to_numpy(), labels, prob)["val_macro_f1"]
        history.append({"epoch": epoch, "val_es_macro_f1": f1})
        logger.info("task=%s epoch=%d early-stop val macro-F1=%.4f", task, epoch, f1)
        if f1 > best:
            best, best_epoch, bad = f1, epoch, 0
            model.save_pretrained(out_dir)
            tok.save_pretrained(out_dir)
        else:
            bad += 1
            if bad > cfg["patience"]:
                break
    train_seconds = time.perf_counter() - t0

    model = AutoModelForSequenceClassification.from_pretrained(out_dir).to(device)
    x_final = x_es if val_final is val_es else encode(
        tok, val_final[TEXT_COL].to_list(), cfg["max_len"], cfg["head_tokens"]
    )
    prob = _probs(predict_logits(model, x_final, cfg["eval_batch_size"], pad_id, device),
                  train_priors, cfg["prior_correction"])
    m = score_task(task, val_final[col].to_numpy(), labels, prob)
    hp = {k: v for k, v in cfg.items() if k != "smoke"}
    hp.update(epochs=epochs, best_epoch=best_epoch, history=history, device=device,
              n_val_scored=val_final.height, n_val_early_stop=val_es.height)
    run_id = log_run(
        cfg["experiment_log"], data_version=dv, model=f"transformer/{cfg['name']}",
        task=col, hyperparams=hp, seed=seed, n_train=train_df.height,
        train_seconds=round(train_seconds, 1), owner=OWNER,
        notes=(f"{notes} val rows scored={val_final.height}; argmax, priority at 0.5").strip(),
        **m,
    )
    meta = {
        "task": task, "labels": labels, "train_priors": train_priors.tolist(),
        "prior_correction": cfg["prior_correction"], "max_len": cfg["max_len"],
        "head_tokens": cfg["head_tokens"], "priority_threshold": 0.5, "run_id": run_id,
        "data_version": dv, "model_version": f"transformer-{cfg['name']}-{dv}",
        "n_train": train_df.height,
    }
    (out_dir / "ciq_meta.json").write_text(json.dumps(meta, indent=2))
    logger.info("task=%s logged run %s %s", task, run_id, m)
    return run_id


def _probs(logits: np.ndarray, train_priors: np.ndarray, correct: bool) -> np.ndarray:
    return softmax(prior_correction(logits, train_priors) if correct else logits)


def evaluate(cfg: dict[str, Any], tasks: Sequence[str], max_val: int | None,
             prior_corr: bool, smoke: bool = False) -> dict[str, str]:
    """Re-score saved checkpoints on val (optionally with prior correction) and log rows."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from complaintiq.data.training_data import LABEL_COLS, data_version, load_split, sample_train
    from complaintiq.eval.tracking import log_run, read_runs

    device = select_device()
    logged = {r["run_id"]: r for r in read_runs()}
    ids: dict[str, str] = {}
    for task in tasks:
        d = resolve(cfg["artifacts_dir"]) / task
        meta = json.loads((d / "ciq_meta.json").read_text())
        col = LABEL_COLS[task]
        val = load_split("val", columns=[TEXT_COL, col])
        if max_val is not None:
            val = sample_train(val, col, max_rows=max_val, seed=int(cfg["seeds"][0]))
        tok = AutoTokenizer.from_pretrained(d)
        model = AutoModelForSequenceClassification.from_pretrained(d).to(device)
        x = encode(tok, val[TEXT_COL].to_list(), meta["max_len"], meta["head_tokens"])
        logits = predict_logits(model, x, cfg["eval_batch_size"], tok.pad_token_id or 0, device)
        prob = _probs(logits, np.array(meta["train_priors"]), prior_corr)
        m = score_task(task, val[col].to_numpy(), meta["labels"], prob)
        ids[task] = log_run(
            cfg["experiment_log"], data_version=data_version(),
            model=f"transformer/{cfg['name']}" + ("+prior_correction" if prior_corr else ""),
            task=col, n_train=meta.get("n_train") or logged.get(meta["run_id"], {}).get("n_train"),
            # A prior-corrected eval is a different scoring rule, so it never supersedes.
            hyperparams={
                ("eval_of_run" if prior_corr else "rescore_of"): meta["run_id"],
                "prior_correction": prior_corr,
            },
            seed=int(cfg["seeds"][0]), owner=OWNER,
            notes=(
                f"rescored: fixed label set; rescore of {meta['run_id']}; no retraining;"
                f" val rows scored={val.height}" + ("; smoke" if smoke else "")
            ),
            **m,
        )
    return ids


# --------------------------------------------------------------------------- serving


class TransformerPredictor:
    """Serving ``Predictor`` over three fine-tuned checkpoints (product, issue, priority)."""

    def __init__(self, model_dir: str | Path) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.device = select_device()
        self.parts: dict[str, tuple[Any, Any, dict[str, Any]]] = {}
        for task in ("product", "issue", "priority"):
            d = Path(model_dir) / task
            meta = json.loads((d / "ciq_meta.json").read_text())
            model = AutoModelForSequenceClassification.from_pretrained(d).to(self.device)
            self.parts[task] = (AutoTokenizer.from_pretrained(d), model, meta)

    @property
    def model_version(self) -> str:
        return str(self.parts["product"][2]["model_version"])

    def _prob(self, task: str, text: str) -> tuple[list[str], np.ndarray]:
        tok, model, meta = self.parts[task]
        x = encode(tok, [text], meta["max_len"], meta["head_tokens"])
        logits = predict_logits(model, x, 1, tok.pad_token_id or 0, self.device)
        prob = _probs(logits, np.array(meta["train_priors"]), meta["prior_correction"])
        return meta["labels"], prob[0]

    def predict(self, text: str) -> Prediction:
        p_labels, p = self._prob("product", text)
        i_labels, i = self._prob("issue", text)
        r_labels, r = self._prob("priority", text)
        top = int(np.argmax(p))
        high = float(r[r_labels.index(HIGH)])
        thr = float(self.parts["priority"][2].get("priority_threshold", 0.5))
        return Prediction(
            product=p_labels[top],
            product_confidence=float(p[top]),
            issue_top3=[(i_labels[j], float(i[j])) for j in np.argsort(-i)[:3]],
            priority=HIGH if high >= thr else "NORMAL",
            priority_score=high,
        )


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> None:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = load_transformer_config()
    ap = argparse.ArgumentParser(prog="python -m complaintiq.models.transformer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("train", "eval"):
        p = sub.add_parser(name)
        p.add_argument("--tasks", default=",".join(cfg["tasks"]))
        p.add_argument("--max-val", type=int, default=None)
        p.add_argument("--smoke", action="store_true", help="CPU-sized run (configs smoke:)")
        p.add_argument("--prior-correction", action="store_true")
        p.add_argument("--notes", default="")
        if name == "train":
            p.add_argument("--max-train", type=int, default=None)
            p.add_argument("--epochs", type=int, default=None)
            p.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    if args.prior_correction:
        cfg["prior_correction"] = True
    tasks = args.tasks.split(",")
    smoke = cfg["smoke"] if args.smoke else {}
    max_val = args.max_val if args.max_val is not None else smoke.get("max_val")

    if args.cmd == "train":
        notes = ("smoke; " if args.smoke else "") + args.notes
        ids = {
            t: train_task(
                t, cfg,
                max_train=args.max_train if args.max_train is not None else smoke.get("max_train"),
                max_val=max_val,
                epochs=args.epochs if args.epochs is not None else smoke.get("epochs"),
                seed=args.seed, notes=notes,
            )
            for t in tasks
        }
    else:
        ids = evaluate(cfg, tasks, max_val, cfg["prior_correction"], smoke=args.smoke)
    print(json.dumps(ids, indent=2))


if __name__ == "__main__":
    main()
