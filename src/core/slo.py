"""
Service level objectives and error budgets — Module 7.

An SLI has to be a number something can actually compute from telemetry
already being captured. "The agent is helpful" is not an SLI; "percentage
of sampled turns scoring >= 4/5 on the calibrated judge, over a rolling
30-request window" is. Three SLOs are defined here, each backed by a
signal this repo already has wired up elsewhere (online_eval.py,
cost_anomaly.py, drift.py) — Module 7 adds nothing new to MEASURE, only
the objective/error-budget layer on top of what Modules 4-6 already
measure.
"""

from collections import deque
from dataclasses import dataclass, field

from src.core import metrics

ROLLING_WINDOW = 30

SLO_DEFINITIONS = {
    "answer_quality": {
        "description": "Sampled investigation turns scoring >= 4/5 on the calibrated online-eval judge",
        "target_pct": 95.0,  # 95% of judged turns should score >= 4
        "signal_source": "online_eval.py's recent_judged()",
    },
    "cost_stability": {
        "description": "Requests NOT flagged by cost-anomaly detection (no runaway-cost spike)",
        "target_pct": 99.0,
        "signal_source": "cost_anomaly.py's observe_cost()",
    },
    "narrative_integrity": {
        "description": "SAR narratives NOT flagged by drift detection (no silent narrative-quality drift)",
        "target_pct": 98.0,
        "signal_source": "drift.py's observe()",
    },
    "capacity_headroom": {
        "description": "Incoming external request rate stays within the Seema governor limit and retains headroom",
        "target_pct": 90.0,
        "signal_source": "src/core/seema.py request window / governor state",
    },
}

_windows: dict[str, deque] = {name: deque(maxlen=ROLLING_WINDOW) for name in SLO_DEFINITIONS}


def record_outcome(slo_name: str, met: bool) -> None:
    """Call this once per relevant event — e.g. after every judged turn for
    'answer_quality', after every cost_anomaly.observe_cost() call for
    'cost_stability'."""
    if slo_name not in _windows:
        raise ValueError(f"Unknown SLO '{slo_name}'. Known: {list(SLO_DEFINITIONS)}")
    _windows[slo_name].append(met)
    if not met:
        metrics.record_slo_breach(slo_name)


def slo_status(slo_name: str) -> dict:
    definition = SLO_DEFINITIONS.get(slo_name)
    if definition is None:
        return {"error": f"Unknown SLO '{slo_name}'"}
    window = _windows[slo_name]
    if not window:
        return {**definition, "name": slo_name, "sample_size": 0, "current_pct": None,
                "error_budget_remaining_pct": None, "slo_met": None}

    met_count = sum(1 for x in window if x)
    current_pct = round(100.0 * met_count / len(window), 2)
    target_pct = definition["target_pct"]
    # Error budget: how much room is left between current performance and the target.
    error_budget_remaining_pct = round(current_pct - target_pct, 2)
    return {
        **definition,
        "name": slo_name,
        "sample_size": len(window),
        "current_pct": current_pct,
        "target_pct": target_pct,
        "error_budget_remaining_pct": error_budget_remaining_pct,
        "slo_met": current_pct >= target_pct,
    }


def all_slo_status() -> list[dict]:
    return [slo_status(name) for name in SLO_DEFINITIONS]


def reset(slo_name: str = None) -> None:
    if slo_name:
        _windows[slo_name].clear()
    else:
        for w in _windows.values():
            w.clear()
