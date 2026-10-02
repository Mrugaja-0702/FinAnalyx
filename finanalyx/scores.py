"""Academic scoring models taught in financial statement analysis courses.

* Piotroski F-Score (2000): 9 binary signals of improving fundamentals.
* Altman Z-Score (1968) and Z''-Score (1995): bankruptcy risk.
* Beneish M-Score (1999): likelihood of earnings manipulation.

Each function returns components with values and plain-English explanations so the
dashboard can teach the model, not just print a number.
"""
from __future__ import annotations

from .model import FinancialData, fy


def _g(fd: FinancialData, key: str, y: int) -> float | None:
    return fd.get(key, y)


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _debt(fd: FinancialData, y: int) -> float | None:
    return _g(fd, "long_term_debt", y) if _g(fd, "long_term_debt", y) is not None else _g(fd, "total_debt_used", y)


# ----------------------------------------------------------------- Piotroski

def piotroski(fd: FinancialData, y: int) -> dict | None:
    p = y - 1
    if p not in fd.years:
        return None
    g = lambda k, yr: _g(fd, k, yr)  # noqa: E731
    roa = _div(g("net_income", y), g("total_assets", p))
    roa_prev = _div(g("net_income", p), g("total_assets", p - 1)) if p - 1 in fd.years else \
        _div(g("net_income", p), g("total_assets", p))
    lev = _div(_debt(fd, y), g("total_assets", y))
    lev_prev = _div(_debt(fd, p), g("total_assets", p))
    cr = _div(g("total_current_assets", y), g("total_current_liabilities", y))
    cr_prev = _div(g("total_current_assets", p), g("total_current_liabilities", p))
    gm = _div(g("gross_profit", y), g("revenue", y))
    gm_prev = _div(g("gross_profit", p), g("revenue", p))
    at = _div(g("revenue", y), g("total_assets", p))
    at_prev = _div(g("revenue", p), g("total_assets", p - 1)) if p - 1 in fd.years else \
        _div(g("revenue", p), g("total_assets", p))
    sh, sh_prev = g("shares_outstanding", y), g("shares_outstanding", p)
    ocf, ni = g("operating_cash_flow", y), g("net_income", y)

    def cmp(a, b, better="higher"):
        if a is None or b is None:
            return None
        return a > b if better == "higher" else a < b

    signals = [
        ("Profitability", "Positive ROA", roa is not None and roa > 0 if roa is not None else None,
         "Net income / opening total assets > 0. The business is profitable."),
        ("Profitability", "Positive operating cash flow", ocf > 0 if ocf is not None else None,
         "The business generates cash, not just accounting profit."),
        ("Profitability", "ROA improving", cmp(roa, roa_prev),
         "Return on assets higher than last year - profitability is trending up."),
        ("Profitability", "Cash flow exceeds net income", cmp(ocf, ni),
         "Operating cash flow > net income, i.e. earnings are backed by cash (low accruals)."),
        ("Leverage & liquidity", "Leverage falling", cmp(lev, lev_prev, "lower") if lev_prev else
         (lev == 0 if lev is not None else None),
         "Long-term debt / total assets lower than last year - less financial risk."),
        ("Leverage & liquidity", "Current ratio improving", cmp(cr, cr_prev),
         "Better short-term liquidity than last year."),
        ("Leverage & liquidity", "No new shares issued", (sh <= sh_prev * 1.005) if sh and sh_prev else None,
         "Diluted share count did not grow - no dilution to fund the business."),
        ("Operating efficiency", "Gross margin improving", cmp(gm, gm_prev),
         "Pricing power or lower input costs."),
        ("Operating efficiency", "Asset turnover improving", cmp(at, at_prev),
         "More revenue generated per unit of assets."),
    ]
    known = [s for s in signals if s[2] is not None]
    score = sum(1 for s in known if s[2])
    if not known:
        return None
    scaled = score if len(known) == 9 else round(score * 9 / len(known), 1)
    if scaled >= 7:
        verdict, tone = "Strong - fundamentals improving on most fronts", "good"
    elif scaled >= 4:
        verdict, tone = "Average - mixed fundamental momentum", "watch"
    else:
        verdict, tone = "Weak - fundamentals deteriorating", "weak"
    return {
        "year": y, "score": score, "max": len(known), "scaled": scaled, "verdict": verdict, "tone": tone,
        "signals": [{"group": grp, "name": n, "pass": ok, "explain": e} for grp, n, ok, e in signals],
        "note": "" if len(known) == 9 else f"{9 - len(known)} signal(s) could not be computed; score scaled to 9.",
    }


