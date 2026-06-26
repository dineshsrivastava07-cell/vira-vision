# CLAUDE.md — VIRA Vision build & deploy runbook

You are operating on an AWS EC2 host (Ubuntu, ap-south-1) inside the `vira-vision` repo.
Execute steps **in order**. Stop at any gate failure and report the exact error.
Do not improvise architecture — the decisions below are fixed.

## Hard constraints
- Claude `ANTHROPIC_API_KEY` must be UNSET. Use `CLAUDE_API_KEY` in `.env` for the NLQ path.
- Ollama runs **natively** on the host (not in Docker) for GPU access.
- Only Open WebUI and vira-tools are containerised.
- Secrets live only in `.env` (gitignored). Never commit `.env`.

## Gate 0 — Config
```bash
cp .env.example .env   # then set: WEBUI_SECRET_KEY, CLAUDE_API_KEY, CH_KEY, TS auth
```

## Gate 1 — Local model
```bash
bash scripts/01-install-ollama.sh
# Must finish with gemma4:12b in `ollama list`
```

## Gate 2 — Preflight
```bash
bash scripts/00-preflight.sh
# ClickHouse SELECT 1 must return HTTP 200
```

## Gate 3 — Validate code
```bash
cd tool-server && python -m py_compile app/*.py && cd ..
python tests/smoke.py    # must print: 0 failed
```

## Gate 4 — Deploy
```bash
bash scripts/02-up.sh
# /healthz must return ok; Open WebUI must answer on :3000
```

## Gate 5 — Wire tools (one-time UI step)
Follow `scripts/03-register-tools.md` in Open WebUI.

## Gate 6 — End-to-end
```bash
bash scripts/04-smoke-test.sh
```
Then ask in chat: *"top 10 stores by net sales last month"* and confirm chart renders.

## On failure
Report: failing step, exact command, stderr, most likely cause. Propose the smallest fix.
Do not retry destructively or change architecture to route around a failure.
