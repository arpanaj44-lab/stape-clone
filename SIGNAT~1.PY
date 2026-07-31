"""
Tracker + cookie signature database.

This is the knowledge base the scanner matches observed network requests and
cookies against. It is intentionally data-only so it is easy to extend: add a
new dict entry and the rest of the pipeline (scanner -> scoring -> recommendations)
picks it up automatically.

Categories used across the app:
    "Analytics"    -> measurement / product analytics
    "Advertising"  -> ad platforms / conversion pixels
    "Tag manager"  -> container loaders (GTM, Tealium...)

server_side:  whether the vendor supports a server-side / Conversions-API path
              that Stape-style setups can move traffic to. Drives recommendations.
"""

# ---------------------------------------------------------------------------
# TRACKERS
# Each tracker is matched by substrings that appear in the *host + path* of a
# network request the page makes. `collect_hosts` are the endpoints that
# indicate the tag actually fired (vs just the library loading); we use them to
# distinguish an active tracker and to guess client- vs server-side.
# ---------------------------------------------------------------------------
TRACKERS = [
    {
        "platform": "Google Analytics 4",
        "category": "Analytics",
        "server_side": True,
        "url_patterns": ["googletagmanager.com/gtag/js", "google-analytics.com", "/g/collect", "analytics.google.com"],
        "collect_hosts": ["google-analytics.com/g/collect", "analytics.google.com/g/collect"],
    },
    {
        "platform": "Google Tag Manager",
        "category": "Tag manager",
        "server_side": True,
        "url_patterns": ["googletagmanager.com/gtm.js", "googletagmanager.com/gtag/destination"],
        "collect_hosts": [],
    },
    {
        "platform": "Google Ads",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["googleadservices.com/pagead/conversion", "googleads.g.doubleclick.net", "google.com/pagead", "google.com/ads/ga-audiences"],
        "collect_hosts": ["googleadservices.com/pagead/conversion", "googleads.g.doubleclick.net/pagead/viewthroughconversion"],
    },
    {
        "platform": "Meta Pixel",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["connect.facebook.net", "facebook.com/tr"],
        "collect_hosts": ["facebook.com/tr"],
    },
    {
        "platform": "LinkedIn",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["snap.licdn.com", "px.ads.linkedin.com", "linkedin.com/px"],
        "collect_hosts": ["px.ads.linkedin.com/collect"],
    },
    {
        "platform": "Reddit",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["redditstatic.com/ads", "pixel-config.reddit.com", "alb.reddit.com", "events.reddit.com"],
        "collect_hosts": ["alb.reddit.com/rp.gif", "events.reddit.com"],
    },
    {
        "platform": "Microsoft Clarity",
        "category": "Advertising",
        "server_side": False,
        "url_patterns": ["clarity.ms"],
        "collect_hosts": ["clarity.ms/collect"],
    },
    {
        "platform": "TikTok",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["analytics.tiktok.com", "analytics-sg.tiktok.com"],
        "collect_hosts": ["analytics.tiktok.com/api"],
    },
    {
        "platform": "Microsoft Ads (UET)",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["bat.bing.com"],
        "collect_hosts": ["bat.bing.com/action", "bat.bing.com/bat.js"],
    },
    {
        "platform": "Snapchat",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["sc-static.net", "tr.snapchat.com", "tr6.snapchat.com"],
        "collect_hosts": ["tr.snapchat.com"],
    },
    {
        "platform": "Pinterest",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["s.pinimg.com", "ct.pinterest.com"],
        "collect_hosts": ["ct.pinterest.com/v3"],
    },
    {
        "platform": "X (Twitter)",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["static.ads-twitter.com", "analytics.twitter.com", "t.co/i/adsct"],
        "collect_hosts": ["analytics.twitter.com/i/adsct", "t.co/i/adsct"],
    },
    {
        "platform": "Hotjar",
        "category": "Analytics",
        "server_side": False,
        "url_patterns": ["static.hotjar.com", "script.hotjar.com", "insights.hotjar.com"],
        "collect_hosts": ["insights.hotjar.com"],
    },
    {
        "platform": "HubSpot",
        "category": "Advertising",
        "server_side": False,
        "url_patterns": ["js.hs-scripts.com", "js.hs-analytics.net", "track.hubspot.com"],
        "collect_hosts": ["track.hubspot.com/__ptq.gif"],
    },
    {
        "platform": "Segment",
        "category": "Analytics",
        "server_side": True,
        "url_patterns": ["cdn.segment.com", "api.segment.io"],
        "collect_hosts": ["api.segment.io/v1"],
    },
    {
        "platform": "Amplitude",
        "category": "Analytics",
        "server_side": True,
        "url_patterns": ["cdn.amplitude.com", "api.amplitude.com", "api2.amplitude.com"],
        "collect_hosts": ["api.amplitude.com", "api2.amplitude.com"],
    },
    {
        "platform": "Mixpanel",
        "category": "Analytics",
        "server_side": True,
        "url_patterns": ["cdn.mxpnl.com", "api.mixpanel.com"],
        "collect_hosts": ["api.mixpanel.com"],
    },
]

