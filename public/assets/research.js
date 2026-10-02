/* FinAnalyx - equity research panels: stock drivers, valuation lab, price & risk, scorecards.
   Loaded before app.js; uses its shared helpers ($, esc, state, fmtAmount, addChart, ...) at call time. */
'use strict';

// ------------------------------------------------------------------ helpers
const pctS = (v, dp = 1, signed = false) => v == null || !isFinite(v) ? 'n/a' : `${signed && v > 0 ? '+' : ''}${(v * 100).toFixed(dp)}%`;
const numS = (v, dp = 2) => v == null || !isFinite(v) ? 'n/a' : Number(v).toFixed(dp);
function priceS(v, curOverride) {
  if (v == null || !isFinite(v)) return 'n/a';
  const cur = curOverride || currencyOf();
  try { return new Intl.NumberFormat(undefined, { style: cur ? 'currency' : 'decimal', currency: cur || undefined, maximumFractionDigits: 2 }).format(v); }
  catch { return Number(v).toFixed(2); }
}
const SIGNAL = {
  bullish: ['good', '&#9650;', 'Tailwind'], bearish: ['crit', '&#9660;', 'Headwind'],
  neutral: ['neutral', '&#8226;', 'Neutral'], 'n/a': ['neutral', '&#8211;', 'No data'],
};
const ZONE = { safe: ['good', '&#10003;', 'Safe zone'], grey: ['warn', '!', 'Grey zone'], distress: ['crit', '&#10005;', 'Distress zone'] };
const learn = (text) => `<details class="learn"><summary>Why this moves the stock</summary><p>${esc(text)}</p></details>`;

function tiltColor(score) {
  if (score == null) return cssVar('--muted');
  return score >= 0.25 ? cssVar('--good') : score <= -0.25 ? cssVar('--crit') : cssVar('--warn');
}

function tiltGauge(score, label, size = 200) {
  // Semicircle from -2 (left) to +2 (right).
  const r = 80, cx = 100, cy = 95;
  const seg = (a0, a1, color) => {
    const p = (a) => [cx + r * Math.cos(Math.PI * (1 - a)), cy - r * Math.sin(Math.PI * (1 - a))];
    const [x0, y0] = p(a0), [x1, y1] = p(a1);
    return `<path d="M${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)}" stroke="${color}" stroke-width="14" fill="none"/>`;
  };
  const cols = [cssVar('--crit'), cssVar('--crit'), cssVar('--warn'), cssVar('--good'), cssVar('--good')];
  const arcs = [0, 0.2, 0.4, 0.6, 0.8].map((a, i) => seg(a + 0.006, a + 0.194, cols[i]) .replace('stroke-width="14"', `stroke-width="14" opacity="${[1, 0.55, 0.7, 0.55, 1][i]}"`)).join('');
  const t = score == null ? 0.5 : Math.min(1, Math.max(0, (score + 2) / 4));
  const ang = Math.PI * (1 - t);
  const nx = cx + (r - 22) * Math.cos(ang), ny = cy - (r - 22) * Math.sin(ang);
  return `<svg viewBox="0 0 200 128" width="${size}" style="max-width:100%" role="img" aria-label="Driver tilt ${esc(label)}">
    ${arcs}
    <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${cssVar('--ink')}" stroke-width="3" stroke-linecap="round"/>
    <circle cx="${cx}" cy="${cy}" r="6" fill="${cssVar('--ink')}"/>
    <text x="20" y="124" font-size="10" text-anchor="middle" stroke="none" fill="${cssVar('--muted')}">Bearish</text>
    <text x="180" y="124" font-size="10" text-anchor="middle" stroke="none" fill="${cssVar('--muted')}">Bullish</text></svg>`;
}

function factorBar(score) {
  const w = Math.abs(score) / 2 * 50;
  const color = score > 0 ? cssVar('--good') : cssVar('--crit');
  return `<div class="fbar" title="Score ${numS(score)} of ±2"><span class="fbar-mid"></span>
    <span class="fbar-fill" style="${score >= 0 ? 'left:50%' : `left:${50 - w}%`};width:${w}%;background:${color}"></span></div>`;
}

// ------------------------------------------------------------ overview card
function driversSnapshot(d) {
  const dr = d.drivers;
  if (!dr) return '';
  const avail = dr.factors.filter((f) => f.available);
  return `<div class="card card-pad section snapshot">
    <div class="card-title">What's driving the stock <button class="btn btn-ghost small" data-goto="drivers">Open stock drivers &rarr;</button></div>
    <div class="snap-grid">
      <div class="snap-gauge">${tiltGauge(dr.overall, dr.label, 190)}<div class="snap-label" style="color:${tiltColor(dr.overall)}">${esc(dr.label)}</div>
        <div class="muted small">${esc(dr.coverage)}</div></div>
      <div class="snap-factors">${avail.map((f) => `<div class="snap-row"><span>${esc(f.name)}</span>${factorBar(f.score)}<b class="num">${f.score > 0 ? '+' : ''}${numS(f.score, 1)}</b></div>`).join('')}</div>
      <div class="snap-cases">
        <div><h4 class="up">&#9650; Could push the price up</h4><ul>${dr.bull.slice(0, 3).map((b) => `<li>${esc(b.text)}</li>`).join('') || '<li class="muted">No clear tailwinds</li>'}</ul></div>
        <div><h4 class="down">&#9660; Could push the price down</h4><ul>${dr.bear.slice(0, 3).map((b) => `<li>${esc(b.text)}</li>`).join('') || '<li class="muted">No clear headwinds</li>'}</ul></div>
      </div>
    </div></div>`;
}

