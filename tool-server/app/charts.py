"""Chart-type decision logic (Stage 3 of the NLQ pipeline).

Deterministic rules -- the model picks the question, code picks the chart.
Returns a Vega-Lite v5 spec.
"""
from __future__ import annotations
from datetime import date, datetime

_TIME_HINTS = ("date", "day", "month", "week", "year", "billdate", "period")

def _is_temporal(name: str, sample) -> bool:
    return any(h in name.lower() for h in _TIME_HINTS) or isinstance(sample, (date, datetime))

def _is_numeric(sample) -> bool:
    return isinstance(sample, (int, float)) and not isinstance(sample, bool)

def decide_chart(meta: list[dict], rows: list[dict]) -> dict:
    cols = [m["name"] for m in meta]
    if not rows or len(cols) < 2:
        return {"chart_type": "table", "spec": None}
    first = rows[0]
    dims = [c for c in cols if not _is_numeric(first.get(c))]
    measures = [c for c in cols if _is_numeric(first.get(c))]
    if not measures:
        return {"chart_type": "table", "spec": None}
    x, y = (dims[0] if dims else cols[0]), measures[0]
    temporal = _is_temporal(x, first.get(x))
    mark = "line" if temporal else "bar"
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": rows},
        "mark": mark,
        "encoding": {
            "x": {"field": x, "type": "temporal" if temporal else "nominal",
                  "sort": "-y" if not temporal else None},
            "y": {"field": y, "type": "quantitative"},
        },
        "width": "container", "height": 320,
    }
    return {"chart_type": mark, "spec": spec}
