"""Shared plumbing for live data providers: HTTP, caching, errors, table building."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from ..ingest import ParsedTable
from ..schema import BS, CF, IS, ITEMS

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# The SEC asks automated clients to identify themselves with a contact address.
SEC_UA = os.environ.get("SEC_USER_AGENT", "FinAnalyx contact@finanalyx.app")


class ProviderError(Exception):
    """A provider could not deliver data. ``status`` maps onto an HTTP status code."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class CompanyData:
    """Everything a provider returns: statements as tables plus market metadata."""
    symbol: str
    name: str
    source: str
    source_url: str
    currency: str | None
    tables: list[ParsedTable]
    overrides: dict[str, str]  # raw label -> item key, so the mapping audit shows real concept names
    shares_outstanding: float | None = None
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    notes: list[str] = field(default_factory=list)
    period_ends: dict[int, str] = field(default_factory=dict)  # fiscal year -> ISO period-end date


class TTLCache:
    """Small thread-safe cache; survives between requests on a warm serverless instance."""

    def __init__(self, ttl: float, max_items: int = 128):
        self.ttl, self.max_items = ttl, max_items
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: Any, fn: Callable[[], Any]) -> Any:
        now = time.time()
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > now:
                return hit[1]
        value = fn()
        with self._lock:
            if len(self._data) >= self.max_items:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (now + self.ttl, value)
        return value


_client: httpx.Client | None = None


def http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0), follow_redirects=True,
                               headers={"Accept-Encoding": "gzip, deflate"})
    return _client


def get_json(url: str, *, params: dict | None = None, user_agent: str = BROWSER_UA, what: str = "data",
             timeout: float = 12.0) -> Any:
    try:
        r = http().get(url, params=params, headers={"User-Agent": user_agent, "Accept": "application/json"},
                       timeout=httpx.Timeout(timeout, connect=5.0))
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not reach the {what} service ({exc.__class__.__name__}). Try again shortly.",
                            504 if isinstance(exc, httpx.TimeoutException) else 502) from exc
    if r.status_code == 404:
        raise ProviderError(f"No {what} found.", 404)
    if r.status_code == 429:
        raise ProviderError(f"The {what} service is rate-limiting requests. Try again in a minute.", 503)
    if r.status_code >= 400:
        raise ProviderError(f"The {what} service returned HTTP {r.status_code}.")
    try:
        return r.json()
    except ValueError as exc:
        raise ProviderError(f"The {what} service returned an unexpected response.") from exc


def build_tables(source: str, values: dict[str, dict[int, float]], labels: dict[str, str],
                 units: str | None) -> tuple[list[ParsedTable], dict[str, str]]:
    """Turn {item key: {year: value}} into one ParsedTable per statement.

    ``labels`` gives the provider's own concept name for each key, which becomes the
    row label (and a mapping override), so the audit trail shows e.g. "us-gaap:Revenues".
    """
    tables, overrides = [], {}
    for statement, title in ((IS, "Income statement"), (BS, "Balance sheet"), (CF, "Cash flow")):
        rows = []
        for key, item in ITEMS.items():
            if item.statement != statement or not values.get(key):
                continue
            label = labels.get(key, item.label)
            overrides[label] = key
            rows.append((label, dict(values[key]), ""))
        years = sorted({y for _, v, _ in rows for y in v})
        if rows:
            tables.append(ParsedTable(name=f"{source} {title.lower()}", source=source, statement=statement,
                                      years=years, rows=rows, units=units))
    if not tables:
        raise ProviderError("The data source returned no financial statement data for this company.", 422)
    return tables, overrides
