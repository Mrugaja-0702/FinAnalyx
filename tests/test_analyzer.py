import csv
import json
import math
from pathlib import Path

import pytest

from finanalyx import analyze
from finanalyx.ingest import parse_number, parse_period
from finanalyx.mapping import LabelMapper
from finanalyx.ratios import NM, MISSING

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


@pytest.fixture(scope="session", autouse=True)
def samples():
    if not (SAMPLES / "northwind").exists() or not (SAMPLES / "meridian_retail_financials.xlsx").exists():
        import runpy
        runpy.run_path(str(SAMPLES / "generate_samples.py"), run_name="__main__")


def write_csv(path: Path, rows: list[list]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return path


# --------------------------------------------------------------- cell parsing

@pytest.mark.parametrize("raw,expected", [
    ("1,234", 1234.0), ("(1,234.5)", -1234.5), ("-", 0.0), ("—", 0.0), ("nil", 0.0), ("", None),
    ("n/a", None), ("$ 12.5", 12.5), ("₹1,00,000", 100000.0), ("12.5%", 0.125), ("1.2bn", 1.2e9),
    ("−45", -45.0), ("1234-", -1234.0), (42, 42.0), (float("nan"), None), ("abc", None),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("FY25", 2025), ("FY2025", 2025), ("FY 2024-25", 2025), ("2024-25", 2025), ("2025", 2025),
    ("Mar-25", 2025), ("31-Mar-2025", 2025), ("Dec 31, 2024", 2024), ("2025-03-31", 2025),
    ("31/03/2025", 2025), ("Year ended 31 March 2025", 2025), ("2026E", 2026), (2023, 2023),
    ("Q1 FY25", None), ("YoY %", None), ("Particulars", None), (1234.5, None), ("2023 (Restated)", 2023),
])
def test_parse_period(raw, expected):
    assert parse_period(raw) == expected


def test_mapping_rejects_qualifier_mismatch_and_accepts_typos():
    m = LabelMapper()
    assert m.match("Total non-current assets") is None
    assert m.match("Total current assets").key == "total_current_assets"
    assert m.match("Inventries").key == "inventory"
    assert m.match("Accounts recievable").key == "accounts_receivable"
    assert m.match("Profit/(Loss) for the year").key == "net_income"
    assert m.match("Net income attributable to non-controlling interests") is None


def test_mapping_override_validation():
    assert LabelMapper({"Net turnover from ops": "revenue"}).match("Net turnover from ops").key == "revenue"
    with pytest.raises(ValueError):
        LabelMapper({"x": "not_an_item"})


# ------------------------------------------------------------- end to end

def test_northwind_ratios():
    a = analyze([SAMPLES / "northwind"])
    r, y = a.ratios, 2025
    assert r.get("current_ratio", y).value == pytest.approx(645 / 360)
    assert r.get("quick_ratio", y).value == pytest.approx((645 - 200) / 360)
    assert r.get("debt_to_equity", y).value == pytest.approx(480 / 785)
    assert r.get("debt_ratio", y).value == pytest.approx(480 / 1565)
    assert r.get("interest_coverage", y).value == pytest.approx(280 / 30)
    assert r.get("roe", y).value == pytest.approx(187.5 / ((785 + 760) / 2))
    assert r.get("roa", y).value == pytest.approx(187.5 / ((1565 + 1448) / 2))
    assert r.get("net_margin", y).value == pytest.approx(187.5 / 1702)
    assert r.get("ebitda_margin", y).value == pytest.approx((280 + 66) / 1702)
    assert r.get("inventory_turnover", y).value == pytest.approx(1011 / ((200 + 165) / 2))
    assert r.get("receivable_turnover", y).value == pytest.approx(1702 / ((310 + 240) / 2))
    assert r.get("asset_turnover", y).value == pytest.approx(1702 / ((1565 + 1448) / 2))
    assert r.get("revenue_cagr").value == pytest.approx((1702 / 1000) ** 0.25 - 1)
    assert r.get("profit_cagr").value == pytest.approx((187.5 / 111) ** 0.25 - 1)
    assert r.get("asset_cagr").value == pytest.approx((1565 / 1000) ** 0.25 - 1)
    # First year has no opening balance: closing balance used and disclosed.
    assert "closing balance" in r.get("roe", 2021).note
    assert a.data.units == "USD millions"


def test_northwind_trend_story():
    a = analyze([SAMPLES / "northwind"])
    titles = " | ".join(i.title for i in a.trends.insights)
    assert "operating expenses grew faster than revenue in FY25" in titles
    assert "Receivables grew faster than revenue" in titles
    assert "Cash conversion dropped in FY25" in titles
    assert "EBITDA margin peaked" in titles
    assert "driven mainly by higher leverage" in titles
    assert len(a.trends.yoy) == 4


def test_messy_excel_workbook():
    a = analyze([SAMPLES / "meridian_retail_financials.xlsx"])
    fd = a.data
    assert fd.years == [2021, 2022, 2023, 2024, 2025]
    assert fd.units == "INR crores"
    # Duplicate "Borrowings" rows are separated by their balance-sheet section.
    assert fd.get("long_term_debt", 2025) == 1500
    assert fd.get("short_term_debt", 2025) == 550
    assert fd.get("capex", 2023) > 0  # "(720.00)" in the source
    assert fd.provenance["ebit"][2025].startswith("derived")
    titles = " | ".join(i.title for i in a.trends.insights)
    assert "Revenue growth is decelerating" in titles
    assert "Interest coverage fell" in titles


def test_five_single_year_files_are_merged(tmp_path):
    for i, year in enumerate(range(2021, 2026)):
        rev = 100 * (1.1 ** i)
        write_csv(tmp_path / f"acme_fy{year}.csv", [
            ["Line item", f"FY{year}"], ["Revenue", rev], ["Net income", rev * 0.1], ["Total assets", 200 + i * 10],
            ["Total equity", 120 + i * 5], ["Total current assets", 80], ["Total current liabilities", 50],
            ["Operating income", rev * 0.15], ["Interest expense", 2],
        ])
    a = analyze([tmp_path])
    assert a.data.years == [2021, 2022, 2023, 2024, 2025]
    assert a.ratios.get("revenue_cagr").value == pytest.approx(0.10)
    assert any("Revenue grew in every year" in i.title for i in a.trends.insights)


def test_transposed_and_descending_layout(tmp_path):
    write_csv(tmp_path / "income_statement.csv", [
        ["Year", "Revenue", "Cost of sales", "Net income"],
        ["2024", "1,200", "(700)", "90"], ["2023", "1,000", "(600)", "80"], ["2022", "900", "(560)", "60"],
    ])
    a = analyze([tmp_path / "income_statement.csv"])
    assert a.data.years == [2022, 2023, 2024]
    assert a.data.get("cogs", 2024) == 700  # magnitude, despite parentheses
    assert a.ratios.get("net_margin", 2024).value == pytest.approx(90 / 1200)
    assert any("transposed" in w for w in a.data.warnings)


def test_edge_cases_negative_equity_losses_and_no_interest(tmp_path):
    write_csv(tmp_path / "combined.csv", [
        ["", "FY2022", "FY2023", "FY2024"],
        ["Revenue", 100, 120, 130], ["Operating income", 10, 5, -8], ["Interest expense", 0, 0, 0],
        ["Net income", 8, -4, -12], ["Total assets", 100, 90, 80], ["Total liabilities", 90, 95, 100],
    ])
    a = analyze([tmp_path / "combined.csv"])
    r = a.ratios
    assert a.data.get("total_equity", 2024) == -20  # derived from the identity
    assert r.get("roe", 2024).status == NM
    assert r.get("debt_to_equity", 2024).status == MISSING  # no debt lines at all
    assert r.get("interest_coverage", 2024).status == NM
    assert r.get("profit_cagr").status == NM
    assert r.get("profit_growth", 2024).status == NM  # prior year was a loss
    assert any("negative" in w for w in a.data.warnings)
    assert any("swung to a net loss" in i.title for i in a.trends.insights)


def test_opex_reported_including_cogs_is_corrected(tmp_path):
    write_csv(tmp_path / "pl.csv", [
        ["", "2023", "2024"], ["Revenue", 1000, 1100], ["Cost of revenue", 600, 650],
        ["Total operating expenses", 850, 930], ["Operating income", 150, 170], ["Net income", 100, 115],
    ])
    a = analyze([tmp_path / "pl.csv"])
    assert a.data.get("operating_expenses", 2024) == 280
    assert any("included cost of sales" in t for t in a.data.assumptions)


def test_single_year_has_no_trends_but_ratios_work(tmp_path):
    write_csv(tmp_path / "bs.csv", [["Balance sheet", "FY2025"], ["Total current assets", 300],
                                    ["Total current liabilities", 150], ["Inventories", 50]])
    a = analyze([tmp_path / "bs.csv"])
    assert a.ratios.get("current_ratio", 2025).value == 2.0
    assert a.ratios.get("quick_ratio", 2025).value == pytest.approx(250 / 150)
    assert a.trends.insights == [] and "at least two" in a.trends.note


def test_unreadable_input_errors_cleanly(tmp_path):
    from finanalyx.ingest import IngestError
    write_csv(tmp_path / "junk.csv", [["hello", "world"], ["foo", "bar"]])
    with pytest.raises(IngestError):
        analyze([tmp_path / "junk.csv"])
    with pytest.raises(IngestError):
        analyze([tmp_path / "missing.csv"])


def test_outputs_render(tmp_path):
    from finanalyx.export import to_excel, to_json
    from finanalyx.report_html import render_html
    from finanalyx.report_text import render_text

    a = analyze([SAMPLES / "meridian_retail_financials.xlsx"])
    text = render_text(a, verbose=True)
    assert "Financial Health" in text and "Current Ratio" in text
    text.encode("ascii")  # the terminal dashboard must stay ASCII-safe
    page = render_html(a)
    assert page.startswith("<!doctype html>") and "Key trends" in page
    data = json.loads(to_json(a))
    assert data["ratios"]["current_ratio"]["by_year"]["2025"]["value"] == pytest.approx(1790 / 1100)
    to_excel(a, tmp_path / "out.xlsx")
    assert (tmp_path / "out.xlsx").stat().st_size > 0


def test_pdf_text_statement(tmp_path):
    pytest.importorskip("pdfplumber")
    plt = pytest.importorskip("matplotlib.pyplot")
    lines = ["Statement of Profit and Loss", "(in millions)", "                     FY2023    FY2024",
             "Revenue                1,000     1,150", "Cost of sales          (600)     (680)",
             "Operating income         150       180", "Finance costs             10        12",
             "Profit for the year      100       125"]
    fig = plt.figure(figsize=(8.5, 4))
    for i, line in enumerate(lines):
        fig.text(0.05, 0.92 - i * 0.1, line, family="monospace", fontsize=11)
    fig.savefig(tmp_path / "pl.pdf")
    plt.close(fig)
    a = analyze([tmp_path / "pl.pdf"])
    assert a.data.years == [2023, 2024]
    assert a.data.get("revenue", 2024) == 1150
    assert a.data.get("cogs", 2024) == 680
    assert a.ratios.get("interest_coverage", 2024).value == pytest.approx(15.0)
    assert math.isclose(a.ratios.get("revenue_growth", 2024).value, 0.15)
