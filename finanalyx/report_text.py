"""Plain-text (terminal) dashboard. ASCII only, so it renders in any console."""
from __future__ import annotations

import textwrap

from .analyzer import Analysis
from .model import fy, item_label
from .ratios import CATEGORIES, HEADLINE, METRIC_INDEX, METRICS, NM, fmt_value
from .trends import CONCERN, NEUTRAL, POSITIVE, WATCH

WIDTH = 78
_STATUS = {"good": "  OK  ", "watch": "WATCH ", "weak": " WEAK "}
_SEV = {POSITIVE: "[+]", NEUTRAL: "[ ]", WATCH: "[!]", CONCERN: "[!!]"}


def _rule(ch: str = "-") -> str:
    return ch * WIDTH


def _wrap(text: str, indent: str = "", first: str = "") -> str:
    return textwrap.fill(text, WIDTH, initial_indent=first or indent, subsequent_indent=indent)


def _delta_text(key: str, delta: float | None) -> str:
    if delta is None:
        return ""
    m = METRIC_INDEX[key]
    if m.unit == "%":
        text = f"{delta * 100:+.1f} pp"
    elif m.unit == "days":
        text = f"{delta:+.0f} d"
    else:
        text = f"{delta:+.2f}x"
    # A move that rounds to zero is shown unsigned rather than as "-0.00x".
    return text.lstrip("+-") if not any(c in "123456789" for c in text) else text


def dashboard_lines(a: Analysis) -> list[str]:
    fd = a.data
    years = fd.years
    span = f"{fy(years[0])}-{fy(years[-1])}" if len(years) > 1 else fy(years[0])
    meta = [span, f"figures in {fd.units}" if fd.units else "units as reported",
            f"balances: {a.ratios.basis}"]
    out = [_rule("="), f" {fd.company.upper()} - FINANCIAL HEALTH DASHBOARD", " " + " | ".join(meta), _rule("=")]
    out += ["", f" Financial Health ({fy(years[-1])})" + " " * 21 + f"{'vs prior':>10}   Status", " " + _rule()[1:]]
    for key in HEADLINE:
        m = METRIC_INDEX[key]
        year, v = a.headline_value(key)
        name = m.name
        if m.period:
            name = name + (f" ({v.note.split(',')[0]})" if v.note and v.ok else "")
        elif year is not None and year != years[-1] and v.ok:
            name += f" ({fy(year)})"
        status = _STATUS.get(m.health(v), "")
        delta = _delta_text(key, a.delta(key, year)) if year else ""
        value = fmt_value(m, v)
        if v.status == NM and v.note:
            value = f"n/m ({v.note})" if len(v.note) < 22 else "n/m"
        out.append(f" {name:<34}{value:>12}{delta:>12}   {status}".rstrip())
    return out


def ratio_table_lines(a: Analysis) -> list[str]:
    years = a.data.years
    col = 9
    out = []
    for cat in CATEGORIES:
        metrics = [m for m in METRICS if m.category == cat]
        out += ["", f" {cat.upper()}", " " + _rule()[1:]]
        header = f" {'Metric':<27}" + "".join(f"{fy(y):>{col}}" for y in years)
        out.append(header)
        for m in metrics:
            if m.period:
                v = a.ratios.get(m.key)
                out.append(f" {m.name:<27}{fmt_value(m, v):>{col}}   " + (v.note or ""))
                continue
            cells = "".join(f"{fmt_value(m, a.ratios.get(m.key, y)).replace(' days', 'd'):>{col}}" for y in years)
            out.append(f" {m.name:<27}{cells}")
    return out


def calculation_notes(a: Analysis) -> list[str]:
    """Per-year metric notes grouped as '<note> (FY21): ROE, ROA, ...'."""
    grouped: dict[tuple[str, int], list[str]] = {}
    for m in METRICS:
        if m.period:
            continue
        for y in a.data.years:
            v = a.ratios.get(m.key, y)
            if v.note:
                grouped.setdefault((v.note, y), []).append(m.name)
    by_note: dict[str, tuple[list[int], list[str]]] = {}
    for (note, y), names in sorted(grouped.items(), key=lambda kv: kv[0][1]):
        years, all_names = by_note.setdefault(note, ([], []))
        years.append(y)
        all_names.extend(n for n in names if n not in all_names)
    return [f"{note[0].upper()}{note[1:]} ({', '.join(fy(y) for y in years)}): {', '.join(names)}"
            for note, (years, names) in by_note.items()]


def render_text(a: Analysis, verbose: bool = False, max_insights: int = 10) -> str:
    fd, tr = a.data, a.trends
    out = dashboard_lines(a)

    out += ["", _rule("="), " EXECUTIVE SUMMARY", _rule("=")]
    for line in tr.summary:
        out.append(_wrap(line, "   ", " - "))
    if tr.note:
        out.append(_wrap(tr.note, "   ", " * "))

    out += ["", _rule("="), f" KEY TRENDS & ANOMALIES ({fy(fd.years[0])}-{fy(fd.years[-1])}, most important first)", _rule("=")]
    insights = tr.insights if verbose else tr.insights[:max_insights]
    if not insights:
        out.append("   No trend findings (insufficient multi-year data).")
    for ins in insights:
        tag = _SEV[ins.severity]
        out.append(_wrap(f"{ins.title}", "       ", f" {tag:<5} "))
        if ins.detail and verbose:
            out.append(_wrap(ins.detail, "       "))
    if not verbose and len(tr.insights) > max_insights:
        out.append(f"   ... {len(tr.insights) - max_insights} more (use --verbose or see the HTML report)")
    out.append("   Legend: [!!] concern  [!] watch  [+] positive  [ ] neutral")

    out += ["", _rule("="), " RATIO ANALYSIS", _rule("=")]
    out += ratio_table_lines(a)

    if verbose and tr.yoy:
        out += ["", _rule("="), " YEAR-OVER-YEAR", _rule("=")]
        for y, text in tr.yoy:
            out.append(_wrap(text, "            ", f" {fy(y)} vs {fy(y - 1)}: "))

    if verbose:
        out += ["", _rule("="), " STANDARDISED LINE ITEMS", _rule("=")]
        frame = fd.to_frame()
        out.append(f" {'Item':<30}" + "".join(f"{fy(y):>10}" for y in fd.years))
        for label, row in frame.iterrows():
            cells = "".join(f"{'' if v != v or v is None else f'{v:,.0f}':>10}" for v in row.values)
            out.append(f" {label[:30]:<30}{cells}")

    if fd.assumptions or fd.warnings:
        out += ["", _rule("="), " ASSUMPTIONS & DATA QUALITY", _rule("=")]
        for text in fd.assumptions:
            out.append(_wrap(text, "     ", " (a) "))
        for text in fd.warnings:
            out.append(_wrap(text, "     ", " (w) "))
    notes = calculation_notes(a)
    if notes and verbose:
        out += ["", " Calculation notes:"]
        for text in notes:
            out.append(_wrap(text, "     ", "   - "))
    basis = ("Averages of opening and closing balances" if a.ratios.basis == "average"
             else "Closing (year-end) balances")
    out += ["", f" {basis} are used for ROE, ROA and turnover ratios.",
            " n/a = input missing; n/m = not meaningful (e.g. negative base).", ""]
    return "\n".join(out)
