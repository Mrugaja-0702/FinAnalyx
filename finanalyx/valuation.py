"""Valuation toolkit: WACC (CAPM), two-stage DCF, reverse DCF, scenario targets,
price-change attribution (EPS growth vs P/E re-rating) and value sensitivities.

The browser re-implements ``dcf`` for instant slider feedback; this module supplies
the defaults, the sensitivity grid and server-side checks. Keep the two in sync.
"""
from __future__ import annotations

import math
import statistics

from .model import FinancialData, fy
from .ratios import RatioResults

DCF_YEARS = 10
HIGH_GROWTH_YEARS = 5


def _latest(fd: FinancialData, key: str) -> tuple[int, float] | None:
    s = fd.series(key).dropna()
    return (int(s.index[-1]), float(s.iloc[-1])) if len(s) else None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def effective_tax_rate(fd: FinancialData) -> tuple[float, str]:
    rates = []
    for y in fd.years[-3:]:
        t, p = fd.get("tax_expense", y), fd.get("pretax_income", y)
        if t is not None and p and p > 0:
            rates.append(t / p)
    if rates:
        return _clamp(statistics.median(rates), 0.0, 0.35), "median effective tax rate, last 3 years"
    return 0.25, "assumed 25% (tax data unavailable)"


def fcff_history(fd: FinancialData, tax: float) -> dict[int, float]:
    """Free cash flow to the firm = OCF + after-tax interest - capex (OCF is after interest under US GAAP/IFRS
    common presentation, so interest is added back to get a pre-financing cash flow)."""
    out = {}
    for y in fd.years:
        ocf, capex = fd.get("operating_cash_flow", y), fd.get("capex", y)
        if ocf is None or capex is None:
            continue
        out[y] = ocf + (fd.get("interest_expense", y) or 0.0) * (1 - tax) - capex
    return out


def wacc(fd: FinancialData, beta: float | None, rf: float, erp: float, market_cap: float | None,
         tax: float) -> dict:
    b = beta if beta is not None else 1.0
    b_used = _clamp(b, 0.4, 2.5)
    ke = rf + b_used * erp
    debt = (_latest(fd, "total_debt_used") or (0, 0.0))[1]
    interest = (_latest(fd, "interest_expense") or (0, None))[1]
    debts = fd.series("total_debt_used").dropna()
    avg_debt = float(debts.iloc[-2:].mean()) if len(debts) else debt
    kd_pre = interest / avg_debt if interest and avg_debt > 0 else rf + 0.015
    kd_pre = _clamp(kd_pre, rf, rf + 0.08)
    kd = kd_pre * (1 - tax)
    equity = market_cap if market_cap else (_latest(fd, "total_equity") or (0, 0.0))[1]
    total = (equity or 0) + debt
    we = equity / total if total > 0 and equity > 0 else 1.0
    w = we * ke + (1 - we) * kd
    return {"rf": rf, "erp": erp, "beta": b, "beta_used": b_used, "cost_of_equity": ke, "cost_of_debt_pre_tax": kd_pre,
            "tax_rate": tax, "cost_of_debt": kd, "weight_equity": we, "weight_debt": 1 - we, "wacc": w,
            "equity_basis": "market value" if market_cap else "book value", "debt": debt}


def dcf(base_fcf: float, g_high: float, g_terminal: float, discount: float, net_debt: float,
        shares: float | None, years: int = DCF_YEARS, high_years: int = HIGH_GROWTH_YEARS) -> dict | None:
    """Two-stage DCF: ``g_high`` for ``high_years``, then a linear fade to ``g_terminal`` by year ``years``,
    then a Gordon-growth terminal value."""
    if discount <= g_terminal + 0.005 or base_fcf is None:
        return None
    fcf, pv, flows = base_fcf, 0.0, []
    for t in range(1, years + 1):
        if t <= high_years:
            g = g_high
        else:
            g = g_high + (g_terminal - g_high) * (t - high_years) / (years - high_years)
        fcf *= 1 + g
        disc = fcf / (1 + discount) ** t
        pv += disc
        flows.append({"year": t, "growth": g, "fcf": fcf, "pv": disc})
    tv = fcf * (1 + g_terminal) / (discount - g_terminal)
    pv_tv = tv / (1 + discount) ** years
    ev = pv + pv_tv
    equity = ev - net_debt
    return {"enterprise_value": ev, "equity_value": equity, "pv_fcf": pv, "pv_terminal": pv_tv,
            "terminal_share": pv_tv / ev if ev else None,
            "per_share": equity / shares if shares else None, "flows": flows}


