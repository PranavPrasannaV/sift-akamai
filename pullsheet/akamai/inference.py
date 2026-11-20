"""One OpenAI-compatible client for Akamai Inference, read from the environment
lazily so importing this module never needs a key.

AKAMAI_BASE_URL, AKAMAI_API_KEY, CHAT_MODEL, EMBEDDING_MODEL, VISION_MODEL.
"""

from __future__ import annotations

import os
import re
import time
from functools import lru_cache

MAX_EMBED_CHARS = 400
EMBED_BATCH = 32
RETRIES = 6


@lru_cache(maxsize=1)
def client():
    from openai import OpenAI

    return OpenAI(base_url=os.environ["AKAMAI_BASE_URL"], api_key=os.environ["AKAMAI_API_KEY"],
                  timeout=120, max_retries=0)


def configured() -> bool:
    return bool(os.environ.get("AKAMAI_BASE_URL") and os.environ.get("AKAMAI_API_KEY"))


def _with_retry(call):
    """The event key shares a per-minute token budget, so 429 is routine. Back off."""
    from openai import APIConnectionError, APITimeoutError, RateLimitError, InternalServerError

    delay = 4.0
    for attempt in range(RETRIES):
        try:
            return call()
        except (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError):
            if attempt == RETRIES - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60)


def embed(texts: list[str]) -> list[list[float]]:
    model = os.environ.get("EMBEDDING_MODEL", "qwen3-embedding-8b")
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = [(t or " ")[:MAX_EMBED_CHARS] for t in texts[i:i + EMBED_BATCH]]
        resp = _with_retry(lambda: client().embeddings.create(model=model, input=batch))
        out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return out


_THINK = re.compile(r"<think>.*?</think>", re.S)


def strip_think(text: str) -> str:
    text = _THINK.sub("", text or "")
    if "</think>" in text:            # an opening tag the server already removed
        text = text.split("</think>", 1)[1]
    return text.strip()


def chat(system: str, user: str, max_tokens: int = 900, model: str | None = None,
         temperature: float = 0.2) -> str:
    model = model or os.environ.get("CHAT_MODEL", "qwen3-8-27b")
    resp = _with_retry(lambda: client().chat.completions.create(
        model=model, temperature=temperature, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    ))
    return strip_think(resp.choices[0].message.content or "")


def vision(prompt: str, image_data_url: str, max_tokens: int = 500) -> str:
    model = os.environ.get("VISION_MODEL", "gemma-4-26b-a4b-it")
    resp = _with_retry(lambda: client().chat.completions.create(
        model=model, temperature=0, max_tokens=max_tokens,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]}],
    ))
    return strip_think(resp.choices[0].message.content or "")
