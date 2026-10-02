# FinAnalyx

*Automated financial statement analysis - ratios, health score, trend intelligence and live valuation.*

Reads a company's Balance Sheet, P&L and Cash Flow statements and produces:

- a **financial health dashboard** with 17 core ratios and 10 supporting ones, each with a status (Healthy, Watch or Weak),
- a **ranked trend narrative** for multi-year data that picks out patterns raw ratios hide (inflection points, costs outrunning revenue, ROE driven by leverage, receivables growing faster than sales, profits not converting to cash, one-off spikes),
- exports to **terminal**, a **self-contained HTML dashboard**, **JSON** and **Excel**,
- a **web app**, deployable to Vercel, for live analysis of any listed company.

## Web app (live data)

Search any company by name or ticker:

- **US filers** use official **SEC EDGAR** 10-K XBRL data, with 10+ years of history.
- **Every other market** uses **Yahoo Finance**: NSE/BSE (`RELIANCE.NS`, `500325.BO`), LSE (`.L`), TSX (`.TO`) and more.

In **Auto** mode, US tickers try SEC first and fall back to Yahoo, and the report notes when that happens. You can also upload your own statements.

Each company page has:

- **Live quote strip:** the price refreshes every 30s, with an intraday chart and 52-week range. Market cap, P/E, P/B, EV/EBITDA, P/S and FCF yield are recalculated on each tick.
- **Health score:** 0–100 overall and by category, from the latest-year ratio grades.
- **Overview:** key metric tiles with history, revenue/margin/cash/returns charts, and top insights.
- **Ratios:** every metric by year, with health dots. Click a row for its history plotted against its thresholds.
- **Insights:** findings you can filter by severity, category and text, plus year-over-year commentary.
- **Financials:** standardised statements, switchable between values, YoY change and common-size. Hover a figure to see its source line.
- **Notes:** warnings, assumptions, formulas, and a source-to-line-item mapping audit.
- **Export:** Excel, HTML report, JSON, CSV, a share link (the URL encodes the company, years, source, basis and tab), and print to PDF.

### Equity research: what makes a stock rise or fall

These tabs are built for finance students. Each one answers one question about the share price and explains the finance behind the answer.

- **Stock drivers:** eight factors, each scored −2 (headwind) to +2 (tailwind) from explicit, inspectable rules:
  - growth
  - profitability
  - earnings quality
  - financial strength
  - valuation
  - price momentum
  - market risk
  - capital allocation

  Every factor lists the evidence behind its score, explains *why it moves share prices*, and says what to watch. The factors combine into an overall tilt, a **bull case vs bear case**, and a watch list.
- **Sensitivities: what moves the price.** These estimate how much EPS or value changes for:
  - +1 point of net margin
  - a 5% revenue beat or miss, amplified by the company's measured operating leverage
  - +1 point on the cost of debt
  - +1 turn of P/E
  - +1 point of WACC
  - a 10% market fall, scaled by beta
- **Price attribution:** splits the share-price change between fiscal year-ends into **EPS growth vs P/E re-rating**, using ln(P₁/P₀) = ln(EPS₁/EPS₀) + ln(PE₁/PE₀). Stock splits are detected and share counts restated.
- **Valuation lab:**
  - an interactive two-stage **DCF** on FCFF, with sliders for growth, terminal growth, risk-free rate, beta and equity risk premium
  - a **WACC build-up** via CAPM, using the stock's measured beta and the live 10-year Treasury yield for USD
  - a WACC × terminal-growth **sensitivity grid**
  - a **reverse DCF**, i.e. the growth the market is pricing in
  - **bull / base / bear price targets** (revenue × margin × P/E), with editable assumptions and a probability-weighted target
- **Price & risk:**
  - price with 50- and 200-day moving averages, golden or death cross, relative performance vs the local index (S&P 500, NIFTY 50, FTSE 100…), and an underwater drawdown chart
  - returns vs the benchmark over 1M–5Y
  - beta, correlation / R², volatility, Sharpe, Sortino, max drawdown, RSI(14) and 12-1 momentum
