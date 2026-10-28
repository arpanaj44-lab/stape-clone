"""
Rule-based recommendations engine.

Maps concrete findings to prioritised, templated recommendations, each with an
estimated "score improvement" (how many overall points the fix is worth). No
LLM, no network — fully deterministic so the same site always yields the same
advice. It also composes the short narrative paragraph shown at the top of the
"Recommended actions" section.

Each recommendation is a dict:
    {title, categories, detail, improvement}
sorted by `improvement` descending, like Stape's report.
"""

from __future__ import annotations


def _cap(improvement: int, headroom: int) -> int:
    """Never promise more improvement than the gap to 100 allows."""
    return max(1, min(improvement, headroom))


def build(findings: dict, scores: dict) -> dict:
    trackers = findings.get("trackers", [])
    cookies = findings.get("cookies", [])
    speed = findings.get("speed", {})

    recs: list[dict] = []
    overall = scores["overall"] if scores["overall"] is not None else 0
    headroom = max(1, 100 - overall)

    analytics_cs = [t for t in trackers if t["category"] == "Analytics"
                    and t["method"] == "Client-side" and t["server_side_supported"]]
    ads_cs = [t for t in trackers if t["category"] == "Advertising"
              and t["method"] == "Client-side" and t["server_side_supported"]]

    # --- Cookies: the ITP short-lifetime problem -------------------------------
    capped = [c for c in cookies if (c["lifetime_days"] is not None and c["lifetime_days"] <= 7)
              and not c.get("http_only")]
    if capped:
        names = ", ".join(dict.fromkeys(c["name"] for c in capped))
        recs.append({
            "title": "Bypass ITP limits and extend cookie duration",
            "categories": ["Cookies"],
            "detail": (
                f"{len(capped)} of your tracking cookies ({names}) are set client-side and "
                "are being capped to roughly 7 days by Safari's Intelligent Tracking "
                "Prevention. Set these cookies server-side (HttpOnly, first-party) so they "
                "persist their full intended lifetime, improving returning-visitor "
                "attribution and audience match rates."
            ),
            "improvement": _cap(19, headroom),
        })

    # --- Analytics: GA4 / other analytics client-side --------------------------
    ga4 = next((t for t in analytics_cs if t["platform"] == "Google Analytics 4"), None)
    if ga4:
        recs.append({
            "title": "Implement Google Analytics 4 server-side tracking",
            "categories": ["Analytics"],
            "detail": (
                "GA4 is currently loaded entirely client-side, so events are lost to ad "
                "blockers, browser restrictions and network failures. Route GA4 through a "
                "server-side GTM container to recover lost events, improve data accuracy "
                "and gain control over the data sent to Google."
            ),
            "improvement": _cap(16, headroom),
        })
    for t in analytics_cs:
        if t["platform"] == "Google Analytics 4":
            continue
        recs.append({
            "title": f"Move {t['platform']} to server-side tracking",
            "categories": ["Analytics"],
            "detail": (
                f"{t['platform']} is running client-side. Sending its events server-side "
                "reduces data loss from blockers and gives you first-party control over the "
                "payload."
            ),
            "improvement": _cap(9, headroom),
        })

    # --- Ad blockers (only meaningful if there is client-side stuff) -----------
    if analytics_cs or ads_cs:
        recs.append({
            "title": "Avoid negative impact of ad blockers",
            "categories": sorted({("Analytics" if analytics_cs else None),
                                  ("Advertising" if ads_cs else None)} - {None}),
            "detail": (
                "A large share of visitors block third-party tracking scripts, so "
                "client-side tags silently under-report. Loading tags from your own domain "
                "via server-side tracking makes them first-party and far harder to block, "
                "recovering conversions you currently never see."
            ),
            "improvement": _cap(12, headroom),
        })

    # --- Per-platform advertising recommendations ------------------------------
    ads_priority = {
        "Google Ads": ("Move Google Ads to server-side tracking",
                       "Send Google Ads conversions via the server-side container / "
                       "enhanced conversions so attribution survives ad blockers and ITP.", 6),
        "Meta Pixel": ("Adopt Meta Conversions API alongside the Pixel",
                       "Pair the browser Pixel with Meta's Conversions API (server-side) to "
                       "de-duplicate events and recover conversions blocked in the browser.", 8),
        "LinkedIn": ("Adopt web and server-side tracking together for LinkedIn",
                     "Add the LinkedIn Conversions API next to the Insight Tag to improve "
                     "match quality and capture conversions lost client-side.", 6),
        "Reddit": ("Configure Reddit server-side tracking",
                   "Enable the Reddit Conversions API to send events server-side and reduce "
                   "signal loss from blockers.", 8),
        "TikTok": ("Configure TikTok Events API",
                   "Send TikTok events server-side via the Events API to improve match rate "
                   "and campaign optimisation.", 7),
        "Snapchat": ("Configure Snapchat Conversions API",
                     "Move Snapchat events server-side via the Conversions API for more "
                     "reliable attribution.", 6),
        "Pinterest": ("Configure Pinterest Conversions API",
                      "Add the Pinterest Conversions API to complement the tag and recover "
                      "blocked events.", 5),
        "Microsoft Ads (UET)": ("Move Microsoft Ads (UET) to server-side",
                                "Send UET conversions server-side to reduce loss from "
                                "tracking prevention.", 5),
        "X (Twitter)": ("Adopt X (Twitter) server-side conversions",
                        "Complement the website tag with server-side conversions for more "
                        "complete attribution.", 5),
    }
    for t in ads_cs:
        spec = ads_priority.get(t["platform"])
        if spec:
            title, detail, imp = spec
            recs.append({
                "title": title,
                "categories": ["Advertising"],
                "detail": detail,
                "improvement": _cap(imp, headroom),
            })

    # --- Unsupported platforms: note, low weight -------------------------------
    unsupported = [t for t in trackers if not t["server_side_supported"]]
    if unsupported:
        names = ", ".join(t["platform"] for t in unsupported)
        recs.append({
            "title": "Review tools without a server-side path",
            "categories": ["Analytics", "Advertising"],
            "detail": (
                f"{names} do not offer a server-side / Conversions-API option. Keep them "
                "behind a consent gate and load them only when needed so they don't drag "
                "down page performance or compliance."
            ),
            "improvement": _cap(3, headroom),
        })

    # --- Page speed ------------------------------------------------------------
    if scores["pagespeed"] < 80:
        load_s = round((speed.get("load_ms", 0) or 0) / 1000, 1)
        tr = speed.get("tracking_requests", 0)
        recs.append({
            "title": "Optimise page speed",
            "categories": ["Pagespeed"],
            "detail": (
                f"The page took about {load_s}s to load and fires roughly {tr} third-party "
                "tracking requests. Consolidating tags into a single server-side container "
                "and deferring non-critical scripts cuts main-thread work and speeds up the "
                "page."
            ),
            "improvement": _cap(7, headroom),
        })

    # No trackers at all -> different story.
    if not trackers:
        recs.append({
            "title": "No tracking detected — add a measurement foundation",
            "categories": ["Analytics"],
            "detail": (
                "We didn't detect any analytics or advertising tags on this page. If that's "
                "unexpected, your tags may be consent-gated or blocked. Otherwise, start with "
                "a server-side GA4 setup so you measure accurately from day one."
            ),
            "improvement": _cap(30, headroom),
        })

    recs.sort(key=lambda r: r["improvement"], reverse=True)
    narrative = _narrative(findings, scores, bool(capped), analytics_cs, ads_cs)
    return {"narrative": narrative, "actions": recs}


