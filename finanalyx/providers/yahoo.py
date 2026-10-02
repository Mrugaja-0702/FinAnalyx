"""Yahoo Finance: global coverage (US, NSE/BSE, LSE, ...), ~4-5 years of annual statements,
live quotes and symbol search. Uses the public JSON endpoints directly (no API key)."""
from __future__ import annotations

import time

from .base import CompanyData, ProviderError, TTLCache, build_tables, get_json

SOURCE = "Yahoo Finance"

# item key -> Yahoo fundamentals-timeseries fields, in order of preference.
FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("TotalRevenue", "OperatingRevenue"),
    "cogs": ("CostOfRevenue", "ReconciledCostOfRevenue"),
    "gross_profit": ("GrossProfit",),
    "operating_expenses": ("OperatingExpense",),
    "depreciation_amortization": ("ReconciledDepreciation", "DepreciationAndAmortizationInIncomeStatement",
                                  "DepreciationAmortizationDepletion"),
    "ebit": ("OperatingIncome", "TotalOperatingIncomeAsReported"),
    "interest_expense": ("InterestExpense", "InterestExpenseNonOperating"),
    "pretax_income": ("PretaxIncome",),
    "tax_expense": ("TaxProvision",),
    "net_income": ("NetIncomeCommonStockholders", "NetIncome"),
    "shares_outstanding": ("DilutedAverageShares", "OrdinarySharesNumber"),
    "cash": ("CashAndCashEquivalents",),
    "short_term_investments": ("OtherShortTermInvestments",),
    "accounts_receivable": ("AccountsReceivable", "Receivables"),
    "inventory": ("Inventory",),
    "total_current_assets": ("CurrentAssets",),
    "ppe": ("NetPPE",),
    "total_assets": ("TotalAssets",),
    "accounts_payable": ("AccountsPayable", "Payables"),
    "short_term_debt": ("CurrentDebt",),
    "long_term_debt": ("LongTermDebt",),
    "total_current_liabilities": ("CurrentLiabilities",),
    "total_liabilities": ("TotalLiabilitiesNetMinorityInterest",),
    "total_equity": ("StockholdersEquity", "CommonStockEquity"),
    "minority_interest": ("MinorityInterest",),
    "retained_earnings": ("RetainedEarnings",),
    "operating_cash_flow": ("OperatingCashFlow",),
    "capex": ("CapitalExpenditure",),
    "investing_cash_flow": ("InvestingCashFlow",),
    "financing_cash_flow": ("FinancingCashFlow",),
    "dividends_paid": ("CashDividendsPaid", "CommonStockDividendPaid"),
}
SHARE_FIELDS = ("OrdinarySharesNumber", "ShareIssued", "DilutedAverageShares")
DEBT_FIELDS = ("TotalDebt", "CapitalLeaseObligations")

_fundamentals_cache = TTLCache(ttl=3600)
_quote_cache = TTLCache(ttl=15, max_items=256)
_search_cache = TTLCache(ttl=3600, max_items=512)
_profile_cache = TTLCache(ttl=86400, max_items=512)


def _fetch_timeseries(symbol: str) -> dict:
    types = [f"annual{f}" for fields in FIELDS.values() for f in fields] + [f"annual{f}" for f in SHARE_FIELDS + DEBT_FIELDS]
    data = get_json(
        f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}",
        params={"type": ",".join(dict.fromkeys(types)), "period1": 493590046, "period2": int(time.time()) + 86400,
                "merge": "false", "padTimeSeries": "false"},
        what="Yahoo Finance fundamentals",
    )
    out: dict[str, dict[int, tuple[float, str, str]]] = {}
    for result in (data.get("timeseries") or {}).get("result") or []:
        field = (result.get("meta", {}).get("type") or [None])[0]
        if not field or field not in result:
            continue
        series = {}
        for point in result[field] or []:
            if not point or "reportedValue" not in point:
                continue
            raw = point["reportedValue"].get("raw")
            if raw is None:
                continue
            series[int(point["asOfDate"][:4])] = (float(raw), point.get("currencyCode") or "", point["asOfDate"])
        if series:
            out[field[len("annual"):]] = series
    return out


