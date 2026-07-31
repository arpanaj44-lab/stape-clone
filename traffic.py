"""
Traffic-intelligence provider layer.

Stape's report shows estimated monthly visits and paid ad spend, which do NOT
come from scanning the page — they come from a third-party traffic-data provider
(Similarweb-style). This module is a small pluggable adapter around that idea.

Select a provider with the TRAFFIC_PROVIDER env var:

    apify        -> an Apify traffic actor      (needs APIFY_TOKEN; APIFY_ACTOR_ID optional)
    similarweb   -> official Similarweb API      (needs SIMILARWEB_API_KEY)
    manual       -> fixed numbers from env       (MONTHLY_VISITS, MONTHLY_AD_SPEND, PAID_SHARE)
    mock         -> deterministic demo numbers derived from the domain (clearly labelled)
    none/unset   -> no data; the ad-spend section shows a "connect an API" note

Every adapter returns the same shape (or None):

    {
      "monthly_visits": int,
      "paid_share": float,          # 0..1 share of visits from paid channels
      "monthly_ad_spend": float,    # USD, may be estimated from visits*cpc
      "avg_cpc": float,             # USD
      "source": str,                # human label shown in the report
      "estimated": bool,            # True if any field was inferred, not measured
    }

Nothing here fabricates numbers silently: mock/estimated results are always
flagged so the UI can label them.
"""

from __future__ import annotations

import hashlib
import os
from datetime import date, timedelta

try:
    import httpx
except Exception:  # httpx optional until a real API is used
    httpx = None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def estimate(domain: str) -> dict | None:
    provider = os.environ.get("TRAFFIC_PROVIDER", "").strip().lower()
    if not provider or provider == "none":
        return None
    if provider == "manual":
        return _manual(domain)
    if provider == "mock":
        return _mock(domain)
    if provider == "apify":
        return _apify(domain)
    if provider == "similarweb":
        return _similarweb(domain)
    return None


# ---------------------------------------------------------------------------
def _manual(domain: str) -> dict | None:
    visits = os.environ.get("MONTHLY_VISITS")
    if not visits:
        return None
    visits = int(float(visits))
    paid_share = _env_float("PAID_SHARE", 0.12)
    avg_cpc = _env_float("AVG_CPC", 1.20)
    spend_env = os.environ.get("MONTHLY_AD_SPEND")
    spend = float(spend_env) if spend_env else round(visits * paid_share * avg_cpc, 2)
    return {
        "monthly_visits": visits,
        "paid_share": paid_share,
        "monthly_ad_spend": spend,
        "avg_cpc": avg_cpc,
        "source": "Manual input",
        "estimated": bool(spend_env is None),
    }


def _mock(domain: str) -> dict:
    """Deterministic pseudo-numbers so the demo/section is exercisable offline."""
    h = int(hashlib.sha256(domain.encode()).hexdigest(), 16)
    visits = 15000 + (h % 90000)          # 15k..105k
    paid_share = 0.08 + (h % 15) / 100     # 8%..22%
    avg_cpc = _env_float("AVG_CPC", 1.20)
    spend = round(visits * paid_share * avg_cpc, 2)
    return {
        "monthly_visits": visits,
        "paid_share": round(paid_share, 3),
        "monthly_ad_spend": spend,
        "avg_cpc": avg_cpc,
        "source": "Demo estimate (mock provider)",
        "estimated": True,
    }


