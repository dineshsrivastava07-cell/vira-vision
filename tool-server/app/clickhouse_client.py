"""ClickHouse access for VIRA Vision.

Rules:
- Auth via X-ClickHouse-User / X-ClickHouse-Key headers (never URL-embedded).
- Read-only: only SELECT/WITH statements sent, readonly=1 param enforced.
- Mandatory business guards injected if the model forgets them.
- BILLDATE is IST wall-clock in UTC-typed column -- no timezone conversion.
"""
from __future__ import annotations
import re
import httpx
from .config import get_settings

S = get_settings()
_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE | re.DOTALL)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|attach|detach|"
    r"optimize|rename|grant|revoke|system|kill)\b", re.IGNORECASE)

class SqlGuardError(ValueError):
    pass

def _division_clause() -> str:
    vals = ", ".join("'" + d.replace("'", "''") + "'" for d in S.EXCLUDED_DIVISIONS)
    return f"DIVISION NOT IN ({vals})"

def enforce_guards(sql: str) -> str:
    sql = sql.strip().rstrip(";").strip()
    if not sql: raise SqlGuardError("Empty query.")
    if ";" in sql: raise SqlGuardError("Multiple statements not allowed.")
    if not _READ_ONLY.match(sql): raise SqlGuardError("Only SELECT/WITH permitted.")
    if _FORBIDDEN.search(sql): raise SqlGuardError("Forbidden keyword in query.")
    if "DIVISION NOT IN" not in sql.upper():
        if re.search(r"\bwhere\b", sql, re.IGNORECASE):
            sql = re.sub(r"\bwhere\b", "WHERE " + _division_clause() + " AND",
                         sql, count=1, flags=re.IGNORECASE)
        else:
            tail = re.search(r"\b(group\s+by|order\s+by|limit)\b", sql, re.IGNORECASE)
            clause = " WHERE " + _division_clause() + " "
            sql = sql[: tail.start()] + clause + sql[tail.start():] if tail else sql + clause
    return sql

def _ch_post(sql: str, extra_params: dict | None = None) -> dict:
    statement = f"{sql.strip().rstrip(';')}\nFORMAT JSON"
    params = {"max_result_rows": str(S.CH_MAX_ROWS), "result_overflow_mode": "break", "readonly": "1", **(extra_params or {})}
    headers = {"X-ClickHouse-User": S.CH_USER, "X-ClickHouse-Key": S.CH_KEY,
               "Content-Type": "text/plain; charset=utf-8"}
    with httpx.Client(timeout=S.CH_TIMEOUT_S) as client:
        resp = client.post(S.CH_URL, params=params, headers=headers, content=statement.encode())
    if resp.status_code != 200:
        raise RuntimeError(f"ClickHouse error {resp.status_code}: {resp.text[:500]}")
    return resp.json()

def run_query(sql: str) -> dict:
    """Execute a guarded NLQ-generated SELECT."""
    return _ch_post(enforce_guards(sql), {"database": S.CH_DATABASE})

def run_analytics_query(sql: str) -> dict:
    """Execute a pre-validated cross-database SQL (no default DB context)."""
    return _ch_post(sql)