- **Scorecards:** **Piotroski F-Score** (9 signals), **Altman Z-Score** (original, using market value) and **Z''-Score** (using book equity), and the **Beneish M-Score** (8 indices, with flags). Every component is shown with its explanation.

**Mixed currencies:** if a share trades in a different currency from its accounts (e.g. Infosys: NSE price in INR, accounts in USD, or London prices in pence), prices are converted at the prevailing exchange rate before any multiple is computed.

**Uploaded statements:** these get the fundamental factors, the scorecards and a DCF. Enter shares and price to get per-share values.

This is a rules-based reading of reported data for learning purposes, not investment advice.

### Run locally

```bash
pip install -r requirements-dev.txt
python -m uvicorn api.index:app --reload     # http://localhost:8000  (API docs at /api/docs)
```

### Deploy to Vercel

The repo is ready to deploy as is:

- `api/index.py` is a FastAPI app that runs as a Python serverless function.
- `public/` is the static frontend, served from Vercel's CDN.
- `vercel.json` routes `/api/*` to the function, with a 60s max duration and 1 GB memory.

Two ways to deploy:

1. **From GitHub (recommended):** push the folder to a GitHub repo. In Vercel, choose **Add New → Project → Import** and accept the defaults (no build command, no output directory). Every push then redeploys.
2. **From the CLI:**
   ```bash
   npm i -g vercel
   vercel login
   vercel          # preview deployment
   vercel --prod   # production
   ```

Set this environment variable under **Settings → Environment Variables**:

| Variable | Why |
|---|---|
| `SEC_USER_AGENT` | The SEC asks automated clients to identify themselves, e.g. `YourApp yourname@yourdomain.com`. A generic default is used if it isn't set. |

Production notes:

- **Caching:** company analyses are cached at Vercel's edge (`s-maxage` 30 min, stale-while-revalidate 1 day), quotes for 15s, and searches for 1 day. Warm function instances also keep an in-memory cache, so repeat lookups are fast and stay within upstream rate limits.
- **Uploads:** limited to 4 MB per request, because Vercel caps request bodies at 4.5 MB. Files are processed in a temporary directory and never stored.
- **Yahoo Finance:** this is an unofficial public endpoint. If it rate-limits Vercel's IP addresses, the UI shows a clear error and the SEC and upload paths keep working. For guaranteed global coverage, add a paid provider as another module in `finanalyx/providers/` (same `CompanyData` interface).
- **Valuation multiples:** these use the live price, the latest reported share count and the latest fiscal-year fundamentals, not trailing-twelve-month figures.
- **Tests:** `python -m pytest`. The API tests stub the data providers, so they run offline.

## Command-line quick start

```bash
pip install -r requirements-dev.txt
python samples/generate_samples.py            # writes the two sample companies

python -m finanalyx analyze samples/northwind --company "Northwind Industries" \
       --html output/northwind.html --xlsx output/northwind.xlsx --json output/northwind.json
python -m finanalyx analyze samples/meridian_retail_financials.xlsx -v
```

| Command | Purpose |
|---|---|
| `analyze INPUTS... [--html F] [--json F] [--xlsx F]` | Analyze files or folders |
| `  --company NAME` | Report title (default: guessed from the file name) |
| `  --mapping map.json` | Map unusual labels: `{"Net turnover from ops": "revenue"}` |
| `  --basis average\|ending` | Balance used in ROE/ROA/turnover ratios (default `average`) |
| `  -v` / `-q` | Verbose output (all findings, YoY, line items) / no terminal output |
| `template DIR` | Write blank CSV templates to fill in |
| `items` | List recognised line items and their keys (for `--mapping`) |

Python API: `from finanalyx import analyze; a = analyze(["statements/"])`, which returns `a.data`, `a.ratios` and `a.trends`.

## Input format

