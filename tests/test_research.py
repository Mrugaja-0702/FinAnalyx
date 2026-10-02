"""Tests for the equity research layer: market stats, scorecards, valuation and stock drivers."""
import math
from pathlib import Path

import numpy as np
import pytest

from finanalyx import analyze
from finanalyx.market import PriceData, beta, max_drawdown, rsi, stats
from finanalyx.research import research
from finanalyx.scores import altman, beneish, piotroski
from finanalyx.valuation import attribution, dcf, reverse_dcf, split_adjusted_shares

ROOT = Path(__file__).resolve().parents[1]
DAY = 86_400


def synthetic(n=600, drift=0.0005, beta_=1.5, seed=1):
    """Benchmark random walk and a stock with a known beta to it."""
    rng = np.random.default_rng(seed)
    mkt = rng.normal(drift, 0.01, n)
    stock = beta_ * mkt + rng.normal(0, 0.004, n)
    start = 1_600_000_000
    b = np.cumprod(1 + mkt) * 100
    s = np.cumprod(1 + stock) * 50
    to_pts = lambda arr: [(start + i * DAY, float(v), float(v)) for i, v in enumerate(arr)]  # noqa: E731
    return PriceData.from_points(to_pts(s)), PriceData.from_points(to_pts(b))


@pytest.fixture(scope="module")
def northwind():
    return analyze([ROOT / "samples" / "northwind"])


# --------------------------------------------------------------------- market

def test_beta_recovers_known_value():
    s, b = synthetic(beta_=1.5)
    est = beta(s.adj, b.adj)
    assert est["beta"] == pytest.approx(1.5, abs=0.15)
    assert 0 < est["r_squared"] <= 1


def test_drawdown_rsi_and_stats():
    s, b = synthetic()
    dd, peak, trough = max_drawdown(s.adj)
    assert dd <= 0 and peak <= trough
    assert 0 <= rsi(s.close) <= 100
    up = PriceData.from_points([(1_600_000_000 + i * DAY, 100 + i, 100 + i) for i in range(60)])
    assert rsi(up.close) == 100.0  # only gains
    st = stats(s, b, rf=0.03)
    assert st["beta"]["beta"] > 1 and st["volatility_1y"] > 0
    assert st["last_cross"] in {"golden", "death", None}
    assert st["returns"]["1Y"] is not None and st["benchmark_returns"]["YTD"] is not None


def test_price_on_uses_last_close_before_date():
    px = PriceData.from_points([(1_600_000_000 + i * DAY, 10 + i, 10 + i) for i in range(10)])
    d = px.close.index[4]
    assert px.price_on(d) == 14
    assert px.price_on(d + __import__("pandas").Timedelta(hours=30)) == 15
    assert px.price_on("1990-01-01") is None


# ----------------------------------------------------------------- scorecards

def test_scorecards_on_sample(northwind):
    fd = northwind.data
    p = piotroski(fd, 2025)
    assert p["max"] == 9 and 0 <= p["score"] <= 9
    names = {s["name"]: s["pass"] for s in p["signals"]}
    assert names["Positive ROA"] is True
    assert names["No new shares issued"] is True        # 96 -> 95 diluted shares
    assert names["Cash flow exceeds net income"] is False  # OCF 140 < NI 187.5
    z = altman(fd, 2025)
    x1 = (645 - 360) / 1565
    x2 = (785 - 200) / 1565
    x3 = 280 / 1565
    x4 = 785 / 780
    assert z["models"][0]["value"] == pytest.approx(6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4)
    zm = altman(fd, 2025, market_cap=2000)
    assert zm["models"][0]["name"].startswith("Z-Score (original")
    m = beneish(fd, 2025)
    dsri = (310 / 1702) / (240 / 1520)
    assert next(c for c in m["components"] if c["key"] == "DSRI")["value"] == pytest.approx(dsri)
    assert m["likely_manipulator"] == (m["value"] > -1.78)