# --------------------------------------------------------------------- Altman

def altman(fd: FinancialData, y: int, market_cap: float | None = None) -> dict | None:
    g = lambda k: _g(fd, k, y)  # noqa: E731
    ta, tl = g("total_assets"), g("total_liabilities")
    tca, tcl = g("total_current_assets"), g("total_current_liabilities")
    re, ebit, sales, te = g("retained_earnings"), g("ebit"), g("revenue"), g("total_equity")
    if not ta or tl is None or None in (tca, tcl, ebit):
        return None
    x1 = (tca - tcl) / ta
    x2 = re / ta if re is not None else None
    x3 = ebit / ta
    out = {"year": y, "components": [], "models": []}
    comps = [
        ("X1", "Working capital / Total assets", x1, "Liquidity cushion relative to the size of the firm."),
        ("X2", "Retained earnings / Total assets", x2, "Cumulative profitability (and age) of the firm; "
         "large buybacks can push this negative even for healthy companies."),
        ("X3", "EBIT / Total assets", x3, "Operating productivity of the assets - the strongest predictor."),
    ]
    if x2 is None:
        out["note"] = "Retained earnings not available - add a 'Retained earnings' row to compute the Z-Score."
        out["components"] = [{"key": k, "name": n, "value": v, "explain": e} for k, n, v, e in comps]
        return out
    # Z'' (book equity, non-manufacturers / emerging markets)
    x4b = _div(te, tl)
    if x4b is not None:
        z2 = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4b
        zone = "safe" if z2 > 2.6 else "grey" if z2 >= 1.1 else "distress"
        out["models"].append({"name": "Z''-Score (book equity)", "value": z2, "zone": zone,
                              "thresholds": "Safe > 2.60 | Grey 1.10-2.60 | Distress < 1.10",
                              "formula": "6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*(Book equity / Total liabilities)"})
        comps.append(("X4''", "Book equity / Total liabilities", x4b, "Solvency cushion: how far assets can fall "
                      "before liabilities exceed them."))
    if market_cap and tl and sales is not None:
        x4m = market_cap / tl
        x5 = sales / ta
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4m + 1.0 * x5
        zone = "safe" if z > 2.99 else "grey" if z >= 1.81 else "distress"
        out["models"].insert(0, {"name": "Z-Score (original, market value)", "value": z, "zone": zone,
                                 "thresholds": "Safe > 2.99 | Grey 1.81-2.99 | Distress < 1.81",
                                 "formula": "1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*(Market cap / Total liabilities) + 1.0*(Sales / Total assets)"})
        comps += [("X4", "Market cap / Total liabilities", x4m, "Market's valuation cushion over obligations."),
                  ("X5", "Sales / Total assets", x5, "Asset turnover - ability to generate sales.")]
    out["components"] = [{"key": k, "name": n, "value": v, "explain": e} for k, n, v, e in comps]
    if out["models"]:
        primary = out["models"][0]
        out["zone"], out["value"], out["primary"] = primary["zone"], primary["value"], primary["name"]
    return out


# -------------------------------------------------------------------- Beneish

_BENEISH = (  # key, coefficient, name, red flag when high, explanation
    ("DSRI", 0.920, "Days sales in receivables index", "Receivables growing faster than sales can signal "
     "revenue booked before cash is collected."),
    ("GMI", 0.528, "Gross margin index", "Deteriorating gross margins create pressure to manipulate."),
    ("AQI", 0.404, "Asset quality index", "Rising share of 'soft' assets may mean costs are being capitalised."),
    ("SGI", 0.892, "Sales growth index", "High growth firms face more pressure to sustain growth."),
    ("DEPI", 0.115, "Depreciation index", "Slowing depreciation rates boost reported profit."),
    ("SGAI", -0.172, "SG&A expense index", "Rising overhead relative to sales."),
    ("TATA", 4.679, "Total accruals to total assets", "Profit not backed by cash flow - the strongest signal."),
    ("LVGI", -0.327, "Leverage index", "Rising leverage increases incentive to meet debt covenants."),
)


