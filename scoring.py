"""
Scoring model.

Turns scanner findings into four sub-scores (Analytics, Ads, Cookie lifetime,
Page speed) and one overall score, each 0-100, plus a rating label. The model
is a transparent, documented heuristic that mirrors the *shape* of Stape's
report (server-side tracking and longer cookie lifetimes score higher). It is
not affiliated with Stape and the exact numbers are our own.

Rationale for the weights lives inline so anyone can tune them.
"""

from __future__ import annotations

# Overall = weighted mean of the four pillars. Ads and Analytics dominate
# because tracking accuracy is the tool's core concern; speed is secondary.
WEIGHTS = {"analytics": 0.30, "ads": 0.30, "cookies": 0.25, "pagespeed": 0.15}


def _rating(score: int) -> str:
    if score >= 80:
        return "Great"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Needs work"
    return "Not good"


def _method_component(rows: list[dict]) -> int | None:
    """
    Score a set of tracker rows on a 0-100 scale by how many are server-side.
    Returns None when there are no trackers in that category (shown as n/a).

    Per-tracker points:
        server-side ............ 100
        client-side, SS-capable . 35   (works, but leaving accuracy on the table)
        client-side, no SS ...... 60   (can't do better, so not penalised as hard)
    """
    if not rows:
        return None
    pts = []
    for r in rows:
        if r["method"] == "Server-side":
            pts.append(100)
        elif r["server_side_supported"]:
            pts.append(35)
        else:
            pts.append(60)
    return round(sum(pts) / len(pts))


def score_analytics(trackers: list[dict]) -> int | None:
    rows = [t for t in trackers if t["category"] == "Analytics"]
    return _method_component(rows)


def score_ads(trackers: list[dict]) -> int | None:
    rows = [t for t in trackers if t["category"] == "Advertising"]
    return _method_component(rows)


def score_cookies(cookies: list[dict]) -> int | None:
    """
    Reward long-lived, server-set cookies; punish ITP-capped ones.

    Client-side cookies set via document.cookie are capped to ~7 days by Safari
    ITP, which is the single biggest lifetime problem the tool exists to flag.
    We map observed lifetime to points and give HttpOnly (server-set) cookies a
    bonus since they survive ITP.
    """
    if not cookies:
        return None
    pts = []
    for c in cookies:
        days = c["lifetime_days"]
        if days is None:          # session cookie -> worst case
            base = 15
        elif days <= 1:
            base = 20
        elif days <= 7:           # classic ITP cap
            base = 30
        elif days <= 30:
            base = 55
        elif days <= 90:
            base = 75
        elif days <= 180:
            base = 88
        else:
            base = 100
        if c.get("http_only"):
            base = min(100, base + 15)
        pts.append(base)
    return round(sum(pts) / len(pts))


def score_pagespeed(speed: dict) -> int:
    """
    Blend absolute load time with tracking-request overhead.

    load_ms:            <=1500 great, >=6000 poor (linear between).
    tracking_requests:  each third-party tracking call shaves points; server-side
                        setups make fewer of them, so this rewards consolidation.
    """
    load_ms = speed.get("load_ms", 0) or 0
    if load_ms <= 1500:
        load_score = 100
    elif load_ms >= 6000:
        load_score = 20
    else:
        load_score = round(100 - (load_ms - 1500) / (6000 - 1500) * 80)

    tr = speed.get("tracking_requests", 0)
    overhead_penalty = min(40, tr * 5)  # 8+ tracking calls = full penalty

    return max(0, min(100, round(load_score * 0.7 + (100 - overhead_penalty) * 0.3)))


def score_all(findings: dict) -> dict:
    trackers = findings.get("trackers", [])
    cookies = findings.get("cookies", [])
    speed = findings.get("speed", {})

    analytics = score_analytics(trackers)
    ads = score_ads(trackers)
    cookie = score_cookies(cookies)
    pagespeed = score_pagespeed(speed)

    # Nothing fired at all -> we can't judge tracking health (usually a consent
    # wall or an aggressive blocker hid everything). Don't award a misleading
    # perfect score off page-speed alone; report an explicit "unknown" state.
    if not trackers and not cookies:
        return {
            "overall": None,
            "rating": "No tracking detected",
            "analytics": None,
            "ads": None,
            "cookies": None,
            "pagespeed": pagespeed,
        }

    # For the overall mean, treat a missing pillar (n/a) as neutral-absent:
    # drop it and renormalise the remaining weights so it isn't unfairly 0.
    parts = {"analytics": analytics, "ads": ads, "cookies": cookie, "pagespeed": pagespeed}
    num = 0.0
    den = 0.0
    for key, val in parts.items():
        if val is None:
            continue
        num += WEIGHTS[key] * val
        den += WEIGHTS[key]
    overall = round(num / den) if den else 0

    return {
        "overall": overall,
        "rating": _rating(overall),
        "analytics": analytics,
        "ads": ads,
        "cookies": cookie,
        "pagespeed": pagespeed,
    }
