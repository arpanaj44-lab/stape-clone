"""
Impact estimation: "users not tracked" and "ad spend impacted by tracking loss".

Mirrors the section in Stape's report. The traffic *magnitude* comes from a
data provider (traffic.py); this module turns that magnitude into an impact
estimate using a documented loss-rate model that depends on how much of the
site's tracking is client-side (worse) vs server-side (better).

All outputs are explicitly flagged as estimates.
"""

from __future__ import annotations

# Baseline share of signal lost when tracking is 100% client-side.
# - USER_LOSS: visitors missing from analytics (ad blockers + tracking prevention).
# - AD_LOSS:  paid conversions/spend that go unattributed (a bit higher — paid
#             traffic skews to platforms/users where blocking bites hardest).
USER_LOSS_CLIENT = 0.13
AD_LOSS_CLIENT = 0.18

# How much of the loss server-side tracking recovers (0..1). Server-side doesn't
# recover everything (consent, hard blocks remain), so cap the benefit.
SS_RECOVERY = 0.65


def _ss_fraction(trackers: list[dict], category: str) -> float:
    rows = [t for t in trackers if t["category"] == category and t["server_side_supported"]]
    if not rows:
        return 0.0
    ss = sum(1 for t in rows if t["method"] == "Server-side")
    return ss / len(rows)


def compute(findings: dict, traffic: dict | None) -> dict | None:
    """
    Return an impact estimate, or None when no traffic data is available (the
    report then shows a 'connect a traffic API' note instead of fake numbers).
    """
    if not traffic:
        return None

    trackers = findings.get("trackers", [])
    analytics_ss = _ss_fraction(trackers, "Analytics")
    ads_ss = _ss_fraction(trackers, "Advertising")

    user_loss = USER_LOSS_CLIENT * (1 - SS_RECOVERY * analytics_ss)
    ad_loss = AD_LOSS_CLIENT * (1 - SS_RECOVERY * ads_ss)

    visits = traffic["monthly_visits"]
    spend = traffic["monthly_ad_spend"]

    users_not_tracked = round(visits * user_loss)
    ad_spend_impacted = round(spend * ad_loss, 2)

    return {
        "monthly_visits": visits,
        "monthly_ad_spend": spend,
        "paid_share": traffic.get("paid_share"),
        "avg_cpc": traffic.get("avg_cpc"),
        "user_loss_pct": round(user_loss * 100, 1),
        "ad_loss_pct": round(ad_loss * 100, 1),
        "users_not_tracked": users_not_tracked,
        "ad_spend_impacted": ad_spend_impacted,
        "source": traffic.get("source", "traffic provider"),
        "estimated": traffic.get("estimated", True),
    }
