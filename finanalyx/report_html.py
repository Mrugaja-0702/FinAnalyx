"""Self-contained HTML dashboard (no external assets; works offline, light & dark)."""
from __future__ import annotations

import datetime as dt
import html
import math

from .analyzer import Analysis
from .model import fy, item_label
from .ratios import CATEGORIES, HEADLINE, METRIC_INDEX, METRICS, NM, MetricDef, Value, fmt_value
from .report_text import calculation_notes
from .trends import CONCERN, NEUTRAL, POSITIVE, WATCH

E = html.escape

_HEALTH = {"good": ("good", "&#10003;", "Healthy"), "watch": ("warn", "!", "Watch"), "weak": ("crit", "&#10005;", "Weak")}
_SEV = {CONCERN: ("crit", "&#10005;", "Concern"), WATCH: ("warn", "!", "Watch"),
        POSITIVE: ("good", "&#10003;", "Positive"), NEUTRAL: ("neutral", "&#8226;", "Note")}

CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;
--good:#0ca30c;--good-text:#006300;--warn:#fab219;--crit:#d03b3b;--crit-text:#b42323;--wash:rgba(11,11,11,.04)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--good-text:#0ca30c;--crit-text:#e66767;--wash:rgba(255,255,255,.05)}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;
--good-text:#0ca30c;--crit-text:#e66767;--wash:rgba(255,255,255,.05)}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 16px 64px}
header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:12px;margin-bottom:20px}
h1{font-size:26px;margin:0;overflow-wrap:anywhere;font-weight:650;letter-spacing:-.01em}
h2{font-size:18px;margin:36px 0 12px;font-weight:620}
h3{font-size:14px;margin:0 0 8px;font-weight:620;color:var(--ink2);text-transform:uppercase;letter-spacing:.04em}
.meta{color:var(--ink2);font-size:13px}
.theme-btn{border:1px solid var(--border);background:var(--surface);color:var(--ink2);border-radius:8px;padding:6px 10px;
font:inherit;font-size:13px;cursor:pointer}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px}
.summary p{margin:0 0 8px}.summary p:last-child{margin:0}
.summary strong{font-weight:620}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(170px,100%),1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px;display:flex;
flex-direction:column;gap:4px;min-width:0}
.tile .label{font-size:13px;color:var(--ink2);display:flex;justify-content:space-between;gap:6px}
.tile .value{font-size:28px;font-weight:620;line-height:1.15}
.tile .delta{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.up-good{color:var(--good-text)}.down-bad{color:var(--crit-text)}
.tile svg{margin-top:6px;width:100%;height:34px;overflow:visible}
.badge{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;border-radius:999px;
padding:1px 8px 1px 6px;white-space:nowrap;border:1px solid var(--border);color:var(--ink2)}
.badge i{font-style:normal;display:inline-grid;place-items:center;width:15px;height:15px;border-radius:50%;
font-size:10px;color:#fff}
.badge.good i{background:var(--good)}.badge.warn i{background:var(--warn);color:#0b0b0b}
.badge.crit i{background:var(--crit)}.badge.neutral i{background:var(--muted)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:12px}
.chart svg{width:100%;height:auto;display:block}
.legend{display:flex;gap:14px;font-size:12.5px;color:var(--ink2);margin-bottom:6px;flex-wrap:wrap}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend b{width:10px;height:10px;border-radius:3px;display:inline-block}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.filters button{border:1px solid var(--border);background:var(--surface);color:var(--ink2);border-radius:999px;
padding:4px 12px;font:inherit;font-size:13px;cursor:pointer}
.filters button[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.insights{display:flex;flex-direction:column;gap:8px}
.insight{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;
display:grid;grid-template-columns:auto 1fr;gap:4px 12px}
.insight .title{font-weight:560}
.insight .detail{grid-column:2;color:var(--ink2);font-size:13.5px}
.insight .tags{grid-column:2;display:flex;gap:6px;flex-wrap:wrap;font-size:11.5px;color:var(--muted)}
.insight .tags span{border:1px solid var(--border);border-radius:6px;padding:0 6px}
.tbl-wrap{overflow-x:auto;background:var(--surface);border:1px solid var(--border);border-radius:12px;margin-bottom:14px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:7px 12px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--grid)}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--surface)}
thead th{color:var(--ink2);font-weight:600;font-size:12.5px}
tbody tr:last-child td{border-bottom:none}
td{font-variant-numeric:tabular-nums}
td.na{color:var(--muted)}
td .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:middle}
.dot.good{background:var(--good)}.dot.warn{background:var(--warn)}.dot.crit{background:var(--crit)}
.metric-name{display:flex;flex-direction:column}
.metric-name small{color:var(--muted);font-size:11.5px}
td.spark svg{width:90px;height:22px;vertical-align:middle}
.ratios th:first-child{width:300px}.ratios th:nth-child(2){width:110px}
.yoy{list-style:none;padding:0;margin:0}.yoy li{padding:8px 0;border-bottom:1px solid var(--grid)}
.yoy li:last-child{border:none}.yoy b{display:inline-block;min-width:110px}
details{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 14px;margin-bottom:8px}
summary{cursor:pointer;font-weight:560}
details ul{margin:8px 0 0;padding-left:20px;color:var(--ink2);font-size:13.5px}
details table{margin-top:8px}
.note{color:var(--muted);font-size:12.5px}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);font-size:12.5px;padding:6px 9px;
border-radius:6px;opacity:0;transition:opacity .08s;z-index:9;white-space:pre;line-height:1.45;max-width:320px}
.hit{fill:transparent;cursor:crosshair}.hit:hover{fill:var(--wash)}
@media (max-width:560px){.tile .value{font-size:22px}h1{font-size:21px}.tile{padding:12px}.yoy b{display:block}}
@media print{.filters,.theme-btn{display:none}.card,.tile,.insight,.tbl-wrap{break-inside:avoid}}
"""

JS = """
(()=>{const tip=document.getElementById('tip');
document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');
if(!t){tip.style.opacity=0;return}tip.textContent=t.dataset.tip;tip.style.opacity=1;
const w=tip.offsetWidth,h=tip.offsetHeight;let x=e.clientX+14,y=e.clientY+14;
if(x+w>innerWidth-8)x=e.clientX-w-14;if(y+h>innerHeight-8)y=e.clientY-h-14;
tip.style.left=x+'px';tip.style.top=y+'px'});
document.querySelectorAll('.filters button').forEach(b=>b.addEventListener('click',()=>{
document.querySelectorAll('.filters button').forEach(o=>o.setAttribute('aria-pressed',o===b));
const f=b.dataset.f;document.querySelectorAll('.insight').forEach(c=>{
c.hidden=!(f==='all'||c.dataset.sev===f)})}));
const root=document.documentElement,btn=document.querySelector('.theme-btn');
let saved=null;try{saved=localStorage.getItem('finanalyx-theme')}catch(e){}
if(saved)root.dataset.theme=saved;
btn&&btn.addEventListener('click',()=>{const dark=root.dataset.theme?root.dataset.theme==='dark':
matchMedia('(prefers-color-scheme: dark)').matches;root.dataset.theme=dark?'light':'dark';
try{localStorage.setItem('finanalyx-theme',root.dataset.theme)}catch(e){}});})();
"""


# --------------------------------------------------------------------- helpers

def _nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 0.001:
        ticks.append(round(t, 10))
        t += step
    if ticks[-1] < hi:
        ticks.append(ticks[-1] + step)
    return ticks


def _compact(x: float) -> str:
    a = abs(x)
    if a >= 1e9:
        return f"{x / 1e9:.1f}B"
    if a >= 1e6:
        return f"{x / 1e6:.1f}M"
    if a >= 1e4:
        return f"{x / 1e3:.0f}K"
    return f"{x:,.0f}" if a >= 10 or x == int(x) else f"{x:.1f}"


def _sparkline(points: list[tuple[str, float]], fmt, w: int = 120, h: int = 30, accent: str = "var(--s1)") -> str:
    if len(points) < 2:
        return ""
    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or abs(hi) or 1
    xs = [i * (w - 8) / (len(points) - 1) + 4 for i in range(len(points))]
    ys = [h - 4 - (v - lo) / span * (h - 8) for v in vals]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3.5 if i == len(xs) - 1 else 2.2}" '
        f'fill="{accent if i == len(xs) - 1 else "var(--muted)"}" stroke="var(--surface)" stroke-width="1.5"/>'
        for i, (x, y) in enumerate(zip(xs, ys)))
    hits = "".join(
        f'<rect class="hit" x="{x - (w / len(xs)) / 2:.1f}" y="0" width="{w / len(xs):.1f}" height="{h}" '
        f'data-tip="{E(lbl)}: {E(fmt(v))}"/>' for x, (lbl, v) in zip(xs, points))
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-label="trend">'
            f'<polyline points="{path}" fill="none" stroke="var(--muted)" stroke-width="1.5" '
            f'stroke-linejoin="round" vector-effect="non-scaling-stroke"/>{dots}{hits}</svg>')


def _badge(kind: tuple[str, str, str] | None) -> str:
    if not kind:
        return ""
    cls, icon, label = kind
    return f'<span class="badge {cls}"><i aria-hidden="true">{icon}</i>{label}</span>'


def _delta_html(m: MetricDef, delta: float | None, prev_year: int) -> str:
    if delta is None:
        return '<span class="delta">&nbsp;</span>'
    # Round to display precision first so tiny moves never show as "-0.00x".
    if m.unit == "%":
        delta = round(delta * 100, 1) / 100
        txt = f"{delta * 100:+.1f} pp"
    elif m.unit == "days":
        delta = float(round(delta))
        txt = f"{delta:+.0f} days"
    else:
        delta = round(delta, 2)
        txt = f"{delta:+.2f}x"
    if delta == 0:
        txt = txt.lstrip("+-")
    cls = ""
    if m.higher_is_better is not None and abs(delta) > 1e-9:
        good = (delta > 0) == m.higher_is_better
        cls = "up-good" if good else "down-bad"
    arrow = "&#9650;" if delta > 0 else "&#9660;" if delta < 0 else "&#8211;"
    return f'<span class="delta"><span class="{cls}">{arrow} {txt}</span> vs {fy(prev_year)}</span>'


# ------------------------------------------------------------------ sections

def _tiles(a: Analysis) -> str:
    out = []
    years = a.data.years
    for key in HEADLINE:
        m = METRIC_INDEX[key]
        year, v = a.headline_value(key)
        value = fmt_value(m, v)
        label = m.name
        if m.period:
            base = {"revenue_cagr": "revenue", "profit_cagr": "net_income", "asset_cagr": "total_assets"}[key]
            s = a.data.series(base).dropna()
            spark = _sparkline([(fy(y), x) for y, x in s.items()], _compact)
            sub = f'<span class="delta">{E(v.note)}</span>' if v.note else '<span class="delta">&nbsp;</span>'
        else:
            s = a.ratios.series(key)
            spark = _sparkline([(fy(y), x) for y, x in s.items()], lambda x, m=m: fmt_value(m, x))
            sub = _delta_html(m, a.delta(key, year) if year else None, (year or years[-1]) - 1)
            if year is not None and year != years[-1] and v.ok:
                label += f" ({fy(year)})"
        if v.status == NM:
            value = "n/m"
            sub = f'<span class="delta">{E(v.note)}</span>'
        health = _HEALTH.get(m.health(v))
        out.append(
            f'<div class="tile" title="{E(m.formula)}"><div class="label"><span>{E(label)}</span>{_badge(health)}</div>'
            f'<div class="value">{E(value)}</div>{sub}{spark}</div>')
    return '<div class="tiles">' + "".join(out) + "</div>"


def _bar_chart(a: Analysis) -> str:
    fd = a.data
    rev, ni = fd.series("revenue"), fd.series("net_income")
    years = [y for y in fd.years if y in rev.index or y in ni.index]
    if len(years) < 2:
        return ""
    vals = [v for s in (rev, ni) for v in s.values if not math.isnan(v)]
    ticks = _nice_ticks(min(vals), max(vals))
    W, H, L, R, T, B = 560, 260, 52, 10, 10, 28
    pw, ph = W - L - R, H - T - B
    lo, hi = ticks[0], ticks[-1]
    yy = lambda v: T + (hi - v) / (hi - lo) * ph  # noqa: E731
    band = pw / len(years)
    bw = min(28, band * 0.3)
    parts = [f'<line x1="{L}" x2="{W - R}" y1="{yy(t):.1f}" y2="{yy(t):.1f}" stroke="var(--grid)" stroke-width="1"/>'
             f'<text x="{L - 8}" y="{yy(t) + 4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)">{_compact(t)}</text>'
             for t in ticks]
    parts.append(f'<line x1="{L}" x2="{W - R}" y1="{yy(0):.1f}" y2="{yy(0):.1f}" stroke="var(--axis)" stroke-width="1"/>')
    for i, y in enumerate(years):
        cx = L + band * (i + 0.5)
        for j, (s, color) in enumerate(((rev, "var(--s1)"), (ni, "var(--s2)"))):
            if y not in s.index or math.isnan(s[y]):
                continue
            v = s[y]
            x = cx - bw - 1 + j * (bw + 2)  # 2px surface gap between the pair
            top, bot = (yy(v), yy(0)) if v >= 0 else (yy(0), yy(v))
            hgt = max(bot - top, 1)
            r = min(4, hgt / 2, bw / 2)
            # 4px rounded data-end anchored to the baseline
            if v >= 0:
                d = (f"M{x:.1f},{bot:.1f}V{top + r:.1f}Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f}H{x + bw - r:.1f}"
                     f"Q{x + bw:.1f},{top:.1f} {x + bw:.1f},{top + r:.1f}V{bot:.1f}Z")
            else:
                d = (f"M{x:.1f},{top:.1f}V{bot - r:.1f}Q{x:.1f},{bot:.1f} {x + r:.1f},{bot:.1f}H{x + bw - r:.1f}"
                     f"Q{x + bw:.1f},{bot:.1f} {x + bw:.1f},{bot - r:.1f}V{top:.1f}Z")
            parts.append(f'<path d="{d}" fill="{color}"/>')
        parts.append(f'<text x="{cx:.1f}" y="{H - 8}" text-anchor="middle" font-size="11.5" fill="var(--ink2)">{fy(y)}</text>')
        tip = f"{fy(y)}\nRevenue: {_fmt_amt(rev.get(y))}\nNet income: {_fmt_amt(ni.get(y))}"
        m = a.ratios.get("net_margin", y)
        if m.ok:
            tip += f"\nNet margin: {m.value * 100:.1f}%"
        parts.append(f'<rect class="hit" x="{L + band * i:.1f}" y="{T}" width="{band:.1f}" height="{ph}" data-tip="{E(tip)}"/>')
    units = f" ({E(fd.units)})" if fd.units else ""
    return (f'<div class="card chart"><h3>Revenue &amp; net income{units}</h3><div class="legend">'
            '<span><b style="background:var(--s1)"></b>Revenue</span><span><b style="background:var(--s2)"></b>Net income</span></div>'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Revenue and net income by year">{"".join(parts)}</svg></div>')


def _fmt_amt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"


def _line_chart(a: Analysis) -> str:
    series = [(k, METRIC_INDEX[k].name, c) for k, c in (("gross_margin", "var(--s1)"), ("ebitda_margin", "var(--s2)"),
                                                         ("net_margin", "var(--s3)"))]
    data = {k: a.ratios.series(k) for k, _, _ in series}
    series = [s for s in series if len(data[s[0]]) >= 2]
    years = a.data.years
    if not series or len(years) < 2:
        return ""
    vals = [v * 100 for k, _, _ in series for v in data[k].values]
    ticks = _nice_ticks(min(vals), max(vals))
    W, H, L, R, T, B = 560, 260, 44, 64, 10, 28
    pw, ph = W - L - R, H - T - B
    lo, hi = ticks[0], ticks[-1]
    xx = lambda i: L + (i + 0.5) * pw / len(years)  # noqa: E731
    yy = lambda v: T + (hi - v) / (hi - lo) * ph  # noqa: E731
    parts = [f'<line x1="{L}" x2="{W - R}" y1="{yy(t):.1f}" y2="{yy(t):.1f}" stroke="var(--grid)"/>'
             f'<text x="{L - 8}" y="{yy(t) + 4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)">{t:g}%</text>'
             for t in ticks]
    for k, name, color in series:
        pts = [(xx(i), yy(data[k][y] * 100)) for i, y in enumerate(years) if y in data[k].index]
        parts.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="{color}" '
                     'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        parts += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" stroke="var(--surface)" stroke-width="2"/>'
                  for x, y in pts]
        last_y = years[-1] if years[-1] in data[k].index else data[k].index[-1]
        parts.append(f'<text x="{pts[-1][0] + 9:.1f}" y="{pts[-1][1] + 4:.1f}" font-size="11.5" fill="var(--ink2)">'
                     f'{data[k][last_y] * 100:.1f}%</text>')
    band = pw / len(years)
    for i, y in enumerate(years):
        parts.append(f'<text x="{xx(i):.1f}" y="{H - 8}" text-anchor="middle" font-size="11.5" fill="var(--ink2)">{fy(y)}</text>')
        tip = fy(y) + "".join(f"\n{name}: {data[k][y] * 100:.1f}%" for k, name, _ in series if y in data[k].index)
        parts.append(f'<rect class="hit" x="{L + band * i:.1f}" y="{T}" width="{band:.1f}" height="{ph}" data-tip="{E(tip)}"/>')
    legend = "".join(f'<span><b style="background:{c}"></b>{E(n)}</span>' for _, n, c in series)
    return (f'<div class="card chart"><h3>Margins</h3><div class="legend">{legend}</div>'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Margin trends">{"".join(parts)}</svg></div>')


def _insights(a: Analysis) -> str:
    tr = a.trends
    if not tr.insights:
        return f'<p class="note">{E(tr.note or "No trend findings.")}</p>'
    counts = {s: sum(i.severity == s for i in tr.insights) for s in (CONCERN, WATCH, POSITIVE, NEUTRAL)}
    buttons = [f'<button data-f="all" aria-pressed="true">All ({len(tr.insights)})</button>'] + [
        f'<button data-f="{s}" aria-pressed="false">{_SEV[s][2]} ({n})</button>' for s, n in counts.items() if n]
    cards = []
    for ins in tr.insights:
        if ins.score < 0:
            continue
        tags = [f"<span>{E(ins.category)}</span>"] + [f"<span>{fy(y)}</span>" for y in ins.years[:6]]
        cards.append(
            f'<div class="insight" data-sev="{ins.severity}">{_badge(_SEV[ins.severity])}'
            f'<div class="title">{E(ins.title)}</div>'
            + (f'<div class="detail">{E(ins.detail)}</div>' if ins.detail else "")
            + f'<div class="tags">{"".join(tags)}</div></div>')
    note = f'<p class="note">{E(tr.note)}</p>' if tr.note else ""
    return f'<div class="filters" role="group" aria-label="Filter findings">{"".join(buttons)}</div>{note}' \
           f'<div class="insights">{"".join(cards)}</div>'


def _cell(m: MetricDef, v: Value) -> str:
    if not v.ok:
        label = "n/m" if v.status == NM else "n/a"
        return f'<td class="na" title="{E(v.note)}">{label}</td>'
    health = m.health(v)
    dot = f'<span class="dot {_HEALTH[health][0]}" aria-label="{_HEALTH[health][2]}"></span>' if health else ""
    title = f' title="{E(v.note)}"' if v.note else ""
    return f"<td{title}>{dot}{E(fmt_value(m, v))}</td>"


def _ratio_tables(a: Analysis) -> str:
    years = a.data.years
    out = []
    for cat in CATEGORIES:
        rows = []
        for m in (m for m in METRICS if m.category == cat):
            name = f'<div class="metric-name">{E(m.name)}<small>{E(m.formula)}</small></div>'
            if m.period:
                v = a.ratios.get(m.key)
                shown = fmt_value(m, v)
                health = m.health(v)
                dot = f'<span class="dot {_HEALTH[health][0]}"></span>' if health else ""
                rows.append(f'<tr><td>{name}</td><td></td><td colspan="{len(years)}" style="text-align:left">'
                            f'{dot}<b>{E(shown)}</b> <span class="note">{E(v.note)}</span></td></tr>')
                continue
            cells = "".join(_cell(m, a.ratios.get(m.key, y)) for y in years)
            s = a.ratios.series(m.key)
            spark = _sparkline([(fy(y), x) for y, x in s.items()], lambda x, m=m: fmt_value(m, x), 90, 22)
            rows.append(f'<tr><td>{name}</td><td class="spark">{spark}</td>{cells}</tr>')
        head = "".join(f"<th>{fy(y)}</th>" for y in years)
        out.append(f'<h3 style="margin-top:18px">{E(cat)}</h3><div class="tbl-wrap"><table class="ratios"><thead><tr><th>Metric</th>'
                   f'<th>Trend</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return "".join(out)


def _line_items(a: Analysis) -> str:
    fd = a.data
    frame_keys = [k for k in fd.to_frame().index]
    label_to_key = {item_label(k): k for k in fd.values}
    rows = []
    for label in frame_keys:
        key = label_to_key.get(label)
        cells = []
        for y in fd.years:
            v = fd.get(key, y) if key else None
            src = fd.provenance.get(key, {}).get(y, "")
            cells.append(f'<td class="na">-</td>' if v is None else f'<td title="{E(src)}">{_fmt_amt(v)}</td>')
        derived = any(fd.provenance.get(key, {}).get(y, "").startswith("derived") for y in fd.years)
        tag = ' <small class="note">(derived)</small>' if derived else ""
        rows.append(f"<tr><td>{E(label)}{tag}</td>{''.join(cells)}</tr>")
    head = "".join(f"<th>{fy(y)}</th>" for y in fd.years)
    return (f'<div class="tbl-wrap"><table><thead><tr><th>Line item</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
            '<p class="note">Hover a figure to see the source row it came from, or the formula used to derive it.</p>')


def _methodology(a: Analysis) -> str:
    fd = a.data
    rows = "".join(
        f"<tr><td>{E(m.name)}</td><td style='text-align:left'>{E(m.formula)}</td>"
        f"<td style='text-align:left;white-space:normal;min-width:260px'>{E(m.description)}</td>"
        f"<td>{E(_threshold_text(m))}</td></tr>" for m in METRICS)
    basis = ("Average of opening and closing balances (first year uses closing balance)" if a.ratios.basis == "average"
             else "Closing (year-end) balances")
    parts = [
        '<details open><summary>Formulas &amp; health thresholds</summary>'
        f'<p class="note">Balance-sheet figures in ROE, ROA and turnover ratios: {basis}. '
        'Thresholds are generic, cross-industry rules of thumb - compare against sector peers before drawing conclusions. '
        'n/a = an input is missing; n/m = not meaningful (e.g. growth from a negative base, ROE on negative equity).</p>'
        '<div class="tbl-wrap"><table><thead><tr><th>Metric</th><th style="text-align:left">Formula</th>'
        f'<th style="text-align:left">What it tells you</th><th>Healthy / Weak</th></tr></thead><tbody>{rows}</tbody></table></div></details>'
    ]
    if fd.assumptions:
        parts.append("<details open><summary>Assumptions made (" + str(len(fd.assumptions)) + ")</summary><ul>"
                     + "".join(f"<li>{E(t)}</li>" for t in fd.assumptions) + "</ul></details>")
    notes = calculation_notes(a)
    if notes:
        parts.append("<details><summary>Calculation notes</summary><ul>"
                     + "".join(f"<li>{E(t)}</li>" for t in notes) + "</ul></details>")
    if fd.warnings:
        parts.append(f"<details open><summary>Data quality warnings ({len(fd.warnings)})</summary><ul>"
                     + "".join(f"<li>{E(t)}</li>" for t in fd.warnings) + "</ul></details>")
    used = [r for r in fd.mapping_log if r.used]
    rows = "".join(f"<tr><td>{E(r.raw_label)}</td><td style='text-align:left'>{E(item_label(r.key))}</td>"
                   f"<td style='text-align:left'>{E(r.method)}</td><td style='text-align:left'>{E(r.table)}</td></tr>"
                   for r in used)
    parts.append(f"<details><summary>Line-item mapping audit ({len(used)} rows used)</summary>"
                 '<div class="tbl-wrap"><table><thead><tr><th>Source label</th><th style="text-align:left">Mapped to</th>'
                 '<th style="text-align:left">Match</th><th style="text-align:left">Source table</th></tr></thead>'
                 f"<tbody>{rows}</tbody></table></div></details>")
    if fd.unmatched:
        labels = sorted({label for _, label in fd.unmatched})
        parts.append(f"<details><summary>Rows not used ({len(labels)})</summary>"
                     '<p class="note">These labels did not match a standard line item. If one should, add it to a '
                     '--mapping JSON file, e.g. {"' + E(labels[0]) + '": "revenue"}.</p><ul>'
                     + "".join(f"<li>{E(lbl)}</li>" for lbl in labels) + "</ul></details>")
    return "".join(parts)


def _threshold_text(m: MetricDef) -> str:
    if m.good is None or m.weak is None:
        return "context-dependent"
    f = lambda x: fmt_value(m, x)  # noqa: E731
    if m.higher_is_better:
        return f"≥ {f(m.good)} / < {f(m.weak)}"
    return f"≤ {f(m.good)} / > {f(m.weak)}"


def render_html(a: Analysis) -> str:
    fd, tr = a.data, a.trends
    years = fd.years
    span = f"{fy(years[0])}–{fy(years[-1])}" if len(years) > 1 else fy(years[0])
    meta = [span, f"Figures in {fd.units}" if fd.units else "Units as reported",
            f"Generated by FinAnalyx on {dt.date.today():%d %b %Y}"]
    def _summary_line(line: str) -> str:
        label, sep, rest = line.partition(": ")
        if sep and label in {"Strength", "Watch-point", "Overall"}:
            return f"<p><strong>{E(label)}:</strong> {E(rest)}</p>"
        return f"<p>{E(line)}</p>"

    summary = "".join(_summary_line(line) for line in tr.summary) or f"<p>{E(tr.note)}</p>"
    yoy = "".join(f"<li><b>{fy(y)} vs {fy(y - 1)}</b> {E(t)}</li>" for y, t in tr.yoy)
    charts = _bar_chart(a) + _line_chart(a)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(fd.company)} Financial Health</title><style>{CSS}</style></head>
<body><div id="tip" role="tooltip"></div><main class="wrap">
<header><div><h1>{E(fd.company)} &middot; Financial Health</h1><div class="meta">{' &middot; '.join(E(m) for m in meta)}</div></div>
<button class="theme-btn" type="button">Toggle theme</button></header>
<section class="card summary" aria-label="Executive summary">{summary}</section>
<h2>Financial health &middot; {fy(years[-1])}</h2>{_tiles(a)}
{f'<h2>Trends</h2><div class="charts">{charts}</div>' if charts else ''}
<h2>Key trends &amp; anomalies</h2>{_insights(a)}
<h2>Ratio analysis</h2>{_ratio_tables(a)}
{f'<h2>Year over year</h2><div class="card"><ul class="yoy">{yoy}</ul></div>' if yoy else ''}
<h2>Standardised financials</h2>{_line_items(a)}
<h2>Methodology &amp; data notes</h2>{_methodology(a)}
</main><script>{JS}</script></body></html>"""