# ---------------------------------------------------------------------------
# COOKIES
# Matched against cookie names. `match` is "exact" or "prefix". `typical_days`
# is the vendor's intended lifetime; the scanner reports the *actual* observed
# lifetime, which is what ITP/browser caps affect.
# ---------------------------------------------------------------------------
COOKIES = [
    {"name": "_ga", "match": "exact", "provider": "Google", "category": "Analytics", "typical_days": 730},
    {"name": "_ga_", "match": "prefix", "provider": "Google", "category": "Analytics", "typical_days": 730},
    {"name": "_gid", "match": "exact", "provider": "Google", "category": "Analytics", "typical_days": 1},
    {"name": "_gat", "match": "prefix", "provider": "Google", "category": "Analytics", "typical_days": 1},
    {"name": "_gcl_au", "match": "exact", "provider": "Google", "category": "Advertising", "typical_days": 90},
    {"name": "_gcl_aw", "match": "exact", "provider": "Google", "category": "Advertising", "typical_days": 90},
    {"name": "_gcl_gb", "match": "exact", "provider": "Google", "category": "Advertising", "typical_days": 90},
    {"name": "_fbp", "match": "exact", "provider": "Meta", "category": "Advertising", "typical_days": 90},
    {"name": "_fbc", "match": "exact", "provider": "Meta", "category": "Advertising", "typical_days": 90},
    {"name": "li_fat_id", "match": "exact", "provider": "LinkedIn", "category": "Advertising", "typical_days": 30},
    {"name": "_rdt_cid", "match": "exact", "provider": "Reddit", "category": "Advertising", "typical_days": 90},
    {"name": "_rdt_uuid", "match": "exact", "provider": "Reddit", "category": "Advertising", "typical_days": 90},
    {"name": "_clck", "match": "exact", "provider": "Microsoft", "category": "Advertising", "typical_days": 365},
    {"name": "_clsk", "match": "exact", "provider": "Microsoft", "category": "Advertising", "typical_days": 1},
    {"name": "_uetsid", "match": "exact", "provider": "Microsoft", "category": "Advertising", "typical_days": 1},
    {"name": "_uetvid", "match": "exact", "provider": "Microsoft", "category": "Advertising", "typical_days": 390},
    {"name": "_ttp", "match": "exact", "provider": "TikTok", "category": "Advertising", "typical_days": 390},
    {"name": "_tt_enable_cookie", "match": "exact", "provider": "TikTok", "category": "Advertising", "typical_days": 390},
    {"name": "_pin_unauth", "match": "exact", "provider": "Pinterest", "category": "Advertising", "typical_days": 365},
    {"name": "_pinterest_ct", "match": "prefix", "provider": "Pinterest", "category": "Advertising", "typical_days": 365},
    {"name": "_scid", "match": "exact", "provider": "Snapchat", "category": "Advertising", "typical_days": 390},
    {"name": "_hjSessionUser", "match": "prefix", "provider": "Hotjar", "category": "Analytics", "typical_days": 365},
    {"name": "_hjSession", "match": "prefix", "provider": "Hotjar", "category": "Analytics", "typical_days": 1},
    {"name": "hubspotutk", "match": "exact", "provider": "HubSpot", "category": "Advertising", "typical_days": 180},
    {"name": "ajs_anonymous_id", "match": "exact", "provider": "Segment", "category": "Analytics", "typical_days": 365},
    {"name": "amplitude_id", "match": "prefix", "provider": "Amplitude", "category": "Analytics", "typical_days": 730},
    {"name": "mp_", "match": "prefix", "provider": "Mixpanel", "category": "Analytics", "typical_days": 365},
]


def match_tracker(url: str):
    """Return the tracker dict whose url_patterns appear in `url`, else None."""
    low = url.lower()
    for t in TRACKERS:
        for pat in t["url_patterns"]:
            if pat in low:
                return t
    return None


def is_collect_hit(url: str, tracker: dict) -> bool:
    """True if `url` is one of the tracker's actual data-collection endpoints."""
    low = url.lower()
    return any(h in low for h in tracker.get("collect_hosts", []))


def match_cookie(name: str):
    """Return the cookie signature matching `name`, else None."""
    for c in COOKIES:
        if c["match"] == "exact" and name == c["name"]:
            return c
        if c["match"] == "prefix" and name.startswith(c["name"]):
            return c
    return None
