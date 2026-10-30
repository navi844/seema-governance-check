"""
Redis-backed response caching — Module 6.

Caches the FINAL raw model response for a given (model, normalized prompt)
pair. Normalization matters more than the cache mechanism: hashing the raw
message list verbatim gives a near-0% hit rate in practice, because two
"identical" questions almost never arrive as byte-identical text (different
casing, whitespace, punctuation). This cache normalizes before hashing.

Falls back to an in-process dict if Redis isn't reachable, so the lab still
runs without a live Redis container — but the cache-hit-rate metric will
read differently, and that's worth noticing (see the observation
questions).
"""

import hashlib
import json
import os
import re
import time
from typing import Optional

try:
    import redis
    _redis_client: Optional["redis.Redis"] = None
except ImportError:  # pragma: no cover
    redis = None
    _redis_client = None

_FALLBACK_STORE: dict[str, tuple[float, str]] = {}
CACHE_TTL_SECONDS = int(os.environ.get("NIYANTRAN_CACHE_TTL_SECONDS", "3600"))


def _get_redis():
    global _redis_client
    if redis is None:
        return None
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            _redis_client = redis.from_url(url, socket_connect_timeout=1)
            _redis_client.ping()
        except Exception:
            _redis_client = None
    return _redis_client


def normalize_question(text: str) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation — the step
    that makes 'What is the EAR?' and 'what is the ear' hash identically."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[?.!]+$", "", text)
    return text


def cache_key(model: str, question: str) -> str:
    normalized = normalize_question(question)
    digest = hashlib.sha256(f"{model}:{normalized}".encode()).hexdigest()[:24]
    return f"niyantran:cache:{digest}"


def get_cached(model: str, question: str) -> Optional[str]:
    key = cache_key(model, question)
    client = _get_redis()
    if client is not None:
        value = client.get(key)
        return value.decode() if value else None
    entry = _FALLBACK_STORE.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        _FALLBACK_STORE.pop(key, None)
        return None
    return value


def set_cached(model: str, question: str, answer: str) -> None:
    key = cache_key(model, question)
    client = _get_redis()
    if client is not None:
        client.setex(key, CACHE_TTL_SECONDS, answer)
        return
    _FALLBACK_STORE[key] = (time.time() + CACHE_TTL_SECONDS, answer)


def cache_backend() -> str:
    return "redis" if _get_redis() is not None else "in_process_fallback"
