"""
Alert rules — inherited base (M4/M5: model mismatch, cost spike, eval drop,
drift) PLUS Module 6/7 additions (cost-anomaly, SLO breach). Every firing
rule is routed through incident_response.open_incident(), which classifies
severity and applies alert-fatigue dedup before deciding whether this is
page-worthy.
"""

from src.core import cost_anomaly, drift, slo, incident_response
from src.core.online_eval import rolling_average_score

_alerts: list[dict] = []


def observe_and_alert(requested_model: str, served_model: str, cost_usd: float,
                       sar_narrative: str, tool_sequence: list[str]) -> list[dict]:
    fired = []

    if requested_model != served_model:
        fired.append(incident_response.open_incident(
            "model_version_mismatch",
            f"Requested {requested_model} but served {served_model}",
            {"requested_model": requested_model, "served_model": served_model},
        ))

    cost_status = cost_anomaly.observe_cost(cost_usd, context="investigation_turn")
    if cost_status.get("flagged"):
        fired.append(incident_response.open_incident(
            "cost_anomaly",
            f"Rolling cost mean {cost_status['rolling_mean_usd']} is {cost_status['ratio']}x baseline",
            cost_status,
        ))
        slo.record_outcome("cost_stability", met=False)
    elif cost_status.get("baseline_ready"):
        slo.record_outcome("cost_stability", met=True)

    drift_result = drift.observe(sar_narrative, tool_sequence)
    if drift_result.get("baseline_ready"):
        if drift_result.get("narrative_drift_flagged") or drift_result.get("tool_mix_drift_flagged"):
            fired.append(incident_response.open_incident(
                "narrative_drift", "Narrative or tool-mix drift threshold crossed", drift_result,
            ))
            slo.record_outcome("narrative_integrity", met=False)
        else:
            slo.record_outcome("narrative_integrity", met=True)

    avg = rolling_average_score()
    if avg is not None and avg < 3.0:
        fired.append(incident_response.open_incident(
            "eval_score_drop", f"Rolling average eval score dropped to {avg}", {"rolling_average_score": avg},
        ))

    for slo_status in slo.all_slo_status():
        if slo_status.get("slo_met") is False:
            fired.append(incident_response.open_incident(
                "slo_breach", f"SLO '{slo_status['name']}' at {slo_status['current_pct']}% (target {slo_status['target_pct']}%)",
                slo_status,
            ))

    _alerts.extend(fired)
    return fired


def recent_alerts(limit: int = 30) -> list[dict]:
    return list(_alerts[-limit:])


def clear_alerts() -> None:
    _alerts.clear()
