"""
The scanning engine.

Loads a URL in a headless Chromium browser (via Playwright), records every
network request the page makes and every cookie it sets, then reduces that raw
data into:

    - detected trackers (platform, category, client- vs server-side, status)
    - detected cookies (name, provider, category, actual lifetime in days)
    - consent mode v2 configuration (detected / not detected, settings)
    - page-speed timing metrics

The heavy lifting is deliberately kept here; scoring.py and recommendations.py
consume the plain dicts this module returns so they can be unit-tested without a
browser.
"""

from __future__ import annotations

import glob
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

import signatures


def _find_headless_shell() -> str | None:
    """
    Locate a chromium-headless-shell binary if the full chromium build isn't
    available. Lets the scanner run in constrained environments where only the
    smaller headless shell could be installed. Override with PW_CHROME_PATH.
    """
    env = os.environ.get("PW_CHROME_PATH")
    if env and os.path.exists(env):
        return env
    home = os.path.expanduser("~")
    patterns = [
        os.path.join(home, ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"),
        os.path.join(home, ".cache/ms-playwright/chromium-*/chrome-linux/chrome"),
    ]
    for pat in patterns:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


# ── Fix 4: Stealth args to bypass basic bot detection ────────────────────
_STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=site-per-process",
    "--disable-infobars",
]

_STEALTH_JS = """
// Mask navigator.webdriver so basic bot-detection scripts see a real browser
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
// Provide a realistic chrome object
window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
// Realistic permissions query
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (params) =>
    params.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(params);
"""


def _launch(p):
    """Launch chromium with stealth args, falling back to a headless-shell."""
    exe = _find_headless_shell()
    try:
        return p.chromium.launch(args=_STEALTH_ARGS)
    except Exception:
        if exe:
            return p.chromium.launch(args=_STEALTH_ARGS, executable_path=exe)
        raise


# How we decide client-side vs server-side:
#   A tag is "server-side" when its collection request is proxied through a
#   first-party host (same registrable domain as the site) instead of hitting
#   the vendor's own domain directly. This is the pattern a Stape / sGTM setup
#   produces. It is a heuristic, not a guarantee, and we label it as such.
def _registrable_domain(host: str) -> str:
    """Very small eTLD+1 approximation good enough for the client/server check."""
    parts = host.lower().split(".")
    if len(parts) <= 2:
        return host.lower()
    # Handle common two-level public suffixes (co.uk, com.au, ...)
    two_level = {"co", "com", "org", "net", "gov", "ac", "edu"}
    if parts[-2] in two_level and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


# ── Fix 1: Auto-click consent banners ────────────────────────────────────
# Common selectors for "Accept all" / "Accept cookies" buttons found on the
# vast majority of cookie-consent banners (OneTrust, Cookiebot, CookieYes,
# Didomi, TrustArc, Complianz, GDPR Cookie Consent, and generic patterns).
# Order matters: more specific first, generic last.
_CONSENT_SELECTORS = [
    # OneTrust
    "#onetrust-accept-btn-handler",
    # Cookiebot
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    # CookieYes
    ".cky-btn-accept",
    # Didomi
    "#didomi-notice-agree-button",
    # TrustArc
    ".trustarc-agree-btn",
    # Complianz
    ".cmplz-btn.cmplz-accept",
    # Iubenda
    ".iubenda-cs-accept-btn",
    # Quantcast / CMP generic
    ".qc-cmp2-summary-buttons button[mode='primary']",
    # Klaro
    ".klaro .cm-btn-accept",
    # Generic patterns that cover many custom banners
    "button[data-testid='cookie-accept']",
    "button[data-action='accept']",
    "[id*='cookie'] button[class*='accept']",
    "[id*='consent'] button[class*='accept']",
    "[class*='cookie-banner'] button[class*='accept']",
    "[class*='consent-banner'] button[class*='accept']",
    # Very broad last-resort: visible buttons whose text says "accept all"
    # (handled via JS below, not CSS selector)
]

# JS fallback: find a visible button whose text matches common consent phrases.
_CONSENT_TEXT_JS = """
() => {
    const phrases = [
        'accept all', 'accept cookies', 'allow all', 'allow cookies',
        'agree', 'i agree', 'got it', 'ok', 'okay',
        'alle akzeptieren', 'alle cookies akzeptieren',   // German
        'tout accepter', 'accepter tout',                   // French
        'aceptar todo', 'aceptar todas',                    // Spanish
    ];
    const buttons = [...document.querySelectorAll('button, a[role="button"], [class*="btn"]')];
    for (const btn of buttons) {
        const text = (btn.textContent || '').trim().toLowerCase();
        const visible = btn.offsetParent !== null && btn.offsetWidth > 0;
        if (visible && phrases.some(p => text === p || text.startsWith(p))) {
            btn.click();
            return true;
        }
    }
    return false;
}
"""


