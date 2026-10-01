"""Command-line interface.

    python -m finanalyx analyze samples/northwind --html report.html
    python -m finanalyx analyze bs.csv pl.csv cf.csv --company "Acme" --json out.json
    python -m finanalyx template ./my_company
    python -m finanalyx items
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from . import __version__
from .ingest import IngestError
from .schema import BS, CF, IS, LINE_ITEMS, STATEMENT_NAMES


def _cmd_analyze(args: argparse.Namespace) -> int:
    from .analyzer import analyze
    from .report_text import render_text

    try:
        result = analyze(args.inputs, mapping=args.mapping, company=args.company, basis=args.basis)
    except (IngestError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(render_text(result, verbose=args.verbose))
    written = []
    if args.html:
        from .report_html import render_html
        Path(args.html).write_text(render_html(result), encoding="utf-8")
        written.append(args.html)
    if args.json:
        from .export import to_json
        Path(args.json).write_text(to_json(result), encoding="utf-8")
        written.append(args.json)
    if args.xlsx:
        from .export import to_excel
        to_excel(result, args.xlsx)
        written.append(args.xlsx)
    for path in written:
        print(f"Wrote {Path(path).resolve()}")
    return 0


def _cmd_template(args: argparse.Namespace) -> int:
    out = Path(args.directory)
    out.mkdir(parents=True, exist_ok=True)
    years = [f"FY{y}" for y in range(args.first_year, args.first_year + args.years)]
    for statement, filename in ((BS, "balance_sheet.csv"), (IS, "income_statement.csv"), (CF, "cash_flow.csv")):
        with open(out / filename, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([f"{STATEMENT_NAMES[statement]} (in millions)"] + [""] * len(years))
            w.writerow(["Line item"] + years)
            for item in LINE_ITEMS:
                if item.statement == statement and item.key not in {"ebitda", "total_debt",
                                                                     "total_liabilities_and_equity"}:
                    w.writerow([item.synonyms[0].capitalize()] + [""] * len(years))
    print(f"Blank templates written to {out.resolve()} - fill in the figures and run: "
          f"python -m finanalyx analyze {out}")
    return 0


def _cmd_items(_: argparse.Namespace) -> int:
    for statement in (IS, BS, CF):
        print(f"\n{STATEMENT_NAMES[statement]}")
        for item in LINE_ITEMS:
            if item.statement == statement:
                print(f"  {item.key:<30} {item.label:<30} e.g. {', '.join(item.synonyms[:3])}")
    print("\nUse these keys in a --mapping JSON file: {\"Your row label\": \"item_key\"}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="finanalyx", description="Automated financial statement analyzer")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="analyze Balance Sheet, P&L and Cash Flow statements")
    a.add_argument("inputs", nargs="+", help="CSV / Excel / PDF files, or a folder containing them")
    a.add_argument("--company", help="company name for the report title")
    a.add_argument("--html", metavar="PATH", help="write an interactive HTML dashboard")
    a.add_argument("--json", metavar="PATH", help="write all results as JSON")
    a.add_argument("--xlsx", metavar="PATH", help="write ratios, line items and insights to Excel")
    a.add_argument("--mapping", metavar="JSON", help='custom label mapping, e.g. {"Net turnover": "revenue"}')
    a.add_argument("--basis", choices=["average", "ending"], default="average",
                   help="balance used in ROE/ROA/turnover ratios (default: average of opening and closing)")
    a.add_argument("-v", "--verbose", action="store_true", help="show all findings, YoY commentary and line items")
    a.add_argument("-q", "--quiet", action="store_true", help="do not print the terminal dashboard")
    a.set_defaults(func=_cmd_analyze)

    t = sub.add_parser("template", help="write blank CSV templates to fill in")
    t.add_argument("directory")
    t.add_argument("--first-year", type=int, default=2021)
    t.add_argument("--years", type=int, default=5)
    t.set_defaults(func=_cmd_template)

    i = sub.add_parser("items", help="list recognised line items and their keys")
    i.set_defaults(func=_cmd_items)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    return args.func(args)
