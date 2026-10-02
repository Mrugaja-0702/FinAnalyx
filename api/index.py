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
from urllib.parse import parse_qsl, urlencode
from urllib.parse import quote as url_quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, Form, Query, Request, UploadFile  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from finanalyx import __version__, providers  # noqa: E402
from finanalyx.analyzer import Analysis, analyze, analyze_tables  # noqa: E402
from finanalyx.export import clean, to_dict, to_excel  # noqa: E402
from finanalyx.ingest import SUPPORTED_EXTENSIONS, IngestError  # noqa: E402
from finanalyx.providers import ProviderError  # noqa: E402
from finanalyx.report_html import render_html  # noqa: E402
from finanalyx.research import research  # noqa: E402

log = logging.getLogger("finanalyx.api")

MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # Vercel caps request bodies at 4.5 MB
MAX_FILES = 12
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-^=&]{1,20}$")

app = FastAPI(title="FinAnalyx API", version=__version__,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)


class RestoreRewrittenPath:
    """Undo Vercel's rewrite so FastAPI routes on the URL the browser requested.

    vercel.json rewrites /api/<rest> to /api/index?__path=<rest>; the function would otherwise
    see "/api/index" for every request. Requests without __path (local runs) pass through untouched.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and b"__path=" in scope.get("query_string", b""):
            params = parse_qsl(scope["query_string"].decode("latin-1"), keep_blank_values=True)
            original = next((v for k, v in params if k == "__path"), "")
            rest = [(k, v) for k, v in params if k != "__path"]
            path = "/api/" + original.lstrip("/")
            scope = dict(scope, path=path, raw_path=url_quote(path).encode(),
                         query_string=urlencode(rest).encode("latin-1"))
        await self.app(scope, receive, send)


app.add_middleware(RestoreRewrittenPath)


# ------------------------------------------------------------------ errors

def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status, headers={"Cache-Control": "no-store"})


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return _error(f"No API route for '{request.url.path}'.", 404)
    return _error(str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    problems = "; ".join(f"{'.'.join(str(x) for x in e.get('loc', [])[1:])}: {e.get('msg')}" for e in exc.errors())
    return _error(f"Invalid request - {problems}", 422)


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
        "period_ends": {str(y): d for y, d in data.period_ends.items()},
    }
    if format == "json":
        extra.update(research(
            a, symbol=data.symbol, currency=data.currency, shares_now=data.shares_outstanding,
            period_ends=data.period_ends, history=providers.yahoo.history,
            benchmark=providers.yahoo.benchmark_for(data.symbol), rf=providers.yahoo.risk_free_rate(data.currency),
            price_currency=providers.yahoo.price_currency, fx_history=providers.yahoo.fx_history))
    return _respond(a, format, _slug(f"{data.symbol}_analysis"), extra,
                    "public, s-maxage=900, stale-while-revalidate=86400")


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
        if format == "json":
            extra.update(research(a))
        return _respond(a, format, _slug(f"{a.data.company}_analysis"), extra, "no-store")


# Local development: serve the web UI too. On Vercel, ./public is served by the CDN.
if not os.environ.get("VERCEL"):
    public = ROOT / "public"
    if public.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=public, html=True), name="ui")