def _dismiss_consent(page) -> bool:
    """Try to click a cookie-consent 'Accept' button. Returns True if clicked."""
    # First try CSS selectors (fast)
    for sel in _CONSENT_SELECTORS:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                return True
        except Exception:
            continue
    # Fallback: text-match via JS
    try:
        return bool(page.evaluate(_CONSENT_TEXT_JS))
    except Exception:
        return False


# ── Fix 3: Consent Mode v2 detection ─────────────────────────────────────
_CONSENT_MODE_JS = """
() => {
    const result = { detected: false, settings: {} };

    // Check dataLayer for consent default/update commands
    const dl = window.dataLayer || [];
    for (const entry of dl) {
        // gtag('consent', 'default', {...}) pushes [\"consent\", \"default\", {...}]
        // but GTM's dataLayer format varies; check both shapes.
        if (Array.isArray(entry)) {
            if (entry[0] === 'consent' && (entry[1] === 'default' || entry[1] === 'update')) {
                result.detected = true;
                if (typeof entry[2] === 'object') {
                    Object.assign(result.settings, entry[2]);
                }
            }
        }
        // Object shape: {event: 'consent_update', ...} or similar
        if (entry && typeof entry === 'object' && !Array.isArray(entry)) {
            const keys = ['ad_storage', 'analytics_storage', 'ad_user_data', 'ad_personalization'];
            for (const k of keys) {
                if (k in entry) {
                    result.detected = true;
                    result.settings[k] = entry[k];
                }
            }
        }
    }

    // Also check for the Google consent signal on the page
    if (window.google_tag_data && window.google_tag_data.ics) {
        result.detected = true;
    }

    // Check if gtag consent command function exists
    if (typeof window.gtag === 'function') {
        try {
            // Look for consent entries in the command queue
            const q = window.dataLayer;
            for (const e of q) {
                if (e && e[0] === 'consent') {
                    result.detected = true;
                }
            }
        } catch(e) {}
    }

    // Detect Consent Mode v2 specific keys (ad_user_data, ad_personalization)
    const v2Keys = ['ad_user_data', 'ad_personalization'];
    result.is_v2 = v2Keys.some(k => k in result.settings);

    return result;
}
"""


# ── Fix 2: Smart post-load wait (network-idle heuristic) ─────────────────
def _wait_for_network_idle(page, idle_ms: int = 2000, budget_ms: int = 8000):
    """
    Wait until no new network requests fire for `idle_ms`, or until
    `budget_ms` total wall time has elapsed — whichever comes first.
    This catches late-firing tags (deferred scripts, SPA hydration,
    consent-gated pixels) without wasting time on fast sites.
    """
    start = time.time()
    deadline = start + budget_ms / 1000
    last_count = len(page.context.pages[0]._impl_obj._raw_requests if hasattr(page, '_impl_obj') else [])

    # Use a simpler approach: poll request count via small waits
    prev_count = 0
    stable_since = time.time()

    while time.time() < deadline:
        page.wait_for_timeout(500)
        # Count requests observed so far (tracked by the parent via on("request"))
        # We can't easily access the list here, so we use a page-level check:
        try:
            current_resources = page.evaluate("performance.getEntriesByType('resource').length")
        except Exception:
            break
        if current_resources == prev_count:
            if (time.time() - stable_since) * 1000 >= idle_ms:
                break
        else:
            prev_count = current_resources
            stable_since = time.time()


def scan(url: str, timeout_ms: int = 30000) -> dict:
    """Scan `url` and return a structured findings dict."""
    if not urlparse(url).scheme:
        url = "https://" + url

    site_domain = _registrable_domain(urlparse(url).netloc)

    requests: list[str] = []
    started = time.time()

    try:
        return _scan_with_browser(url, site_domain, requests, started, timeout_ms)
    except Exception as e:
        # Browser couldn't launch or crashed (e.g. version/executable mismatch).
        # Fail gracefully so the web app shows a message instead of a 500.
        return {"error": f"Browser engine error: {e}", "url": url}


