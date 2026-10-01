"""HTTP API for the FinAnalyx (Vercel serverless function / any ASGI host).

Routes
  GET  /api/health
  GET  /api/search?q=reliance
  GET  /api/quote/{symbol}                         live price + intraday path
  GET  /api/company/{symbol}?source=auto|sec|yahoo&years=5&basis=average&format=json|xlsx|html
  POST /api/analyze   multipart: files[], company?, basis?, format?   (CSV / Excel / PDF upload)

Run locally:  uvicorn api.index:app --reload   (also serves the web UI from ./public)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, Form, Query, Request, UploadFile  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response  # noqa: E402

from finanalyx import __version__, providers  # noqa: E402
from finanalyx.analyzer import Analysis, analyze, analyze_tables  # noqa: E402
from finanalyx.export import clean, to_dict, to_excel  # noqa: E402
from finanalyx.ingest import SUPPORTED_EXTENSIONS, IngestError  # noqa: E402
from finanalyx.providers import ProviderError  # noqa: E402
from finanalyx.report_html import render_html  # noqa: E402

log = logging.getLogger("finanalyx.api")

MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # Vercel caps request bodies at 4.5 MB
MAX_FILES = 12
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-^=&]{1,20}$")

app = FastAPI(title="FinAnalyx API", version=__version__,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)


# ------------------------------------------------------------------ errors

def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status, headers={"Cache-Control": "no-store"})


@app.exception_handler(ProviderError)
async def _provider_error(_: Request, exc: ProviderError):
    return _error(str(exc), exc.status)


@app.exception_handler(IngestError)
async def _ingest_error(_: Request, exc: IngestError):
    return _error(str(exc), 422)


@app.exception_handler(ValueError)
async def _value_error(_: Request, exc: ValueError):
    return _error(str(exc), 422)


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return _error("Something went wrong while analysing this company. Please try again.", 500)


# ----------------------------------------------------------------- helpers

def _symbol(symbol: str) -> str:
    symbol = symbol.strip()
    if not SYMBOL_RE.match(symbol):
        raise ProviderError("That doesn't look like a ticker symbol (e.g. AAPL, RELIANCE.NS, 500325.BO).", 400)
    return symbol.upper()


def _valuation_inputs(a: Analysis) -> dict:
    """Latest fundamentals the browser needs to recompute valuation multiples as the price moves."""
    fd = a.data
    latest = {}
    for key in ("net_income", "total_equity", "total_debt_used", "cash", "short_term_investments", "ebitda",
                "revenue", "free_cash_flow"):
        s = fd.series(key).dropna()
        latest[key] = {"value": float(s.iloc[-1]), "year": int(s.index[-1])} if len(s) else None
    return latest


def _respond(a: Analysis, fmt: str, filename: str, extra: dict, cache: str) -> Response:
    headers = {"Cache-Control": cache}
    if fmt == "xlsx":
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.xlsx"
            to_excel(a, path)
            body = path.read_bytes()
        headers["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
        return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers=headers)
    if fmt == "html":
        headers["Content-Disposition"] = f'attachment; filename="{filename}.html"'
        return HTMLResponse(render_html(a), headers=headers)
    payload = to_dict(a)
    payload.update(extra)
    return JSONResponse(clean(payload), headers=headers)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:60] or "analysis"


# ------------------------------------------------------------------ routes

@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "time": dt.datetime.now(dt.timezone.utc).isoformat()}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=60)):
    results = providers.search(q.strip(), 8)
    return JSONResponse({"results": results}, headers={"Cache-Control": "public, s-maxage=86400, stale-while-revalidate=604800"})


@app.get("/api/quote/{symbol}")
def quote(symbol: str):
    data = providers.yahoo.quote(_symbol(symbol))
    return JSONResponse(clean(data), headers={"Cache-Control": "public, s-maxage=15, stale-while-revalidate=30"})


@app.get("/api/company/{symbol}")
def company(symbol: str, source: str = Query("auto"), years: int = Query(5, ge=2, le=15),
            basis: str = Query("average", pattern="^(average|ending)$"),
            format: str = Query("json", pattern="^(json|xlsx|html)$")):
    sym = _symbol(symbol)
    data = providers.fetch_company(sym, source.lower(), years)
    if not (data.sector or data.exchange):  # SEC data carries no market profile; enrich best-effort
        try:
            prof = providers.yahoo.profile_for(sym)
            data.exchange, data.sector, data.industry = prof.get("exchange"), prof.get("sector"), prof.get("industry")
            data.name = prof.get("name") or data.name  # SEC names are often upper-case
        except ProviderError:
            pass
    a = analyze_tables(data.tables, data.name, data.overrides, basis=basis, notes=data.notes)
    if data.sector == "Financial Services":
        a.data.warn("Financial-sector company: liquidity, turnover and debt ratios are designed for operating "
                    "companies and read differently for banks and insurers (deposits and float are funding, not debt).")
    extra = {
        "company_info": {
            "symbol": data.symbol, "name": data.name, "source": data.source, "source_url": data.source_url,
            "currency": data.currency, "exchange": data.exchange, "sector": data.sector, "industry": data.industry,
            "shares_outstanding": data.shares_outstanding,
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        "valuation_inputs": _valuation_inputs(a),
    }
    return _respond(a, format, _slug(f"{data.symbol}_analysis"), extra,
                    "public, s-maxage=1800, stale-while-revalidate=86400")


@app.post("/api/analyze")
async def analyze_upload(files: list[UploadFile] = File(...), company: str = Form(""),
                         basis: str = Form("average"), format: str = Form("json")):
    if basis not in {"average", "ending"} or format not in {"json", "xlsx", "html"}:
        raise ValueError("basis must be average|ending and format json|xlsx|html.")
    if not files or len(files) > MAX_FILES:
        raise ValueError(f"Upload between 1 and {MAX_FILES} files.")
    with tempfile.TemporaryDirectory() as tmp:
        paths, total = [], 0
        for i, f in enumerate(files):
            name = Path(f.filename or f"file{i}").name
            ext = Path(name).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise ValueError(f"'{name}' is not a supported type. Use CSV, Excel (.xlsx/.xls) or PDF.")
            body = await f.read()
            total += len(body)
            if total > MAX_UPLOAD_BYTES:
                raise ValueError("Uploads are limited to 4 MB in total.")
            path = Path(tmp) / f"{i:02d}_{re.sub(r'[^A-Za-z0-9._-]+', '_', name)}"
            path.write_bytes(body)
            paths.append(path)
        a = analyze(paths, company=company.strip() or None, basis=basis)
        extra = {"company_info": {"symbol": None, "name": a.data.company, "source": "Uploaded statements",
                                  "source_url": None, "currency": None,
                                  "files": [Path(f.filename or "").name for f in files],
                                  "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()},
                 "valuation_inputs": None}
        return _respond(a, format, _slug(f"{a.data.company}_analysis"), extra, "no-store")


# Local development: serve the web UI too. On Vercel, ./public is served by the CDN.
if not os.environ.get("VERCEL"):
    public = ROOT / "public"
    if public.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=public, html=True), name="ui")
