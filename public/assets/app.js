/* FinAnalyx - single-page UI (no build step). */
'use strict';

// ---------------------------------------------------------------- utilities
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fy = (y) => 'FY' + String(y).slice(-2);
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

const SEV = {
  concern: ['crit', '&#10005;', 'Concern'], watch: ['warn', '!', 'Watch'],
  positive: ['good', '&#10003;', 'Positive'], neutral: ['neutral', '&#8226;', 'Note'],
};
const HEALTH = { good: ['good', '&#10003;', 'Healthy'], watch: ['warn', '!', 'Watch'], weak: ['crit', '&#10005;', 'Weak'] };
const CATEGORIES = ['Liquidity', 'Solvency', 'Profitability', 'Efficiency', 'Growth', 'Cash Flow & Supplementary'];
const STATEMENTS = [['income_statement', 'Income statement'], ['balance_sheet', 'Balance sheet'], ['cash_flow', 'Cash flow'], ['derived', 'Derived']];
const QUICK = [['AAPL', 'Apple'], ['MSFT', 'Microsoft'], ['NVDA', 'NVIDIA'], ['TSLA', 'Tesla'], ['RELIANCE.NS', 'Reliance'],
  ['TCS.NS', 'TCS'], ['INFY.NS', 'Infosys'], ['HINDUNILVR.NS', 'HUL']];

const state = {
  data: null, kind: null, key: null, symbol: null,
  params: { years: 5, source: 'auto', basis: 'average' },
  tab: 'overview', upload: { files: [] }, charts: [], cache: new Map(),
  quote: null, quoteTimer: null, insights: { sev: 'all', cat: 'all', q: '' },
  statement: 'income_statement', finMode: 'values',
};

function badge(kind) {
  if (!kind) return '';
  const [cls, icon, label] = kind;
  return `<span class="badge ${cls}"><i aria-hidden="true">${icon}</i>${label}</span>`;
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), 2600);
}

// ------------------------------------------------------------------ number formats
function currencyOf() { return state.data?.company_info?.currency || null; }
function isLive() { return state.kind === 'company'; }

function fmtAmount(v, { compact = true } = {}) {
  if (v == null || !isFinite(v)) return '-';
  const cur = currencyOf();
  if (isLive() && compact) {
    try {
      return new Intl.NumberFormat(undefined, { style: cur ? 'currency' : 'decimal', currency: cur || undefined,
        notation: 'compact', maximumFractionDigits: Math.abs(v) >= 1e3 ? 1 : 2 }).format(v);
    } catch { /* unknown currency code */ }
    return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(v);
  }
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 1 }).format(v);
}

function fmtMetric(m, v, signed = false) {
  if (v == null || !isFinite(v)) return 'n/a';
  const s = signed && v > 0 ? '+' : '';
  if (m.unit === '%') return s + (v * 100).toFixed(1) + '%';
  if (m.unit === 'x') return s + v.toFixed(2) + 'x';
  if (m.unit === 'days') return s + Math.round(v) + ' days';
  return s + fmtAmount(v);
}

function fmtDelta(m, d) {
  if (d == null) return '';
  let txt;
  if (m.unit === '%') { d = Math.round(d * 1000) / 1000; txt = (d * 100).toFixed(1) + ' pp'; }
  else if (m.unit === 'days') { d = Math.round(d); txt = d + ' days'; }
  else { d = Math.round(d * 100) / 100; txt = d.toFixed(2) + 'x'; }
  if (d === 0) return `<span class="flat">&#8211; 0 vs prior</span>`;
  const good = m.higher_is_better == null ? null : (d > 0) === m.higher_is_better;
  const cls = good == null ? 'flat' : good ? 'up' : 'down';
  return `<span class="${cls}">${d > 0 ? '&#9650; +' : '&#9660; '}${txt.replace('-', '')}</span> vs prior year`;
}

function metricRec(key, year) {
  const m = state.data.ratios[key];
  if (!m) return null;
  if (m.period) return { value: m.value, status: m.status, note: m.note, health: m.health };
  return m.by_year?.[String(year)] || null;
}

function seriesOf(key) {
  const m = state.data.ratios[key];
  return state.data.years.map((y) => [y, m?.by_year?.[String(y)]?.value ?? null]).filter(([, v]) => v != null);
}

function itemSeries(key) {
  const it = state.data.line_items[key];
  return state.data.years.map((y) => [y, it?.values?.[String(y)] ?? null]);
}

// --------------------------------------------------------------------------- API
async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  let body = null;
  try { body = await r.json(); } catch { /* non-JSON */ }
  if (!r.ok) throw new Error(body?.error || `Request failed (HTTP ${r.status}).`);
  return body;
}
const api = {
  search: (q, signal) => getJSON(`/api/search?q=${encodeURIComponent(q)}`, { signal }),
  company: (sym, p) => getJSON(`/api/company/${encodeURIComponent(sym)}?${new URLSearchParams(p)}`),
  quote: (sym) => getJSON(`/api/quote/${encodeURIComponent(sym)}`),
  analyze(files, opts, format = 'json') {
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f, f.name));
    fd.append('company', opts.company || '');
    fd.append('basis', opts.basis || 'average');
    fd.append('format', format);
    return fetch('/api/analyze', { method: 'POST', body: fd });
  },
};

