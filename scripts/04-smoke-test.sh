#!/usr/bin/env bash
# End-to-end smoke test against the running tool server.
set -euo pipefail
BASE="${1:-http://localhost:8000}"

echo "1) health"
curl -fs "${BASE}/healthz" | sed 's/^/   /'
echo

echo "2) answer_question (NL -> SQL -> ClickHouse -> chart)"
curl -fs -X POST "${BASE}/answer_question" \
  -H 'Content-Type: application/json' \
  -d '{"question":"top 10 stores by net sales last month"}' \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("   sql:",d.get("sql","")[:120]);print("   rows:",d.get("row_count"),"chart:",d.get("chart_type"))' \
  || echo "   (check CH_KEY / connectivity)"
echo

echo "3) sudhhar_stores (100 Ka Sudhhar)"
curl -fs "${BASE}/sudhhar_stores" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("   flagged:",d.get("flagged_count"),"stores")' \
  || echo "   (check CH_KEY / connectivity)"
echo

echo "4) detect_anomalies"
curl -fs -X POST "${BASE}/detect_anomalies" \
  -H 'Content-Type: application/json' \
  -d '{"metric_sql":"SELECT STORE_ID AS label, sum(NETAMT) AS v FROM vmart_sales.dt_pos_transactional_data WHERE DIVISION NOT IN (\u0027Others\u0027) AND toDate(BILLDATE)=yesterday() GROUP BY STORE_ID","value_field":"v","label_field":"label","threshold":3.0}' \
  | sed 's/^/   /' || echo "   (check connectivity)"
echo
echo "All checks complete."
