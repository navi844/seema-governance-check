"""Narrative + tool-mix drift detection. Inherited base (M5)."""

import os
import math
from collections import deque, Counter

from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_FILE)

BASELINE_SIZE = int(os.environ.get("NIYANTRAN_DRIFT_BASELINE_SIZE", "8"))
WINDOW = int(os.environ.get("NIYANTRAN_DRIFT_WINDOW", "15"))
EMBEDDING_DRIFT_THRESHOLD = float(os.environ.get("NIYANTRAN_DRIFT_THRESHOLD", "0.08"))
TOOL_MIX_THRESHOLD = float(os.environ.get("NIYANTRAN_TOOL_MIX_THRESHOLD", "0.35"))

_baseline_embeddings: list[list[float]] = []
_baseline_tool_counts: Counter = Counter()
_rolling_embeddings: deque = deque(maxlen=WINDOW)
_rolling_tool_counts: deque = deque(maxlen=WINDOW)
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


def _embed(text: str) -> list[float]:
    resp = _get_client().embeddings.create(model="text-embedding-3-small", input=text[:2000])
    return resp.data[0].embedding


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - (dot / (norm_a * norm_b))


def _centroid(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(len(vectors[0]))]


def _total_variation_distance(a: Counter, b: Counter) -> float:
    keys = set(a) | set(b)
    total_a, total_b = sum(a.values()) or 1, sum(b.values()) or 1
    return 0.5 * sum(abs(a.get(k, 0) / total_a - b.get(k, 0) / total_b) for k in keys)


def observe(narrative: str, tool_sequence: list[str]) -> dict:
    embedding = _embed(narrative)
    if len(_baseline_embeddings) < BASELINE_SIZE:
        _baseline_embeddings.append(embedding)
        _baseline_tool_counts.update(tool_sequence)
        return {"baseline_ready": False, "baseline_size": len(_baseline_embeddings)}

    _rolling_embeddings.append(embedding)
    _rolling_tool_counts.append(tool_sequence)

    centroid = _centroid(_baseline_embeddings)
    narrative_drift = _cosine_distance(embedding, centroid)

    rolling_tools: Counter = Counter()
    for seq in _rolling_tool_counts:
        rolling_tools.update(seq)
    tool_mix_drift = _total_variation_distance(_baseline_tool_counts, rolling_tools)

    return {
        "baseline_ready": True,
        "narrative_drift_score": round(narrative_drift, 4),
        "narrative_drift_flagged": narrative_drift >= EMBEDDING_DRIFT_THRESHOLD,
        "tool_mix_drift_score": round(tool_mix_drift, 4),
        "tool_mix_drift_flagged": tool_mix_drift >= TOOL_MIX_THRESHOLD,
    }


def status() -> dict:
    return {
        "baseline_ready": len(_baseline_embeddings) >= BASELINE_SIZE,
        "baseline_size": len(_baseline_embeddings),
        "baseline_target": BASELINE_SIZE,
        "rolling_window_size": len(_rolling_embeddings),
    }


def reset_baseline() -> None:
    _baseline_embeddings.clear()
    _baseline_tool_counts.clear()
    _rolling_embeddings.clear()
    _rolling_tool_counts.clear()
