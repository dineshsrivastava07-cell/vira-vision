"""VIRA Vision -- OpenAPI tool server + OpenAI-compatible proxy.

Open WebUI ingests /openapi.json and exposes endpoints as native tools.
Also serves /v1/models and /v1/chat/completions so Open WebUI can use
Claude as the chat model on the same port.

In Open WebUI -> Connections -> OpenAI API: URL = http://vira-tools:8000/v1
Docs: http://<host>:8000/docs
"""
from __future__ import annotations
import json, time
import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from . import anomaly, charts, nlq, workflows
from . import clickhouse_client as ch
from . import thoughtspot_client as ts
from .config import get_settings

S = get_settings()
app = FastAPI(
    title="VIRA Vision", version="1.0.0",
    description="Self-service retail analytics: NL->SQL, 100 Ka Sudhaar, inventory analysis, anomaly detection, workflow automation.",
)
app.add_middleware(CORSMiddleware, allow_origins=S.ALLOWED_ORIGINS,
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

# ---------------------------------------------------------------------------
# Pre-validated cross-database SQL -- NOT NLQ-generated.
# Business rules baked in: STORE_TYPE whitelist, REGION != WAREHOUSE,
# 6-month lookback, sudhaar_score >= 15 threshold.
# ---------------------------------------------------------------------------
_SUDHHAR_SQL = """
SELECT
  t.STORE_ID,
  ifNull(s.STORE_NAME, t.STORE_ID)                                               AS store_name,
  s.STORE_TYPE, s.ZONE, s.REGION,
  round(sum(t.NETAMT), 0)                                                         AS net_sales_6m,
  round(sum(t.NETAMT) / 6, 0)                                                     AS avg_monthly_sales,
  round(sum(t.NETAMT) / nullIf(count(DISTINCT t.BILLNO), 0), 0)                  AS atv,
  round(sum(t.QTY)    / nullIf(count(DISTINCT t.BILLNO), 0), 1)                  AS upt,
  round(sum(t.DISCOUNTAMT) / nullIf(sum(t.GROSSAMT), 0) * 100, 1)                AS discount_pct,
  round(
    (sum(t.NETAMT) - sum(t.QTY * toFloat64OrZero(v.COSTRATE)))
    / nullIf(sum(t.NETAMT), 0) * 100, 1)                                          AS gross_margin_pct,
  round(
    sum(t.QTY) / nullIf(sum(t.QTY) + any(i.store_soh), 0) * 100, 1)             AS sell_thru_pct,
  any(i.store_soh)                                                                 AS current_soh,
  round(
    (38 - ((sum(t.NETAMT) - sum(t.QTY * toFloat64OrZero(v.COSTRATE)))
           / nullIf(sum(t.NETAMT), 0) * 100))
    + (40 - (sum(t.QTY) / nullIf(sum(t.QTY) + any(i.store_soh), 0) * 100)), 1)  AS sudhaar_score
FROM vmart_sales.dt_pos_transactional_data t
GLOBAL LEFT JOIN vmart_sales.stores s ON s.CODE = t.STORE_ID
GLOBAL LEFT JOIN (SELECT ICODE, COSTRATE FROM vmart_product.vitem_data) v ON v.ICODE = t.ICODE
GLOBAL LEFT JOIN (
  SELECT STORE_CODE, sum(SOH) AS store_soh FROM vmart_product.inventory_current GROUP BY STORE_CODE
) i ON i.STORE_CODE = t.STORE_ID
WHERE t.DIVISION NOT IN ('Others','Fixed Assets','Repair and Maintenance','Marketing N Advertisement')
  AND s.ACTIVE     = 'TRUE'
  AND s.STORE_TYPE IN ('Fashion','Composite','Apparel')
  AND s.REGION    != 'WAREHOUSE'
  AND toDate(t.BILLDATE) >= addMonths(today(), -6)
GROUP BY t.STORE_ID, store_name, s.STORE_TYPE, s.ZONE, s.REGION
HAVING gross_margin_pct < 38 AND sell_thru_pct < 40 AND net_sales_6m > 0 AND sudhaar_score >= 15
ORDER BY sudhaar_score DESC
LIMIT 100
"""

# ===========================================================================
# OpenAI-compatible proxy (hidden from OpenAPI tool schema)
# ===========================================================================
@app.get("/v1/models", include_in_schema=False)
def list_models():
    return {"object": "list", "data": [{"id": S.CLAUDE_MODEL, "object": "model",
            "created": 1699000000, "owned_by": "anthropic"}]}

@app.post("/v1/chat/completions", include_in_schema=False)
async def chat_completions(request: Request):
    body = await request.json()
    messages, model = body.get("messages", []), body.get("model", S.CLAUDE_MODEL)
    max_tokens, temperature, do_stream = body.get("max_tokens", 4096), body.get("temperature", 0.0), body.get("stream", False)
    system, filtered = None, []
    for msg in messages:
        if msg.get("role") == "system": system = msg["content"]
        else: filtered.append({"role": msg["role"], "content": msg["content"]})
    if not filtered: filtered = [{"role": "user", "content": "Hello"}]
    client = anthropic.Anthropic(api_key=S.CLAUDE_API_KEY)
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": filtered}
    if system: kwargs["system"] = system
    if do_stream:
        def generate():
            with client.messages.stream(**kwargs) as s:
                for text in s.text_stream:
                    chunk = {"id": "chatcmpl-vira", "object": "chat.completion.chunk",
                             "created": int(time.time()), "model": model,
                             "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
                    yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream")
    resp = client.messages.create(**kwargs)
    return {"id": resp.id, "object": "chat.completion", "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": resp.content[0].text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": resp.usage.input_tokens, "completion_tokens": resp.usage.output_tokens,
                      "total_tokens": resp.usage.input_tokens + resp.usage.output_tokens}}

# --------------------------------------------------------------------------- #
# 1. Self-service NLQ
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    question: str = Field(..., description="Business question in plain English, e.g. 'top 10 stores by revenue last month'.")

@app.post("/answer_question", operation_id="answer_question", summary="Answer a data question")
def answer_question(req: AskRequest):
    """Convert a natural-language question to ClickHouse SQL, run it, return rows + chart spec.

    Use for any quantitative retail question (sales, ATV, UPT, inventory, store performance,
    region/zone analysis). Do NOT use for 100 Ka Sudhaar -- call sudhhar_stores instead.
    """
    try:
        sql = ch.enforce_guards(nlq.generate_sql(req.question))
        result = ch.run_query(sql)
        meta, rows = result.get("meta", []), result.get("data", [])
        chart = charts.decide_chart(meta, rows)
        return {"sql": sql, "row_count": len(rows), "rows": rows[:200],
                "chart_type": chart["chart_type"], "chart_spec": chart["spec"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --------------------------------------------------------------------------- #
# 1b. 100 Ka Sudhhar
# --------------------------------------------------------------------------- #
@app.get("/sudhhar_stores", operation_id="sudhhar_stores", summary="100 Ka Sudhhar stores list")
def sudhhar_stores():
    """Return the 100 Ka Sudhhar underperforming store list.

    Flags active Fashion/Composite/Apparel stores (non-Warehouse) that over the
    last 6 months have: gross margin < 38% AND sell-thru < 40% AND sudhaar_score >= 15.
    Sorted by sudhaar_score DESC (higher = worse). Max 100 stores.

    ALWAYS call for: '100 ka sudhar', 'sudhhar stores', underperforming stores,
    weak stores, stores needing improvement, turnaround stores, store health flag.
    """
    try:
        rows = ch.run_analytics_query(_SUDHHAR_SQL).get("data", [])
        return {"programme": "100 Ka Sudhhar",
                "criteria": {"gross_margin_pct_below": 38, "sell_thru_pct_below": 40,
                              "sudhaar_score_minimum": 15, "period_months": 6,
                              "store_types_included": ["Fashion","Composite","Apparel"],
                              "warehouse_excluded": True},
                "flagged_count": len(rows), "stores": rows}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --------------------------------------------------------------------------- #
# 1c. 100 Ka Sudhhar -- inventory analysis
# --------------------------------------------------------------------------- #
@app.get("/sudhhar_inventory_analysis", operation_id="sudhhar_inventory_analysis",
         summary="100 Ka Sudhhar -- inventory value locked")
def sudhhar_inventory_analysis():
    """Inventory value locked and capital release potential for 100 Ka Sudhhar stores.

    Per store: inventory_value_locked_cr (SOH x avg cost, in Crores), total_units_soh,
    sell_thru_gap_pct, capital_release_if_target_met_cr (value freed at 40% sell-thru).

    ALWAYS call for: inventory value, locked capital, stock value, money stuck in inventory,
    financial impact of sell-through, excess stock analysis.
    """
    try:
        sudhhar_rows = ch.run_analytics_query(_SUDHHAR_SQL).get("data", [])
        if not sudhhar_rows:
            return {"store_count": 0, "stores": [], "total_inventory_value_locked_cr": 0}
        store_ids_csv = ",".join(f"'{r['STORE_ID']}'" for r in sudhhar_rows)
        inv_sql = f"""
SELECT i.STORE_CODE AS store_id,
       round(sum(i.soh * v.avg_cost), 0) AS inventory_value_locked,
       sum(i.soh) AS total_units_soh
FROM (
    SELECT STORE_CODE, ICODE, sum(SOH) AS soh
    FROM vmart_product.inventory_current
    WHERE STORE_CODE IN ({store_ids_csv})
    GROUP BY STORE_CODE, ICODE
) i
GLOBAL LEFT JOIN (
    SELECT ICODE, avg(toFloat64OrZero(COSTRATE)) AS avg_cost
    FROM vmart_product.vitem_data WHERE toFloat64OrZero(COSTRATE) > 0
    GROUP BY ICODE
) v ON v.ICODE = i.ICODE
GROUP BY i.STORE_CODE
"""
        inv_by_store = {r["store_id"]: r for r in ch.run_analytics_query(inv_sql).get("data", [])}
        SELL_THRU_TARGET = 40.0
        stores_out = []
        for row in sudhhar_rows:
            sid = row["STORE_ID"]
            inv = inv_by_store.get(sid, {})
            inv_value = inv.get("inventory_value_locked", 0) or 0
            soh_units = inv.get("total_units_soh", 0) or 0
            store_sell_thru = row.get("sell_thru_pct", 0) or 0
            gap = max(SELL_THRU_TARGET - store_sell_thru, 0)
            impact = round(inv_value * (gap / SELL_THRU_TARGET), 0)
            stores_out.append({
                "store_id": sid, "store_name": row.get("store_name"),
                "zone": row.get("ZONE"), "region": row.get("REGION"),
                "net_sales_6m_cr": round((row.get("net_sales_6m") or 0) / 1e7, 2),
                "store_sell_thru_pct": store_sell_thru, "sell_thru_target_pct": SELL_THRU_TARGET,
                "sell_thru_gap_pct": round(gap, 1), "gross_margin_pct": row.get("gross_margin_pct"),
                "inventory_value_locked_cr": round(inv_value / 1e7, 2),
                "total_units_soh": soh_units,
                "capital_release_if_target_met_cr": round(impact / 1e7, 2),
            })
        stores_out.sort(key=lambda x: x["inventory_value_locked_cr"], reverse=True)
        return {"programme": "100 Ka Sudhhar -- Inventory Analysis",
                "sell_thru_target_pct": SELL_THRU_TARGET,
                "total_inventory_value_locked_cr": round(sum(s["inventory_value_locked_cr"] for s in stores_out), 2),
                "total_capital_release_if_target_met_cr": round(sum(s["capital_release_if_target_met_cr"] for s in stores_out), 2),
                "store_count": len(stores_out), "stores": stores_out}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --------------------------------------------------------------------------- #
# 2. Governed search (ThoughtSpot)
# --------------------------------------------------------------------------- #
class SearchRequest(BaseModel):
    query_string: str = Field(..., description="ThoughtSpot search tokens, e.g. '[revenue] [store name] top 10 last month'.")
    worksheet_guid: str | None = Field(None, description="Worksheet GUID. Omit to use TS_DEFAULT_WORKSHEET.")

@app.post("/governed_search", operation_id="governed_search", summary="Governed metric search")
def governed_search(req: SearchRequest):
    """Run a governed query through ThoughtSpot against a curated semantic worksheet.
    Use when the answer must follow official metric definitions, not ad-hoc SQL.
    """
    try: return ts.search_data(req.query_string, req.worksheet_guid)
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

# --------------------------------------------------------------------------- #
# 3. Anomaly detection
# --------------------------------------------------------------------------- #
class AnomalyRequest(BaseModel):
    metric_sql: str = Field(..., description="Read-only aggregate SELECT with a label and numeric value column.")
    value_field: str = Field(..., description="Name of the numeric column to test.")
    label_field: str = Field(..., description="Name of the label/dimension column.")
    threshold: float = Field(3.0, description="Z-score magnitude to flag (default 3.0).")

@app.post("/detect_anomalies", operation_id="detect_anomalies", summary="Detect outliers")
def detect_anomalies(req: AnomalyRequest):
    """Flag statistical outliers (z-score) across a dimension. Use for proactive ops checks."""
    try: return anomaly.detect(req.metric_sql, req.value_field, req.label_field, req.threshold)
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

# --------------------------------------------------------------------------- #
# 4. ThoughtSpot Liveboard
# --------------------------------------------------------------------------- #
class LiveboardRequest(BaseModel):
    liveboard_guid: str = Field(..., description="GUID of the ThoughtSpot Liveboard.")
    with_data: bool = Field(False, description="Also return the underlying tile data.")

@app.post("/open_liveboard", operation_id="open_liveboard", summary="Open a dashboard")
def open_liveboard(req: LiveboardRequest):
    """Return a link to a ThoughtSpot Liveboard (comments, sharing, KPI alerts)."""
    try:
        out = {"embed_url": ts.liveboard_embed_url(req.liveboard_guid)}
        if req.with_data: out["data"] = ts.liveboard_data(req.liveboard_guid)
        return out
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

# --------------------------------------------------------------------------- #
# 5. Workflow automation
# --------------------------------------------------------------------------- #
class WorkflowRequest(BaseModel):
    name: str = Field(..., description="Registered workflow name (webhook path).")
    params: dict | None = Field(None, description="JSON parameters for the workflow.")

@app.post("/trigger_workflow", operation_id="trigger_workflow", summary="Trigger a workflow")
def trigger_workflow(req: WorkflowRequest):
    """Fire a named webhook workflow (n8n, EventBridge, etc.) with parameters."""
    try: return workflows.trigger(req.name, req.params)
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@app.get("/healthz", operation_id="healthz", summary="Health check")
def healthz():
    return {"status": "ok", "service": "vira-vision", "model": S.CLAUDE_MODEL}
