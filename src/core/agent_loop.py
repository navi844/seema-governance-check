"""
The full pipeline, one investigation at a time:
  tool loop -> SAR sub-agent delegation -> cost attribution -> cost
  anomaly check -> online eval -> drift check -> SLO recording ->
  alerting (with incident classification + alert-fatigue dedup)

Every module built across M2-M7 is called from exactly one place: here.
"""

import json
import uuid

from src.core.llm_provider import chat_raw
from src.core.sub_agent import run_sar_drafting_subagent
from src.core.otel_setup import get_tracer
from src.core import metrics, cost_attribution, online_eval, slo, alerting
from src.tools.investigation_tools import TOOL_SCHEMAS, TOOL_FUNCTIONS
from src.core.seema import record_incoming_request
from src.core.routing import route_request

SYSTEM_PROMPT = """You are Niyantran, a fraud/AML transaction-pattern investigation
assistant for Lloyds Financial (training scenario). Given a customer_id, use the
available tools to gather evidence: KYC profile, transaction history, an AML
typology check relevant to the pattern you observe, and counterparty watchlist
screening. Summarize your findings in a short internal note once done — a
specialist will draft the formal SAR from your findings.
"""

MAX_TURNS = 6
TEAM_NAME = "fraud-aml-ops"
FEATURE_NAME = "transaction_investigation"
FAQ_FEATURE_NAME = "compliance_faq"

FAQ_SYSTEM_PROMPT = """You are a concise AML/compliance assistant answering
general policy questions (not specific-customer investigations). Keep
answers short and factual."""


def answer_faq(question: str, user: str = "anonymous") -> dict:
    """
    The cacheable path. Unlike run_investigation() (a multi-turn tool loop
    whose message history differs every time, so caching the raw API call
    would never hit), this is a single-turn, tool-free Q&A path for
    general compliance questions — e.g. 'What counts as structuring?' —
    where the same question really does recur verbatim across users. This
    is the call site that actually exercises caching.py; see the
    observation questions document for why run_investigation() doesn't.
    """
    governor = record_incoming_request(request_type="faq", priority="low", original_tier="light")
    result = chat_raw(
        messages=[
            {"role": "system", "content": FAQ_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        task_kind="tool_loop",
        allow_cache=True,
        complexity_hint="normal",
        request_type="faq",
        priority="low",
        governor=governor,
    )
    cost_attribution.record_cost(TEAM_NAME, FAQ_FEATURE_NAME, user, result.cost_usd)
    metrics.record_investigation_turn(result.served_model, result.duration_ms, result.cost_usd,
                                       result.cache_hit, result.routing_tier)
    return {
        "question": question,
        "answer": result.content,
        "cache_hit": result.cache_hit,
        "cost_usd": result.cost_usd,
        "served_model": result.served_model,
    }


def run_investigation(customer_id: str, complexity_hint: str = "normal", verbose: bool = True) -> dict:
    tracer = get_tracer("niyantran.agent_loop")
    investigation_id = str(uuid.uuid4())[:8]
    governor = record_incoming_request(request_type="investigation", priority="normal", original_tier="light")

    with tracer.start_as_current_span("investigation") as parent_span:
        parent_span.set_attribute("niyantran.investigation_id", investigation_id)
        parent_span.set_attribute("niyantran.customer_id", customer_id)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Investigate customer_id: {customer_id}"},
        ]

        call_log = []
        final_summary = None
        gathered_evidence = {}
        total_cost = 0.0

        for turn in range(1, MAX_TURNS + 1):
            result = chat_raw(
                messages,
                tools=TOOL_SCHEMAS,
                task_kind="tool_loop",
                complexity_hint=complexity_hint,
                request_type="investigation",
                priority="normal",
                governor=governor,
            )
            total_cost += result.cost_usd
            cost_attribution.record_cost(TEAM_NAME, FEATURE_NAME, customer_id, result.cost_usd)
            metrics.record_investigation_turn(result.served_model, result.duration_ms, result.cost_usd,
                                               result.cache_hit, result.routing_tier)

            call_log.append({
                "turn": turn, "finish_reason": result.finish_reason,
                "requested_model": result.requested_model, "served_model": result.served_model,
                "routing_tier": result.routing_tier, "cost_usd": round(result.cost_usd, 6),
                "tool_calls_requested": [tc.name for tc in result.tool_calls],
            })

            if verbose:
                print(f"[turn {turn}] tier={result.routing_tier} tool_calls={[tc.name for tc in result.tool_calls]} "
                      f"cost_usd={result.cost_usd:.6f}")

            if result.finish_reason == "tool_calls" and result.tool_calls:
                messages.append({
                    "role": "assistant", "content": result.content,
                    "tool_calls": [{"id": tc.id, "type": "function",
                                     "function": {"name": tc.name, "arguments": tc.arguments}}
                                    for tc in result.tool_calls],
                })
                for tc in result.tool_calls:
                    fn = TOOL_FUNCTIONS.get(tc.name)
                    try:
                        args = json.loads(tc.arguments)
                        tool_result = fn(**args) if fn else {"error": f"unknown tool {tc.name}"}
                    except Exception as exc:  # noqa: BLE001
                        tool_result = {"error": str(exc)}
                    gathered_evidence[tc.name] = tool_result
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tool_result)})
                continue

            final_summary = result.content
            break

        sar = run_sar_drafting_subagent(customer_id, investigation_evidence=gathered_evidence)
        total_cost += sar["cost_usd"]
        cost_attribution.record_cost(TEAM_NAME, "sar_drafting", customer_id, sar["cost_usd"])

        eval_result = online_eval.maybe_grade(gathered_evidence, sar["sar_narrative"])
        if eval_result:
            slo.record_outcome("answer_quality", met=(eval_result["verdict"] == "pass"))

        fired_alerts = alerting.observe_and_alert(
            requested_model=call_log[-1]["requested_model"] if call_log else "",
            served_model=sar["served_model"],
            cost_usd=total_cost,
            sar_narrative=sar["sar_narrative"],
            tool_sequence=list(gathered_evidence.keys()),
        )

        return {
            "investigation_id": investigation_id,
            "customer_id": customer_id,
            "internal_summary": final_summary,
            "gathered_evidence": gathered_evidence,
            "sar": sar,
            "total_cost_usd": round(total_cost, 6),
            "call_log": call_log,
            "eval_result": eval_result,
            "alerts_fired": fired_alerts,
        }