def fetch_company(symbol: str, years: int = 5) -> CompanyData:
    symbol = symbol.upper()
    raw = _fundamentals_cache.get_or_set(symbol, lambda: _fetch_timeseries(symbol))
    if not raw:
        raise ProviderError(f"Yahoo Finance has no annual financial statements for '{symbol}'. "
                            "Check the symbol (Indian stocks need a suffix, e.g. TCS.NS or 500325.BO).", 404)
    values: dict[str, dict[int, float]] = {}
    labels: dict[str, str] = {}
    currencies: set[str] = set()
    for key, fields in FIELDS.items():
        merged: dict[int, float] = {}
        used = []
        for f in fields:
            for year, (val, cur, _) in raw.get(f, {}).items():
                if year not in merged:
                    merged[year] = val
                    currencies.add(cur)
                    if f not in used:
                        used.append(f)
        if merged:
            values[key] = merged
            labels[key] = "Yahoo: " + " / ".join(used)
    # Where borrowings are not itemised, use Total Debt less lease obligations (leases are
    # excluded from debt throughout). For debt-free companies this correctly yields zero.
    total, leases = raw.get("TotalDebt", {}), raw.get("CapitalLeaseObligations", {})
    borrowings = {y: val - (leases.get(y, (0.0, "", ""))[0]) for y, (val, _, _) in total.items()
                  if y not in values.get("short_term_debt", {}) and y not in values.get("long_term_debt", {})}
    if borrowings:
        values["total_debt"] = {y: max(v, 0.0) for y, v in borrowings.items()}
        labels["total_debt"] = "Yahoo: TotalDebt - CapitalLeaseObligations"
    all_years = sorted({y for v in values.values() for y in v})[-years:]
    values = {k: {y: v for y, v in s.items() if y in all_years} for k, s in values.items()}
    currencies.discard("")
    currency = sorted(currencies)[0] if len(currencies) == 1 else (sorted(currencies)[0] if currencies else None)
    shares = None
    for f in SHARE_FIELDS:
        if raw.get(f):
            shares = raw[f][max(raw[f])][0]
            break
    tables, overrides = build_tables(SOURCE, values, labels, currency)
    period_ends: dict[int, str] = {}
    for f in ("TotalRevenue", "NetIncome", "TotalAssets"):
        for year, (_, _, date) in raw.get(f, {}).items():
            if year in all_years:
                period_ends.setdefault(year, date)
    profile = profile_for(symbol)
    notes = []
    if len(currencies) > 1:
        notes.append("Yahoo reported mixed currencies (" + ", ".join(sorted(currencies)) + ") - check the figures.")
    return CompanyData(
        symbol=symbol, name=profile.get("name") or symbol, source=SOURCE,
        source_url=f"https://finance.yahoo.com/quote/{symbol}/financials", currency=currency,
        tables=tables, overrides=overrides, shares_outstanding=shares, exchange=profile.get("exchange"),
        sector=profile.get("sector"), industry=profile.get("industry"), notes=notes, period_ends=period_ends,
    )


def search(query: str, limit: int = 8) -> list[dict]:
    def run() -> list[dict]:
        data = get_json("https://query2.finance.yahoo.com/v1/finance/search",
                        params={"q": query, "quotesCount": limit, "newsCount": 0, "listsCount": 0,
                                "enableFuzzyQuery": "true"}, what="symbol search")
        out = []
        for q in data.get("quotes") or []:
            if q.get("quoteType") not in {"EQUITY"} or not q.get("symbol"):
                continue
            out.append({"symbol": q["symbol"], "name": q.get("longname") or q.get("shortname") or q["symbol"],
                        "exchange": q.get("exchDisp") or q.get("exchange"), "sector": q.get("sectorDisp"),
                        "industry": q.get("industryDisp")})
            _profile_cache.get_or_set(q["symbol"].upper(), lambda q=q: {
                "name": q.get("longname") or q.get("shortname"), "exchange": q.get("exchDisp"),
                "sector": q.get("sectorDisp"), "industry": q.get("industryDisp")})
        return out
    return _search_cache.get_or_set(query.lower(), run)


def profile_for(symbol: str) -> dict:
    def run() -> dict:
        try:
            for hit in search(symbol, 5):
                if hit["symbol"].upper() == symbol.upper():
                    return {"name": hit["name"], "exchange": hit["exchange"], "sector": hit["sector"],
                            "industry": hit["industry"]}
        except ProviderError:
            pass
        return {}
    return _profile_cache.get_or_set(symbol.upper(), run)


def quote(symbol: str) -> dict:
    """Latest price plus today's intraday path (5-minute bars) for the live ticker strip."""
    def run() -> dict:
        data = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                        params={"range": "1d", "interval": "5m", "includePrePost": "false"}, what="quote")
        result = ((data.get("chart") or {}).get("result") or [None])[0]
        if not result:
            raise ProviderError(f"No quote available for '{symbol}'.", 404)
        meta = result.get("meta", {})
        closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        stamps = result.get("timestamp") or []
        intraday = [[t, c] for t, c in zip(stamps, closes) if c is not None]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        currency = meta.get("currency")
        divisor = 1.0
        if currency in {"GBp", "ZAc", "ILA"}:  # quoted in minor units
            divisor, currency = 100.0, {"GBp": "GBP", "ZAc": "ZAR", "ILA": "ILS"}[currency]
        return {
            "symbol": meta.get("symbol", symbol), "price": price, "previous_close": prev,
            "change": (price - prev) if price is not None and prev else None,
            "change_pct": ((price / prev - 1) * 100) if price is not None and prev else None,
            "currency": currency, "price_divisor": divisor, "exchange": meta.get("fullExchangeName"),
            "name": meta.get("longName") or meta.get("shortName"),
            "market_time": meta.get("regularMarketTime"), "timezone": meta.get("exchangeTimezoneName"),
            "day_high": meta.get("regularMarketDayHigh"), "day_low": meta.get("regularMarketDayLow"),
            "week52_high": meta.get("fiftyTwoWeekHigh"), "week52_low": meta.get("fiftyTwoWeekLow"),
            "intraday": intraday,
        }
    return _quote_cache.get_or_set(symbol.upper(), run)


