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
    if provider in ("similarweb_free", "similarweb-free", "swfree"):
        return _similarweb_free(domain)
    if provider == "semrush":
        return _semrush(domain)
    if provider == "apify":
        return _apify(domain)
    if provider == "similarweb":
        return _similarweb(domain)
    return None


# User-Agent that the Similarweb extension endpoint expects; a plain client UA
# usually gets a 403, so we present a browser-like one.
_SW_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.similarweb.com/",
}


def _similarweb_free(domain: str, _return_raw: bool = False):
    """
    FREE, no-key traffic data via Similarweb's browser-extension endpoint
    (data.similarweb.com). Returns the same rich object the extension shows:
    real monthly visits + traffic-source split. Reuses _extract_traffic.

    Caveat: unofficial endpoint. It can rate-limit or block datacenter IPs
    (cloud hosts), in which case it returns non-200/empty and we degrade to None.
    """
    if httpx is None:
        return (None, {"error": "httpx not installed"}) if _return_raw else None
    url = f"https://data.similarweb.com/api/v1/data?domain={domain}"
    dbg: dict = {}
    try:
        with httpx.Client(timeout=30, headers=_SW_HEADERS, follow_redirects=True) as c:
            r = c.get(url)
        dbg["http_status"] = r.status_code
        if r.status_code >= 300:
            dbg["snippet"] = r.text[:300]
            return (None, dbg) if _return_raw else None
        item = r.json()
    except Exception as e:
        dbg["error"] = str(e)
        return (None, dbg) if _return_raw else None

    if isinstance(item, dict):
        dbg["item_top_keys"] = list(item.keys())[:40]
    visits, paid, cpc = _extract_traffic(item)
    if not visits:
        dbg["parsed"] = {"visits": visits, "paid_share": paid}
        return (None, dbg) if _return_raw else None
    visits = int(visits)
    paid_share = paid if paid is not None else _env_float("PAID_SHARE", 0.12)
    # Optional floor: sites with ~0 reported paid traffic (small/no-ads sites) would
    # otherwise show $0 ad spend. MIN_PAID_SHARE (default 0 = honest) lets you model a
    # "what-if you advertised" share instead. Set e.g. 0.08 to assume >=8% paid.
    paid_share = max(paid_share, _env_float("MIN_PAID_SHARE", 0.0))
    paid_share = min(0.9, max(0.0, paid_share))
    avg_cpc = cpc if cpc else _env_float("AVG_CPC", 1.20)
    result = {
        "monthly_visits": visits,
        "paid_share": round(paid_share, 3),
        "monthly_ad_spend": round(visits * paid_share * avg_cpc, 2),
        "avg_cpc": round(avg_cpc, 2),
        "source": "Similarweb (free)",
        "estimated": True,
    }
    return (result, dbg) if _return_raw else result


