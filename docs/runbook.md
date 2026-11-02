# Niyantran — On-Call Runbook

Scope: the fraud/AML transaction-pattern investigation agent (Lloyds
Financial, training scenario) and its cost/SLO operations layer.

## When you get paged

1. **Check which alert fired.** `GET /alerts` or the Alertmanager UI
   (`:9093`) names the exact rule (`alert_rules.yml`) and its labels.
2. **Check severity.** `incident_response.classify()` has already assigned
   one: SEV1 (customer-facing harm or compliance exposure — page
   immediately), SEV2 (quality/cost SLO breach, same-day response), SEV3
   (isolated anomaly, log only, no page).
3. **Open the matching dashboard panel first**, not raw traces — Grafana's
   Niyantran dashboard (`:3000`) should answer "is this still happening"
   and "how bad" in one glance.

## Per-alert playbook

### `NiyantranCostBurnRateHigh` / `cost_anomaly` incident
- Check `GET /cost/anomalies` for the baseline-vs-rolling ratio.
- Check `GET /cost/attribution/feature` and `/cost/attribution/user` —
  is the spend concentrated in one feature/customer (points to a specific
  bug) or spread evenly (points to a genuine traffic increase)?
- Common root cause in this repo's incident history: a delegation loop
  re-invoking the SAR sub-agent repeatedly. Check the trace for an
  unusually long `sar_drafting_subagent` chain.

### `NiyantranCacheHitRateLow`
- Check `caching.py`'s `cache_backend()` — if it reports
  `in_process_fallback`, Redis isn't reachable; that alone explains a
  lower hit rate (fallback cache is per-process, not shared).
- If Redis IS reachable, check `normalize_question()` — overly specific
  cache keys are the most common cause.

### `NiyantranEvalScoreDropped` / `eval_score_drop` incident
- `GET /eval/recent` — read the judge's `reason` field for the failing
  entries, not just the score.
- Check `GET /annotation-queue` for a human-reviewed example to compare
  against.

### `NiyantranDriftScoreHigh` / `narrative_drift` incident
- `GET /drift/status` — confirm `baseline_ready` is true (a drift alert
  before the baseline is frozen is a false positive from undersampling).
- Compare `narrative_drift_flagged` vs. `tool_mix_drift_flagged` — they
  point to different root causes (narrative wording drift vs. a change in
  which tools are being called).

### `NiyantranSLOBreach` / `slo_breach` incident (SEV1)
- `GET /slo/status` — identify which SLO and by how much
  (`error_budget_remaining_pct`).
- This is the aggregate signal: don't try to fix it by looking at one
  request. Work backward from which underlying alert (cost/eval/drift) is
  driving the breach.

### `model_version_mismatch` incident
- Compare `gen_ai.request.model` vs. `gen_ai.response.model` on a recent
  trace in Jaeger. If they disagree, something upstream (a provider alias,
  a config change) is silently serving a different model than requested.

### `NiyantranCapacityHeadroomBreach` / `capacity_headroom` incident (SEV1)
- This alert means the Seema governor has seen sustained request pressure: the
  average observed headroom over the last 10 minutes has stayed below 90% for
  2 minutes. In code, this is the `capacity_headroom` SLO in
  `src/core/slo.py` and the request-rate guard in `src/core/seema.py`.
- Start with `GET /slo/status` and look for the `capacity_headroom` item.
  Confirm:
  - `name == "capacity_headroom"`
  - `sample_size > 0`
  - `current_pct < target_pct` (90)
  - `slo_met == false`
- The Prometheus expression is the same logic in a rolling metric view:
  `sum(rate(niyantran_seema_capacity_headroom_pct_sum[10m])) /
  clamp_min(sum(rate(niyantran_seema_capacity_headroom_pct_count[10m])), 1) < 90`
  If you see this query return true in Prometheus, the system is still under
  sustained pressure.
- Check the live governor state in the app or logs: the default limit is
  `SEEMA_REQUEST_LIMIT=4` with a 10-second window. A burst of too many
  external requests arriving in the same short window is the expected cause.
- Common triggers in this repo:
  - a queue or batch job repeatedly calling `GET /investigate` in parallel
  - a downstream client retry storm
  - a large increase in real customer traffic or a misconfigured workflow
    temporarily bypassing the normal load-shedding checks
- If the issue is real, respond by:
  1. confirming the pressure is external and sustained (not a single noisy
     spike)
  2. checking whether the governor is actively throttling requests or
     routing them to lower tiers
  3. reducing or pausing the source burst if it is operationally safe
  4. escalating to the on-call owner if customer impact or compliance risk
     is present
- If the alert is noisy or false-positive, check for stale runtime state or a
  missing reset. `POST /admin/reset` clears SLO and governor memory and is the
  fastest way to confirm a fresh measurement after a manual test or a bad
  deployment.
- For a deeper trace, use Grafana (`:3000`) and Jaeger (`:16687`) together:
  look for repeated `investigation` requests clustered in the same 10-second
  interval and confirm the Seema governor is recording `request_rate_exceeded`
  and/or `slo_breach` reasons on the same traffic pattern.

## Alert-fatigue control

`incident_response.should_page()` dedupes pages for the same incident
class within a 10-minute window; Alertmanager's `alertmanager.yml` adds a
second layer (`repeat_interval: 4h` for SEV2/SEV3, `30m` for SEV1). If
you're being paged repeatedly for the same thing faster than that, the
dedup window itself may need tuning — don't just silence the alert.

## After the incident

Every opened incident has a postmortem shell available at
`GET /incidents/postmortem-template`. Fill in root cause at the SYSTEM
level (a missing check, an unguarded assumption, a monitoring gap) — never
assign it to a person. File concrete remediation action items, and verify
them by deliberately re-triggering the same incident class and confirming
it's now caught faster than it was this time.