// ------------------------------------------------------------------------ search
function attachSearch(input) {
  const list = input.parentElement.querySelector('.search-results');
  let items = [], active = -1, ctrl = null;
  const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); active = -1; };
  const go = (sym) => { close(); input.value = ''; input.blur(); navigate(`/c/${encodeURIComponent(sym)}`); };
  const render = () => {
    if (!items.length) {
      list.innerHTML = `<li class="sr-empty">No matches. Press Enter to try "${esc(input.value.trim().toUpperCase())}" as a ticker.</li>`;
    } else {
      list.innerHTML = items.map((r, i) => `<li role="option" data-i="${i}" aria-selected="${i === active}">
        <span class="sr-sym">${esc(r.symbol)}</span><span class="sr-name">${esc(r.name)}</span>
        <span class="sr-ex">${esc(r.exchange || '')}</span></li>`).join('');
    }
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };
  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 1) { close(); return; }
    ctrl?.abort();
    ctrl = new AbortController();
    try {
      items = (await api.search(q, ctrl.signal)).results || [];
      active = items.length ? 0 : -1;
      if (document.activeElement === input) render();
    } catch (e) { if (e.name !== 'AbortError') { items = []; render(); } }
  }, 220);
  input.addEventListener('input', run);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!items.length) return;
      e.preventDefault();
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      render();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const q = input.value.trim();
      if (active >= 0 && items[active] && !list.hidden) go(items[active].symbol);
      else if (q) go(q.toUpperCase());
    } else if (e.key === 'Escape') { close(); input.blur(); }
  });
  list.addEventListener('mousedown', (e) => {
    const li = e.target.closest('li[data-i]');
    if (li) { e.preventDefault(); go(items[+li.dataset.i].symbol); }
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
}

// ------------------------------------------------------------------------ router
function navigate(path) { location.hash = '#' + path; }

function parseHash() {
  const raw = location.hash.slice(1) || '/';
  const [path, qs] = raw.split('?');
  return { parts: path.split('/').filter(Boolean), params: new URLSearchParams(qs || '') };
}

function companyHash() {
  const p = new URLSearchParams({ years: state.params.years, source: state.params.source, basis: state.params.basis });
  if (state.tab !== 'overview') p.set('tab', state.tab);
  return `#/c/${encodeURIComponent(state.symbol)}?${p}`;
}

async function route() {
  stopQuote();
  const { parts, params } = parseHash();
  if (parts[0] === 'c' && parts[1]) {
    state.params = {
      years: Math.min(15, Math.max(2, +params.get('years') || 5)),
      source: ['auto', 'sec', 'yahoo'].includes(params.get('source')) ? params.get('source') : 'auto',
      basis: params.get('basis') === 'ending' ? 'ending' : 'average',
    };
    state.tab = params.get('tab') || 'overview';
    await loadCompany(decodeURIComponent(parts[1]).toUpperCase());
  } else if (parts[0] === 'upload' && state.kind === 'upload' && state.data) {
    state.tab = params.get('tab') || state.tab || 'overview';
    renderAnalysis();
  } else {
    renderHome();
  }
}

// ---------------------------------------------------------------------- views
function destroyCharts() { state.charts.forEach((c) => c.destroy()); state.charts = []; }

function renderHome() {
  destroyCharts();
  state.data = null; state.kind = null;
  document.title = 'FinAnalyx · Financial health analysis';
  $('#app').innerHTML = `
  <section class="hero">
    <h1>Financial health of <span>any company</span>,<br>analysed in seconds</h1>
    <p>Ratios, a health score, trend narratives and live valuation from official SEC filings and global market data - or from your own statements.</p>
    <div class="hero-search">
      <div class="search" role="search">
        <svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
        <input id="hero-search" type="search" autocomplete="off" spellcheck="false" placeholder="Company name or ticker (AAPL, RELIANCE.NS, 500325.BO)" aria-label="Search companies" role="combobox" aria-expanded="false">
        <ul class="search-results" role="listbox" hidden></ul>
      </div>
    </div>
    <div class="chips">${QUICK.map(([s, n]) => `<button class="chip" data-sym="${s}"><b>${s}</b>${n}</button>`).join('')}</div>
  </section>
  <section class="features">
    ${feature('M3 3v18h18M7 15l4-4 3 3 5-6', 'Live company data', 'US companies from SEC EDGAR 10-K filings (10+ years); global markets incl. NSE/BSE via Yahoo Finance.')}
    ${feature('M12 2a10 10 0 100 20 10 10 0 000-20zm0 5v5l3 3', 'Real-time valuation', 'Live price refreshed every 30 seconds with market cap, P/E, P/B and EV/EBITDA recomputed on each tick.')}
    ${feature('M4 19h16M6 15l3-3 3 2 6-6', '27 ratios and a health score', 'Liquidity, solvency, profitability, efficiency and growth - each graded, with formulas and caveats.')}
    ${feature('M9 18h6M10 22h4M12 2a7 7 0 00-4 12.7V17h8v-2.3A7 7 0 0012 2z', 'Trend intelligence', 'Detects inflection points, margin squeeze, leverage-driven ROE, receivable build-ups and one-offs.')}
  </section>
  <div class="alert info"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/></svg>
    <div><h3>Have private or unlisted company statements?</h3>
    Upload a Balance Sheet, P&amp;L and Cash Flow as CSV, Excel or PDF. <a href="#" id="home-upload">Upload statements</a> or
    <a href="#" data-sample="northwind">try a sample</a>.</div></div>`;
  attachSearch($('#hero-search'));
  $$('.chip[data-sym]').forEach((b) => b.addEventListener('click', () => navigate(`/c/${b.dataset.sym}`)));
  $('#home-upload').addEventListener('click', (e) => { e.preventDefault(); openUpload(); });
  bindSampleLinks($('#app'));
  setTimeout(() => $('#hero-search')?.focus({ preventScroll: true }), 50);
}

function feature(path, title, text) {
  return `<div class="card feature"><div class="ico"><svg viewBox="0 0 24 24"><path d="${path}"/></svg></div>
    <h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
}

function renderLoading(label) {
  destroyCharts();
  $('#app').innerHTML = `
    <div class="company-head"><div style="width:100%;max-width:420px">
      <div class="skeleton" style="height:30px;width:70%"></div>
      <div class="skeleton" style="height:16px;width:50%;margin-top:10px"></div></div></div>
    <p class="loading-msg">${esc(label)}</p>
    <div class="top-grid"><div class="skeleton" style="height:220px"></div><div class="skeleton" style="height:220px"></div></div>
    <div class="tiles" style="margin-top:24px">${'<div class="skeleton" style="height:130px"></div>'.repeat(8)}</div>`;
}

function renderError(message, symbol) {
  destroyCharts();
  const tips = symbol ? `<ul class="notes-list">
      <li>Check the ticker. Non-US listings need an exchange suffix: <b>.NS</b> (NSE), <b>.BO</b> (BSE), <b>.L</b> (London), <b>.TO</b> (Toronto).</li>
      <li>Use the search box to find the exact symbol.</li>
      <li>Banks, funds and very new listings may have incomplete statement data.</li></ul>` : '';
  $('#app').innerHTML = `
    <div class="alert error" role="alert"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>
      <div><h3>We couldn't analyse ${esc(symbol || 'these files')}</h3><div>${esc(message)}</div>${tips}
      <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
        ${symbol ? '<button class="btn" id="retry">Try again</button>' : ''}
        ${symbol && state.params.source !== 'yahoo' ? '<button class="btn" id="try-yahoo">Use Yahoo Finance data</button>' : ''}
        <button class="btn btn-ghost" onclick="location.hash='#/'">Back to search</button>
      </div></div></div>`;
  $('#retry')?.addEventListener('click', () => { state.cache.delete(state.key); route(); });
  $('#try-yahoo')?.addEventListener('click', () => { state.params.source = 'yahoo'; state.tab = 'overview'; location.hash = companyHash(); });
}

async function loadCompany(symbol) {
  state.symbol = symbol;
  state.kind = 'company';
  const key = [symbol, state.params.years, state.params.source, state.params.basis].join('|');
  state.key = key;
  if (!state.cache.has(key)) {
    const where = state.params.source === 'yahoo' ? 'Yahoo Finance'
      : state.params.source === 'sec' ? 'SEC EDGAR' : (symbol.includes('.') ? 'Yahoo Finance' : 'SEC EDGAR filings');
    renderLoading(`Fetching ${symbol} financial statements from ${where}...`);
    try {
      state.cache.set(key, await api.company(symbol, state.params));
    } catch (e) {
      if (state.key === key) renderError(e.message, symbol);
      return;
    }
  }
  if (state.key !== key) return; // user navigated away meanwhile
  state.data = state.cache.get(key);
  renderAnalysis();
  startQuote(symbol);
}

// ------------------------------------------------------------- analysis view
function renderAnalysis() {
  destroyCharts();
  if (state._valFor !== state.data) { state.val = null; state._valFor = state.data; }
  const d = state.data, info = d.company_info || {};
  if (state.tab === 'market' && !d.market) state.tab = 'overview';
  document.title = `${d.company} - Financial Health`;
  const years = d.years;
  const span = years.length > 1 ? `${fy(years[0])}-${fy(years[years.length - 1])}` : fy(years[0]);
  const insightsN = d.insights.filter((i) => i.score >= 0).length;
  const live = state.kind === 'company';
  const fetched = info.fetched_at ? new Date(info.fetched_at).toLocaleString() : '';

  $('#app').innerHTML = `
  <div class="company-head">
    <div>
      <h1>${esc(d.company)}</h1>
      <div class="company-meta">
        ${info.symbol ? `<span class="tag tag-brand">${esc(info.symbol)}</span>` : ''}
        ${info.exchange ? `<span>${esc(info.exchange)}</span>` : ''}
        ${info.sector ? `<span>${esc(info.sector)}${info.industry ? ' · ' + esc(info.industry) : ''}</span>` : ''}
        <span>${span} · ${years.length} fiscal years</span>
        <span class="tag">${info.source_url ? `<a href="${esc(info.source_url)}" target="_blank" rel="noopener">${esc(info.source)}</a>` : esc(info.source || 'Uploaded')}</span>
        ${d.units && !live ? `<span class="tag">${esc(d.units)}</span>` : ''}
        ${info.currency && live ? `<span class="tag">Figures in ${esc(info.currency)}</span>` : ''}
      </div>
      ${fetched ? `<div class="muted small" style="margin-top:4px">Statements retrieved ${esc(fetched)}</div>` : ''}
    </div>
    <div class="controls">
      ${live ? `
      <select class="select" id="ctl-years" aria-label="Years of history">
        ${[3, 5, 10].map((n) => `<option value="${n}" ${state.params.years === n ? 'selected' : ''}>${n} years</option>`).join('')}
      </select>
      <select class="select" id="ctl-source" aria-label="Data source">
        <option value="auto" ${state.params.source === 'auto' ? 'selected' : ''}>Auto source</option>
        <option value="sec" ${state.params.source === 'sec' ? 'selected' : ''}>SEC EDGAR</option>
        <option value="yahoo" ${state.params.source === 'yahoo' ? 'selected' : ''}>Yahoo Finance</option>
      </select>
      <select class="select" id="ctl-basis" aria-label="Balance basis">
        <option value="average" ${state.params.basis === 'average' ? 'selected' : ''}>Avg balances</option>
        <option value="ending" ${state.params.basis === 'ending' ? 'selected' : ''}>Year-end balances</option>
      </select>` : ''}
      <div class="dropdown">
        <button class="btn" id="export-btn" aria-haspopup="true" aria-expanded="false">
          <svg viewBox="0 0 24 24"><path d="M12 4v12m0 0l-4-4m4 4l4-4M4 20h16"/></svg>Export</button>
        <div class="menu" id="export-menu" hidden>
          <button data-export="xlsx"><svg viewBox="0 0 24 24"><path d="M4 4h16v16H4zM4 10h16M10 4v16"/></svg>Excel workbook</button>
          <button data-export="html"><svg viewBox="0 0 24 24"><path d="M6 2h9l5 5v15H6zM14 2v6h6"/></svg>HTML report</button>
          <button data-export="json"><svg viewBox="0 0 24 24"><path d="M8 4c-2 0-2 2-2 4s-2 4-2 4 2 2 2 4 0 4 2 4M16 4c2 0 2 2 2 4s2 4 2 4-2 2-2 4 0 4-2 4"/></svg>JSON data</button>
          <button data-export="csv"><svg viewBox="0 0 24 24"><path d="M4 4h16v16H4zM4 9h16M4 14h16"/></svg>Line items (CSV)</button>
          ${live ? '<button data-export="link"><svg viewBox="0 0 24 24"><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/></svg>Copy share link</button>' : ''}
          <button data-export="print"><svg viewBox="0 0 24 24"><path d="M6 9V3h12v6M6 18H4v-7h16v7h-2M8 14h8v7H8z"/></svg>Print / PDF</button>
        </div>
      </div>
    </div>
  </div>

  <div class="top-grid">
    ${live ? `<div class="card card-pad" id="quote-card">${quoteSkeleton()}</div>` : summaryCard(d)}
    <div class="card card-pad">${healthCard(d)}</div>
  </div>

  <div class="tabs" role="tablist">
    ${[['overview', 'Overview'], ['drivers', 'Stock drivers'], ['valuation', 'Valuation'],
       ...(d.market ? [['market', 'Price &amp; risk']] : []), ['scores', 'Scorecards'], ['ratios', 'Ratios'],
       ['insights', `Insights <span class="count">${insightsN}</span>`],
       ['financials', 'Financials'], ['notes', `Notes &amp; methodology${d.warnings.length ? ` <span class="count">${d.warnings.length}</span>` : ''}`]]
      .map(([k, l]) => `<button class="tab" role="tab" data-tab="${k}" aria-selected="${state.tab === k}">${l}</button>`).join('')}
  </div>
  <div class="panel" id="panel" role="tabpanel"></div>`;

  bindHeader();
  $$('.tab').forEach((b) => b.addEventListener('click', () => setTab(b.dataset.tab)));
  renderPanel();
  if (live && state.quote && state.quote.symbol?.toUpperCase() === state.symbol) paintQuote(state.quote);
}

function bindHeader() {
  const reload = () => { state.tab = state.tab || 'overview'; location.hash = companyHash(); };
  $('#ctl-years')?.addEventListener('change', (e) => { state.params.years = +e.target.value; reload(); });
  $('#ctl-source')?.addEventListener('change', (e) => { state.params.source = e.target.value; reload(); });
  $('#ctl-basis')?.addEventListener('change', (e) => { state.params.basis = e.target.value; reload(); });
  const btn = $('#export-btn'), menu = $('#export-menu');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    btn.setAttribute('aria-expanded', String(!menu.hidden));
  });
  $$('[data-export]', menu).forEach((b) => b.addEventListener('click', () => doExport(b.dataset.export)));
}

function setTab(tab) {
  state.tab = tab;
  $$('.tab').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
  const hash = state.kind === 'company' ? companyHash() : `#/upload${tab !== 'overview' ? '?tab=' + tab : ''}`;
  history.replaceState(null, '', hash);
  renderPanel();
}

function renderPanel() {
  destroyCharts();
  const p = $('#panel');
  ({ overview: panelOverview, drivers: panelDrivers, valuation: panelValuation, market: panelMarket, scores: panelScores,
     ratios: panelRatios, insights: panelInsights, financials: panelFinancials, notes: panelNotes }[state.tab]
    || panelOverview)(p);
}

// ------------------------------------------------------------ health / summary
function scoreColor(v) { return v == null ? cssVar('--muted') : v >= 75 ? cssVar('--good') : v >= 55 ? cssVar('--warn') : cssVar('--crit'); }

function healthCard(d) {
  const hs = d.health_score || {};
  const v = hs.overall;
  const r = 52, c = 2 * Math.PI * r, off = c * (1 - (v || 0) / 100);
  const cats = ['Liquidity', 'Solvency', 'Profitability', 'Growth'];
  return `<div class="card-title">Financial health score</div>
    <div class="score">
      <div class="gauge" role="img" aria-label="Health score ${v ?? 'not available'} out of 100, ${esc(hs.label)}">
        <svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="${r}" stroke="${cssVar('--line-2')}" stroke-width="11"/>
          <circle cx="60" cy="60" r="${r}" stroke="${scoreColor(v)}" stroke-width="11" stroke-dasharray="${c}" stroke-dashoffset="${off}" stroke-linecap="round"/></svg>
        <div class="gauge-val"><div><b>${v ?? '-'}</b><span>${esc(hs.label || '')}</span></div></div>
      </div>
      <div class="cat-bars">${cats.map((cat) => {
        const s = hs.categories?.[cat];
        return `<div class="cat-row"><span>${cat}</span><div class="cat-track"><div class="cat-fill" style="width:${s ?? 0}%;background:${scoreColor(s)}"></div></div><b>${s ?? '-'}</b></div>`;
      }).join('')}</div>
    </div>
    <div class="score-note">Latest-year ratios graded Healthy (100) / Watch (55) / Weak (15) against generic thresholds, averaged by category. Compare with sector peers.</div>`;
}

function summaryCard(d) {
  return `<div class="card-title">Executive summary</div>${summaryList(d)}`;
}

function summaryList(d) {
  const items = d.summary.map((line) => {
    const m = line.match(/^(Strength|Watch-point|Overall): (.*)$/);
    if (!m) return `<li class="lead">${esc(line)}</li>`;
    const kind = m[1] === 'Strength' ? SEV.positive : m[1] === 'Watch-point' ? SEV.watch : null;
    return `<li>${kind ? badge(kind) : '<b>Overall</b>'}<span>${esc(m[2])}</span></li>`;
  });
  return `<ul class="summary-list">${items.join('') || `<li class="muted">${esc(d.trends_note || 'Trend analysis needs at least two years of data.')}</li>`}</ul>`;
}

// ------------------------------------------------------------------- live quote
function quoteSkeleton() {
  return `<div class="card-title">Market <span class="muted small">loading quote...</span></div>
    <div class="skeleton" style="height:40px;width:50%"></div><div class="skeleton" style="height:90px;margin-top:14px"></div>`;
}

function stopQuote() { clearInterval(state.quoteTimer); state.quoteTimer = null; }

function startQuote(symbol) {
  stopQuote();
  const tick = async () => {
    if (document.hidden || state.kind !== 'company' || state.symbol !== symbol) return;
    try {
      const q = await api.quote(symbol);
      if (state.symbol !== symbol) return;
      state.quote = q;
      paintQuote(q);
    } catch (e) {
      const card = $('#quote-card');
      if (card && !state.quote) card.innerHTML = `<div class="card-title">Market</div><p class="muted">Live quote unavailable: ${esc(e.message)}</p>${summaryList(state.data)}`;
    }
  };
  tick();
  state.quoteTimer = setInterval(tick, 30000);
}

function paintQuote(q) {
  const card = $('#quote-card');
  if (!card) return;
  const price = q.price, cur = q.currency;
  const nf = (v, dp = 2) => v == null ? '-' : new Intl.NumberFormat(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(v);
  const chg = q.change ?? 0;
  const cls = chg > 0 ? 'up' : chg < 0 ? 'down' : 'flat';
  const ageMin = q.market_time ? (Date.now() / 1000 - q.market_time) / 60 : 999;
  const liveNow = ageMin < 20;
  const lastTrade = q.market_time ? new Date(q.market_time * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '';
  const lo = q.week52_low, hi = q.week52_high;
  const pos = lo != null && hi != null && hi > lo ? Math.min(100, Math.max(0, (price - lo) / (hi - lo) * 100)) : null;
  card.innerHTML = `
    <div class="card-title">Market <span class="muted small" style="text-transform:none;letter-spacing:0">${esc(q.exchange || '')}</span></div>
    <div class="quote">
      <div>
        <div class="price num">${nf(price)}<small>${esc(cur || '')}</small></div>
        <div class="change ${cls} num">${chg > 0 ? '&#9650; +' : chg < 0 ? '&#9660; ' : ''}${nf(chg)} (${q.change_pct != null ? (q.change_pct > 0 ? '+' : '') + q.change_pct.toFixed(2) : '0.00'}%)</div>
        <div class="live ${liveNow ? '' : 'stale'}"><i></i>${liveNow ? 'Live · refreshes every 30s' : 'Market closed · last trade ' + esc(lastTrade)}</div>
        ${pos != null ? `<div class="range">52-week range<div class="range-bar"><span style="left:${pos}%"></span></div>
          <div class="range-ends num"><span>${nf(lo)}</span><span>${nf(hi)}</span></div></div>` : ''}
      </div>
      <div class="intraday"><canvas id="intraday" aria-label="Intraday price"></canvas></div>
    </div>
    <div class="valuation">${valuationCells(q)}</div>`;
  drawIntraday(q);
}

function valuationCells(q) {
  const d = state.data, vi = d.valuation_inputs || {}, info = d.company_info || {};
  const shares = info.shares_outstanding;
  const finCur = (info.currency || '').toUpperCase(), qCur = (q.currency || '').toUpperCase();
  const price = q.price != null ? q.price / (q.price_divisor || 1) : null;
  const cell = (k, v, title = '') => `<div title="${esc(title)}"><div class="val-k">${k}</div><div class="val-v">${v}</div></div>`;
  if (!shares || price == null) return cell('Valuation', '<span class="muted small">Share count unavailable</span>');
  const mcap = price * shares;
  const mcapTxt = (() => {
    try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: qCur, notation: 'compact', maximumFractionDigits: 2 }).format(mcap); }
    catch { return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 2 }).format(mcap); }
  })();
  const fx = d.valuation_model?.fx;
  let px = price, mcapFin = mcap;
  if (finCur && qCur && finCur !== qCur) {
    if (!(fx && fx.quote?.toUpperCase() === qCur && fx.rate)) {
      return cell('Market cap', mcapTxt) + cell('Multiples', `<span class="muted small">Financials in ${esc(finCur)}, quote in ${esc(qCur)}</span>`);
    }
    px = price / fx.rate;  // convert the live price into the reporting currency
    mcapFin = px * shares;
  }
  const v = (k) => vi[k]?.value;
  const mult = (num, den, label) => den == null || num == null ? 'n/a' : den <= 0 ? 'n/m' : (num / den).toFixed(1) + 'x';
  const ev = mcapFin + (v('total_debt_used') || 0) - (v('cash') || 0) - (v('short_term_investments') || 0);
  const fcfYield = v('free_cash_flow') != null ? (v('free_cash_flow') / mcapFin * 100).toFixed(1) + '%' : 'n/a';
  const fxNote = mcapFin !== mcap ? ` (price converted at ${fx.rate.toFixed(2)} ${qCur}/${finCur})` : '';
  const yr = (k) => vi[k]?.year ? ` (${fy(vi[k].year)})` : '';
  return cell('Market cap', mcapTxt, 'Live price x shares outstanding')
    + cell('P/E', mult(mcapFin, v('net_income')), 'Market cap / net income' + yr('net_income') + fxNote)
    + cell('P/B', mult(mcapFin, v('total_equity')), 'Market cap / shareholders\' equity' + yr('total_equity') + fxNote)
    + cell('EV/EBITDA', mult(ev, v('ebitda')), 'Enterprise value / EBITDA' + yr('ebitda') + fxNote)
    + cell('P/S', mult(mcapFin, v('revenue')), 'Market cap / revenue' + yr('revenue') + fxNote)
    + cell('FCF yield', fcfYield, 'Free cash flow / market cap' + yr('free_cash_flow'));
}

