# Niyantran architecture

```mermaid
flowchart LR
    User["User / Operator"] --> API["FastAPI app\napp.py"]

    API --> Investigate["Investigation endpoint\n/investigate"]
    API --> SLO["SLO status\n/slo/status"]
    API --> Cost["Cost / anomaly endpoints\n/cost/*"]
    API --> Alerts["Alert endpoints\n/alerts / /incidents"]

    Investigate --> Agent["Agent loop\nagent_loop.py"]
    Agent --> Route["Routing + Seema governor\nrouting.py + seema.py"]
    Route --> Light["Light tier\nfaq / low-priority traffic"]
    Route --> Heavy["Heavy tier\nsub-agent / high-complexity work"]

    Agent --> Tools["Investigation tools\nKYC / transactions / watchlist / evidence"]
    Agent --> Cache["Cache layer\ncaching.py"]
    Agent --> CostAttr["Cost attribution\ncost_attribution.py"]
    Agent --> Eval["Online eval\nonline_eval.py"]
    Agent --> Drift["Drift detection\ndrift.py"]
    Agent --> SLOState["SLO state\nslo.py"]
    Agent --> Alerting["Alerting + incident classification\nalerting.py + incident_response.py"]

    Tools --> Metrics["OTel metrics\nmetrics.py"]
    Cache --> Metrics
    CostAttr --> Metrics
    Eval --> Metrics
    Drift --> Metrics
    Route --> Metrics
    SLOState --> Metrics
    Alerting --> Metrics

    Metrics --> OTel["OpenTelemetry Collector\notel-collector"]
    OTel --> Jaeger["Jaeger\ntraces"]
    OTel --> Prom["Prometheus\nmetrics + rules"]
    Prom --> AlertManager["Alertmanager"]
    Prom --> Grafana["Grafana dashboard"]
    AlertManager --> Pager["On-call page / review"]

    User --> Grafana
    User --> Prom
    User --> Jaeger

    classDef app fill:#e8f1ff,stroke:#4b7bec,color:#111827;
    classDef signal fill:#eefaf2,stroke:#2ecc71,color:#111827;
    classDef ops fill:#fff4e5,stroke:#f39c12,color:#111827;

    class API,Investigate,Agent,Route,Light,Heavy,Tools,Cache,CostAttr,Eval,Drift,SLOState,Alerting app;
    class Metrics,OTel,Jaeger,Prom,AlertManager,Grafana,SLO,Cost,Alerts signal;
    class Pager ops;
```

This architecture shows the end-to-end control loop of the assignment:

- external traffic enters the FastAPI app
- the agent loop routes work through the Seema governor
- cost, cache, eval, drift, SLO, and incident signals are emitted as OTel metrics
- Prometheus evaluates sustained alert rules
- Grafana and Alertmanager provide operational visibility and paging

The design deliberately couples a real service path with a fully observable operations plane, so the same request can be traced, measured, and reasoned about end-to-end.
