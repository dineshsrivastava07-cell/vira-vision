# VIRA Vision — Architecture

## Design Principle

**Gemma routes. Deterministic code decides.**

The local 12B model interprets user intent, selects a tool, and narrates results.
Every correctness-critical decision lives in code — SQL safety, mandatory business filters,
chart type selection, anomaly thresholds, workflow routing.
A model mistake degrades phrasing quality; it cannot corrupt data or bypass business rules.

---

## System Architecture

```mermaid
graph TB
    subgraph Client
        U([User / Browser])
    end
    subgraph EC2["AWS EC2 · ap-south-1 · Docker Compose"]
        OW["Open WebUI :3000\nChat surface + tool orchestration"]
        VT["VIRA Tool Server :8000\nFastAPI · OpenAPI · 7 endpoints"]
        OL["Ollama (native on host)\ngemma4:12b\nNL intent + tool selection + narration"]
    end
    subgraph External["External Services"]
        CH[("ClickHouse\nAnalytical data warehouse")]
        TS["ThoughtSpot\nSemantic layer + Liveboards"]
        ANT["Anthropic Claude Haiku\nNLQ SQL generation"]
        WF["Workflow Engine\nn8n / EventBridge"]
    end
    U -->|HTTPS chat| OW
    OW <-->|Ollama API| OL
    OW -->|Native function call\nvia OpenAPI spec| VT
    VT -->|guarded SELECT\nX-ClickHouse-Key header| CH
    VT -->|REST v2\nBearer / Cookie auth| TS
    VT -->|messages.create| ANT
    VT -->|POST webhook| WF
```

---

## Data Flow: `answer_question`

Four-stage pipeline: intent → SQL → guard → execute → chart.

```mermaid
sequenceDiagram
    participant U as User
    participant OW as Open WebUI
    participant VT as Tool Server
    participant CL as Claude Haiku
    participant CH as ClickHouse

    U->>OW: "top 10 stores by net sales last month"
    OW->>VT: POST /answer_question
    VT->>CL: generate_sql(question)
    Note over CL: System prompt =\nschema corpus + few-shot examples
    CL-->>VT: ClickHouse SELECT
    VT->>VT: enforce_guards(sql)\n· read-only check\n· inject DIVISION NOT IN\n· reject forbidden keywords
    VT->>CH: POST sql FORMAT JSON\n(readonly=1, header auth)
    CH-->>VT: {meta, data, rows}
    VT->>VT: decide_chart(meta, rows)\n→ Vega-Lite spec
    VT-->>OW: {sql, rows, chart_type, chart_spec}
    OW-->>U: Table + chart
```

---

## Data Flow: `sudhhar_stores` (100 Ka Sudhaar)

Pre-validated SQL — no NLQ, guaranteed correctness.

```mermaid
sequenceDiagram
    participant U as User
    participant OW as Open WebUI
    participant VT as Tool Server
    participant CH as ClickHouse

    U->>OW: "show 100 ka sudhaar stores"
    OW->>VT: GET /sudhhar_stores
    VT->>CH: _SUDHHAR_SQL (hardcoded, cross-DB)
    Note over CH: Filters in SQL:\n· STORE_TYPE IN (Fashion, Composite, Apparel)\n· REGION != 'WAREHOUSE'\n· gross_margin < 38%\n· sell_thru < 40%\n· sudhaar_score >= 15\nORDER BY sudhaar_score DESC LIMIT 100
    CH-->>VT: flagged stores with metrics
    VT-->>OW: {programme, criteria, flagged_count, stores[]}
    OW-->>U: Ranked underperforming store list
```

---

## Data Flow: `sudhhar_inventory_analysis`

2-step Python merge: Sudhaar list → inventory cost → financial impact.

```mermaid
sequenceDiagram
    participant VT as Tool Server
    participant CH as ClickHouse

    VT->>CH: Step 1: _SUDHHAR_SQL
    CH-->>VT: sudhhar_rows[] (with sell_thru_pct per store)
    VT->>VT: Build store_ids_csv from results
    VT->>CH: Step 2: Inventory SQL\nSELECT store, sum(soh * avg_cost)\nFROM inventory_current\nGLOBAL LEFT JOIN vitem_data (avg COSTRATE/ICODE)\nWHERE STORE_CODE IN (store_ids_csv)
    CH-->>VT: {store_id, inventory_value_locked, total_units_soh}
    VT->>VT: Merge: for each store\n  gap = max(40 - sell_thru, 0)\n  impact = inv_value x (gap / 40)
    VT-->>OW: {total_locked_cr, stores[inv_value_cr, capital_release_cr]}
```

---

## NL→SQL Pipeline (Detail)

```mermaid
flowchart TD
    Q[User question] --> SP[Build system prompt\ntables.yaml + examples.yaml\ninjected wholesale]
    SP --> CM[Claude Haiku API\ntemperature=0, max_tokens=1024]
    CM --> EX[_extract_sql\nstrip markdown fences]
    EX --> EG[enforce_guards\n· non-empty, no semicolons\n· SELECT/WITH only\n· no DDL keywords\n· inject DIVISION NOT IN if missing]
    EG --> RQ[run_query\nPOST to ClickHouse\nreadonly=1, FORMAT JSON]
    RQ --> DC[decide_chart\ntemporal → line\ncategorical → bar]
    DC --> RT[Return: sql + rows + chart_spec]
```

---

## Security Model

