"""
Traffic-intelligence provider layer.

Stape's report shows estimated monthly visits and paid ad spend, which do NOT
come from scanning the page — they come from a third-party traffic-data provider
(Similarweb-style). This module is a small pluggable adapter around that idea.

Select a provider with the TRAFFIC_PROVIDER env var:

    similarweb   -> official Similarweb API   (needs SIMILARWEB_API_KEY)
    manual       -> fixed numbers from env    (MONTHLY_VISITS, MONTHLY_AD_SPEND, PAID_SHARE)
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
