"""
Orchestration layer: URL in -> full report dict out.

Kept separate from the web layer so the same function backs both the web app
and the CLI (`python report.py <url>`).
"""

from __future__ import annotations

import scanner
import scoring
import recommendations
import traffic as traffic_provider
import estimates
import semrush as semrush_provider


def generate(url) -> dict:
    """
    `url` may be a single string or a list (for multi-page scans).
    """
    findings = scanner.scan(url)
    if findings.get("error"):
        first_url = findings.get("url") or (url if isinstance(url, str) else (url[0] if url else ""))
        return {"error": findings["error"], "url": first_url}

    scores = scoring.score_all(findings)
    recs = recommendations.build(findings, scores)

    traffic = traffic_provider.estimate(findings["site_domain"])
    impact = estimates.compute(findings, traffic)

    authority = None
    try:
        authority = semrush_provider.fetch_authority(findings["site_domain"])
    except Exception:
        authority = None

    return {
        "error": None,
        "url": findings["url"],
        "final_url": findings["final_url"],
        "scanned_at": findings["scanned_at"],
        "site_domain": findings["site_domain"],
        "scores": scores,
        "trackers": findings["trackers"],
        "cookies": findings["cookies"],
        "speed": findings["speed"],
        # New (v2 scanner) fields — safe for templates to .get() with defaults.
        "cmps": findings.get("cmps", []),
        "consent": findings.get("consent", {}),
        "cloudflare_challenge": findings.get("cloudflare_challenge", {}),
        "blocked_tracking_requests": findings.get("blocked_tracking_requests", 0),
        "urls_scanned": findings.get("urls_scanned", [findings.get("url", "")]),
        "pages_scanned": findings.get("pages_scanned", 1),
        "pages_total": findings.get("pages_total", 1),
        "page_errors": findings.get("page_errors", []),
        "impact": impact,
        "authority": authority,
        "recommendations": recs,
    }


if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://www.example.com"
    print(json.dumps(generate(target), indent=2))
