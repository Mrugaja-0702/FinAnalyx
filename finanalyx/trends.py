"""Narrative trend analysis.

A set of detectors look across the multi-year line items and ratios for
patterns that a static ratio table hides: costs outrunning revenue, margins
that peaked and are fading, ROE propped up by leverage, receivables growing
faster than sales, profits that do not convert to cash, one-off spikes, and
inflection points where a multi-year trend reversed.

Each finding is an ``Insight`` with a severity and an importance score; the
report shows them ranked so the most decision-relevant ones come first.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .model import FinancialData, fy, item_label
from .ratios import RatioResults

POSITIVE, NEUTRAL, WATCH, CONCERN = "positive", "neutral", "watch", "concern"
_SEVERITY_WEIGHT = {CONCERN: 1.35, WATCH: 1.15, POSITIVE: 1.0, NEUTRAL: 0.6}


@dataclass
class Insight:
    category: str
    severity: str
    title: str
    detail: str = ""
    years: list[int] = field(default_factory=list)
    score: float = 0.0


@dataclass
class TrendReport:
    insights: list[Insight]
    summary: list[str]
    yoy: list[tuple[int, str]]
    note: str = ""


# ------------------------------------------------------------------ formatting

def pct(x: float, signed: bool = True) -> str:
    return f"{'+' if signed and x > 0 else ''}{x * 100:.1f}%"


def bps(x: float) -> str:
    return f"{'+' if x > 0 else ''}{x * 10000:,.0f} bps"


def num(x: float) -> str:
    # Live data arrives in raw currency units; abbreviate so narratives stay readable.
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(x) >= div:
            return f"{x / div:,.2f}{suffix}"
    return f"{x:,.0f}" if abs(x) >= 100 or float(x).is_integer() else f"{x:,.1f}"


def mult(x: float) -> str:
    return f"{x:.2f}x"


def year_list(years: list[int]) -> str:
    """FY22, FY23, FY24 -> 'FY22-FY24'; FY22, FY24 -> 'FY22 and FY24'."""
    years = sorted(years)
    if not years:
        return ""
    if len(years) > 2 and years[-1] - years[0] == len(years) - 1:
        return f"{fy(years[0])}-{fy(years[-1])}"
    labels = [fy(y) for y in years]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


# ---------------------------------------------------------------- series tools

def growth(s: pd.Series) -> pd.Series:
    """YoY growth between consecutive fiscal years, only where the base is positive."""
    out = {}
    for y in s.index:
        if y - 1 in s.index and s[y - 1] > 0 and not (math.isnan(s[y]) or math.isnan(s[y - 1])):
            out[y] = s[y] / s[y - 1] - 1
    return pd.Series(out, dtype=float)


def cagr(s: pd.Series) -> float | None:
    s = s.dropna()
    if len(s) < 2 or s.iloc[0] <= 0 or s.iloc[-1] <= 0:
        return None
    return (s.iloc[-1] / s.iloc[0]) ** (1 / (s.index[-1] - s.index[0])) - 1


def inflection(s: pd.Series, min_move: float) -> tuple[int, str, float] | None:
    """Most recent turning point after which a multi-year trend reversed.

    Returns (turning year, "peak" | "trough", move since the turn) when the
    series moved the same way for at least two years and then reversed.
    """
    s = s.dropna()
    if len(s) < 4:
        return None
    years = list(s.index)
    diffs = np.diff(s.values)
    signs = [0 if abs(d) < min_move else int(np.sign(d)) for d in diffs]
    for k in range(len(signs) - 1, 1, -1):
        new = signs[k]
        if new == 0:
            continue
        # The new direction must persist to the end; the prior run must last two moves.
        if any(sg == -new for sg in signs[k:]):
            continue
        prior = signs[k - 1]
        if prior != -new:
            continue
        run = 0
        for sg in reversed(signs[:k]):
            if sg == prior:
                run += 1
            else:
                break
        if run >= 2:
            turn_year = years[k]
            return turn_year, "peak" if prior > 0 else "trough", float(s.iloc[-1] - s[turn_year])
    return None


def monotonic(s: pd.Series, min_move: float = 0.0) -> int:
    """+1 if every move is up (by more than min_move), -1 if every move is down, else 0."""
    d = np.diff(s.dropna().values)
    if len(d) < 2:
        return 0
    if all(x > min_move for x in d):
        return 1
    if all(x < -min_move for x in d):
        return -1
    return 0


# ------------------------------------------------------------------- analyzer

class TrendAnalyzer:
    def __init__(self, fd: FinancialData, rr: RatioResults):
        self.fd, self.rr = fd, rr
        self.latest = fd.years[-1]
        self.insights: list[Insight] = []

    def s(self, key: str) -> pd.Series:
        return self.fd.series(key).dropna()

    def r(self, key: str) -> pd.Series:
        return self.rr.series(key).dropna()

    def add(self, category: str, severity: str, title: str, detail: str = "", years: list[int] | None = None,
            weight: float = 5.0, magnitude: float = 0.0) -> None:
        years = sorted(years or [])
        score = weight * _SEVERITY_WEIGHT[severity] + min(magnitude, 3.0)
        if years and years[-1] == self.latest:
            score += 2.0
        self.insights.append(Insight(category, severity, title, detail, years, round(score, 2)))

    # --------------------------------------------------------------- detectors
    def revenue(self) -> None:
        rev = self.s("revenue")
        g = growth(rev)
        if len(g) == 0:
            return
        c = cagr(rev)
        span = f"{fy(rev.index[0])} to {fy(rev.index[-1])}"
        detail = "YoY: " + ", ".join(f"{fy(y)} {pct(v)}" for y, v in g.items())
        declines = [y for y, v in g.items() if v < 0]
        if not declines and len(g) >= 2:
            self.add("Growth", POSITIVE,
                     f"Revenue grew in every year, from {num(rev.iloc[0])} to {num(rev.iloc[-1])} "
                     f"({pct(c, False)} CAGR, {span}).", detail, list(g.index), weight=8, magnitude=c * 10)
        elif len(declines) == len(g) and len(g) >= 2:
            self.add("Growth", CONCERN, f"Revenue declined in every year ({pct(c, False) if c is not None else 'n/m'} "
                     f"CAGR, {span}).", detail, list(g.index), weight=9, magnitude=2)
        else:
            last = g.index[-1]
            if g[last] < 0:
                streak = 0
                for v in reversed(g.values[:-1]):
                    if v > 0:
                        streak += 1
                    else:
                        break
                tail = f", ending a {streak}-year growth streak" if streak >= 2 else ""
                self.add("Growth", CONCERN, f"Revenue fell {pct(abs(g[last]), False)} in {fy(last)}{tail}.",
                         detail, [last], weight=9, magnitude=abs(g[last]) * 10)
            for y in declines:
                if y == last:
                    continue
                after = g[g.index > y]
                if len(after) and (after > 0).all():
                    self.add("Growth", NEUTRAL,
                             f"Revenue dipped {pct(abs(g[y]), False)} in {fy(y)} but recovered, growing "
                             f"{pct(after.iloc[0])} in {fy(after.index[0])}"
                             + (" and every year since." if len(after) > 1 else "."),
                             detail, [y, *after.index], weight=6)
        # Acceleration / deceleration over the last three growth observations.
        if len(g) >= 3:
            last3 = g.iloc[-3:]
            d = np.diff(last3.values)
            path = " -> ".join(pct(v) for v in last3.values)
            if all(x < -0.02 for x in d):
                sev = WATCH if last3.iloc[-1] > 0 else CONCERN
                self.add("Growth", sev, f"Revenue growth is decelerating: {path} over {year_list(list(last3.index))}.",
                         "Each year's growth rate was lower than the year before - an inflection in the "
                         "top-line trajectory even though revenue may still be rising.",
                         list(last3.index), weight=8, magnitude=abs(d.sum()) * 10)
            elif all(x > 0.02 for x in d):
                self.add("Growth", POSITIVE, f"Revenue growth is accelerating: {path} over {year_list(list(last3.index))}.",
                         "", list(last3.index), weight=7, magnitude=d.sum() * 10)
        if len(g) >= 3 and g.std() > 0.15:
            self.add("Growth", WATCH, f"Revenue growth is volatile (standard deviation {g.std() * 100:.0f} pp "
                     f"across years).", detail, list(g.index), weight=4)

    def costs(self) -> None:
        rev = self.s("revenue")
        rg = growth(rev)
        consistent_growth = len(rg) >= 2 and (rg > 0).all()
        for key, name, margin_key, margin_name in (
            ("operating_expenses", "operating expenses", "operating_margin", "EBIT margin"),
            ("cogs", "cost of sales", "gross_margin", "gross margin"),
        ):
            cg = growth(self.s(key))
            common = [y for y in rg.index if y in cg.index]
            if not common:
                continue
            faster = [y for y in common if cg[y] - rg[y] > 0.01]
            margin = self.r(margin_key)
            if faster:
                lead = f"Revenue increased consistently, but {name} grew faster than revenue" if consistent_growth \
                    else f"{name.capitalize()} grew faster than revenue"
                title = f"{lead} in {year_list(faster)}"
                parts = [f"{fy(y)}: {name} {pct(cg[y])} vs revenue {pct(rg[y])}" for y in faster]
                m_change = None
                if faster[-1] in margin.index and faster[0] - 1 in margin.index:
                    m_change = margin[faster[-1]] - margin[faster[0] - 1]
                    parts.append(f"{margin_name} moved {bps(m_change)} over that span "
                                 f"({pct(margin[faster[0] - 1], False)} -> {pct(margin[faster[-1]], False)})")
                recent = faster[-1] == self.latest
                consecutive_tail = recent and len(faster) >= 2 and faster[-2] == faster[-1] - 1
                if recent and m_change is not None and m_change > 0:
                    # Costs outran revenue, yet the margin still widened (e.g. via gross margin): worth
                    # watching, not alarming.
                    sev = WATCH
                    title += f", though {margin_name} still widened ({bps(m_change)})."
                elif recent:
                    sev = CONCERN if (m_change is not None and m_change < -0.01) or \
                        (consecutive_tail and m_change is None) else WATCH
                    title += " - squeezing " + margin_name + "." if m_change is not None and m_change < 0 else "."
                else:
                    sev = NEUTRAL
                    title += f", but cost growth has stayed below revenue growth since {fy(faster[-1] + 1)}."
                self.add("Cost structure", sev, title, "; ".join(parts) + ".", faster,
                         weight=8 if key == "operating_expenses" else 7,
                         magnitude=abs(m_change or 0) * 100)
            elif len(common) >= 2:
                c_rev, c_cost = cagr(rev[rev.index >= common[0] - 1]), cagr(self.s(key))
                if c_rev is not None and c_cost is not None and c_rev - c_cost > 0.01:
                    self.add("Cost structure", POSITIVE,
                             f"Positive operating leverage: {name} grew more slowly than revenue every year "
                             f"({pct(c_cost, False)} vs {pct(c_rev, False)} CAGR).",
                             f"{margin_name.capitalize()}: {pct(margin.iloc[0], False)} -> {pct(margin.iloc[-1], False)}."
                             if len(margin) >= 2 else "", common, weight=6, magnitude=(c_rev - c_cost) * 20)

    def margins(self) -> None:
        for key, name, weight in (("ebitda_margin", "EBITDA margin", 7), ("net_margin", "Net profit margin", 6),
                                  ("gross_margin", "Gross margin", 5)):
            m = self.r(key)
            if len(m) < 3:
                continue
            change = m.iloc[-1] - m.iloc[0]
            path = " -> ".join(f"{v * 100:.1f}%" for v in m.values)
            detail = f"{year_list(list(m.index))}: {path}."
            turn = inflection(m, 0.002)
            peak_y = m.idxmax()
            mono = monotonic(m, 0.0005)
            if mono == 1 and change >= 0.01:
                self.add("Profitability", POSITIVE, f"{name} expanded every year, up {bps(change).lstrip('+')} to "
                         f"{pct(m.iloc[-1], False)}.", detail, list(m.index), weight, abs(change) * 100)
            elif mono == -1 and change <= -0.01:
                self.add("Profitability", CONCERN, f"{name} contracted every year, down {bps(-change).lstrip('+')} "
                         f"to {pct(m.iloc[-1], False)}.", detail, list(m.index), weight + 1, abs(change) * 100)
            elif turn and turn[1] == "peak" and turn[2] <= -0.01:
                sev = CONCERN if turn[2] <= -0.03 else WATCH
                self.add("Profitability", sev,
                         f"{name} peaked at {pct(m[turn[0]], False)} in {fy(turn[0])} and has contracted "
                         f"{bps(-turn[2]).lstrip('+')} since, to {pct(m.iloc[-1], False)} (inflection point).",
                         detail, [turn[0], m.index[-1]], weight + 1, abs(turn[2]) * 100)
            elif turn and turn[1] == "trough" and turn[2] >= 0.01:
                self.add("Profitability", POSITIVE,
                         f"{name} bottomed at {pct(m[turn[0]], False)} in {fy(turn[0])} and has recovered "
                         f"{bps(turn[2])} since, to {pct(m.iloc[-1], False)} (inflection point).",
                         detail, [turn[0], m.index[-1]], weight, abs(turn[2]) * 100)
            elif peak_y not in (m.index[0], m.index[-1]) and m[peak_y] - m.iloc[-1] >= 0.015:
                drop = m[peak_y] - m.iloc[-1]
                self.add("Profitability", WATCH, f"{name} is {bps(drop).lstrip('+')} below its {fy(peak_y)} peak of "
                         f"{pct(m[peak_y], False)}.", detail, [peak_y, m.index[-1]], weight, drop * 100)
            elif abs(change) >= 0.01:
                sev = POSITIVE if change > 0 else WATCH
                self.add("Profitability", sev, f"{name} {'widened' if change > 0 else 'narrowed'} by "
                         f"{bps(abs(change)).lstrip('+')} over the period, to {pct(m.iloc[-1], False)}.",
                         detail, [m.index[0], m.index[-1]], weight - 1, abs(change) * 100)
            elif key == "ebitda_margin":
                self.add("Profitability", NEUTRAL, f"{name} has been stable at {pct(m.min(), False)}-"
                         f"{pct(m.max(), False)}.", detail, list(m.index), 3)

    def profit_vs_revenue(self) -> None:
        rc, pc = self.rr.get("revenue_cagr"), self.rr.get("profit_cagr")
        ni = self.s("net_income")
        if rc.ok and pc.ok:
            diff = pc.value - rc.value
            if diff > 0.03:
                self.add("Profitability", POSITIVE,
                         f"Net income compounded faster than revenue ({pct(pc.value, False)} vs {pct(rc.value, False)} CAGR) "
                         "- growth has been margin-accretive.", pc.note, [], weight=6, magnitude=diff * 20)
            elif diff < -0.03:
                self.add("Profitability", WATCH,
                         f"Profit growth lagged revenue growth ({pct(pc.value, False)} vs {pct(rc.value, False)} CAGR) "
                         "- the business is growing at lower margins.", pc.note, [], weight=7, magnitude=-diff * 20)
        elif len(ni) >= 2:
            if ni.iloc[-1] < 0 <= ni.iloc[0]:
                self.add("Profitability", CONCERN, f"The company swung to a net loss of {num(ni.iloc[-1])} in "
                         f"{fy(ni.index[-1])}.", "", [ni.index[-1]], weight=9, magnitude=3)
            elif ni.iloc[0] < 0 < ni.iloc[-1]:
                self.add("Profitability", POSITIVE, f"The company turned profitable, from a loss of {num(ni.iloc[0])} "
                         f"in {fy(ni.index[0])} to a profit of {num(ni.iloc[-1])} in {fy(ni.index[-1])}.", "",
                         [ni.index[0], ni.index[-1]], weight=8)

        rg, ng, eg = growth(self.s("revenue")), growth(ni), growth(self.s("ebit"))
        diverge = [y for y in rg.index if y in ng.index and rg[y] > 0.02 and ng[y] < -0.05]
        if diverge:
            parts = [f"{fy(y)}: revenue {pct(rg[y])}, net income {pct(ng[y])}" for y in diverge]
            self.add("Profitability", WATCH if diverge[-1] != self.latest else CONCERN,
                     f"Net income fell despite higher revenue in {year_list(diverge)}.", "; ".join(parts) + ".",
                     diverge, weight=7, magnitude=max(abs(ng[y]) for y in diverge) * 5)
        below = [y for y in ng.index if y in eg.index and abs(ng[y] - eg[y]) > 0.20 and abs(ng[y]) > 0.10]
        for y in below:
            direction = "outpaced" if ng[y] > eg[y] else "fell well short of"
            self.add("Earnings quality", WATCH,
                     f"Net income growth in {fy(y)} ({pct(ng[y])}) {direction} operating profit growth ({pct(eg[y])}).",
                     "The gap comes from below-the-line items - interest, tax rate, other income or one-off "
                     "gains/charges - rather than the core business.", [y], weight=5, magnitude=abs(ng[y] - eg[y]) * 3)

    def returns(self) -> None:
        roe = self.r("roe")
        # Prefer years computed on average balances so the comparison is like-for-like.
        consistent = [y for y in roe.index if not self.rr.get("roe", y).note]
        if len(consistent) >= 2:
            roe = roe[consistent]
        if len(roe) < 2:
            return
        y0, y1 = roe.index[0], roe.index[-1]
        comps = {}
        for key, label in (("net_margin", "net margin"), ("asset_turnover", "asset turnover"),
                           ("equity_multiplier", "leverage")):
            a, b = self.rr.get(key, y0), self.rr.get(key, y1)
            if a.ok and b.ok and a.value > 0 and b.value > 0:
                comps[label] = (a.value, b.value, math.log(b.value / a.value))
        change = roe[y1] - roe[y0]
        detail = f"ROE {fy(y0)} {pct(roe[y0], False)} -> {fy(y1)} {pct(roe[y1], False)}."
        if abs(change) < 0.01:
            self.add("Returns", NEUTRAL, f"ROE has held steady around {pct(roe.mean(), False)}.", detail,
                     [y0, y1], weight=3)
            return
        up = change > 0
        title = f"ROE {'rose' if up else 'fell'} from {pct(roe[y0], False)} to {pct(roe[y1], False)}"
        sev = POSITIVE if up else WATCH
        if len(comps) == 3 and roe[y0] > 0 and roe[y1] > 0:
            driver = max(comps, key=lambda k: abs(comps[k][2]) if (comps[k][2] > 0) == up else 0)
            a, b, _ = comps[driver]
            fmt = (lambda v: pct(v, False)) if driver == "net margin" else mult
            measure = "equity multiplier " if driver == "leverage" else ""
            title += f", driven mainly by {'higher' if up else 'lower'} {driver} ({measure}{fmt(a)} -> {fmt(b)})"
            if up and driver == "leverage":
                sev = WATCH
                title += " rather than better operating performance"
            detail += " DuPont: ROE = Net margin x Asset turnover x Equity multiplier. " + "; ".join(
                f"{'equity multiplier' if k == 'leverage' else k}: {(pct(a, False) if k == 'net margin' else mult(a))} -> "
                f"{(pct(b, False) if k == 'net margin' else mult(b))}" for k, (a, b, _) in comps.items()) + "."
        if not up and abs(change) >= 0.05:
            sev = CONCERN
        turn = inflection(self.r("roe"), 0.005)
        if turn:
            detail += f" ROE {'peaked' if turn[1] == 'peak' else 'bottomed'} in {fy(turn[0])}."
        self.add("Returns", sev, title + ".", detail, [y0, y1], weight=7, magnitude=abs(change) * 30)

    def working_capital(self) -> None:
        for bal_key, flow_key, days_key, name, flow_name, days_name in (
            ("accounts_receivable", "revenue", "dso", "Receivables", "revenue", "DSO"),
            ("inventory", "cogs", "dio", "Inventory", "cost of sales", "DIO"),
        ):
            bg, fg = growth(self.s(bal_key)), growth(self.s(flow_key))
            common = [y for y in bg.index if y in fg.index]
            faster = [y for y in common if bg[y] - fg[y] > 0.05]
            days = self.r(days_key)
            if faster and faster[-1] >= self.latest - 1:
                parts = [f"{fy(y)}: {name.lower()} {pct(bg[y])} vs {flow_name} {pct(fg[y])}" for y in faster]
                d_txt, d_change = "", 0.0
                if len(days) >= 2:
                    start = days[faster[0] - 1] if faster[0] - 1 in days.index else days.iloc[0]
                    d_change = days.iloc[-1] - start
                    if d_change >= 1:
                        d_txt = f", stretching {days_name} from {start:.0f} to {days.iloc[-1]:.0f} days"
                    else:
                        d_txt = f", though {days_name} is no longer than before ({start:.0f} -> {days.iloc[-1]:.0f} days)"
                meaning = ("collections are slowing or credit terms have loosened" if bal_key == "accounts_receivable"
                           else "stock is building up ahead of demand - a possible sign of slowing sales or obsolescence")
                if d_change < 1:
                    sev = NEUTRAL
                    meaning = "a build-up in some years that has since been absorbed"
                else:
                    sev = CONCERN if d_change >= 10 or len(faster) >= 2 else WATCH
                self.add("Working capital", sev, f"{name} grew faster than {flow_name} in {year_list(faster)}{d_txt}.",
                         "; ".join(parts) + f". This suggests {meaning}.", faster, weight=7, magnitude=d_change / 5)
            elif len(days) >= 3:
                d_change = days.iloc[-1] - days.iloc[0]
                if d_change <= -5:
                    self.add("Working capital", POSITIVE, f"{days_name} improved from {days.iloc[0]:.0f} to "
                             f"{days.iloc[-1]:.0f} days over {year_list(list(days.index))}.", "", list(days.index),
                             weight=5, magnitude=-d_change / 5)
                elif d_change >= 10:
                    self.add("Working capital", WATCH, f"{days_name} lengthened from {days.iloc[0]:.0f} to "
                             f"{days.iloc[-1]:.0f} days over {year_list(list(days.index))}.", "", list(days.index),
                             weight=6, magnitude=d_change / 5)

    def leverage(self) -> None:
        de = self.r("debt_to_equity")
        debt, capex = self.s("total_debt_used"), self.s("capex")
        ta = self.s("total_assets")
        dg = growth(debt)
        for y, v in dg.items():
            jump = debt[y] - debt[y - 1]
            if v > 0.30 and y in ta.index and jump > 0.05 * ta[y]:
                ctx = ""
                if y in capex.index and y - 1 in capex.index and capex[y] > capex[y - 1] * 1.3:
                    ctx = f", alongside a capex step-up to {num(capex[y])} (from {num(capex[y - 1])}) - a debt-funded expansion"
                self.add("Leverage", WATCH, f"Borrowings jumped {pct(v, False)} in {fy(y)}, from {num(debt[y - 1])} "
                         f"to {num(debt[y])}{ctx}.", "", [y], weight=6, magnitude=v * 2)
        if len(de) >= 2:
            a, b = de.iloc[0], de.iloc[-1]
            detail = " -> ".join(f"{fy(y)} {mult(v)}" for y, v in de.items())
            if b - a > 0.2:
                sev = CONCERN if b > 2 or (a <= 1 < b) else WATCH
                cross = " - now above 1.0x" if a <= 1 < b else ""
                self.add("Leverage", sev, f"Leverage is rising: Debt/Equity went from {mult(a)} to {mult(b)}{cross}.",
                         detail, [de.index[0], de.index[-1]], weight=7, magnitude=(b - a) * 2)
            elif a - b > 0.2:
                self.add("Leverage", POSITIVE, f"The balance sheet de-levered: Debt/Equity fell from {mult(a)} to {mult(b)}.",
                         detail, [de.index[0], de.index[-1]], weight=6, magnitude=(a - b) * 2)
        ic = self.r("interest_coverage")
        if len(ic) >= 2:
            peak_y = ic.idxmax()
            last = ic.iloc[-1]
            if last < 3 and ic.max() >= 3:
                self.add("Leverage", CONCERN if last < 2 else WATCH,
                         f"Interest coverage fell to {mult(last)} in {fy(ic.index[-1])} from {mult(ic[peak_y])} in "
                         f"{fy(peak_y)} - thin headroom if earnings soften.",
                         " -> ".join(f"{fy(y)} {mult(v)}" for y, v in ic.items()), [peak_y, ic.index[-1]],
                         weight=8, magnitude=3)
            elif peak_y != ic.index[-1] and last < 0.6 * ic[peak_y]:
                self.add("Leverage", WATCH, f"Interest coverage has fallen from {mult(ic[peak_y])} ({fy(peak_y)}) to "
                         f"{mult(last)} - still adequate but deteriorating.",
                         " -> ".join(f"{fy(y)} {mult(v)}" for y, v in ic.items()), [peak_y, ic.index[-1]],
                         weight=6, magnitude=2)
        nde = self.r("net_debt_to_ebitda")
        if len(nde) and nde.iloc[-1] > 3:
            self.add("Leverage", CONCERN, f"Net debt is {mult(nde.iloc[-1])} EBITDA in {fy(nde.index[-1])}, above the "
                     "3x level lenders typically treat as stretched.", "", [nde.index[-1]], weight=7, magnitude=2)

    def liquidity(self) -> None:
        cr = self.r("current_ratio")
        if len(cr) < 2:
            return
        a, b = cr.iloc[0], cr.iloc[-1]
        detail = " -> ".join(f"{fy(y)} {mult(v)}" for y, v in cr.items())
        if b < 1 <= a:
            self.add("Liquidity", CONCERN, f"Current ratio slipped below 1.0x (to {mult(b)}): current liabilities now "
                     "exceed current assets.", detail, [cr.index[-1]], weight=8, magnitude=3)
        elif b < 1.5 <= a:
            self.add("Liquidity", WATCH, f"Current ratio weakened from {mult(a)} to {mult(b)}, below the 1.5x comfort level.",
                     detail, [cr.index[0], cr.index[-1]], weight=6, magnitude=(a - b) * 3)
        elif a - b > 0.3:
            self.add("Liquidity", WATCH, f"Liquidity is tightening: current ratio down from {mult(a)} to {mult(b)}.",
                     detail, [cr.index[0], cr.index[-1]], weight=5, magnitude=(a - b) * 3)
        elif b - a > 0.3:
            self.add("Liquidity", POSITIVE, f"Liquidity strengthened: current ratio up from {mult(a)} to {mult(b)}.",
                     detail, [cr.index[0], cr.index[-1]], weight=4, magnitude=(b - a) * 2)

    def capital_efficiency(self) -> None:
        ac, rc = self.rr.get("asset_cagr"), self.rr.get("revenue_cagr")
        at = self.r("asset_turnover")
        if not (ac.ok and rc.ok) or len(at) < 2:
            return
        diff = ac.value - rc.value
        tail = f"asset turnover {mult(at.iloc[0])} -> {mult(at.iloc[-1])}"
        if diff > 0.03:
            self.add("Efficiency", WATCH, f"The asset base grew faster than revenue ({pct(ac.value, False)} vs "
                     f"{pct(rc.value, False)} CAGR); {tail}.",
                     "Recent investment has not yet produced proportionate revenue - watch for returns on new capacity.",
                     [at.index[0], at.index[-1]], weight=5, magnitude=diff * 20)
        elif diff < -0.03:
            self.add("Efficiency", POSITIVE, f"Revenue outgrew the asset base ({pct(rc.value, False)} vs "
                     f"{pct(ac.value, False)} CAGR); {tail}.", "", [at.index[0], at.index[-1]], weight=4,
                     magnitude=-diff * 20)

    def cash_flow(self) -> None:
        cc = self.r("cash_conversion")
        ni, ocf = self.s("net_income"), self.s("operating_cash_flow")
        if len(cc) >= 2:
            weak = [y for y, v in cc.items() if v < 0.8]
            detail = "OCF / Net income: " + ", ".join(f"{fy(y)} {mult(v)}" for y, v in cc.items())
            if cc.iloc[-1] < 0.8 and cc.iloc[:-1].mean() >= 1.0:
                self.add("Earnings quality", CONCERN, f"Cash conversion dropped in {fy(cc.index[-1])}: operating cash "
                         f"flow covered only {mult(cc.iloc[-1])} of net income versus a prior average of "
                         f"{mult(cc.iloc[:-1].mean())}.", detail, [cc.index[-1]], weight=8, magnitude=3)
            elif len(weak) >= max(2, len(cc) // 2):
                self.add("Earnings quality", CONCERN, f"Operating cash flow trailed net income in {year_list(weak)} - "
                         "reported profits are not consistently converting to cash.", detail, weak, weight=7,
                         magnitude=2)
            elif not weak and cc.min() >= 1.0:
                self.add("Earnings quality", POSITIVE, f"Earnings are cash-backed: operating cash flow exceeded net "
                         f"income in every year (avg {mult(cc.mean())}).", detail, list(cc.index), weight=5)
        ng, og = growth(ni), growth(ocf)
        split = [y for y in ng.index if y in og.index and ng[y] > 0.03 and og[y] < -0.03]
        if split:
            parts = [f"{fy(y)}: net income {pct(ng[y])}, operating cash flow {pct(og[y])}" for y in split]
            self.add("Earnings quality", CONCERN if split[-1] == self.latest else WATCH,
                     f"Profit and cash flow diverged in {year_list(split)}: net income rose while operating cash flow fell.",
                     "; ".join(parts) + ". Typically driven by working-capital build-up (receivables, inventory).",
                     split, weight=7, magnitude=2)
        fcf = self.s("free_cash_flow")
        neg = [y for y, v in fcf.items() if v < 0]
        if neg:
            capex_int = self.r("capex_intensity")
            ctx = ""
            if neg[-1] in capex_int.index and len(capex_int) >= 2:
                ctx = f" Capex was {pct(capex_int[neg[-1]], False)} of revenue that year (period average " \
                      f"{pct(capex_int.mean(), False)})."
            self.add("Cash flow", WATCH if neg[-1] == self.latest else NEUTRAL,
                     f"Free cash flow was negative in {year_list(neg)}.", ctx.strip(), neg, weight=6, magnitude=1)
        elif len(fcf) >= 3:
            self.add("Cash flow", POSITIVE, f"Free cash flow was positive in every year (cumulative {num(fcf.sum())}).",
                     "", list(fcf.index), weight=4)
        div = self.s("dividends_paid")
        over = [y for y in div.index if y in fcf.index and div[y] > 0 and div[y] > fcf[y]]
        if over:
            self.add("Cash flow", WATCH, f"Dividends exceeded free cash flow in {year_list(over)} - payouts were "
                     "funded from cash reserves or borrowing.", "", over, weight=5, magnitude=1)

    def anomalies(self) -> None:
        keys = ("net_income", "operating_cash_flow", "capex", "cash", "total_assets", "operating_expenses",
                "accounts_receivable", "inventory", "ebit")
        for key in keys:
            g = growth(self.s(key))
            if len(g) < 2:
                continue
            years = list(g.index)
            flagged = set()
            for y0, y1 in zip(years, years[1:]):
                if y1 != y0 + 1:
                    continue
                a, b = g[y0], g[y1]
                if (a > 0.40 and b < -0.25) or (a < -0.30 and b > 0.40):
                    self.add("Anomaly", WATCH,
                             f"{item_label(key)} {'spiked' if a > 0 else 'dropped'} {pct(abs(a), False)} in {fy(y0)} "
                             f"and reversed ({pct(b)}) in {fy(y1)} - likely a one-off item.",
                             "Exclude one-offs when judging the underlying trend.", [y0, y1], weight=5,
                             magnitude=min(abs(a), 2))
                    flagged.update({y0, y1})
            if len(g) >= 4:
                med = g.median()
                mad = (g - med).abs().median() or 0.02
                for y, v in g.items():
                    if y in flagged:
                        continue
                    if abs(v - med) > max(4 * mad, 0.35):
                        self.add("Anomaly", NEUTRAL,
                                 f"Unusual move: {item_label(key)} changed {pct(v)} in {fy(y)} against a typical "
                                 f"{pct(med)} a year.", "", [y], weight=3, magnitude=min(abs(v - med), 2))

    # ------------------------------------------------------------------ output
    def yoy_summaries(self) -> list[tuple[int, str]]:
        out = []
        series = {k: self.s(k) for k in ("revenue", "ebitda", "net_income", "operating_expenses", "operating_cash_flow")}
        margins = {k: self.r(k) for k in ("ebitda_margin", "net_margin")}
        for y in self.fd.years[1:]:
            bits = []
            for key, label in (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("net_income", "Net income"),
                               ("operating_expenses", "Opex"), ("operating_cash_flow", "Operating cash flow")):
                s = series[key]
                if y in s.index and y - 1 in s.index:
                    if s[y - 1] > 0:
                        bits.append(f"{label} {pct(s[y] / s[y - 1] - 1)}")
                    else:
                        bits.append(f"{label} {num(s[y - 1])} -> {num(s[y])}")
            for key, label in (("ebitda_margin", "EBITDA margin"), ("net_margin", "net margin")):
                m = margins[key]
                if y in m.index and y - 1 in m.index:
                    bits.append(f"{label} {bps(m[y] - m[y - 1])} to {pct(m[y], False)}")
            if bits:
                out.append((y, "; ".join(bits) + "."))
        return out

    def executive_summary(self, ranked: list[Insight]) -> list[str]:
        lines = []
        rc = self.rr.get("revenue_cagr")
        span = f"{fy(self.fd.years[0])}-{fy(self.fd.years[-1])}"
        y, em = self.rr.latest("ebitda_margin")
        _, roe = self.rr.latest("roe")
        _, de = self.rr.latest("debt_to_equity")
        facts = []
        if rc.ok:
            facts.append(f"revenue compounded at {pct(rc.value, False)} a year")
        if em.ok:
            facts.append(f"EBITDA margin {pct(em.value, False)} in {fy(y)}")
        if roe.ok:
            facts.append(f"ROE {pct(roe.value, False)}")
        if de.ok:
            facts.append(f"Debt/Equity {mult(de.value)}")
        if facts:
            lines.append(f"Over {span}: " + ", ".join(facts) + ".")
        pos = [i for i in ranked if i.severity == POSITIVE]
        neg = [i for i in ranked if i.severity in (CONCERN, WATCH)]
        lines += [f"Strength: {i.title}" for i in pos[:2]]
        lines += [f"Watch-point: {i.title}" for i in neg[:3]]
        concerns = sum(i.severity == CONCERN for i in ranked)
        if concerns == 0 and len(pos) >= len(neg):
            lines.append("Overall: financial trajectory is healthy, with no material red flags detected.")
        elif concerns >= 3:
            lines.append(f"Overall: {concerns} material concerns flagged - the recent trend warrants close review.")
        else:
            lines.append("Overall: mixed picture - solid fundamentals with specific areas to monitor.")
        return lines

    def run(self) -> TrendReport:
        n = len(self.fd.years)
        if n < 2:
            return TrendReport([], [], [], "Trend analysis needs at least two fiscal years of data; "
                                               f"only {n} found.")
        for detector in (self.revenue, self.costs, self.margins, self.profit_vs_revenue, self.returns,
                         self.working_capital, self.leverage, self.liquidity, self.capital_efficiency,
                         self.cash_flow, self.anomalies):
            try:
                detector()
            except Exception as exc:  # one faulty detector must not sink the report
                self.insights.append(Insight("Internal", NEUTRAL, f"{detector.__name__} analysis skipped: {exc}",
                                             score=-1))
        ranked = sorted(self.insights, key=lambda i: -i.score)
        note = ""
        if n < 5:
            note = (f"{n} fiscal years supplied. Multi-year pattern detection (inflection points, "
                    "acceleration) is most reliable with five years.")
        return TrendReport(ranked, self.executive_summary(ranked), self.yoy_summaries(), note)


def analyze_trends(fd: FinancialData, rr: RatioResults) -> TrendReport:
    return TrendAnalyzer(fd, rr).run()
