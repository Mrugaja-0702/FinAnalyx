"""Price-based analytics: returns, risk, beta, trend and momentum.

Inputs are daily (timestamp, close, adjusted close) points. Total-return measures
(returns, volatility, beta, Sharpe, drawdown) use the dividend-adjusted close; the
trend indicators (moving averages, RSI, 52-week range) use the traded close.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class PriceData:
    close: pd.Series  # split-adjusted traded price, indexed by date
    adj: pd.Series    # dividend-adjusted total-return price

    @classmethod
    def from_points(cls, points: list[tuple[int, float, float]]) -> "PriceData":
        idx = pd.to_datetime([p[0] for p in points], unit="s").normalize()
        close = pd.Series([p[1] for p in points], index=idx, dtype=float)
        adj = pd.Series([p[2] for p in points], index=idx, dtype=float)
        close = close[~close.index.duplicated(keep="last")]
        adj = adj[~adj.index.duplicated(keep="last")]
        return cls(close.sort_index(), adj.sort_index())

    def price_on(self, date: str | pd.Timestamp, tolerance_days: int = 10) -> float | None:
        """Last traded close on or before ``date`` (None if the gap is larger than the tolerance)."""
        d = pd.Timestamp(date)
        s = self.close[self.close.index <= d]
        if s.empty or (d - s.index[-1]).days > tolerance_days:
            return None
        return float(s.iloc[-1])


def _ret_since(s: pd.Series, offset: pd.DateOffset) -> float | None:
    start = s.index[-1] - offset
    if s.index[0] > start + pd.Timedelta(days=20):
        return None
    base = s[s.index <= start]
    if base.empty:
        return None
    return float(s.iloc[-1] / base.iloc[-1] - 1)


def _cagr_since(s: pd.Series, years: int) -> float | None:
    r = _ret_since(s, pd.DateOffset(years=years))
    return None if r is None or r <= -1 else (1 + r) ** (1 / years) - 1


def rsi(close: pd.Series, period: int = 14) -> float | None:
    """Wilder's Relative Strength Index."""
    if len(close) <= period:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    if loss.iloc[-1] == 0:
        return 100.0
    rs = gain.iloc[-1] / loss.iloc[-1]
    return float(100 - 100 / (1 + rs))


def max_drawdown(s: pd.Series) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    """Largest peak-to-trough fall: (drawdown as negative decimal, peak date, trough date)."""
    if s.empty:
        return 0.0, None, None
    peak = s.cummax()
    dd = s / peak - 1
    trough = dd.idxmin()
    peak_date = s[:trough].idxmax()
    return float(dd.min()), peak_date, trough


def beta(stock: pd.Series, bench: pd.Series) -> dict | None:
    """Beta, correlation and R-squared from weekly total returns over the common history."""
    w = pd.concat([stock.resample("W-FRI").last(), bench.resample("W-FRI").last()], axis=1).dropna()
    r = w.pct_change().dropna()
    if len(r) < 26:
        return None
    var = r.iloc[:, 1].var()
    if not var:
        return None
    b = r.iloc[:, 0].cov(r.iloc[:, 1]) / var
    corr = r.iloc[:, 0].corr(r.iloc[:, 1])
    return {"beta": float(b), "correlation": float(corr), "r_squared": float(corr ** 2), "weeks": int(len(r))}


def _last_cross(ma_fast: pd.Series, ma_slow: pd.Series) -> tuple[str | None, str | None]:
    diff = (ma_fast - ma_slow).dropna()
    if len(diff) < 2:
        return None, None
    sign = np.sign(diff)
    changes = sign[sign.diff().fillna(0) != 0]
    if changes.empty:
        return None, None
    when = changes.index[-1]
    return ("golden" if changes.iloc[-1] > 0 else "death"), when.date().isoformat()


