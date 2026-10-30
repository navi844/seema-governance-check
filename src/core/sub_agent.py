"""SAR-drafting sub-agent delegation — routed to the heavy tier (gpt-4o),
traced as a child span of the parent investigation."""

from typing import Optional

from src.core.llm_provider import chat_raw
from src.core.otel_setup import get_tracer

SAR_SYSTEM_PROMPT = """You are a SAR (Suspicious Activity Report) drafting
assistant for Lloyds Financial (training scenario). Given the evidence
provided, write a short, formal SAR narrative suitable for a human
compliance reviewer: what was found, which typology was flagged (if any),
whether any counterparty is on the watchlist, and a recommended next
action.
"""


def run_sar_drafting_subagent(customer_id: str, investigation_evidence: Optional[dict] = None) -> dict:
    tracer = get_tracer("niyantran.subagent")
    with tracer.start_as_current_span("sar_drafting_subagent") as span:
        span.set_attribute("niyantran.subagent.customer_id", customer_id)
        evidence_text = f"Evidence gathered by the investigation:\n{investigation_evidence}"

        result = chat_raw(
            messages=[
                {"role": "system", "content": SAR_SYSTEM_PROMPT},
                {"role": "user", "content": f"customer_id: {customer_id}\n\n{evidence_text}"},
            ],
            task_kind="sub_agent",
        )
        span.set_attribute("niyantran.subagent.cost_usd", result.cost_usd)

        return {
            "customer_id": customer_id,
            "sar_narrative": result.content,
            "requested_model": result.requested_model,
            "served_model": result.served_model,
            "cost_usd": result.cost_usd,
        }
