"""Live data providers and source selection."""
from __future__ import annotations

from . import sec, yahoo
from .base import CompanyData, ProviderError

SOURCES = ("auto", "sec", "yahoo")


def fetch_company(symbol: str, source: str = "auto", years: int = 5) -> CompanyData:
    """Fetch statements for a ticker.

    ``auto`` prefers SEC EDGAR for US-listed companies (official filings, longer
    history) and falls back to Yahoo Finance for everything else or on failure.
    """
    if source not in SOURCES:
        raise ProviderError(f"Unknown source '{source}'. Use one of: {', '.join(SOURCES)}.", 400)
    if source == "sec":
        return sec.fetch_company(symbol, years)
    if source == "yahoo":
        return yahoo.fetch_company(symbol, years)
    fallback_note = None
    if "." not in symbol:
        try:
            if sec.lookup(symbol):
                data = sec.fetch_company(symbol, years)
                if len({y for t in data.tables for y in t.years}) >= 2:
                    return data
                fallback_note = "SEC EDGAR had fewer than two years of usable data"
        except ProviderError as exc:
            fallback_note = f"SEC EDGAR unavailable ({exc})"
    data = yahoo.fetch_company(symbol, years)
    if fallback_note:
        data.notes.append(fallback_note + "; Yahoo Finance data used instead.")
    return data


def search(query: str, limit: int = 8) -> list[dict]:
    """Global symbol search (Yahoo), falling back to the SEC directory if Yahoo is unavailable."""
    try:
        results = yahoo.search(query, limit)
        if results:
            return results
    except ProviderError:
        pass
    return sec.search(query, limit)


__all__ = ["CompanyData", "ProviderError", "fetch_company", "search", "SOURCES", "sec", "yahoo"]
