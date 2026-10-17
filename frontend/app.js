// Atlas Terminal — vanilla JS frontend. No deps.
'use strict';

const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
const AMBER='#FFB000', GAIN='#00FF7F', LOSS='#FF3030', MUTED='#806030', BORDER='#333';

const state = { tab: 'mkts', ticker: 'SPY', quoteRange: '6M' };

const fmt = {
  n: (v, d=2) => v == null || isNaN(v) ? '—' : Number(v).toLocaleString('en-US', {maximumFractionDigits: d}),
  pct: (v, d=2) => v == null || isNaN(v) ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(d) + '%',
  abs: (v, d=2) => v == null || isNaN(v) ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(d),
  big: v => v == null ? '—' : abbreviate(v),
  ts: s => { try { return new Date(s).toLocaleString('en-US', {hour12:false}); } catch { return '—'; } },
  date: s => { try { return new Date(s).toISOString().slice(0,10); } catch { return '—'; } },
};
function abbreviate(n) {
  const a = Math.abs(n);
  if (a >= 1e12) return (n/1e12).toFixed(2)+'T';
  if (a >= 1e9)  return (n/1e9 ).toFixed(2)+'B';
  if (a >= 1e6)  return (n/1e6 ).toFixed(2)+'M';
  if (a >= 1e3)  return (n/1e3 ).toFixed(2)+'K';
  return n.toFixed(0);
}

function setStatus(msg, kind='') {
  const el = $('#status');
  el.textContent = msg;
  el.className = 'status ' + kind;
}

async function fetchJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  let j = null;
  try { j = await r.json(); } catch { /* may be empty */ }
  if (!r.ok) {
    const err = (j && j.error) || ('status ' + r.status);
    const e = new Error(err); e.payload = j; throw e;
  }
  return j;
}

function errBlock(panel, e) {
  panel.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'err';
  div.textContent = `data unavailable — ${e.message || e}`;
  panel.appendChild(div);
}

// ============ tab + command ============
function setTab(tab, ticker) {
  state.tab = tab;
  if (ticker) state.ticker = ticker.toUpperCase();
  $$('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $$('.panel').forEach(p => p.hidden = (p.id !== 'p-' + tab));
  loadPanel();
}

function parseCommand(s) {
  s = (s || '').trim().toUpperCase();
  if (!s) return null;
  const tokens = s.split(/\s+/);
  const known = { MKTS:'mkts', QUOTE:'quote', FA:'fa', RISK:'risk', NEWS:'news', ECO:'eco' };
  // last token is a tab name? → tab only
  if (tokens.length === 1 && known[tokens[0]]) return { tab: known[tokens[0]] };
  // TICKER [TAB]
  if (tokens.length >= 1 && /^[A-Z^.\-]{1,8}$/.test(tokens[0])) {
    const t = tokens[1] ? known[tokens[1]] : 'quote';
    return { tab: t || 'quote', ticker: tokens[0] };
  }
  // MKTS / ECO alone
  if (known[tokens[0]]) return { tab: known[tokens[0]] };
  return null;
}

document.addEventListener('DOMContentLoaded', () => {
  $$('.tab').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));
  $('#cmd-form').addEventListener('submit', e => {
    e.preventDefault();
    const parsed = parseCommand($('#cmd').value);
    if (!parsed) { setStatus('unrecognized — use ticker letter or tab', 'err'); return; }
    setTab(parsed.tab, parsed.ticker);
    $('#cmd').value = '';
  });
  document.addEventListener('keydown', e => {
    if (document.activeElement === $('#cmd')) return;
    if (e.key === '/' || e.key === ':') { e.preventDefault(); $('#cmd').focus(); return; }
    const m = { 'F1':'mkts','F2':'quote','F3':'fa','F4':'risk','F5':'news','F6':'eco' }[e.key.toUpperCase()];
    if (m) { e.preventDefault(); setTab(m); }
  });
  setTab('mkts');
});

