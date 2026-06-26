#!/usr/bin/env bash
# Build and start Open WebUI + VIRA tool server.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Run: cp .env.example .env  and fill secrets first."; exit 1; }
docker compose up -d --build
echo "Waiting for tool server..."
for i in $(seq 1 30); do
  curl -fs http://localhost:8000/healthz >/dev/null 2>&1 && { echo "tool server: healthy"; break; }
  sleep 2
  [ "$i" = "30" ] && { echo "ERROR: tool server unhealthy"; docker compose logs --tail=50 vira-tools; exit 1; }
done
echo "Waiting for Open WebUI..."
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 || true)
  [ "$code" = "200" ] && { echo "Open WebUI: up on :3000"; break; }
  sleep 2
done
echo
echo "Stack is up."
echo "  Open WebUI  http://localhost:3000"
echo "  Tool docs   http://localhost:8000/docs"
echo "Next: follow scripts/03-register-tools.md"