function drawIntraday(q) {
  const el = $('#intraday');
  if (!el || !window.Chart) return;
  state.intraday?.destroy();
  const pts = q.intraday || [];
  if (pts.length < 2) { el.parentElement.innerHTML = '<div class="muted small" style="padding-top:30px;text-align:center">No intraday data yet today</div>'; return; }
  const up = (q.change ?? 0) >= 0;
  const color = up ? cssVar('--good') : cssVar('--crit');
  state.intraday = new Chart(el, {
    type: 'line',
    data: {
      labels: pts.map((p) => new Date(p[0] * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })),
      datasets: [{ data: pts.map((p) => p[1]), borderColor: color, borderWidth: 2, pointRadius: 0, tension: 0.25, fill: false },
        ...(q.previous_close ? [{ data: pts.map(() => q.previous_close), borderColor: cssVar('--axis'), borderDash: [4, 4], borderWidth: 1, pointRadius: 0 }] : [])],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, filter: (i) => i.datasetIndex === 0,
        callbacks: { label: (c) => `${c.parsed.y.toFixed(2)} ${q.currency || ''}` } } },
      interaction: { mode: 'index', intersect: false },
      scales: { x: { display: false }, y: { display: false } },
    },
  });
}

// ------------------------------------------------------------------- panels
function panelOverview(p) {
  const d = state.data;
  const live = state.kind === 'company';
  p.innerHTML = `
    ${live ? `<div class="card card-pad section"><div class="card-title">Executive summary</div>${summaryList(d)}</div>` : ''}
    ${driversSnapshot(d)}
    <h2 class="section-title">Key metrics <span class="muted small" style="font-weight:400">Latest fiscal year · click any metric for history</span></h2>
    <div class="tiles">${d.headline.map(tileHTML).join('')}</div>
    <h2 class="section-title">Trends</h2>
    <div class="chart-grid">
      ${chartCard('c-rev', 'Revenue & net income', [['Revenue', '--s1'], ['Net income', '--s2']])}
      ${chartCard('c-margin', 'Margins', [['Gross', '--s1'], ['EBITDA', '--s2'], ['Net', '--s3']])}
      ${chartCard('c-cash', 'Cash generation', [['Operating cash flow', '--s1'], ['Capex', '--s2'], ['Free cash flow', '--s3']])}
      ${chartCard('c-returns', 'Returns on capital', [['ROE', '--s1'], ['ROA', '--s2']])}
    </div>
    <h2 class="section-title">Top insights <a href="#" id="see-all" class="small" style="font-weight:500">See all ${d.insights.length} &rarr;</a></h2>
    <div class="insights">${d.insights.filter((i) => i.score >= 0).slice(0, 4).map(insightHTML).join('') || '<div class="card empty">No trend findings - more years of data are needed.</div>'}</div>`;
  $$('.tile', p).forEach((t) => {
    t.addEventListener('click', () => openMetric(t.dataset.key));
    t.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMetric(t.dataset.key); } });
  });
  $('#see-all').addEventListener('click', (e) => { e.preventDefault(); setTab('insights'); });
  $$('[data-goto]', p).forEach((b) => b.addEventListener('click', () => { setTab(b.dataset.goto); window.scrollTo({ top: $('.tabs').offsetTop - 70, behavior: 'smooth' }); }));
  drawOverviewCharts();
}

