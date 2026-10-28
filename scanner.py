"""
The scanning engine (v2 — with consent-handling, loaded-vs-fired, CMP
detection, request-failure tracking, friendly errors, and multi-URL support).

Loads one or more URLs in a headless Chromium browser (via Playwright), records
every network request + failed request + cookie, tries to click common
consent-banner "Accept all" buttons so tags actually fire, and reduces that raw
data into:

    - detected trackers (platform, category, client/server, fired vs loaded-only)
    - detected cookies (name, provider, category, real observed lifetime)
    - detected CMPs (consent-management platforms present on the page)
    - blocked / failed tracking request counts
    - page-speed timing metrics
    - friendly error classification when navigation fails

Downstream modules (scoring, recommendations) are schema-compatible — new
fields are additive, no breaking changes.
"""

from __future__ import annotations

import glob
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

import signatures


# ──────────────────────────────────────────────────────────────────────────────
# Browser launch + helpers
# ──────────────────────────────────────────────────────────────────────────────
def _find_headless_shell() -> str | None:
    """Locate chromium-headless-shell as a fallback (sandbox envs)."""
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
    args = ["--no-sandbox", "--disable-dev-shm-usage"]
    exe = _find_headless_shell()
    try:
        return p.chromium.launch(args=args)
    except Exception:
        if exe:
            return p.chromium.launch(args=args, executable_path=exe)
        raise


def _registrable_domain(host: str) -> str:
    """Small eTLD+1 approximation for client/server-side classification."""
    parts = host.lower().split(".")
    if len(parts) <= 2:
        return host.lower()
    two_level = {"co", "com", "org", "net", "gov", "ac", "edu"}
    if parts[-2] in two_level and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


# ──────────────────────────────────────────────────────────────────────────────
# Error classification (#17)
# ──────────────────────────────────────────────────────────────────────────────
def _friendly_error(raw: str, status_code: int | None = None) -> str:
    """Turn a cryptic Playwright/network error string into a one-line reason."""
    s = (raw or "").lower()
    if status_code and status_code >= 400:
        return f"The site returned HTTP {status_code}."
    if "err_name_not_resolved" in s or "dns" in s:
        return "DNS lookup failed — the domain can't be found. Check the spelling."
    if "err_connection_refused" in s:
        return "The server refused the connection."
    if "err_connection_timed_out" in s or "err_timed_out" in s or "timeout" in s:
        return "The site timed out before it finished loading (>30 s)."
    if "err_cert" in s or "err_ssl" in s or "ssl" in s:
        return "The site has an SSL/certificate problem — it won't let us connect securely."
    if "err_too_many_redirects" in s:
        return "The site is stuck in a redirect loop."
    if "err_blocked" in s or "err_aborted" in s or "net::err_failed" in s:
        return "The site blocked our request (likely bot protection or geo-blocking)."
    if "err_http_response_code_failure" in s:
        return "The site returned an HTTP error."
    if "net::" in s:
        return f"Network error from the browser: {raw.strip().splitlines()[0]}"
    return f"Browser couldn't load the page: {raw[:160]}"


# ──────────────────────────────────────────────────────────────────────────────
# Consent handling (#1)
# ──────────────────────────────────────────────────────────────────────────────
def _try_accept_consent(page, cmps_seen: list[str]) -> dict:
    """
    Best-effort click on a CMP's 'Accept all' button so analytics/ad tags
    actually fire. Returns {clicked, selector, cmp}. Never raises.
    """
    info = {"attempted": False, "clicked": False, "selector": None, "cmp": None}
    tried: list[str] = []
    # 1) CMP-specific selectors first (strongest signal).
    for cmp in signatures.CMPS:
        if cmp["platform"] in cmps_seen:
            for sel in cmp.get("accept_selectors", []):
                tried.append(sel)
                if _click_if_present(page, sel):
                    info.update({"attempted": True, "clicked": True,
                                 "selector": sel, "cmp": cmp["platform"]})
                    return info
    # 2) Try ALL known CMP selectors even if we didn't see the script —
    #    many CMPs inject only inline HTML, no identifiable network request.
    for cmp in signatures.CMPS:
        if cmp["platform"] in cmps_seen:
            continue  # already tried
        for sel in cmp.get("accept_selectors", []):
            tried.append(sel)
            if _click_if_present(page, sel):
                info.update({"attempted": True, "clicked": True,
                             "selector": sel, "cmp": cmp["platform"]})
                return info
    # 3) Generic text/attribute fallbacks.
    for sel in signatures.GENERIC_ACCEPT_SELECTORS:
        tried.append(sel)
        if _click_if_present(page, sel):
            info.update({"attempted": True, "clicked": True, "selector": sel, "cmp": "generic"})
            return info
    # 4) Text-based last-ditch via XPath (matches English "Accept all"-style buttons).
    for text in ("Accept all", "Accept All", "I accept", "Allow all", "Agree and continue", "Accept Cookies"):
        xp = f"xpath=//button[contains(normalize-space(.), '{text}')] | //a[contains(normalize-space(.), '{text}')]"
        tried.append(xp)
        if _click_if_present(page, xp):
            info.update({"attempted": True, "clicked": True, "selector": xp, "cmp": "text-match"})
            return info
    info["attempted"] = bool(tried)
    info["tried_count"] = len(tried)
    return info


