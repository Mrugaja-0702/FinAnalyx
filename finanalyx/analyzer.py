"""End-to-end pipeline: files -> parsed tables -> line items -> ratios -> trends."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .ingest import IngestError, ParsedTable, load_path, parse_table
from .mapping import LabelMapper
from .model import FinancialData, build_financials
from .ratios import CASH, METRIC_INDEX, METRICS, RatioResults, Value, compute_ratios
from .trends import TrendReport, analyze_trends


@dataclass
class Analysis:
    data: FinancialData
    ratios: RatioResults
    trends: TrendReport

    @property
    def company(self) -> str:
        return self.data.company

    def delta(self, key: str, year: int) -> float | None:
        """Change in a per-year metric versus the prior year (None if either side unavailable)."""
        if METRIC_INDEX[key].period:
            return None
        cur, prev = self.ratios.get(key, year), self.ratios.get(key, year - 1)
        if cur.ok and prev.ok:
            return cur.value - prev.value
        return None

    def headline_value(self, key: str) -> tuple[int | None, Value]:
        return self.ratios.latest(key)


def analyze(paths: list[str | Path], mapping: str | Path | dict | None = None, company: str | None = None,
            basis: str = "average") -> Analysis:
    mapper = LabelMapper(mapping) if isinstance(mapping, dict) else LabelMapper.from_file(mapping)
    raw_tables = []
    for p in paths:
        raw_tables.extend(load_path(p))
    parsed, skipped = [], []
    for raw in raw_tables:
        table = parse_table(raw)
        if table is None or not table.rows:
            skipped.append(raw.name)
        else:
            parsed.append(table)
    if not parsed:
        raise IngestError(
            "No figures found. Each statement needs a fiscal-year header row (e.g. 'FY2025', '2025', "
            "'Mar-25') with line items in the first column and numeric values under each year. "
            "Checked: " + ", ".join(skipped)
        )
    fd = build_financials(parsed, mapper, company or _guess_company(paths))
    for name in skipped:
        fd.warn(f"Skipped '{name}': no fiscal-year header or figures found.")
    return _finish(fd, basis)


def analyze_tables(tables: list[ParsedTable], company: str, overrides: dict[str, str] | None = None,
                   basis: str = "average", notes: list[str] | None = None) -> Analysis:
    """Analyze statements that arrive already structured (e.g. from a live data provider)."""
    fd = build_financials(tables, LabelMapper(overrides or {}), company)
    for note in notes or []:
        fd.warn(note)
    return _finish(fd, basis)


def _finish(fd: FinancialData, basis: str) -> Analysis:
    rr = compute_ratios(fd, basis)
    return Analysis(fd, rr, analyze_trends(fd, rr))


_HEALTH_POINTS = {"good": 100.0, "watch": 55.0, "weak": 15.0}


def health_scores(a: Analysis) -> dict:
    """0-100 score per category and overall, from the latest value of each graded metric.

    A simple, transparent heuristic: Healthy = 100, Watch = 55, Weak = 15, averaged.
    Metrics without thresholds or without data are left out.
    """
    by_cat: dict[str, list[float]] = {}
    for m in METRICS:
        if m.good is None or m.category == CASH:
            continue
        _, v = a.ratios.latest(m.key)
        h = m.health(v)
        if h:
            by_cat.setdefault(m.category, []).append(_HEALTH_POINTS[h])
    cats = {c: round(sum(v) / len(v)) for c, v in by_cat.items()}
    overall = round(sum(cats.values()) / len(cats)) if cats else None
    if overall is None:
        label = "Insufficient data"
    elif overall >= 75:
        label = "Strong"
    elif overall >= 55:
        label = "Moderate"
    elif overall >= 35:
        label = "Weak"
    else:
        label = "Distressed"
    return {"overall": overall, "label": label, "categories": cats}


def _guess_company(paths: list[str | Path]) -> str:
    p = Path(paths[0])
    name = p.name if p.is_dir() else p.stem
    stop = {"balance", "sheet", "income", "statement", "statements", "cash", "flow", "financials", "financial",
            "pl", "p&l", "pnl", "bs", "cf", "is", "data", "annual", "report"}
    words = [w for w in re.split(r"[_\-\s]+", name) if w and w.lower() not in stop and not re.fullmatch(r"(fy)?\d+", w.lower())]
    return " ".join(words).title() if words else "Company"
