"""Pure-function tests for complaintiq.models.transformer (no torch, downloads or training)."""

import numpy as np
import pytest

from complaintiq.models import transformer as tr


def test_head_tail_truncate() -> None:
    ids = list(range(10))
    assert tr.head_tail_truncate(ids, 3, 2) == [0, 1, 2, 8, 9]
    assert tr.head_tail_truncate(ids, 6, 6) == ids
    assert tr.head_tail_truncate(ids, 4, 0) == [0, 1, 2, 3]


def test_content_budget_fits_max_len() -> None:
    head, tail = tr.content_budget(256, 128)
    assert (head, tail) == (128, 126)
    assert head + tail + 2 == 256
    assert tr.content_budget(64, 128) == (62, 0)


def test_encode_adds_specials_and_truncates() -> None:
    class FakeTok:
        cls_token_id, sep_token_id, bos_token_id, eos_token_id = 101, 102, None, None

        def __call__(self, texts, add_special_tokens, truncation):
            return {"input_ids": [list(range(len(t))) for t in texts]}

    out = tr.encode(FakeTok(), ["x" * 300, "abc"], max_len=10, head_tokens=4)
    assert out[0] == [101, 0, 1, 2, 3, 296, 297, 298, 299, 102]
    assert out[1] == [101, 0, 1, 2, 102]


def test_label_maps_are_sorted_and_inverse() -> None:
    l2i, i2l = tr.build_label_maps(["b", "a", "c", "a"])
    assert l2i == {"a": 0, "b": 1, "c": 2}
    assert all(i2l[i] == lbl for lbl, i in l2i.items())


def test_balanced_class_weights() -> None:
    w = tr.balanced_class_weights([0, 0, 0, 1], 3)
    assert w[0] == pytest.approx(4 / (2 * 3))
    assert w[1] == pytest.approx(4 / (2 * 1))
    assert w[2] == 0.0


def test_prior_correction() -> None:
    logits = np.log(np.array([[0.9, 0.1]]))
    priors = np.array([0.9, 0.1])
    adj = tr.softmax(tr.prior_correction(logits, priors))
    assert adj[0] == pytest.approx([0.5, 0.5])
    to_target = tr.softmax(tr.prior_correction(logits, priors, np.array([0.5, 0.5])))
    assert to_target[0] == pytest.approx([0.5, 0.5])
    assert tr.softmax(np.array([[1.0, 1.0, 1.0]]))[0] == pytest.approx([1 / 3] * 3)


def test_config_has_required_keys() -> None:
    cfg = tr.load_transformer_config()
    for key in ("name", "max_len", "head_tokens", "tail_tokens", "epochs", "seeds", "tasks",
                "train_rows", "prior_correction", "smoke"):
        assert key in cfg
    assert cfg["tasks"][0] == "issue"
    assert 100_000 <= cfg["train_rows"] <= 200_000
