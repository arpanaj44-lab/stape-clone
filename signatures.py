"""
Tracker, cookie and CMP (consent-management-platform) signature database.

The scanner matches observed network requests, cookies, and script hosts
against the dicts in this file. Data-only, so extending is: add an entry,
done — the rest of the pipeline (scanner -> scoring -> recommendations)
picks it up automatically.

Categories:
    "Analytics"      -> measurement / product analytics
    "Advertising"    -> ad platforms / conversion pixels
    "Tag manager"    -> container loaders (GTM, Tealium…)
    "Session replay" -> heatmaps, recording (Hotjar, Clarity, Fullstory…)
    "Engagement"     -> live chat / help widgets (Intercom, Drift, Zendesk…)
    "Marketing"      -> marketing-automation (Marketo, Pardot, Mailchimp…)
    "CDP"            -> customer data platforms (Segment, Rudderstack, mParticle…)

server_side: whether the vendor supports a server-side / Conversions-API path
             that Stape-style setups can move traffic to. Drives recommendations.
"""

# ---------------------------------------------------------------------------
# TRACKERS
# Matched by substrings against the full URL (host+path). `collect_hosts` are
# the actual data-collection endpoints; a hit on one of them means the tag is
# FIRING. A hit only on `url_patterns` (e.g. the library .js) means LOADED
# ONLY — the integration is present but not sending events on this page.
# ---------------------------------------------------------------------------
TRACKERS = [
    # ===== Analytics / Measurement =====
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
        "platform": "Adobe Analytics",
        "category": "Analytics",
        "server_side": True,
        "url_patterns": ["sc.omtrdc.net", ".2o7.net", "assets.adobedtm.com", "demdex.net", "/b/ss/"],
        "collect_hosts": ["sc.omtrdc.net/b/ss", ".2o7.net/b/ss"],
    },
    {
        "platform": "Snowplow",
        "category": "Analytics",
        "server_side": True,
        "url_patterns": ["com.snowplowanalytics.snowplow", "sp.js", "snowplowanalytics.com", "/i?stm="],
        "collect_hosts": ["/com.snowplowanalytics.snowplow/tp2", "/i?stm="],
    },
    {
        "platform": "PostHog",
        "category": "Analytics",
        "server_side": True,
        "url_patterns": ["app.posthog.com", "us.posthog.com", "eu.posthog.com", "/static/array.js", "posthog.js"],
        "collect_hosts": ["posthog.com/e/", "posthog.com/capture", "posthog.com/decide"],
    },
    {
        "platform": "Heap",
        "category": "Analytics",
        "server_side": True,
        "url_patterns": ["cdn.heapanalytics.com", "heapanalytics.com"],
        "collect_hosts": ["heapanalytics.com/h", "heapanalytics.com/api"],
    },
    {
        "platform": "Hotjar",
        "category": "Session replay",
        "server_side": False,
        "url_patterns": ["static.hotjar.com", "script.hotjar.com", "insights.hotjar.com"],
        "collect_hosts": ["insights.hotjar.com"],
    },
    {
        "platform": "Fullstory",
        "category": "Session replay",
        "server_side": False,
        "url_patterns": ["fullstory.com/s/fs.js", "rs.fullstory.com", "fullstory.com/rec"],
        "collect_hosts": ["rs.fullstory.com", "fullstory.com/rec"],
    },
    {
        "platform": "Segment",
        "category": "CDP",
        "server_side": True,
        "url_patterns": ["cdn.segment.com", "api.segment.io"],
        "collect_hosts": ["api.segment.io/v1"],
    },
    {
        "platform": "Rudderstack",
        "category": "CDP",
        "server_side": True,
        "url_patterns": ["rudderanalytics.min.js", ".dataplane.rudderstack.com", "cdn.rudderlabs.com"],
        "collect_hosts": [".dataplane.rudderstack.com"],
    },
    {
        "platform": "mParticle",
        "category": "CDP",
        "server_side": True,
        "url_patterns": ["jssdkcdns.mparticle.com", "nativesdks.mparticle.com", ".identity.mparticle.com"],
        "collect_hosts": ["nativesdks.mparticle.com/v2", "identity.mparticle.com/v1"],
    },
    {
        "platform": "Tealium",
        "category": "Tag manager",
        "server_side": True,
        "url_patterns": ["tags.tiqcdn.com", "collect.tealiumiq.com"],
        "collect_hosts": ["collect.tealiumiq.com"],
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
        "url_patterns": ["cdn.mxpnl.com", "api.mixpanel.com", "cdn-mxpnl.com"],
        "collect_hosts": ["api.mixpanel.com"],
    },
    {
        "platform": "Microsoft Clarity",
        "category": "Session replay",
        "server_side": False,
        "url_patterns": ["clarity.ms"],
        "collect_hosts": ["clarity.ms/collect"],
    },

    # ===== Advertising / Pixels =====
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
        "platform": "Quora Pixel",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["a.quora.com/qevents.js", "q.quora.com"],
        "collect_hosts": ["q.quora.com", "a.quora.com/qevents"],
    },
    {
        "platform": "Yahoo DOT",
        "category": "Advertising",
        "server_side": True,
        "url_patterns": ["s.yimg.com/wi/ytc.js", "sp.analytics.yahoo.com"],
        "collect_hosts": ["sp.analytics.yahoo.com/spp.pl", "sp.analytics.yahoo.com/sp.pl"],
    },

    # ===== Marketing automation / CRM =====
    {
        "platform": "HubSpot",
        "category": "Marketing",
        "server_side": False,
        "url_patterns": ["js.hs-scripts.com", "js.hs-analytics.net", "track.hubspot.com", "js.hs-banner.com", "js.hsadspixel.net"],
        "collect_hosts": ["track.hubspot.com/__ptq.gif", "track.hubspot.com/__trk"],
    },
    {
        "platform": "Klaviyo",
        "category": "Marketing",
        "server_side": True,
        "url_patterns": ["fast.a.klaviyo.com", "static.klaviyo.com", "a.klaviyo.com"],
        "collect_hosts": ["a.klaviyo.com/api", "a.klaviyo.com/onsite"],
    },
    {
        "platform": "Attentive",
        "category": "Marketing",
        "server_side": True,
        "url_patterns": ["cdn.attn.tv", "events.attentivemobile.com"],
        "collect_hosts": ["events.attentivemobile.com"],
    },
    {
        "platform": "Marketo",
        "category": "Marketing",
        "server_side": False,
        "url_patterns": ["marketo.net/munchkin.js", "mktoresp.com", ".marketo.net/webevents"],
        "collect_hosts": ["mktoresp.com/webevents", ".marketo.net/webevents"],
    },
    {
        "platform": "Pardot",
        "category": "Marketing",
        "server_side": False,
        "url_patterns": ["pi.pardot.com", "go.pardot.com", "pardot.com/pd"],
        "collect_hosts": ["pi.pardot.com/analytics", "go.pardot.com"],
    },
    {
        "platform": "Mailchimp",
        "category": "Marketing",
        "server_side": False,
        "url_patterns": ["chimpstatic.com", "list-manage.com/subscribe", "mailchimp.com/mc"],
        "collect_hosts": ["list-manage.com/subscribe"],
    },

    # ===== Engagement / Live chat =====
    {
        "platform": "Intercom",
        "category": "Engagement",
        "server_side": False,
        "url_patterns": ["widget.intercom.io", "api.intercom.io", "nexus.intercom.io", "api-iam.intercom.io"],
        "collect_hosts": ["api-iam.intercom.io", "api.intercom.io/messenger"],
    },
    {
        "platform": "Drift",
        "category": "Engagement",
        "server_side": False,
        "url_patterns": ["js.driftt.com", "js.drift.com", "widget.drift.com", "customer.drift.com"],
        "collect_hosts": ["customer.drift.com", "event.api.drift.com"],
    },
    {
        "platform": "Zendesk",
        "category": "Engagement",
        "server_side": False,
        "url_patterns": ["static.zdassets.com", ".zdassets.com", ".zendesk.com/embeddable"],
        "collect_hosts": [".zdassets.com/ekr/snippet.js", ".zendesk.com/embeddable"],
    },
]

