"""Assemble parsed tables into one validated, year-indexed set of line items."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from .ingest import ParsedTable
from .mapping import LabelMapper
from .schema import ITEMS, STATEMENT_NAMES

# Derived items that are not in the line-item schema.
EXTRA_LABELS = {
    "total_debt_used": "Total Debt (used in ratios)",
    "free_cash_flow": "Free Cash Flow",
    "net_debt": "Net Debt",
}


def item_label(key: str) -> str:
    if key in EXTRA_LABELS:
        return EXTRA_LABELS[key]
    return ITEMS[key].label.replace(" (reported)", "") if key in ITEMS else key


@dataclass
class MappingRecord:
    table: str
    raw_label: str
    key: str
    method: str
    used: bool


@dataclass
class FinancialData:
    company: str
    years: list[int]
    units: str | None
    values: dict[str, dict[int, float]] = field(default_factory=dict)
    provenance: dict[str, dict[int, str]] = field(default_factory=dict)
    mapping_log: list[MappingRecord] = field(default_factory=list)
    unmatched: list[tuple[str, str]] = field(default_factory=list)
    statements_found: dict[str, list[str]] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def get(self, key: str, year: int) -> float | None:
        return self.values.get(key, {}).get(year)

    def has(self, key: str) -> bool:
        return bool(self.values.get(key))

    def series(self, key: str) -> pd.Series:
        data = self.values.get(key, {})
        return pd.Series({y: data[y] for y in self.years if y in data}, dtype=float)

    def set(self, key: str, year: int, value: float, source: str) -> None:
        self.values.setdefault(key, {})[year] = float(value)
        self.provenance.setdefault(key, {})[year] = source

    def assume(self, text: str) -> None:
        if text not in self.assumptions:
            self.assumptions.append(text)

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    def to_frame(self) -> pd.DataFrame:
        order = [k for k in ITEMS if k != "total_debt"] + list(EXTRA_LABELS)
        keys = [k for k in order if self.values.get(k)]
        rows = {item_label(k): {y: self.values[k].get(y) for y in self.years} for k in keys}
        return pd.DataFrame(rows).T.reindex(columns=self.years)


def fy(year: int) -> str:
    return f"FY{year % 100:02d}"


# ------------------------------------------------------------------- assembly

def _infer_statement(table: ParsedTable, mapper: LabelMapper) -> str | None:
    counts: Counter[str] = Counter()
    for label, _, _ in table.rows:
        m = mapper.match(label)
        if m:
            counts[ITEMS[m.key].statement] += 1
    if not counts:
        return None
    statement, n = counts.most_common(1)[0]
    # A combined sheet (all statements in one table) has no single statement.
    if n < 0.6 * sum(counts.values()):
        return None
    return statement


def build_financials(tables: list[ParsedTable], mapper: LabelMapper | None = None,
                     company: str = "Company") -> FinancialData:
    mapper = mapper or LabelMapper()
    if not tables:
        raise ValueError("No usable financial tables were found in the inputs.")

    candidates = []
    statements_found: dict[str, list[str]] = {}
    unmatched: list[tuple[str, str]] = []
    pre_warnings: list[str] = []
    for t_idx, table in enumerate(tables):
        for w in table.warnings:
            pre_warnings.append(f"{table.name}: {w}")
        if table.statement is None:
            table.statement = _infer_statement(table, mapper)
            if table.statement:
                pre_warnings.append(
                    f"{table.name}: statement type not named in file/sheet; treated as "
                    f"{STATEMENT_NAMES[table.statement]} based on its line items."
                )
        statements_found.setdefault(table.statement or "combined", []).append(table.name)
        for r_idx, (label, values, section) in enumerate(table.rows):
            # "Borrowings" under "Current liabilities" -> "current borrowings".
            m = (mapper.match(f"{section} {label}") if section else None) or mapper.match(label)
            if m is None:
                unmatched.append((table.name, label))
                continue
            home = table.statement is None or table.statement == ITEMS[m.key].statement
            sort_key = (not home, m.method == "fuzzy", -table.latest_year, m.rank, t_idx, r_idx)
            candidates.append((sort_key, m, table, label, values))
    candidates.sort(key=lambda c: c[0])

    years = sorted({y for _, _, table, _, values in candidates for y, v in values.items() if v is not None})
    if not years:
        raise ValueError(
            "No recognisable line items were found. Check that row labels are standard "
            "(e.g. 'Revenue', 'Total assets') or supply a --mapping file."
        )

    units_seen = Counter(t.units for t in tables if t.units)
    units = units_seen.most_common(1)[0][0] if units_seen else None
    fd = FinancialData(company=company, years=years, units=units, statements_found=statements_found,
                       unmatched=unmatched)
    fd.warnings.extend(pre_warnings)
    if len(units_seen) > 1:
        fd.warn(
            "Inputs declare different units (" + ", ".join(sorted(units_seen)) + "). Ratios are only "
            "valid if all statements use the same scale - please convert before analysing."
        )

    for _, m, table, label, values in candidates:
        used = False
        for year, value in values.items():
            if value is None or fd.get(m.key, year) is not None:
                continue
            fd.set(m.key, year, value, f'{table.name}: "{label}"' + (" (fuzzy match)" if m.method == "fuzzy" else ""))
            used = True
        fd.mapping_log.append(MappingRecord(table.name, label, m.key, m.method, used))
        if used and m.method == "fuzzy":
            fd.assume(f'"{label}" in {table.name} was matched to {ITEMS[m.key].label} by approximate spelling.')

    gaps = [y for y in range(years[0], years[-1] + 1) if y not in years]
    if gaps:
        fd.warn("Missing fiscal years in the inputs: " + ", ".join(fy(y) for y in gaps)
                + ". Growth rates and CAGR use the actual year spacing.")

    _normalise_signs(fd)
    _derive(fd)
    _validate(fd)
    return fd


# --------------------------------------------------------------- derivations

def _normalise_signs(fd: FinancialData) -> None:
    for key, item in ITEMS.items():
        if not item.magnitude or key not in fd.values:
            continue
        flipped = [y for y, v in fd.values[key].items() if v < 0]
        for y in flipped:
            fd.values[key][y] = abs(fd.values[key][y])
        if flipped:
            fd.assume(f"{item.label} was presented as negative figures; magnitudes are used.")


def _derive(fd: FinancialData) -> None:
    g = fd.get
    for y in fd.years:
        rev, cogs, gp = g("revenue", y), g("cogs", y), g("gross_profit", y)
        if rev is None and gp is not None and cogs is not None:
            fd.set("revenue", y, gp + cogs, "derived: Gross Profit + COGS")
        if cogs is None and rev is not None and gp is not None:
            fd.set("cogs", y, rev - gp, "derived: Revenue - Gross Profit")
        rev, cogs = g("revenue", y), g("cogs", y)
        if g("gross_profit", y) is None and rev is not None and cogs is not None:
            fd.set("gross_profit", y, rev - cogs, "derived: Revenue - COGS")

        if g("ebit", y) is None and g("pretax_income", y) is not None and g("interest_expense", y) is not None:
            fd.set("ebit", y, g("pretax_income", y) + g("interest_expense", y),
                   "derived: Pre-tax Income + Interest Expense")
            fd.assume("Where operating income was not reported, EBIT = Pre-tax Income + Interest Expense "
                      "(this includes any non-operating income).")

        opex, ebit, gp = g("operating_expenses", y), g("ebit", y), g("gross_profit", y)
        rev, cogs = g("revenue", y), g("cogs", y)
        if opex is not None and ebit is not None and rev and cogs:
            # Some statements report "Total operating expenses" including cost of sales.
            if abs(rev - opex - ebit) <= 0.02 * abs(rev) and abs(gp - opex - ebit) > 0.02 * abs(rev):
                fd.set("operating_expenses", y, opex - cogs, "derived: Total costs - COGS")
                fd.assume("Reported operating expenses included cost of sales; COGS was removed so opex "
                          "reflects operating (below-gross-profit) costs only.")
        if g("operating_expenses", y) is None and gp is not None and ebit is not None:
            fd.set("operating_expenses", y, gp - ebit, "derived: Gross Profit - EBIT")
            fd.assume("Operating expenses not reported separately; derived as Gross Profit - EBIT "
                      "(includes D&A and other operating items).")
        if g("ebit", y) is None and gp is not None and g("operating_expenses", y) is not None:
            fd.set("ebit", y, gp - g("operating_expenses", y), "derived: Gross Profit - Operating Expenses")

        # EBITDA: computed definitionally where possible for consistency across years.
        ebit, da, reported = g("ebit", y), g("depreciation_amortization", y), g("ebitda", y)
        if ebit is not None and da is not None:
            note = "derived: EBIT + D&A"
            if reported is not None and abs(reported - (ebit + da)) > 0.02 * max(abs(reported), 1e-9):
                note += f" (reported EBITDA {reported:,.1f} differs; likely 'adjusted')"
                fd.assume("Reported EBITDA differs from EBIT + D&A in some years (often an 'adjusted' "
                          "figure); the computed EBIT + D&A is used for consistency.")
            fd.set("ebitda", y, ebit + da, note)

        # Total debt
        parts = {k: g(k, y) for k in ("short_term_debt", "current_portion_ltd", "long_term_debt")}
        present = {k: v for k, v in parts.items() if v is not None}
        if g("total_debt", y) is not None:
            fd.set("total_debt_used", y, g("total_debt", y), fd.provenance["total_debt"][y])
        elif present:
            fd.set("total_debt_used", y, sum(present.values()),
                   "derived: " + " + ".join(ITEMS[k].label for k in present))

        # Balance-sheet identities
        ta, tl, te, tle = g("total_assets", y), g("total_liabilities", y), g("total_equity", y), \
            g("total_liabilities_and_equity", y)
        if ta is None and tle is not None:
            fd.set("total_assets", y, tle, "derived: Total Liabilities & Equity")
        elif ta is None and tl is not None and te is not None:
            fd.set("total_assets", y, tl + te, "derived: Total Liabilities + Total Equity")
        ta = g("total_assets", y)
        if te is None and ta is not None and tl is not None:
            fd.set("total_equity", y, ta - tl, "derived: Total Assets - Total Liabilities")
        te = g("total_equity", y)
        if tl is None and ta is not None and te is not None:
            fd.set("total_liabilities", y, ta - te, "derived: Total Assets - Total Equity")

        if g("total_current_assets", y) is None:
            comps = {k: g(k, y) for k in ("cash", "short_term_investments", "accounts_receivable", "inventory")}
            if comps["cash"] is not None and comps["accounts_receivable"] is not None:
                fd.set("total_current_assets", y, sum(v for v in comps.values() if v is not None),
                       "derived: Cash + ST Investments + Receivables + Inventory")
                fd.assume("Total current assets not reported; approximated from cash, investments, "
                          "receivables and inventory (understates if other current assets exist).")

        # Cash-flow derived
        if g("operating_cash_flow", y) is not None and g("capex", y) is not None:
            fd.set("free_cash_flow", y, g("operating_cash_flow", y) - g("capex", y),
                   "derived: Operating Cash Flow - Capex")
        if g("total_debt_used", y) is not None and g("cash", y) is not None:
            fd.set("net_debt", y, g("total_debt_used", y) - g("cash", y) - (g("short_term_investments", y) or 0.0),
                   "derived: Total Debt - Cash - ST Investments")

    if not fd.has("total_debt_used") and fd.has("total_assets"):
        fd.warn("No borrowing line items were found (short/long-term debt, borrowings). Debt-based ratios "
                "are unavailable - if the company is debt-free, add a 'Total debt' row of zeros.")


def _validate(fd: FinancialData) -> None:
    g = fd.get
    unbalanced: list[tuple[int, float]] = []
    for y in fd.years:
        p = fd.provenance
        ta, tl, te = g("total_assets", y), g("total_liabilities", y), g("total_equity", y)
        all_reported = all(not p.get(k, {}).get(y, "derived").startswith("derived")
                           for k in ("total_assets", "total_liabilities", "total_equity"))
        if all_reported and None not in (ta, tl, te) and ta:
            # Parent-only equity excludes non-controlling interests, which sit between the totals.
            gap = ta - tl - te - (g("minority_interest", y) or 0.0)
            if abs(gap) > 0.01 * abs(ta):
                unbalanced.append((y, gap / ta))
        tca, tcl = g("total_current_assets", y), g("total_current_liabilities", y)
        if tca is not None and ta is not None and tca > ta * 1.001:
            fd.warn(f"{fy(y)}: Current assets exceed total assets - check the mapping of these rows.")
        if tcl is not None and tl is not None and tcl > tl * 1.001:
            fd.warn(f"{fy(y)}: Current liabilities exceed total liabilities - check the mapping of these rows.")
        rev, cogs, gp = g("revenue", y), g("cogs", y), g("gross_profit", y)
        if None not in (rev, cogs, gp) and "derived" not in p["gross_profit"][y] \
                and abs(rev - cogs - gp) > 0.01 * abs(rev):
            fd.warn(f"{fy(y)}: Reported gross profit ({gp:,.0f}) differs from Revenue - COGS ({rev - cogs:,.0f}).")
        if rev is not None and rev <= 0:
            fd.warn(f"{fy(y)}: Revenue is zero or negative - margin and turnover ratios are not meaningful.")
        if te is not None and te < 0:
            fd.warn(f"{fy(y)}: Shareholders' equity is negative ({te:,.0f}); ROE and Debt/Equity are not meaningful.")
    if unbalanced:
        worst = max(abs(r) for _, r in unbalanced)
        fd.warn(f"Balance sheet does not balance in {', '.join(fy(y) for y, _ in unbalanced)}: assets differ from "
                f"liabilities + equity by up to {worst:.1%} of assets (minority interest or a mezzanine item may "
                "sit outside both totals).")

    essentials = ["revenue", "net_income", "total_assets", "total_equity", "total_current_assets",
                  "total_current_liabilities", "operating_cash_flow"]
    missing = [ITEMS[k].label for k in essentials if not fd.has(k)]
    if missing:
        fd.warn("Not found in any input: " + ", ".join(missing) + ". Dependent ratios are shown as unavailable.")
    for key in ("revenue", "net_income", "total_assets"):
        if fd.has(key):
            absent = [fy(y) for y in fd.years if g(key, y) is None]
            if absent:
                fd.warn(f"{ITEMS[key].label} is missing for {', '.join(absent)}.")
    for statement in ("balance_sheet", "income_statement", "cash_flow"):
        if statement not in fd.statements_found and "combined" not in fd.statements_found:
            fd.warn(f"No {STATEMENT_NAMES[statement]} was identified among the inputs.")