// ============ panel loader ============
async function loadPanel() {
  const id = 'p-' + state.tab;
  const panel = $('#' + id);
  panel.innerHTML = '<div class="muted">loading…</div>';
  try {
    if (state.tab === 'mkts')  await renderMkts(panel);
    if (state.tab === 'quote') await renderQuote(panel);
    if (state.tab === 'fa')    await renderFA(panel);
    if (state.tab === 'risk')  await renderRisk(panel);
    if (state.tab === 'news')  await renderNews(panel);
    if (state.tab === 'eco')   await renderEco(panel);
    setStatus('ok', 'ok');
  } catch (e) {
    errBlock(panel, e);
    setStatus('error', 'err');
  }
}

// ============ canvas helpers ============
function fitCanvas(c) {
  const dpr = window.devicePixelRatio || 1;
  const rect = c.getBoundingClientRect();
  c.width = Math.max(2, Math.round(rect.width * dpr));
  c.height = Math.max(2, Math.round(rect.height * dpr));
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: rect.width, h: rect.height };
}

function drawLineChart(canvas, series, opts={}) {
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = BORDER; ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, w-1, h-1);

  const padL = 44, padR = 10, padT = 8, padB = 18;
  const innerW = w - padL - padR, innerH = h - padT - padB;

  const volSeries = series.find(s => s.role === 'vol');
  const priceSeries = series.filter(s => s.role !== 'vol');
  const volH = (volSeries && volSeries.data.length) ? Math.min(36, innerH * 0.22) : 0;
  const priceH = innerH - volH;

  // y-scale from price series only
  const all = [];
  priceSeries.forEach(s => s.data.forEach(p => all.push(p.v)));
  if (!all.length) {
    ctx.fillStyle = MUTED; ctx.font = '11px ui-monospace';
    ctx.fillText('no data', padL + 4, padT + 14);
    return;
  }
  let lo = Math.min(...all), hi = Math.max(...all);
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.05;
  lo -= pad; hi += pad;
  const n = Math.max(...series.map(s => s.data.length));
  const xAt = i => padL + (n === 1 ? 0 : (i / (n - 1)) * innerW);
  const yAt = v => padT + (1 - (v - lo) / (hi - lo)) * priceH;

  // grid + y labels over price area only
  ctx.fillStyle = MUTED; ctx.font = '10px ui-monospace'; ctx.textBaseline = 'middle';
  for (let k = 0; k <= 4; k++) {
    const y = padT + (k/4) * priceH;
    ctx.strokeStyle = '#1d1d1d';
    ctx.beginPath(); ctx.moveTo(padL, y + 0.5); ctx.lineTo(w - padR, y + 0.5); ctx.stroke();
    const v = hi - (k/4) * (hi - lo);
    ctx.textAlign = 'right';
    ctx.fillText(fmt.n(v, 2), padL - 4, y);
  }
  ctx.textAlign = 'left';

  // price lines
  priceSeries.forEach(s => drawLine(ctx, s.data, xAt, yAt, s.color));

  // separator between price and volume
  if (volH) {
    const sep = padT + priceH + 0.5;
    ctx.strokeStyle = BORDER; ctx.beginPath();
    ctx.moveTo(padL, sep); ctx.lineTo(w - padR, sep); ctx.stroke();
  }

  // volume bars
  if (volH && volSeries.data.length) {
    const maxV = Math.max(...volSeries.data.map(p => p.v), 1);
    ctx.fillStyle = '#3a2a10';
    volSeries.data.forEach((p, i) => {
      const x = xAt(i);
      const bw = Math.max(1, innerW / volSeries.data.length - 1);
      const bh = (p.v / maxV) * volH;
      ctx.fillRect(x, h - padB - bh, bw, bh);
    });
  }

  // x labels (first/last date) — only if provided
  const xLabels = series[0].xLabels;
  if (xLabels) {
    ctx.fillStyle = MUTED; ctx.textBaseline = 'top';
    ctx.fillText(xLabels.first, padL, h - padB + 4);
    ctx.textAlign = 'right';
    ctx.fillText(xLabels.last, w - padR, h - padB + 4);
    ctx.textAlign = 'left';
  }
}
function drawLine(ctx, data, xAt, yAt, color) {
  if (!data.length) return;
  ctx.strokeStyle = color || AMBER; ctx.lineWidth = 1.25;
  ctx.beginPath();
  data.forEach((p, i) => {
    const x = xAt(i), y = yAt(p.v);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawBars(canvas, data, labels) {
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = BORDER; ctx.strokeRect(0.5, 0.5, w-1, h-1);
  if (!data.length) {
    ctx.fillStyle = MUTED; ctx.font='11px ui-monospace';
    ctx.fillText('no data', 8, 14); return;
  }
  const padL=40, padR=10, padT=8, padB=20;
  const innerW = w-padL-padR, innerH = h-padT-padB;
  let lo = Math.min(...data.map(p=>p.v)), hi = Math.max(...data.map(p=>p.v));
  if (lo === hi) { lo-=1; hi+=1; }
  const bw = Math.max(1, innerW/data.length - 1);
  const yAt = v => padT + (1 - (v - lo)/(hi - lo)) * innerH;
  // grid
  ctx.fillStyle = MUTED; ctx.font = '10px ui-monospace'; ctx.textBaseline='middle'; ctx.textAlign='right';
  for (let k=0;k<=4;k++) {
    const y = padT + (k/4)*innerH;
    ctx.strokeStyle = '#1d1d1d';
    ctx.beginPath(); ctx.moveTo(padL, y+0.5); ctx.lineTo(w-padR, y+0.5); ctx.stroke();
    const v = hi - (k/4)*(hi-lo);
    ctx.fillText(fmt.n(v,2), padL-4, y);
  }
  ctx.textAlign='left';
  data.forEach((p, i) => {
    const x = padL + i*(bw+1);
    const y = yAt(p.v);
    ctx.fillStyle = p.v >= 0 ? GAIN : LOSS;
    ctx.fillRect(x, Math.min(y, padT+innerH), bw, Math.abs(y - (padT+innerH)));
  });
  if (labels) {
    ctx.fillStyle = MUTED; ctx.textBaseline='top';
    ctx.fillText(labels.first, padL, h-padB+4);
    ctx.textAlign='right'; ctx.fillText(labels.last, w-padR, h-padB+4);
  }
}

function drawHeatmap(canvas, matrix, labels) {
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
  const n = labels.length;
  if (!n) { ctx.fillStyle=MUTED; ctx.font='11px ui-monospace'; ctx.fillText('no data', 8, 14); return; }
  const padL = 70, padT = 60, padR = 10, padB = 10;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const cell = Math.min(innerW, innerH) / n;
  const startX = padL + (innerW - cell*n) / 2;
  const startY = padT + (innerH - cell*n) / 2;
  // col labels
  ctx.fillStyle = MUTED; ctx.font='10px ui-monospace'; ctx.textBaseline='middle';
  labels.forEach((l, j) => {
    ctx.save();
    ctx.translate(startX + j*cell + cell/2, padT - 6);
    ctx.rotate(-Math.PI/4);
    ctx.textAlign='left';
    ctx.fillText(l, 0, 0);
    ctx.restore();
  });
  ctx.textAlign='right';
  labels.forEach((l, i) => {
    ctx.fillText(l, startX - 6, startY + i*cell + cell/2);
  });
  // cells
  for (let i=0;i<n;i++) for (let j=0;j<n;j++) {
    const v = matrix[i][j];
    ctx.fillStyle = corrColor(v);
    ctx.fillRect(startX + j*cell, startY + i*cell, cell-1, cell-1);
    if (cell > 28) {
      ctx.fillStyle = Math.abs(v) > 0.6 ? '#000' : AMBER;
      ctx.font = '10px ui-monospace'; ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.fillText(v.toFixed(2), startX + j*cell + cell/2, startY + i*cell + cell/2);
    }
  }
}
function corrColor(v) {
  // green positive, red negative, neutral mid
  const t = Math.max(-1, Math.min(1, v));
  if (t >= 0) {
    // 0..1 → dark to bright green
    const a = t;
    return `rgb(${Math.round(20*(1-a))},${Math.round(60 + 160*a)},${Math.round(40*(1-a))})`;
  } else {
    const a = -t;
    return `rgb(${Math.round(60 + 160*a)},${Math.round(30*(1-a))},${Math.round(30*(1-a))})`;
  }
}

// ============ MKTS ============
async function renderMkts(panel) {
  const data = await fetchJSON('/api/mkts');
  panel.innerHTML = '';
  const meta = `source: ${data.source || '—'} · ${fmt.ts(data.fetched_at)}`;
  panel.innerHTML = `
    <div class="h">MARKETS <span class="meta">${meta}</span></div>
    <div>
      <div class="h">INDICES</div>
      <table class="t"><thead><tr><th>Ticker</th><th>Last</th><th>Δ</th><th>Δ%</th></tr></thead>
        <tbody id="m-indices"></tbody></table>
    </div>
    <div>
      <div class="h">WATCHLIST</div>
      <table class="t"><thead><tr><th>Ticker</th><th>Last</th><th>Δ</th><th>Δ%</th></tr></thead>
        <tbody id="m-watch"></tbody></table>
    </div>
    <div class="row g4" id="m-macro"></div>
  `;
  const idx = $('#m-indices', panel);
  (data.indices || []).forEach(r => idx.appendChild(rowIndex(r)));
  const wl  = $('#m-watch', panel);
  (data.watchlist || []).forEach(r => wl.appendChild(rowIndex(r)));
  const mac = $('#m-macro', panel);
  const m = data.macro || {};
  mac.innerHTML = `
    ${macroTile('FED FUNDS', m.fed_funds, '%')}
    ${macroTile('UST 10Y',   m.ust10,    '%')}
    ${macroTile('2s10s',     m.ust2s10s, 'bp')}
    ${macroTile('CPI YoY',   m.cpi_yoy,  '%')}
  `;
}
function rowIndex(r) {
  const tr = document.createElement('tr');
  const ch = (r.change_pct >= 0);
  tr.innerHTML = `
    <td>${r.ticker}</td>
    <td>${fmt.n(r.last)}</td>
    <td class="${ch?'gain':'loss'}">${fmt.abs(r.change_abs != null ? r.change_abs : r.change_pct/100*r.last)}</td>
    <td class="${ch?'gain':'loss'}">${fmt.pct(r.change_pct)}</td>
  `;
  return tr;
}
function macroTile(label, val, unit) {
  let s = '—';
  if (val != null && !isNaN(val)) {
    if (unit === 'bp') s = (val >= 0 ? '+' : '') + Number(val).toFixed(0) + ' bp';
    else s = Number(val).toFixed(2) + '%';
  }
  return `<div class="tile"><div class="lbl">${label}</div><div class="val">${s}</div></div>`;
}

// ============ QUOTE ============
async function renderQuote(panel) {
  panel.innerHTML = '<div class="muted">loading…</div>';
  const data = await fetchJSON(`/api/quote/${encodeURIComponent(state.ticker)}?range=${state.quoteRange}`);
  panel.innerHTML = '';
  const meta = `source: ${data.source || '—'} · ${fmt.ts(data.fetched_at)}`;
  panel.innerHTML = `
    <div class="h">QUOTE <span class="meta">${meta}</span></div>
    <div class="qhdr" id="q-hdr"></div>
    <div class="h">PRICE <span class="meta">${data.series?.length || 0} pts</span>
      <span class="range" id="q-range">
        ${['1M','6M','1Y','5Y'].map(r => `<button data-r="${r}" class="${r===state.quoteRange?'on':''}">${r}</button>`).join('')}
      </span>
    </div>
    <canvas id="q-chart"></canvas>
  `;
  const hdr = $('#q-hdr', panel);
  const ch = data.change_pct >= 0;
  hdr.innerHTML = `
    <div><div class="sym">${data.ticker}</div><div class="name">${data.name || ''}</div></div>
    <div class="cell"><div class="lbl">LAST</div><div class="last">${fmt.n(data.last)}</div></div>
    <div class="cell"><div class="lbl">Δ%</div><div class="last ${ch?'gain':'loss'}">${fmt.pct(data.change_pct)}</div></div>
    <div class="cell"><div class="lbl">52W H/L</div><div class="last">${fmt.n(data.high_52w)} / ${fmt.n(data.low_52w)}</div></div>
    <div class="cell"><div class="lbl">VOLUME</div><div class="last">${fmt.big(data.volume)}</div></div>
  `;
  $('#q-range', panel).addEventListener('click', e => {
    const b = e.target.closest('button[data-r]'); if (!b) return;
    state.quoteRange = b.dataset.r;
    renderQuote(panel);
  });
  drawQuoteChart($('#q-chart', panel), data);
}
function drawQuoteChart(canvas, data) {
  const series = data.series || [];
  if (!series.length) {
    const { ctx, w, h } = fitCanvas(canvas);
    ctx.fillStyle = MUTED; ctx.font='11px ui-monospace';
    ctx.fillText('no series', 8, 14); return;
  }
  const closes = series.map(p => ({ v: p.adj_close != null ? p.adj_close : p.close }));
  const vols   = series.map(p => ({ v: p.volume || 0 }));
  const xLabels = series.length ? {
    first: fmt.date(series[0].ts),
    last:  fmt.date(series[series.length-1].ts),
  } : null;
  drawLineChart(canvas, [
    { data: closes, color: AMBER, role: 'price', xLabels },
    { data: (data.ma50  || []).map(v => ({v})), color: '#5fd9ff', role: 'ma' },
    { data: (data.ma200 || []).map(v => ({v})), color: '#ff79c6', role: 'ma' },
    { data: vols, role: 'vol' },
  ], {});
}

// ============ FA ============
async function renderFA(panel) {
  const data = await fetchJSON(`/api/fa/${encodeURIComponent(state.ticker)}`);
  panel.innerHTML = '';
  const meta = `source: ${data.source || '—'} · ${fmt.ts(data.fetched_at)}`;
  panel.innerHTML = `
    <div class="h">FUNDAMENTALS — ${data.ticker} <span class="meta">${meta}</span></div>
    <div class="h">QUARTERS (last 8)</div>
    <table class="t">
      <thead><tr>
        <th>Period End</th><th>Revenue</th><th>Net Income</th><th>EPS Diluted</th>
        <th>Gross Margin</th><th>Net Margin</th>
      </tr></thead>
      <tbody id="fa-q"></tbody>
    </table>
    <div class="h">LATEST FILINGS</div>
    <div class="filings" id="fa-f"></div>
  `;
  const qb = $('#fa-q', panel);
  (data.quarters || []).slice(0, 8).forEach(q => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${fmt.date(q.period_end)}</td>
      <td>${fmt.big(q.revenue)}</td>
      <td class="${q.net_income>=0?'gain':'loss'}">${fmt.big(q.net_income)}</td>
      <td class="${q.diluted_eps>=0?'gain':'loss'}">${fmt.n(q.diluted_eps, 2)}</td>
      <td>${q.gross_margin!=null ? (q.gross_margin*100).toFixed(1)+'%' : '—'}</td>
      <td>${q.net_margin!=null ? (q.net_margin*100).toFixed(1)+'%' : '—'}</td>
    `;
    qb.appendChild(tr);
  });
  const fb = $('#fa-f', panel);
  if (!data.filings?.length) fb.innerHTML = '<div class="muted">no filings</div>';
  (data.filings || []).slice(0, 6).forEach(f => {
    const div = document.createElement('div');
    div.className = 'filing-row';
    div.innerHTML = `<div class="form">${f.form}</div>
      <div class="when">${fmt.date(f.filed_at)}</div>
      <div><a href="${f.url}" target="_blank" rel="noopener">filing ↗</a></div>`;
    fb.appendChild(div);
  });
}

// ============ RISK ============
async function renderRisk(panel) {
  const data = await fetchJSON('/api/risk');
  panel.innerHTML = '';
  const meta = `source: ${data.source || '—'} · ${fmt.ts(data.fetched_at)} · RfR ${fmt.n((data.rfr||0)*100,2)}%`;
  panel.innerHTML = `
    <div class="h">RISK <span class="meta">${meta}</span></div>
    <table class="t">
      <thead><tr>
        <th>Ticker</th><th>Ann Return</th><th>Ann Vol</th><th>Sharpe</th>
        <th>β vs SPY</th><th>Max DD</th>
      </tr></thead>
      <tbody id="r-t"></tbody>
    </table>
    <div class="h">CORRELATION MATRIX</div>
    <canvas id="r-heat" class="heat"></canvas>
  `;
  const tb = $('#r-t', panel);
  (data.tickers || []).forEach(t => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${t.ticker}</td>
      <td class="${t.ann_return>=0?'gain':'loss'}">${fmt.pct(t.ann_return*100,1)}</td>
      <td>${fmt.pct(t.ann_vol*100,1)}</td>
      <td>${fmt.n(t.sharpe,2)}</td>
      <td>${fmt.n(t.beta_spy,2)}</td>
      <td class="loss">${fmt.pct(t.max_drawdown*100,1)}</td>
    `;
    tb.appendChild(tr);
  });
  const corr = data.correlation || { matrix: [], tickers: [] };
  drawHeatmap($('#r-heat', panel), corr.matrix || [], corr.tickers || []);
}

// ============ NEWS ============
async function renderNews(panel) {
  const data = await fetchJSON(`/api/news/${encodeURIComponent(state.ticker)}`);
  panel.innerHTML = '';
  const meta = `source: ${data.source || '—'} · ${fmt.ts(data.fetched_at)} · avg sent ${fmt.n(data.avg_sentiment,2)}`;
  panel.innerHTML = `
    <div class="h">NEWS — ${data.ticker} <span class="meta">${meta}</span></div>
    <div class="news-list" id="n-list"></div>
  `;
  const list = $('#n-list', panel);
  (data.headlines || []).slice(0, 10).forEach(h => {
    const cls = h.sentiment_label === 'positive' ? 'pos'
              : h.sentiment_label === 'negative' ? 'neg' : 'neu';
    const conf = h.sentiment_score != null ? Math.round(Math.abs(h.sentiment_score)*100) + '%' : '—';
    const row = document.createElement('div');
    row.className = 'news-row';
    row.innerHTML = `
      <div><a href="${h.url}" target="_blank" rel="noopener">${escapeHTML(h.title || '')}</a>
        <div class="muted">${escapeHTML(h.publisher || '')}</div></div>
      <div class="when">${fmt.date(h.published_at)}</div>
      <div class="src">${escapeHTML(h.source || '')}</div>
      <div><span class="pill ${cls}">${cls==='pos'?'POS':cls==='neg'?'NEG':'NEU'}</span> ${conf}</div>
    `;
    list.appendChild(row);
  });
  if (!data.headlines?.length) list.innerHTML = '<div class="muted">no headlines</div>';
}
function escapeHTML(s) {
  return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

// ============ ECO ============
async function renderEco(panel) {
  const data = await fetchJSON('/api/eco');
  panel.innerHTML = '';
  const meta = `source: ${data.source || '—'} · ${fmt.ts(data.fetched_at)}`;
  panel.innerHTML = `
    <div class="h">ECONOMICS <span class="meta">${meta}</span></div>
    <div class="row g3">
      <div>
        <div class="h">FED FUNDS (DFF)</div>
        <canvas id="e-dff" class="small"></canvas>
      </div>
      <div>
        <div class="h">CPI YoY</div>
        <canvas id="e-cpi" class="small"></canvas>
      </div>
      <div>
        <div class="h">UNRATE</div>
        <canvas id="e-unr" class="small"></canvas>
      </div>
    </div>
    <div class="h">YIELD CURVE</div>
    <table class="t"><thead><tr><th>Tenor</th><th>Yield</th></tr></thead><tbody id="e-yc"></tbody></table>
  `;
  drawSeries($('#e-dff', panel), data.dff, AMBER);
  drawSeries($('#e-cpi', panel), data.cpi_yoy, '#5fd9ff');
  drawSeries($('#e-unr', panel), data.unrate, '#ff79c6');
  const yb = $('#e-yc', panel);
  const yc = data.yield_curve || {};
  [['3M', yc['3M']], ['2Y', yc['2Y']], ['10Y', yc['10Y']]].forEach(([k, v]) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${k}</td><td>${v==null?'—':fmt.n(v,2)+'%'}</td>`;
    yb.appendChild(tr);
  });
}
function drawSeries(canvas, arr, color) {
  const data = (arr || []).map(p => ({ v: p.value }));
  const xLabels = arr && arr.length ? {
    first: fmt.date(arr[0].ts),
    last:  fmt.date(arr[arr.length-1].ts),
  } : null;
  drawLineChart(canvas, [{ data, color, role: 'price', xLabels }], {});
}