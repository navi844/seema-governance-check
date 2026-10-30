"""
Incident classification, alert-fatigue control, and blameless postmortem
templating — Module 7.

This does NOT duplicate alerting.py's signal detection (model mismatch,
drift, cost spikes, SLO breaches all still fire from their own modules).
What this adds is what happens AFTER a signal fires: deciding how urgent
it is, deduping so on-call isn't paged once per request, and producing a
postmortem document shell that forces root-cause-not-blame structure.
"""

import time
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    SEV1 = "SEV1"  # customer-facing harm or compliance exposure (e.g. PII leak, wrong SAR filed)
    SEV2 = "SEV2"  # quality/cost SLO breach, no direct harm yet, needs same-day response
    SEV3 = "SEV3"  # isolated anomaly, track but no page


INCIDENT_CLASSES = {
    "model_version_mismatch": Severity.SEV2,
    "cost_anomaly": Severity.SEV2,
    "narrative_drift": Severity.SEV2,
    "eval_score_drop": Severity.SEV2,
    "slo_breach": Severity.SEV1,
    "watchlist_screening_failure": Severity.SEV1,  # compliance-exposure class, always SEV1
}

# Alert-fatigue control: don't re-page for the same (class) within the
# dedup window, regardless of how many times the underlying rule refires.
DEDUP_WINDOW_SECONDS = 600
_last_paged: dict[str, float] = {}
_incident_log: list[dict] = []


def classify(incident_class: str) -> Severity:
    return INCIDENT_CLASSES.get(incident_class, Severity.SEV3)


def should_page(incident_class: str) -> bool:
    """True once per DEDUP_WINDOW_SECONDS per incident class — this is the
    anti-alert-fatigue check referenced by alerting.py before it raises an
    alert as 'page-worthy' vs. just logging it."""
    now = time.time()
    last = _last_paged.get(incident_class)
    if last is not None and (now - last) < DEDUP_WINDOW_SECONDS:
        return False
    _last_paged[incident_class] = now
    return True


def open_incident(incident_class: str, summary: str, evidence: dict) -> dict:
    severity = classify(incident_class)
    paged = should_page(incident_class)
    record = {
        "incident_class": incident_class,
        "severity": severity.value,
        "summary": summary,
        "evidence": evidence,
        "paged": paged,
        "opened_at": time.time(),
    }
    _incident_log.append(record)
    return record


def recent_incidents(limit: int = 20) -> list[dict]:
    return list(_incident_log[-limit:])


def postmortem_template(incident_record: dict) -> str:
    """
    A blameless postmortem shell — deliberately structured so that filling
    it in forces a process/systemic root cause rather than naming a person.
    No field here asks "who did this."
    """
    return f"""# Postmortem — {incident_record['incident_class']} ({incident_record['severity']})

## Summary
{incident_record['summary']}

## Timeline
- Detected at: {incident_record['opened_at']}
- (fill in: when did the underlying condition actually start vs. when was it detected?)

## Impact
- (fill in: how many requests/customers affected, for how long)
- (fill in: SLO/error-budget impact, citing slo.py's current_pct at the time)

## Root Cause (systemic, not individual)
- (fill in: what CONDITION in the system allowed this — a missing check, an
  unguarded assumption, a monitoring gap — never "who")

## Evidence
{incident_record['evidence']}

## What Caught It / What Should Have Caught It Sooner
- (fill in: which alert/dashboard/SLO surfaced this, and how much time
  elapsed between the condition starting and it being noticed)

## Remediation — Action Items (owner + due date, not blame)
- [ ] (fill in: concrete change — new alert rule, runbook update, code fix)
- [ ] (fill in)

## Follow-up Verification
- (fill in: how will we confirm the remediation actually closed the gap —
  re-run the same incident class and confirm it's now caught faster)
"""