# ------------------------------------------------------------------ valuation

def test_dcf_matches_closed_form_when_growth_is_flat():
    # Constant 3% growth forever = Gordon growth: FCF1 / (r - g)
    r = dcf(100, 0.03, 0.03, 0.10, net_debt=0, shares=10)
    assert r["enterprise_value"] == pytest.approx(100 * 1.03 / (0.10 - 0.03), rel=1e-9)
    assert r["per_share"] == pytest.approx(r["equity_value"] / 10)
    assert dcf(100, 0.05, 0.08, 0.08, 0, 1) is None  # r must exceed terminal growth


def test_reverse_dcf_round_trip():
    target = dcf(100, 0.12, 0.03, 0.09, net_debt=50, shares=10)["per_share"]
    g = reverse_dcf(target, 10, 100, 0.03, 0.09, 50)
    assert g == pytest.approx(0.12, abs=1e-6)


def test_split_detection_and_attribution(northwind):
    import copy
    fd = copy.deepcopy(northwind.data)
    # Simulate a 4-for-1 split between FY23 and FY24 in the reported share counts.
    fd.values["shares_outstanding"] = {2021: 25, 2022: 24.75, 2023: 24.25, 2024: 96, 2025: 95}
    adj, notes = split_adjusted_shares(fd)
    assert adj[2021] == pytest.approx(100) and adj[2025] == 95 and "4-for-1" in notes[0]
    ends = {y: f"{y}-12-31" for y in fd.years}
    prices = {f"{y}-12-31": p for y, p in zip(fd.years, [10, 12, 15, 18, 20])}
    att = attribution(fd, ends, lambda d: prices.get(d))
    for per in att["periods"]:  # price change = (1 + EPS change)(1 + P/E change) - 1, exactly
        assert (1 + per["price_change"]) == pytest.approx((1 + per["eps_change"]) * (1 + per["pe_change"]))
    assert att["total"]["price_change"] == pytest.approx(1.0)


# -------------------------------------------------------------------- drivers

def test_research_without_market_data(northwind):
    r = research(northwind)
    assert r["market"] is None and r["valuation_model"]["price"] is None
    f = {x["key"]: x for x in r["drivers"]["factors"]}
    assert not f["valuation"]["available"] and not f["momentum"]["available"]
    assert f["growth"]["available"] and f["growth"]["score"] > 0  # 14% revenue CAGR
    assert r["drivers"]["label"] in {"Bullish tilt", "Moderately positive", "Balanced", "Moderately negative", "Bearish tilt"}
    assert all(-2 <= x["score"] <= 2 for x in r["drivers"]["factors"])


def test_research_with_market_data(northwind):
    s, b = synthetic(n=800)
    pts = lambda px: [(int(ts.value // 1e9), float(c), float(a)) for (ts, c), a in zip(px.close.items(), px.adj.values)]  # noqa: E731
    hist = {"NWND": pts(s), "^GSPC": pts(b)}
    r = research(northwind, symbol="NWND", currency="USD", shares_now=95, period_ends={},
                 history=lambda sym: hist[sym], benchmark=("^GSPC", "S&P 500"), rf=(0.04, "test"))
    vm = r["valuation_model"]
    assert r["market"]["benchmark"] == "S&P 500"
    assert vm["market_cap"] == pytest.approx(r["market"]["last_price"] * 95)
    assert vm["wacc"]["cost_of_equity"] == pytest.approx(0.04 + vm["wacc"]["beta_used"] * 0.05)
    levers = {x["lever"] for x in vm["sensitivities"]}
    assert {"Net margin", "Valuation multiple (P/E)", "Overall market"} <= levers
    f = {x["key"]: x for x in r["drivers"]["factors"]}
    assert f["valuation"]["available"] and f["momentum"]["available"] and f["risk"]["available"]
    assert math.isfinite(r["drivers"]["overall"])
