"""Equity research layer: combines statements with market data into scores, valuation and stock drivers."""
from __future__ import annotations

import logging
from typing import Callable

from .analyzer import Analysis
from .drivers import analyze_drivers
from .market import PriceData, series_payload, stats
from .scores import compute_scores
from .valuation import attribution, build_model

log = logging.getLogger(__name__)

HistoryFn = Callable[[str], list]


def research(a: Analysis, *, symbol: str | None = None, currency: str | None = None,
             shares_now: float | None = None, period_ends: dict[int, str] | None = None,
             history: HistoryFn | None = None, benchmark: tuple[str, str] | None = None,
             rf: tuple[float, str] | None = None,
             price_currency: Callable[[str], str | None] | None = None,
             fx_history: Callable[[str, str], list] | None = None) -> dict:
    """Build the research payload.

    ``history`` fetches [(ts, close, adj close)] for a symbol; when it is missing or fails
    (uploads, offline, rate limits) everything that needs prices is skipped and noted.
    When the share trades in a different currency from the one the accounts are reported in
    (e.g. Infosys: NSE price in INR, accounts in USD), prices are converted at the prevailing
    exchange rate before any valuation multiple is computed.
    """
    notes: list[str] = []
    market = series = None
    px = None
    if symbol and history:
        try:
            px = PriceData.from_points(history(symbol))
            bench_px = None
            if benchmark:
                try:
                    bench_px = PriceData.from_points(history(benchmark[0]))
                except Exception as exc:  # noqa: BLE001 - benchmark is optional
                    notes.append(f"Benchmark {benchmark[1]} unavailable ({exc}); beta not computed.")
            rate, _ = rf or (0.04, "")
            market = stats(px, bench_px, rate)
            market["benchmark"] = benchmark[1] if benchmark and bench_px is not None else None
            market["currency"] = price_currency(symbol) if price_currency else currency
            series = series_payload(px, bench_px)
        except Exception as exc:  # noqa: BLE001
            log.warning("market data failed for %s: %s", symbol, exc)
            notes.append(f"Price history unavailable ({exc}); valuation, momentum and risk factors skipped.")
            px = None

    # Prices in the reporting currency, for valuation.
    price = market["last_price"] if market else None
    price_on = px.price_on if px is not None else None
    fx_info = None
    pcur = (market or {}).get("currency")
    if price is not None and pcur and currency and pcur.upper() != currency.upper():
        try:
            if not fx_history:
                raise ValueError("no FX source")
            fx = PriceData.from_points(fx_history(currency, pcur))  # pcur per 1 unit of reporting currency
            rate = float(fx.close.iloc[-1])
            price = price / rate
            price_on = (lambda d, _px=px, _fx=fx: (lambda p, r: p / r if p is not None and r else None)(
                _px.price_on(d), _fx.price_on(d)))
            fx_info = {"base": currency, "quote": pcur, "rate": rate, "as_of": fx.close.index[-1].date().isoformat()}
            notes.append(f"Shares trade in {pcur} but the accounts are in {currency}: prices converted at "
                         f"{rate:,.4g} {pcur}/{currency} for valuation multiples.")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Shares trade in {pcur} but accounts are in {currency}, and no exchange rate was available "
                         f"({exc}); valuation multiples skipped.")
            price, price_on = None, None

    fd = a.data
    latest_shares = fd.series("shares_outstanding").dropna()
    shares = shares_now or (float(latest_shares.iloc[-1]) if len(latest_shares) else None)
    beta = ((market or {}).get("beta") or {}).get("beta")
    rate, rate_src = rf or (0.04, "assumed 4% (no market data)")

    val = build_model(fd, a.ratios, price=price, shares=shares, beta=beta, rf=rate, rf_source=rate_src,
                      currency=currency)
    val["fx"] = fx_info
    val["attribution"] = attribution(fd, period_ends, price_on) if price_on and period_ends else None

    scores = compute_scores(fd, market_cap=val.get("market_cap"))
    drivers = analyze_drivers(a, scores, market, val if price else None)
    return {"market": market, "price_series": series, "valuation_model": val, "scores": scores,
            "drivers": drivers, "research_notes": notes}
