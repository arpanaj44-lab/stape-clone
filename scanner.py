"""
The scanning engine.

Loads a URL in a headless Chromium browser (via Playwright), records every
network request the page makes and every cookie it sets, then reduces that raw
data into:

    - detected trackers (platform, category, client- vs server-side, status)
    - detected cookies (name, provider, category, actual lifetime in days)
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


def _launch(p):
    """Launch chromium, falling back to a standalone headless-shell binary."""
    args = ["--no-sandbox", "--disable-dev-shm-usage"]
    exe = _find_headless_shell()
    try:
        return p.chromium.launch(args=args)
    except Exception:
        if exe:
            return p.chromium.launch(args=args, executable_path=exe)
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


def scan(url: str, timeout_ms: int = 30000) -> dict:
    """Scan `url` and return a structured findings dict."""
    if not urlparse(url).scheme:
        url = "https://" + url

    site_domain = _registrable_domain(urlparse(url).netloc)

    requests: list[str] = []
    started = time.time()

    with sync_playwright() as p:
        browser = _launch(p)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.on("request", lambda r: requests.append(r.url))

        timings = {}
        error = None
        try:
            resp = page.goto(url, wait_until="load", timeout=timeout_ms)
            final_url = page.url
            status_code = resp.status if resp else None
            # Give late-firing tags (consent-gated, deferred) a moment.
            page.wait_for_timeout(3500)
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