_history_cache = TTLCache(ttl=900, max_items=128)


def history(symbol: str, range_: str = "5y", interval: str = "1d") -> list[tuple[int, float, float]]:
    """[(unix seconds, close, adjusted close), ...].

    ``close`` is split-adjusted only (what the stock traded at; used for P/E history);
    ``adjusted close`` also reinvests dividends (used for total returns, beta, volatility).
    """
    def run() -> list[tuple[int, float, float]]:
        data = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                        params={"range": range_, "interval": interval, "events": "div,splits"},
                        what="price history")
        result = ((data.get("chart") or {}).get("result") or [None])[0]
        if not result or not result.get("timestamp"):
            raise ProviderError(f"No price history for '{symbol}'.", 404)
        ind = result.get("indicators") or {}
        closes = (ind.get("quote") or [{}])[0].get("close") or []
        adj = (ind.get("adjclose") or [{}])[0].get("adjclose") or closes
        currency = (result.get("meta") or {}).get("currency")
        scale = 1.0
        if currency in _MINOR_UNITS:  # e.g. London prices in pence: convert to pounds
            currency, scale = _MINOR_UNITS[currency], 0.01
        _currencies[symbol.upper()] = currency
        return [(int(t), float(c) * scale, float(a) * scale) for t, c, a in zip(result["timestamp"], closes, adj)
                if c is not None and a is not None]
    return _history_cache.get_or_set((symbol.upper(), range_, interval), run)


_MINOR_UNITS = {"GBp": "GBP", "ZAc": "ZAR", "ILA": "ILS"}
_currencies: dict[str, str | None] = {}


def price_currency(symbol: str) -> str | None:
    """Currency of the prices returned by ``history`` (after minor-unit conversion)."""
    if symbol.upper() not in _currencies:
        history(symbol)
    return _currencies.get(symbol.upper())


def fx_history(base: str, quote: str) -> list[tuple[int, float, float]]:
    """Daily rate: units of ``quote`` currency per 1 unit of ``base`` (e.g. USD -> INR ~ 83)."""
    return history(f"{base.upper()}{quote.upper()}=X")


# Broad-market benchmark used for beta and relative strength, by listing suffix.
BENCHMARKS = {".NS": ("^NSEI", "NIFTY 50"), ".BO": ("^BSESN", "BSE SENSEX"), ".L": ("^FTSE", "FTSE 100"),
              ".TO": ("^GSPTSE", "S&P/TSX"), ".HK": ("^HSI", "Hang Seng"), ".T": ("^N225", "Nikkei 225"),
              ".AX": ("^AXJO", "ASX 200"), ".DE": ("^GDAXI", "DAX"), ".PA": ("^FCHI", "CAC 40"),
              ".SI": ("^STI", "Straits Times"), ".KS": ("^KS11", "KOSPI")}


def benchmark_for(symbol: str) -> tuple[str, str]:
    for suffix, bench in BENCHMARKS.items():
        if symbol.upper().endswith(suffix):
            return bench
    return "^GSPC", "S&P 500"


def risk_free_rate(currency: str | None) -> tuple[float, str]:
    """Annual risk-free rate (decimal) and its source. Live 10-year US Treasury yield for USD."""
    if (currency or "USD").upper() == "USD":
        try:
            pts = history("^TNX", "5d", "1d")
            if pts:
                return pts[-1][1] / 100, "US 10-year Treasury yield (live)"
        except ProviderError:
            pass
        return 0.043, "US 10-year Treasury (fallback estimate)"
    defaults = {"INR": (0.068, "India 10-year G-Sec (estimate)"), "GBP": (0.045, "UK 10-year gilt (estimate)"),
                "EUR": (0.027, "German 10-year Bund (estimate)"), "JPY": (0.012, "Japan 10-year JGB (estimate)"),
                "CAD": (0.034, "Canada 10-year (estimate)"), "AUD": (0.043, "Australia 10-year (estimate)"),
                "HKD": (0.04, "Hong Kong long bond (estimate)")}
    return defaults.get((currency or "").upper(), (0.04, "Generic long-bond yield (estimate)"))
