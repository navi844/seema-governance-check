"""
Demo runner. Shows the Module 6/7 additions concretely:
  - running the SAME customer many times to trip the cache (M6)
  - running a "high complexity" case to show routing choosing the heavy tier (M6)
  - checking cost attribution and SLO status after a batch of runs (M6/M7)

Run: python agent.py
"""

from src.core.agent_loop import run_investigation, answer_faq
from src.core import cost_attribution, slo, alerting


def demo_caching():
    print("\n=== Caching demo — same FAQ question asked twice ===")
    q = "What counts as transaction structuring under AML rules?"
    first = answer_faq(q)
    second = answer_faq(q)
    print(f"  first call:  cache_hit={first['cache_hit']}  cost_usd={first['cost_usd']}")
    print(f"  second call: cache_hit={second['cache_hit']}  cost_usd={second['cost_usd']}")


def run_batch(customer_id: str = "CUST-10587", n: int = 12):
    print(f"\n=== Running {n} investigations for {customer_id} ===")
    for i in range(n):
        outcome = run_investigation(customer_id, verbose=False)
        print(f"  run {i+1}: cost=${outcome['total_cost_usd']} alerts_fired={len(outcome['alerts_fired'])}")

    print("\n--- Cost attribution by feature ---")
    for row in cost_attribution.attribution_by_feature():
        print(" ", row)

    print("\n--- SLO status ---")
    for s in slo.all_slo_status():
        print(" ", s)

    print("\n--- Recent alerts ---")
    for a in alerting.recent_alerts():
        print(" ", a)


if __name__ == "__main__":
    demo_caching()
    run_batch()
