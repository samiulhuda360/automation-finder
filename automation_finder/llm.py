"""A small client for an OpenAI-compatible chat API (Gemini by default) with a replay cache.

Modes:
- off: never called; callers use their rule-based answer;
- replay (default): answers come only from eval-cache/llm; a miss is reported, not sent;
- live: a miss is sent to the API (AI_API_KEY), spaced by AI_MIN_INTERVAL seconds, and stored.

Every stored answer is keyed by a hash of the model and the full request, so CI replays the exact runs behind the
published numbers without a key.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-flash-lite-latest"


class RateLimited(RuntimeError):
    pass


class CacheMiss(RuntimeError):
    pass


class ChatClient:
    def __init__(self, cache_dir: Path, mode: str = "replay", model: str | None = None) -> None:
        self.cache_dir = cache_dir
        self.mode = mode
        self.model = model or os.environ.get("AI_MODEL", DEFAULT_MODEL)
        self.min_interval = float(os.environ.get("AI_MIN_INTERVAL", "4.5"))
        self.calls = 0
        self.hits = 0
        self._last = 0.0

    def _key(self, messages: list[dict[str, str]]) -> str:
        blob = json.dumps({"model": self.model, "messages": messages}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def json_chat(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Returns the model's JSON answer (parsed), from the cache when possible."""
        if self.mode == "off":
            raise CacheMiss("model switched off")
        path = self.cache_dir / f"{self._key(messages)}.json"
        if path.exists():
            self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["answer"]  # type: ignore[no-any-return]
        if self.mode != "live":
            raise CacheMiss("no stored answer for this request (run with --live and AI_API_KEY to fetch it)")
        key = os.environ.get("AI_API_KEY", "")
        if not key:
            raise CacheMiss("AI_API_KEY is not set")
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        resp = httpx.post(
            f"{os.environ.get('AI_BASE_URL', DEFAULT_BASE)}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        self._last = time.monotonic()
        self.calls += 1
        if resp.status_code == 429:
            raise RateLimited("model API rate limit (429)")
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        answer = json.loads(_strip_fences(content))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"model": self.model, "answer": answer}, indent=1), encoding="utf-8")
        return answer  # type: ignore[no-any-return]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text
