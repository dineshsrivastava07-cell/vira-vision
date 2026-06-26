"""Offline unit checks -- no network required.
Run: python tests/smoke.py
Validates SQL guard, chart selection, and anomaly math in isolation.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tool-server"))
from app.clickhouse_client import enforce_guards, SqlGuardError
from app.charts import decide_chart
from app.anomaly import zscore_anomalies

passed = failed = 0

def check(name, cond):
    global passed, failed
    if cond: passed += 1; print(f"  PASS  {name}")
    else:    failed += 1; print(f"  FAIL  {name}")

def rejects(sql):
    try: enforce_guards(sql); return False
    except SqlGuardError: return True

print("SQL guard:")
check("blocks DELETE", rejects("DELETE FROM t"))
check("blocks multi-statement", rejects("SELECT 1; SELECT 2"))
check("blocks DDL", rejects("SELECT 1 FROM x; DROP TABLE x"))
g1 = enforce_guards("SELECT STORE_CODE, sum(NETAMT) v FROM dt_pos_transactional_data GROUP BY STORE_CODE")
check("injects DIVISION NOT IN when missing", "DIVISION NOT IN" in g1.upper())
g2 = enforce_guards("SELECT * FROM t WHERE toDate(BILLDATE)=today()")
check("injects filter with existing WHERE", "DIVISION NOT IN" in g2.upper() and "BILLDATE" in g2)

print("Chart:")
meta = [{"name": "day", "type": "Date"}, {"name": "net_sales", "type": "Float64"}]
rows = [{"day": "2026-06-01", "net_sales": 10.0}, {"day": "2026-06-02", "net_sales": 12.0}]
check("temporal -> line", decide_chart(meta, rows)["chart_type"] == "line")
meta2 = [{"name": "store", "type": "String"}, {"name": "v", "type": "Float64"}]
rows2 = [{"store": f"S{i}", "v": float(i)} for i in range(5)]
check("category -> bar", decide_chart(meta2, rows2)["chart_type"] == "bar")

print("Anomaly:")
series = [{"label": f"S{i}", "v": 100.0} for i in range(10)] + [{"label": "S_out", "v": 1000.0}]
flagged = zscore_anomalies(series, "v", "label", threshold=2.0)
check("flags the outlier", any(a["label"] == "S_out" for a in flagged))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