function tileHTML(key) {
  const d = state.data, m = d.ratios[key];
  if (!m) return '';
  const y = m.latest_year ?? d.years[d.years.length - 1];
  const rec = metricRec(key, y) || {};
  let value = rec.status === 'n/m' ? 'n/m' : fmtMetric(m, rec.value);
  let sub;
  let spark;
  if (m.period) {
    sub = `<span>${esc(rec.note || '')}</span>`;
    const base = { revenue_cagr: 'revenue', profit_cagr: 'net_income', asset_cagr: 'total_assets' }[key];
    spark = sparkSVG(itemSeries(base).filter(([, v]) => v != null), (v) => fmtAmount(v));
  } else {
    const prev = metricRec(key, y - 1);
    const delta = rec.value != null && prev?.value != null ? rec.value - prev.value : null;
    sub = rec.status === 'n/m' ? esc(rec.note) : fmtDelta(m, delta);
    spark = sparkSVG(seriesOf(key), (v) => fmtMetric(m, v));
  }
  const latestYear = d.years[d.years.length - 1];
  const label = m.name + (!m.period && y !== latestYear && rec.value != null ? ` (${fy(y)})` : '');
  return `<div class="card tile" tabindex="0" role="button" data-key="${key}" title="${esc(m.formula)}">
    <div class="tile-top"><span>${esc(label)}</span>${badge(HEALTH[rec.health])}</div>
    <div class="tile-val num">${value}</div>
    <div class="tile-delta">${sub || '&nbsp;'}</div>${spark}</div>`;
}