# ---------------------------------------------------------------------------
# COOKIES — matched against cookie names. `match` is "exact" or "prefix".
# `typical_days` is the vendor's intended lifetime; actual (observed) lifetime
# is what gets reported, and that's what ITP/browser caps affect.
# ---------------------------------------------------------------------------
COOKIES = [
    {"name": "_ga", "match": "exact", "provider": "Google", "category": "Analytics", "typical_days": 730},
    {"name": "_ga_", "match": "prefix", "provider": "Google", "category": "Analytics", "typical_days": 730},
    {"name": "_gid", "match": "exact", "provider": "Google", "category": "Analytics", "typical_days": 1},
    {"name": "_gat", "match": "prefix", "provider": "Google", "category": "Analytics", "typical_days": 1},
    {"name": "_gcl_au", "match": "exact", "provider": "Google", "category": "Advertising", "typical_days": 90},
    {"name": "_gcl_aw", "match": "exact", "provider": "Google", "category": "Advertising", "typical_days": 90},
    {"name": "_gcl_gb", "match": "exact", "provider": "Google", "category": "Advertising", "typical_days": 90},
    {"name": "_gcl_dc", "match": "exact", "provider": "Google", "category": "Advertising", "typical_days": 90},
    {"name": "_fbp", "match": "exact", "provider": "Meta", "category": "Advertising", "typical_days": 90},
    {"name": "_fbc", "match": "exact", "provider": "Meta", "category": "Advertising", "typical_days": 90},
    {"name": "li_fat_id", "match": "exact", "provider": "LinkedIn", "category": "Advertising", "typical_days": 30},
    {"name": "lidc", "match": "exact", "provider": "LinkedIn", "category": "Advertising", "typical_days": 1},
    {"name": "bcookie", "match": "exact", "provider": "LinkedIn", "category": "Advertising", "typical_days": 365},
    {"name": "_rdt_cid", "match": "exact", "provider": "Reddit", "category": "Advertising", "typical_days": 90},
    {"name": "_rdt_uuid", "match": "exact", "provider": "Reddit", "category": "Advertising", "typical_days": 90},
    {"name": "_clck", "match": "exact", "provider": "Microsoft", "category": "Session replay", "typical_days": 365},
    {"name": "_clsk", "match": "exact", "provider": "Microsoft", "category": "Session replay", "typical_days": 1},
    {"name": "_uetsid", "match": "exact", "provider": "Microsoft", "category": "Advertising", "typical_days": 1},
    {"name": "_uetvid", "match": "exact", "provider": "Microsoft", "category": "Advertising", "typical_days": 390},
    {"name": "_ttp", "match": "exact", "provider": "TikTok", "category": "Advertising", "typical_days": 390},
    {"name": "_tt_enable_cookie", "match": "exact", "provider": "TikTok", "category": "Advertising", "typical_days": 390},
    {"name": "_pin_unauth", "match": "exact", "provider": "Pinterest", "category": "Advertising", "typical_days": 365},
    {"name": "_pinterest_ct", "match": "prefix", "provider": "Pinterest", "category": "Advertising", "typical_days": 365},
    {"name": "_scid", "match": "exact", "provider": "Snapchat", "category": "Advertising", "typical_days": 390},
    {"name": "_hjSessionUser", "match": "prefix", "provider": "Hotjar", "category": "Session replay", "typical_days": 365},
    {"name": "_hjSession", "match": "prefix", "provider": "Hotjar", "category": "Session replay", "typical_days": 1},
    {"name": "hubspotutk", "match": "exact", "provider": "HubSpot", "category": "Marketing", "typical_days": 180},
    {"name": "__hssc", "match": "exact", "provider": "HubSpot", "category": "Marketing", "typical_days": 1},
    {"name": "__hssrc", "match": "exact", "provider": "HubSpot", "category": "Marketing", "typical_days": 1},
    {"name": "ajs_anonymous_id", "match": "exact", "provider": "Segment", "category": "CDP", "typical_days": 365},
    {"name": "amplitude_id", "match": "prefix", "provider": "Amplitude", "category": "Analytics", "typical_days": 730},
    {"name": "mp_", "match": "prefix", "provider": "Mixpanel", "category": "Analytics", "typical_days": 365},
    {"name": "__klaviyo", "match": "prefix", "provider": "Klaviyo", "category": "Marketing", "typical_days": 730},
    {"name": "intercom-id-", "match": "prefix", "provider": "Intercom", "category": "Engagement", "typical_days": 270},
    {"name": "intercom-session-", "match": "prefix", "provider": "Intercom", "category": "Engagement", "typical_days": 7},
    {"name": "driftt_aid", "match": "exact", "provider": "Drift", "category": "Engagement", "typical_days": 365},
    {"name": "ph_", "match": "prefix", "provider": "PostHog", "category": "Analytics", "typical_days": 365},
    # Adobe
    {"name": "s_sq", "match": "exact", "provider": "Adobe", "category": "Analytics", "typical_days": 1},
    {"name": "s_vi", "match": "exact", "provider": "Adobe", "category": "Analytics", "typical_days": 730},
    {"name": "AMCVS_", "match": "prefix", "provider": "Adobe", "category": "Analytics", "typical_days": 1},
    {"name": "AMCV_", "match": "prefix", "provider": "Adobe", "category": "Analytics", "typical_days": 730},
    # Marketo
    {"name": "_mkto_trk", "match": "exact", "provider": "Marketo", "category": "Marketing", "typical_days": 730},
]

