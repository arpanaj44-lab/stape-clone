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


def generate(url: str) -> dict:
    findings = scanner.scan(url)
    if findings.get("error"):
        return {"error": findings["error"], "url": findings.get("url", url)}

    scores = scoring.score_all(findings)
    recs = recommendations.build(findings, scores)

    # Traffic + impact estimates (only when a traffic provider is configured).
    traffic = traffic_provider.estimate(findings["site_domain"])
    impact = estimates.compute(findings, traffic)

    # Semrush v4 site authority (only when SEMRUSH_API_KEY is set). Independent
    # of traffic; failure is silent (report just omits the section).
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
        "impact": impact,
        "authority": authority,
        "recommendations": recs,
    }


if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "https://www.example.com"
    print(json.dumps(generate(target), indent=2))