// ------------------------------------------------------------- drivers tab
function panelDrivers(p) {
  const d = state.data, dr = d.drivers, vm = d.valuation_model || {};
  if (!dr) { p.innerHTML = '<div class="card empty section">Driver analysis is not available for this data.</div>'; return; }
  const factorCards = dr.factors.map((f) => `
    <div class="card card-pad factor ${f.signal}">
      <div class="factor-head"><h3>${esc(f.name)}</h3>${badge(SIGNAL[f.signal] || SIGNAL.neutral)}</div>
      ${f.available ? `${factorBar(f.score)}<div class="muted small" style="margin-top:4px">${esc(f.summary)} · score ${f.score > 0 ? '+' : ''}${numS(f.score, 2)} of ±2 · weight ${f.weight}</div>
      <ul class="evidence">${f.evidence.map((e) => `<li class="${e.impact}"><i aria-hidden="true">${e.impact === 'positive' ? '&#9650;' : e.impact === 'negative' ? '&#9660;' : '&#8226;'}</i><span>${esc(e.text)}</span></li>`).join('')}</ul>
      ${f.watch.length ? `<div class="watch"><b>Watch:</b> ${f.watch.map(esc).join(' ')}</div>` : ''}` : `<p class="muted">Needs ${f.key === 'valuation' || f.key === 'momentum' || f.key === 'risk' ? 'a listed ticker with market prices' : 'more data'}.</p>`}
      ${learn(f.why)}
    </div>`).join('');

  const sens = vm.sensitivities || [];
  const maxImp = Math.max(0.0001, ...sens.map((s) => Math.abs(s.impact)));
  const sensRows = sens.map((s) => {
    const w = Math.abs(s.impact) / maxImp * 100;
    const col = s.impact >= 0 ? cssVar('--good') : cssVar('--crit');
    return `<tr><td><b>${esc(s.lever)}</b><div class="muted small">${esc(s.change)}</div></td>
      <td style="min-width:180px"><div class="sbar"><span style="width:${w}%;background:${col}"></span></div></td>
      <td class="num" style="font-weight:600;color:${col}">${pctS(s.impact, 1, true)}</td><td class="muted small">${esc(s.basis)}</td>
      <td style="white-space:normal;min-width:280px;text-align:left" class="small">${esc(s.explain)}</td></tr>`;
  }).join('');

  p.innerHTML = `
    <div class="card card-pad section drivers-head">
      <div class="dh-gauge">${tiltGauge(dr.overall, dr.label, 230)}
        <div class="snap-label" style="color:${tiltColor(dr.overall)}">${esc(dr.label)}</div>
        <div class="muted small">Weighted score ${dr.overall == null ? 'n/a' : (dr.overall > 0 ? '+' : '') + numS(dr.overall)} on a ±2 scale · ${esc(dr.coverage)}</div></div>
      <div class="dh-text">
        <h2 style="font-size:18px;margin-bottom:6px">Which forces push this share price up or down?</h2>
        <p class="muted" style="margin:0 0 12px">A share price is the market's estimate of future cash flows, discounted for risk. Eight factors capture what changes that estimate:
        growth and profitability (the cash flows), earnings quality and financial strength (their reliability), valuation (what is already priced in),
        momentum and market risk (sentiment and the discount rate), and capital allocation (how much of the value reaches each share).</p>
        <div class="snap-factors">${dr.factors.filter((f) => f.available).map((f) => `<div class="snap-row"><span>${esc(f.name)}</span>${factorBar(f.score)}<b class="num">${f.score > 0 ? '+' : ''}${numS(f.score, 1)}</b></div>`).join('')}</div>
        <p class="muted small" style="margin:10px 0 0">${esc(dr.disclaimer)}</p>
      </div>
    </div>
    <div class="cases section">
      <div class="card card-pad case bull"><h3>&#9650; Bull case <span class="muted small">what could drive the price higher</span></h3>
        <ol>${dr.bull.map((b) => `<li><span class="tag">${esc(b.factor)}</span> ${esc(b.text)}</li>`).join('') || '<li class="muted">No strong positives in the data.</li>'}</ol></div>
      <div class="card card-pad case bear"><h3>&#9660; Bear case <span class="muted small">what could drive the price lower</span></h3>
        <ol>${dr.bear.map((b) => `<li><span class="tag">${esc(b.factor)}</span> ${esc(b.text)}</li>`).join('') || '<li class="muted">No strong negatives in the data.</li>'}</ol></div>
    </div>
    <h2 class="section-title">Factor scorecard</h2>
    <div class="factor-grid">${factorCards}</div>
    ${sens.length ? `<h2 class="section-title">What moves the price: sensitivities</h2>
    <div class="card table-card"><div class="table-wrap"><table><thead><tr><th>Lever</th><th style="text-align:left">Relative size</th><th>Impact</th><th>On</th><th style="text-align:left">How it works</th></tr></thead>
      <tbody>${sensRows}</tbody></table></div></div>
    <p class="muted small">Estimates hold everything else constant using the latest fiscal year. EPS effects translate one-for-one into price at an unchanged P/E.</p>` : ''}
    ${attributionHTML(vm.attribution)}
    ${dr.watch.length ? `<h2 class="section-title">What to watch next</h2><div class="card card-pad"><ul class="notes-list">${dr.watch.map((w) => `<li>${esc(w)}</li>`).join('')}</ul></div>` : ''}`;
  if (vm.attribution?.periods?.length) drawAttribution(vm.attribution);
}

function attributionHTML(att) {
  if (!att) return '';
  const t = att.total;
  const summary = t ? `From ${t.from} to ${t.to} the share price moved <b>${pctS(t.price_change, 1, true)}</b>: earnings per share changed
    <b>${pctS(t.eps_change, 1, true)}</b> and the P/E multiple changed <b>${pctS(t.pe_change, 1, true)}</b>.
    The move was driven mainly by <b>${esc(t.driver)}</b>${t.eps_share != null && isFinite(t.eps_share) ? ` (earnings explain ~${Math.round(Math.max(-9.99, Math.min(9.99, t.eps_share)) * 100)}% of the log price change)` : ''}.` :
    'Earnings were negative at one end of the period, so the move cannot be split into EPS and P/E.';
  return `<h2 class="section-title">Where did past returns come from?</h2>
    <div class="card card-pad">
      <p style="margin-top:0">${summary}</p>
      <div class="chart-box"><canvas id="c-attr"></canvas></div>
      <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>Fiscal year-end</th><th>Share price</th><th>EPS (diluted)</th><th>P/E</th></tr></thead>
        <tbody>${att.rows.map((r) => `<tr><td>${esc(r.label)} <span class="muted small">${esc(r.date)}</span></td><td>${priceS(r.price)}</td><td>${numS(r.eps)}</td><td>${r.pe ? numS(r.pe, 1) + 'x' : 'n/m'}</td></tr>`).join('')}</tbody></table></div>
      <p class="muted small">${esc(att.explain)} ${att.notes.map(esc).join(' ')} Prices are fiscal-year-end closes (split-adjusted, excluding dividends).</p>
    </div>`;
}