def _semrush(domain: str, _return_raw: bool = False):
    """
    Semrush Analytics API — Domain Overview / domain_ranks.

    v4 keys (starting with 'semrtkn_') and legacy v3 keys are both supported:
    if the key starts with 'semrtkn_' we call the v4 endpoint with an
    'Authorization: Apikey ...' header; otherwise we fall back to the v3
    endpoint which passes the key as a query parameter. Both return the same
    ;-separated CSV with organic + paid SEARCH traffic and Adwords Cost (Ac),
    which we treat as monthly ad spend directly (no CPC guess needed).

    Note: this is SEARCH traffic (organic + paid), NOT total cross-channel
    visits like Similarweb — so 'monthly_visits' here is search-only.

    Env:
        SEMRUSH_API_KEY  (required)
        SEMRUSH_DB       (optional, default 'us') — Semrush database/country.
    """
    key = (os.environ.get("SEMRUSH_API_KEY") or "").strip()
    if not key or httpx is None:
        return (None, {"error": "no key / httpx"}) if _return_raw else None
    db = os.environ.get("SEMRUSH_DB", "us")
    export_columns = "Dn,Rk,Or,Ot,Oc,Ad,At,Ac"

    # v4 keys start with the token prefix (some UIs write it slightly differently);
    # accept any 'semrtkn' prefix, and honour an explicit override via SEMRUSH_API_VERSION.
    v_env = (os.environ.get("SEMRUSH_API_VERSION") or "").strip().lower()
    if v_env in ("v3", "3"):
        is_v4 = False
    elif v_env in ("v4", "4"):
        is_v4 = True
    else:
        is_v4 = key.lower().startswith("semrtkn")
    if is_v4:
        # v4: dedicated base URL for the standard API, key sent as header.
        url = "https://api.semrush.com/analytics/v1/"
        headers = {"Authorization": f"Apikey {key}"}
        params = {"type": "domain_ranks", "domain": domain, "database": db,
                  "export_columns": export_columns}
    else:
        url = "https://api.semrush.com/"
        headers = {}
        params = {"type": "domain_ranks", "key": key, "domain": domain,
                  "database": db, "export_columns": export_columns}

    dbg: dict = {
        "api_version": "v4" if is_v4 else "v3",
        "key_prefix": key[:10] + "...",   # first 10 chars only — no secret leaked
        "key_length": len(key),
    }
    try:
        with httpx.Client(timeout=30, headers=headers) as c:
            r = c.get(url, params=params)
        dbg["http_status"] = r.status_code
        text = (r.text or "").strip()
        dbg["snippet"] = text[:300]
        if r.status_code >= 300 or text.upper().startswith("ERROR"):
            return (None, dbg) if _return_raw else None
        lines = text.splitlines()
        if len(lines) < 2:
            return (None, dbg) if _return_raw else None
        cols = lines[1].split(";")
        if len(cols) < 8:
            return (None, dbg) if _return_raw else None
        ot = _coerce_number(cols[3]) or 0
        at = _coerce_number(cols[6]) or 0
        ac = _coerce_number(cols[7])
        visits = int(ot + at)
        if visits <= 0:
            dbg["parsed"] = {"organic_traffic": ot, "paid_traffic": at, "adwords_cost": ac}
            return (None, dbg) if _return_raw else None
        paid_share = (at / (ot + at)) if (ot + at) > 0 else _env_float("PAID_SHARE", 0.12)
        paid_share = max(paid_share, _env_float("MIN_PAID_SHARE", 0.0))
        paid_share = min(0.9, max(0.0, paid_share))
        avg_cpc = _env_float("AVG_CPC", 1.20)
        spend = ac if (ac is not None and ac > 0) else round(visits * paid_share * avg_cpc, 2)
        dbg["parsed"] = {"organic_traffic": ot, "paid_traffic": at, "adwords_cost": ac}
        result = {
            "monthly_visits": visits,
            "paid_share": round(paid_share, 3),
            "monthly_ad_spend": round(spend, 2),
            "avg_cpc": round(avg_cpc, 2),
            "source": f"Semrush ({db}, search traffic + Adwords cost)",
            "estimated": True,
        }
        return (result, dbg) if _return_raw else result
    except Exception as e:
        dbg["error"] = str(e)
        return (None, dbg) if _return_raw else None


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
            nums = [n for n in (_coerce_number(v) for v in ts.values()) if n is not None]
            # Values may be fractions (0..1, extension API) or percentages
            # (0..100, some actors). Detect scale from the total.
            scale = 100.0 if sum(nums) > 1.5 else 1.0
            total_paid, found = 0.0, False
            for k, v in ts.items():
                if "paid" in str(k).lower():
                    n = _coerce_number(v)
                    if n is not None:
                        total_paid += n
                        found = True
            if found:
                paid = total_paid / scale

        # vortex_data-style flat fields (totalVisits + paid*Traffic shares)
        if not visits:
            tv = _coerce_number(item.get("totalVisits"))
            if tv:
                visits = tv
            else:
                mvd = item.get("monthlyVisitsDateFormat")
                if isinstance(mvd, dict) and mvd:
                    try:
                        visits = _coerce_number(mvd[sorted(mvd.keys())[-1]])
                    except Exception:
                        pass
        if paid is None:
            tot, found = 0.0, False
            for f in ("paidReferralsTraffic", "displayAdsTraffic"):
                n = _coerce_number(item.get(f))
                if n is not None:
                    tot += n
                    found = True
            if found:
                paid = tot if tot <= 1 else tot / 100.0

    if not visits:
        visits = _deep_find(item, _VISIT_KEYS, lambda n: n >= 100)
    if paid is None:
        p = _deep_find(item, _PAID_KEYS, lambda n: 0 < n <= 100)
        if p is not None:
            paid = p / 100 if p > 1 else p
    cpc = _deep_find(item, _CPC_KEYS, lambda n: n > 0)
    return visits, paid, cpc


