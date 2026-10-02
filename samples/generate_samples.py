"""Generate the sample statements shipped in this folder.

* northwind/   - three clean CSVs (USD millions, FY21-FY25, oldest year first)
* meridian_retail_financials.xlsx - one messy, Ind-AS style workbook (INR crores,
  title rows, Note column, newest year first, dates as headers, parentheses
  for negatives, "-" for nil, duplicate "Borrowings" labels split by section)

Both companies have a deliberate story so the trend engine has something to find.
Run:  python samples/generate_samples.py
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

HERE = Path(__file__).parent


def northwind() -> None:
    years = ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"]
    rev = [1000, 1150, 1310, 1520, 1702]
    cogs = [600, 684, 774, 897, 1011]
    sga = [200, 225, 250, 285, 345]  # FY25: opex outpaces revenue
    da = [40, 44, 50, 60, 66]
    interest = [12, 11, 22, 28, 30]
    ebit = [r - c - s - d for r, c, s, d in zip(rev, cogs, sga, da)]
    pbt = [e - i for e, i in zip(ebit, interest)]
    tax = [round(p * 0.25, 1) for p in pbt]
    ni = [round(p - t, 1) for p, t in zip(pbt, tax)]

    cash = [120, 150, 140, 130, 95]
    ar = [140, 160, 182, 240, 310]  # receivables run ahead of sales FY24-25
    inv = [110, 125, 140, 165, 200]
    oca = [30, 32, 35, 38, 40]
    tca = [sum(x) for x in zip(cash, ar, inv, oca)]
    ppe = [500, 520, 700, 760, 800]  # FY23 capacity expansion
    onca = [100, 105, 110, 115, 120]
    ta = [a + b + c for a, b, c in zip(tca, ppe, onca)]
    ap = [90, 100, 112, 130, 150]
    std = [40, 35, 60, 80, 120]
    ocl = [60, 64, 70, 80, 90]
    tcl = [sum(x) for x in zip(ap, std, ocl)]
    ltd = [160, 140, 300, 340, 360]  # debt-funded FY23 capex
    oncl = [50, 52, 55, 58, 60]
    tl = [a + b + c for a, b, c in zip(tcl, ltd, oncl)]
    te = [a - b for a, b in zip(ta, tl)]

    ocf = [150, 170, 195, 175, 140]  # cash conversion fades in FY25
    capex = [60, 64, 230, 120, 106]
    divs = [30, 38.5, 151.5, 137.5, 162.5]

    out = HERE / "northwind"
    out.mkdir(exist_ok=True)

    def write(name: str, title: str, rows: list[tuple[str, list]]) -> None:
        with open(out / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([title] + [""] * len(years))
            w.writerow(["USD in millions"] + [""] * len(years))
            w.writerow(["Line item"] + years)
            for label, vals in rows:
                w.writerow([label] + (["" for _ in years] if vals is None else vals))

    write("northwind_income_statement.csv", "Northwind Industries - Income Statement", [
        ("Revenue", rev), ("Cost of goods sold", cogs), ("Gross profit", [r - c for r, c in zip(rev, cogs)]),
        ("Selling, general & administrative", sga), ("Depreciation & amortization", da),
        ("Operating income", ebit), ("Interest expense", interest), ("Income before taxes", pbt),
        ("Income tax expense", tax), ("Net income", ni),
        ("Diluted shares outstanding", [100, 99, 97, 96, 95]),
    ])
    write("northwind_balance_sheet.csv", "Northwind Industries - Balance Sheet", [
        ("Assets", None), ("Cash and cash equivalents", cash), ("Accounts receivable, net", ar),
        ("Inventories", inv), ("Other current assets", oca), ("Total current assets", tca),
        ("Property, plant & equipment, net", ppe), ("Other non-current assets", onca), ("Total assets", ta),
        ("Liabilities", None), ("Accounts payable", ap), ("Short-term debt", std),
        ("Other current liabilities", ocl), ("Total current liabilities", tcl), ("Long-term debt", ltd),
        ("Other non-current liabilities", oncl), ("Total liabilities", tl),
        ("Shareholders' equity", None), ("Common stock", [200] * 5), ("Retained earnings", [e - 200 for e in te]),
        ("Total shareholders' equity", te),
        ("Total liabilities & shareholders' equity", ta),
    ])
    inv_cf = [-c for c in capex]
    cash_change = [None] + [cash[i] - cash[i - 1] for i in range(1, 5)]
    fin_cf = [-50] + [cash_change[i] - ocf[i] - inv_cf[i] for i in range(1, 5)]
    write("northwind_cash_flow.csv", "Northwind Industries - Cash Flow Statement", [
        ("Net income", ni), ("Depreciation & amortization", da),
        ("Net cash provided by operating activities", ocf),
        ("Capital expenditures", [f"({c})" for c in capex]),
        ("Net cash used in investing activities", inv_cf),
        ("Dividends paid", [-d for d in divs]),
        ("Net cash provided by (used in) financing activities", fin_cf),
    ])


def meridian() -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        print("openpyxl not installed - skipping Excel sample")
        return
    n = 5
    rev = [2400, 2880, 3370, 3640, 3750]  # growth decelerating 20% -> 3%
    other_inc = [20, 25, 30, 25, 20]
    cogs = [1440, 1700, 1955, 2220, 2360]
    emp = [300, 350, 400, 450, 500]
    oth = [250, 300, 340, 400, 440]
    da = [80, 95, 120, 150, 165]
    fin = [60, 75, 110, 160, 190]  # rising finance costs
    exp_total = [sum(x) for x in zip(cogs, emp, oth, da, fin)]
    pbt = [r + o - e for r, o, e in zip(rev, other_inc, exp_total)]
    tax = [round(p * 0.25, 2) for p in pbt]
    pat = [round(p - t, 2) for p, t in zip(pbt, tax)]
    divs = [40] * n

    share_cap = [200] * n
    other_eq = []
    bal = 900.0
    for p, d in zip(pat, divs):
        bal += p - d
        other_eq.append(round(bal, 2))
    te = [a + b for a, b in zip(share_cap, other_eq)]
    ppe = [1200, 1300, 1900, 2400, 2600]
    onca = [150] * n
    inv = [400, 470, 560, 690, 800]
    ar = [330, 400, 520, 640, 790]
    cash = [150, 160, 120, 80, 60]
    oca = [100, 110, 120, 130, 140]
    tca = [sum(x) for x in zip(inv, ar, cash, oca)]
    ta = [a + b + c for a, b, c in zip(ppe, onca, tca)]
    ltb = [400, 450, 900, 1300, 1500]
    stb = [100, 150, 300, 400, 550]
    tp = [300, 340, 380, 420, 430]
    ocl = [120] * n
    oncl = [ta[i] - te[i] - ltb[i] - stb[i] - tp[i] - ocl[i] for i in range(n)]
    tcl = [a + b + c for a, b, c in zip(stb, tp, ocl)]
    tncl = [a + b for a, b in zip(ltb, oncl)]

    wc = [ar[i] + inv[i] + oca[i] - tp[i] for i in range(n)]
    ocf = [pbt[i] + da[i] + fin[i] - other_inc[i] - (wc[i] - (wc[i - 1] if i else wc[i] - 60)) - tax[i]
           for i in range(n)]
    capex = [180] + [ppe[i] - ppe[i - 1] + da[i] for i in range(1, n)]

    # Newest year first, as in most Indian annual reports.
    order = list(reversed(range(n)))
    labels = [f"FY {2020 + i}-{(21 + i) % 100:02d}" for i in range(n)]  # FY 2020-21 .. FY 2024-25
    dates = [dt.datetime(2021 + i, 3, 31) for i in range(n)]

    wb = Workbook()
    bold = Font(bold=True)

    def sheet(title: str, heading: str, header_cells: list, rows: list[tuple[str, str, list | None]],
              as_text: bool = False) -> None:
        ws = wb.create_sheet(title)
        ws.append(["Meridian Retail Limited"])
        ws.append([heading])
        ws.append(["(All amounts in ₹ crores, unless otherwise stated)"])
        ws.append([])
        ws.append(["Particulars", "Note"] + [header_cells[i] for i in order])
        for c in ws[5]:
            c.font = bold
        for label, note, vals in rows:
            if vals is None:
                ws.append([label])
                ws.cell(ws.max_row, 1).font = bold
                continue
            cells = []
            for i in order:
                v = vals[i]
                if as_text:
                    cells.append("-" if v == 0 else (f"({abs(v):,.2f})" if v < 0 else f"{v:,.2f}"))
                else:
                    cells.append(v)
            ws.append([label, note] + cells)
        ws.column_dimensions["A"].width = 48

    sheet("BS", "Balance Sheet as at 31 March", dates, [
        ("ASSETS", "", None), ("Non-current assets", "", None),
        ("Property, plant and equipment", "3", ppe), ("Other non-current assets", "4", onca),
        ("Current assets", "", None), ("Inventories", "5", inv),
        ("Financial assets", "", None), ("Trade receivables", "6", ar),
        ("Cash and cash equivalents", "7", cash), ("Other current assets", "8", oca),
        ("Total current assets", "", tca), ("TOTAL ASSETS", "", ta),
        ("EQUITY AND LIABILITIES", "", None), ("Equity", "", None),
        ("Equity share capital", "9", share_cap), ("Other equity", "10", other_eq), ("Total equity", "", te),
        ("Non-current liabilities", "", None), ("Financial liabilities", "", None),
        ("Borrowings", "11", ltb), ("Other non-current liabilities", "12", oncl),
        ("Total non-current liabilities", "", tncl),
        ("Current liabilities", "", None), ("Financial liabilities", "", None),
        ("Borrowings", "13", stb), ("Trade payables", "14", tp), ("Other current liabilities", "15", ocl),
        ("Total current liabilities", "", tcl), ("TOTAL EQUITY AND LIABILITIES", "", ta),
    ])
    sheet("P&L", "Statement of Profit and Loss for the year ended 31 March", labels, [
        ("Income", "", None), ("Revenue from operations", "16", rev), ("Other income", "17", other_inc),
        ("Total income", "", [a + b for a, b in zip(rev, other_inc)]), ("Expenses", "", None),
        ("Cost of materials consumed", "18", cogs), ("Employee benefits expense", "19", emp),
        ("Finance costs", "20", fin), ("Depreciation and amortisation expense", "3", da),
        ("Other expenses", "21", oth), ("Total expenses", "", exp_total),
        ("Exceptional items", "", [0] * n), ("Profit before tax", "", pbt),
        ("Tax expense", "22", tax), ("Profit for the year", "", pat),
    ], as_text=True)
    sheet("Cash Flow", "Statement of Cash Flows for the year ended 31 March", [l.replace("FY ", "") for l in labels], [
        ("A. Cash flow from operating activities", "", None), ("Profit before tax", "", pbt),
        ("Depreciation and amortisation expense", "", da), ("Finance costs", "", fin),
        ("Net cash flow from operating activities (A)", "", ocf),
        ("B. Cash flow from investing activities", "", None),
        ("Purchase of property, plant and equipment", "", [-c for c in capex]),
        ("Interest received", "", other_inc),
        ("Net cash used in investing activities (B)", "", [-c + o for c, o in zip(capex, other_inc)]),
        ("C. Cash flow from financing activities", "", None),
        ("Dividends paid", "", [-d for d in divs]),
        ("Net cash (used in)/from financing activities (C)", "", [
            (ltb[i] + stb[i] - (ltb[i - 1] + stb[i - 1] if i else 450)) - fin[i] - divs[i] for i in range(n)]),
    ], as_text=True)
    del wb["Sheet"]
    wb.save(HERE / "meridian_retail_financials.xlsx")


def publish_to_web() -> None:
    """Copy the samples into public/samples so the web UI's "Try a sample" links work."""
    import shutil
    dest = HERE.parent / "public" / "samples"
    dest.mkdir(parents=True, exist_ok=True)
    for f in [*(HERE / "northwind").glob("*.csv"), HERE / "meridian_retail_financials.xlsx"]:
        if f.exists():
            shutil.copy2(f, dest / f.name)


if __name__ == "__main__":
    northwind()
    meridian()
    publish_to_web()
    print("Samples written to", HERE, "and public/samples")
