"""ThoughtSpot REST API v2.0 access for VIRA Vision.

Auth precedence:
  0. TS_SESSION_COOKIE + TS_CSRF_TOKEN  (Google SSO workaround)
  1. TS_BEARER_TOKEN
  2. TS_USERNAME + TS_PASSWORD  -> /auth/token/full
  3. TS_SECRET_KEY  (Trusted Authentication)
"""
from __future__ import annotations
import time
import httpx
from .config import get_settings

S = get_settings()
_token_cache: dict[str, float | str] = {"value": "", "expires_at": 0.0}

def _request_full_token() -> tuple[str, float]:
    body = {"username": S.TS_USERNAME, "password": S.TS_PASSWORD,
            "validity_time_in_sec": S.TS_TOKEN_VALIDITY_S}
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{S.TS_HOST}/api/rest/2.0/auth/token/full", json=body,
                           headers={"Accept": "application/json", "Content-Type": "application/json"})
    if resp.status_code != 200:
        raise RuntimeError(f"ThoughtSpot auth failed {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["token"], data.get("expiration_time_in_millis", 0) / 1000.0

def get_token() -> str:
    if S.TS_BEARER_TOKEN: return S.TS_BEARER_TOKEN
    now = time.time()
    if _token_cache["value"] and float(_token_cache["expires_at"]) - 60 > now:
        return str(_token_cache["value"])
    if S.TS_USERNAME and S.TS_PASSWORD:
        token, expires_at = _request_full_token()
        _token_cache.update(value=token, expires_at=expires_at or (now + S.TS_TOKEN_VALIDITY_S))
        return token
    raise RuntimeError("No ThoughtSpot auth. Set TS_BEARER_TOKEN or TS_USERNAME+TS_PASSWORD.")

def _auth_headers() -> dict[str, str]:
    if S.TS_SESSION_COOKIE and S.TS_CSRF_TOKEN:
        return {"Cookie": S.TS_SESSION_COOKIE, "x-csrf-token": S.TS_CSRF_TOKEN,
                "Accept": "application/json", "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {get_token()}",
            "Accept": "application/json", "Content-Type": "application/json"}

def search_data(query_string: str, worksheet_guid: str | None = None) -> dict:
    guid = worksheet_guid or S.TS_DEFAULT_WORKSHEET
    if not guid: raise RuntimeError("No worksheet GUID and TS_DEFAULT_WORKSHEET unset.")
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{S.TS_HOST}/api/rest/2.0/searchdata",
                           json={"query_string": query_string, "logical_table_identifier": guid},
                           headers=_auth_headers())
    if resp.status_code != 200:
        raise RuntimeError(f"TS searchdata {resp.status_code}: {resp.text[:300]}")
    return resp.json()

def liveboard_data(liveboard_guid: str) -> dict:
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"{S.TS_HOST}/api/rest/2.0/metadata/liveboard/data",
                           json={"metadata_identifier": liveboard_guid}, headers=_auth_headers())
    if resp.status_code != 200:
        raise RuntimeError(f"TS liveboard {resp.status_code}: {resp.text[:300]}")
    return resp.json()

def liveboard_embed_url(liveboard_guid: str) -> str:
    return f"{S.TS_HOST}/#/pinboard/{liveboard_guid}"
