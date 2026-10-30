"""
The model-call primitive, now carrying the full stack: OTel span, routing
decision, cache check, and cost accounting — all in one call site so every
caller gets all of it for free.

NOTE: .env is loaded explicitly, by path, before anything reads
OPENAI_API_KEY — a bug in an earlier repo in this series taught us to
always check for this.
"""

import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from src.core.otel_setup import get_tracer
from src.core.genai_conventions import (
    GEN_AI_SYSTEM, GEN_AI_OPERATION_NAME, GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_MODEL, GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_USAGE_INPUT_TOKENS, GEN_AI_USAGE_OUTPUT_TOKENS,
    NIYANTRAN_COST_USD, NIYANTRAN_ROUTING_TIER, NIYANTRAN_ROUTING_REASON,
    NIYANTRAN_CACHE_HIT, NIYANTRAN_SEEMA_ACTIVE, NIYANTRAN_SEEMA_ACTION,
    NIYANTRAN_SEEMA_TRIGGER_REASONS, NIYANTRAN_SEEMA_REQUEST_COUNT,
    NIYANTRAN_SEEMA_REQUEST_LIMIT, NIYANTRAN_SEEMA_CAPACITY_HEADROOM_PCT,
    NIYANTRAN_SEEMA_ORIGINAL_TIER, NIYANTRAN_SEEMA_EFFECTIVE_TIER,
    safe_prompt_attribute,
)
from src.core.pricing import estimate_cost_usd
from src.core.routing import route_request
from src.core.caching import get_cached, set_cached

ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_FILE)

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(f"OPENAI_API_KEY is not set. Check your .env file at: {ENV_FILE}")
        _client = OpenAI(api_key=api_key)
    return _client


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ModelCallResult:
    content: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    requested_model: str = ""
    served_model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    cache_hit: bool = False
    routing_tier: str = ""
    routing_reason: str = ""


def chat_raw(messages: list[dict], tools: Optional[list] = None,
             task_kind: str = "tool_loop", complexity_hint: str = "normal",
             allow_cache: bool = False, temperature: Optional[float] = None,
             request_type: Optional[str] = None, priority: Optional[str] = None,
             governor=None) -> ModelCallResult:
    """
    allow_cache: only pass True for cacheable, tool-free single-turn calls
    (e.g. raw_call_demo-style lookups). The main tool loop and sub-agent
    calls never cache, since their messages differ turn to turn.
    """
    tracer = get_tracer("niyantran.model")
    client = _get_client()

    decision = route_request(task_kind, complexity_hint, request_type=request_type,
                            priority=priority, governor=governor)

    with tracer.start_as_current_span("model_call") as span:
        span.set_attribute(GEN_AI_SYSTEM, "openai")
        span.set_attribute(GEN_AI_OPERATION_NAME, "chat")
        span.set_attribute(GEN_AI_REQUEST_MODEL, decision.model)
        span.set_attribute(NIYANTRAN_ROUTING_TIER, decision.tier)
        span.set_attribute(NIYANTRAN_ROUTING_REASON, decision.reason)
        span.set_attribute(NIYANTRAN_SEEMA_ACTIVE, decision.governor_active)
        span.set_attribute(NIYANTRAN_SEEMA_ACTION, decision.governor_action)
        span.set_attribute(NIYANTRAN_SEEMA_TRIGGER_REASONS, decision.governor_reasons)
        span.set_attribute(NIYANTRAN_SEEMA_REQUEST_COUNT, decision.governor_request_count)
        span.set_attribute(NIYANTRAN_SEEMA_REQUEST_LIMIT, decision.governor_request_limit)
        span.set_attribute(NIYANTRAN_SEEMA_CAPACITY_HEADROOM_PCT, decision.capacity_headroom_pct)
        span.set_attribute(NIYANTRAN_SEEMA_ORIGINAL_TIER, "light")
        span.set_attribute(NIYANTRAN_SEEMA_EFFECTIVE_TIER, decision.tier)
        if messages:
            last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            span.set_attribute("gen_ai.prompt.last_user_message", safe_prompt_attribute(last_user))

        cache_hit = False
        if allow_cache and messages:
            question = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            cached = get_cached(decision.model, question)
            if cached is not None:
                cache_hit = True
                span.set_attribute(NIYANTRAN_CACHE_HIT, True)
                span.set_attribute(GEN_AI_RESPONSE_MODEL, decision.model)
                span.set_attribute(NIYANTRAN_COST_USD, 0.0)
                return ModelCallResult(
                    content=cached, finish_reason="stop",
                    requested_model=decision.model, served_model=decision.model,
                    cache_hit=True, routing_tier=decision.tier, routing_reason=decision.reason,
                )
            span.set_attribute(NIYANTRAN_CACHE_HIT, False)

        kwargs = {"model": decision.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if temperature is not None:
            kwargs["temperature"] = temperature

        t0 = time.perf_counter()
        response = client.chat.completions.create(**kwargs)
        duration_ms = (time.perf_counter() - t0) * 1000

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        cost = estimate_cost_usd(response.model, input_tokens, output_tokens)

        span.set_attribute(GEN_AI_RESPONSE_MODEL, response.model)
        span.set_attribute(GEN_AI_RESPONSE_FINISH_REASONS, [choice.finish_reason])
        span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS, input_tokens)
        span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS, output_tokens)
        span.set_attribute(NIYANTRAN_COST_USD, cost)

        if allow_cache and messages and choice.message.content:
            question = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            set_cached(decision.model, question, choice.message.content)

        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
            for tc in (choice.message.tool_calls or [])
        ]

        return ModelCallResult(
            content=choice.message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            requested_model=decision.model,
            served_model=response.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
            cache_hit=cache_hit,
            routing_tier=decision.tier,
            routing_reason=decision.reason,
        )