# ---------------------------------------------------------------------------
# CMPs — Consent-Management Platforms. Detected the same way as trackers but
# surfaced separately so the UI can flag "scan may be consent-gated". The
# scanner also uses `accept_selectors` to try to auto-click the "Accept all"
# button so tags DO fire during the scan.
# ---------------------------------------------------------------------------
CMPS = [
    {
        "platform": "OneTrust",
        "url_patterns": ["cdn.cookielaw.org", "optanon.blob.core.windows.net", "cookie-cdn.cookiepro.com", "cookiepro.com", "onetrust-cdn"],
        "accept_selectors": [
            "#onetrust-accept-btn-handler",
            "button#onetrust-accept-btn-handler",
            ".onetrust-close-btn-handler",
        ],
    },
    {
        "platform": "Cookiebot",
        "url_patterns": ["consent.cookiebot.com", "consent.cookiebot.eu", "consentcdn.cookiebot.com"],
        "accept_selectors": [
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
            "#CybotCookiebotDialogBodyLevelButtonAccept",
        ],
    },
    {
        "platform": "Didomi",
        "url_patterns": ["sdk.privacy-center.org", ".didomi.io"],
        "accept_selectors": [
            "#didomi-notice-agree-button",
            ".didomi-components-button--primary",
        ],
    },
    {
        "platform": "TrustArc",
        "url_patterns": ["consent.trustarc.com", "trustarc.com/notice"],
        "accept_selectors": [
            ".pdynamicbutton[call='agreeAll']",
            ".call-call_bn_agree_all",
            ".truste-button2",
        ],
    },
    {
        "platform": "Osano",
        "url_patterns": ["cmp.osano.com", "osano.com/cm"],
        "accept_selectors": [".osano-cm-accept-all", "button.osano-cm-accept"],
    },
    {
        "platform": "CookieYes",
        "url_patterns": ["cdn-cookieyes.com", "cookieyes.com"],
        "accept_selectors": [".cky-btn-accept", "#ckySuperAccept", "button[data-cky-tag='accept-button']"],
    },
    {
        "platform": "Iubenda",
        "url_patterns": ["cdn.iubenda.com", "cs.iubenda.com"],
        "accept_selectors": [".iubenda-cs-accept-btn", "#iubenda-cs-banner .iubenda-cs-accept-btn"],
    },
    {
        "platform": "Quantcast Choice",
        "url_patterns": ["quantcast.mgr.consensu.org", ".choice.quantcast"],
        "accept_selectors": [".qc-cmp2-summary-buttons button[mode='primary']", "button.css-47sehv"],
    },
    {
        "platform": "Termly",
        "url_patterns": ["app.termly.io", ".termly.io"],
        "accept_selectors": [".t-preference-button button[data-tid='banner-accept']", "button.ctcc-banner__btn"],
    },
    {
        "platform": "Usercentrics",
        "url_patterns": ["app.usercentrics.eu", "api.usercentrics.eu", "usercentrics.eu/latest"],
        "accept_selectors": [
            "button[data-testid='uc-accept-all-button']",
            "#usercentrics-root >>> button[data-testid='uc-accept-all-button']",
        ],
    },
    {
        "platform": "Cookie Script",
        "url_patterns": ["cookie-script.com"],
        "accept_selectors": ["#cookiescript_accept"],
    },
    {
        "platform": "Secure Privacy",
        "url_patterns": ["cdn.secureprivacy.ai", "app.secureprivacy.ai"],
        "accept_selectors": ["button#sp-cc-accept"],
    },
    # Generic WordPress Cookie Notice
    {
        "platform": "WP Cookie Notice",
        "url_patterns": ["/wp-content/plugins/cookie-notice/"],
        "accept_selectors": ["#cn-accept-cookie"],
    },
]

# A short list of generic text/attribute-based buttons tried as a last-ditch
# fallback when no CMP matched. Attempts in order; stops at first success.
GENERIC_ACCEPT_SELECTORS = [
    "button[aria-label*='accept all' i]",
    "button[aria-label*='accept cookies' i]",
    "button[title*='accept all' i]",
    "button[id*='accept-all' i]",
    "button[id*='acceptAll' i]",
    "button[class*='accept-all' i]",
    "button[class*='acceptAll' i]",
    "a[id*='accept-all' i]",
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


def match_cmp(url: str):
    """Return the CMP dict whose url_patterns appear in `url`, else None."""
    low = url.lower()
    for c in CMPS:
        for pat in c["url_patterns"]:
            if pat in low:
                return c
    return None