function sparkSVG(points, fmt, w = 200, h = 36) {
  if (points.length < 2) return '<svg class="spark" viewBox="0 0 200 36"></svg>';
  const vals = points.map((p) => p[1]);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || Math.abs(hi) || 1;
  const xs = points.map((_, i) => 4 + i * (w - 8) / (points.length - 1));
  const ys = vals.map((v) => h - 5 - (v - lo) / span * (h - 10));
  const path = xs.map((x, i) => `${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ');
  const last = xs.length - 1;
  const titles = points.map((p, i) => `<circle cx="${xs[i].toFixed(1)}" cy="${ys[i].toFixed(1)}" r="${i === last ? 3.5 : 2}" fill="${i === last ? cssVar('--brand') : cssVar('--muted')}" stroke="${cssVar('--surface')}" stroke-width="1.5"><title>${fy(p[0])}: ${esc(fmt(p[1]))}</title></circle>`).join('');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <polyline points="${path}" fill="none" stroke="${cssVar('--axis')}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>${titles}</svg>`;
}

function chartCard(id, title, legend) {
  return `<div class="card card-pad"><div class="card-title">${esc(title)}</div>
    <div class="legend">${legend.map(([n, c]) => `<span><b style="background:var(${c})"></b>${esc(n)}</span>`).join('')}</div>
    <div class="chart-box"><canvas id="${id}"></canvas></div></div>`;
}

function baseOptions(yFmt) {
  const grid = cssVar('--line-2'), tick = cssVar('--muted');
  return {
    responsive: true, maintainAspectRatio: false, animation: { duration: 350 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { backgroundColor: cssVar('--ink'), titleColor: cssVar('--surface'), bodyColor: cssVar('--surface'),
        padding: 10, boxPadding: 4, usePointStyle: true,
        callbacks: { label: (c) => ` ${c.dataset.label}: ${c.parsed.y == null ? 'n/a' : yFmt(c.parsed.y)}` } },
    },
    scales: {
      x: { grid: { display: false }, border: { color: cssVar('--axis') }, ticks: { color: tick, font: { family: 'Inter', size: 11.5 } } },
      y: { grid: { color: grid }, border: { display: false }, ticks: { color: tick, font: { family: 'Inter', size: 11 }, callback: (v) => yFmt(v), maxTicksLimit: 6 } },
    },
  };
}

function addChart(id, config) {
  const el = document.getElementById(id);
  if (!el || !window.Chart) return;
  state.charts.push(new Chart(el, config));
}

function drawOverviewCharts() {
  if (!window.Chart) return;
  Chart.defaults.font.family = 'Inter, system-ui, sans-serif';
  const d = state.data, labels = d.years.map(fy);
  const vals = (k) => d.years.map((y) => d.line_items[k]?.values?.[String(y)] ?? null);
  const pct = (k) => d.years.map((y) => d.ratios[k]?.by_year?.[String(y)]?.value ?? null);
  const amt = (v) => fmtAmount(v);
  const p100 = (v) => (v * 100).toFixed(0) + '%';
  const bar = (label, data, color) => ({ label, data, backgroundColor: cssVar(color), borderRadius: 4, borderSkipped: 'start', maxBarThickness: 30, categoryPercentage: 0.7, barPercentage: 0.92 });
  const line = (label, data, color) => ({ label, data, borderColor: cssVar(color), backgroundColor: cssVar(color), borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: cssVar('--surface'), pointBorderWidth: 2, tension: 0.2, spanGaps: true });
  const pctOpts = baseOptions(p100);
  pctOpts.plugins.tooltip.callbacks.label = (c) => ` ${c.dataset.label}: ${c.parsed.y == null ? 'n/a' : (c.parsed.y * 100).toFixed(1) + '%'}`;

  addChart('c-rev', { type: 'bar', data: { labels, datasets: [bar('Revenue', vals('revenue'), '--s1'), bar('Net income', vals('net_income'), '--s2')] }, options: baseOptions(amt) });
  addChart('c-margin', { type: 'line', data: { labels, datasets: [line('Gross margin', pct('gross_margin'), '--s1'), line('EBITDA margin', pct('ebitda_margin'), '--s2'), line('Net margin', pct('net_margin'), '--s3')] }, options: pctOpts });
  addChart('c-cash', { type: 'bar', data: { labels, datasets: [bar('Operating cash flow', vals('operating_cash_flow'), '--s1'), bar('Capex', vals('capex'), '--s2'), bar('Free cash flow', vals('free_cash_flow'), '--s3')] }, options: baseOptions(amt) });
  const rOpts = baseOptions(p100);
  rOpts.plugins.tooltip.callbacks.label = pctOpts.plugins.tooltip.callbacks.label;
  addChart('c-returns', { type: 'line', data: { labels, datasets: [line('ROE', pct('roe'), '--s1'), line('ROA', pct('roa'), '--s2')] }, options: rOpts });
}

function panelRatios(p) {
  const d = state.data;
  const years = d.years;
  p.innerHTML = CATEGORIES.map((cat) => {
    const metrics = Object.entries(d.ratios).filter(([, m]) => m.category === cat);
    const rows = metrics.map(([key, m]) => {
      const name = `<div class="metric-cell">${esc(m.name)}<small>${esc(m.formula)}</small></div>`;
      if (m.period) {
        const dot = m.health ? `<span class="dot ${HEALTH[m.health][0]}"></span>` : '';
        const val = m.status === 'n/m' ? 'n/m' : fmtMetric(m, m.value);
        return `<tr class="clickable" data-key="${key}"><td>${name}</td><td></td><td colspan="${years.length}" style="text-align:left">${dot}<b>${val}</b> <span class="muted small">${esc(m.note || '')}</span></td></tr>`;
      }
      const cells = years.map((y) => {
        const r = m.by_year?.[String(y)];
        if (!r || r.value == null) return `<td class="na" title="${esc(r?.note || 'Not available')}">${r?.status === 'n/m' ? 'n/m' : 'n/a'}</td>`;
        const dot = r.health ? `<span class="dot ${HEALTH[r.health][0]}" aria-label="${HEALTH[r.health][2]}"></span>` : '';
        return `<td${r.note ? ` title="${esc(r.note)}"` : ''}>${dot}${fmtMetric(m, r.value)}</td>`;
      }).join('');
      return `<tr class="clickable" data-key="${key}"><td>${name}</td><td class="spark-cell">${sparkSVG(seriesOf(key), (v) => fmtMetric(m, v), 96, 24)}</td>${cells}</tr>`;
    }).join('');
    return `<div class="card table-card"><div class="card-title">${esc(cat)}</div><div class="table-wrap"><table>
      <thead><tr><th style="min-width:250px">Metric</th><th>Trend</th>${years.map((y) => `<th>${fy(y)}</th>`).join('')}</tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
  }).join('') + `<p class="muted small">Dots show Healthy / Watch / Weak against generic thresholds. n/a = input missing; n/m = not meaningful (e.g. negative base). Hover a value for calculation notes; click a row for its history.</p>`;
  $$('tr.clickable', p).forEach((tr) => tr.addEventListener('click', () => openMetric(tr.dataset.key)));
}

function insightHTML(i) {
  const tags = [i.category, ...i.years.slice(0, 6).map(fy)].map((t) => `<span>${esc(t)}</span>`).join('');
  return `<div class="card insight ${i.severity}">${badge(SEV[i.severity])}<div class="insight-title">${esc(i.title)}</div>
    ${i.detail ? `<div class="insight-detail">${esc(i.detail)}</div>` : ''}<div class="insight-tags">${tags}</div></div>`;
}

function panelInsights(p) {
  const d = state.data;
  const all = d.insights.filter((i) => i.score >= 0);
  const cats = [...new Set(all.map((i) => i.category))].sort();
  const count = (s) => all.filter((i) => i.severity === s).length;
  const f = state.insights;
  p.innerHTML = `
    <div class="filters" style="margin-top:16px">
      ${[['all', `All (${all.length})`], ['concern', `Concerns (${count('concern')})`], ['watch', `Watch (${count('watch')})`],
         ['positive', `Positive (${count('positive')})`], ['neutral', `Notes (${count('neutral')})`]]
        .map(([k, l]) => `<button class="chip" data-sev="${k}" aria-pressed="${f.sev === k}">${l}</button>`).join('')}
      <span class="spacer"></span>
      <select class="select" id="ins-cat" aria-label="Category"><option value="all">All categories</option>
        ${cats.map((c) => `<option ${f.cat === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>
      <input class="select" style="background-image:none;padding-right:10px;width:180px" id="ins-q" type="search" placeholder="Filter text..." value="${esc(f.q)}">
    </div>
    <div class="insights" id="ins-list"></div>
    ${d.year_over_year.length ? `<h2 class="section-title">Year over year</h2><div class="card card-pad"><ul class="yoy-list">
      ${d.year_over_year.map((r) => `<li><b>${fy(r.year)} vs ${fy(r.year - 1)}</b><span>${esc(r.text)}</span></li>`).join('')}</ul></div>` : ''}`;
  const draw = () => {
    const q = f.q.toLowerCase();
    const shown = all.filter((i) => (f.sev === 'all' || i.severity === f.sev) && (f.cat === 'all' || i.category === f.cat)
      && (!q || (i.title + ' ' + i.detail).toLowerCase().includes(q)));
    $('#ins-list').innerHTML = shown.map(insightHTML).join('') || '<div class="card empty">No findings match these filters.</div>';
  };
  $$('.chip[data-sev]', p).forEach((b) => b.addEventListener('click', () => {
    f.sev = b.dataset.sev;
    $$('.chip[data-sev]', p).forEach((o) => o.setAttribute('aria-pressed', String(o === b)));
    draw();
  }));
  $('#ins-cat').addEventListener('change', (e) => { f.cat = e.target.value; draw(); });
  $('#ins-q').addEventListener('input', debounce((e) => { f.q = e.target.value; draw(); }, 150));
  draw();
}

function panelFinancials(p) {
  const d = state.data, years = d.years;
  const present = STATEMENTS.filter(([k]) => Object.values(d.line_items).some((it) => it.statement === k));
  if (!present.some(([k]) => k === state.statement)) state.statement = present[0]?.[0];
  p.innerHTML = `
    <div class="filters" style="margin-top:16px">
      ${present.map(([k, l]) => `<button class="chip" data-st="${k}" aria-pressed="${state.statement === k}">${l}</button>`).join('')}
      <span class="spacer"></span>
      <button class="chip" data-mode="values" aria-pressed="${state.finMode === 'values'}">Values</button>
      <button class="chip" data-mode="yoy" aria-pressed="${state.finMode === 'yoy'}">YoY change</button>
      <button class="chip" data-mode="common" aria-pressed="${state.finMode === 'common'}">% of revenue / assets</button>
    </div>
    <div class="card table-card"><div class="table-wrap"><table id="fin-table"></table></div></div>
    <p class="muted small">${isLive() ? `Figures in ${esc(currencyOf() || 'reported currency')}, abbreviated.` : `Figures as reported${d.units ? ' (' + esc(d.units) + ')' : ''}.`}
      Hover a value to see the exact source line or the formula used to derive it. "Derived" rows were computed from accounting identities.</p>`;
  const draw = () => {
    const rows = Object.entries(d.line_items).filter(([, it]) => it.statement === state.statement).sort((a, b) => a[1].order - b[1].order);
    const base = state.statement === 'balance_sheet' ? 'total_assets' : 'revenue';
    const body = rows.map(([key, it]) => {
      const derived = Object.values(it.source || {}).some((s) => String(s).startsWith('derived'));
      const cells = years.map((y) => {
        const v = it.values[String(y)];
        const src = it.source?.[String(y)] || '';
        if (v == null) return '<td class="na">-</td>';
        if (state.finMode === 'yoy') {
          const prev = it.values[String(y - 1)];
          if (prev == null || prev <= 0) return '<td class="na">-</td>';
          const g = v / prev - 1;
          return `<td class="${g < 0 ? 'neg' : ''}" title="${esc(fmtAmount(prev))} &rarr; ${esc(fmtAmount(v))}">${g > 0 ? '+' : ''}${(g * 100).toFixed(1)}%</td>`;
        }
        if (state.finMode === 'common') {
          const b = d.line_items[base]?.values?.[String(y)];
          if (!b) return '<td class="na">-</td>';
          return `<td title="${esc(fmtAmount(v, { compact: false }))}">${(v / b * 100).toFixed(1)}%</td>`;
        }
        return `<td class="${v < 0 ? 'neg' : ''}" title="${esc(src)}\n${esc(fmtAmount(v, { compact: false }))}">${fmtAmount(v)}</td>`;
      }).join('');
      return `<tr><td>${esc(it.label)}${derived ? '<span class="derived">derived</span>' : ''}</td>${cells}</tr>`;
    }).join('');
    $('#fin-table').innerHTML = `<thead><tr><th style="min-width:230px">Line item</th>${years.map((y) => `<th>${fy(y)}</th>`).join('')}</tr></thead><tbody>${body}</tbody>`;
  };
  $$('[data-st]', p).forEach((b) => b.addEventListener('click', () => {
    state.statement = b.dataset.st;
    $$('[data-st]', p).forEach((o) => o.setAttribute('aria-pressed', String(o === b)));
    draw();
  }));
  $$('[data-mode]', p).forEach((b) => b.addEventListener('click', () => {
    state.finMode = b.dataset.mode;
    $$('[data-mode]', p).forEach((o) => o.setAttribute('aria-pressed', String(o === b)));
    draw();
  }));
  draw();
}

function panelNotes(p) {
  const d = state.data, info = d.company_info || {};
  const used = d.mapping.filter((r) => r.used);
  const unmatched = [...new Set(d.unmatched_labels.map((u) => u.label))];
  const methodRows = Object.values(d.ratios).map((m) => `<tr><td>${esc(m.name)}</td><td style="text-align:left">${esc(m.formula)}</td>
    <td style="text-align:left;white-space:normal;min-width:280px">${esc(m.description)}</td>
    <td>${m.good == null ? '<span class="muted">context</span>' : (m.higher_is_better ? '&ge; ' : '&le; ') + fmtMetric(m, m.good) + ' / ' + (m.higher_is_better ? '&lt; ' : '&gt; ') + fmtMetric(m, m.weak)}</td></tr>`).join('');
  p.innerHTML = `
    <div class="section" style="display:grid;gap:12px">
      ${(d.research_notes || []).length ? `<div class="card card-pad"><div class="card-title">Market data notes</div><ul class="notes-list">${d.research_notes.map((w) => `<li>${esc(w)}</li>`).join('')}</ul></div>` : ''}
      ${d.warnings.length ? `<div class="card card-pad"><div class="card-title">Data quality warnings</div><ul class="notes-list">${d.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul></div>` : ''}
      <div class="card card-pad"><div class="card-title">Assumptions applied</div>
        ${d.assumptions.length ? `<ul class="notes-list">${d.assumptions.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : '<p class="muted" style="margin:0">No special assumptions were needed for this data set.</p>'}
        <ul class="notes-list">
          <li>ROE, ROA and turnover ratios use ${d.balance_basis === 'average' ? 'the average of opening and closing balances (the first year uses the closing balance)' : 'year-end balances'}.</li>
          <li>Total debt = short-term borrowings + current portion of long-term debt + long-term debt; lease liabilities are excluded.</li>
          <li>EBITDA = EBIT + depreciation &amp; amortisation, computed consistently rather than taken from "adjusted" figures.</li>
          ${isLive() ? '<li>Valuation multiples use the live price, latest reported shares outstanding and the most recent fiscal-year fundamentals (not trailing-twelve-month).</li>' : ''}
        </ul></div>
      <div class="card card-pad"><div class="card-title">Data source</div>
        <p style="margin:0">${esc(info.source || '')}${info.source_url ? ` - <a href="${esc(info.source_url)}" target="_blank" rel="noopener">view source</a>` : ''}${info.files ? ' - ' + info.files.map(esc).join(', ') : ''}.
        ${info.source === 'SEC EDGAR' ? 'Annual figures from 10-K XBRL filings; where a figure was restated, the most recent filing is used.' : ''}
        ${info.source === 'Yahoo Finance' ? 'Annual statements as standardised by Yahoo Finance; history is typically limited to 4-5 years.' : ''}</p></div>
      <details class="card" open><summary>Formulas &amp; thresholds</summary><div class="details-body"><div class="table-wrap"><table>
        <thead><tr><th>Metric</th><th style="text-align:left">Formula</th><th style="text-align:left">What it tells you</th><th>Healthy / Weak</th></tr></thead>
        <tbody>${methodRows}</tbody></table></div></div></details>
      <details class="card"><summary>Source mapping audit (${used.length})</summary><div class="details-body"><div class="table-wrap"><table>
        <thead><tr><th>Source label / concept</th><th style="text-align:left">Mapped to</th><th style="text-align:left">Match</th><th style="text-align:left">Table</th></tr></thead>
        <tbody>${used.map((r) => `<tr><td style="white-space:normal">${esc(r.raw_label)}</td><td style="text-align:left">${esc(d.line_items[r.key]?.label || r.key)}</td><td style="text-align:left">${esc(r.method)}</td><td style="text-align:left">${esc(r.table)}</td></tr>`).join('')}</tbody>
        </table></div></div></details>
      ${unmatched.length ? `<details class="card"><summary>Rows not used (${unmatched.length})</summary><div class="details-body">
        <p class="muted small">These source rows did not match a standard line item and were ignored.</p>
        <ul class="notes-list">${unmatched.map((u) => `<li>${esc(u)}</li>`).join('')}</ul></div></details>` : ''}
    </div>`;
}

// ------------------------------------------------------------- metric modal
function openMetric(key) {
  const d = state.data, m = d.ratios[key];
  if (!m) return;
  $('#metric-title').textContent = m.name;
  $('#metric-formula').textContent = m.formula;
  const thr = m.good != null ? ` Healthy ${m.higher_is_better ? '&ge;' : '&le;'} ${fmtMetric(m, m.good)}; weak ${m.higher_is_better ? '&lt;' : '&gt;'} ${fmtMetric(m, m.weak)}.` : '';
  $('#metric-desc').innerHTML = esc(m.description) + thr;
  const notes = m.period ? (m.note ? [`${m.note}`] : [])
    : d.years.map((y) => [y, m.by_year?.[String(y)]]).filter(([, r]) => r?.note).map(([y, r]) => `${fy(y)}: ${r.note}`);
  $('#metric-notes').innerHTML = notes.length ? `<ul class="notes-list small">${notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : '';
  openModal('#metric-modal');
  state.metricChart?.destroy();
  if (!window.Chart) return;
  const labels = d.years.map(fy);
  let data, fmt;
  if (m.period) {
    const base = { revenue_cagr: 'revenue', profit_cagr: 'net_income', asset_cagr: 'total_assets' }[key];
    data = d.years.map((y) => d.line_items[base]?.values?.[String(y)] ?? null);
    fmt = (v) => fmtAmount(v);
  } else {
    data = d.years.map((y) => m.by_year?.[String(y)]?.value ?? null);
    fmt = (v) => fmtMetric(m, v);
  }
  const datasets = [{ label: m.period ? d.line_items[{ revenue_cagr: 'revenue', profit_cagr: 'net_income', asset_cagr: 'total_assets' }[key]]?.label : m.name,
    data, borderColor: cssVar('--s1'), backgroundColor: cssVar('--s1'), borderWidth: 2, pointRadius: 5, pointBorderColor: cssVar('--surface'), pointBorderWidth: 2, tension: 0.2, spanGaps: true }];
  if (!m.period && m.good != null) {
    datasets.push({ label: 'Healthy threshold', data: labels.map(() => m.good), borderColor: cssVar('--good'), borderDash: [5, 5], borderWidth: 1.5, pointRadius: 0 });
    datasets.push({ label: 'Weak threshold', data: labels.map(() => m.weak), borderColor: cssVar('--crit'), borderDash: [5, 5], borderWidth: 1.5, pointRadius: 0 });
  }
  const opts = baseOptions(m.unit === '%' ? (v) => (v * 100).toFixed(0) + '%' : m.unit === 'x' ? (v) => v.toFixed(1) + 'x' : fmt);
  opts.plugins.tooltip.callbacks.label = (c) => ` ${c.dataset.label}: ${c.parsed.y == null ? 'n/a' : fmt(c.parsed.y)}`;
  opts.plugins.legend = { display: datasets.length > 1, position: 'bottom', labels: { color: cssVar('--ink-2'), boxWidth: 18, boxHeight: 2 } };
  state.metricChart = new Chart($('#metric-chart'), { type: m.period ? 'bar' : 'line', data: { labels, datasets: m.period ? [{ ...datasets[0], borderRadius: 4, maxBarThickness: 36 }] : datasets }, options: opts });
}

// ------------------------------------------------------------------- export
async function doExport(kind) {
  $('#export-menu').hidden = true;
  const d = state.data;
  const base = (d.company_info?.symbol || d.company).replace(/[^A-Za-z0-9]+/g, '_');
  try {
    if (kind === 'json') return download(new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' }), `${base}_analysis.json`);
    if (kind === 'csv') return download(new Blob([lineItemsCSV()], { type: 'text/csv' }), `${base}_line_items.csv`);
    if (kind === 'print') return window.print();
    if (kind === 'link') { await navigator.clipboard.writeText(location.href); return toast('Link copied to clipboard'); }
    toast('Preparing download...');
    let blob;
    if (state.kind === 'company') {
      const r = await fetch(`/api/company/${encodeURIComponent(state.symbol)}?${new URLSearchParams({ ...state.params, format: kind })}`);
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'Export failed');
      blob = await r.blob();
    } else {
      const r = await api.analyze(state.upload.files, state.upload, kind);
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'Export failed');
      blob = await r.blob();
    }
    download(blob, `${base}_analysis.${kind}`);
  } catch (e) { toast(e.message); }
}

function lineItemsCSV() {
  const d = state.data;
  const q = (s) => `"${String(s).replace(/"/g, '""')}"`;
  const rows = [['Line item', 'Statement', ...d.years.map(fy)].map(q).join(',')];
  Object.values(d.line_items).sort((a, b) => a.order - b.order).forEach((it) => {
    rows.push([q(it.label), q(it.statement), ...d.years.map((y) => it.values[String(y)] ?? '')].join(','));
  });
  return rows.join('\n');
}

function download(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

// ------------------------------------------------------------------- modals
function openModal(sel) {
  const m = $(sel);
  m.hidden = false;
  m._prev = document.activeElement;
  setTimeout(() => (m.querySelector('[data-close].btn') || m.querySelector('button'))?.focus(), 30);
}
function closeModal(m) { m.hidden = true; m._prev?.focus?.(); if (m.id === 'metric-modal') state.metricChart?.destroy(); }

function openUpload() { renderFileList(); openModal('#upload-modal'); }

function renderFileList() {
  const files = state.upload.files;
  $('#file-list').innerHTML = files.map((f, i) => `<li><span>${esc(f.name)} <span class="muted small">${(f.size / 1024).toFixed(0)} KB</span></span>
    <button data-rm="${i}" aria-label="Remove ${esc(f.name)}">&times;</button></li>`).join('');
  $$('[data-rm]').forEach((b) => b.addEventListener('click', (e) => { e.preventDefault(); files.splice(+b.dataset.rm, 1); renderFileList(); }));
  $('#upload-go').disabled = !files.length;
}

function addFiles(list) {
  const ok = /\.(csv|tsv|txt|xlsx|xlsm|xls|pdf)$/i;
  for (const f of list) {
    if (!ok.test(f.name)) { toast(`${f.name}: unsupported file type`); continue; }
    if (!state.upload.files.some((g) => g.name === f.name && g.size === f.size)) state.upload.files.push(f);
  }
  renderFileList();
}

async function runUpload() {
  const files = state.upload.files;
  if (!files.length) return;
  const total = files.reduce((s, f) => s + f.size, 0);
  if (total > 4 * 1024 * 1024) { toast('Files exceed the 4 MB limit'); return; }
  state.upload.company = $('#upload-company').value.trim();
  state.upload.basis = $('#upload-basis').value;
  closeModal($('#upload-modal'));
  stopQuote();
  state.kind = 'upload'; state.symbol = null; state.key = null;
  renderLoading(`Analysing ${files.length} file${files.length > 1 ? 's' : ''}...`);
  try {
    const r = await api.analyze(files, state.upload);
    const body = await r.json().catch(() => null);
    if (!r.ok) throw new Error(body?.error || `Upload failed (HTTP ${r.status}).`);
    state.data = body;
    state.tab = 'overview';
    if (location.hash === '#/upload') renderAnalysis(); else navigate('/upload');
  } catch (e) { renderError(e.message, null); }
}

const SAMPLES = {
  northwind: ['northwind_balance_sheet.csv', 'northwind_income_statement.csv', 'northwind_cash_flow.csv'],
  meridian: ['meridian_retail_financials.xlsx'],
};

async function loadSample(name) {
  try {
    const files = await Promise.all(SAMPLES[name].map(async (f) => {
      const r = await fetch(`/samples/${f}`);
      if (!r.ok) throw new Error('Sample not found');
      return new File([await r.blob()], f);
    }));
    state.upload.files = files;
    $('#upload-company').value = name === 'northwind' ? 'Northwind Industries' : 'Meridian Retail';
    renderFileList();
    if ($('#upload-modal').hidden) openModal('#upload-modal');
  } catch (e) { toast(e.message); }
}

function bindSampleLinks(root) {
  $$('[data-sample]', root).forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); loadSample(a.dataset.sample); }));
}

// --------------------------------------------------------------------- boot
function initTheme() {
  $('#theme-toggle').addEventListener('click', () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('finanalyx-theme', root.dataset.theme); } catch { /* storage unavailable */ }
    if (state.data && $('#panel')) { renderAnalysis(); }
  });
}

function init() {
  attachSearch($('#search'));
  initTheme();
  $('#upload-open').addEventListener('click', openUpload);
  $$('.modal').forEach((m) => m.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) closeModal(m); }));
  const dz = $('#dropzone');
  $('#file-input').addEventListener('change', (e) => { addFiles(e.target.files); e.target.value = ''; });
  ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('drag'); }));
  dz.addEventListener('drop', (e) => addFiles(e.dataTransfer.files));
  $('#upload-go').addEventListener('click', runUpload);
  bindSampleLinks($('#upload-modal'));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') $$('.modal:not([hidden])').forEach(closeModal);
    if (e.key === '/' && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); $('#search').focus(); }
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && state.kind === 'company' && state.symbol && state.quoteTimer) api.quote(state.symbol).then((q) => { state.quote = q; paintQuote(q); }).catch(() => {});
  });
  document.addEventListener('click', (e) => {
    if (e.target.closest('.dropdown')) return;
    $$('.menu').forEach((m) => { m.hidden = true; });
    $$('[aria-haspopup]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
  });
  window.addEventListener('hashchange', route);
  route();
}

init();
