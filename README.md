# Website Tracking Checker — MVP

A working clone of the core functionality behind Stape's *Website Tracking Checker*.
Enter any public URL → we load the page in a **real headless browser**, detect the
analytics/advertising **trackers** and **cookies** that fire, **score** the setup
across four pillars, and produce **prioritized, rule-based recommendations** for
improving tracking (mostly: move client-side tags to server-side, extend cookie
lifetimes).

> Not affiliated with Stape. Built as an independent MVP that reproduces the
> report's structure and logic. Scoring numbers are our own transparent heuristic.

![example report](sample_report_hubspot.html)

---

## Want a public link (no IDE needed)?

See **[DEPLOY.md](DEPLOY.md)** — deploy to a free Render tier in ~5–10 minutes
and get a shareable `https://…onrender.com` URL, or run it locally with one
Docker command. No Python setup required for either.

---

## Quick start (local Python)

**macOS / Linux**
```bash
cd tracking-checker
./run.sh
```

**Windows**
```bat
cd tracking-checker
run.bat
```

Then open <http://localhost:8000>, paste a URL, and click **Scan your site**.
A scan takes ~10–20 seconds while the page loads and its tags fire.

### Manual setup (if you prefer)
```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium                # downloads the browser once
uvicorn app:app --port 8000
```

---

## What the report contains

Mirrors the Stape report layout:

- **Overall score (0–100)** with a rating label (Great / Good / Needs work / Not good).
- **Four sub-scores:** Analytics, Ads, Cookie lifetime, Page speed.
- **Trackers detected** — platform, category, client-side vs server-side, and a status
  (`Good` / `Improve` / `Server-side tracking not supported`).
- **Tracking loss impact** — *users not tracked* and *ad spend impacted* per month,
  like Stape. These use a traffic-data provider (see below); without one, the section
  shows a "connect a provider" note instead of fabricated numbers.
- **Main tracking cookies detected** — name, provider, category, and *actual* observed
  lifetime (short ~7-day cookies are flagged as ITP-capped).
- **Recommended actions** — a narrative summary plus prioritized fixes, each with an
  estimated score improvement.

> Not built: the competitor-comparison table from Stape's report (skipped by request).

### Traffic-data provider (for the ad-spend / users-not-tracked estimates)

Traffic volume and ad spend can't be read from a page scan — Stape gets them from a
traffic-intelligence provider. Configure one with env vars:

| `TRAFFIC_PROVIDER` | Needs | Behaviour |
|---|---|---|
| *(unset)* / `none` | — | Impact section shows a "connect a provider" note |
| `mock` | — | Deterministic demo numbers, clearly labelled (quick look) |
| `manual` | `MONTHLY_VISITS` (+ optional `MONTHLY_AD_SPEND`, `PAID_SHARE`) | Your own numbers |
| `similarweb` | `SIMILARWEB_API_KEY` | Live monthly visits + paid share from Similarweb |

`AVG_CPC` (default `1.20`) derives ad spend from paid visits when the provider doesn't
return spend directly. The loss-rate model (how much tracking is lost, reduced by
server-side coverage) lives in `estimates.py` and is fully documented.

---

## How it works

```
URL ─▶ scanner.py ─▶ scoring.py ─────▶ recommendations.py ─▶ report.html
        (Playwright)   (heuristics)  │   (rule templates)      (Jinja2)
                                      └▶ traffic.py ─▶ estimates.py
                                        (data provider)  (impact model)
```

- **`scanner.py`** launches headless Chromium, records every network request and every
  cookie the page sets, measures load timing, then matches requests/cookies against the
  signature database.
- **`signatures.py`** — the knowledge base: known tracker request patterns and cookie
  names (GA4, Google Ads, Meta, LinkedIn, Reddit, Microsoft Clarity, TikTok, Bing/UET,
  Snapchat, Pinterest, X, Hotjar, HubSpot, Segment, Amplitude, Mixpanel…). Add an entry
  and the whole pipeline picks it up.
- **`scoring.py`** — transparent, documented scoring. Server-side tags and long-lived
  cookies score higher; ITP-capped cookies and slow/heavy pages score lower.
- **`recommendations.py`** — deterministic rules map findings to prioritized advice with
  score-improvement values and compose the narrative. No LLM, no API keys.
- **`app.py`** — FastAPI app: `GET /` (form), `POST /scan` (HTML report),
  `GET /api/scan?url=…` (raw JSON).

### Client-side vs server-side detection
Heuristic: a tag counts as **server-side** when its data-collection request is proxied
through a **first-party host** (same registrable domain as the site) instead of hitting
the vendor's own domain — the pattern a Stape / server-GTM setup produces. It's a signal,
not a guarantee, and is labeled as such.

---

## CLI / JSON usage

Generate a report as JSON without the web UI:
```bash
python report.py https://example.com          # full report dict
python scanner.py https://example.com         # raw findings only
```
Or hit the API:
```bash
curl "http://localhost:8000/api/scan?url=https://example.com"
```

---

## Extending it

- **Add a tracker or cookie:** append a dict to `TRACKERS` / `COOKIES` in `signatures.py`.
- **Tune the scoring:** weights and thresholds are constants at the top of `scoring.py`.
- **Change the advice:** edit templates in `recommendations.py`.

## Notes & limits (it's an MVP)

- Consent-gated tags/cookies may not fire during an automated visit, so a site behind a
  strict cookie wall can look "clean." A future version could auto-accept consent.
- The scan visits a single page (the URL given), not the whole site.
- Scores are a reasonable heuristic for prioritization, not an audited benchmark.