def _click_if_present(page, selector: str) -> bool:
    try:
        loc = page.locator(selector).first
        if loc.count() > 0 and loc.is_visible(timeout=600):
            loc.click(timeout=1500, force=True)
            return True
    except Exception:
        pass
    return False


# ──────────────────────────────────────────────────────────────────────────────
# The public scan API
# ──────────────────────────────────────────────────────────────────────────────
def scan(url, timeout_ms: int = 35000) -> dict:
    """
    Scan a URL (or a list of URLs — multi-page mode, #9) and return a
    structured findings dict. For multi-page, trackers / cookies / CMPs are
    merged (union), with the firing status upgraded when any page shows it.
    """
    urls = url if isinstance(url, (list, tuple)) else [url]
    urls = [u for u in (u.strip() for u in urls) if u][:3]  # cap at 3 pages
    if not urls:
        return {"error": "No URL provided.", "url": ""}

    # Normalise all URLs
    norm = []
    for u in urls:
        if not urlparse(u).scheme:
            u = "https://" + u
        norm.append(u)

    site_domain = _registrable_domain(urlparse(norm[0]).netloc)

    page_results = []
    try:
        with sync_playwright() as p:
            browser = _launch(p)
            try:
                context = _new_context(browser)
                for u in norm:
                    page_results.append(_scan_one(context, u, site_domain, timeout_ms))
            finally:
                browser.close()
    except Exception as e:
        return {"error": _friendly_error(str(e)), "url": norm[0]}

    # If every page errored, surface the first error cleanly.
    if all(r.get("error") for r in page_results):
        first = page_results[0]
        return {"error": first.get("error", "Scan failed."), "url": first.get("url", norm[0])}

    return _merge_pages(page_results, norm, site_domain)


def _new_context(browser):
    return browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 900},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        ignore_https_errors=True,  # try to scan even sites with expired/misconfigured certs
    )


