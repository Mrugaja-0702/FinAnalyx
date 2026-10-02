"""Stock drivers: which fundamental and market factors push the share price up or down.

Eight factors, each scored -2 (strong headwind) to +2 (strong tailwind) from explicit,
inspectable evidence rules. The output is designed for learning: every factor carries
the evidence behind its score, why that factor moves share prices, and what to watch.

This is a structured reading of the data, not a recommendation.
"""
from __future__ import annotations

from .analyzer import Analysis
from .model import fy

FACTORS = {
    "growth": ("Growth", 1.2,
               "Over the long run share prices follow earnings. Investors pay up for companies that compound revenue "
               "and EPS; when growth slows, valuations that assumed continued growth get cut (a 'de-rating')."),
    "profitability": ("Profitability", 1.2,
                      "High returns on capital mean each unit reinvested creates more value. Expanding margins lift EPS "
                      "faster than revenue (operating leverage); shrinking margins do the opposite."),
    "quality": ("Earnings quality", 1.0,
                "Markets eventually price cash, not accounting profit. Profits not backed by operating cash flow, or "
                "accounting red flags, often precede earnings disappointments and sharp price falls."),
    "strength": ("Financial strength", 1.0,
                 "Leverage magnifies outcomes: debt boosts ROE in good times but raises bankruptcy and refinancing risk. "
                 "Weak balance sheets are punished hardest in recessions and when interest rates rise."),
    "valuation": ("Valuation", 1.2,
                  "The price you pay sets your future return. A great business bought at a price that already discounts "
                  "optimistic growth can still disappoint; a cheap valuation leaves room for re-rating."),
    "momentum": ("Price momentum", 0.8,
                 "Stocks that have outperformed over 3-12 months tend to keep doing so for a while (the momentum "
                 "anomaly); prices below their long-term trend often reflect deteriorating sentiment."),
    "risk": ("Market risk", 0.8,
             "Beta and volatility determine how violently a stock reacts to market swings. Higher systematic risk "
             "means a higher required return (CAPM) and larger drawdowns in sell-offs."),
    "capital": ("Capital allocation", 0.8,
                "How management uses cash - buybacks, dividends, reinvestment or dilution - changes each shareholder's "
                "claim on future earnings. Returns above the cost of equity create value; dilution destroys it."),
}


class _Factor:
    def __init__(self, key: str):
        self.key = key
        self.name, self.weight, self.why = FACTORS[key]
        self.points = 0.0
        self.evidence: list[dict] = []
        self.watch: list[str] = []
        self.available = True

    def add(self, pts: float, text: str) -> None:
        self.points += pts
        self.evidence.append({"text": text, "impact": "positive" if pts > 0 else "negative" if pts < 0 else "neutral",
                              "points": pts})

    def result(self) -> dict:
        score = max(-2.0, min(2.0, self.points))
        signal = "bullish" if score >= 0.75 else "bearish" if score <= -0.75 else "neutral"
        summary = {"bullish": "Tailwind for the share price", "bearish": "Headwind for the share price",
                   "neutral": "Mixed / limited impact"}[signal]
        return {"key": self.key, "name": self.name, "weight": self.weight, "score": round(score, 2),
                "signal": signal if self.available else "n/a",
                "summary": summary if self.available else "Not enough data", "evidence": self.evidence,
                "why": self.why, "watch": self.watch, "available": self.available}


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _p(x: float) -> str:
    return f"{x * 100:.1f}%"