def stats(px: PriceData, bench: PriceData | None, rf: float) -> dict:
    close, adj = px.close, px.adj
    last = float(close.iloc[-1])
    periods = {"1M": pd.DateOffset(months=1), "3M": pd.DateOffset(months=3), "6M": pd.DateOffset(months=6),
               "1Y": pd.DateOffset(years=1)}
    returns = {k: _ret_since(adj, off) for k, off in periods.items()}
    ytd_base = adj[adj.index < pd.Timestamp(adj.index[-1].year, 1, 1)]
    returns["YTD"] = float(adj.iloc[-1] / ytd_base.iloc[-1] - 1) if not ytd_base.empty else None
    returns["3Y (annual)"] = _cagr_since(adj, 3)
    returns["5Y (annual)"] = _cagr_since(adj, 5)
    bench_returns = None
    if bench is not None and not bench.adj.empty:
        bench_returns = {k: _ret_since(bench.adj, off) for k, off in periods.items()}
        b_ytd = bench.adj[bench.adj.index < pd.Timestamp(bench.adj.index[-1].year, 1, 1)]
        bench_returns["YTD"] = float(bench.adj.iloc[-1] / b_ytd.iloc[-1] - 1) if not b_ytd.empty else None
        bench_returns["3Y (annual)"] = _cagr_since(bench.adj, 3)
        bench_returns["5Y (annual)"] = _cagr_since(bench.adj, 5)

    daily = np.log(adj).diff().dropna()
    last_year = daily[daily.index > daily.index[-1] - pd.DateOffset(years=1)]
    vol_1y = float(last_year.std() * math.sqrt(TRADING_DAYS)) if len(last_year) > 20 else None
    years_span = max((adj.index[-1] - adj.index[0]).days / 365.25, 1e-9)
    ann_return = float((adj.iloc[-1] / adj.iloc[0]) ** (1 / years_span) - 1) if years_span >= 0.5 else None
    vol_full = float(daily.std() * math.sqrt(TRADING_DAYS)) if len(daily) > 20 else None
    downside = daily[daily < 0]
    down_vol = float(downside.std() * math.sqrt(TRADING_DAYS)) if len(downside) > 20 else None
    sharpe = (ann_return - rf) / vol_full if ann_return is not None and vol_full else None
    sortino = (ann_return - rf) / down_vol if ann_return is not None and down_vol else None
    mdd, peak_d, trough_d = max_drawdown(adj)

    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    cross, cross_date = _last_cross(ma50, ma200)
    year = close[close.index > close.index[-1] - pd.DateOffset(years=1)]
    hi, lo = float(year.max()), float(year.min())

    b = beta(adj, bench.adj) if bench is not None else None
    rel_1y = None
    if returns.get("1Y") is not None and bench_returns and bench_returns.get("1Y") is not None:
        rel_1y = returns["1Y"] - bench_returns["1Y"]
    # 12-1 momentum (the academic momentum factor skips the most recent month)
    mom_12_1 = None
    a12, a1 = _ret_since(adj, pd.DateOffset(years=1)), _ret_since(adj, pd.DateOffset(months=1))
    if a12 is not None and a1 is not None:
        mom_12_1 = (1 + a12) / (1 + a1) - 1

    def f(x):
        return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else x

    return {
        "last_price": last, "as_of": close.index[-1].date().isoformat(),
        "returns": {k: f(v) for k, v in returns.items()},
        "benchmark_returns": {k: f(v) for k, v in bench_returns.items()} if bench_returns else None,
        "relative_1y": f(rel_1y), "momentum_12_1": f(mom_12_1),
        "volatility_1y": f(vol_1y), "volatility": f(vol_full), "annual_return": f(ann_return),
        "sharpe": f(sharpe), "sortino": f(sortino), "risk_free": rf,
        "max_drawdown": mdd, "max_drawdown_peak": peak_d.date().isoformat() if peak_d is not None else None,
        "max_drawdown_trough": trough_d.date().isoformat() if trough_d is not None else None,
        "drawdown_from_high": float(last / hi - 1) if hi else None,
        "high_52w": hi, "low_52w": lo,
        "ma50": f(float(ma50.iloc[-1])) if not math.isnan(ma50.iloc[-1]) else None,
        "ma200": f(float(ma200.iloc[-1])) if not math.isnan(ma200.iloc[-1]) else None,
        "last_cross": cross, "last_cross_date": cross_date,
        "rsi14": f(rsi(close)),
        "beta": b,
        "history_years": round(years_span, 1),
    }


def series_payload(px: PriceData, bench: PriceData | None) -> dict:
    """Compact arrays for charting: [ms timestamp, close] (and benchmark adjusted close)."""
    def pts(s: pd.Series) -> list[list]:
        return [[int(ts.value // 1_000_000), round(float(v), 4)] for ts, v in s.items()]

    out = {"close": pts(px.close), "adj": pts(px.adj)}
    if bench is not None:
        out["benchmark"] = pts(bench.adj)
    return out
