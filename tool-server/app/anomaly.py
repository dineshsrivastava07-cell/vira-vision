"""Z-score anomaly detection over ClickHouse aggregate metrics.

The model decides *what* to check; this code decides *whether it is anomalous*.
"""
from __future__ import annotations
from statistics import mean, pstdev
from . import clickhouse_client as ch

def zscore_anomalies(rows: list[dict], value_field: str, label_field: str,
                     threshold: float = 3.0) -> list[dict]:
    values = [float(r[value_field]) for r in rows if r.get(value_field) is not None]
    if len(values) < 3: return []
    mu, sigma = mean(values), pstdev(values)
    if sigma == 0: return []
    flagged = []
    for r in rows:
        v = r.get(value_field)
        if v is None: continue
        z = (float(v) - mu) / sigma
        if abs(z) >= threshold:
            flagged.append({"label": r.get(label_field), "value": float(v),
                            "zscore": round(z, 2), "direction": "high" if z > 0 else "low"})
    return sorted(flagged, key=lambda x: abs(x["zscore"]), reverse=True)

def detect(metric_sql: str, value_field: str, label_field: str,
           threshold: float = 3.0) -> dict:
    rows = ch.run_query(metric_sql).get("data", [])
    anomalies = zscore_anomalies(rows, value_field, label_field, threshold)
    return {"threshold": threshold, "n_points": len(rows),
            "n_anomalies": len(anomalies), "anomalies": anomalies}