| Layer | Mechanism |
|---|---|
| ClickHouse auth | `X-ClickHouse-User` + `X-ClickHouse-Key` headers — never in URL |
| ClickHouse access | `readonly=1` param + SQL guard rejects all non-SELECT |
| Business filters | Injected by `enforce_guards()` even if the LLM omits them |
| ThoughtSpot auth | Cookie+CSRF → Bearer token → Username+Password → Trusted key |
| CORS | `ALLOWED_ORIGINS` env var — tighten from `*` before production |
| Secrets | `.env` gitignored; never hardcoded in source |

---

## Deployment

```
AWS EC2 · ap-south-1
├── Ollama (native, GPU access, always-on)
│   └── gemma4:12b
└── Docker Compose
    ├── open-webui  :3000  ← user-facing chat
    └── vira-tools  :8000  ← tool server (FastAPI)

External (managed, no deploy needed)
├── ClickHouse   (read-only access via API key)
└── ThoughtSpot  (REST v2, trial or managed)
```

**Remote access options** (choose one; do not open ports without TLS):
- SSH tunnel: `ssh -L 3000:localhost:3000 ubuntu@<ec2-ip>`
- Reverse proxy: Caddy or Nginx + TLS on a subdomain
- Cloudflare Tunnel: zero-port-opening, free tier

---

## ClickHouse Schema

```
vmart_sales.dt_pos_transactional_data   ← main POS fact table (Distributed)
vmart_sales.stores                      ← store master
vmart_product.inventory_current         ← current SOH snapshot
vmart_product.vitem_data                ← item/article master (COSTRATE, MRP)
```

Cross-database queries use `GLOBAL LEFT JOIN` (ClickHouse distributed join pattern).
`BILLDATE` is IST wall-clock in a UTC-typed column — no timezone conversion needed.
`COSTRATE` stored as String — use `toFloat64OrZero(COSTRATE)` in all math.
`vitem_data` has multiple rows per ICODE — always pre-aggregate (`avg`) before joining.

---

## Roadmap — Auto Dashboarding

Current gap: charts are returned as Vega-Lite JSON specs but not rendered —
Open WebUI shows tables only. ThoughtSpot-like auto-dashboarding requires 4 phases:

### Phase 1 — Chart Rendering in Chat (1–2 days)

Render charts as base64 PNG or inline Plotly HTML inside the Open WebUI chat bubble.

```mermaid
graph LR
    A[answer_question] --> B[generate SQL + run]
    B --> C[decide_chart]
    C --> D["render_chart(spec, rows)\n→ base64 PNG via Plotly/Kaleido"]
    D --> E["Return chart_image:\ndata:image/png;base64,..."]
    E --> F[Open WebUI renders inline image]
```

**Changes needed:** add `plotly` + `kaleido` to requirements.txt, add `render_chart()` to
`charts.py`, return `chart_image` field from `answer_question`.

### Phase 2 — Auto Dashboard Endpoint (3–4 days)

One API call → full HTML page with 4–6 charts for a business topic.

```mermaid
graph TD
    A["GET /auto_dashboard?topic=store_performance"] --> B[DASHBOARD_TEMPLATES\ntopic → list of SQL queries]
    B --> C1[Query 1: Top stores by sales]
    B --> C2[Query 2: Zone breakdown]
    B --> C3[Query 3: Trend last 30d]
    B --> C4[Query 4: ATV vs UPT]
    C1 & C2 & C3 & C4 --> D[Compose single HTML page\nPlotly.js charts embedded]
    D --> E[Return text/html or save as pinboard]
```

Starter topics: `store_performance`, `sudhhar_overview`, `inventory_health`, `zone_comparison`.

### Phase 3 — Pinboards / Saved Dashboards (3–5 days)

Save, name, and reload multi-chart dashboards. Data refreshes live on every load.

```mermaid
graph LR
    A[User: save this dashboard] --> B["POST /pinboard/save\n{name, queries[], chart_types[]}"]
    B --> C[(SQLite pinboard store)]
    D[User: open weekly ops] --> E["GET /pinboard/weekly-ops"]
    E --> C
    C --> F[Re-run queries against live ClickHouse]
    F --> G[Render fresh Plotly charts]
    G --> H[Return HTML dashboard]
```

### Phase 4 — Apache Superset (1–2 weeks)

Add Superset to Docker Compose as a proper self-serve BI surface.

```mermaid
graph TB
    subgraph EC2
        OW["Open WebUI :3000\nChat + NLQ"]
        VT["VIRA Tool Server :8000\nGoverned endpoints"]
        SS["Apache Superset :8088\nDrag-and-drop dashboards"]
        OL[Ollama gemma4:12b]
    end
    CH[(ClickHouse)]
    OW --> VT & OL
    VT --> CH
    SS -->|read-only user| CH
```

Superset connects directly to ClickHouse with a read-only credential.
`vira-tools` remains the governed layer for chat; Superset serves power users.

---

## Phased Delivery

| Phase | Milestone |
|---|---|
| 1 — Foundation | Ollama + gemma4:12b, CH/TS connectivity, schema corpus |
| 2 — Core | Tool server live, NLQ validated on real schema, Open WebUI wired |
| 3 — Capabilities | 100 Ka Sudhaar, inventory analysis, anomaly checks, first webhook |
| 4 — Hardening | Tighten CORS, dedicated TS service account, reverse proxy + TLS |
| 5 — Auto Dashboard | Chart rendering, auto-dashboard endpoint, pinboards, Superset |