def _coerce_number(v) -> float | None:
    """Turn values like 1234, '1,234', '1.2M', '500K', '3.4B' into a float."""
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().replace(",", "").replace("$", "")
    if not s:
        return None
    mult = 1.0
    if s[-1:].upper() in ("K", "M", "B"):
        mult = {"K": 1e3, "M": 1e6, "B": 1e9}[s[-1].upper()]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _deep_find(obj, key_matches, value_test):
    """
    Recursively search a nested dict/list for the first value whose *key* matches
    any predicate in key_matches and whose coerced value passes value_test.
    Returns the coerced float, or None. Makes us resilient to differing actor
    output schemas (monthlyVisits vs total_visits vs visits, etc.).
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(m(kl) for m in key_matches):
                num = _coerce_number(v)
                if num is not None and value_test(num):
                    return num
        for v in obj.values():
            found = _deep_find(v, key_matches, value_test)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _deep_find(v, key_matches, value_test)
            if found is not None:
                return found
    return None


# Key predicates + extractor shared by the live adapter and the diagnostics.
_VISIT_KEYS = [
    lambda k: ("visit" in k and ("month" in k or "total" in k or "estimat" in k)),
    lambda k: k in ("visits", "traffic", "monthlyvisits", "estimatedvisits"),
]
_PAID_KEYS = [lambda k: "paid" in k]
_CPC_KEYS = [lambda k: "cpc" in k]


def _extract_traffic(item):
    """
    Return (monthly_visits, paid_share_fraction, cpc) from an actor item.

    paid_share is normalised to a 0..1 fraction. Handles the default
    pro100chok/similarweb schema precisely (Engagments.Visits + TrafficSources
    percentages) and falls back to a generic key search for other actors.
    """
    visits = paid = cpc = None
    if isinstance(item, dict):
        eng = item.get("Engagments") or item.get("Engagements")
        if isinstance(eng, dict):
            visits = _coerce_number(eng.get("Visits") or eng.get("VisitsFormatted"))
        if not visits:
            emv = item.get("EstimatedMonthlyVisits")
            if isinstance(emv, dict) and emv:
                try:
                    visits = _coerce_number(emv[sorted(emv.keys())[-1]])
                except Exception:
                    pass
        ts = item.get("TrafficSources")
        if isinstance(ts, dict):
            total_paid, found = 0.0, False
            for k, v in ts.items():
                if "paid" in str(k).lower():
                    n = _coerce_number(v)
                    if n is not None:
                        total_paid += n
                        found = True
            if found:
                paid = total_paid / 100.0  # TrafficSources values are percentages

    if not visits:
        visits = _deep_find(item, _VISIT_KEYS, lambda n: n >= 100)
    if paid is None:
        p = _deep_find(item, _PAID_KEYS, lambda n: 0 < n <= 100)
        if p is not None:
            paid = p / 100 if p > 1 else p
    cpc = _deep_find(item, _CPC_KEYS, lambda n: n > 0)
    return visits, paid, cpc


def _apify_payload(domain: str) -> dict:
    # `searchType` is REQUIRED by the default (pro100chok) actor; without it the
    # run returns 0 items. Extra keys are ignored by actors that don't use them.
    return {
        "searchType": "similarweb",
        "domains": [domain], "websites": [domain], "website": domain,
        "queries": [domain], "startUrls": [{"url": f"https://{domain}"}],
        "maxItems": 1, "maxResults": 1,
    }


def diagnose(domain: str) -> dict:
    """
    Human-readable check of the configured traffic provider. Powers the
    /api/traffic-debug endpoint so you can confirm the API is wired correctly
    without redeploying. Never returns secrets (token shown only as a prefix).
    """
    provider = os.environ.get("TRAFFIC_PROVIDER", "").strip().lower()
    info = {"provider": provider or "(unset)", "domain": domain}
    if not provider or provider == "none":
        info["status"] = "No provider configured. Set TRAFFIC_PROVIDER (e.g. apify)."
        return info
    if provider == "apify":
        return _apify_diagnose(domain, info)
    # Other providers: run and report.
    try:
        r = estimate(domain)
        info["result"] = r
        info["status"] = "ok" if r else "Provider returned no data (check key / subscription)."
    except Exception as e:
        info["status"] = "error"
        info["error"] = str(e)
    return info


def _apify_diagnose(domain: str, info: dict) -> dict:
    token = os.environ.get("APIFY_TOKEN")
    actor = os.environ.get("APIFY_ACTOR_ID", "pro100chok~similarweb-scraper")
    info["actor"] = actor
    info["token_present"] = bool(token)
    if token:
        info["token_prefix"] = token[:9] + "…"
    if not token:
        info["status"] = "APIFY_TOKEN is not set on the server."
        return info
    if httpx is None:
        info["status"] = "httpx is not installed."
        return info
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    try:
        with httpx.Client(timeout=120) as c:
            r = c.post(url, params={"token": token}, json=_apify_payload(domain))
        info["http_status"] = r.status_code
        if r.status_code >= 300:
            info["status"] = f"Apify returned HTTP {r.status_code}."
            info["response_snippet"] = r.text[:400]
            if r.status_code == 401:
                info["hint"] = "Token rejected — check APIFY_TOKEN."
            elif r.status_code == 404:
                info["hint"] = "Actor not found — check APIFY_ACTOR_ID (username~actor-name)."
            return info
        items = r.json()
        info["items_returned"] = len(items) if isinstance(items, list) else 1
        item = items[0] if isinstance(items, list) and items else (items or None)
        if not item:
            info["status"] = "Actor ran but returned 0 items (domain may be unranked)."
            return info
        info["item_top_keys"] = list(item.keys())[:40] if isinstance(item, dict) else str(type(item))
        visits, paid, cpc = _extract_traffic(item)
        info["parsed"] = {"visits": visits, "paid_share_raw": paid, "cpc": cpc}
        if visits:
            info["status"] = "OK — traffic parsed. The report should now show estimates."
        else:
            info["status"] = ("Connected, but couldn't locate a visits field in the response. "
                              "Look at item_top_keys and either switch APIFY_ACTOR_ID to a "
                              "traffic actor, or send me these keys and I'll map them.")
    except Exception as e:
        info["status"] = "Request to Apify failed."
        info["error"] = str(e)
    return info


def _apify(domain: str) -> dict | None:
    """
    Run an Apify traffic actor and extract monthly visits, paid share and CPC.

    Config:
        APIFY_TOKEN     (required) — your Apify API token.
        APIFY_ACTOR_ID  (optional) — actor to run, in 'username~actor-name' form.
                        Defaults to a Similarweb-style traffic actor.
        AVG_CPC         (optional) — fallback CPC if the actor returns none.

    We send a permissive input covering the common field names actors use, then
    parse the returned dataset item defensively. Returns None on any failure so
    the report degrades to the 'connect a provider' note rather than wrong data.
    """
    token = os.environ.get("APIFY_TOKEN")
    if not token or httpx is None:
        return None
    actor = os.environ.get("APIFY_ACTOR_ID", "pro100chok~similarweb-scraper")

    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    try:
        with httpx.Client(timeout=120) as c:
            r = c.post(url, params={"token": token}, json=_apify_payload(domain))
            r.raise_for_status()
            items = r.json()
    except Exception:
        return None
    if not items:
        return None
    item = items[0] if isinstance(items, list) else items

    visits, paid, cpc = _extract_traffic(item)  # paid is a 0..1 fraction or None
    if not visits:
        return None
    visits = int(visits)

    paid_share = paid if paid is not None else _env_float("PAID_SHARE", 0.12)
    paid_share = min(0.9, max(0.0, paid_share))

    avg_cpc = cpc if cpc else _env_float("AVG_CPC", 1.20)
    spend = round(visits * paid_share * avg_cpc, 2)
    return {
        "monthly_visits": visits,
        "paid_share": round(paid_share, 3),
        "monthly_ad_spend": spend,
        "avg_cpc": round(avg_cpc, 2),
        "source": f"Apify ({actor.split('~')[0]})",
        "estimated": True,
    }


def _similarweb(domain: str) -> dict | None:
    """
    Query the official Similarweb API for monthly visits and paid share.

    Requires SIMILARWEB_API_KEY and an active subscription. Ad spend is not a
    direct Similarweb metric, so we derive it as paid_visits * AVG_CPC (CPC is
    configurable via the AVG_CPC env var). Returns None on any failure so the
    report degrades gracefully instead of showing wrong numbers.
    """
    key = os.environ.get("SIMILARWEB_API_KEY")
    if not key or httpx is None:
        return None

    end = date.today().replace(day=1) - timedelta(days=1)  # last full month
    start = end.replace(day=1)
    period = {"start_date": start.strftime("%Y-%m"), "end_date": end.strftime("%Y-%m"),
              "granularity": "monthly", "main_domain_only": "true", "api_key": key}
    base = f"https://api.similarweb.com/v1/website/{domain}"

    try:
        with httpx.Client(timeout=20) as c:
            v = c.get(f"{base}/total-traffic-and-engagement/visits", params=period)
            v.raise_for_status()
            visits_series = v.json().get("visits", [])
            monthly_visits = int(visits_series[-1]["visits"]) if visits_series else 0

            paid_share = 0.12
            try:
                s = c.get(f"{base}/traffic-sources/overview-share", params=period)
                s.raise_for_status()
                shares = s.json()
                # Structure varies; pull paid search + display if present.
                blob = str(shares).lower()
                if "paid" in blob:
                    src = shares.get("visits", shares)
                    # Best-effort: sum any keys mentioning paid/display.
                    total = 0.0
                    if isinstance(src, dict):
                        for k, val in src.items():
                            if isinstance(val, (int, float)) and ("paid" in k.lower() or "display" in k.lower()):
                                total += float(val)
                    if total > 0:
                        paid_share = min(0.9, total if total <= 1 else total / 100)
            except Exception:
                pass
    except Exception:
        return None

    if monthly_visits <= 0:
        return None
    avg_cpc = _env_float("AVG_CPC", 1.20)
    spend = round(monthly_visits * paid_share * avg_cpc, 2)
    return {
        "monthly_visits": monthly_visits,
        "paid_share": round(paid_share, 3),
        "monthly_ad_spend": spend,
        "avg_cpc": avg_cpc,
        "source": "Similarweb",
        "estimated": True,  # spend is derived from visits*CPC
    }
