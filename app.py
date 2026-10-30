"""FastAPI entrypoint for Niyantran. Run with: uvicorn app:app --reload --port 8000"""

from fastapi import FastAPI, HTTPException

from src.core.agent_loop import run_investigation, answer_faq
from src.core import cost_attribution, cost_anomaly, slo, alerting, feedback, online_eval, drift, incident_response
from src.core.seema import reset as reset_seema
from src.data.mock_store import CUSTOMERS

app = FastAPI(title="Niyantran — Cost, Capacity & SLO-Driven Operations for the Fraud/AML Agent")


@app.get("/customers")
def list_customers():
    return {"customers": list(CUSTOMERS.keys())}


@app.get("/investigate")
def investigate(customer_id: str, complexity_hint: str = "normal"):
    if customer_id not in CUSTOMERS:
        raise HTTPException(status_code=404, detail=f"Unknown customer_id {customer_id}")
    return run_investigation(customer_id, complexity_hint=complexity_hint, verbose=False)


@app.get("/faq")
def faq(question: str, user: str = "anonymous"):
    """The cacheable path — ask the same question twice and watch
    cache_hit flip to true and cost_usd drop to 0 on the second call."""
    return answer_faq(question, user=user)


# ---- Module 6: cost / capacity ----
@app.get("/cost/attribution/feature")
def cost_by_feature():
    return {"by_feature": cost_attribution.attribution_by_feature()}


@app.get("/cost/attribution/team")
def cost_by_team():
    return {"by_team": cost_attribution.attribution_by_team()}


@app.get("/cost/attribution/user")
def cost_by_user(limit: int = 10):
    return {"by_user": cost_attribution.attribution_by_user(limit)}


@app.get("/cost/anomalies")
def cost_anomalies():
    return {"anomalies": cost_anomaly.recent_anomalies()}


# ---- Module 7: SLOs / alerting / incidents ----
@app.get("/slo/status")
def slo_status():
    return {"slos": slo.all_slo_status()}


@app.get("/alerts")
def alerts():
    return {"alerts": alerting.recent_alerts()}


@app.post("/alerts/clear")
def clear_alerts():
    alerting.clear_alerts()
    return {"cleared": True}


@app.get("/incidents")
def incidents():
    return {"incidents": incident_response.recent_incidents()}


@app.get("/incidents/postmortem-template")
def postmortem_template():
    recent = incident_response.recent_incidents(limit=1)
    if not recent:
        raise HTTPException(status_code=404, detail="No incidents to generate a postmortem for yet")
    return {"template_markdown": incident_response.postmortem_template(recent[-1])}


# ---- inherited M4/M5 endpoints ----
@app.get("/eval/recent")
def eval_recent():
    return {"recent": online_eval.recent_judged(), "rolling_average_score": online_eval.rolling_average_score()}


@app.get("/drift/status")
def drift_status():
    return drift.status()


@app.post("/drift/reset-baseline")
def drift_reset():
    drift.reset_baseline()
    return {"reset": True}


@app.post("/feedback")
def submit_feedback(investigation_id: str, rating: str, note: str = ""):
    return feedback.record_feedback(investigation_id, rating, note)


@app.get("/annotation-queue")
def annotation_queue():
    return {"queue": feedback.annotation_queue()}


@app.post("/admin/reset")
def reset_runtime_state():
    """Admin reset for in-memory capacity/SLO state during live validation."""
    slo.reset()
    cost_anomaly.reset()
    cost_attribution.reset_rollup()
    alerting.clear_alerts()
    reset_seema()
    return {
        "reset": True,
        "cleared": [
            "slo",
            "cost_anomaly",
            "cost_attribution",
            "alerts",
            "seema",
        ],
    }
