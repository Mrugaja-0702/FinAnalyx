"""SEC EDGAR XBRL "company facts": official 10-K figures for US-listed companies, 10+ years."""
from __future__ import annotations

import datetime as dt

from .base import SEC_UA, CompanyData, ProviderError, TTLCache, build_tables, get_json

SOURCE = "SEC EDGAR"

# item key -> us-gaap concepts, in order of preference. Concepts are merged per year,
# so a company that switched concept (e.g. SalesRevenueNet -> RevenueFromContract...) stays continuous.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet",
                "SalesRevenueServicesNet"),
    "cogs": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices"),
    "gross_profit": ("GrossProfit",),
    "operating_expenses": ("OperatingExpenses", "CostsAndExpenses", "SellingGeneralAndAdministrativeExpense"),
    "depreciation_amortization": ("DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                                  "DepreciationAndAmortization", "Depreciation"),
    "ebit": ("OperatingIncomeLoss",),
    "interest_expense": ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                         "InterestAndDebtExpense"),
    "pretax_income": ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"),
    "tax_expense": ("IncomeTaxExpenseBenefit",),
    "net_income": ("NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"),
    "shares_outstanding": ("WeightedAverageNumberOfDilutedSharesOutstanding",
                           "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted"),
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
             "Cash"),
    "short_term_investments": ("ShortTermInvestments", "MarketableSecuritiesCurrent",
                               "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
    "accounts_receivable": ("AccountsReceivableNetCurrent", "ReceivablesNetCurrent"),
    "inventory": ("InventoryNet",),
    "total_current_assets": ("AssetsCurrent",),
    "ppe": ("PropertyPlantAndEquipmentNet",),
    "total_assets": ("Assets",),
    "accounts_payable": ("AccountsPayableCurrent",),
    "short_term_debt": ("ShortTermBorrowings", "CommercialPaper", "OtherShortTermBorrowings"),
    "current_portion_ltd": ("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
    "total_current_liabilities": ("LiabilitiesCurrent",),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermNotesPayable",
                       "SeniorLongTermNotes"),
    "total_liabilities": ("Liabilities",),
    "total_equity": ("StockholdersEquity",
                     "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    "minority_interest": ("MinorityInterest",),
    "retained_earnings": ("RetainedEarningsAccumulatedDeficit",),
    "total_liabilities_and_equity": ("LiabilitiesAndStockholdersEquity",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",
                            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "investing_cash_flow": ("NetCashProvidedByUsedInInvestingActivities",
                            "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"),
    "financing_cash_flow": ("NetCashProvidedByUsedInFinancingActivities",
                            "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"),
    "dividends_paid": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
}
# Flows are measured over a fiscal year; the rest are point-in-time balances.
FLOW_ITEMS = {"revenue", "cogs", "gross_profit", "operating_expenses", "depreciation_amortization", "ebit",
              "interest_expense", "pretax_income", "tax_expense", "net_income", "operating_cash_flow", "capex",
              "investing_cash_flow", "financing_cash_flow", "dividends_paid", "shares_outstanding"}
SHARE_ITEMS = {"shares_outstanding"}

_tickers_cache = TTLCache(ttl=86400, max_items=2)
_facts_cache = TTLCache(ttl=3600, max_items=64)


def ticker_map() -> dict[str, dict]:
    def run() -> dict[str, dict]:
        data = get_json("https://www.sec.gov/files/company_tickers.json", user_agent=SEC_UA,
                        what="SEC ticker directory")
        return {row["ticker"].upper(): {"cik": int(row["cik_str"]), "name": row["title"]} for row in data.values()}
    return _tickers_cache.get_or_set("tickers", run)


def lookup(symbol: str) -> dict | None:
    return ticker_map().get(symbol.upper().replace(".", "-"))


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _annual_points(units: dict, flow: bool) -> dict[dt.date, tuple[float, str]]:
    """{period end: (value, filed)} for annual 10-K figures, latest filing wins (captures restatements)."""
    out: dict[dt.date, tuple[float, str]] = {}
    for entries in units.values():
        for e in entries:
            if not str(e.get("form", "")).startswith("10-K"):
                continue
            end = _date(e["end"])
            if flow:
                if "start" not in e:
                    continue
                days = (end - _date(e["start"])).days
                if not 350 <= days <= 380:
                    continue
            elif "start" in e:
                continue
            prev = out.get(end)
            if prev is None or e.get("filed", "") > prev[1]:
                out[end] = (float(e["val"]), e.get("filed", ""))
        break  # first unit (USD) only
    return out


def fetch_company(symbol: str, years: int = 10) -> CompanyData:
    info = lookup(symbol)
    if not info:
        raise ProviderError(f"'{symbol}' is not in the SEC ticker directory (SEC EDGAR covers US-listed filers).", 404)
    cik = info["cik"]
    facts = _facts_cache.get_or_set(cik, lambda: get_json(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", user_agent=SEC_UA,
        what="SEC company facts", timeout=25.0))
    gaap = (facts.get("facts") or {}).get("us-gaap")
    if not gaap:
        raise ProviderError(f"{info['name']} does not file US-GAAP financials with the SEC "
                            "(foreign filers report under IFRS).", 422)

    def usd_units(concept: str, unit: str = "USD") -> dict:
        units = (gaap.get(concept) or {}).get("units") or {}
        return {unit: units[unit]} if unit in units else {}

    # Fiscal year-ends are the end dates of annual net income / revenue periods.
    fy_ends: set[dt.date] = set()
    for concept in ("NetIncomeLoss", "ProfitLoss", "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"):
        fy_ends.update(_annual_points(usd_units(concept), flow=True))
    if not fy_ends:
        raise ProviderError(f"No annual (10-K) figures found for {info['name']}.", 422)

    def fiscal_year(end: dt.date) -> int | None:
        for fe in fy_ends:
            if abs((fe - end).days) <= 7:
                return fe.year
        return None

    values: dict[str, dict[int, float]] = {}
    labels: dict[str, str] = {}
    for key, concepts in CONCEPTS.items():
        merged: dict[int, float] = {}
        used = []
        for concept in concepts:
            unit = "shares" if key in SHARE_ITEMS else "USD"
            for end, (val, _) in sorted(_annual_points(usd_units(concept, unit), key in FLOW_ITEMS).items()):
                year = fiscal_year(end)
                if year is None or year in merged:
                    continue
                merged[year] = val
                if concept not in used:
                    used.append(concept)
        if merged:
            values[key] = merged
            labels[key] = "us-gaap:" + " / ".join(used)

    keep = sorted({y for v in values.values() for y in v})[-years:]
    values = {k: {y: v for y, v in s.items() if y in keep} for k, s in values.items()}

    shares = None
    dei = (facts.get("facts") or {}).get("dei") or {}
    pts = ((dei.get("EntityCommonStockSharesOutstanding") or {}).get("units") or {}).get("shares") or []
    if pts:
        latest_end = max(p["end"] for p in pts)
        shares = float(sum(p["val"] for p in pts if p["end"] == latest_end))  # sums share classes
    tables, overrides = build_tables(SOURCE, values, labels, "USD")
    period_ends = {fe.year: fe.isoformat() for fe in sorted(fy_ends) if fe.year in keep}
    return CompanyData(
        symbol=symbol.upper(), name=facts.get("entityName") or info["name"], source=SOURCE,
        source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}&type=10-K",
        currency="USD", tables=tables, overrides=overrides, shares_outstanding=shares, period_ends=period_ends,
    )


def search(query: str, limit: int = 8) -> list[dict]:
    q = query.strip().upper()
    hits = []
    for ticker, info in ticker_map().items():
        name = info["name"].upper()
        if ticker == q:
            rank = 0
        elif ticker.startswith(q):
            rank = 1
        elif name.startswith(q):
            rank = 2
        elif q in name:
            rank = 3
        else:
            continue
        hits.append((rank, len(ticker), ticker, info["name"]))
    hits.sort()
    return [{"symbol": t, "name": n, "exchange": "US (SEC filer)", "sector": None, "industry": None}
            for _, _, t, n in hits[:limit]]