function drawAttribution(att) {
  const labels = att.periods.map((x) => `${x.from}→${x.to}`);
  const ds = (label, key, color) => ({ label, data: att.periods.map((x) => x[key]), backgroundColor: cssVar(color), borderRadius: 4, maxBarThickness: 26 });
  const opts = baseOptions((v) => (v * 100).toFixed(0) + '%');
  opts.plugins.tooltip.callbacks.label = (c) => ` ${c.dataset.label}: ${pctS(c.parsed.y, 1, true)}`;
  opts.plugins.legend = { display: true, position: 'bottom', labels: { color: cssVar('--ink-2'), boxWidth: 12, boxHeight: 12, useBorderRadius: true, borderRadius: 3 } };
  addChart('c-attr', { type: 'bar', data: { labels, datasets: [ds('Share price', 'price_change', '--s1'), ds('EPS', 'eps_change', '--s3'), ds('P/E multiple', 'pe_change', '--s2')] }, options: opts });
}

// ------------------------------------------------------------ valuation lab
function dcfJS(base, g, gT, r, netDebt, shares, years = 10, high = 5) {
  if (!(base > 0) || r <= gT + 0.005) return null;
  let f = base, pv = 0;
  const flows = [];
  for (let t = 1; t <= years; t++) {
    const gt = t <= high ? g : g + (gT - g) * (t - high) / (years - high);
    f *= 1 + gt;
    const d = f / (1 + r) ** t;
    pv += d;
    flows.push({ t, g: gt, fcf: f, pv: d });
  }
  const tv = f * (1 + gT) / (r - gT), pvTv = tv / (1 + r) ** years, ev = pv + pvTv, eq = ev - netDebt;
  return { ev, eq, pv, pvTv, tvShare: pvTv / ev, perShare: shares ? eq / shares : null, flows };
}

function reverseJS(price, shares, base, gT, r, netDebt) {
  if (!(price > 0 && shares > 0 && base > 0)) return null;
  const target = price * shares;
  const val = (g) => dcfJS(base, g, gT, r, netDebt, shares)?.eq;
  let lo = -0.5, hi = 1.0;
  const vlo = val(lo), vhi = val(hi);
  if (vlo == null || vhi == null || target < vlo || target > vhi) return null;
  for (let i = 0; i < 70; i++) { const mid = (lo + hi) / 2; if (val(mid) < target) lo = mid; else hi = mid; }
  return (lo + hi) / 2;
}

function valState() {
  const vm = state.data.valuation_model;
  if (!state.val || state.val._key !== state.key) {
    const w = vm.wacc || {};
    state.val = {
      _key: state.key, g: vm.growth ?? 0.05, gT: vm.terminal_growth ?? 0.03, rf: w.rf ?? 0.04, erp: w.erp ?? 0.05,
      beta: w.beta_used ?? 1, base: vm.base_fcff, price: vm.price ?? (state.quote?.price ? state.quote.price / (state.quote.price_divisor || 1) : null),
      shares: vm.shares, netDebt: vm.net_debt ?? 0, years: 3,
      scen: vm.scenarios ? JSON.parse(JSON.stringify(vm.scenarios)) : null, probs: { bear: 0.25, base: 0.5, bull: 0.25 },
    };
  }
  return state.val;
}

function waccOf(v) {
  const w = state.data.valuation_model.wacc || {};
  const ke = v.rf + v.beta * v.erp;
  const we = w.weight_equity ?? 1, kd = w.cost_of_debt ?? 0;
  return { ke, kd, we, wacc: we * ke + (1 - we) * kd };
}

function slider(id, label, value, min, max, step, fmt, help) {
  return `<label class="slider"><span class="slider-top"><span>${label}</span><b id="${id}-out">${fmt(value)}</b></span>
    <input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${value}">
    ${help ? `<span class="muted small">${help}</span>` : ''}</label>`;
}

function panelValuation(p) {
  const d = state.data, vm = d.valuation_model;
  if (!vm) { p.innerHTML = '<div class="card empty section">Valuation inputs are not available.</div>'; return; }
  const v = valState();
  const live = isLive();
  p.innerHTML = `
    <div class="alert info section"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/></svg>
      <div><h3>Valuation lab</h3>A discounted cash flow (DCF) values a business as the present value of the free cash flow it will generate.
      Move the sliders to see how sensitive the value is to growth and the discount rate - the two levers that drive most share-price swings.
      ${vm.dcf_note ? `<div style="margin-top:6px"><b>${esc(vm.dcf_note)}</b></div>` : ''}</div></div>
    <div class="val-grid section">
      <div class="card card-pad">
        <div class="card-title">Assumptions <button class="btn btn-ghost small" id="val-reset">Reset to defaults</button></div>
        ${slider('s-g', 'Free cash flow growth, years 1-5', v.g, -0.1, 0.4, 0.005, (x) => pctS(+x), `Historical revenue CAGR: ${pctS(vm.historical_growth)}; fades linearly to terminal growth by year 10.`)}
        ${slider('s-gt', 'Terminal growth (after year 10)', v.gT, 0, 0.06, 0.0025, (x) => pctS(+x, 2), 'Should not exceed long-run nominal GDP growth / the risk-free rate.')}
        <div class="wacc-box">
          <div class="card-title" style="margin:6px 0 8px">Discount rate (WACC) build-up</div>
          ${slider('s-rf', 'Risk-free rate', v.rf, 0, 0.12, 0.001, (x) => pctS(+x, 2), esc(vm.rf_source || ''))}
          ${slider('s-beta', 'Beta', v.beta, 0.3, 2.5, 0.05, (x) => (+x).toFixed(2), d.market?.beta ? `Measured: ${numS(d.market.beta.beta)} vs ${esc(d.market.benchmark || 'market')} (weekly, R² ${numS(d.market.beta.r_squared)})` : 'No market data - assumed 1.0')}
          ${slider('s-erp', 'Equity risk premium', v.erp, 0.02, 0.1, 0.0025, (x) => pctS(+x, 2), 'Extra return investors demand for owning equities over government bonds.')}
          <div class="wacc-calc" id="wacc-calc"></div>
        </div>
        <div class="form-row">
          <label>Base free cash flow (FCFF) <span class="muted">${v.base != null ? fmtAmount(v.base) : ''}</span><input type="number" id="in-base" value="${v.base != null ? Math.round(v.base) : ''}" step="any"></label>
          <label>Net debt <span class="muted">${fmtAmount(v.netDebt || 0)}</span><input type="number" id="in-nd" value="${Math.round(v.netDebt || 0)}" step="any"></label>
          ${!live ? `<label>Shares outstanding<input type="number" id="in-shares" value="${v.shares ?? ''}" step="any" placeholder="e.g. 95"></label>
          <label>Share price<input type="number" id="in-price" value="${v.price ?? ''}" step="any" placeholder="optional"></label>` : ''}
        </div>
        <p class="muted small">${esc(vm.base_note || '')} FCFF = operating cash flow + after-tax interest − capex. ${esc(vm.tax_note || '')}.</p>
      </div>
      <div class="val-out">
        <div class="card card-pad" id="dcf-out"></div>
        <div class="card card-pad"><div class="card-title">Projected free cash flow</div><div class="chart-box"><canvas id="c-dcf"></canvas></div></div>
      </div>
    </div>
    <div class="val-grid2 section">
      <div class="card card-pad"><div class="card-title">Sensitivity: value per share</div><div id="sens-grid"></div>
        <p class="muted small">Rows: WACC. Columns: terminal growth. Green cells exceed the current price by 15%+, red cells sit 15%+ below it.</p></div>
      <div class="card card-pad" id="rev-dcf"></div>
    </div>
    <h2 class="section-title">Scenario price targets (EPS × P/E)</h2>
    <div class="card card-pad" id="scen"></div>`;

  const bind = (id, key, cast = Number) => $(id)?.addEventListener('input', (e) => { v[key] = cast(e.target.value); recomputeVal(); });
  bind('#s-g', 'g'); bind('#s-gt', 'gT'); bind('#s-rf', 'rf'); bind('#s-beta', 'beta'); bind('#s-erp', 'erp');
  bind('#in-base', 'base'); bind('#in-nd', 'netDebt');
  bind('#in-shares', 'shares', (x) => (x === '' ? null : Number(x))); bind('#in-price', 'price', (x) => (x === '' ? null : Number(x)));
  $('#val-reset').addEventListener('click', () => { state.val = null; renderPanel(); });
  recomputeVal();
  renderScenarios();
}