def reverse_dcf(price: float, shares: float, base_fcf: float, g_terminal: float, discount: float,
                net_debt: float) -> float | None:
    """High-stage growth rate that makes the DCF value equal to the current price."""
    if not (price and shares and base_fcf and base_fcf > 0):
        return None
    target = price * shares

    def val(g):
        r = dcf(base_fcf, g, g_terminal, discount, net_debt, shares)
        return r["equity_value"] if r else None

    lo, hi = -0.5, 1.0
    v_lo, v_hi = val(lo), val(hi)
    if v_lo is None or v_hi is None or not (v_lo <= target <= v_hi):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if val(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def split_adjusted_shares(fd: FinancialData) -> tuple[dict[int, float], list[str]]:
    """Diluted shares restated onto the latest basis, undoing stock splits that older filings predate."""
    s = fd.series("shares_outstanding").dropna()
    shares = {int(y): float(v) for y, v in s.items() if v > 0}
    notes = []
    years = sorted(shares)
    factor = 1.0
    adjusted = {}
    for i in range(len(years) - 1, -1, -1):
        y = years[i]
        if i < len(years) - 1:
            nxt = years[i + 1]
            ratio = shares[nxt] / shares[y]  # raw ratio between consecutive filings
            for f in (2, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40, 50):
                if abs(ratio / f - 1) < 0.08:
                    factor *= f
                    notes.append(f"{f}-for-1 split detected between {fy(y)} and {fy(nxt)}; earlier share counts restated.")
                    break
                if abs(ratio * f - 1) < 0.08 and f > 1:
                    factor /= f
                    notes.append(f"1-for-{f} reverse split detected between {fy(y)} and {fy(nxt)}.")
                    break
        adjusted[y] = shares[y] * factor
    return adjusted, notes


def attribution(fd: FinancialData, period_ends: dict[int, str], price_on) -> dict | None:
    """Split the price change between fiscal year-ends into EPS growth and P/E re-rating.

    ln(P1/P0) = ln(EPS1/EPS0) + ln(PE1/PE0) — each period's move is exactly the product of the two.
    """
    shares, notes = split_adjusted_shares(fd)
    rows = []
    for y in sorted(period_ends):
        price = price_on(period_ends[y])
        ni = fd.get("net_income", y)
        sh = shares.get(y)
        if price is None or ni is None or not sh:
            continue
        eps = ni / sh
        rows.append({"year": y, "label": fy(y), "date": period_ends[y], "price": price, "eps": eps,
                     "pe": price / eps if eps > 0 else None})
    if len(rows) < 2:
        return None
    periods = []
    for a, b in zip(rows, rows[1:]):
        if a["eps"] > 0 and b["eps"] > 0:
            price_chg = b["price"] / a["price"] - 1
            eps_chg = b["eps"] / a["eps"] - 1
            pe_chg = b["pe"] / a["pe"] - 1
            lp, le, lpe = math.log(1 + price_chg), math.log(1 + eps_chg), math.log(1 + pe_chg)
            periods.append({"from": a["label"], "to": b["label"], "price_change": price_chg, "eps_change": eps_chg,
                            "pe_change": pe_chg,
                            "eps_share": le / lp if abs(lp) > 1e-9 else None, "driver": "earnings" if abs(le) >= abs(lpe) else "valuation"})
    first, last = rows[0], rows[-1]
    total = None
    if first["eps"] > 0 and last["eps"] > 0:
        total = {"from": first["label"], "to": last["label"], "price_change": last["price"] / first["price"] - 1,
                 "eps_change": last["eps"] / first["eps"] - 1, "pe_change": last["pe"] / first["pe"] - 1}
        lp = math.log(1 + total["price_change"])
        le = math.log(1 + total["eps_change"])
        total["eps_share"] = le / lp if abs(lp) > 1e-9 else None
        total["driver"] = "earnings growth" if abs(le) >= abs(lp - le) else "P/E re-rating"
    pes = [r["pe"] for r in rows if r["pe"]]
    return {"rows": rows, "periods": periods, "total": total, "notes": notes,
            "pe_median": statistics.median(pes) if pes else None,
            "explain": "Price = EPS x P/E. A share price can rise because the company earns more (EPS growth) or "
                       "because investors pay more for each unit of earnings (P/E re-rating). Earnings-driven gains "
                       "tend to be more durable; multiple-driven gains reverse when sentiment or interest rates change."}


def operating_leverage(fd: FinancialData) -> float | None:
    """Median degree of operating leverage: %change EBIT / %change revenue."""
    vals = []
    for y in fd.years[1:]:
        r0, r1 = fd.get("revenue", y - 1), fd.get("revenue", y)
        e0, e1 = fd.get("ebit", y - 1), fd.get("ebit", y)
        if None in (r0, r1, e0, e1) or r0 <= 0 or e0 <= 0:
            continue
        dr = r1 / r0 - 1
        if abs(dr) < 0.02:
            continue
        vals.append((e1 / e0 - 1) / dr)
    return _clamp(statistics.median(vals), 0.0, 5.0) if vals else None


def sensitivities(fd: FinancialData, tax: float, pe: float | None, dcf_base: dict | None,
                  dcf_fn, beta: float | None) -> list[dict]:
    """How much EPS / value moves for a given change in each lever."""
    out = []
    rev = _latest(fd, "revenue")
    ni = _latest(fd, "net_income")
    ebit = _latest(fd, "ebit")
    debt = _latest(fd, "total_debt_used")
    if rev and ni and ni[1] > 0:
        impact = rev[1] * 0.01 / ni[1]
        out.append({"lever": "Net margin", "change": "+1 percentage point", "impact": impact, "basis": "EPS",
                    "explain": "Each extra point of margin on the current revenue base flows straight to earnings; at a "
                               "constant P/E the share price moves by the same percentage."})
        dol = operating_leverage(fd)
        if ebit and ebit[1] > 0:
            d = dol if dol is not None else 1.0
            impact = d * 0.05 * ebit[1] * (1 - tax) / ni[1]
            out.append({"lever": "Revenue", "change": "+5% vs plan", "impact": impact, "basis": "EPS",
                        "explain": f"With operating leverage of ~{d:.1f}x (EBIT moves {d:.1f}x as fast as revenue), a "
                                   "5% revenue beat or miss is amplified in earnings."
                                   + ("" if dol is not None else " (leverage assumed 1.0x - not enough history)")})
        if debt and debt[1] > 0:
            impact = -debt[1] * 0.01 * (1 - tax) / ni[1]
            out.append({"lever": "Interest rate on debt", "change": "+1 percentage point", "impact": impact,
                        "basis": "EPS", "explain": "Higher borrowing costs on existing debt reduce after-tax earnings "
                                                   "once the debt reprices."})
    if pe and pe > 0:
        out.append({"lever": "Valuation multiple (P/E)", "change": "+1 turn", "impact": 1 / pe, "basis": "Price",
                    "explain": f"At a P/E of {pe:.1f}x, one extra turn of multiple lifts the price by {1 / pe:.1%} with no "
                               "change in earnings - multiples move with sentiment, growth expectations and interest rates."})
    if dcf_base and dcf_fn:
        hi = dcf_fn(0.01)
        if hi and dcf_base.get("equity_value") and dcf_base["equity_value"] > 0:
            out.append({"lever": "Discount rate (WACC)", "change": "+1 percentage point",
                        "impact": hi["equity_value"] / dcf_base["equity_value"] - 1, "basis": "DCF value",
                        "explain": "Rising interest rates or risk premia raise the discount rate, shrinking the present "
                                   "value of distant cash flows - why long-duration growth stocks fall most when rates rise."})
    if beta is not None:
        out.append({"lever": "Overall market", "change": "-10% market fall", "impact": -0.10 * beta, "basis": "Price (expected)",
                    "explain": f"With a beta of {beta:.2f}, the stock has historically moved about {beta:.2f}x the market. "
                               "This is systematic risk that diversification cannot remove."})
    return out


def build_model(fd: FinancialData, rr: RatioResults, *, price: float | None, shares: float | None,
                beta: float | None, rf: float, rf_source: str, currency: str | None) -> dict:
    """Defaults and results for the valuation lab."""
    tax, tax_note = effective_tax_rate(fd)
    erp = 0.07 if (currency or "").upper() == "INR" else 0.05
    market_cap = price * shares if price and shares else None
    w = wacc(fd, beta, rf, erp, market_cap, tax)
    hist = fcff_history(fd, tax)
    recent = [hist[y] for y in sorted(hist)[-3:]]
    base = statistics.mean(recent) if recent else None
    latest_fcff = hist[max(hist)] if hist else None
    rc = rr.get("revenue_cagr")
    g_default = _clamp(rc.value, -0.05, 0.25) if rc.ok else 0.05
    g_terminal = 0.05 if (currency or "").upper() == "INR" else min(0.03, max(0.015, rf - 0.01))
    cash = (_latest(fd, "cash") or (0, 0.0))[1] + (_latest(fd, "short_term_investments") or (0, 0.0))[1]
    net_debt = w["debt"] - cash
    result = dcf(base, g_default, g_terminal, w["wacc"], net_debt, shares) if base and base > 0 else None

    grid = None
    if result:
        waccs = [w["wacc"] + d for d in (-0.02, -0.01, 0.0, 0.01, 0.02)]
        gts = [g_terminal + d for d in (-0.01, -0.005, 0.0, 0.005, 0.01)]
        grid = {"wacc": waccs, "terminal": gts,
                "values": [[(r["per_share"] if (r := dcf(base, g_default, gt, wc, net_debt, shares)) and shares else
                             (r["equity_value"] if r else None)) for gt in gts] for wc in waccs]}
    implied = reverse_dcf(price, shares, base, g_terminal, w["wacc"], net_debt) if price and shares and base else None

    eps_latest = None
    ni = _latest(fd, "net_income")
    if ni and shares:
        eps_latest = ni[1] / shares
    pe = price / eps_latest if price and eps_latest and eps_latest > 0 else None

    def dcf_shift(dw):
        return dcf(base, g_default, g_terminal, w["wacc"] + dw, net_debt, shares) if base and base > 0 else None

    sens = sensitivities(fd, tax, pe, result, dcf_shift, beta)

    # Scenario (EPS x P/E) defaults from the company's own history
    nm = rr.series("net_margin").dropna()
    rg = rr.series("revenue_growth").dropna()
    rev = _latest(fd, "revenue")
    scen = None
    if rev and len(nm):
        g_hist = rc.value if rc.ok else (float(rg.mean()) if len(rg) else 0.05)
        m_now = float(nm.iloc[-1])
        pe_base = pe if pe else 15.0
        scen = {
            "revenue": rev[1], "shares": shares, "price": price, "years": 3,
            "bear": {"growth": _clamp(min(g_hist, float(rg.min()) if len(rg) else g_hist) - 0.02, -0.2, 0.3),
                     "margin": max(float(nm.min()), m_now - 0.03) if m_now > 0 else m_now, "pe": max(pe_base * 0.7, 5)},
            "base": {"growth": _clamp(g_hist, -0.1, 0.3), "margin": m_now, "pe": pe_base},
            "bull": {"growth": _clamp(max(g_hist, float(rg.max()) if len(rg) else g_hist) + 0.02, -0.1, 0.4),
                     "margin": min(float(nm.max()), m_now + 0.03) if m_now > 0 else m_now + 0.02, "pe": pe_base * 1.25},
        }

    return {
        "price": price, "shares": shares, "market_cap": market_cap, "currency": currency,
        "rf_source": rf_source, "tax_note": tax_note, "wacc": w,
        "fcff_history": {fy(y): v for y, v in hist.items()}, "base_fcff": base, "latest_fcff": latest_fcff,
        "base_note": "Average free cash flow to the firm over the last 3 years (smooths one-off capex swings).",
        "growth": g_default, "terminal_growth": g_terminal, "net_debt": net_debt, "cash": cash,
        "dcf": result, "upside": (result["per_share"] / price - 1) if result and result.get("per_share") and price else None,
        "sensitivity": grid, "implied_growth": implied, "historical_growth": rc.value if rc.ok else None,
        "eps": eps_latest, "pe": pe, "sensitivities": sens, "scenarios": scen,
        "dcf_note": None if result else "DCF not meaningful: average free cash flow is negative or unavailable "
                                        "(typical for early-stage, cyclical-trough or heavy-investment years).",
    }
