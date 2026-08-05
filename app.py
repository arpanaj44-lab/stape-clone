"""
Website Tracking Checker — MVP web app.

A single FastAPI service:
    GET  /            -> landing page with a URL input box
    POST /scan        -> runs a scan and renders the report (HTML)
    GET  /api/scan    -> ?url=... returns the raw report JSON (handy for testing)

Run:
    uvicorn app:app --reload --port 8000
Then open http://localhost:8000

The scan itself is blocking (Playwright sync API), so we run it in a thread
pool to keep the event loop responsive.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import report as report_engine

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Website Tracking Checker (MVP)")

# ---------------------------------------------------------------------------
# Shareable reports.
# Each scan is stored under a random id and served at /r/{id} so the URL can be
# shared. Reports expire after REPORT_TTL_HOURS (default 6). Storage is
# in-memory: simple and fine while the instance is running, but links are lost
# if the server restarts / a free-tier instance goes to sleep. For links that
# reliably survive the full TTL, back this with a database or a persistent disk.
# ---------------------------------------------------------------------------
REPORT_TTL_HOURS = float(os.environ.get("REPORT_TTL_HOURS", "6"))
_TTL = REPORT_TTL_HOURS * 3600
_REPORTS: dict[str, dict] = {}


def _purge() -> None:
    now = time.time()
    for rid in [k for k, v in _REPORTS.items() if now - v["created"] > _TTL]:
        _REPORTS.pop(rid, None)


def _store(data: dict) -> str:
    _purge()
    rid = uuid.uuid4().hex[:12]
    _REPORTS[rid] = {"data": data, "created": time.time()}
    return rid


def _share_ctx(request: Request, rid: str, created: float) -> dict:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
    expires = created + _TTL
    remaining_h = max(0, (expires - time.time()) / 3600)
    return {
        "url": f"{base}/r/{rid}",
        "expires_human": datetime.fromtimestamp(expires, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "ttl_hours": int(REPORT_TTL_HOURS) if REPORT_TTL_HOURS.is_integer() else REPORT_TTL_HOURS,
        "remaining_hours": round(remaining_h, 1),
    }


async def _run_scan(url: str) -> dict:
    return await asyncio.to_thread(report_engine.generate, url)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/scan")
async def scan(request: Request, url: str = Form(...)):
    url = url.strip()
    if not url:
        return templates.TemplateResponse(
            request, "index.html", {"error": "Please enter a URL."}
        )
    data = await _run_scan(url)
    if data.get("error"):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"error": f"Couldn't scan that URL: {data['error']}", "prefill": url},
        )
    # Store and redirect to a shareable, bookmarkable URL.
    rid = _store(data)
    return RedirectResponse(url=f"/r/{rid}", status_code=303)


@app.get("/r/{rid}", response_class=HTMLResponse)
async def shared_report(request: Request, rid: str):
    _purge()
    entry = _REPORTS.get(rid)
    if not entry:
        return templates.TemplateResponse(
            request, "expired.html", {"ttl_hours": int(REPORT_TTL_HOURS) if REPORT_TTL_HOURS.is_integer() else REPORT_TTL_HOURS},
            status_code=404,
        )
    share = _share_ctx(request, rid, entry["created"])
    return templates.TemplateResponse(request, "report.html", {"r": entry["data"], "share": share})


@app.get("/api/scan")
async def api_scan(url: str):
    return JSONResponse(await _run_scan(url))


@app.get("/api/traffic-debug")
async def traffic_debug(domain: str = "hubspot.com"):
    """Check whether the configured traffic provider (Apify etc.) is working.
    Visit /api/traffic-debug?domain=yoursite.com — secrets are never returned."""
    import traffic
    result = await asyncio.to_thread(traffic.diagnose, domain)
    return JSONResponse(result)


@app.get("/api/authority-debug")
async def authority_debug(domain: str = "hubspot.com"):
    """Check whether the Semrush v4 key + Backlinks Overview endpoint is working.
    Visit /api/authority-debug?domain=yoursite.com — the key is never returned."""
    import semrush
    result = await asyncio.to_thread(semrush.diagnose, domain)
    return JSONResponse(result)


@app.get("/health")
async def health():
    return {"ok": True}
