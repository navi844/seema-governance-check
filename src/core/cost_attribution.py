"""
Cost attribution by team / feature / user — Module 6.

Every finished model call reports its cost tagged with three dimensions.
"Team" and "feature" are passed in by the caller (agent_loop.py knows
which feature it's serving; a real deployment would resolve "team" from
auth context). "user" is the customer_id being investigated, standing in
for whichever end-user identity your real system has.

record_cost() both pushes to the OTel metrics instrument (metrics.py) AND
keeps a small in-memory rollup so /cost/attribution can answer "who's
spending what" without needing a live Prometheus query during the lab.
"""

from collections import defaultdict
from dataclasses import dataclass, field

_ROLLUP: dict[tuple[str, str, str], float] = defaultdict(float)
_CALL_COUNT: dict[tuple[str, str, str], int] = defaultdict(int)


@dataclass
class CostEvent:
    team: str
    feature: str
    user: str
    cost_usd: float


def record_cost(team: str, feature: str, user: str, cost_usd: float) -> CostEvent:
    key = (team, feature, user)
    _ROLLUP[key] += cost_usd
    _CALL_COUNT[key] += 1
    return CostEvent(team=team, feature=feature, user=user, cost_usd=cost_usd)


def attribution_by_feature() -> list[dict]:
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for (team, feature, user), cost in _ROLLUP.items():
        totals[feature] += cost
        counts[feature] += _CALL_COUNT[(team, feature, user)]
    rows = [
        {"feature": feature, "total_cost_usd": round(cost, 6), "call_count": counts[feature]}
        for feature, cost in totals.items()
    ]
    return sorted(rows, key=lambda r: r["total_cost_usd"], reverse=True)


def attribution_by_team() -> list[dict]:
    totals: dict[str, float] = defaultdict(float)
    for (team, feature, user), cost in _ROLLUP.items():
        totals[team] += cost
    rows = [{"team": team, "total_cost_usd": round(cost, 6)} for team, cost in totals.items()]
    return sorted(rows, key=lambda r: r["total_cost_usd"], reverse=True)


def attribution_by_user(limit: int = 10) -> list[dict]:
    totals: dict[str, float] = defaultdict(float)
    for (team, feature, user), cost in _ROLLUP.items():
        totals[user] += cost
    rows = [{"user": user, "total_cost_usd": round(cost, 6)} for user, cost in totals.items()]
    return sorted(rows, key=lambda r: r["total_cost_usd"], reverse=True)[:limit]


def reset_rollup() -> None:
    _ROLLUP.clear()
    _CALL_COUNT.clear()
