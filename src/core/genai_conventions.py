"""
OpenTelemetry GenAI semantic convention attribute names, plus this repo's
own niyantran.* namespace for everything the standard doesn't cover.
Centralized here so every module spells an attribute name the same way.
"""

# --- standard GenAI semantic conventions ---
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"

# --- cost / routing (M6) ---
NIYANTRAN_COST_USD = "niyantran.cost_usd"
NIYANTRAN_COST_TEAM = "niyantran.cost.team"
NIYANTRAN_COST_FEATURE = "niyantran.cost.feature"
NIYANTRAN_COST_USER = "niyantran.cost.user"
NIYANTRAN_ROUTING_TIER = "niyantran.routing.tier"
NIYANTRAN_ROUTING_REASON = "niyantran.routing.reason"
NIYANTRAN_CACHE_HIT = "niyantran.cache.hit"
NIYANTRAN_CACHE_KEY = "niyantran.cache.key"
NIYANTRAN_SEEMA_ACTIVE = "seema.active"
NIYANTRAN_SEEMA_ACTION = "seema.action"
NIYANTRAN_SEEMA_TRIGGER_REASONS = "seema.trigger_reasons"
NIYANTRAN_SEEMA_REQUEST_COUNT = "seema.request_count"
NIYANTRAN_SEEMA_REQUEST_LIMIT = "seema.request_limit"
NIYANTRAN_SEEMA_CAPACITY_HEADROOM_PCT = "seema.capacity_headroom_pct"
NIYANTRAN_SEEMA_ORIGINAL_TIER = "seema.original_tier"
NIYANTRAN_SEEMA_EFFECTIVE_TIER = "seema.effective_tier"

# --- eval / drift / alerting (M4-M5, inherited base) ---
NIYANTRAN_EVAL_SAMPLED = "niyantran.eval.sampled"
NIYANTRAN_EVAL_SCORE = "niyantran.eval.score"
NIYANTRAN_EVAL_VERDICT = "niyantran.eval.verdict"
NIYANTRAN_DRIFT_SCORE = "niyantran.drift.score"
NIYANTRAN_DRIFT_FLAGGED = "niyantran.drift.flagged"

# --- SLO / incident response (M7) ---
NIYANTRAN_SLO_NAME = "niyantran.slo.name"
NIYANTRAN_SLO_MET = "niyantran.slo.met"
NIYANTRAN_INCIDENT_SEVERITY = "niyantran.incident.severity"
NIYANTRAN_INCIDENT_CLASS = "niyantran.incident.class"


def safe_prompt_attribute(text: str, max_len: int = 300) -> str:
    """Truncate + flag long prompt text before it goes into a span attribute."""
    if text is None:
        return ""
    text = str(text)
    return text if len(text) <= max_len else text[:max_len] + "...[truncated]"