**Supported:** CSV/TSV, Excel (`.xlsx`, `.xlsm`, `.xls`, one sheet per statement or one sheet per file), and text-based PDF (best-effort; scanned PDFs need OCR first). A folder is read recursively.

**Layout:** line items in the first column and one column per fiscal year. The parser also handles:

- title, company and units rows above the header (units such as "USD in millions" or "₹ in crores" are detected),
- a **Note** column between labels and figures,
- years newest-first or oldest-first, or **years as rows** (the table is transposed automatically),
- headers like `FY25`, `FY2025`, `FY 2024-25` (counted as FY25), `2025`, `Mar-25`, `31-03-2025`, real Excel dates, `Year ended 31 March 2025`. Quarterly, TTM and "YoY %" columns are ignored,
- `(1,234)` negatives, currency symbols, `-` or `nil` (read as 0) versus blank or `n/a` (read as missing),
- **one file per year** (five annual filings are merged by year; where years overlap, the most recent filing wins, since it carries any restatements),
- Ind-AS style duplicate labels: "Borrowings" under *Current liabilities* becomes short-term debt, and under *Non-current liabilities* it becomes long-term debt.

The statement type comes from the file or sheet name (e.g. `balance_sheet.csv`, sheet `P&L`). Failing that, it is inferred from the line items. Labels are matched against about 300 synonyms (US GAAP, IFRS and Ind-AS wording), with a cautious fuzzy fallback for typos. "Total non-current assets" is never mistaken for "Total current assets". Every mapping is listed in the HTML report's audit section.

## Metrics

| Category | Metric | Formula | Healthy / Weak |
|---|---|---|---|
| Liquidity | Current Ratio | Current Assets / Current Liabilities | ≥1.5x / <1.0x |
| | Quick Ratio | (Current Assets − Inventory) / Current Liabilities | ≥1.0x / <0.7x |
| Solvency | Debt/Equity | Total Debt / Total Equity | ≤1.0x / >2.0x |
| | Debt Ratio | Total Debt / Total Assets | ≤0.4 / >0.6 |
| | Interest Coverage | EBIT / Interest Expense | ≥5x / <2x |
| Profitability | ROE | Net Income / Avg Equity | ≥15% / <8% |
| | ROA | Net Income / Avg Total Assets | ≥7% / <3% |
| | Net Profit Margin | Net Income / Revenue | ≥10% / <5% |
| | EBITDA Margin | (EBIT + D&A) / Revenue | ≥20% / <10% |
| Efficiency | Inventory Turnover | COGS / Avg Inventory | – |
| | Receivable Turnover | Revenue / Avg Receivables | – |
| | Asset Turnover | Revenue / Avg Total Assets | – |
| Growth | Revenue, Profit, Asset CAGR | (End / Start)^(1/years) − 1 | ≥10% / <0% |
| | YoY growth (revenue, profit, assets) | Value_t / Value_t−1 − 1 | |

Supporting metrics (these feed the narrative): gross margin, EBIT margin, opex/revenue, DSO, DIO, OCF/net income, FCF margin, capex/revenue, net debt/EBITDA, equity multiplier.

Thresholds are generic rules of thumb that apply across industries. Compare against sector peers before drawing conclusions.

## Assumptions and edge cases

Every assumption that is actually applied is listed in the report's "Assumptions" section.

- **Averages:** ROE, ROA and turnover ratios use the average of opening and closing balances. The first year has no opening balance, so it uses the closing balance, and the report says so. Use `--basis ending` to use closing balances throughout.
- **Total Debt:** short-term borrowings + current portion of long-term debt + long-term debt, or a reported "Total debt" line if one exists. Lease liabilities are excluded unless they are reported as debt. If no debt lines exist, debt ratios show **n/a** (not 0), with a hint to add a zero row if the company is debt-free.
- **EBITDA:** calculated as EBIT + D&A for consistency. If this differs from a reported (often "adjusted") EBITDA, the report flags it.
- **Derived items** (each flagged as derived, with its formula in the hover text):
  - Revenue, COGS and gross profit from each other
  - EBIT = PBT + interest
  - Opex = gross profit − EBIT
  - Equity = assets − liabilities, and similar balance-sheet identities
  - FCF = OCF − capex
  - Net debt = total debt − cash − short-term investments
