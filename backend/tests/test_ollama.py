"""Robustheit gegenueber typischen Modell-Antworten."""

from __future__ import annotations

import pytest

from app.ollama import OllamaError, classify_fit, extract_json


def test_extract_plain_json():
    assert extract_json('{"verdict": "ok"}') == {"verdict": "ok"}


def test_extract_from_code_fence():
    raw = (
        'Hier mein Ergebnis:\n```json\n'
        '{"verdict": "rejected", "confidence": 0.8}\n```\nViel Erfolg!'
    )
    assert extract_json(raw)["verdict"] == "rejected"


def test_extract_with_surrounding_prose():
    raw = 'Nach Prüfung des Inserats: {"verdict": "ok", "findings": []} - das war es.'
    assert extract_json(raw)["findings"] == []


def test_extract_rejects_garbage():
    with pytest.raises(OllamaError):
        extract_json("Ich kann das leider nicht beurteilen.")


def test_extract_rejects_empty():
    with pytest.raises(OllamaError):
        extract_json("")


@pytest.mark.parametrize(
    ("gib", "expected"),
    [(8, "single_gpu"), (13, "single_gpu"), (20, "tensor_split"), (60, "too_large")],
)
def test_vram_fit_classification(gib, expected):
    """16 GB je V100 - darueber wird Tensor-Split noetig."""
    assert classify_fit(gib * 1024**3) == expected


def test_vram_fit_unknown_without_size():
    assert classify_fit(None) == "unknown"
