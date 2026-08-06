"""
DataForSEO traffic-data provider.

Uses the DataForSEO Labs 'Domain Rank Overview' endpoint, which returns organic
and paid search-traffic metrics — importantly including an estimated monthly
paid-traffic cost that we can use as ad spend directly (no CPC assumption).

Why this over Apify:
    - Official, subscription-free (pay-as-you-go, $50 min deposit, $1 free trial).
    - No scraper flakiness.
    - Real ad-spend figure (`estimated_paid_traffic_cost`), not a modelled guess.

Endpoint:
    POST https://api.dataforseo.com/v3/dataforseo_labs/google/domain_rank_overview/live
    Auth: HTTP Basic (username = your DataForSEO login/email, password = API key)
    Body: [{"target": "hubspot.com", "location_code": 2840, "language_code": "en"}]

Env vars:
    DATAFORSEO_LOGIN     — your DataForSEO account login (email)
    DATAFORSEO_PASSWORD  — your API password / key
    DATAFORSEO_LOCATION  — optional, default '2840' (United States); see
                           https://docs.dataforseo.com/v3/appendix/locations/
    DATAFORSEO_LANGUAGE  — optional, default 'en'

Nothing here caches results. Nothing writes secrets to logs.
"""

from __future__ import annotations

import base64
import os

try:
    import httpx
except Exception:
    httpx = None


ENDPOINT = "https://api.dataforseo.com/v3/dataforseo_labs/google/domain_rank_overview/live"


def _creds() -> tuple[str, str] | None:
    login = os.environ.get("DATAFORSEO_LOGIN")
    password = os.environ.get("DATAFORSEO_PASSWORD")
    if login and password:
        return login, password
    return None


def _auth_header(creds: tuple[str, str]) -> str:
    raw = f"{creds[0]}:{creds[1]}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def enabled() -> bool:
    return _creds() is not None and httpx is not None


def estimate(domain: str) -> dict | None:
    """Provider entry point used by traffic.py. Returns the same shape the
    other providers do (or None on any failure)."""
    result, _ = _fetch(domain)
    return result


def diagnose(domain: str) -> dict:
    """Human-readable check for /api/dataforseo-debug — never returns the key."""
    info: dict = {"provider": "dataforseo", "domain": domain,
                  "build": "dataforseo-v1", "endpoint": ENDPOINT}
    creds = _creds()
    info["credentials_present"] = bool(creds)
    if creds:
        info["login_prefix"] = creds[0][:4] + "..."
    if httpx is None:
        info["status"] = "httpx not installed on the server."
        return info
    if not creds:
        info["status"] = "Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD to enable."
        return info
    result, dbg = _fetch(domain)
    info.update(dbg)
    if result:
        info["result"] = result
        info["status"] = "OK — DataForSEO parsed. The report will show these estimates."
    else:
        info["status"] = ("Reached DataForSEO but couldn't extract usable metrics. "
                          "Check http_status, task_status_code and snippet above.")
    return info


# ---------------------------------------------------------------------------
def _fetch(domain: str) -> tuple[dict | None, dict]:
    creds = _creds()
    if not creds or httpx is None:
        return None, {"error": "no credentials / httpx"}

    location_code = int(os.environ.get("DATAFORSEO_LOCATION", "2840"))
    language_code = os.environ.get("DATAFORSEO_LANGUAGE", "en")
    body = [{
        "target": domain,
        "location_code": location_code,
        "language_code": language_code,
        # Include projected metrics too — some accounts get richer data when
        # this flag is set; unknown flags are ignored by the API.
        "include_serp_info": False,
    }]
    headers = {
        "Authorization": _auth_header(creds),
        "Content-Type": "application/json",
    }
    dbg: dict = {"location_code": location_code, "language_code": language_code}
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(ENDPOINT, headers=headers, json=body)
        dbg["http_status"] = r.status_code
        text = r.text or ""
        dbg["snippet"] = text[:400]
        if r.status_code >= 300:
            return None, dbg
        payload = r.json()
    except Exception as e:
        dbg["error"] = str(e)
        return None, dbg

    # DataForSEO wraps everything in { tasks: [ { status_code, result: [...] } ] }
    tasks = payload.get("tasks") or []
    if not tasks:
        return None, dbg
    task = tasks[0]
    dbg["task_status_code"] = task.get("status_code")
    dbg["task_status_message"] = task.get("status_message")
    results = task.get("result") or []
    if not results:
        return None, dbg
    result = results[0]
    if not isinstance(result, dict):
        return None, dbg

    metrics = result.get("metrics") or {}
    organic = metrics.get("organic") or {}
    paid = metrics.get("paid") or {}
    dbg["metrics_keys"] = {"organic": list(organic.keys())[:20],
                           "paid": list(paid.keys())[:20]}

    # `etv` (Estimated Traffic Volume) is a monthly click-count estimate per
    # DataForSEO — the closest analogue to Similarweb's "visits". We use
    # organic+paid ETV as our monthly-visits proxy for the search channel.
    organic_visits = _num(organic.get("etv"))
    paid_visits = _num(paid.get("etv"))
    total_visits = int(round((organic_visits or 0) + (paid_visits or 0)))
    if total_visits <= 0:
        # Some domains return count=0 across the board — nothing usable.
        return None, dbg

    # `estimated_paid_traffic_cost` is the total monthly $ that a domain would
    # be paying to buy the equivalent paid traffic — i.e. their ad spend.
    ad_spend = (_num(paid.get("estimated_paid_traffic_cost"))
                or _num(paid.get("impressions_estimated_paid_traffic_cost"))
                or 0.0)
    paid_share = (paid_visits / (organic_visits + paid_visits)
                  if (organic_visits + paid_visits) > 0 else 0.0)

    result_dict = {
        "monthly_visits": total_visits,
        "paid_share": round(paid_share, 4),
        "monthly_ad_spend": round(ad_spend, 2),
        "avg_cpc": None,   # DataForSEO returns spend directly, not CPC.
        "source": "DataForSEO Labs (Google Domain Rank Overview)",
        "estimated": True,
    }
    return result_dict, dbg


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None
    return None