- **Sign handling:** expense lines shown as negatives (e.g. `(600)` COGS or capex) are converted to positive amounts.
- **Opex that includes COGS** (the US "total costs and expenses" layout) is detected and corrected.
- **n/a vs n/m:** *n/a* means an input is missing. *n/m* means a value is not meaningful: ROE or D/E on negative equity, growth from a zero or negative base, CAGR when either endpoint is a loss, coverage when there is no interest expense.
- **Data-quality checks:**
  - the balance sheet balances,
  - current items do not exceed their totals,
  - reported gross profit matches revenue − COGS,
  - revenue is not zero or negative,
  - equity is not negative,
  - no fiscal years are missing (CAGR uses the actual gap between years),
  - all statements use the same units,
  - core items and statements are present.

## Trend narrative

These run whenever there are at least 2 years of data. Detectors that look for multi-year patterns need 3–4 or more. Each finding has a severity (concern, watch, positive or note) and a score. Findings that involve the latest year rank higher.

| Detector | Examples of what it finds |
|---|---|
| Revenue | Unbroken growth, a year that broke a growth streak, recovery after a dip, growth accelerating or decelerating |
| Cost structure | Opex or COGS growing faster than revenue in specific years, and the effect on margins (e.g. *"Revenue increased consistently, but operating expenses grew faster than revenue in FY25"*) |
| Margins | Expanding or contracting every year, or peak-and-fade and trough-and-recovery **inflection points** |
| Profit vs revenue | Profit CAGR vs revenue CAGR, net income falling while revenue rose, below-the-line divergence from EBIT |
| Returns | ROE change broken down with **DuPont** analysis (margin × turnover × leverage), flagging ROE gains that come from leverage |
| Working capital | Receivables or inventory growing faster than sales or COGS, and DSO/DIO moving by more than a few days |
| Leverage | Debt jumps (and whether capex was debt-funded), D/E trend, interest coverage deterioration, net debt/EBITDA |
| Liquidity, efficiency | Current ratio crossing 1.5x or 1.0x, assets growing faster than revenue |
| Cash flow | OCF/NI conversion, profit vs cash divergence, negative FCF, dividends larger than FCF |
| Anomalies | One-off spike-and-reverse moves, statistical outliers |

## Project layout

```
api/index.py      FastAPI app (Vercel serverless function; also serves public/ locally)
public/           web UI: index.html, assets/app.js + research.js (panels), app.css + research.css, samples/
vercel.json       routing, function limits, security headers
finanalyx/
  providers/      live data: sec.py (SEC EDGAR XBRL), yahoo.py (Yahoo Finance), base.py (HTTP, cache)
  research.py     orchestrates market data, scorecards, valuation and drivers (with FX conversion)
  drivers.py      8-factor stock-driver scorecard, bull/bear case, watch list
  valuation.py    WACC (CAPM), two-stage DCF, reverse DCF, scenarios, EPS-vs-P/E attribution, sensitivities
  market.py       returns, beta, volatility, Sharpe/Sortino, drawdown, moving averages, RSI
  scores.py       Piotroski F-Score, Altman Z / Z'', Beneish M-Score
  ingest.py       file reading, header/period/number parsing, units, statement detection
  schema.py       canonical line items + synonyms
  mapping.py      label -> line-item matching (exact, override, guarded fuzzy)
  model.py        merge tables, sign normalisation, derivations, validation
  ratios.py       metric definitions, thresholds, calculation
  trends.py       narrative trend detectors, executive summary, YoY commentary
  report_text.py  terminal dashboard      report_html.py  HTML dashboard
  export.py       JSON / Excel            cli.py, analyzer.py  entry points
samples/          generator + two sample companies (clean CSVs, messy Ind-AS workbook)
tests/            pytest suite (python -m pytest)
```
