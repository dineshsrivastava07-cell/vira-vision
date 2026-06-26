"""Trigger named operational workflows via webhook.

VIRA does not own workflow logic -- it hands off to an external engine
(n8n, EventBridge, etc.). The model triggers; the engine executes.
"""
from __future__ import annotations
import httpx
from .config import get_settings

S = get_settings()

def trigger(name: str, params: dict | None = None) -> dict:
    if not S.WORKFLOW_WEBHOOK_BASE:
        raise RuntimeError("WORKFLOW_WEBHOOK_BASE is not configured.")
    url = f"{S.WORKFLOW_WEBHOOK_BASE.rstrip('/')}/{name}"
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, json=params or {})
    return {"workflow": name, "status_code": resp.status_code,
            "ok": resp.is_success, "response": resp.text[:500]}
