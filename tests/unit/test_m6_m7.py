"""
Deterministic tests for Module 6/7 logic — no OPENAI_API_KEY required,
since none of this touches llm_provider.py, online
(those need a live API). Run with: pytest tests/unit -v
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core import cost_attribution, cost_anomaly, slo, incident_response, routing
from src.core.caching import normalize_question, cache_key
from src.core.seema import SeemaGovernor


def test_cost_attribution_rolls_up_by_feature():
    cost_attribution.reset_rollup()
    cost_attribution.record_cost("team-a", "investigation", "CUST-1", 0.01)
    cost_attribution.record_cost("team-a", "investigation", "CUST-2", 0.02)
    cost_attribution.record_cost("team-a", "sar_drafting", "CUST-1", 0.05)
    by_feature = cost_attribution.attribution_by_feature()
    totals = {r["feature"]: r["total_cost_usd"] for r in by_feature}
    assert totals["investigation"] == 0.03
    assert totals["sar_drafting"] == 0.05


def test_cost_anomaly_flags_sustained_spike():
    cost_anomaly.reset()
    for _ in range(15):
        cost_anomaly.observe_cost(0.001)  # baseline
    status = None
    for _ in range(8):
        status = cost_anomaly.observe_cost(0.01)  # 10x spike, sustained
    assert status["flagged"] is True


def test_cost_anomaly_does_not_flag_normal_variation():
    cost_anomaly.reset()
    for _ in range(15):
        cost_anomaly.observe_cost(0.01)
    status = None
    for _ in range(8):
        status = cost_anomaly.observe_cost(0.011)  # small normal variation
    assert status["flagged"] is False


def test_slo_status_computes_error_budget():
    slo.reset("answer_quality")
    for _ in range(27):
        slo.record_outcome("answer_quality", met=True)
    for _ in range(3):
        slo.record_outcome("answer_quality", met=False)
    status = slo.slo_status("answer_quality")
    assert status["sample_size"] == 30
    assert status["current_pct"] == 90.0
    assert status["slo_met"] is False  # target is 95%


def test_incident_classification():
    assert incident_response.classify("slo_breach").value == "SEV1"
    assert incident_response.classify("cost_anomaly").value == "SEV2"
    assert incident_response.classify("unknown_class").value == "SEV3"


def test_incident_dedup_suppresses_repeat_page_within_window():
    incident_response._last_paged.clear()
    first = incident_response.should_page("test_class_dedup")
    second = incident_response.should_page("test_class_dedup")
    assert first is True
    assert second is False  # within DEDUP_WINDOW_SECONDS


def test_routing_sends_subagent_to_heavy_tier():
    decision = routing.route_request("sub_agent")
    assert decision.model == routing.HEAVY_TIER_MODEL


def test_routing_sends_normal_tool_loop_to_light_tier():
    decision = routing.route_request("tool_loop", complexity_hint="normal")
    assert decision.model == routing.LIGHT_TIER_MODEL


def test_routing_escalates_on_high_complexity():
    decision = routing.route_request("tool_loop", complexity_hint="high")
    assert decision.model == routing.HEAVY_TIER_MODEL


def test_cache_key_normalizes_case_and_punctuation():
    k1 = cache_key("gpt-4o-mini", "What is the overdraft EAR?")
    k2 = cache_key("gpt-4o-mini", "what is the overdraft ear")
    assert k1 == k2


def test_cache_key_differs_by_model():
    k1 = cache_key("gpt-4o-mini", "same question")
    k2 = cache_key("gpt-4o", "same question")
    assert k1 != k2


def test_seema_trips_on_request_rate_limit():
    slo.reset()
    clock = [0.0]
    governor = SeemaGovernor(request_limit=2, window_seconds=10, clock=lambda: clock[0])
    for _ in range(2):
        decision = governor.record_incoming_request(request_type="faq", priority="low", original_tier="light")
        assert decision.active is False
    decision = governor.record_incoming_request(request_type="faq", priority="low", original_tier="light")
    assert decision.active is True
    assert decision.reasons == ["request_rate_exceeded"]
    assert decision.effective_tier == "light"


def test_seema_trips_on_slo_failure():
    clock = [0.0]
    governor = SeemaGovernor(request_limit=20, window_seconds=10, clock=lambda: clock[0])
    slo.reset()
    slo.record_outcome("answer_quality", met=False)
    decision = governor.evaluate_state(request_type="investigation", priority="normal", original_tier="light")
    assert decision.active is True
    assert "slo_breach" in decision.reasons
    assert decision.effective_tier == "light"