def _narrative(findings, scores, has_capped_cookies, analytics_cs, ads_cs) -> str:
    overall = scores["overall"]
    trackers = findings.get("trackers", [])
    if not trackers:
        return (
            "We couldn't find any active tracking on this page. If you expect analytics or "
            "ad tags here, they may be blocked or waiting on consent. Adding a reliable, "
            "server-side measurement foundation is the place to start."
        )

    client_side = [t for t in trackers if t["method"] == "Client-side" and t["server_side_supported"]]
    platform_names = ", ".join(dict.fromkeys(t["platform"] for t in client_side[:3]))

    if overall < 40:
        severity = f"received a low score of {overall}, indicating significant room for improvement"
    elif overall < 60:
        severity = f"scored {overall}, which leaves clear room for improvement"
    elif overall < 80:
        severity = f"scored {overall} — a solid setup with a few gaps to close"
    else:
        severity = f"scored {overall}, which is a strong, resilient setup"

    parts = [f"Your website's tracking setup {severity}."]
    if client_side:
        parts.append(
            f"Key platforms{f' like {platform_names}' if platform_names else ''} are currently "
            "tracked client-side, which makes them vulnerable to ad blockers, browser "
            "restrictions and data loss."
        )
    if has_capped_cookies:
        parts.append(
            "Several tracking cookies are being shortened to about 7 days by browser tracking "
            "prevention, which weakens returning-visitor attribution."
        )
    parts.append(
        "Moving supported platforms to server-side tracking and extending cookie lifetimes "
        "will improve data accuracy, attribution and resilience. The prioritised actions "
        "below show where to start and how much each is worth."
    )
    return " ".join(parts)
