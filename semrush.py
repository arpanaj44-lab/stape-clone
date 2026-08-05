"""
Semrush v4 adapter — "Site authority" section.

Reality check on what v4 exposes and why this looks the way it does:

    - v4 Standard API (which is what a `semrtkn_...` key can call) has ONLY the
      SEO endpoints: Backlinks + Keyword reports. Domain-level *traffic* / *paid
      spend* live in v3's `domain_ranks` (unavailable to new v4 keys) or in the
      separate paid *Trends API*. Neither is reachable with a Pro-plan v4 key.
    - So we don't use Semrush for the ad-spend estimate — that stays with the
      traffic providers (Apify vortex, etc.) in traffic.py.
    - What Semrush v4 CAN give a tracking-checker report is a genuine signal of
      site quality: Backlinks Overview returns Authority Score (0–100), total
      backlinks, referring domains, and follow/lost counts.

Endpoint used:
    GET https://api.semrush.com/apis/v4/backlinks/v1/overview
         ?url=<domain>&scope=ROOT_DOMAIN
    Header: Authorization: Apikey <SEMRUSH_API_KEY>
    Cost:   45 API units per request (drawn from Standard API balance)

Env:
    SEMRUSH_API_KEY   — v4 API key (starts with 'semrtkn')
    SEMRUSH_SCOPE     — optional, default ROOT_DOMAIN (also: SUBDOMAIN, SUBFOLDER, PAGE)
"""

from __future__ import annotations

import os

try:
    import httpx
except Exception:
    httpx = None


V4_BACKLINKS_OVERVIEW = "https://api.semrush.com/apis/v4/backlinks/v1/overview"


def _key() -> str | None:
    return os.environ.get("SEMRUSH_API_KEY")


def _scope() -> str:
    return (os.environ.get("SEMRUSH_SCOPE") or "ROOT_DOMAIN").upper()


def enabled() -> bool:
    return bool(_key()) and httpx is not None


def fetch_authority(domain: str) -> dict | None:
    """
    Call Backlinks Overview and return a clean, template-ready dict, or None if
    nothing usable (no key, request failed, or empty payload). Returns:

        {
          "authority_score": int|None,   # 0..100
          "backlinks_count": int,
          "domains_count":  int,         # referring domains
          "follows_count":  int,
          "nofollows_count":int,
          "new_count":      int,
          "lost_count":     int,
          "dofollow_pct":   float,       # 0..100
          "net_growth":     int,         # new - lost (last 30d)
          "url_used":       str,
          "scope":          str,
          "source":         str,
        }
    """
    if not enabled():
        return None
    data, _dbg = _call(domain)
    return _shape(domain, data) if data else None


def diagnose(domain: str) -> dict:
    """Human-readable check for /api/authority-debug — never returns the key."""
    info = {"provider": "semrush", "domain": domain, "build": "semrush-v4-authority-1"}
    key = _key()
    info["key_present"] = bool(key)
    if key:
        info["key_prefix"] = key[:10] + "..."
        info["key_length"] = len(key)
    if httpx is None:
        info["status"] = "httpx not installed"
        return info
    if not key:
        info["status"] = "SEMRUSH_API_KEY not set on the server."
        return info
    data, dbg = _call(domain)
    info.update(dbg)
    if data:
        info["parsed"] = _shape(domain, data)
        info["status"] = "OK — Backlinks Overview parsed. Site-authority section will show."
    else:
        info["status"] = "Reached the API but couldn't parse an Overview payload — see snippet above."
    return info


# ---------------------------------------------------------------------------
def _call(domain: str) -> tuple[dict | None, dict]:
    """Do the actual HTTP call. Returns (data_dict_or_None, debug_dict)."""
    key = _key()
    scope = _scope()
    dbg: dict = {"endpoint": V4_BACKLINKS_OVERVIEW, "scope": scope}
    headers = {"Authorization": f"Apikey {key}", "Accept": "application/json"}
    # v4 accepts the domain with or without a protocol; sending it bare avoids
    # accidental %-encoding issues.
    params = {"url": domain, "scope": scope, "format": "json"}
    try:
        with httpx.Client(timeout=30) as c:
            r = c.get(V4_BACKLINKS_OVERVIEW, params=params, headers=headers)
        dbg["http_status"] = r.status_code
        text = (r.text or "")
        dbg["snippet"] = text[:400]
        if r.status_code >= 300:
            # v4 returns a structured JSON error body — extract it for the caller.
            try:
                err = r.json().get("error") or {}
                dbg["error_code"] = err.get("code")
                dbg["error_message"] = err.get("message")
            except Exception:
                pass
            return None, dbg
        js = r.json()
        # v4 wraps data under {"meta":{...},"data":{...}}
        data = js.get("data") if isinstance(js, dict) else None
        if not data or not isinstance(data, dict):
            return None, dbg
        return data, dbg
    except Exception as e:
        dbg["error"] = str(e)
        return None, dbg


def _shape(domain: str, data: dict) -> dict:
    def g(name):
        v = data.get(name)
        return v if isinstance(v, (int, float)) else 0

    backlinks = g("backlinks_count")
    follows = g("follows_count")
    nofollows = g("nofollows_count")
    total_labelled = follows + nofollows
    dofollow_pct = round((follows / total_labelled) * 100, 1) if total_labelled else 0.0
    return {
        "authority_score": data.get("score") if isinstance(data.get("score"), int) else None,
        "backlinks_count": backlinks,
        "domains_count": g("domains_count"),
        "follows_count": follows,
        "nofollows_count": nofollows,
        "new_count": g("new_count"),
        "lost_count": g("lost_count"),
        "dofollow_pct": dofollow_pct,
        "net_growth": g("new_count") - g("lost_count"),
        "url_used": domain,
        "scope": _scope(),
        "source": "Semrush v4 · Backlinks Overview",
    }
