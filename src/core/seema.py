"""Proactive capacity governor for external request admission and tier routing."""

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv

from src.core import metrics

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DEFAULT_WINDOW_SECONDS = 10
DEFAULT_REQUEST_LIMIT = 4


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {raw!r}")
    return value


@dataclass
class GovernorDecision:
    active: bool
    action: str
    reasons: list[str] = field(default_factory=list)
    observed_request_count: int = 0
    request_limit: int = DEFAULT_REQUEST_LIMIT
    window_seconds: int = DEFAULT_WINDOW_SECONDS
    capacity_headroom_pct: float = 0.0
    original_tier: str = "light"
    effective_tier: str = "light"


class SeemaGovernor:
    """Counts real external requests and throttles tier selection when limits are exceeded."""

    def __init__(
        self,
        *,
        request_limit: Optional[int] = None,
        window_seconds: Optional[int] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.request_limit = request_limit if request_limit is not None else _env_positive_int(
            "SEEMA_REQUEST_LIMIT", DEFAULT_REQUEST_LIMIT
        )
        self.window_seconds = window_seconds if window_seconds is not None else _env_positive_int(
            "SEEMA_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS
        )
        if request_limit is not None and request_limit <= 0:
            raise ValueError(f"request_limit must be > 0, got {request_limit!r}")
        if window_seconds is not None and window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds!r}")

        self.clock = clock or time.monotonic
        self._timestamps: deque[float] = deque()
        self._lock = threading.RLock()

    def reset(self) -> None:
        with self._lock:
            self._timestamps.clear()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def _capacity_headroom_pct(self, observed_request_count: int) -> float:
        if self.request_limit <= 0:
            return 0.0
        headroom = ((self.request_limit - observed_request_count) / self.request_limit) * 100.0
        return round(max(headroom, 0.0), 2)

    def _slo_reasons(self) -> list[str]:
        try:
            from src.core import slo

            statuses = slo.all_slo_status()
            if any(status.get("slo_met") is False for status in statuses):
                return ["slo_breach"]
            return []
        except Exception:
            return []

    def _decide_tier(self, *, request_type: Optional[str], priority: Optional[str], original_tier: str) -> tuple[str, str]:
        normalized_request_type = (request_type or "").lower()
        normalized_priority = (priority or "").lower()

        if normalized_request_type in {"faq", "low_priority", "low-priority", "low_priority_request", "background"}:
            return "light", "route_to_light_tier"
        if normalized_request_type in {"investigation", "tool_loop", "sub_agent", "high_priority", "high-priority"}:
            return original_tier, "preserve_high_priority_request"

        if normalized_priority in {"low", "faq", "background"}:
            return "light", "route_to_light_tier"
        if normalized_priority in {"high", "urgent", "critical"}:
            return original_tier, "preserve_high_priority_request"

        return "light", "route_to_light_tier"

    def _record_capacity_slo(self, *, active: bool) -> None:
        try:
            from src.core import slo

            slo.record_outcome("capacity_headroom", met=not active)
        except Exception:
            return

    def evaluate_state(
        self,
        *,
        request_type: Optional[str] = None,
        priority: Optional[str] = None,
        original_tier: str = "light",
    ) -> GovernorDecision:
        with self._lock:
            now = self.clock()
            self._prune(now)
            observed_request_count = len(self._timestamps)
            reasons: list[str] = []
            if observed_request_count > self.request_limit:
                reasons.append("request_rate_exceeded")
            reasons.extend(self._slo_reasons())
            active = bool(reasons)
            capacity_headroom_pct = self._capacity_headroom_pct(observed_request_count)
            if active:
                effective_tier, action = self._decide_tier(
                    request_type=request_type,
                    priority=priority,
                    original_tier=original_tier,
                )
            else:
                effective_tier = original_tier
                action = "allow_normal_routing"

            decision = GovernorDecision(
                active=active,
                action=action,
                reasons=reasons,
                observed_request_count=observed_request_count,
                request_limit=self.request_limit,
                window_seconds=self.window_seconds,
                capacity_headroom_pct=capacity_headroom_pct,
                original_tier=original_tier,
                effective_tier=effective_tier,
            )
            metrics.record_seema_state(
                request_count=observed_request_count,
                request_limit=self.request_limit,
                headroom_pct=capacity_headroom_pct,
                active=active,
            )
            for reason in reasons:
                metrics.record_seema_decision(action=action, reason=reason)
            return decision

    def record_incoming_request(
        self,
        *,
        request_type: Optional[str] = None,
        priority: Optional[str] = None,
        original_tier: str = "light",
    ) -> GovernorDecision:
        with self._lock:
            now = self.clock()
            self._timestamps.append(now)
            self._prune(now)
            observed_request_count = len(self._timestamps)
            reasons: list[str] = []
            if observed_request_count > self.request_limit:
                reasons.append("request_rate_exceeded")
            reasons.extend(self._slo_reasons())
            active = bool(reasons)
            capacity_headroom_pct = self._capacity_headroom_pct(observed_request_count)
            if active:
                effective_tier, action = self._decide_tier(
                    request_type=request_type,
                    priority=priority,
                    original_tier=original_tier,
                )
            else:
                effective_tier = original_tier
                action = "allow_normal_routing"
            self._record_capacity_slo(active=active)

            decision = GovernorDecision(
                active=active,
                action=action,
                reasons=reasons,
                observed_request_count=observed_request_count,
                request_limit=self.request_limit,
                window_seconds=self.window_seconds,
                capacity_headroom_pct=capacity_headroom_pct,
                original_tier=original_tier,
                effective_tier=effective_tier,
            )
            metrics.record_seema_state(
                request_count=observed_request_count,
                request_limit=self.request_limit,
                headroom_pct=capacity_headroom_pct,
                active=active,
            )
            for reason in reasons:
                metrics.record_seema_decision(action=action, reason=reason)
            return decision


def get_default_governor() -> SeemaGovernor:
    return _DEFAULT_GOVERNOR


_DEFAULT_GOVERNOR = SeemaGovernor()


def evaluate_request(
    *,
    request_type: Optional[str] = None,
    priority: Optional[str] = None,
    original_tier: str = "light",
) -> GovernorDecision:
    return _DEFAULT_GOVERNOR.evaluate_state(
        request_type=request_type,
        priority=priority,
        original_tier=original_tier,
    )


def record_incoming_request(
    *,
    request_type: Optional[str] = None,
    priority: Optional[str] = None,
    original_tier: str = "light",
) -> GovernorDecision:
    return _DEFAULT_GOVERNOR.record_incoming_request(
        request_type=request_type,
        priority=priority,
        original_tier=original_tier,
    )


def reset() -> None:
    _DEFAULT_GOVERNOR.reset()
