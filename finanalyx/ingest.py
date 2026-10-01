"""Read CSV / Excel / PDF statements into a uniform table structure.

Each source table becomes a ``ParsedTable``: a list of (row label -> {fiscal
year: value}) plus metadata (detected statement type, units, warnings). The
parser is deliberately tolerant of real-world layouts:

* title / note rows above the header, header not on the first row
* years as columns (usual) **or** years as rows (transposed layouts)
* "FY25", "FY2024-25", "2025", "Mar-25", "31/03/2025", "Dec 31, 2024" headers
* years presented newest-first
* "(1,234)" negatives, currency symbols, thousands separators, dashes for nil
* a "Note" column between the label and the figures
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .schema import BS, CF, IS

SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls", ".pdf"}


class IngestError(Exception):
    """Raised when an input cannot be read at all."""


@dataclass
class RawTable:
    name: str
    source: str
    grid: list[list[Any]]
    hint: str = ""  # file / sheet name, page heading: used for statement detection


@dataclass
class ParsedTable:
    name: str
    source: str
    statement: str | None
    years: list[int]
    # (label, {year: value}, section) - section is "current" / "non current" when the
    # row sits under such a heading, used to disambiguate labels like "Borrowings".
    rows: list[tuple[str, dict[int, float | None], str]]
    units: str | None = None
    period_labels: dict[int, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def latest_year(self) -> int:
        return max(self.years) if self.years else 0


# ----------------------------------------------------------------- cell parsing

_NIL = {"-", "–", "—", "--", "---", "nil", "–-", "−"}
_MISSING = {"", "na", "n/a", "n.a.", "nm", "n.m.", "none", "null", "nan", "#n/a", "#value!", "#div/0!", "#ref!", "x"}
_SCALE_SUFFIX = {"k": 1e3, "m": 1e6, "mn": 1e6, "mm": 1e6, "b": 1e9, "bn": 1e9}
_NUMBER_RE = re.compile(r"^[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?$", re.I)


def _is_blank(cell: Any) -> bool:
    if cell is None:
        return True
    if isinstance(cell, float) and math.isnan(cell):
        return True
    return isinstance(cell, str) and not cell.strip()


def parse_number(cell: Any) -> float | None:
    """Parse a financial figure. Dashes / 'nil' mean zero; blanks and 'n/a' mean missing."""
    if _is_blank(cell):
        return None
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if math.isfinite(cell) else None
    s = str(cell).strip().lower()
    if s in _MISSING:
        return None
    if s in _NIL:
        return 0.0
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = s.replace("−", "-").replace("–", "-")
    s = re.sub(r"(?:usd|inr|eur|gbp|rs\.?|[$€£₹¥])", "", s)
    s = s.replace(",", "").replace(" ", "").replace(" ", "").replace("'", "")
    if s.endswith("-") and len(s) > 1:  # trailing minus: "1234-"
        negative, s = True, s[:-1]
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    scale = 1.0
    if s.endswith("%"):
        s, scale = s[:-1], 0.01
    else:
        m = re.match(r"^(.*\d)(k|mn|mm|m|bn|b)$", s)
        if m:
            s, scale = m.group(1), _SCALE_SUFFIX[m.group(2)]
    if not _NUMBER_RE.match(s):
        return None
    value = float(s) * scale
    return -abs(value) if negative else value


_MONTHS = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
_PERIOD_EXCLUDE = re.compile(r"\b(?:Q[1-4]|[1-4]Q|H[12]|QUARTER|HALF|9M|6M|3M|YTD|TTM|LTM|CHANGE|GROWTH|VAR|VARIANCE|YOY)\b")


def _yy(token: str) -> int:
    y = int(token)
    if y < 100:
        y += 1900 if y > 50 else 2000
    return y


def parse_period(cell: Any) -> int | None:
    """Return the fiscal year a header cell refers to, or None.

    A fiscal year spanning two calendar years ("FY2024-25") is labelled by the
    year in which it ends (2025), as is a period-end date ("31-Mar-2025").
    """
    if _is_blank(cell) or isinstance(cell, bool):
        return None
    if isinstance(cell, (dt.date, dt.datetime, pd.Timestamp)):
        return cell.year if 1950 <= cell.year <= 2100 else None
    if isinstance(cell, (int, float)):
        if float(cell).is_integer() and 1950 <= cell <= 2100:
            return int(cell)
        return None
    s = str(cell).strip().upper()
    if not s or len(s) > 48 or "%" in s or _PERIOD_EXCLUDE.search(s):
        return None
    if re.fullmatch(r"(?:19|20)\d{2}\.0", s):
        return int(float(s))
    # 2024-25, FY2024/25, 2024-2025
    m = re.search(r"((?:19|20)\d{2})\s*[-/–]\s*(\d{4}|\d{2})\b(?![-/]\d)", s)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if end == start + 1 or end == (start + 1) % 100:
            return start + 1
    # ISO date 2025-03-31
    m = re.search(r"\b((?:19|20)\d{2})[-/.]\d{1,2}[-/.]\d{1,2}\b", s)
    if m:
        return int(m.group(1))
    # 31/03/2025, 31-03-25
    m = re.search(r"\b\d{1,2}[/.-]\d{1,2}[/.-]((?:19|20)\d{2}|\d{2})\b", s)
    if m:
        return _yy(m.group(1))
    # Mar-25, March 2025, Dec 31, 2024, 31 Mar 2025, Year ended 31 March 2025
    m = re.search(rf"\b(?:{_MONTHS})[A-Z]*\.?[\s\-'/,]*(?:\d{{1,2}}(?:ST|ND|RD|TH)?[\s,]+)?((?:19|20)\d{{2}}|\d{{2}})\b", s)
    if m:
        return _yy(m.group(1))
    # FY25, FY 2025, FY'25, Fiscal 2025
    m = re.search(r"\b(?:FY|F\.Y\.|FISCAL(?:\s+YEAR)?|YEAR)\s*[-']?\s*((?:19|20)\d{2}|\d{2})\b", s)
    if m:
        return _yy(m.group(1))
    # 2025, 2025A, 2026E, CY2025, 2025 (Restated)
    stripped = re.sub(r"\([^)]*\)", "", s).strip()
    m = re.fullmatch(r"(?:CY|YE)?\s*((?:19|20)\d{2})\s*[AEFPR]?", stripped)
    if m:
        return int(m.group(1))
    return None


def _has_explicit_period_marker(cell: Any) -> bool:
    if isinstance(cell, (dt.date, dt.datetime, pd.Timestamp)):
        return True
    s = str(cell).upper()
    return bool(re.search(rf"FY|FISCAL|YEAR|{_MONTHS}|\d{{1,2}}[/.-]\d{{1,2}}[/.-]", s))


# ---------------------------------------------------------------- table parsing

def _clean_grid(grid: list[list[Any]]) -> list[list[Any]]:
    rows = [list(r) for r in grid if any(not _is_blank(c) for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [None] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any(not _is_blank(r[j]) for r in rows)]
    return [[r[j] for j in keep] for r in rows]


def _find_header(grid: list[list[Any]], max_scan: int = 30) -> tuple[int, dict[int, int], list[str]] | None:
    """Locate the row holding fiscal-year column headers.

    Returns (row index, {column index: year}, warnings).
    """
    for i, row in enumerate(grid[:max_scan]):
        found: dict[int, int] = {}
        warnings: list[str] = []
        for j, cell in enumerate(row):
            y = parse_period(cell)
            if y is None:
                continue
            if y in found.values():
                warnings.append(f"Duplicate column for {y} ('{cell}') ignored - first occurrence used.")
                continue
            found[j] = y
        # Figures need a label column to their left; a year in column 0 is a title line.
        if not found or min(found) == 0:
            continue
        others = [c for j, c in enumerate(row) if j not in found and not _is_blank(c)]
        numeric_others = [c for c in others if parse_number(c) is not None and parse_period(c) is None]
        if numeric_others:
            continue  # a data row that happens to contain a year-like number
        if len(found) >= 2:
            span = max(found.values()) - min(found.values())
            if span <= 3 * len(found) + 5:
                return i, found, warnings
        elif len(found) == 1:
            (j, _), = found.items()
            cell = row[j]
            plain_string_year = isinstance(cell, str) and re.fullmatch(r"\s*(?:19|20)\d{2}\s*[AE]?\s*", cell)
            if _has_explicit_period_marker(cell) or plain_string_year or (
                isinstance(cell, (int, float)) and j > 0 and all(_is_blank(c) or isinstance(c, str) for c in row[:j])
            ):
                return i, found, warnings
    return None


def _label_column(grid: list[list[Any]], start_row: int, first_year_col: int) -> int | None:
    best, best_score = None, 0
    for j in range(first_year_col):
        score = sum(
            1 for r in grid[start_row:]
            if isinstance(r[j], str) and r[j].strip() and parse_number(r[j]) is None
        )
        if score > best_score:
            best, best_score = j, score
    return best


_UNITS_RE = re.compile(
    r"(?:in|amounts? in|figures? in|all figures in)?\s*"
    r"(?P<cur>usd|us\$|inr|rs\.?|eur|gbp|\$|₹|€|£)?\s*'?\s*"
    r"(?P<unit>thousands?|millions?|billions?|crores?|lakhs?|lacs|mn|bn|'?000s?|k)\b",
    re.I,
)


def detect_units(texts: list[str]) -> str | None:
    for text in texts:
        if not text:
            continue
        for m in _UNITS_RE.finditer(text):
            unit = m.group("unit").lower().strip("'")
            if unit in {"k"} and not m.group("cur"):
                continue
            unit = {"thousand": "thousands", "000": "thousands", "000s": "thousands", "k": "thousands",
                    "million": "millions", "mn": "millions", "billion": "billions", "bn": "billions",
                    "crore": "crores", "lakh": "lakhs", "lacs": "lakhs"}.get(unit, unit)
            cur = m.group("cur") or ""
            if not cur:
                c = re.search(r"\b(USD|INR|EUR|GBP|JPY|CNY|AUD|CAD|Rs)\b|([$₹€£¥])", text, re.I)
                cur = (c.group(1) or c.group(2)) if c else ""
            cur = cur.upper().replace("US$", "USD").replace("$", "USD").replace("RS.", "INR")
            cur = {"RS": "INR", "₹": "INR", "€": "EUR", "£": "GBP", "¥": "JPY"}.get(cur, cur)
            return f"{cur} {unit}".strip()
    return None


_STATEMENT_KEYWORDS = (
    (CF, r"cash\s*flows?|\bcf\b|cashflow"),
    (BS, r"balance\s*sheet|financial\s+position|\bbs\b|\bbal\b|assets\s+and\s+liabilities"),
    (IS, r"income\s+statement|profit\s*(?:and|&)\s*loss|\bp\s*&?\s*l\b|\bpnl\b|statement\s+of\s+(?:comprehensive\s+)?income|"
         r"statement\s+of\s+operations|statement\s+of\s+earnings|\bincome\b|\bis\b|earnings|profit"),
)


def detect_statement(text: str) -> str | None:
    t = re.sub(r"[_\-.]+", " ", text.lower())
    for statement, pattern in _STATEMENT_KEYWORDS:
        if re.search(pattern, t):
            return statement
    return None


def _section_of(label: str) -> str | None:
    norm = re.sub(r"[^a-z]+", " ", label.lower()).strip()
    norm = re.sub(r"^(?:total|sub total)\s+", "", norm)
    m = re.fullmatch(r"(non current|current)\s+(?:assets|liabilities)", norm)
    return m.group(1) if m else None


def parse_table(raw: RawTable) -> ParsedTable | None:
    grid = _clean_grid(raw.grid)
    if not grid:
        return None
    header = _find_header(grid)
    transposed = False
    if header is None:
        t = _clean_grid([list(col) for col in zip(*grid)])
        header = _find_header(t)
        if header is not None:
            grid, transposed = t, True
    if header is None:
        return None
    hdr_idx, year_cols, warnings = header
    label_col = _label_column(grid, hdr_idx + 1, min(year_cols))
    if label_col is None:
        return None

    rows: list[tuple[str, dict[int, float | None], str]] = []
    section = ""
    for r in grid[hdr_idx + 1:]:
        label = r[label_col]
        if _is_blank(label) or not isinstance(label, str) or parse_number(label) is not None:
            continue
        values = {y: parse_number(r[j]) for j, y in year_cols.items()}
        heading = _section_of(label)
        if all(v is None for v in values.values()):
            if heading is not None:
                section = heading
            continue  # section heading
        rows.append((label.strip(), values, section))
        if heading is not None or re.match(r"\s*total\b", label, re.I):
            section = ""  # a subtotal closes the section

    context = [str(c) for r in grid[: hdr_idx + 1] for c in r if isinstance(c, str)]
    statement = detect_statement(raw.hint) or detect_statement(" ".join(context[:6]))
    if transposed:
        warnings.append("Years were laid out as rows; the table was transposed.")
    years = sorted(year_cols.values())
    return ParsedTable(
        name=raw.name,
        source=raw.source,
        statement=statement,
        years=years,
        rows=rows,
        units=detect_units([raw.hint, *context]),
        period_labels={y: str(grid[hdr_idx][j]).strip() for j, y in year_cols.items()},
        warnings=warnings,
    )


# ------------------------------------------------------------------ file loading

def _read_csv(path: Path) -> list[list[Any]]:
    last_err: Exception | None = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            sep = "\t" if path.suffix.lower() == ".tsv" else None
            df = pd.read_csv(path, header=None, dtype=str, sep=sep, engine="python",
                             encoding=enc, skip_blank_lines=False, keep_default_na=False)
            return df.values.tolist()
        except UnicodeDecodeError as exc:
            last_err = exc
        except pd.errors.EmptyDataError:
            return []
        except pd.errors.ParserError:
            # Ragged rows (title lines with fewer fields): fall back to the csv module.
            import csv
            with open(path, newline="", encoding=enc) as fh:
                sample = fh.read(4096)
                fh.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                except csv.Error:
                    dialect = csv.excel
                return [row for row in csv.reader(fh, dialect)]
    raise IngestError(f"Could not decode {path.name}: {last_err}")


def _read_excel(path: Path) -> list[tuple[str, list[list[Any]]]]:
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    except ImportError as exc:
        raise IngestError(
            f"Reading {path.suffix} files needs an extra package: {exc}. Try: pip install openpyxl"
        ) from exc
    out = []
    for sheet, df in sheets.items():
        grid = df.astype(object).where(pd.notna(df), None).values.tolist()
        out.append((str(sheet), grid))
    return out


_PDF_NUM = r"\(?-?[$₹€£]?\d[\d,]*(?:\.\d+)?\)?|[-–—]"
_PDF_LINE = re.compile(rf"^(?P<label>.*?[A-Za-z].*?)\s+(?P<nums>(?:(?:{_PDF_NUM})\s*)+)$")


def _pdf_text_grid(text: str) -> list[list[Any]]:
    """Turn the text of a statement page into a grid: header row + label/number rows."""
    grid: list[list[Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        tokens = line.split()
        years = [t for t in re.findall(r"FY\s?'?\d{2,4}(?:-\d{2})?|(?<![\d,.])(?:19|20)\d{2}(?:-\d{2})?(?![\d,.])", line)]
        if len(years) >= 2 and len(years) >= len(tokens) / 2:
            grid.append([""] + years)
            continue
        m = _PDF_LINE.match(line)
        if m:
            nums = re.findall(_PDF_NUM, m.group("nums"))
            grid.append([m.group("label").strip()] + nums)
        else:
            grid.append([line])
    # Right-align numbers so a "Note" column does not shift the years.
    width = max((len(r) for r in grid), default=0)
    aligned = []
    for r in grid:
        if len(r) > 1:
            r = [r[0]] + [None] * (width - len(r)) + r[1:]
        aligned.append(r)
    return aligned


def _read_pdf(path: Path) -> list[tuple[str, list[list[Any]]]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise IngestError("PDF support needs pdfplumber: pip install pdfplumber") from exc
    out: list[tuple[str, list[list[Any]]]] = []
    with pdfplumber.open(path) as pdf:
        for n, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            heading = " ".join(text.splitlines()[:4])
            tables = page.extract_tables() or []
            usable = [t for t in tables if t and _find_header(_clean_grid(t)) is not None]
            if usable:
                for k, t in enumerate(usable, start=1):
                    out.append((f"page {n} table {k} | {heading}", t))
            elif text.strip():
                out.append((f"page {n} | {heading}", _pdf_text_grid(text)))
    if not out:
        raise IngestError(
            f"No text could be extracted from {path.name}. Scanned PDFs need OCR first "
            "(e.g. ocrmypdf), or export the statements to Excel/CSV."
        )
    return out


def load_path(path: str | Path) -> list[RawTable]:
    p = Path(path)
    if not p.exists():
        raise IngestError(f"File not found: {p}")
    if p.is_dir():
        tables: list[RawTable] = []
        for child in sorted(p.iterdir()):
            if child.suffix.lower() in SUPPORTED_EXTENSIONS and not child.name.startswith(("~$", ".")):
                tables.extend(load_path(child))
        if not tables:
            raise IngestError(f"No supported files (CSV, Excel, PDF) found in {p}")
        return tables
    ext = p.suffix.lower()
    if ext in {".csv", ".tsv", ".txt"}:
        return [RawTable(p.name, str(p), _read_csv(p), hint=p.stem)]
    if ext in {".xlsx", ".xlsm", ".xls"}:
        return [RawTable(f"{p.name} > {sheet}", str(p), grid, hint=f"{sheet} {p.stem}")
                for sheet, grid in _read_excel(p)]
    if ext == ".pdf":
        return [RawTable(f"{p.name} > {name}", str(p), grid, hint=name) for name, grid in _read_pdf(p)]
    raise IngestError(f"Unsupported file type '{ext}' for {p.name}. Use CSV, Excel (.xlsx) or PDF.")
