"""
OTel metric instruments — the aggregate layer under the Grafana dashboard.
Inherited base (M4); Module 6 adds cost-attribution and cache-hit-rate
instruments alongside it.
"""

from src.core.otel_setup import get_meter

_meter = get_meter("niyantran.metrics")

request_counter = _meter.create_counter("niyantran.requests.total", description="Total finished investigation turns")
duration_histogram = _meter.create_histogram("niyantran.request.duration_ms", unit="ms")
cost_histogram = _meter.create_histogram("niyantran.request.cost_usd", unit="usd")
cache_hit_counter = _meter.create_counter("niyantran.cache.hits.total")
cache_miss_counter = _meter.create_counter("niyantran.cache.misses.total")
routing_tier_counter = _meter.create_counter("niyantran.routing.tier.total")
eval_score_histogram = _meter.create_histogram("niyantran.eval.score")
drift_score_histogram = _meter.create_histogram("niyantran.drift.score")
cost_anomaly_counter = _meter.create_counter("niyantran.cost.anomaly.total")
slo_breach_counter = _meter.create_counter("niyantran.slo.breach.total")
# --- Seema capacity governor (M6/M7) ---
seema_request_count_histogram = _meter.create_histogram("niyantran.seema.request_count")
seema_request_limit_histogram = _meter.create_histogram("niyantran.seema.request_limit")
seema_headroom_histogram = _meter.create_histogram("niyantran.seema.capacity_headroom_pct")
seema_active_counter = _meter.create_counter("niyantran.seema.active.total")
seema_decision_counter = _meter.create_counter("niyantran.seema.decision.total")


def record_investigation_turn(model: str, duration_ms: float, cost_usd: float,
                               cache_hit: bool, routing_tier: str) -> None:
    request_counter.add(1, {"model": model})
    duration_histogram.record(duration_ms, {"model": model})
    cost_histogram.record(cost_usd, {"model": model})
    (cache_hit_counter if cache_hit else cache_miss_counter).add(1)
    routing_tier_counter.add(1, {"tier": routing_tier})


def record_eval_score(score: float) -> None:
    eval_score_histogram.record(score)


def record_drift_score(score: float, dimension: str) -> None:
    drift_score_histogram.record(score, {"dimension": dimension})


def record_cost_anomaly() -> None:
    cost_anomaly_counter.add(1)


def record_slo_breach(slo_name: str) -> None:
    slo_breach_counter.add(1, {"slo": slo_name})


def record_seema_state(request_count: int, request_limit: int, headroom_pct: float, active: bool) -> None:
    seema_request_count_histogram.record(request_count)
    seema_request_limit_histogram.record(request_limit)
    seema_headroom_histogram.record(headroom_pct)
    if active:
        seema_active_counter.add(1)


def record_seema_decision(action: str, reason: str) -> None:
    seema_decision_counter.add(1, {"action": action, "reason": reason})
