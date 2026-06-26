#!/usr/bin/env bash
# Preflight: verify host can reach all dependencies before building.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== VIRA Vision preflight =="
[ -f .env ] || { echo "FAIL: .env missing. Run: cp .env.example .env"; exit 1; }
set -a; . ./.env; set +a
command -v docker >/dev/null || { echo "FAIL: docker not installed"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "FAIL: docker compose v2 missing"; exit 1; }
echo "OK: docker + compose"
for p in 3000 8000; do
  ss -ltn 2>/dev/null | grep -q ":$p " && echo "WARN: port $p in use"
done
if [ -n "${CH_KEY:-}" ]; then
  code=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "X-ClickHouse-User: ${CH_USER}" -H "X-ClickHouse-Key: ${CH_KEY}" \
    --data-binary "SELECT 1" "${CH_URL}" || true)
  echo "ClickHouse SELECT 1 -> HTTP ${code}"
else
  echo "SKIP: CH_KEY empty"
fi
[ -n "${TS_HOST:-}" ] && {
  ts_code=$(curl -s -o /dev/null -w "%{http_code}" "${TS_HOST}/callosum/v1/ping" || true)
  echo "ThoughtSpot ping -> HTTP ${ts_code}"
}
echo "== preflight done =="