def _scan_with_browser(url, site_domain, requests, started, timeout_ms) -> dict:
    with sync_playwright() as p:
        browser = _launch(p)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )

        # ── Fix 4: Inject stealth script before any page loads ────────
        context.add_init_script(_STEALTH_JS)

        page = context.new_page()
        page.on("request", lambda r: requests.append(r.url))

        timings = {}
        consent_mode = {"detected": False, "settings": {}, "is_v2": False}
        consent_dismissed = False
        error = None
        try:
            resp = page.goto(url, wait_until="load", timeout=timeout_ms)
            final_url = page.url
            status_code = resp.status if resp else None

            # ── Fix 1: Dismiss cookie-consent banner before waiting ───
            # Give the consent banner a moment to render (many inject late).
            page.wait_for_timeout(1500)
            consent_dismissed = _dismiss_consent(page)

            # ── Fix 2: Smart wait — network idle or 8s budget ─────────
            # After dismissing consent, tags that were gated will now fire.
            # Wait for network to settle instead of a fixed 3.5s.
            _wait_for_network_idle(page, idle_ms=2000, budget_ms=8000)

            # ── Fix 3: Detect Consent Mode v2 ────────────────────────
            try:
                consent_mode = page.evaluate(_CONSENT_MODE_JS)
            except Exception:
                consent_mode = {"detected": False, "settings": {}, "is_v2": False}

            try:
                timings = page.evaluate(
                    """() => {
                        const n = performance.getEntriesByType('navigation')[0] || {};
                        return {
                          domContentLoaded: n.domContentLoadedEventEnd || 0,
                          load: n.loadEventEnd || 0,
                          responseEnd: n.responseEnd || 0,
                          resourceCount: performance.getEntriesByType('resource').length
                        };
                    }"""
                )
            except Exception:
                timings = {}
            raw_cookies = context.cookies()
        except Exception as e:  # navigation failed / timed out
            error = str(e)
            final_url = url
            status_code = None
            raw_cookies = []
        finally:
            wall_load = round(time.time() - started, 2)
            browser.close()

    if error and not requests:
        return {"error": error, "url": url}

    trackers = _detect_trackers(requests, site_domain)
    cookies = _detect_cookies(raw_cookies)
    speed = _page_speed(timings, requests, wall_load)

    return {
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "site_domain": site_domain,
        "trackers": trackers,
        "cookies": cookies,
        "consent_mode": consent_mode,
        "consent_dismissed": consent_dismissed,
        "speed": speed,
        "request_count": len(requests),
        "error": None,
    }


def _detect_trackers(requests: list[str], site_domain: str) -> list[dict]:
    """Collapse raw requests into a de-duplicated list of detected trackers."""
    found: dict[str, dict] = {}
    for url in requests:
        sig = signatures.match_tracker(url)
        if not sig:
            continue
        host = urlparse(url).netloc
        proxied = _registrable_domain(host) == site_domain
        collect = signatures.is_collect_hit(url, sig)

        entry = found.setdefault(
            sig["platform"],
            {
                "platform": sig["platform"],
                "category": sig["category"],
                "server_side_supported": sig["server_side"],
                "fired": False,          # saw an actual collection hit
                "server_side": False,    # collection hit was first-party proxied
            },
        )
        if collect:
            entry["fired"] = True
            if proxied:
                entry["server_side"] = True

    # Build display rows with method + status.
    rows = []
    for e in found.values():
        if e["server_side"]:
            method = "Server-side"
            status = "Good"
        else:
            method = "Client-side"
            if not e["server_side_supported"]:
                status = "Server-side tracking not supported"
            else:
                status = "Improve"
        rows.append(
            {
                "platform": e["platform"],
                "category": e["category"],
                "method": method,
                "status": status,
                "server_side_supported": e["server_side_supported"],
                "fired": e["fired"],
            }
        )
    # Analytics first, then Advertising, then the rest — matches Stape ordering.
    order = {"Analytics": 0, "Advertising": 1, "Tag manager": 2}
    rows.sort(key=lambda r: (order.get(r["category"], 9), r["platform"]))
    return rows


def _detect_cookies(raw_cookies: list[dict]) -> list[dict]:
    """Map browser cookies to known signatures with actual observed lifetime."""
    now = time.time()
    out = {}
    for c in raw_cookies:
        sig = signatures.match_cookie(c.get("name", ""))
        if not sig:
            continue
        expires = c.get("expires", -1)
        if expires and expires > 0:
            days = max(0, round((expires - now) / 86400))
        else:
            days = None  # session cookie
        # Collapse cookies that share a signature name (e.g. _ga_ABC, _ga_DEF).
        key = sig["name"]
        display_name = c["name"]
        if sig["match"] == "prefix":
            display_name = sig["name"] + "{id}"
        out.setdefault(
            key,
            {
                "name": display_name,
                "provider": sig["provider"],
                "category": sig["category"],
                "lifetime_days": days,
                "typical_days": sig["typical_days"],
                "http_only": c.get("httpOnly", False),
            },
        )
    order = {"Analytics": 0, "Advertising": 1}
    return sorted(out.values(), key=lambda r: (order.get(r["category"], 9), r["provider"]))


def _page_speed(timings: dict, requests: list[str], wall_load: float) -> dict:
    """Derive page-speed metrics used by scoring."""
    load_ms = timings.get("load") or 0
    if not load_ms:
        load_ms = wall_load * 1000
    third_party = 0
    for u in requests:
        sig = signatures.match_tracker(u)
        if sig:
            third_party += 1
    return {
        "load_ms": int(load_ms),
        "dom_content_loaded_ms": int(timings.get("domContentLoaded") or 0),
        "resource_count": int(timings.get("resourceCount") or len(requests)),
        "tracking_requests": third_party,
    }


if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://www.example.com"
    print(json.dumps(scan(target), indent=2))
