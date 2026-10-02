"""Canonical line items and the label synonyms used to recognise them.

Every raw row label found in an uploaded statement is normalised (see
``normalize_label``) and compared against the synonyms below. Synonyms are
listed in order of preference: when a statement contains several rows that map
to the same item (e.g. "Sales" and "Total revenue"), the earlier synonym wins.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

BS = "balance_sheet"
IS = "income_statement"
CF = "cash_flow"

STATEMENT_NAMES = {BS: "Balance Sheet", IS: "Profit & Loss", CF: "Cash Flow"}


@dataclass(frozen=True)
class LineItem:
    key: str
    label: str
    statement: str
    synonyms: tuple[str, ...]
    # Expense-type items are stored as positive magnitudes regardless of how the
    # source presents them (many statements show costs in parentheses).
    magnitude: bool = False


LINE_ITEMS: tuple[LineItem, ...] = (
    # ---------------------------------------------------------------- P&L
    LineItem("revenue", "Revenue", IS, (
        "total revenue", "total revenues", "revenue", "revenues", "net revenue",
        "net revenues", "total net revenue", "total net sales", "net sales",
        "revenue from operations", "total revenue from operations",
        "income from operations net", "operating revenue", "operating revenues",
        "sales revenue", "turnover", "sales", "net turnover",
    )),
    LineItem("cogs", "Cost of Goods Sold", IS, (
        "cost of goods sold", "cost of sales", "cost of revenue", "cost of revenues",
        "total cost of revenue", "total cost of revenues", "cogs",
        "cost of products sold", "cost of materials consumed", "cost of goods and services sold",
    ), magnitude=True),
    LineItem("gross_profit", "Gross Profit", IS, ("gross profit", "gross margin", "gross income")),
    LineItem("operating_expenses", "Operating Expenses", IS, (
        "total operating expenses", "operating expenses", "total operating costs",
        "operating costs", "opex", "selling general and administrative expenses",
        "selling general and administrative", "sg and a", "sg and a expenses",
        "total other operating expenses", "other operating expenses",
    ), magnitude=True),
    LineItem("depreciation_amortization", "Depreciation & Amortization", IS, (
        "depreciation and amortization", "depreciation and amortisation",
        "depreciation and amortization expense", "depreciation and amortisation expense",
        "depreciation amortization", "depreciation amortisation",
        "depreciation amortization and impairment", "depreciation amortisation and impairment",
        "depreciation", "d and a",
    ), magnitude=True),
    LineItem("ebitda", "EBITDA (reported)", IS, ("ebitda", "reported ebitda")),
    LineItem("ebit", "EBIT / Operating Income", IS, (
        "operating income", "operating profit", "income from operations", "ebit",
        "profit from operations", "earnings before interest and taxes",
        "earnings before interest and tax", "operating income loss", "operating profit loss",
        "results from operating activities",
    )),
    LineItem("interest_expense", "Interest Expense", IS, (
        "interest expense", "finance costs", "finance cost", "interest expense net",
        "net interest expense", "interest and finance charges", "finance charges",
        "borrowing costs", "interest", "interest costs",
    ), magnitude=True),
    LineItem("pretax_income", "Pre-tax Income", IS, (
        "income before income taxes", "income before taxes", "income before tax",
        "profit before tax", "profit before taxation", "profit before income tax",
        "earnings before taxes", "earnings before income taxes", "pretax income",
        "pre tax income", "pbt",
    )),
    LineItem("tax_expense", "Income Tax", IS, (
        "income tax expense", "provision for income taxes", "total tax expense",
        "tax expense", "income taxes", "income tax", "taxes", "taxation",
    )),
    LineItem("net_income", "Net Income", IS, (
        "net income", "net profit", "net earnings", "profit for the year",
        "profit for the period", "net profit for the year", "net profit after tax",
        "profit after tax", "pat", "net income attributable to shareholders",
        "net income attributable to common shareholders", "profit attributable to owners",
        "net income attributable to parent",
    )),
    LineItem("shares_outstanding", "Diluted Shares Outstanding", IS, (
        "weighted average shares diluted", "weighted average diluted shares outstanding",
        "diluted weighted average shares", "diluted shares outstanding", "diluted shares",
        "weighted average number of shares diluted", "weighted average shares outstanding",
        "weighted average number of shares", "shares outstanding", "number of shares outstanding",
    )),
    # ------------------------------------------------------- Balance sheet
    LineItem("cash", "Cash & Equivalents", BS, (
        "cash and cash equivalents", "cash and equivalents", "cash", "cash and bank balances",
        "cash and bank", "cash and cash equivalents at end of year",
    )),
    LineItem("short_term_investments", "Short-term Investments", BS, (
        "short term investments", "marketable securities", "current investments",
        "short term marketable securities",
    )),
    LineItem("accounts_receivable", "Accounts Receivable", BS, (
        "accounts receivable", "accounts receivable net", "trade receivables",
        "trade and other receivables", "net receivables", "receivables",
        "trade debtors", "sundry debtors", "debtors",
    )),
    LineItem("inventory", "Inventory", BS, (
        "inventory", "inventories", "merchandise inventory", "stock in trade", "stock",
    )),
    LineItem("total_current_assets", "Total Current Assets", BS, (
        "total current assets", "current assets",
    )),
    LineItem("ppe", "Property, Plant & Equipment", BS, (
        "property plant and equipment", "property plant and equipment net", "net ppe", "ppe",
        "fixed assets", "net fixed assets", "property and equipment net", "property and equipment",
    )),
    LineItem("total_assets", "Total Assets", BS, ("total assets",)),
    LineItem("accounts_payable", "Accounts Payable", BS, (
        "accounts payable", "trade payables", "trade and other payables", "payables",
        "trade creditors", "sundry creditors", "creditors",
    )),
    LineItem("short_term_debt", "Short-term Debt", BS, (
        "short term debt", "short term borrowings", "current borrowings", "short term loans",
        "notes payable", "bank overdraft", "bank overdrafts", "commercial paper", "current debt",
    )),
    LineItem("current_portion_ltd", "Current Portion of LT Debt", BS, (
        "current portion of long term debt", "current maturities of long term debt",
        "current portion of long term borrowings", "current maturities of long term borrowings",
    )),
    LineItem("total_current_liabilities", "Total Current Liabilities", BS, (
        "total current liabilities", "current liabilities",
    )),
    LineItem("long_term_debt", "Long-term Debt", BS, (
        "long term debt", "long term borrowings", "non current borrowings",
        "long term debt net of current portion", "long term loans", "term loans",
        "bonds payable", "borrowings",
    )),
    LineItem("total_debt", "Total Debt (reported)", BS, (
        "total debt", "total borrowings", "gross debt", "debt",
    )),
    LineItem("total_liabilities", "Total Liabilities", BS, ("total liabilities",)),
    LineItem("total_equity", "Total Equity", BS, (
        "total equity", "total shareholders equity", "total stockholders equity",
        "total shareholders funds", "shareholders equity", "stockholders equity",
        "shareholders funds", "total equity attributable to shareholders",
        "equity attributable to owners", "net worth", "networth", "equity",
    )),
    LineItem("retained_earnings", "Retained Earnings", BS, (
        "retained earnings", "retained earnings accumulated deficit", "accumulated deficit",
        "retained profits", "accumulated earnings",
    )),
    LineItem("minority_interest", "Non-controlling Interest", BS, (
        "non controlling interests", "non controlling interest", "noncontrolling interests",
        "noncontrolling interest", "minority interest", "minority interests",
    )),
    LineItem("total_liabilities_and_equity", "Total Liabilities & Equity", BS, (
        "total liabilities and equity", "total liabilities and shareholders equity",
        "total liabilities and stockholders equity", "total equity and liabilities",
    )),
    # ------------------------------------------------------------ Cash flow
    LineItem("operating_cash_flow", "Operating Cash Flow", CF, (
        "net cash from operating activities", "net cash provided by operating activities",
        "net cash generated from operating activities", "net cash flow from operating activities",
        "cash flow from operating activities", "cash flows from operating activities",
        "net cash provided by used in operating activities", "operating cash flow",
        "cash from operations", "cash generated from operations", "net cash from operations",
    )),
    LineItem("capex", "Capital Expenditure", CF, (
        "capital expenditure", "capital expenditures", "capex",
        "purchase of property plant and equipment", "purchases of property plant and equipment",
        "purchases of property and equipment", "purchase of property and equipment",
        "purchase of fixed assets", "additions to property plant and equipment",
        "payments for property plant and equipment", "acquisition of property plant and equipment",
    ), magnitude=True),
    LineItem("investing_cash_flow", "Investing Cash Flow", CF, (
        "net cash used in investing activities", "net cash from investing activities",
        "net cash provided by investing activities", "net cash flow from investing activities",
        "cash flow from investing activities", "cash flows from investing activities",
        "net cash used in investing activities net", "investing cash flow",
    )),
    LineItem("financing_cash_flow", "Financing Cash Flow", CF, (
        "net cash used in financing activities", "net cash from financing activities",
        "net cash provided by financing activities", "net cash flow from financing activities",
        "cash flow from financing activities", "cash flows from financing activities",
        "financing cash flow",
    )),
    LineItem("dividends_paid", "Dividends Paid", CF, (
        "dividends paid", "dividend paid", "cash dividends paid", "dividends paid to shareholders",
        "dividends",
    ), magnitude=True),
)

ITEMS: dict[str, LineItem] = {item.key: item for item in LINE_ITEMS}

# Items that are also shown by name only on the derived side.
DERIVED_LABELS = {
    "ebitda_calc": "EBITDA",
    "total_debt_calc": "Total Debt",
    "free_cash_flow": "Free Cash Flow",
    "net_debt": "Net Debt",
}


_ENUM_PREFIX = re.compile(r"^\s*(?:[ivxlc]+[.)]|[a-z][.)]|\d+(?:\.\d+)*[.)]?|\([a-z0-9]+\))\s+", re.I)
_PARENS = re.compile(r"\([^)]*\)")
_LEADING_WORDS = re.compile(r"^(?:less|add|of which|minus|plus)\s+")


def normalize_label(label: str) -> str:
    """Lower-case a label and strip punctuation, enumeration and notes.

    "  2. Profit/(Loss) for the year*" -> "profit for the year"
    "Selling, General & Admin. Expenses" -> "selling general and admin expenses"
    """
    s = str(label).strip()
    s = _ENUM_PREFIX.sub("", s)
    s = s.replace("&", " and ")
    s = _PARENS.sub(" ", s)
    s = s.lower().replace("’", "'")
    s = re.sub(r"'s\b", "s", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _LEADING_WORDS.sub("", s)
    # "for the year ended 31 march" style trailing qualifiers
    s = re.sub(r"\s+for the (?:fiscal )?(?:year|period) ended.*$", "", s)
    return s


SYNONYM_INDEX: dict[str, tuple[str, int]] = {}
for _item in LINE_ITEMS:
    for _rank, _syn in enumerate(_item.synonyms):
        _norm = normalize_label(_syn)
        # First definition wins; a synonym must map to exactly one item.
        SYNONYM_INDEX.setdefault(_norm, (_item.key, _rank))