def beneish(fd: FinancialData, y: int) -> dict | None:
    p = y - 1
    if p not in fd.years:
        return None
    g = lambda k, yr: _g(fd, k, yr)  # noqa: E731
    rev, rev_p = g("revenue", y), g("revenue", p)
    if not rev or not rev_p:
        return None
    ar, ar_p = g("accounts_receivable", y), g("accounts_receivable", p)
    gp, gp_p = g("gross_profit", y), g("gross_profit", p)
    ta, ta_p = g("total_assets", y), g("total_assets", p)
    ca, ca_p = g("total_current_assets", y), g("total_current_assets", p)
    ppe, ppe_p = g("ppe", y), g("ppe", p)
    da, da_p = g("depreciation_amortization", y), g("depreciation_amortization", p)
    sga, sga_p = g("operating_expenses", y), g("operating_expenses", p)
    ni, ocf = g("net_income", y), g("operating_cash_flow", y)
    cl, cl_p = g("total_current_liabilities", y), g("total_current_liabilities", p)
    ltd, ltd_p = _debt(fd, y) or 0.0, _debt(fd, p) or 0.0

    def idx(cur, prev):
        return cur / prev if cur is not None and prev not in (None, 0) else None

    vals = {
        "DSRI": idx(_div(ar, rev), _div(ar_p, rev_p)),
        "GMI": idx(_div(gp_p, rev_p), _div(gp, rev)),
        "AQI": idx(1 - (ca + ppe) / ta if None not in (ca, ppe) and ta else None,
                   1 - (ca_p + ppe_p) / ta_p if None not in (ca_p, ppe_p) and ta_p else None),
        "SGI": rev / rev_p,
        "DEPI": idx(_div(da_p, (da_p or 0) + (ppe_p or 0)) if da_p is not None and ppe_p is not None else None,
                    _div(da, (da or 0) + (ppe or 0)) if da is not None and ppe is not None else None),
        "SGAI": idx(_div(sga, rev), _div(sga_p, rev_p)),
        "TATA": _div((ni - ocf) if None not in (ni, ocf) else None, ta),
        "LVGI": idx(_div((cl or 0) + ltd, ta) if cl is not None else None,
                    _div((cl_p or 0) + ltd_p, ta_p) if cl_p is not None else None),
    }
    essential = ("DSRI", "SGI", "TATA")
    if any(vals[k] is None for k in essential):
        return None
    defaulted = [k for k, v in vals.items() if v is None]
    m = -4.84
    comps = []
    for key, coef, name, explain in _BENEISH:
        v = vals[key] if vals[key] is not None else (0.0 if key == "TATA" else 1.0)
        m += coef * v
        comps.append({"key": key, "name": name, "value": vals[key], "coef": coef, "explain": explain,
                      "flag": vals[key] is not None and ((key == "TATA" and v > 0.031) or
                                                         (key in {"DSRI", "GMI", "AQI", "SGI"} and v > 1.25))})
    likely = m > -1.78
    return {
        "year": y, "value": m, "threshold": -1.78, "likely_manipulator": likely,
        "verdict": ("Above -1.78: profile resembles companies that manipulated earnings - investigate the flagged "
                    "components" if likely else "Below -1.78: no statistical red flag for earnings manipulation"),
        "tone": "weak" if likely else "good",
        "components": comps,
        "note": (f"{', '.join(defaulted)} not computable; set to neutral (1.0). " if defaulted else "")
                + "Operating expenses are used as the SG&A proxy.",
    }


def compute_scores(fd: FinancialData, market_cap: float | None = None) -> dict:
    """Latest-year scores plus Piotroski history."""
    years = fd.years
    if not years:
        return {}
    latest = years[-1]
    pio_hist = {}
    for y in years:
        r = piotroski(fd, y)
        if r:
            pio_hist[fy(y)] = r["scaled"]
    return {
        "piotroski": piotroski(fd, latest), "piotroski_history": pio_hist,
        "altman": altman(fd, latest, market_cap), "beneish": beneish(fd, latest),
    }
