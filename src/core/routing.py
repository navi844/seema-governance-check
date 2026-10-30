"""
Model routing / tiering — Module 6.

Production teams typically do this with LiteLLM's router (model lists,
fallback chains, load balancing across providers/keys). This file is a
small, dependency-free stand-in that implements the same DECISION the
router makes — which tier a request belongs in — so the logic is fully
visible for the lab. Swapping this for a real LiteLLM Router config is a
drop-in change: route_request() stays the call site, only its internals
change.

Two tiers:
  - "light"  (gpt-4o-mini) for single-tool-call, low-ambiguity requests
  - "heavy"  (gpt-4o)      for anything that needs multi-step reasoning
               over several pieces of evidence (and for the SAR-drafting
               sub-agent, which must sound reliably professional)
"""

from dataclasses import dataclass, field
from typing import Optional

LIGHT_TIER_MODEL = "gpt-4o-mini"
HEAVY_TIER_MODEL = "gpt-4o"


@dataclass
class RoutingDecision:
    model: str
    tier: str
    reason: str
    governor_active: bool = False
    governor_action: str = "allow_normal_routing"
    governor_reasons: list[str] = field(default_factory=list)
    governor_request_count: int = 0
    governor_request_limit: int = 20
    capacity_headroom_pct: float = 100.0


def route_request(task_kind: str, complexity_hint: str = "normal",
                 request_type: Optional[str] = None,
                 priority: Optional[str] = None,
                 governor=None) -> RoutingDecision:
    """
    task_kind: "tool_loop" (the main investigation loop) or "sub_agent" (SAR drafting)
    complexity_hint: "normal" or "high" — callers can pass "high" when they
    already know a case is unusually large to force the heavy tier even for the tool loop.
    request_type: explicit external request classification (e.g. "investigation", "faq").
    priority: explicit caller priority signal; low values and missing priority default to light tier.
    """
    if task_kind == "sub_agent":
        base_decision = RoutingDecision(
            model=HEAVY_TIER_MODEL, tier="heavy",
            reason="SAR narratives are reviewer-facing and must be reliably well-formed",
        )
    elif complexity_hint == "high":
        base_decision = RoutingDecision(
            model=HEAVY_TIER_MODEL, tier="heavy",
            reason="caller flagged high complexity (large transaction set / multiple watchlist hits)",
        )
    else:
        base_decision = RoutingDecision(
            model=LIGHT_TIER_MODEL, tier="light",
            reason="standard tool-calling turn, no complexity signal raised",
        )

    if governor is None:
        base_decision.governor_active = False
        base_decision.governor_action = "allow_normal_routing"
        base_decision.governor_reasons = []
        base_decision.governor_request_count = 0
        base_decision.governor_request_limit = 20
        base_decision.capacity_headroom_pct = 100.0
        return base_decision

    if hasattr(governor, "active"):
        governor_state = governor
    else:
        governor_state = governor.evaluate_state(
            request_type=(request_type or task_kind).lower(),
            priority=(priority or "normal").lower(),
            original_tier=base_decision.tier,
        )

    if governor_state.active:
        base_decision.tier = governor_state.effective_tier
        base_decision.model = LIGHT_TIER_MODEL if governor_state.effective_tier == "light" else HEAVY_TIER_MODEL
        base_decision.reason = f"Seema active: {governor_state.action}; trigger_reasons={governor_state.reasons}"
        base_decision.governor_active = True
        base_decision.governor_action = governor_state.action
        base_decision.governor_reasons = governor_state.reasons
        base_decision.governor_request_count = governor_state.observed_request_count
        base_decision.governor_request_limit = governor_state.request_limit
        base_decision.capacity_headroom_pct = governor_state.capacity_headroom_pct
        return base_decision

    base_decision.governor_active = False
    base_decision.governor_action = "allow_normal_routing"
    base_decision.governor_reasons = []
    base_decision.governor_request_count = governor_state.observed_request_count
    base_decision.governor_request_limit = governor_state.request_limit
    base_decision.capacity_headroom_pct = governor_state.capacity_headroom_pct
    return base_decision
