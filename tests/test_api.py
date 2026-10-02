"""API tests. Live data providers are stubbed so the suite runs offline and deterministically."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import index  # noqa: E402
from finanalyx import providers  # noqa: E402
from finanalyx.providers import sec  # noqa: E402
from finanalyx.providers.base import CompanyData, ProviderError, build_tables  # noqa: E402

client = TestClient(index.app)


def fake_company(symbol="ACME", source="auto", years=5):
    if symbol == "MISSING":
        raise ProviderError("No data for MISSING", 404)
    ys = range(2021, 2026)
    g = {y: 1.1 ** (y - 2021) for y in ys}
    values = {
        "revenue": {y: 1000e6 * g[y] for y in ys}, "cogs": {y: 600e6 * g[y] for y in ys},
        "ebit": {y: 150e6 * g[y] for y in ys}, "depreciation_amortization": {y: 40e6 for y in ys},
        "interest_expense": {y: 10e6 for y in ys}, "net_income": {y: 100e6 * g[y] for y in ys},
        "cash": {y: 80e6 for y in ys}, "total_current_assets": {y: 400e6 for y in ys},
        "total_current_liabilities": {y: 250e6 for y in ys}, "total_assets": {y: 1500e6 for y in ys},
        "total_equity": {y: 800e6 for y in ys}, "long_term_debt": {y: 300e6 for y in ys},
        "operating_cash_flow": {y: 130e6 * g[y] for y in ys}, "capex": {y: 50e6 for y in ys},
    }
    tables, overrides = build_tables("Stub", values, {k: f"stub:{k}" for k in values}, "USD")
    return CompanyData(symbol=symbol, name="Acme Corp", source="Stub", source_url="https://example.com",
                       currency="USD", tables=tables, overrides=overrides, shares_outstanding=1e8,
                       exchange="NYSE", sector="Industrials")


def fake_history(symbol, range_="5y", interval="1d"):
    """Two years of synthetic daily prices: a steady uptrend with a weekly wiggle."""
    import math
    start, day = 1_700_000_000, 86_400
    drift = 0.0006 if symbol == "ACME" else 0.0004
    out = []
    for i in range(520):
        p = 100 * math.exp(drift * i) * (1 + 0.02 * math.sin(i / 3))
        out.append((start + i * day, p, p))
    return out


@pytest.fixture(autouse=True)
def stub_providers(monkeypatch):
    monkeypatch.setattr(providers, "fetch_company", fake_company)
    monkeypatch.setattr(providers.yahoo, "history", fake_history)
    monkeypatch.setattr(providers.yahoo, "risk_free_rate", lambda cur: (0.04, "test"))
    monkeypatch.setattr(providers, "search", lambda q, limit=8: [{"symbol": "ACME", "name": "Acme Corp",
                                                                  "exchange": "NYSE"}])


def test_health_and_search():
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/search", params={"q": "acme"}).json()["results"][0]["symbol"] == "ACME"


def test_company_json_contract():
    r = client.get("/api/company/ACME")
    assert r.status_code == 200
    assert "s-maxage" in r.headers["cache-control"]
    d = r.json()
    assert d["company_info"]["name"] == "Acme Corp"
    assert d["years"] == [2021, 2022, 2023, 2024, 2025]
    assert d["ratios"]["current_ratio"]["by_year"]["2025"]["value"] == pytest.approx(1.6)
    assert d["ratios"]["revenue_cagr"]["value"] == pytest.approx(0.10)
    assert d["health_score"]["overall"] is not None
    assert d["valuation_inputs"]["net_income"]["year"] == 2025
    assert set(d["headline"]) <= set(d["ratios"])
    # the mapping audit shows the provider's own concept names
    assert any(m["raw_label"] == "stub:revenue" for m in d["mapping"])
    # research layer
    assert d["market"]["benchmark"] == "S&P 500" and d["market"]["beta"]["beta"] > 0
    assert len(d["price_series"]["close"]) > 400
    vm = d["valuation_model"]
    assert vm["wacc"]["wacc"] > 0 and vm["dcf"]["per_share"] > 0
    assert {f["key"] for f in d["drivers"]["factors"]} >= {"growth", "valuation", "momentum", "risk"}
    assert d["drivers"]["label"]
    assert d["scores"]["piotroski"]["score"] >= 0


def test_upload_has_fundamental_research_only():
    files = [("files", (p.name, p.read_bytes())) for p in sorted((ROOT / "public" / "samples").glob("northwind_*.csv"))]
    d = client.post("/api/analyze", files=files).json()
    assert d["market"] is None and d["valuation_model"]["price"] is None
    names = {f["key"]: f for f in d["drivers"]["factors"]}
    assert names["valuation"]["available"] is False and names["growth"]["available"] is True


def test_company_exports():
    r = client.get("/api/company/ACME", params={"format": "xlsx"})
    assert r.status_code == 200 and r.content[:2] == b"PK"
    r = client.get("/api/company/ACME", params={"format": "html"})
    assert r.status_code == 200 and "<!doctype html>" in r.text


def test_company_errors():
    assert client.get("/api/company/MISSING").status_code == 404
    r = client.get("/api/company/bad$ticker")
    assert r.status_code == 400 and "ticker" in r.json()["error"]
    assert client.get("/api/company/ACME", params={"years": 99}).status_code == 422
    assert client.get("/api/company/ACME", params={"format": "exe"}).status_code == 422


def test_upload_and_validation():
    files = [("files", (p.name, p.read_bytes())) for p in sorted((ROOT / "public" / "samples").glob("northwind_*.csv"))]
    r = client.post("/api/analyze", files=files, data={"company": "Northwind"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["company"] == "Northwind" and d["company_info"]["source"] == "Uploaded statements"
    assert client.post("/api/analyze", files=[("files", ("x.exe", b"MZ"))]).status_code == 422
    big = [("files", ("big.csv", b"a" * (4 * 1024 * 1024 + 1)))]
    assert client.post("/api/analyze", files=big).status_code == 422
    junk = [("files", ("junk.csv", b"hello,world\nfoo,bar\n"))]
    r = client.post("/api/analyze", files=junk)
    assert r.status_code == 422 and "error" in r.json()


def test_sec_annual_point_selection():
    units = {"USD": [
        {"start": "2023-10-01", "end": "2024-09-28", "val": 100, "form": "10-K", "filed": "2024-11-01"},
        {"start": "2023-10-01", "end": "2024-09-28", "val": 105, "form": "10-K", "filed": "2025-11-01"},  # restated
        {"start": "2024-06-30", "end": "2024-09-28", "val": 30, "form": "10-K", "filed": "2024-11-01"},   # quarter
        {"start": "2024-09-29", "end": "2025-06-28", "val": 80, "form": "10-Q", "filed": "2025-08-01"},   # 10-Q
    ]}
    pts = sec._annual_points(units, flow=True)
    assert len(pts) == 1 and list(pts.values())[0][0] == 105
    inst = {"USD": [{"end": "2024-09-28", "val": 7, "form": "10-K", "filed": "2024-11-01"},
                    {"start": "2023-10-01", "end": "2024-09-28", "val": 9, "form": "10-K", "filed": "2024-11-01"}]}
    assert list(sec._annual_points(inst, flow=False).values())[0][0] == 7