def analyze_drivers(a: Analysis, scores: dict, market: dict | None, val: dict | None) -> dict:
    rr, fd = a.ratios, a.data
    lv = lambda k: rr.latest(k)[1]  # noqa: E731
    f = {k: _Factor(k) for k in FACTORS}

    # ------------------------------------------------------------- growth
    g = f["growth"]
    rc, pc = rr.get("revenue_cagr"), rr.get("profit_cagr")
    if rc.ok:
        if rc.value >= 0.20:
            g.add(2, f"Revenue compounding fast at {_p(rc.value)} a year ({rc.note}).")
        elif rc.value >= 0.10:
            g.add(1, f"Solid revenue growth of {_p(rc.value)} a year.")
        elif rc.value >= 0.03:
            g.add(0.25, f"Modest revenue growth of {_p(rc.value)} a year.")
        elif rc.value < 0:
            g.add(-1.5, f"Revenue shrinking {_p(rc.value)} a year.")
        else:
            g.add(-0.25, f"Revenue roughly flat ({_p(rc.value)} a year).")
    rg = rr.series("revenue_growth").dropna()
    if len(rg) >= 3:
        last, prior = rg.iloc[-1], rg.iloc[:-1].mean()
        if last < prior - 0.03:
            g.add(-0.75, f"Growth slowing: latest {_p(last)} vs {_p(prior)} average before - markets often de-rate "
                         "decelerating growers.")
            g.watch.append("Next results: does revenue growth stabilise or keep decelerating?")
        elif last > prior + 0.03:
            g.add(0.5, f"Growth accelerating: latest {_p(last)} vs {_p(prior)} average before.")
    if pc.ok:
        if pc.value >= 0.15:
            g.add(0.75, f"Net income compounding at {_p(pc.value)} a year.")
        elif pc.value < 0:
            g.add(-0.75, f"Net income declining {_p(pc.value)} a year.")
    elif pc.status == "n/m":
        g.add(-0.5, f"Profit growth not meaningful ({pc.note}).")
    if not g.evidence:
        g.available = False

    # ------------------------------------------------------- profitability
    p = f["profitability"]
    roe, em = lv("roe"), lv("equity_multiplier")
    if roe.ok:
        lev_note = f" (flattered by leverage: equity multiplier {em.value:.1f}x)" if em.ok and em.value > 4 else ""
        if roe.value >= 0.25:
            p.add(1.5 if not lev_note else 0.75, f"Very high ROE of {_p(roe.value)}{lev_note}.")
        elif roe.value >= 0.15:
            p.add(1, f"Healthy ROE of {_p(roe.value)}{lev_note}.")
        elif roe.value < 0.08:
            p.add(-1, f"Low ROE of {_p(roe.value)} - below a typical cost of equity, so growth may not create value.")
        else:
            p.add(0, f"ROE of {_p(roe.value)} is middling.")
    nm = rr.series("net_margin").dropna()
    if len(nm) and nm.iloc[-1] < 0:
        p.add(-1.5, f"Loss-making: net margin {_p(nm.iloc[-1])}.")
    em_ser = rr.series("ebitda_margin").dropna()
    if len(em_ser) >= 3:
        d = em_ser.iloc[-1] - em_ser.iloc[-4:-1].mean()
        if d >= 0.01:
            p.add(0.75, f"EBITDA margin expanding: {_p(em_ser.iloc[-1])}, {d * 10000:+.0f} bps vs the prior 3-year "
                        "average - operating leverage is lifting EPS.")
        elif d <= -0.01:
            p.add(-0.75, f"EBITDA margin contracting: {_p(em_ser.iloc[-1])}, {d * 10000:+.0f} bps vs the prior 3-year "
                         "average.")
            p.watch.append("Margin guidance and cost growth versus revenue growth.")
    if not p.evidence:
        p.available = False

    # -------------------------------------------------------------- quality
    q = f["quality"]
    cc = rr.series("cash_conversion").dropna()
    if len(cc):
        avg = float(cc.iloc[-3:].mean())
        if avg >= 1.0:
            q.add(1, f"Operating cash flow averages {avg:.2f}x net income (last {min(3, len(cc))} years) - profits are cash-backed.")
        elif avg < 0.8:
            q.add(-1, f"Operating cash flow only {avg:.2f}x net income on average - profit not converting to cash.")
            q.watch.append("Receivables and inventory build-up in the next balance sheet.")
    pio = scores.get("piotroski")
    if pio:
        if pio["scaled"] >= 7:
            q.add(1, f"Piotroski F-Score {pio['score']}/{pio['max']} - fundamentals improving broadly.")
        elif pio["scaled"] <= 3:
            q.add(-1, f"Piotroski F-Score {pio['score']}/{pio['max']} - fundamentals deteriorating.")
        else:
            q.add(0, f"Piotroski F-Score {pio['score']}/{pio['max']} - average.")
    ben = scores.get("beneish")
    if ben:
        if ben["likely_manipulator"]:
            flagged = [c["key"] for c in ben["components"] if c["flag"]]
            q.add(-1.5, f"Beneish M-Score {ben['value']:.2f} is above -1.78 - accounting red flag"
                        + (f" (driven by {', '.join(flagged)})." if flagged else "."))
            q.watch.append("Audit opinion, revenue recognition and accrual trends.")
        else:
            q.add(0.25, f"Beneish M-Score {ben['value']:.2f} - no earnings-manipulation signal.")
    if not q.evidence:
        q.available = False

    # ------------------------------------------------------------- strength
    s = f["strength"]
    de, ic, cr = lv("debt_to_equity"), lv("interest_coverage"), lv("current_ratio")
    nd = fd.series("net_debt").dropna()
    if len(nd) and nd.iloc[-1] < 0:
        s.add(0.75, "Net cash position - more cash than debt, giving resilience and optionality.")
    if de.ok:
        if de.value <= 0.5:
            s.add(0.75, f"Low leverage: Debt/Equity {de.value:.2f}x.")
        elif de.value > 2:
            s.add(-1.5, f"High leverage: Debt/Equity {de.value:.2f}x - equity is a thin cushion.")
        elif de.value > 1:
            s.add(-0.5, f"Elevated leverage: Debt/Equity {de.value:.2f}x.")
    if ic.ok:
        if ic.value < 1.5:
            s.add(-2, f"Interest coverage only {ic.value:.1f}x - earnings barely cover interest.")
        elif ic.value < 3:
            s.add(-1, f"Thin interest coverage of {ic.value:.1f}x.")
            s.watch.append("Refinancing terms and interest-rate exposure.")
        elif ic.value > 10:
            s.add(0.5, f"Interest is easily covered ({ic.value:.1f}x).")
    alt = scores.get("altman")
    if alt and alt.get("zone"):
        z = {"safe": (0.5, "safe zone"), "grey": (-0.25, "grey zone"), "distress": (-1.5, "distress zone")}[alt["zone"]]
        s.add(z[0], f"Altman {alt['primary'].split(' (')[0]} {alt['value']:.2f} - {z[1]}.")
    if cr.ok and cr.value < 1:
        s.add(-0.5, f"Current ratio {cr.value:.2f}x - short-term liabilities exceed short-term assets.")
    if not s.evidence:
        s.available = False

    # ------------------------------------------------------------- valuation
    v = f["valuation"]
    if val and val.get("price"):
        pe = val.get("pe")
        growth = pc.value if pc.ok else (rc.value if rc.ok else None)
        if pe:
            if growth and growth > 0:
                peg = pe / (growth * 100)
                if peg < 1:
                    v.add(1, f"P/E {pe:.1f}x vs earnings growth {_p(growth)} - PEG {peg:.2f} (<1 suggests growth is cheap).")
                elif peg > 2.5:
                    v.add(-1, f"P/E {pe:.1f}x vs earnings growth {_p(growth)} - PEG {peg:.2f}; the price assumes "
                              "faster growth than history shows.")
                else:
                    v.add(0, f"P/E {pe:.1f}x with PEG {peg:.2f} - fairly priced for its growth.")
            elif pe > 25:
                v.add(-0.75, f"P/E {pe:.1f}x without demonstrated earnings growth.")
        elif val.get("eps") is not None and val["eps"] <= 0:
            v.add(-0.5, "No P/E: the company is loss-making, so valuation rests on future profits.")
        base_fcff, mcap = val.get("latest_fcff"), val.get("market_cap")
        if base_fcff is not None and mcap:
            fy_ = base_fcff / mcap
            if fy_ >= 0.06:
                v.add(1, f"Free cash flow yield {_p(fy_)} - investors are paid well in cash for the price.")
            elif fy_ < 0.02:
                v.add(-0.5, f"Free cash flow yield only {_p(fy_)}.")
        ig, hg = val.get("implied_growth"), val.get("historical_growth")
        if ig is not None and hg is not None:
            if ig <= hg - 0.02:
                v.add(1, f"Reverse DCF: the price implies {_p(ig)} annual cash-flow growth vs {_p(hg)} revenue "
                         "growth delivered - expectations look undemanding.")
            elif ig >= hg + 0.05:
                v.add(-1, f"Reverse DCF: the price implies {_p(ig)} annual growth vs {_p(hg)} delivered - "
                          "priced for perfection.")
                v.watch.append("Any growth shortfall versus the high expectations embedded in the price.")
            else:
                v.add(0, f"Reverse DCF: implied growth {_p(ig)} is close to the {_p(hg)} delivered.")
        att = val.get("attribution") or {}
        med = att.get("pe_median")
        if pe and med:
            if pe > med * 1.3:
                v.add(-0.5, f"P/E {pe:.1f}x is above its fiscal-year-end median of {med:.1f}x - room to de-rate.")
            elif pe < med * 0.8:
                v.add(0.5, f"P/E {pe:.1f}x is below its fiscal-year-end median of {med:.1f}x - room to re-rate.")
    else:
        v.available = False

    # -------------------------------------------------------------- momentum
    m = f["momentum"]
    r = f["risk"]
    if market:
        price, ma50, ma200 = market.get("last_price"), market.get("ma50"), market.get("ma200")
        if price and ma200:
            gap = price / ma200 - 1
            m.add(0.5 if gap > 0 else -0.5, f"Price is {_pct(gap)} {'above' if gap > 0 else 'below'} its 200-day moving "
                                            "average (long-term trend " + ("up)." if gap > 0 else "down)."))
        if market.get("last_cross") and ma50 and ma200:
            golden = ma50 > ma200
            m.add(0.5 if golden else -0.5, ("Golden cross" if golden else "Death cross")
                  + f" regime: 50-day MA {'above' if golden else 'below'} 200-day MA (last cross {market.get('last_cross_date')}).")
        rel = market.get("relative_1y")
        if rel is not None:
            if rel > 0.10:
                m.add(0.75, f"Outperformed the benchmark by {_pct(rel)} over 12 months.")
            elif rel < -0.10:
                m.add(-0.75, f"Underperformed the benchmark by {_pct(rel)} over 12 months.")
            else:
                m.add(0, f"In line with the benchmark over 12 months ({_pct(rel)}).")
        rsi = market.get("rsi14")
        if rsi is not None:
            if rsi > 70:
                m.add(-0.25, f"RSI {rsi:.0f} - overbought; short-term pullbacks are common from here.")
            elif rsi < 30:
                m.add(0.25, f"RSI {rsi:.0f} - oversold; selling may be stretched.")
        dd = market.get("drawdown_from_high")
        if dd is not None and dd < -0.25:
            m.watch.append(f"Stock is {_pct(dd)} below its 52-week high - watch whether support holds.")

        b = (market.get("beta") or {}).get("beta")
        vol = market.get("volatility_1y")
        if b is not None:
            if b > 1.3:
                r.add(-0.75, f"High beta {b:.2f}: tends to amplify market moves by ~{b:.1f}x.")
            elif b < 0.8:
                r.add(0.5, f"Defensive beta {b:.2f}: historically moves less than the market.")
            else:
                r.add(0, f"Beta {b:.2f}: moves broadly with the market.")
        if vol is not None:
            if vol > 0.45:
                r.add(-1, f"Very volatile: {_p(vol)} annualised volatility.")
            elif vol < 0.25:
                r.add(0.5, f"Relatively stable: {_p(vol)} annualised volatility.")
            else:
                r.add(0, f"Volatility {_p(vol)} annualised.")
        mdd = market.get("max_drawdown")
        if mdd is not None and mdd < -0.5:
            r.add(-0.5, f"Suffered a {_pct(mdd)} peak-to-trough fall in the period - shows how deep sell-offs can go.")
        sh = market.get("sharpe")
        if sh is not None:
            if sh > 1:
                r.add(0.5, f"Sharpe ratio {sh:.2f} - strong return per unit of risk.")
            elif sh < 0:
                r.add(-0.5, f"Sharpe ratio {sh:.2f} - returns below the risk-free rate.")
    else:
        m.available = r.available = False

    # ------------------------------------------------------- capital allocation
    c = f["capital"]
    sh_ser = fd.series("shares_outstanding").dropna()
    if len(sh_ser) >= 2:
        n = sh_ser.index[-1] - sh_ser.index[0]
        if n > 0 and sh_ser.iloc[0] > 0:
            ch = (sh_ser.iloc[-1] / sh_ser.iloc[0]) ** (1 / n) - 1
            if ch < -0.01:
                c.add(1, f"Share count shrinking {_pct(ch)} a year - buybacks raise each share's claim on earnings.")
            elif ch > 0.02:
                c.add(-1, f"Share count growing {_pct(ch)} a year - dilution reduces each share's claim on earnings.")
            else:
                c.add(0, f"Share count stable ({_pct(ch)} a year).")
    divs, fcf = fd.series("dividends_paid").dropna(), fd.series("free_cash_flow").dropna()
    common = [y for y in divs.index if y in fcf.index and divs[y] > 0]
    if common:
        y = common[-1]
        if fcf[y] > 0:
            payout = divs[y] / fcf[y]
            if payout > 1:
                c.add(-0.75, f"Dividends were {payout:.0%} of free cash flow in {fy(y)} - not covered by cash generation.")
            else:
                c.add(0.25, f"Dividends {payout:.0%} of free cash flow in {fy(y)} - comfortably covered.")
        else:
            c.add(-0.75, f"Dividends paid despite negative free cash flow in {fy(y)}.")
    ke = ((val or {}).get("wacc") or {}).get("cost_of_equity")
    if ke and roe.ok:
        spread = roe.value - ke
        if spread > 0.03:
            c.add(0.75, f"ROE {_p(roe.value)} exceeds the cost of equity ({_p(ke)}) - reinvested profits create value.")
        elif spread < -0.02:
            c.add(-0.75, f"ROE {_p(roe.value)} is below the cost of equity ({_p(ke)}) - growth destroys value at the margin.")
    if not c.evidence:
        c.available = False

    factors = [x.result() for x in f.values()]
    avail = [x for x in factors if x["available"]]
    overall = (sum(x["score"] * x["weight"] for x in avail) / sum(x["weight"] for x in avail)) if avail else None
    if overall is None:
        label = "Insufficient data"
    elif overall >= 0.75:
        label = "Bullish tilt"
    elif overall >= 0.25:
        label = "Moderately positive"
    elif overall > -0.25:
        label = "Balanced"
    elif overall > -0.75:
        label = "Moderately negative"
    else:
        label = "Bearish tilt"

    ev = [(e, x["name"]) for x in avail for e in x["evidence"]]
    bull = [{"factor": n, "text": e["text"]} for e, n in sorted(ev, key=lambda t: -t[0]["points"]) if e["points"] > 0][:6]
    bear = [{"factor": n, "text": e["text"]} for e, n in sorted(ev, key=lambda t: t[0]["points"]) if e["points"] < 0][:6]
    watch = [w for x in factors for w in x["watch"]]
    for ins in a.trends.insights:
        if ins.severity == "concern" and len(watch) < 7:
            watch.append(ins.title)
    return {
        "overall": round(overall, 2) if overall is not None else None, "label": label,
        "factors": factors, "bull": bull, "bear": bear, "watch": watch[:7],
        "coverage": f"{len(avail)} of {len(factors)} factors scored"
                    + ("" if market else " (no market data: valuation, momentum and risk need a listed ticker)"),
        "disclaimer": "A rules-based reading of reported data for learning purposes - not investment advice.",
    }

