"""
Cost anomaly detection — Module 6.

Catches "the runaway loop that only shows up on the invoice": a bug (e.g.
a delegation loop, a retry storm) that burns cost well above normal
without ever throwing an error. A fixed dollar threshold doesn't work
across teams/features with very different normal spend, so this compares
a rolling recent mean against a frozen baseline mean instead — the same
baseline/rolling-window pattern used by drift.py.
"""

import os
from collections import deque
from pathlib import Path

from dotenv import load_dotenv

from src.core import metrics

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BASELINE_SIZE = int(os.environ.get("NIYANTRAN_COST_BASELINE_SIZE", "15"))
ROLLING_WINDOW = int(os.environ.get("NIYANTRAN_COST_ROLLING_WINDOW", "8"))
SPIKE_MULTIPLIER = float(os.environ.get("NIYANTRAN_COST_SPIKE_MULTIPLIER", "3.0"))

_baseline: list[float] = []
_rolling: deque = deque(maxlen=ROLLING_WINDOW)
_anomalies: list[dict] = []


def observe_cost(cost_usd: float, context: str = "") -> dict:
    """Call once per finished request with its total cost. Returns a status dict."""
    if len(_baseline) < BASELINE_SIZE:
        _baseline.append(cost_usd)
        return {"baseline_ready": False, "baseline_size": len(_baseline), "flagged": False}

    _rolling.append(cost_usd)
    baseline_mean = sum(_baseline) / len(_baseline)
    rolling_mean = sum(_rolling) / len(_rolling)

    flagged = len(_rolling) >= ROLLING_WINDOW and baseline_mean > 0 and rolling_mean >= baseline_mean * SPIKE_MULTIPLIER
    result = {
        "baseline_ready": True,
        "baseline_mean_usd": round(baseline_mean, 6),
        "rolling_mean_usd": round(rolling_mean, 6),
        "ratio": round(rolling_mean / baseline_mean, 2) if baseline_mean > 0 else None,
        "flagged": flagged,
    }
    if flagged:
        _anomalies.append({"context": context, **result})
        metrics.record_cost_anomaly()
    return result


def recent_anomalies() -> list[dict]:
    return list(_anomalies[-20:])


def reset() -> None:
    _baseline.clear()
    _rolling.clear()
    _anomalies.clear()
