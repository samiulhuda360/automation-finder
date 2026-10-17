"""Groups texts that mean the same thing, so repeats of one chore share one key.

Two ways to turn text into vectors:
- `tfidf` (default, no model, no network): word and character n-gram TF-IDF. Good at templated text such as
  "Invoice INV-123 from X"; weaker when people word the same request differently.
- `gemini`: an embedding model through the OpenAI-compatible API, which also groups paraphrases
  ("Can we move Thursday's booking?" / "Need a different day for the job"). Every vector is cached on disk by a
  hash of the masked text, so later runs and CI replay without calling the API.

Texts are masked first (see events.mask), so ids, amounts, dates and names never reach the model.
Grouping is average-linkage agglomerative clustering on cosine distance with a distance cut-off.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np
from scipy.sparse import hstack
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIMS = 256
# Cosine-distance cut-offs, tuned on the development seed (0) only; the evaluation reports seeds 1-5.
THRESHOLDS = {"tfidf": 0.70, "gemini": 0.20}


class Embedder(Protocol):
    name: str

    def vectors(self, texts: list[str]) -> np.ndarray: ...


class TfidfEmbedder:
    name = "tfidf"

    def vectors(self, texts: list[str]) -> np.ndarray:
        if len(texts) == 1:
            return np.ones((1, 1))
        words = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True, min_df=1)
        chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)
        try:
            w = words.fit_transform(texts)
        except ValueError:  # every text was a stop word
            w = None
        c = chars.fit_transform(texts)
        x = hstack([w, c]) if w is not None else c
        return np.asarray(normalize(x).todense())


class EmbeddingCache:
    """Vectors stored as float16, keyed by sha256(model + text). One JSON file per model."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
        self.dirty = False

    @staticmethod
    def key(model: str, text: str) -> str:
        return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()[:24]

    def get(self, model: str, text: str) -> np.ndarray | None:
        raw = self.data.get(self.key(model, text))
        if raw is None:
            return None
        return np.frombuffer(base64.b64decode(raw), dtype=np.float16).astype(np.float32)

    def put(self, model: str, text: str, vec: np.ndarray) -> None:
        self.data[self.key(model, text)] = base64.b64encode(vec.astype(np.float16).tobytes()).decode()
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, sort_keys=True, separators=(",", ":")))
            self.dirty = False


class GeminiEmbedder:
    """Embeddings through the OpenAI-compatible endpoint. mode: replay (cache only), live (call on a miss)."""

    name = "gemini"

    def __init__(self, cache_dir: Path, mode: str = "replay", batch: int = 80) -> None:
        self.cache = EmbeddingCache(cache_dir / f"{EMBED_MODEL}-{EMBED_DIMS}.json")
        self.mode = mode
        self.batch = batch
        self.calls = 0
        # The free tier counts each text in a batch against a per-minute quota, so batches are a minute apart.
        self.min_interval = float(os.environ.get("EMBED_MIN_INTERVAL", "62"))
        self._last = 0.0

    def _fetch(self, texts: list[str]) -> list[list[float]]:
        key = os.environ.get("AI_API_KEY", "")
        if not key:
            raise RuntimeError("AI_API_KEY is not set (needed for --embed gemini in live mode)")
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        base = os.environ.get("AI_BASE_URL", GEMINI_BASE)
        for attempt in range(3):
            resp = httpx.post(
                f"{base}/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": EMBED_MODEL, "input": texts, "dimensions": EMBED_DIMS},
                timeout=120,
            )
            self._last = time.monotonic()
            self.calls += 1
            if resp.status_code != 429:
                break
            if attempt == 2:
                raise RuntimeError("embedding API rate limit (429); cached vectors are kept, rerun later to resume")
            time.sleep(self.min_interval)
        resp.raise_for_status()
        data = resp.json()["data"]
        return [d["embedding"] for _, d in sorted(enumerate(data), key=lambda p: p[1].get("index", p[0]))]

    def vectors(self, texts: list[str]) -> np.ndarray:
        missing = [t for t in dict.fromkeys(texts) if self.cache.get(EMBED_MODEL, t) is None]
        if missing and self.mode != "live":
            raise RuntimeError(f"{len(missing)} texts have no cached embedding; run with --live and AI_API_KEY")
        try:
            for i in range(0, len(missing), self.batch):
                chunk = missing[i : i + self.batch]
                for text, vec in zip(chunk, self._fetch(chunk), strict=True):
                    self.cache.put(EMBED_MODEL, text, np.asarray(vec, dtype=np.float32))
        finally:
            self.cache.save()
        out = np.vstack([self.cache.get(EMBED_MODEL, t) for t in texts])  # type: ignore[misc]
        return np.asarray(normalize(out))


def cluster(texts: list[str], embedder: Embedder, threshold: float | None = None) -> list[int]:
    """Cluster label per text. Identical texts always share a label."""
    unique = list(dict.fromkeys(texts))
    if len(unique) == 1:
        return [0] * len(texts)
    vecs = embedder.vectors(unique)
    dist = np.clip(1.0 - vecs @ vecs.T, 0.0, 2.0)
    np.fill_diagonal(dist, 0.0)
    model = AgglomerativeClustering(
        n_clusters=None,
        metric="precomputed",
        linkage="average",
        distance_threshold=threshold if threshold is not None else THRESHOLDS.get(embedder.name, 0.5),
    )
    labels = model.fit_predict(dist)
    by_text = dict(zip(unique, labels, strict=True))
    return [int(by_text[t]) for t in texts]
