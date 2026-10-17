"""The published numbers replay from the committed caches, with no key and no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation_finder.evaluate import run_seed
from automation_finder.similarity import GeminiEmbedder, TfidfEmbedder

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "results" / "eval.json"


@pytest.mark.skipif(not EVAL.exists(), reason="no stored evaluation")
def test_seed_one_reproduces_the_stored_evaluation(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    stored = json.loads(EVAL.read_text())["per_seed"][0]
    embedders = [TfidfEmbedder(), GeminiEmbedder(ROOT / "eval-cache" / "embeddings", "replay")]
    fresh = run_seed(stored["seed"], embedders, tmp_path)
    for method in ("tfidf", "gemini", "keyword_baseline", "repeat_baseline"):
        assert fresh[method] == stored[method], method