function recomputeVal() {
  const d = state.data, vm = d.valuation_model, v = valState();
  const fmtOut = { 's-g': pctS(v.g), 's-gt': pctS(v.gT, 2), 's-rf': pctS(v.rf, 2), 's-beta': v.beta.toFixed(2), 's-erp': pctS(v.erp, 2) };
  Object.entries(fmtOut).forEach(([k, t]) => { const el = $(`#${k}-out`); if (el) el.textContent = t; });
  const w = waccOf(v);
  $('#wacc-calc').innerHTML = `
    <div>Cost of equity = ${pctS(v.rf, 2)} + ${v.beta.toFixed(2)} × ${pctS(v.erp, 2)} = <b>${pctS(w.ke, 2)}</b> <span class="muted small">(CAPM)</span></div>
    <div>After-tax cost of debt = <b>${pctS(w.kd, 2)}</b> <span class="muted small">(${pctS(vm.wacc?.cost_of_debt_pre_tax, 2)} pre-tax, ${pctS(vm.wacc?.tax_rate, 0)} tax)</span></div>
    <div>Weights: equity ${pctS(w.we, 0)} / debt ${pctS(1 - w.we, 0)} <span class="muted small">(${esc(vm.wacc?.equity_basis || '')})</span></div>
    <div class="wacc-total">WACC = <b>${pctS(w.wacc, 2)}</b></div>`;
  const r = dcfJS(v.base, v.g, v.gT, w.wacc, v.netDebt || 0, v.shares);
  const out = $('#dcf-out');
  const price = v.price;
  if (!r) {
    out.innerHTML = `<div class="card-title">Intrinsic value</div><p class="muted">${v.base > 0 ? 'Discount rate must exceed terminal growth.' : 'Enter a positive base free cash flow to run the DCF.'}</p>`;
  } else {
    const up = r.perShare && price ? r.perShare / price - 1 : null;
    const upCls = up == null ? '' : up >= 0.15 ? 'up' : up <= -0.15 ? 'down' : 'flat';
    out.innerHTML = `<div class="card-title">Intrinsic value</div>
      <div class="iv"><div><div class="muted small">DCF value per share</div><div class="iv-val">${r.perShare != null ? priceS(r.perShare) : '<span class="muted small">enter shares</span>'}</div></div>
        <div><div class="muted small">Current price</div><div class="iv-val muted">${price ? priceS(price) : '-'}</div></div>
        <div><div class="muted small">Upside / downside</div><div class="iv-val ${upCls}">${up == null ? '-' : pctS(up, 1, true)}</div></div></div>
      <div class="kv-grid">
        <div><span>Enterprise value</span><b>${fmtAmount(r.ev)}</b></div><div><span>− Net debt</span><b>${fmtAmount(v.netDebt)}</b></div>
        <div><span>Equity value</span><b>${fmtAmount(r.eq)}</b></div><div><span>PV of years 1-10</span><b>${fmtAmount(r.pv)}</b></div>
        <div><span>PV of terminal value</span><b>${fmtAmount(r.pvTv)}</b></div><div><span>Terminal share of value</span><b class="${r.tvShare > 0.75 ? 'down' : ''}">${pctS(r.tvShare, 0)}</b></div>
      </div>
      ${r.tvShare > 0.75 ? '<p class="muted small">Over 75% of the value comes from beyond year 10 - the result is highly sensitive to long-run assumptions.</p>' : ''}`;
  }
  drawDcfChart(r);
  renderSensGrid(v, w.wacc, price);
  renderReverse(v, w.wacc, price);
  renderScenarios();
}

function drawDcfChart(r) {
  const idx = state.charts.findIndex((c) => c.canvas?.id === 'c-dcf');
  if (idx >= 0) { state.charts[idx].destroy(); state.charts.splice(idx, 1); }
  if (!r) return;
  const opts = baseOptions((x) => fmtAmount(x));
  addChart('c-dcf', { type: 'bar', data: { labels: r.flows.map((f) => 'Y' + f.t), datasets: [
    { label: 'Projected FCFF', data: r.flows.map((f) => f.fcf), backgroundColor: cssVar('--s1'), borderRadius: 4, maxBarThickness: 22 },
    { label: 'Present value', data: r.flows.map((f) => f.pv), backgroundColor: cssVar('--s3'), borderRadius: 4, maxBarThickness: 22 }] }, options: { ...opts, plugins: { ...opts.plugins, legend: { display: true, position: 'bottom', labels: { color: cssVar('--ink-2'), boxWidth: 12, boxHeight: 12 } } } } });
}