# ──────────────────────────────────────────────────────────────────────────────
# Per-page scan
# ──────────────────────────────────────────────────────────────────────────────
def _scan_one(context, url, site_domain, timeout_ms) -> dict:
    page = context.new_page()
    started = time.time()

    requests_seen: list[str] = []            # all outgoing
    failed_requests: list[dict] = []         # requestfailed events (#11)

    page.on("request", lambda r: requests_seen.append(r.url))
    page.on("requestfailed",
            lambda r: failed_requests.append({"url": r.url, "failure": (r.failure or "")}))

    error_text = None
    final_url = url
    status_code = None
    timings = {}
    raw_cookies: list[dict] = []
    consent = {"attempted": False, "clicked": False}
    cmps_seen: list[str] = []

    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        final_url = page.url
        status_code = resp.status if resp else None

        # Snapshot CMPs seen so far from script hosts, then try to accept.
        cmps_seen = _detect_cmps(requests_seen)
        consent = _try_accept_consent(page, cmps_seen)

        # Give post-consent/post-DCL tags time to fire.
        page.wait_for_timeout(4000)

        # Trigger a bit of interaction (helps "on scroll / on click" tags).
        try:
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(600)
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(1200)
        except Exception:
            pass

        # Refresh CMP list after new scripts loaded post-accept.
        cmps_seen = _detect_cmps(requests_seen)

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

    except Exception as e:
        error_text = _friendly_error(str(e), status_code)
    finally:
        wall_load = round(time.time() - started, 2)
        try:
            page.close()
        except Exception:
            pass

    if error_text and not requests_seen:
        return {"error": error_text, "url": url}

    trackers = _detect_trackers(requests_seen, failed_requests, site_domain)
    cookies = _detect_cookies(raw_cookies)
    speed = _page_speed(timings, requests_seen, wall_load)
    cmp_rows = _cmp_rows(cmps_seen, consent)
    blocked_tracking = sum(
        1 for f in failed_requests if signatures.match_tracker(f["url"])
    )

    return {
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "trackers": trackers,
        "cookies": cookies,
        "speed": speed,
        "cmps": cmp_rows,
        "consent": consent,
        "blocked_tracking_requests": blocked_tracking,
        "request_count": len(requests_seen),
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Multi-page merge (#9)
# ──────────────────────────────────────────────────────────────────────────────
def _merge_pages(page_results: list[dict], urls: list[str], site_domain: str) -> dict:
    successes = [r for r in page_results if not r.get("error")]
    # trackers: keyed by platform; upgrade status when any page shows better.
    tr_map: dict[str, dict] = {}
    status_rank = {"Server-side": 3, "Firing (client-side)": 2,
                   "Server-side tracking not supported": 1, "Loaded only": 0}
    for r in successes:
        for t in r.get("trackers", []):
            cur = tr_map.get(t["platform"])
            if cur is None or status_rank.get(t.get("method"), 0) > status_rank.get(cur.get("method"), 0):
                tr_map[t["platform"]] = t
    trackers = sorted(
        tr_map.values(),
        key=lambda r: ({"Analytics": 0, "Advertising": 1, "Tag manager": 2,
                        "CDP": 3, "Marketing": 4, "Session replay": 5,
                        "Engagement": 6}.get(r["category"], 9), r["platform"])
    )

    # cookies: keep longest observed lifetime per name.
    ck_map: dict[str, dict] = {}
    for r in successes:
        for c in r.get("cookies", []):
            cur = ck_map.get(c["name"])
            if cur is None or (c.get("lifetime_days") or 0) > (cur.get("lifetime_days") or 0):
                ck_map[c["name"]] = c
    cookies = list(ck_map.values())

    # CMPs: union
    cmp_map: dict[str, dict] = {}
    for r in successes:
        for c in r.get("cmps", []):
            cmp_map.setdefault(c["platform"], c)

    # speed: average of successful pages
    def avg(key):
        vals = [r["speed"].get(key, 0) or 0 for r in successes if r.get("speed")]
        return int(sum(vals) / len(vals)) if vals else 0
    speed = {
        "load_ms": avg("load_ms"),
        "dom_content_loaded_ms": avg("dom_content_loaded_ms"),
        "resource_count": avg("resource_count"),
        "tracking_requests": avg("tracking_requests"),
    }

    blocked = sum(r.get("blocked_tracking_requests", 0) for r in successes)
    consent_summary = next((r.get("consent") for r in successes if r.get("consent", {}).get("clicked")), successes[0].get("consent") if successes else {})

    primary = successes[0] if successes else page_results[0]
    return {
        "url": urls[0],
        "urls_scanned": [r["url"] for r in page_results],
        "pages_scanned": len(successes),
        "pages_total": len(page_results),
        "page_errors": [{"url": r["url"], "error": r.get("error")} for r in page_results if r.get("error")],
        "final_url": primary.get("final_url", urls[0]),
        "status_code": primary.get("status_code"),
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "site_domain": site_domain,
        "trackers": trackers,
        "cookies": cookies,
        "cmps": list(cmp_map.values()),
        "consent": consent_summary,
        "blocked_tracking_requests": blocked,
        "speed": speed,
        "request_count": sum(r.get("request_count", 0) for r in successes),
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Detection — trackers, cookies, CMPs, speed
# ──────────────────────────────────────────────────────────────────────────────
def _detect_trackers(requests_seen, failed_requests, site_domain) -> list[dict]:
    """
    Collapse raw requests into deduped trackers with LOADED-vs-FIRED split (#3).

    A tracker row has one of these methods:
        'Server-side'          — collection hit on a first-party host
        'Firing (client-side)' — collection hit on vendor host
        'Loaded only'          — library loaded but no collection hit observed
    """
    found: dict[str, dict] = {}

    def _mark(url_hit, from_failure=False):
        sig = signatures.match_tracker(url_hit)
        if not sig:
            return
        host = urlparse(url_hit).netloc
        proxied = _registrable_domain(host) == site_domain
        collect = signatures.is_collect_hit(url_hit, sig)
        entry = found.setdefault(
            sig["platform"],
            {
                "platform": sig["platform"],
                "category": sig["category"],
                "server_side_supported": sig["server_side"],
                "fired": False,
                "server_side": False,
                "loaded": False,
                "blocked": False,
            },
        )
        entry["loaded"] = True
        if collect:
            entry["fired"] = True
            if proxied:
                entry["server_side"] = True
        if from_failure and collect:
            entry["blocked"] = True

    for u in requests_seen:
        _mark(u)
    for f in failed_requests:
        _mark(f["url"], from_failure=True)

    rows = []
    for e in found.values():
        if e["server_side"]:
            method, status = "Server-side", "Good"
        elif e["fired"]:
            method = "Firing (client-side)"
            status = "Server-side tracking not supported" if not e["server_side_supported"] else "Improve"
        else:
            method = "Loaded only"
            status = "Loaded but not firing — check tag triggers"
        if e["blocked"] and not e["fired"]:
            method, status = "Blocked", "Blocked by ad-blocker or network"
        rows.append({
            "platform": e["platform"],
            "category": e["category"],
            "method": method,
            "status": status,
            "server_side_supported": e["server_side_supported"],
            "fired": e["fired"],
            "loaded": e["loaded"],
            "blocked": e["blocked"],
        })
    order = {"Analytics": 0, "Advertising": 1, "Tag manager": 2,
             "CDP": 3, "Marketing": 4, "Session replay": 5, "Engagement": 6}
    rows.sort(key=lambda r: (order.get(r["category"], 9), r["platform"]))
    return rows


def _detect_cookies(raw_cookies) -> list[dict]:
    now = time.time()
    out: dict[str, dict] = {}
    for c in raw_cookies:
        sig = signatures.match_cookie(c.get("name", ""))
        if not sig:
            continue
        expires = c.get("expires", -1)
        if expires and expires > 0:
            days = max(0, round((expires - now) / 86400))
        else:
            days = None
        key = sig["name"]
        display_name = c["name"]
        if sig["match"] == "prefix":
            display_name = sig["name"] + "{id}"
        out.setdefault(key, {
            "name": display_name,
            "provider": sig["provider"],
            "category": sig["category"],
            "lifetime_days": days,
            "typical_days": sig["typical_days"],
            "http_only": c.get("httpOnly", False),
            "same_site": c.get("sameSite"),
            "secure": c.get("secure", False),
        })
    order = {"Analytics": 0, "Advertising": 1}
    return sorted(out.values(), key=lambda r: (order.get(r["category"], 9), r["provider"]))


def _detect_cmps(requests_seen) -> list[str]:
    seen: list[str] = []
    for u in requests_seen:
        cmp = signatures.match_cmp(u)
        if cmp and cmp["platform"] not in seen:
            seen.append(cmp["platform"])
    return seen


def _cmp_rows(cmps_seen: list[str], consent: dict) -> list[dict]:
    rows = []
    for name in cmps_seen:
        rows.append({
            "platform": name,
            "accepted": consent.get("clicked") and (consent.get("cmp") == name or consent.get("cmp") in ("generic", "text-match")),
        })
    return rows


def _page_speed(timings, requests_seen, wall_load) -> dict:
    load_ms = timings.get("load") or 0
    if not load_ms:
        load_ms = wall_load * 1000
    third_party = sum(1 for u in requests_seen if signatures.match_tracker(u))
    return {
        "load_ms": int(load_ms),
        "dom_content_loaded_ms": int(timings.get("domContentLoaded") or 0),
        "resource_count": int(timings.get("resourceCount") or len(requests_seen)),
        "tracking_requests": third_party,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Top-level entry needs scanned_at even on single-page path
# ──────────────────────────────────────────────────────────────────────────────
_scan_impl = scan


def scan(url, timeout_ms: int = 35000) -> dict:  # noqa: F811 — override above
    out = _scan_impl(url, timeout_ms)
    if "error" in out and out.get("error"):
        return out
    out.setdefault("scanned_at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    out.setdefault("site_domain", _registrable_domain(urlparse(out.get("url", "")).netloc))
    return out


if __name__ == "__main__":
    import json, sys
    target = sys.argv[1] if len(sys.argv) > 1 else "https://www.example.com"
    print(json.dumps(scan(target), indent=2, default=str))
