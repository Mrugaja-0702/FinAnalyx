"""Financial ratio definitions and calculation.

Every metric returns a ``Value`` carrying the number *and* its status, so the
dashboard can tell apart "not enough data" (missing) from "mathematically
defined but meaningless" (n/m, e.g. ROE on negative equity).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .model import FinancialData, fy

LIQUIDITY, SOLVENCY, PROFITABILITY, EFFICIENCY, GROWTH, CASH = (
    "Liquidity", "Solvency", "Profitability", "Efficiency", "Growth", "Cash Flow & Supplementary")
CATEGORIES = (LIQUIDITY, SOLVENCY, PROFITABILITY, EFFICIENCY, GROWTH, CASH)

OK, MISSING, NM = "ok", "missing", "n/m"


@dataclass
class Value:
    value: float | None
    status: str = OK
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK and self.value is not None


def _missing(*names: str) -> Value:
    return Value(None, MISSING, "Missing: " + ", ".join(names))


@dataclass(frozen=True)
class MetricDef:
    key: str
    name: str
    category: str
    unit: str  # "x" | "%" | "days" | "abs"
    formula: str
    description: str
    higher_is_better: bool | None = True
    good: float | None = None  # threshold for "healthy"
    weak: float | None = None  # threshold for "weak"
    period: bool = False  # True for whole-period metrics (CAGR)

    def health(self, v: Value) -> str | None:
        if not v.ok or self.good is None or self.weak is None or self.higher_is_better is None:
            return None
        x = v.value
        if self.higher_is_better:
            return "good" if x >= self.good else "weak" if x < self.weak else "watch"
        return "good" if x <= self.good else "weak" if x > self.weak else "watch"


METRICS: tuple[MetricDef, ...] = (
    # Liquidity
    MetricDef("current_ratio", "Current Ratio", LIQUIDITY, "x", "Current Assets / Current Liabilities",
              "Ability to meet obligations due within a year from short-term assets.", True, 1.5, 1.0),
    MetricDef("quick_ratio", "Quick Ratio", LIQUIDITY, "x",
              "(Current Assets - Inventory) / Current Liabilities",
              "Liquidity excluding inventory, which may be slow to convert to cash.", True, 1.0, 0.7),
    # Solvency
    MetricDef("debt_to_equity", "Debt/Equity", SOLVENCY, "x", "Total Debt / Total Equity",
              "Financial leverage: borrowed capital per unit of shareholder capital. "
              "Total Debt = short-term borrowings + current portion of LT debt + long-term debt "
              "(or a reported 'Total debt' line). Lease liabilities are excluded unless reported as debt.",
              False, 1.0, 2.0),
    MetricDef("debt_ratio", "Debt Ratio", SOLVENCY, "x", "Total Debt / Total Assets",
              "Share of the asset base financed by interest-bearing debt.", False, 0.4, 0.6),
    MetricDef("interest_coverage", "Interest Coverage", SOLVENCY, "x", "EBIT / Interest Expense",
              "How many times operating profit covers interest cost.", True, 5.0, 2.0),
    # Profitability
    MetricDef("roe", "ROE", PROFITABILITY, "%", "Net Income / Average Total Equity",
              "Return generated on shareholders' capital.", True, 0.15, 0.08),
    MetricDef("roa", "ROA", PROFITABILITY, "%", "Net Income / Average Total Assets",
              "Return generated on the total asset base.", True, 0.07, 0.03),
    MetricDef("net_margin", "Net Profit Margin", PROFITABILITY, "%", "Net Income / Revenue",
              "Share of each unit of revenue retained as profit after all costs and taxes.", True, 0.10, 0.05),
    MetricDef("ebitda_margin", "EBITDA Margin", PROFITABILITY, "%", "(EBIT + D&A) / Revenue",
              "Operating profitability before depreciation, amortisation, interest and tax.", True, 0.20, 0.10),
    # Efficiency
    MetricDef("inventory_turnover", "Inventory Turnover", EFFICIENCY, "x", "COGS / Average Inventory",
              "How many times inventory is sold and replaced in a year.", True),
    MetricDef("receivable_turnover", "Receivable Turnover", EFFICIENCY, "x",
              "Revenue / Average Accounts Receivable",
              "How many times receivables are collected in a year (all revenue assumed on credit).", True),
    MetricDef("asset_turnover", "Asset Turnover", EFFICIENCY, "x", "Revenue / Average Total Assets",
              "Revenue generated per unit of assets.", True),
    # Growth (per-year)
    MetricDef("revenue_growth", "Revenue Growth (YoY)", GROWTH, "%", "Revenue_t / Revenue_t-1 - 1",
              "Year-over-year change in revenue.", True, 0.10, 0.0),
    MetricDef("profit_growth", "Net Income Growth (YoY)", GROWTH, "%", "Net Income_t / Net Income_t-1 - 1",
              "Year-over-year change in net income (n/m when the prior year is a loss).", True, 0.10, 0.0),
    MetricDef("asset_growth", "Asset Growth (YoY)", GROWTH, "%", "Total Assets_t / Total Assets_t-1 - 1",
              "Year-over-year change in the asset base.", None),
    # Growth (period)
    MetricDef("revenue_cagr", "Revenue CAGR", GROWTH, "%", "(Revenue_end / Revenue_start)^(1/years) - 1",
              "Compound annual revenue growth over the full period.", True, 0.10, 0.0, period=True),
    MetricDef("profit_cagr", "Profit CAGR", GROWTH, "%",
              "(Net Income_end / Net Income_start)^(1/years) - 1",
              "Compound annual net income growth; undefined if either endpoint is a loss.", True, 0.10, 0.0,
              period=True),
    MetricDef("asset_cagr", "Asset CAGR", GROWTH, "%",
              "(Total Assets_end / Total Assets_start)^(1/years) - 1",
              "Compound annual growth of the asset base.", None, period=True),
    # Supplementary - used heavily by the trend narrative
    MetricDef("gross_margin", "Gross Margin", CASH, "%", "Gross Profit / Revenue", "Profit after direct costs.", True),
    MetricDef("operating_margin", "EBIT Margin", CASH, "%", "EBIT / Revenue", "Operating profit margin.", True),
    MetricDef("opex_ratio", "Opex / Revenue", CASH, "%", "Operating Expenses / Revenue",
              "Operating cost intensity.", False),
    MetricDef("dso", "Days Sales Outstanding", CASH, "days", "365 / Receivable Turnover",
              "Average collection period.", False),
    MetricDef("dio", "Days Inventory Outstanding", CASH, "days", "365 / Inventory Turnover",
              "Average days inventory is held.", False),
    MetricDef("cash_conversion", "OCF / Net Income", CASH, "x", "Operating Cash Flow / Net Income",
              "Earnings quality: how much of reported profit arrives as cash (>1 is healthy).", True, 1.0, 0.8),
    MetricDef("fcf_margin", "FCF Margin", CASH, "%", "(Operating Cash Flow - Capex) / Revenue",
              "Free cash generated per unit of revenue.", True, 0.05, 0.0),
    MetricDef("capex_intensity", "Capex / Revenue", CASH, "%", "Capital Expenditure / Revenue",
              "Reinvestment intensity.", None),
    MetricDef("net_debt_to_ebitda", "Net Debt / EBITDA", CASH, "x",
              "(Total Debt - Cash - ST Investments) / EBITDA",
              "Years of EBITDA needed to repay net debt.", False, 2.0, 3.5),
    MetricDef("equity_multiplier", "Equity Multiplier", CASH, "x", "Average Total Assets / Average Total Equity",
              "Leverage component of the DuPont decomposition of ROE.", None),
)

METRIC_INDEX = {m.key: m for m in METRICS}

# Shown on the dashboard, in order.
HEADLINE = ("revenue_growth", "revenue_cagr", "ebitda_margin", "net_margin", "roe", "roa",
            "debt_to_equity", "interest_coverage", "current_ratio", "quick_ratio", "asset_turnover",
            "profit_cagr")


@dataclass
class RatioResults:
    years: list[int]
    basis: str
    per_year: dict[str, dict[int, Value]] = field(default_factory=dict)
    period: dict[str, Value] = field(default_factory=dict)

    def get(self, key: str, year: int | None = None) -> Value:
        if METRIC_INDEX[key].period:
            return self.period.get(key, Value(None, MISSING))
        return self.per_year.get(key, {}).get(year, Value(None, MISSING))

    def series(self, key: str) -> pd.Series:
        data = self.per_year.get(key, {})
        return pd.Series({y: v.value for y, v in data.items() if v.ok}, dtype=float)

    def latest(self, key: str) -> tuple[int | None, Value]:
        """Most recent year with a usable value (falls back to the latest status)."""
        if METRIC_INDEX[key].period:
            return None, self.get(key)
        for y in reversed(self.years):
            v = self.get(key, y)
            if v.ok:
                return y, v
        return self.years[-1], self.get(key, self.years[-1])

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({k: self.series(k) for k in self.per_year}).T.reindex(columns=self.years)


class RatioEngine:
    def __init__(self, fd: FinancialData, basis: str = "average"):
        if basis not in {"average", "ending"}:
            raise ValueError("basis must be 'average' or 'ending'")
        self.fd = fd
        self.basis = basis

    # -------------------------------------------------------------- helpers
    def _g(self, key: str, y: int) -> float | None:
        return self.fd.get(key, y)

    def _bal(self, key: str, y: int) -> tuple[float | None, str]:
        """Balance-sheet figure for a flow ratio: average of opening and closing, if possible."""
        cur = self._g(key, y)
        if cur is None:
            return None, ""
        if self.basis == "ending":
            return cur, ""
        prev = self._g(key, y - 1)
        if prev is None:
            return cur, "closing balance used (no prior year)"
        return (cur + prev) / 2, ""

    @staticmethod
    def _div(num: float | None, den: float | None, num_name: str, den_name: str,
             positive_den: bool = False, note: str = "") -> Value:
        missing = [n for n, v in ((num_name, num), (den_name, den)) if v is None]
        if missing:
            return _missing(*missing)
        if den == 0:
            return Value(None, NM, f"{den_name} is zero")
        if positive_den and den < 0:
            return Value(None, NM, f"{den_name} is negative")
        return Value(num / den, OK, note)

    # --------------------------------------------------------------- metrics
    def _year_metrics(self, y: int) -> dict[str, Value]:
        g, b, div = self._g, self._bal, self._div
        out: dict[str, Value] = {}
        rev, ni = g("revenue", y), g("net_income", y)
        tca, tcl, inv = g("total_current_assets", y), g("total_current_liabilities", y), g("inventory", y)
        debt, te, ta = g("total_debt_used", y), g("total_equity", y), g("total_assets", y)

        out["current_ratio"] = div(tca, tcl, "Current Assets", "Current Liabilities")
        if tca is not None:
            note = "" if inv is not None else "no inventory line found; assumed nil"
            out["quick_ratio"] = div(tca - (inv or 0.0), tcl, "Current Assets", "Current Liabilities", note=note)
        else:
            quick = [g(k, y) for k in ("cash", "short_term_investments", "accounts_receivable")]
            if quick[0] is not None and quick[2] is not None:
                out["quick_ratio"] = div(sum(q or 0.0 for q in quick), tcl, "Quick assets", "Current Liabilities",
                                         note="current assets unavailable; cash + ST investments + receivables used")
            else:
                out["quick_ratio"] = _missing("Current Assets")

        out["debt_to_equity"] = div(debt, te, "Total Debt", "Total Equity", positive_den=True)
        out["debt_ratio"] = div(debt, ta, "Total Debt", "Total Assets", positive_den=True)
        ebit, interest = g("ebit", y), g("interest_expense", y)
        if interest == 0 and ebit is not None:
            out["interest_coverage"] = Value(None, NM, "no interest expense")
        else:
            out["interest_coverage"] = div(ebit, interest, "EBIT", "Interest Expense")

        eq_avg, eq_note = b("total_equity", y)
        ta_avg, ta_note = b("total_assets", y)
        out["roe"] = div(ni, eq_avg, "Net Income", "Average Equity", positive_den=True, note=eq_note)
        out["roa"] = div(ni, ta_avg, "Net Income", "Average Total Assets", positive_den=True, note=ta_note)
        out["net_margin"] = div(ni, rev, "Net Income", "Revenue", positive_den=True)
        out["ebitda_margin"] = div(g("ebitda", y), rev, "EBITDA", "Revenue", positive_den=True)

        inv_avg, inv_note = b("inventory", y)
        cogs = g("cogs", y)
        if cogs is None and rev is not None and inv_avg is not None:
            out["inventory_turnover"] = div(rev, inv_avg, "Revenue", "Average Inventory", positive_den=True,
                                            note="COGS unavailable; revenue used (overstates turnover)")
        elif inv_avg == 0:
            out["inventory_turnover"] = Value(None, NM, "no inventory held")
        else:
            out["inventory_turnover"] = div(cogs, inv_avg, "COGS", "Average Inventory", positive_den=True,
                                            note=inv_note)
        ar_avg, ar_note = b("accounts_receivable", y)
        out["receivable_turnover"] = div(rev, ar_avg, "Revenue", "Average Receivables", positive_den=True,
                                         note=ar_note)
        out["asset_turnover"] = div(rev, ta_avg, "Revenue", "Average Total Assets", positive_den=True,
                                    note=ta_note)

        for key, item in (("revenue_growth", "revenue"), ("profit_growth", "net_income"),
                          ("asset_growth", "total_assets")):
            out[key] = self._yoy(item, y)

        out["gross_margin"] = div(g("gross_profit", y), rev, "Gross Profit", "Revenue", positive_den=True)
        out["operating_margin"] = div(ebit, rev, "EBIT", "Revenue", positive_den=True)
        out["opex_ratio"] = div(g("operating_expenses", y), rev, "Operating Expenses", "Revenue", positive_den=True)
        rt, it = out["receivable_turnover"], out["inventory_turnover"]
        out["dso"] = Value(365 / rt.value, OK, rt.note) if rt.ok and rt.value else Value(None, rt.status, rt.note)
        out["dio"] = Value(365 / it.value, OK, it.note) if it.ok and it.value else Value(None, it.status, it.note)
        ocf = g("operating_cash_flow", y)
        out["cash_conversion"] = div(ocf, ni, "Operating Cash Flow", "Net Income", positive_den=True)
        out["fcf_margin"] = div(g("free_cash_flow", y), rev, "Free Cash Flow", "Revenue", positive_den=True)
        out["capex_intensity"] = div(g("capex", y), rev, "Capex", "Revenue", positive_den=True)
        ebitda, nd = g("ebitda", y), g("net_debt", y)
        if ebitda is not None and ebitda <= 0 and nd is not None:
            out["net_debt_to_ebitda"] = Value(None, NM, "EBITDA is not positive")
        else:
            out["net_debt_to_ebitda"] = div(nd, ebitda, "Net Debt", "EBITDA")
        out["equity_multiplier"] = div(ta_avg, eq_avg, "Average Total Assets", "Average Equity", positive_den=True)
        return out

    def _yoy(self, item: str, y: int) -> Value:
        cur, prev = self._g(item, y), self._g(item, y - 1)
        if cur is None:
            return _missing(item.replace("_", " "))
        if prev is None:
            return Value(None, MISSING, f"no {fy(y - 1)} figure")
        if prev <= 0:
            return Value(None, NM, f"prior-year base is {'zero' if prev == 0 else 'negative'}")
        return Value(cur / prev - 1)

    def _cagr(self, item: str) -> Value:
        s = self.fd.series(item).dropna()
        if len(s) < 2:
            return Value(None, MISSING, "needs at least two years of data")
        y0, y1 = int(s.index[0]), int(s.index[-1])
        v0, v1 = float(s.iloc[0]), float(s.iloc[-1])
        n = y1 - y0
        span = f"{fy(y0)}-{fy(y1)}, {n} yr{'s' if n != 1 else ''}"
        if v0 <= 0:
            return Value(None, NM, f"starting value ({fy(y0)}) is {'zero' if v0 == 0 else 'negative'}; "
                                   f"CAGR is undefined ({span})")
        if v1 <= 0:
            return Value(None, NM, f"ending value ({fy(y1)}) is {'zero' if v1 == 0 else 'negative'}; "
                                   f"CAGR is undefined ({span})")
        note = span
        if (y0, y1) != (self.fd.years[0], self.fd.years[-1]):
            note += "; first/last years with data used"
        return Value((v1 / v0) ** (1 / n) - 1, OK, note)

    def run(self) -> RatioResults:
        res = RatioResults(self.fd.years, self.basis)
        for y in self.fd.years:
            for key, value in self._year_metrics(y).items():
                res.per_year.setdefault(key, {})[y] = value
        res.period["revenue_cagr"] = self._cagr("revenue")
        res.period["profit_cagr"] = self._cagr("net_income")
        res.period["asset_cagr"] = self._cagr("total_assets")
        return res


def compute_ratios(fd: FinancialData, basis: str = "average") -> RatioResults:
    return RatioEngine(fd, basis).run()


def fmt_value(metric: MetricDef | str, v: Value | float | None, signed: bool = False) -> str:
    """Human formatting: 1.71x, 21.3%, 48 days."""
    m = METRIC_INDEX[metric] if isinstance(metric, str) else metric
    if isinstance(v, Value):
        if v.status == NM:
            return "n/m"
        if not v.ok:
            return "n/a"
        x = v.value
    else:
        if v is None:
            return "n/a"
        x = v
    sign = "+" if signed and x > 0 else ""
    if m.unit == "%":
        return f"{sign}{x * 100:.1f}%"
    if m.unit == "days":
        return f"{sign}{x:.0f} days"
    if m.unit == "x":
        return f"{sign}{x:.2f}x"
    return f"{sign}{x:,.0f}"
