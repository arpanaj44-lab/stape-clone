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
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import report as report_engine

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Website Tracking Checker (MVP)")


async def _run_scan(url: str) -> dict:
    return await asyncio.to_thread(report_engine.generate, url)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/scan", response_class=HTMLResponse)
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
    return templates.TemplateResponse(request, "report.html", {"r": data})


@app.get("/api/scan")
async def api_scan(url: str):
    return JSONResponse(await _run_scan(url))


@app.get("/health")
async def health():
    return {"ok": True}