def _apify_payload(domain: str) -> dict:
    """
    Build the actor input.

    The default pro100chok/similarweb actor's schema defines ONLY `searchType`
    and `domains` — sending extra keys (startUrls, websites, queries, maxItems…)
    made it take a different path and return 0 results. So we send exactly that
    minimal input. A different actor can be pointed at via APIFY_ACTOR_ID, and
    its input shape overridden with APIFY_INPUT_JSON (a JSON template where the
    string {domain} is substituted).
    """
    tpl = os.environ.get("APIFY_INPUT_JSON")
    if tpl:
        import json
        try:
            return json.loads(tpl.replace("{domain}", domain))
        except Exception:
            pass
    return {"searchType": "similarweb", "domains": [domain]}


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
    if provider in ("similarweb_free", "similarweb-free", "swfree"):
        info["build"] = "traffic-v5-swfree"
        res, dbg = _similarweb_free(domain, _return_raw=True)
        info.update(dbg)
        info["result"] = res
        if res:
            info["status"] = "OK — traffic parsed. The report will now show estimates."
        elif info.get("http_status") in (403, 429) or "http_status" not in info:
            info["status"] = ("The free Similarweb endpoint blocked this request (common from cloud/"
                              "datacenter IPs like Render). This free source often works locally but "
                              "not from a server. See http_status/snippet above.")
        else:
            info["status"] = "Reached the endpoint but couldn't parse traffic — see item_top_keys."
        return info
    if provider == "semrush":
        info["build"] = "traffic-v9-semrush-detect"
        res, dbg = _semrush(domain, _return_raw=True)
        info.update(dbg)
        info["result"] = res
        if res:
            info["status"] = "OK — Semrush data parsed. The report will show estimates."
        else:
            info["status"] = ("No usable data. Check http_status/snippet above. Common Semrush errors: "
                              "'ERROR 120' = wrong API key; 'ERROR 134/135' = API not available on your "
                              "plan or no units; empty = domain not in the chosen database (try SEMRUSH_DB).")
        return info
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
    info["build"] = "traffic-v6-vortex"
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
    payload = _apify_payload(domain)
    info["sent_input"] = payload
    base = "https://api.apify.com/v2"
    try:
        with httpx.Client(timeout=150) as c:
            # Start the run and wait for it to finish so we can read run status.
            run = c.post(f"{base}/acts/{actor}/runs",
                         params={"token": token, "waitForFinish": 120}, json=payload)
            info["http_status"] = run.status_code
            if run.status_code >= 300:
                info["status"] = f"Apify returned HTTP {run.status_code}."
                info["response_snippet"] = run.text[:500]
                if run.status_code == 401:
                    info["hint"] = "Token rejected — check APIFY_TOKEN."
                elif run.status_code == 404:
                    info["hint"] = "Actor not found — check APIFY_ACTOR_ID."
                elif run.status_code == 402:
                    info["hint"] = "Payment required — the actor needs billing/credit on your Apify account."
                return info
            data = run.json().get("data", {})
            info["run_status"] = data.get("status")             # SUCCEEDED / FAILED / RUNNING ...
            info["run_message"] = data.get("statusMessage")     # human reason, if any
            stats = data.get("stats") or {}
            info["dataset_item_count"] = stats.get("datasetItemCount")
            ds = data.get("defaultDatasetId")
            items = []
            if ds:
                di = c.get(f"{base}/datasets/{ds}/items", params={"token": token, "limit": 1, "clean": "true"})
                if di.status_code < 300 and isinstance(di.json(), list):
                    items = di.json()
            info["items_returned"] = len(items)
            item = items[0] if items else None
            if not item:
                info["status"] = (
                    f"Run finished as {data.get('status')} with 0 items. "
                    "Check 'run_message' for the reason — common causes: the actor needs billing/"
                    "credit on your Apify account (free plan without a payment method), or SimilarWeb "
                    "returned nothing for this domain. If run_status is FAILED, that message is the fix."
                )
                return info
            info["item_top_keys"] = list(item.keys())[:40] if isinstance(item, dict) else str(type(item))
            visits, paid, cpc = _extract_traffic(item)
            info["parsed"] = {"visits": visits, "paid_share": paid, "cpc": cpc}
            info["status"] = ("OK — traffic parsed. The report will now show estimates."
                              if visits else
                              "Connected, but no visits field found — send me item_top_keys and I'll map it.")
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
    # Optional floor: sites with ~0 reported paid traffic (small/no-ads sites) would
    # otherwise show $0 ad spend. MIN_PAID_SHARE (default 0 = honest) lets you model a
    # "what-if you advertised" share instead. Set e.g. 0.08 to assume >=8% paid.
    paid_share = max(paid_share, _env_float("MIN_PAID_SHARE", 0.0))
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