function renderSensGrid(v, wacc, price) {
  const el = $('#sens-grid');
  if (!el) return;
  const ws = [-0.02, -0.01, 0, 0.01, 0.02].map((dlt) => wacc + dlt), gs = [-0.01, -0.005, 0, 0.005, 0.01].map((dlt) => v.gT + dlt);
  const cell = (wc, gt) => {
    const r = dcfJS(v.base, v.g, gt, wc, v.netDebt || 0, v.shares);
    const val = r ? (r.perShare ?? r.eq) : null;
    let cls = '';
    if (val != null && price && r.perShare != null) cls = val >= price * 1.15 ? 'sg-up' : val <= price * 0.85 ? 'sg-down' : '';
    const cur = Math.abs(wc - wacc) < 1e-9 && Math.abs(gt - v.gT) < 1e-9 ? ' sg-cur' : '';
    return `<td class="${cls}${cur}">${val == null ? 'n/m' : r.perShare != null ? priceS(val) : fmtAmount(val)}</td>`;
  };
  el.innerHTML = `<div class="table-wrap"><table class="sens"><thead><tr><th>WACC \\ g<sub>T</sub></th>${gs.map((g) => `<th>${pctS(g, 2)}</th>`).join('')}</tr></thead>
    <tbody>${ws.map((wc) => `<tr><td><b>${pctS(wc, 1)}</b></td>${gs.map((g) => cell(wc, g)).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function renderReverse(v, wacc, price) {
  const el = $('#rev-dcf');
  if (!el) return;
  const vm = state.data.valuation_model;
  const ig = reverseJS(price, v.shares, v.base, v.gT, wacc, v.netDebt || 0);
  const hg = vm.historical_growth;
  let verdict = '';
  if (ig != null && hg != null) {
    verdict = ig > hg + 0.05 ? `<p class="down"><b>The market is pricing in much faster growth than the company has delivered.</b> Any shortfall risks a sharp de-rating.</p>`
      : ig < hg - 0.02 ? `<p class="up"><b>The market is pricing in less growth than the company has delivered.</b> If history repeats, there is room for upside.</p>`
        : `<p><b>Market expectations are close to the company's track record.</b></p>`;
  }
  el.innerHTML = `<div class="card-title">Reverse DCF: what growth is priced in?</div>
    ${ig == null ? `<p class="muted">${price ? 'Not solvable with the current inputs (requires positive free cash flow).' : 'Needs a share price.'}</p>` : `
    <div class="iv"><div><div class="muted small">Implied FCF growth (yrs 1-5)</div><div class="iv-val">${pctS(ig)}</div></div>
      <div><div class="muted small">Historical revenue CAGR</div><div class="iv-val muted">${pctS(hg)}</div></div></div>${verdict}`}
    <p class="muted small">Instead of asking "what is it worth?", a reverse DCF asks "what must happen to justify today's price?" -
    it solves for the growth rate that makes the DCF value equal the market price, using the same discount rate and terminal growth.</p>`;
}

function renderScenarios() {
  const el = $('#scen');
  if (!el) return;
  const v = valState(), sc = v.scen;
  if (!sc) { el.innerHTML = '<p class="muted">Scenario targets need revenue and margin history.</p>'; return; }
  const shares = v.shares, price = v.price, n = v.years;
  const calc = (k) => {
    const s = sc[k];
    const rev = sc.revenue * (1 + s.growth) ** n;
    const ni = rev * s.margin;
    const eps = shares ? ni / shares : null;
    const target = eps != null ? eps * s.pe : null;
    const ret = target && price ? (target / price) ** (1 / n) - 1 : null;
    return { rev, ni, eps, target, ret };
  };
  const res = { bear: calc('bear'), base: calc('base'), bull: calc('bull') };
  const ev = ['bear', 'base', 'bull'].reduce((s, k) => (res[k].target != null ? s + res[k].target * v.probs[k] : null), 0);
  const inp = (k, f, val, step) => `<input type="number" class="scen-in" data-k="${k}" data-f="${f}" value="${val}" step="${step}">`;
  const col = (k, title, cls) => {
    const s = sc[k], r = res[k];
    return `<div class="scen-col ${cls}"><h4>${title}</h4>
      <label>Revenue growth / yr ${inp(k, 'growth', (s.growth * 100).toFixed(1), 0.5)}<span>%</span></label>
      <label>Net margin ${inp(k, 'margin', (s.margin * 100).toFixed(1), 0.5)}<span>%</span></label>
      <label>Exit P/E ${inp(k, 'pe', s.pe.toFixed(1), 0.5)}<span>x</span></label>
      <label>Probability ${inp(k, 'prob', Math.round(v.probs[k] * 100), 5)}<span>%</span></label>
      <div class="scen-res"><div class="muted small">Year-${n} EPS</div><b>${r.eps != null ? numS(r.eps) : 'n/a'}</b>
        <div class="muted small" style="margin-top:6px">Target price</div><b class="scen-target">${r.target != null ? priceS(r.target) : 'n/a'}</b>
        <div class="muted small" style="margin-top:6px">Implied annual return</div><b class="${r.ret == null ? '' : r.ret >= 0 ? 'up' : 'down'}">${r.ret != null ? pctS(r.ret, 1, true) : 'n/a'}</b></div></div>`;
  };
  el.innerHTML = `<div class="scen-top"><p class="muted" style="margin:0">Price target = Revenue<sub>t</sub> × Net margin × P/E ÷ Shares. Defaults come from the company's own history:
    the bear case uses its weakest growth and margins and a 30% lower multiple; the bull case its strongest with a 25% higher multiple.</p>
    <label class="muted small">Horizon <select class="select" id="scen-years">${[1, 2, 3, 5].map((y) => `<option ${y === n ? 'selected' : ''}>${y}</option>`).join('')}</select> years</label></div>
    <div class="scen-grid">${col('bear', 'Bear', 'bear')}${col('base', 'Base', 'base')}${col('bull', 'Bull', 'bull')}</div>
    <div class="scen-ev">Probability-weighted target: <b>${ev != null && shares ? priceS(ev) : 'n/a'}</b>${ev != null && price && shares ? ` · <span class="${ev >= price ? 'up' : 'down'}">${pctS(ev / price - 1, 1, true)} vs current price</span>` : ''}
    ${Math.abs(v.probs.bear + v.probs.base + v.probs.bull - 1) > 0.001 ? ' <span class="down small">(probabilities do not sum to 100%)</span>' : ''}</div>`;
  $$('.scen-in', el).forEach((i) => i.addEventListener('change', (e) => {
    const k = e.target.dataset.k, f = e.target.dataset.f, x = Number(e.target.value);
    if (f === 'prob') v.probs[k] = x / 100; else if (f === 'pe') sc[k].pe = x; else sc[k][f] = x / 100;
    renderScenarios();
  }));
  $('#scen-years').addEventListener('change', (e) => { v.years = Number(e.target.value); renderScenarios(); });
}

// ------------------------------------------------------------ price & risk
function movingAvg(arr, n) {
  const out = new Array(arr.length).fill(null);
  let sum = 0;
  for (let i = 0; i < arr.length; i++) {
    sum += arr[i];
    if (i >= n) sum -= arr[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

function panelMarket(p) {
  const d = state.data, m = d.market, ps = d.price_series;
  if (!m || !ps) { p.innerHTML = '<div class="card empty section">Price history is available for listed companies only.</div>'; return; }
  state.mkt = state.mkt || { range: '1Y', mode: 'price' };
  const rows = ['1M', '3M', '6M', 'YTD', '1Y', '3Y (annual)', '5Y (annual)'].map((k) => {
    const s = m.returns?.[k], b = m.benchmark_returns?.[k];
    const diff = s != null && b != null ? s - b : null;
    return `<tr><td>${k}</td><td class="${s < 0 ? 'neg' : ''}">${pctS(s, 1, true)}</td><td>${pctS(b, 1, true)}</td>
      <td class="${diff == null ? 'na' : diff >= 0 ? 'up' : 'down'}">${diff == null ? '-' : pctS(diff, 1, true)}</td></tr>`;
  }).join('');
  const b = m.beta || {};
  const stat = (k, v, help, cls = '') => `<div class="stat"><div class="stat-k">${k}</div><div class="stat-v ${cls}">${v}</div><div class="muted small">${help}</div></div>`;
  const rsi = m.rsi14;
  const mp = (x) => priceS(x, m.currency);
  const pos = m.high_52w > m.low_52w ? (m.last_price - m.low_52w) / (m.high_52w - m.low_52w) * 100 : null;
  p.innerHTML = `
    <div class="card card-pad section">
      <div class="filters" style="margin-bottom:8px">
        ${['6M', '1Y', '3Y', '5Y'].map((r) => `<button class="chip" data-range="${r}" aria-pressed="${state.mkt.range === r}">${r}</button>`).join('')}
        <span class="spacer"></span>
        ${[['price', 'Price + moving averages'], ['relative', `vs ${m.benchmark || 'benchmark'}`], ['drawdown', 'Drawdown']].map(([k, l]) => `<button class="chip" data-mode="${k}" aria-pressed="${state.mkt.mode === k}">${esc(l)}</button>`).join('')}
      </div>
      <div class="legend" id="mkt-legend"></div>
      <div class="chart-box tall"><canvas id="c-price"></canvas></div>
      <p class="muted small" id="mkt-explain"></p>
    </div>
    <div class="mkt-grid section">
      <div class="card table-card"><div class="card-title">Returns vs ${esc(m.benchmark || 'benchmark')}</div><div class="table-wrap"><table>
        <thead><tr><th>Period</th><th>Stock</th><th>Benchmark</th><th>Difference</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="muted small" style="padding:0 16px">Total returns including dividends. Multi-year figures are annualised. As of ${esc(m.as_of)}.</p></div>
      <div class="card card-pad"><div class="card-title">Risk</div><div class="stat-grid">
        ${stat('Beta', numS(b.beta), `Moves ~${numS(b.beta, 1)}x the market. CAPM: higher beta → higher required return.`)}
        ${stat('Volatility (1Y)', pctS(m.volatility_1y), 'Annualised standard deviation of daily returns.')}
        ${stat('Sharpe ratio', numS(m.sharpe), `Excess return over the ${pctS(m.risk_free, 1)} risk-free rate per unit of volatility.`, m.sharpe > 1 ? 'up' : m.sharpe < 0 ? 'down' : '')}
        ${stat('Sortino ratio', numS(m.sortino), 'Like Sharpe but penalises only downside volatility.')}
        ${stat('Max drawdown', pctS(m.max_drawdown), `Worst peak-to-trough fall (${esc(m.max_drawdown_peak || '')} → ${esc(m.max_drawdown_trough || '')}).`, 'down')}
        ${stat('Correlation / R²', `${numS(b.correlation)} / ${numS(b.r_squared)}`, `R² = share of price moves explained by the market (${b.weeks || '-'} weeks).`)}
      </div></div>
      <div class="card card-pad"><div class="card-title">Trend & momentum</div><div class="stat-grid">
        ${stat('50-day MA', mp(m.ma50), m.ma50 ? `Price ${pctS(m.last_price / m.ma50 - 1, 1, true)} vs MA` : '', m.last_price > m.ma50 ? 'up' : 'down')}
        ${stat('200-day MA', mp(m.ma200), m.ma200 ? `Price ${pctS(m.last_price / m.ma200 - 1, 1, true)} vs MA` : '', m.last_price > m.ma200 ? 'up' : 'down')}
        ${stat('MA regime', m.last_cross === 'golden' ? 'Golden cross' : m.last_cross === 'death' ? 'Death cross' : 'n/a', m.last_cross_date ? `50-day crossed the 200-day on ${esc(m.last_cross_date)}.` : '', m.last_cross === 'golden' ? 'up' : m.last_cross === 'death' ? 'down' : '')}
        ${stat('12-1 momentum', pctS(m.momentum_12_1, 1, true), 'Return over 12 months excluding the latest month (academic momentum factor).', m.momentum_12_1 > 0 ? 'up' : 'down')}
      </div>
      <div class="rsi"><div class="stat-k">RSI (14-day): <b>${numS(rsi, 0)}</b> ${rsi > 70 ? '<span class="down small">overbought</span>' : rsi < 30 ? '<span class="up small">oversold</span>' : '<span class="muted small">neutral</span>'}</div>
        <div class="rsi-bar"><span class="rsi-zone" style="left:0;width:30%"></span><span class="rsi-zone" style="left:70%;width:30%"></span><i style="left:${rsi ?? 50}%"></i></div>
        <div class="range-ends muted small"><span>0</span><span>30</span><span>70</span><span>100</span></div></div>
      ${pos != null ? `<div class="range" style="margin-top:14px">52-week range · ${pctS(m.drawdown_from_high, 1, true)} from high<div class="range-bar"><span style="left:${pos}%"></span></div>
        <div class="range-ends num"><span>${mp(m.low_52w)}</span><span>${mp(m.high_52w)}</span></div></div>` : ''}
      </div>
    </div>`;
  $$('[data-range]', p).forEach((b2) => b2.addEventListener('click', () => { state.mkt.range = b2.dataset.range; panelMarket(p); }));
  $$('[data-mode]', p).forEach((b2) => b2.addEventListener('click', () => { state.mkt.mode = b2.dataset.mode; panelMarket(p); }));
  drawPriceChart();
}

function drawPriceChart() {
  const idx = state.charts.findIndex((c) => c.canvas?.id === 'c-price');
  if (idx >= 0) { state.charts[idx].destroy(); state.charts.splice(idx, 1); }
  const d = state.data, ps = d.price_series, m = d.market;
  const days = { '6M': 182, '1Y': 365, '3Y': 1095, '5Y': 1830 }[state.mkt.range];
  const endTs = ps.close[ps.close.length - 1][0], startTs = endTs - days * 86400000;
  const closeAll = ps.close.map((x) => x[1]);
  const ma50All = movingAvg(closeAll, 50), ma200All = movingAvg(closeAll, 200);
  const keep = ps.close.map((x, i) => [x, i]).filter(([x]) => x[0] >= startTs);
  const labels = keep.map(([x]) => new Date(x[0]).toLocaleDateString(undefined, { year: '2-digit', month: 'short', day: 'numeric' }));
  const line = (label, data, color, width = 2, dash) => ({ label, data, borderColor: cssVar(color), backgroundColor: cssVar(color), borderWidth: width, pointRadius: 0, pointHoverRadius: 3, tension: 0, borderDash: dash, spanGaps: true });
  let datasets, fmt, legend, explain;
  if (state.mkt.mode === 'price') {
    datasets = [line('Price', keep.map(([x]) => x[1]), '--s1'), line('50-day MA', keep.map(([, i]) => ma50All[i]), '--s2', 1.5), line('200-day MA', keep.map(([, i]) => ma200All[i]), '--s3', 1.5)];
    fmt = (v) => priceS(v, m.currency);
    legend = [['Price', '--s1'], ['50-day MA', '--s2'], ['200-day MA', '--s3']];
    explain = 'Moving averages smooth noise to show the trend. Price above a rising 200-day average is a classic sign of an uptrend; a 50-day crossing above the 200-day ("golden cross") or below it ("death cross") marks shifts in medium-term momentum.';
  } else if (state.mkt.mode === 'relative') {
    const bmap = new Map((ps.benchmark || []).map((x) => [new Date(x[0]).toDateString(), x[1]]));
    const adjMap = new Map(ps.adj.map((x) => [x[0], x[1]]));
    const s0 = adjMap.get(keep[0][0][0]);
    let b0 = null;
    const bench = keep.map(([x]) => { const bv = bmap.get(new Date(x[0]).toDateString()); if (bv != null && b0 == null) b0 = bv; return bv != null && b0 ? bv / b0 * 100 : null; });
    datasets = [line(d.company_info?.symbol || 'Stock', keep.map(([x]) => adjMap.get(x[0]) / s0 * 100), '--s1'), line(m.benchmark || 'Benchmark', bench, '--s2', 1.5)];
    fmt = (v) => v.toFixed(0);
    legend = [[d.company_info?.symbol || 'Stock', '--s1'], [m.benchmark || 'Benchmark', '--s2']];
    explain = 'Both series rebased to 100 at the start of the range, with dividends reinvested. The gap between the lines is the stock\'s outperformance or underperformance - what is left after the overall market\'s move (alpha plus stock-specific news).';
  } else {
    const adj = ps.adj.map((x) => x[1]);
    let peak = -Infinity;
    const ddAll = adj.map((v) => { peak = Math.max(peak, v); return v / peak - 1; });
    datasets = [{ ...line('Drawdown', keep.map(([, i]) => ddAll[i]), '--crit'), fill: true, backgroundColor: cssVar('--crit-soft') }];
    fmt = (v) => (v * 100).toFixed(0) + '%';
    legend = [['Drawdown from previous peak', '--crit']];
    explain = 'The "underwater" chart shows how far the stock sat below its previous high at each point. Deep, long drawdowns show the pain an investor would have endured - a practical measure of risk that volatility alone misses.';
  }
  $('#mkt-legend').innerHTML = legend.map(([n, c]) => `<span><b style="background:var(${c})"></b>${esc(n)}</span>`).join('');
  $('#mkt-explain').textContent = explain;
  const opts = baseOptions(fmt);
  opts.scales.x.ticks.maxTicksLimit = 8;
  opts.scales.x.ticks.autoSkip = true;
  opts.scales.x.ticks.maxRotation = 0;
  opts.scales.y.beginAtZero = false;
  opts.plugins.tooltip.callbacks.label = (c) => ` ${c.dataset.label}: ${c.parsed.y == null ? 'n/a' : fmt(c.parsed.y)}`;
  opts.animation = false;
  addChart('c-price', { type: 'line', data: { labels, datasets }, options: opts });
}

// --------------------------------------------------------------- scorecards
function panelScores(p) {
  const sc = state.data.scores || {};
  const pio = sc.piotroski, alt = sc.altman, ben = sc.beneish;
  const pioHTML = pio ? (() => {
    const groups = [...new Set(pio.signals.map((s) => s.group))];
    const r = 46, c = 2 * Math.PI * r, frac = pio.scaled / 9;
    const col = pio.tone === 'good' ? cssVar('--good') : pio.tone === 'weak' ? cssVar('--crit') : cssVar('--warn');
    return `<div class="score-head"><div class="gauge" style="width:110px;height:110px"><svg viewBox="0 0 110 110"><circle cx="55" cy="55" r="${r}" stroke="${cssVar('--line-2')}" stroke-width="10"/>
      <circle cx="55" cy="55" r="${r}" stroke="${col}" stroke-width="10" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - frac)}" stroke-linecap="round"/></svg>
      <div class="gauge-val"><div><b style="font-size:28px">${pio.score}</b><span>of ${pio.max}</span></div></div></div>
      <div><b>${esc(pio.verdict)}</b><div class="muted small">${fy(pio.year)} vs ${fy(pio.year - 1)}. ${esc(pio.note)}</div>
      ${Object.keys(sc.piotroski_history || {}).length > 1 ? `<div class="pio-hist">${Object.entries(sc.piotroski_history).map(([y, s]) => `<div title="${y}: ${s}/9"><span style="height:${s / 9 * 100}%"></span><i>${y}</i></div>`).join('')}</div>` : ''}</div></div>
      ${groups.map((g) => `<h4 class="sc-group">${esc(g)}</h4><ul class="signals">${pio.signals.filter((s) => s.group === g).map((s) => `
        <li class="${s.pass == null ? 'na' : s.pass ? 'pass' : 'fail'}"><i>${s.pass == null ? '&#8211;' : s.pass ? '&#10003;' : '&#10005;'}</i><div><b>${esc(s.name)}</b><div class="muted small">${esc(s.explain)}</div></div></li>`).join('')}</ul>`).join('')}`;
  })() : '<p class="muted">Needs at least two consecutive years of data.</p>';

  const altHTML = alt ? `${(alt.models || []).map((mdl) => {
    const scale = mdl.name.startsWith("Z''") ? [0, 1.1, 2.6, 5] : [0, 1.81, 2.99, 5];
    const pos = Math.min(100, Math.max(0, (mdl.value - scale[0]) / (scale[3] - scale[0]) * 100));
    return `<div class="alt-model"><div class="alt-top"><b>${esc(mdl.name)}</b>${badge(ZONE[mdl.zone])}</div>
      <div class="alt-val num">${numS(mdl.value)}</div>
      <div class="zone-bar"><span class="z-d" style="width:${scale[1] / scale[3] * 100}%"></span><span class="z-g" style="width:${(scale[2] - scale[1]) / scale[3] * 100}%"></span><span class="z-s"></span><i style="left:${pos}%"></i></div>
      <div class="muted small">${esc(mdl.thresholds)}<br><code>${esc(mdl.formula)}</code></div></div>`;
  }).join('')}
    ${alt.note ? `<p class="muted">${esc(alt.note)}</p>` : ''}
    <table class="mini"><thead><tr><th>Ratio</th><th>Value</th></tr></thead><tbody>${(alt.components || []).map((c) => `<tr><td><b>${esc(c.key)}</b> ${esc(c.name)}<div class="muted small" style="white-space:normal">${esc(c.explain)}</div></td><td>${numS(c.value, 3)}</td></tr>`).join('')}</tbody></table>` : '<p class="muted">Needs current assets/liabilities, EBIT and total liabilities.</p>';

  const benHTML = ben ? (() => {
    const pos = Math.min(100, Math.max(0, (ben.value + 4) / 4 * 100));
    const tpos = (ben.threshold + 4) / 4 * 100;
    return `<div class="alt-top"><b>M-Score ${fy(ben.year)}</b>${badge(ben.likely_manipulator ? ['crit', '!', 'Red flag'] : ['good', '&#10003;', 'No flag'])}</div>
      <div class="alt-val num">${numS(ben.value)}</div>
      <div class="zone-bar ben"><span class="z-s" style="width:${tpos}%"></span><span class="z-d"></span><i style="left:${pos}%"></i></div>
      <div class="muted small">Threshold -1.78 (8-variable model). ${esc(ben.verdict)}.</div>
      <div class="table-wrap"><table class="mini"><thead><tr><th>Index</th><th>Value</th><th>Weight</th><th>Contribution</th></tr></thead><tbody>${ben.components.map((c) => `
        <tr class="${c.flag ? 'flagged' : ''}"><td><b>${esc(c.key)}</b> ${esc(c.name)}${c.flag ? ' <span class="down small">flag</span>' : ''}<div class="muted small" style="white-space:normal">${esc(c.explain)}</div></td>
        <td>${c.value == null ? '<span class="muted">n/a</span>' : numS(c.value, 3)}</td><td>${numS(c.coef, 3)}</td><td>${c.value == null ? '-' : numS(c.coef * c.value, 3)}</td></tr>`).join('')}</tbody></table></div>
      <p class="muted small">${esc(ben.note)} Constant term -4.84.</p>`;
  })() : '<p class="muted">Needs two consecutive years including receivables, gross profit and cash flow.</p>';

  p.innerHTML = `
    <div class="alert info section"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/></svg>
      <div><h3>Academic scorecards</h3>Three classic models from the accounting and finance literature. Each condenses many ratios into one signal:
      <b>Piotroski</b> (is the business getting stronger?), <b>Altman</b> (how close is it to financial distress?), <b>Beneish</b> (do the accounts look manipulated?).
      They are screening tools - starting points for questions, not verdicts.</div></div>
    <div class="score-grid section">
      <div class="card card-pad"><div class="card-title">Piotroski F-Score</div>${pioHTML}
        ${learn('Piotroski (2000) showed that cheap stocks with high F-Scores (8-9) outperformed those with low scores (0-1) by over 20% a year: improving fundamentals tend to be rewarded by the market before they show up in consensus expectations.')}</div>
      <div class="card card-pad"><div class="card-title">Altman Z-Score</div>${altHTML}
        ${learn('Altman (1968) combined five ratios to predict bankruptcy within two years with ~80-90% accuracy. Firms drifting into the distress zone usually see their shares fall as lenders tighten terms and equity holders price in the risk of being wiped out.')}</div>
      <div class="card card-pad"><div class="card-title">Beneish M-Score</div>${benHTML}
        ${learn('Beneish (1999) built the model from firms caught manipulating earnings; it flagged Enron before its collapse. Stocks with high M-Scores have historically underperformed as aggressive accounting unwinds.')}</div>
    </div>`;
}
