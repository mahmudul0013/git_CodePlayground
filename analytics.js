/* ============================================================
   ANALYTICS PAGE — analytics.js
   Data comes from server.py -> /api/trades (parsed from the Nordnet
   CSVs). The page polls /api/trades/status and reloads on change.
   ============================================================ */
'use strict';

const POLL_MS = 10_000;
const C = { s: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
            other: '#5d6170', green: '#26A69A', red: '#EF5350', dim: '#787B86', grid: '#2A2E39' };

const COUNTRY = { US: 'United States', SE: 'Sweden', NO: 'Norway', DE: 'Germany', GB: 'United Kingdom',
  IE: 'Ireland', LU: 'Luxembourg', NL: 'Netherlands', FI: 'Finland', DK: 'Denmark', CA: 'Canada',
  FR: 'France', KY: 'Cayman Is.', JE: 'Jersey', CH: 'Switzerland', IT: 'Italy', ES: 'Spain', BM: 'Bermuda',
  IL: 'Israel', CN: 'China', TW: 'Taiwan', JP: 'Japan', BE: 'Belgium', AT: 'Austria', '??': 'Unknown' };

const VIEWS = [
  { id: 'all',     label: 'All ever held',     cls: '',     hint: 'Every asset that ever appears in your transaction history — held now or not.' },
  { id: 'current', label: 'Currently held',    cls: '',     hint: 'Assets with a quantity above zero according to the ledger (cross-checked with the holdings export).' },
  { id: 'closed',  label: 'Sold out / closed', cls: '',     hint: 'Assets you traded in the past but no longer hold.' },
  { id: 'buy1w',   label: 'Bought · 1 week',   cls: 'buy',  hint: 'Assets with at least one buy in the window.', win: 'w' },
  { id: 'buy1m',   label: 'Bought · 1 month',  cls: 'buy',  hint: 'Assets with at least one buy in the window.', win: 'm' },
  { id: 'sell1w',  label: 'Sold · 1 week',     cls: 'sell', hint: 'Assets with at least one sell in the window.', win: 'w' },
  { id: 'sell1m',  label: 'Sold · 1 month',    cls: 'sell', hint: 'Assets with at least one sell in the window.', win: 'm' },
];

const S = {
  data: null, sig: null, tab: 'assets', view: 'current',
  type: '', ccy: '', dom: '', q: '',
  sort: { key: 'metric', dir: -1 }, open: new Set(), charts: {}, gran: 'month', dgran: 'month', metric: 'value', idx: new Set(), overlay: null,
};

// ───────── helpers ─────────
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf0 = new Intl.NumberFormat('sv-SE', { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat('sv-SE', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const fmt = n => (n == null || isNaN(n)) ? '—' : nf0.format(Math.round(n)).replace('−', '-');
const fmt2 = n => (n == null || isNaN(n)) ? '—' : nf2.format(n).replace('−', '-');
const sgn = n => (n == null || isNaN(n)) ? '—' : (n > 0 ? '+' : '') + fmt(n);
const pct = (n, d = 1) => (n == null || isNaN(n)) ? '—' : n.toFixed(d).replace('.', ',') + '%';
const cls = n => n > 0 ? 'pos' : n < 0 ? 'neg' : '';
const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');

function windowStart(kind) {
  const d = new Date();
  if (kind === 'w') d.setDate(d.getDate() - 7); else d.setMonth(d.getMonth() - 1);
  return iso(d);
}

async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  const j = await r.json();
  if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}

// ───────── data load + auto-sync ─────────
// The server values everything once (valuation.py): /api/trades is already live-valued, and /api/snapshot (small) carries the
// same valuation for the 30 s refresh. The browser does no pricing of its own, it only copies those numbers into S.data.
const SNAP_MS = 30_000, HISTORY_RETRY_MS = 20_000;
const tolerance = x => Math.max(5, 0.0005 * Math.abs(x));      // same rule as valuation.allowed(): rounding / FX differences up to 5 kr or 0.05%
const SCORE = (v, good, poor, lower) => { if (v == null) return null; const t = lower ? (poor - v) / (poor - good || 1) : (v - poor) / (good - poor || 1); return Math.round(Math.max(0, Math.min(1, t)) * 100); };
const GRADE = s => s >= 85 ? 'A' : s >= 70 ? 'B' : s >= 55 ? 'C' : s >= 40 ? 'D' : s >= 25 ? 'E' : 'F';

function mergeSnapshot(snap) {
  const D = S.data;
  if (!D || !snap || !snap.ok) return false;
  const t = snap.totals, o = D.insights.overview;
  for (const a of D.assets) {
    const s = snap.assets[a.isin];
    if (!s) continue;
    a.value = s.value; a.price = s.price; a.unrealized = s.unrealized; a.unrealized_pct = s.unrealized_pct; a.day_pct = s.day_pct; a.live = s.live;
    a.total_pnl = Math.round(((a.realized || 0) + s.unrealized) * 100) / 100;
  }
  Object.assign(o, { holdings_value: t.holdings, total_value: t.account, unrealized: t.unrealized, all_time_pnl: t.all_time, all_time_pnl_pct: t.all_time_pct });
  D.valuation = Object.assign(D.valuation || {}, { asof: snap.asof, export_date: snap.export_date, live_positions: t.live_positions, positions: t.positions });
  // the two habit scores that depend on position sizes follow the live values (same formulas as trade_analytics.build_scorecard)
  const sc = D.insights.scorecard, held = D.assets.filter(a => a.held && a.value);
  if (sc && held.length) {
    const tot = held.reduce((x, a) => x + a.value, 0);
    const vals = { top_weight: Math.max(...held.map(a => a.value)) / tot * 100, fragmentation: held.filter(a => a.value < 2000).length / held.length * 100 };
    let ws = 0, ss = 0;
    for (const i of sc.items) {
      if (i.key in vals) { i.value = Math.round(vals[i.key] * 100) / 100; i.score = SCORE(vals[i.key], i.good, i.poor, i.lower_is_better); }
      if (i.score != null) { ws += i.weight; ss += i.score * i.weight; }
    }
    if (ws) { sc.overall = Math.round(ss / ws); sc.grade = GRADE(sc.overall); }
  }
  return true;
}

let snapBusy = false;
async function refreshSnapshot() {
  if (snapBusy || !S.data) return;
  snapBusy = true;
  try {
    if (!mergeSnapshot(await getJSON('/api/snapshot'))) return;
    renderKpis();
    if (S.tab === 'assets') renderAssetsLight();
    // tabs with charts are redrawn only when the account value moved by more than the accepted rounding tolerance
    const tv = S.data.insights.overview.total_value;
    if (S.tabValue != null && Math.abs(tv - S.tabValue) > tolerance(tv) && ['assets', 'habits', 'deposits', 'dividends'].includes(S.tab)) renderTab();
    setSync(true);
  } catch (e) { /* keep the numbers on screen */ } finally { snapBusy = false; }
}

let historyTimer = 0;
function watchHistory() {
  clearTimeout(historyTimer);
  const pending = !!(S.data && S.data.valuation && S.data.valuation.history_pending);
  const hint = $('dep-pending'); if (hint) hint.hidden = !pending;
  if (pending) historyTimer = setTimeout(() => load(true), HISTORY_RETRY_MS);      // the deposit analysis is still being built from Yahoo daily prices
}

async function load(force) {
  try {
    const sig = await getJSON('/api/trades/status');
    const sigStr = JSON.stringify(sig);
    if (!force && sigStr === S.sig && S.data) { setSync(true); loadAdvice(); return; }
    const data = await getJSON('/api/trades');
    S.sig = sigStr;
    S.data = data;
    index();
    setSync(true);
    renderAll();
    watchHistory();
    loadAdvice();
  } catch (e) {
    setSync(false, e.message);
    if (!S.data) showBanner('Could not load data: ' + e.message + '. Start the app with <b>python server.py</b> and open http://localhost:8000/analytics.html', true);
  }
}

function setSync(ok, err) {
  $('sync-dot').className = 'dot ' + (ok ? 'live' : 'err');
  if (!ok) { $('sync-text').textContent = 'Offline — ' + (err || ''); return; }
  const s = S.data.sources, t = s.transactions, h = s.holdings;
  const stamp = x => x ? new Date(x.mtime * 1000).toLocaleString('sv-SE').slice(0, 16) : '—';
  const stale = t && h && t.mtime < h.mtime - 60;   // ledger older than holdings -> quantities may differ
  $('sync-text').textContent = `Synced ${new Date().toLocaleTimeString('sv-SE')} · holdings: ${h ? h.file : 'none'} (${stamp(h)})`
    + ` · ledger: ${t ? t.file : 'none'} (${stamp(t)})` + (stale ? ' — ledger is older than holdings, export transactions again' : '');
}

function showBanner(html, isErr) {
  const b = $('banner');
  b.hidden = !html; b.className = 'banner' + (isErr ? ' err' : '');
  b.innerHTML = html || '';
}

function index() {
  S.byIsin = new Map();
  for (const t of S.data.trades) {
    if (!S.byIsin.has(t.isin)) S.byIsin.set(t.isin, []);
    S.byIsin.get(t.isin).push(t);
  }
  S.data.assets.forEach(a => { a.trades = S.byIsin.get(a.isin) || []; });
}

// ───────── asset view logic ─────────
function viewDef() { return VIEWS.find(v => v.id === S.view); }

/** Per-asset stats restricted to the active view's date window (or all-time). */
function windowed(a, v) {
  const from = v.win ? windowStart(v.win) : null;
  const side = v.id.startsWith('buy') ? 'BUY' : v.id.startsWith('sell') ? 'SELL' : null;
  let bought = 0, sold = 0, nb = 0, ns = 0;
  for (const t of a.trades) {
    if (from && t.date < from) continue;
    if (t.side === 'BUY') { bought += t.amount; nb++; } else { sold += t.amount; ns++; }
  }
  return { from, side, bought, sold, nb, ns };
}

function inView(a, v, w) {
  switch (v.id) {
    case 'all': return true;
    case 'current': return a.held;
    case 'closed': return !a.held;
    default: return v.id.startsWith('buy') ? w.nb > 0 : w.ns > 0;
  }
}

function metricFor(a, v, w) {
  if (v.id === 'current') return a.value;
  if (v.id.startsWith('buy')) return w.bought;
  if (v.id.startsWith('sell')) return w.sold;
  return a.bought_sek;
}
function metricName(v) {
  if (v.id === 'current') return 'Market value (SEK)';
  if (v.id.startsWith('buy')) return 'Bought in window (SEK)';
  if (v.id.startsWith('sell')) return 'Sold in window (SEK)';
  return 'Total bought, all-time (SEK)';
}

function derive() {
  const v = viewDef();
  const rows = S.data.assets.map(a => {
    const w = windowed(a, v);
    return { a, w, metric: metricFor(a, v, w) };
  });
  const counts = {};
  for (const vv of VIEWS) counts[vv.id] = rows.filter(r => inView(r.a, vv, windowed(r.a, vv))).length;
  const q = S.q.trim().toLowerCase();
  const list = rows.filter(r =>
    inView(r.a, v, r.w) &&
    (!S.type || r.a.type === S.type) && (!S.ccy || r.a.ccy === S.ccy) && (!S.dom || r.a.domicile === S.dom) &&
    (!q || r.a.name.toLowerCase().includes(q)));
  return { v, rows, list, counts };
}

function sortVal(r, key) {
  const a = r.a, w = r.w;
  switch (key) {
    case 'metric': return r.metric;
    case 'name': return a.name.toLowerCase();
    case 'type': return a.type; case 'ccy': return a.ccy; case 'status': return a.held ? 1 : 0;
    case 'advice': { const v = adviceOf(a); return v ? (ADV_RANK[v.action] ?? 9) * 1000 - v.score : 9999; }
    case 'qty': return a.qty; case 'value': return a.value;
    case 'bought': return w.bought; case 'sold': return w.sold;
    case 'trades': return w.nb + w.ns;
    case 'last_buy': return a.last_buy || ''; case 'last_sell': return a.last_sell || '';
    case 'fees': return a.fees; case 'realized': return a.realized;
    case 'unrealized': return a.unrealized; case 'total_pnl': return a.total_pnl;
    default: return 0;
  }
}

// ───────── render: top ─────────
function renderAll() {
  const w = S.data.warnings || [];
  showBanner(w.length ? `<b>Data notes (${w.length}):</b><ul>${w.slice(0, 8).map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '');
  renderKpis();
  renderTab();
}

function kpi(l, v, s, c) {
  return `<div class="kpi"><div class="l">${l}</div><div class="v ${c || ''}">${v}</div><div class="s">${s || ''}</div></div>`;
}

function renderKpis() {
  const o = S.data.insights.overview, c = S.data.insights.costs, v = S.data.valuation || {};
  const valued = v.asof ? `valued ${v.asof.slice(11, 16)} · live prices for ${v.live_positions} of ${v.positions} holdings` : '';
  $('kpis').innerHTML =
    kpi('Account value', fmt(o.total_value) + ' kr', `holdings ${fmt(o.holdings_value)} + cash ${fmt(o.cash_balance)}${valued ? ' · ' + valued : ''}`) +
    kpi('Deposited (net)', fmt(o.net_deposits) + ' kr', `${o.deposit_count} deposits`) +
    kpi('All-time result', sgn(o.all_time_pnl) + ' kr', o.all_time_pnl_pct == null ? '' : `${pct(o.all_time_pnl_pct, 2)} on deposits`, cls(o.all_time_pnl)) +
    kpi('Broker costs paid', fmt(c.broker_total) + ' kr', `${pct(c.pct_of_net_deposits)} of deposits · ${pct(c.pct_of_turnover, 2)} of turnover`, 'neg') +
    kpi('Realised (after fees)', sgn(o.realized) + ' kr', `${o.sells} sells`, cls(o.realized)) +
    kpi('Unrealised', sgn(o.unrealized) + ' kr', `${o.held_assets} open positions`, cls(o.unrealized)) +
    kpi('Data range', `${o.first_date.slice(2)} → ${o.last_date.slice(2)}`, `${o.trades} trades · ${o.distinct_assets} assets`);
}

// ───────── render: assets tab ─────────
function renderAssetKpis(d) {
  const { v, list } = d;
  const sum = f => list.reduce((s, r) => s + (f(r) || 0), 0);
  const mt = sum(r => r.metric);
  $('asset-kpis').innerHTML =
    kpi('Assets', list.length, `${list.filter(r => r.a.held).length} held now`) +
    kpi(metricName(v), fmt(mt), v.id === 'current' ? 'sum of current holdings' : '') +
    kpi('Realised (all-time)', sgn(sum(r => r.a.realized)), 'closed trades, after fees', cls(sum(r => r.a.realized))) +
    kpi('Unrealised', sgn(sum(r => r.a.unrealized)), 'open positions', cls(sum(r => r.a.unrealized))) +
    kpi('Fees paid (all-time)', fmt(sum(r => r.a.fees)), `${sum(r => r.a.trades.length)} trades`);
}

// 30 s refresh of the Assets tab: only the KPI row and the table (the three charts follow when the value moved beyond the tolerance)
function renderAssetsLight() { const d = derive(); renderAssetKpis(d); renderTable(d); }

function renderAssets() {
  const d = derive();
  const { v, list } = d;

  // chips
  $('view-chips').innerHTML = VIEWS.map(x =>
    `<button class="chip ${x.cls} ${x.id === S.view ? 'active' : ''}" data-v="${x.id}">${x.label}<span class="n">${d.counts[x.id]}</span></button>`).join('');
  const from = v.win ? windowStart(v.win) : null;
  $('view-hint').textContent = v.hint + (from ? ` Window: ${from} → today (${iso(new Date())}).` : '') +
    ` Showing ${list.length} of ${d.rows.length} assets.`;

  // filter option lists (built from all assets so options stay stable)
  fillSelect('f-type', 'All types', uniq(S.data.assets.map(a => a.type)), S.type);
  fillSelect('f-ccy', 'All currencies', uniq(S.data.assets.map(a => a.ccy)), S.ccy);
  fillSelect('f-dom', 'All countries', uniq(S.data.assets.map(a => a.domicile)), S.dom, k => `${k} · ${COUNTRY[k] || k}`);

  renderAssetKpis(d);

  // charts
  const group = key => {
    const m = new Map();
    for (const r of list) if (r.metric > 0) m.set(r.a[key], (m.get(r.a[key]) || 0) + r.metric);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  };
  const mn = metricName(v);
  $('t-type').textContent = 'By type · ' + mn;
  $('t-dom').textContent = 'By country (ISIN) · ' + mn;
  $('t-top').textContent = 'Top assets · ' + mn;
  doughnut('c-type', group('type'), k => k);
  doughnut('c-dom', group('domicile'), k => `${COUNTRY[k] || k}`);
  const top = [...list].filter(r => r.metric > 0).sort((a, b) => b.metric - a.metric).slice(0, 12);
  mkChart('c-top', {
    type: 'bar',
    data: { labels: top.map(r => r.a.name.length > 26 ? r.a.name.slice(0, 25) + '…' : r.a.name), datasets: [{ data: top.map(r => r.metric), backgroundColor: C.s[0], borderRadius: 4, maxBarThickness: 14 }] },
    options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ' ' + fmt(c.parsed.x) + ' kr' } } },
      scales: { x: { grid: { color: C.grid }, ticks: { callback: v => fmt(v) } }, y: { grid: { display: false }, ticks: { font: { size: 10 } } } } },
  });

  renderTable(d);
}

function uniq(a) { return [...new Set(a)].sort(); }
function fillSelect(id, allLabel, vals, cur, label) {
  $(id).innerHTML = `<option value="">${allLabel}</option>` +
    vals.map(x => `<option value="${esc(x)}" ${x === cur ? 'selected' : ''}>${esc(label ? label(x) : x)}</option>`).join('');
}

function doughnut(id, entries, nameFn) {
  const MAX = 7;
  let items = entries.slice(0, MAX);
  const rest = entries.slice(MAX).reduce((s, e) => s + e[1], 0);
  const labels = items.map(e => nameFn(e[0])), data = items.map(e => e[1]);
  const colors = items.map((_, i) => C.s[i]);
  if (rest > 0) { labels.push('Other'); data.push(rest); colors.push(C.other); }
  const total = data.reduce((a, b) => a + b, 0);
  mkChart(id, {
    type: 'doughnut',
    data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: '#1E2130', borderWidth: 2 }] },
    options: { cutout: '58%', plugins: {
      legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, font: { size: 11 },
        generateLabels: ch => ch.data.labels.map((l, i) => ({ text: `${l} ${total ? (data[i] / total * 100).toFixed(0) : 0}%`,
          fillStyle: colors[i], strokeStyle: colors[i], index: i, fontColor: '#D1D4DC' })) } },
      tooltip: { callbacks: { label: c => ` ${c.label}: ${fmt(c.parsed)} kr (${total ? (c.parsed / total * 100).toFixed(1) : 0}%)` } } } },
  });
}

function mkChart(id, cfg) {
  if (S.charts[id]) S.charts[id].destroy();
  const el = $(id);
  if (!el || typeof Chart === 'undefined') return;
  cfg.options = cfg.options || {};
  cfg.options.responsive = true;
  cfg.options.maintainAspectRatio = false;
  cfg.options.animation = { duration: 250 };
  S.charts[id] = new Chart(el, cfg);
}

function col(key, label, sortable = true) { return { key, label, sortable }; }

function renderTable(d) {
  const { v, list } = d;
  const win = v.win ? (v.win === 'w' ? ' (1W)' : ' (1M)') : '';
  const cols = [
    col('name', 'Asset'), col('type', 'Type · Ccy'), col('status', 'Status'), col('advice', 'Add / trim'),
    col('qty', 'Qty'), col('value', 'Value kr'),
    col('bought', 'Bought kr' + win), col('sold', 'Sold kr' + win), col('trades', 'Buys / sells' + win),
    col('fees', 'Fees kr'), col('realized', 'Realised kr'), col('unrealized', 'Unrealised kr'), col('total_pnl', 'Total P&L kr'),
  ];
  const { key, dir } = S.sort;
  const rows = [...list].sort((x, y) => {
    const a = sortVal(x, key), b = sortVal(y, key);
    return (a < b ? -1 : a > b ? 1 : 0) * dir;
  });
  const th = cols.map(c => `<th class="sortable" data-k="${c.key}">${c.label}${c.key === key ? `<span class="arr">${dir > 0 ? '▲' : '▼'}</span>` : ''}</th>`).join('');
  const body = rows.map(r => {
    const a = r.a, w = r.w, open = S.open.has(a.isin);
    let h = `<tr class="row" data-i="${esc(a.isin)}">
      <td class="name" title="${esc(a.name)} · ${esc(a.isin)}">${open ? '▾' : '▸'} ${esc(a.name)}</td>
      <td class="tag tl">${esc(a.type)} · ${esc(a.ccy)}</td>
      <td><span class="badge ${a.held ? 'held' : 'closed'}">${a.held ? 'Held' : 'Closed'}</span></td>
      <td class="adv-td">${adviceCell(a)}</td>
      <td>${a.held ? fmt2(a.qty).replace(/,00$/, '') : '—'}</td><td>${a.held ? fmt(a.value) : '—'}</td>
      <td>${fmt(w.bought)}</td><td>${fmt(w.sold)}</td><td>${w.nb} / ${w.ns}</td>
      <td>${fmt(a.fees)}</td><td class="${cls(a.realized)}">${sgn(a.realized)}</td>
      <td class="${cls(a.unrealized)}">${a.held ? sgn(a.unrealized) : '—'}</td><td class="${cls(a.total_pnl)}">${sgn(a.total_pnl)}</td></tr>`;
    if (open) h += `<tr class="detail"><td colspan="${cols.length}">${detail(a)}</td></tr>`;
    return h;
  }).join('');
  const sum = f => list.reduce((s, r) => s + (f(r) || 0), 0);
  const foot = `<tr><td>Total (${list.length})</td><td></td><td></td><td></td><td></td><td>${fmt(sum(r => r.a.value))}</td>
    <td>${fmt(sum(r => r.w.bought))}</td><td>${fmt(sum(r => r.w.sold))}</td><td>${sum(r => r.w.nb)} / ${sum(r => r.w.ns)}</td>
    <td>${fmt(sum(r => r.a.fees))}</td><td>${sgn(sum(r => r.a.realized))}</td><td>${sgn(sum(r => r.a.unrealized))}</td><td>${sgn(sum(r => r.a.total_pnl))}</td></tr>`;
  $('asset-table').innerHTML = `<thead><tr>${th}</tr></thead><tbody>${body || `<tr><td colspan="${cols.length}" style="text-align:center;padding:24px;color:var(--text-dim)">No assets match this filter.</td></tr>`}</tbody><tfoot>${foot}</tfoot>`;
  $('table-title').textContent = `${v.label} — ${list.length} assets`;
  if (window.AssetChart) {
    document.querySelectorAll('.asset-chart[data-chart]').forEach(el => {
      const a = S.data.assets.find(x => x.isin === el.dataset.chart);
      if (a) AssetChart.render(el, a);
    });
  }
  S.lastList = list;
}

function detail(a) {
  const rows = [...a.trades].reverse().map(t => `<tr>
    <td>${t.date}</td><td class="${t.side === 'BUY' ? 'buy-t' : 'sell-t'}">${t.side === 'BUY' ? 'Buy' : 'Sell'}</td>
    <td>${t.qty}</td><td>${t.price == null ? '—' : fmt2(t.price) + ' ' + esc(t.ccy)}</td><td>${fmt(t.amount)}</td><td>${fmt2(t.fee)}</td>
    <td class="${cls(t.realized)}">${t.realized == null ? '—' : sgn(t.realized)}</td><td>${t.hold_days == null ? '—' : t.hold_days + ' d'}</td><td>${t.pos_after}</td></tr>`).join('');
  return `<div class="asset-chart" data-chart="${esc(a.isin)}"></div><div class="detail-inner"><table><thead><tr><th>Date</th><th>Side</th><th>Qty</th><th>Price</th><th>Amount kr</th><th>Fee kr</th><th>Realised kr</th><th>Held</th><th>Position after</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function exportCsv() {
  const v = viewDef();
  const head = ['Name', 'ISIN', 'Type', 'Currency', 'Held', 'Qty', 'ValueSEK', 'BoughtSEK', 'SoldSEK', 'Buys', 'Sells', 'LastBuy', 'LastSell', 'FeesSEK', 'RealizedSEK', 'UnrealizedSEK', 'TotalPnlSEK'];
  const lines = [head.join(';')].concat((S.lastList || []).map(r => {
    const a = r.a, w = r.w;
    return [a.name, a.isin, a.type, a.ccy, a.held ? 'yes' : 'no', a.qty, a.value, w.bought.toFixed(2), w.sold.toFixed(2), w.nb, w.ns,
      a.last_buy || '', a.last_sell || '', a.fees, a.realized, a.unrealized, a.total_pnl].map(x => `"${String(x).replace(/"/g, '""')}"`).join(';');
  }));
  const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv' });
  const el = document.createElement('a');
  el.href = URL.createObjectURL(blob); el.download = `assets_${v.id}_${iso(new Date())}.csv`; el.click();
  setTimeout(() => URL.revokeObjectURL(el.href), 2000);
}

// ───────── render: habits tab ─────────
function table(id, head, rows, empty) {
  $(id).innerHTML = `<thead><tr>${head.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${
    rows.length ? rows.map(r => `<tr>${r.map(c => `<td${c && c.c ? ` class="${c.c}"` : ''}>${c && c.v !== undefined ? c.v : c}</td>`).join('')}</tr>`).join('')
      : `<tr><td colspan="${head.length}" style="text-align:center;color:var(--text-dim);padding:14px">${empty || 'Nothing found.'}</td></tr>`}</tbody>`;
}

function renderHabits() {
  const I = S.data.insights, o = I.overview, c = I.costs, sq = I.sell_quality;
  const split = I.split_orders, sd = I.same_day, rb = I.rebuys;

  // ---- verdict cards
  const grossBack = o.all_time_pnl + c.broker_total;
  const feeVsGain = c.fee_vs_realized_gross;
  $('verdict').innerHTML = [
    ['bad', 'Broker costs', fmt(c.broker_total) + ' kr',
      `${pct(c.pct_of_net_deposits)} of everything you deposited. ${c.paid_trades} paid trades at ${fmt2(c.avg_fee_per_paid_trade)} kr on average (courtage ${fmt(c.courtage)}, FX ${fmt(c.fx_fees)}, interest ${fmt(c.interest)}).`],
    [o.all_time_pnl > 0 ? 'warn' : 'bad', 'Account result after all costs', sgn(o.all_time_pnl) + ' kr',
      `Account value ${fmt(o.total_value)} vs ${fmt(o.net_deposits)} deposited. Without broker costs the account would be roughly ${sgn(grossBack)} kr.`],
    [feeVsGain != null && feeVsGain > 50 ? 'bad' : 'warn', 'Fees vs. profit made by selling', feeVsGain == null ? '—' : pct(feeVsGain, 0),
      `Sells made ${sgn(sq.realized_before_fees)} kr before fees; fees were ${fmt(c.trade_fees)} kr. ${feeVsGain >= 100 ? 'Fees took all of it.' : 'Fees took this share of it.'}`],
    ['warn', 'Win rate on sells', pct(sq.win_rate),
      `${sq.wins} winners / ${sq.losses} losers. Avg win ${sgn(sq.avg_win)} kr, avg loss ${sgn(sq.avg_loss)} kr (payoff ${sq.payoff_ratio ?? '—'}×, profit factor ${sq.profit_factor ?? '—'}).`],
  ].map(([k, t, b, p]) => `<div class="vcard ${k}"><div class="t">${t}</div><div class="big">${b}</div><p>${p}</p></div>`).join('');

  renderScore();

  // ---- findings
  const sizeRows = I.fee_by_size;
  const bench = (sizeRows.find(r => r.bucket === '> 10k') || sizeRows[sizeRows.length - 1]).fee_pct;
  const small = sizeRows.filter(r => ['< 500', '500-1k', '1k-2.5k'].includes(r.bucket));
  const premium = small.reduce((s, r) => s + Math.max(0, r.fees - r.turnover * bench / 100), 0);
  const smallTrades = small.reduce((s, r) => s + r.trades, 0);
  const hb = Object.fromEntries(I.hold_buckets.map(b => [b.bucket, b]));
  const flip = hb['0-1 d'], quick = hb['2-7 d'];
  const churnTop = I.churn_assets.slice(0, 3);
  const best = I.hold_buckets.filter(b => b.sells >= 20).sort((a, b) => b.net - a.net)[0];

  const F = [];
  F.push(['high', 'Many small orders', `${fmt(premium)} kr`,
    `${smallTrades} trades were under 2 500 kr. Their fees averaged ${pct(small.reduce((s, r) => s + r.fees, 0) / small.reduce((s, r) => s + r.turnover, 0) * 100, 2)} of value versus ${pct(bench, 2)} on trades over 10 000 kr — the extra paid is the figure above.`,
    `${I.small_trades.count} trades had fees ≥ 1% of their value (${fmt(I.small_trades.fees)} kr in fees).`]);
  F.push(['high', 'Same order split into pieces', `${fmt(split.avoidable_fees)} kr`,
    `${split.groups} cases where you bought or sold the same asset on the same day in 2+ separate orders (${split.extra_orders} extra orders). Each order pays its own courtage.`,
    'Estimate: one combined order per day/asset/side would have paid only the largest single fee of each group.']);
  if (flip && flip.sells) F.push(['high', 'Sold within 1 day of buying', `${sgn(flip.net)} kr`,
    `${flip.sells} sells held 0–1 days: only ${pct(flip.win_rate, 0)} were profitable, net ${sgn(flip.net)} kr after ${fmt(flip.fees)} kr fees on ${fmt(flip.turnover)} kr traded.`,
    quick ? `Holding 2–7 days: ${quick.sells} sells, ${pct(quick.win_rate, 0)} winners, net ${sgn(quick.net)} kr.` : '']);
  F.push(['med', 'Same-day buy and sell of one asset', `${fmt(sd.fees)} kr fees`,
    `${sd.count} day/asset combinations where you both bought and sold the same asset on the same day. Realised on those days: ${sgn(sd.realized)} kr.`,
    sd.top[0] ? `Most expensive: ${esc(sd.top[0].name)} on ${sd.top[0].date} (${fmt(sd.top[0].fees)} kr in fees).` : '']);
  F.push(['med', 'Fees that wiped out the gain', `${sq.fee_eaten_count} sells`,
    `${sq.fee_eaten_count} sells were profitable before fees but a loss after (${fmt(sq.fee_eaten_fees)} kr fees), and ${sq.thin_profit_count} more kept less than half of their gross gain.`,
    'Typical when a small profit target is combined with a flat ~9 kr courtage per order.']);
  F.push(['info', 'Sell, then buy back within 14 days', `${rb.count} cases`,
    `${rb.better} buy-backs were cheaper than your sale price and ${rb.worse} were more expensive; price effect ${sgn(rb.net_effect)} kr, but the round trips cost ${fmt(rb.fees)} kr in fees.`,
    'This pattern is not clearly a mistake — the price effect is positive — but check whether it beats simply holding after fees.']);
  if (churnTop.length) F.push(['info', 'Most traded assets', `${churnTop[0].trades} trades`,
    churnTop.map(a => `${esc(a.name)} ${a.trades} trades / ${fmt(a.fees)} kr fees / total ${sgn(a.total_pnl)} kr`).join(' · '), 'See the table "Most-traded assets" below.']);
  if (best) F.push(['info', 'Where your results were best', best.bucket,
    `Holding ${best.bucket}: ${best.sells} sells, ${pct(best.win_rate, 0)} winners, net ${sgn(best.net)} kr after ${fmt(best.fees)} kr fees.`, '']);
  F.push(['info', 'Trading rhythm', `${I.rhythm.trades_per_active_day} / active day`,
    `${o.trades} trades on ${o.active_days} of ${o.days_span} calendar days; ${I.rhythm.days_with_10plus} days had 10+ trades. Median sell size ${fmt(sq.median_sell_size)} kr, median holding ${sq.median_hold_days} days.`, '']);
  $('findings').innerHTML = F.map(([sev, t, num, p, tip]) =>
    `<div class="finding"><h4><span class="sev ${sev}">${sev === 'high' ? 'HIGH' : sev === 'med' ? 'MEDIUM' : 'INFO'}</span>${t}</h4><div class="num">${num}</div><p>${p}</p>${tip ? `<div class="tip">${tip}</div>` : ''}</div>`).join('');

  // ---- charts
  const base = { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { grid: { color: C.grid }, ticks: { callback: v => fmt(v) } } } };
  const dates = I.cumulative.map(x => x.date);
  mkChart('h-cum', { type: 'line',
    data: { labels: dates, datasets: [
      { label: 'Cumulative fees', data: I.cumulative.map(x => x.fees), borderColor: C.s[1], backgroundColor: C.s[1], borderWidth: 2, pointRadius: 0, tension: .15 },
      { label: 'Cumulative realised P&L (after fees)', data: I.cumulative.map(x => x.realized), borderColor: C.s[0], backgroundColor: C.s[0], borderWidth: 2, pointRadius: 0, tension: .15 },
    ] },
    options: { interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: true, labels: { boxWidth: 10, boxHeight: 10 } },
      tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${fmt(c.parsed.y)} kr` } } },
      scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { grid: { color: C.grid }, ticks: { callback: v => fmt(v) } } } } });
  mkChart('h-held', { type: 'line',
    data: { labels: I.held_over_time.map(x => x.date), datasets: [{ label: 'Positions held', data: I.held_over_time.map(x => x.held), borderColor: C.s[2], backgroundColor: C.s[2], borderWidth: 2, pointRadius: 0, stepped: true }] },
    options: { interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false } },
      scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { grid: { color: C.grid }, beginAtZero: true } } } });
  const months = I.monthly.map(m => m.month);
  mkChart('h-trades', { type: 'bar', data: { labels: months, datasets: [
    { label: 'Buys', data: I.monthly.map(m => m.buys), backgroundColor: C.s[2], borderRadius: 3, stack: 's' },
    { label: 'Sells', data: I.monthly.map(m => m.sells), backgroundColor: C.s[1], borderRadius: 3, stack: 's' }] },
    options: { plugins: { legend: { display: true, labels: { boxWidth: 10, boxHeight: 10 } } }, scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, grid: { color: C.grid } } } } });
  mkChart('h-fees', { type: 'bar', data: { labels: months, datasets: [{ label: 'Fees', data: I.monthly.map(m => m.fees), backgroundColor: C.s[1], borderRadius: 4 }] },
    options: { ...base, plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: c => `${I.monthly[c.dataIndex].trades} trades` } } } } });
  mkChart('h-vol', { type: 'bar', data: { labels: months, datasets: [
    { label: 'Bought', data: I.monthly.map(m => m.buy_sek), backgroundColor: C.s[2], borderRadius: 3 },
    { label: 'Sold', data: I.monthly.map(m => m.sell_sek), backgroundColor: C.s[1], borderRadius: 3 }] },
    options: { plugins: { legend: { display: true, labels: { boxWidth: 10, boxHeight: 10 } }, tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${fmt(c.parsed.y)} kr` } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: C.grid }, ticks: { callback: v => fmt(v) } } } } });
  const wd = I.weekday.filter(d => d.trades > 0);
  mkChart('h-wd', { type: 'bar', data: { labels: wd.map(d => d.day), datasets: [{ label: 'Trades', data: wd.map(d => d.trades), backgroundColor: C.s[0], borderRadius: 4 }] },
    options: { ...base, plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: c => `fees ${fmt(wd[c.dataIndex].fees)} kr` } } } } });
  mkChart('h-size', { type: 'bar', data: { labels: sizeRows.map(r => r.bucket), datasets: [{ label: 'Fee %', data: sizeRows.map(r => r.fee_pct), backgroundColor: sizeRows.map(r => r.fee_pct > 0.6 ? C.s[1] : C.s[0]), borderRadius: 4 }] },
    options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.parsed.y.toFixed(2)}% of value`, afterLabel: c => `${sizeRows[c.dataIndex].trades} trades · ${fmt(sizeRows[c.dataIndex].fees)} kr fees` } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: C.grid }, ticks: { callback: v => v + '%' } } } } });
  const hbRows = I.hold_buckets.filter(b => b.sells > 0);
  mkChart('h-hold', { type: 'bar', data: { labels: hbRows.map(b => b.bucket), datasets: [{ label: 'Net realised', data: hbRows.map(b => b.net), backgroundColor: hbRows.map(b => b.net >= 0 ? C.green : C.red), borderRadius: 4 }] },
    options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${sgn(c.parsed.y)} kr`, afterLabel: c => `${hbRows[c.dataIndex].sells} sells · ${pct(hbRows[c.dataIndex].win_rate, 0)} winners` } } },
      scales: { x: { grid: { display: false } }, y: { grid: { color: C.grid }, ticks: { callback: v => fmt(v) } } } } });

  // ---- tables
  table('tb-size', ['Trade size kr', 'Trades', 'Turnover kr', 'Fees kr', 'Fee %'],
    sizeRows.map(r => [r.bucket, r.trades, fmt(r.turnover), fmt(r.fees), { v: pct(r.fee_pct, 2), c: r.fee_pct > 0.6 ? 'neg' : '' }]));
  table('tb-hold', ['Held', 'Sells', 'Win rate', 'Net kr', 'Fees kr', 'Fee-eaten'],
    I.hold_buckets.filter(b => b.sells).map(b => [b.bucket, b.sells, pct(b.win_rate, 0), { v: sgn(b.net), c: cls(b.net) }, fmt(b.fees), b.fee_eaten]));
  table('tb-costs', ['Item', 'SEK', 'Note'], [
    ['Courtage (commission)', fmt(c.courtage), `${c.paid_trades} paid trades`],
    ['FX / other trade fees', fmt2(c.fx_fees), 'Total fee minus courtage'],
    ['Debit / overdraft interest', fmt2(c.interest), ''],
    ['ADR & other fees', fmt2(c.other_fees), ''],
    ['Fund-fee refunds', { v: '−' + fmt2(c.fee_refunds), c: 'pos' }, 'Reduces cost'],
    [{ v: '<b>Total broker cost</b>' }, { v: '<b>' + fmt(c.broker_total) + '</b>' }, `${pct(c.pct_of_net_deposits)} of deposits`],
    ['Withholding tax on dividends', fmt2(c.dividend_tax), 'Tax, not broker cost (not in total)'],
    ['Dividends received (gross)', fmt2(o.dividends), ''],
  ]);
  table('tb-churn', ['Asset', 'Trades', 'Fees kr', 'Realised', 'Unrealised', 'Total'],
    I.churn_assets.map(a => [esc(a.name) + (a.held ? '' : ' <span class="tag">(closed)</span>'), a.trades, fmt(a.fees), { v: sgn(a.realized), c: cls(a.realized) }, { v: sgn(a.unrealized), c: cls(a.unrealized) }, { v: sgn(a.total_pnl), c: cls(a.total_pnl) }]));
  table('tb-split', ['Date', 'Asset', 'Side', 'Orders', 'Fees kr', 'Avoidable kr'],
    split.top.map(s => [s.date, esc(s.name), s.side === 'BUY' ? { v: 'Buy', c: 'buy-t' } : { v: 'Sell', c: 'sell-t' }, s.orders, fmt(s.fees), fmt(s.avoidable)]));
  table('tb-sameday', ['Date', 'Asset', 'Bought kr', 'Sold kr', 'Fees kr', 'Realised kr'],
    sd.top.map(s => [s.date, esc(s.name), fmt(s.buy_amount), fmt(s.sell_amount), fmt(s.fees), { v: sgn(s.realized), c: cls(s.realized) }]));
  table('tb-rebuy', ['Asset', 'Sold', 'Rebought', 'Sell kr/sh', 'Buy kr/sh', 'Effect kr'],
    rb.worst.map(r => [esc(r.name), r.sold, r.rebought, fmt(r.sell_price_sek), fmt(r.buy_price_sek), { v: sgn(r.effect), c: cls(r.effect) }]));
  table('tb-busy', ['Date', 'Trades'], I.rhythm.busiest_days.map(b => [b.date, b.trades]));

  $('method').innerHTML = [
    `Source files: <b>${esc(S.data.sources.transactions?.file || '—')}</b> (ledger) and <b>${esc(S.data.sources.holdings?.file || 'none')}</b> (current holdings). Drop a newer export in the project folder and this page updates by itself within ~${POLL_MS / 1000}s.`,
    'Realised P&L uses the average-cost method in SEK; buy fees are part of cost and sell fees reduce proceeds. Holding time uses FIFO lots. Nordnet\'s own "Resultat" column is converted at the trade FX rate and is shown in the ledger for comparison only, so small differences are expected.',
    'Account result = (holdings value + cash balance) − (deposits − withdrawals). It includes every cost and needs no assumption about prices.',
    'Asset type and country are inferred from the name and the ISIN prefix; the CSV carries no sector data, so none is shown.',
    'Split-order, small-order and re-buy figures are estimates meant to show where behaviour costs money, not exact savings.',
    'Not investment advice — this describes your past activity only.',
  ].map(x => `<li>${x}</li>`).join('');
}

// ───────── render: deposit behaviour tab ─────────
const DEP = { dep: C.s[0], port: C.s[6], held: C.s[2], net: C.dim };
const weekStart = d => { const x = new Date(d + 'T00:00:00'); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return iso(x); };

// One row per day -> one row per bucket. Deposits add up; every level (value, positions...) is the last day's.
function bucketSeries(series, gran) {
  const key = gran === 'day' ? d => d : gran === 'week' ? weekStart : d => d.slice(0, 7);
  const out = [];
  for (const r of series) {
    const k = key(r.date);
    let b = out[out.length - 1];
    if (!b || b.key !== k) out.push(b = { key: k, deposit: 0, buys: 0 });
    b.deposit += r.deposit; b.buys += r.buys;
    Object.assign(b, { value: r.value, cash: r.cash, net: r.net_deposited, held: r.held, index: r.index, last: r.date });
  }
  return out;
}

// Hovering one of the stacked charts moves the crosshair + tooltip in the others (same x buckets).
function linkCharts(ids) {
  const sync = idx => ids.forEach(id => {
    const ch = S.charts[id]; if (!ch) return;
    const act = idx == null ? [] : [{ datasetIndex: 0, index: idx }];
    ch.setActiveElements(act);
    ch.tooltip.setActiveElements(act, idx == null ? {} : { x: ch.scales.x.getPixelForValue(idx), y: ch.chartArea.top + 10 });
    ch.update('none');
  });
  ids.forEach(id => {
    const ch = S.charts[id]; if (!ch) return;
    ch.canvas.onmousemove = ev => {
      const hit = ch.getElementsAtEventForMode(ev, 'index', { intersect: false }, false)[0];
      sync(hit ? hit.index : null);
    };
    ch.canvas.onmouseleave = () => sync(null);
  });
}

const OV_COLOR = { omx: C.s[1], spx: C.s[3], nq: C.s[4] };

// Index curves come from /api/overlay (Yahoo); fetched only once an index is ticked, again after the CSVs change.
async function ensureOverlay() {
  if (S.overlay && (S.overlay.for === S.data.generated)) return;
  if (S.overlay && S.overlay.pending === S.data.generated) return;
  const gen = S.data.generated;
  S.overlay = { ...(S.overlay || {}), pending: gen };
  let r;
  try { r = await (await fetch('/api/overlay')).json(); } catch (e) { r = { ok: false, error: String(e) }; }
  S.overlay = { ...r, for: gen };
  if (S.tab === 'deposits') renderDeposits();
}

const crossPlugin = { id: 'cross', afterDatasetsDraw(ch) {
  const a = ch.tooltip ? ch.tooltip.getActiveElements() : [];
  if (!a.length) return;
  const x = ch.scales.x.getPixelForValue(a[0].index), { top, bottom } = ch.chartArea, g = ch.ctx;
  g.save(); g.strokeStyle = C.dim; g.lineWidth = 1; g.setLineDash([3, 3]);
  g.beginPath(); g.moveTo(x, top); g.lineTo(x, bottom); g.stroke(); g.restore();
} };

// ───────── deposit tab: insights computed from the daily series (+ S&P 500 overlay when loaded) ─────────
function renderDepInsights(D, OV) {
  const ser = D.series, n = ser.length, ov = S.data.insights.overview, co = S.data.insights.costs;
  const sp = OV && OV.indices.find(i => i.id === 'spx');
  const omx = OV && OV.indices.find(i => i.id === 'omx');
  const lv = ix => ix.perf.map(p => p == null ? null : 1 + p / 100);          // index level, 1 = first deposit day
  const L = { me: ser.map(r => r.index / 100), spx: sp && lv(sp), omx: omx && lv(omx) };
  const sd = a => { const m = a.reduce((s, x) => s + x, 0) / a.length; return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1)); };
  const vol = l => { const r = []; for (let i = 14; i < n; i += 7) r.push(l[i] / l[i - 7] - 1); return r.length > 3 ? sd(r) * Math.sqrt(52) * 100 : null; };
  const mdd = l => { let pk = 0, w = 0; for (const x of l) { pk = Math.max(pk, x); w = Math.min(w, x / pk - 1); } return w * 100; };

  // monthly returns: month-end level / previous month-end level
  const ends = [];
  ser.forEach((r, i) => { const m = r.date.slice(0, 7); if (!ends.length || ends[ends.length - 1].m !== m) ends.push({ m, i }); else ends[ends.length - 1].i = i; });
  const months = ends.map((e, k) => {
    const a = k ? ends[k - 1].i : 0, ret = l => l ? (l[e.i] / l[a] - 1) * 100 : null;
    return { m: e.m, me: ret(L.me), spx: ret(L.spx), omx: ret(L.omx) };
  }).filter(x => x.me != null && isFinite(x.me));

  const cards = [];
  const total = l => l ? (l[n - 1] / l[0] - 1) * 100 : null;
  const myRet = total(L.me);

  // 1. return vs the market
  if (sp) {
    const beat = months.filter(m => m.me > m.spx).length;
    const worst = [...months].sort((a, b) => (a.me - a.spx) - (b.me - b.spx))[0];
    const best = [...months].sort((a, b) => (b.me - b.spx) - (a.me - a.spx))[0];
    cards.push([myRet < total(L.spx) ? 'high' : 'info', 'Your return vs the market', `${sgn2(myRet)}% vs ${sgn2(total(L.spx))}%`,
      `Return of your portfolio with deposits removed vs S&P 500 (${sgn2(total(L.omx))}% for OMXS30), both in SEK, since your first deposit. You beat the S&P 500 in ${beat} of ${months.length} months. Worst month vs the market: ${worst.m} (${sgn2(worst.me - worst.spx)} points); best: ${best.m} (${sgn2(best.me - best.spx)} points).`,
      'Tip: the gap is the cost of active picking and trading. A broad index fund would have matched the market.']);
  }

  // 2. risk: same ride, less return?
  const vme = vol(L.me), vsp = L.spx && vol(L.spx);
  if (vme != null) {
    const dme = mdd(L.me), dsp = L.spx && mdd(L.spx);
    cards.push([sp && vme >= vsp && myRet < total(L.spx) ? 'high' : 'info', 'Risk taken', `${vme.toFixed(0)}% / ${dme.toFixed(0)}%`,
      `Yearly volatility / worst fall from a peak of your portfolio${sp ? `, against ${vsp.toFixed(0)}% / ${dsp.toFixed(0)}% for the S&P 500` : ''} (weekly returns, deposits removed).`
      + (sp ? (vme >= vsp * 0.9 && myRet < total(L.spx) ? ' You took about the market\'s risk, or more, for a lower return.' : vme < vsp ? ' You took less risk than the market, which explains part of the lower return.' : '') : ''),
      'Tip: judge return per unit of risk, not return alone.']);
  }

  // 3. cash drag
  const share = ser.filter(r => r.value > 10000).map(r => r.cash / r.value);
  const avgCash = share.reduce((s, x) => s + x, 0) / Math.max(share.length, 1) * 100;
  let drag = null;
  if (L.spx) { drag = 0; for (let i = 1; i < n; i++) if (L.spx[i] && L.spx[i - 1]) drag += Math.max(ser[i - 1].cash, 0) * (L.spx[i] / L.spx[i - 1] - 1); }
  cards.push([avgCash > 8 ? 'med' : 'info', 'Cash sitting idle', `${avgCash.toFixed(1).replace('.', ',')}%`,
    `Average share of the account held as cash (now ${fmt(ser[n - 1].cash)} kr).` + (drag != null ? ` Had that cash tracked the S&P 500 it would have ${drag >= 0 ? 'earned' : 'lost'} about ${fmt(Math.abs(drag))} kr.` : ''),
    'Tip: deposit when you are ready to buy, not days before.']);

  // 4. did the deposit timing help? portfolio move in the 5 days after a deposit vs any 5 days
  const ev = D.events.filter(e => e.next_5d != null);
  const evAmt = ev.reduce((s, e) => s + e.amount, 0);
  const after = ev.reduce((s, e) => s + e.next_5d * e.amount, 0) / Math.max(evAmt, 1);
  const win = []; for (let i = 0; i + 5 < n; i++) if (ser[i].value > 10000) win.push((L.me[i + 5] / L.me[i] - 1) * 100);
  const any = win.reduce((s, x) => s + x, 0) / Math.max(win.length, 1);
  cards.push([after < any ? 'med' : 'info', 'Deposit timing', `${sgn2(after)}% vs ${sgn2(any)}%`,
    `Average move of your portfolio in the 5 days after a deposit (weighted by amount) vs after an average day. ${Math.abs(after - any) < 0.15 ? 'No timing edge either way: the day you deposit has not mattered.' : after > any ? 'Your deposits came shortly before good stretches.' : 'Your deposits came shortly before weaker stretches.'}`,
    'Tip: regular fixed deposits remove the guesswork and the habit of timing.']);

  // 5. where the gap to the index went
  let gap = null;
  if (sp) {
    const idxValue = sp.dca[n - 1], fees = co.broker_total, divs = ov.dividends - ov.dividend_tax;
    const diff = ov.total_value - idxValue, pick = diff + fees - divs;
    gap = { diff, fees: -fees, divs, pick };
    cards.push([diff < 0 ? 'high' : 'info', `Why you are ${diff < 0 ? 'behind' : 'ahead of'} the S&P 500`, `${sgn(diff)} kr`,
      `If every deposit had bought the S&P 500 you would have ${fmt(idxValue)} kr, you have ${fmt(ov.total_value)} kr. Broker costs explain ${fmt(fees)} kr${diff < 0 ? ` (${(fees / -diff * 100).toFixed(0)}% of the gap)` : ''}, dividends gave back ${fmt(divs)} kr, the rest (${sgn(pick)} kr) is what your stock picking and timing added or lost.`,
      'Tip: costs are the one part you control with certainty.']);
  }

  // 6. position sizing
  const avgPos = ov.holdings_value / Math.max(ov.held_assets, 1);
  cards.push([ov.held_assets > 40 ? 'med' : 'info', 'Money per position', `${fmt(avgPos)} kr`,
    `${ov.held_assets} open positions, ${fmt(ov.holdings_value)} kr invested, so each holding is about ${pct(avgPos / ov.holdings_value * 100, 1)} of the portfolio. With this many holdings no single stock can move the result, and following them all takes time.`,
    'Tip: fewer, larger positions cost fewer fees and are easier to follow.']);

  const sev = { high: 'high', med: 'med', info: 'info' };
  $('dep-insights').innerHTML = cards.map(([k, t, big, p, tip]) => `<div class="finding"><h4><span class="sev ${sev[k]}">${k === 'high' ? 'ACT' : k === 'med' ? 'WATCH' : 'NOTE'}</span>${esc(t)}</h4>
    <div class="num">${esc(big)}</div><p>${p}</p><p class="tip">${esc(tip)}</p></div>`).join('')
    + (sp ? '' : `<div class="finding"><h4><span class="sev info">WAIT</span>Market comparison</h4><p>${S.overlay && S.overlay.error ? esc('Index data unavailable: ' + S.overlay.error) : 'Loading index data…'}</p></div>`);

  // ---- monthly return chart: you vs S&P 500
  const mlabels = months.map(m => m.m);
  const ds = [{ label: 'Your portfolio', data: months.map(m => +m.me.toFixed(2)), backgroundColor: DEP.port, borderRadius: 3, maxBarThickness: 22 }];
  if (sp) ds.push({ label: 'S&P 500 (SEK)', data: months.map(m => +m.spx.toFixed(2)), backgroundColor: OV_COLOR.spx, borderRadius: 3, maxBarThickness: 22 });
  mkChart('d-month', { type: 'bar', data: { labels: mlabels, datasets: ds },
    options: { interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: true, labels: { boxWidth: 10, boxHeight: 10 } },
        tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${sgn2(c.parsed.y)}%` } } },
      scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 9, maxRotation: 0 } }, y: { grid: { color: C.grid }, ticks: { callback: v => v + '%' } } } } });

  // ---- gap chart: what moved you away from the S&P 500
  const gc = $('d-gap-wrap');
  if (gap) {
    gc.hidden = false;
    const rows = [['Broker costs', gap.fees], ['Dividends', gap.divs], ['Picking & timing', gap.pick], ['Total vs S&P 500', gap.diff]];
    mkChart('d-gap', { type: 'bar', data: { labels: rows.map(r => r[0]), datasets: [{ data: rows.map(r => Math.round(r[1])),
        backgroundColor: rows.map((r, i) => i === 3 ? C.s[0] : r[1] >= 0 ? C.green : C.red), borderRadius: 4, maxBarThickness: 40 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${sgn(c.parsed.x)} kr` } } },
        scales: { x: { grid: { color: C.grid }, ticks: { callback: v => fmt(v) } }, y: { grid: { display: false } } } } });
  } else { gc.hidden = true; if (S.charts['d-gap']) { S.charts['d-gap'].destroy(); delete S.charts['d-gap']; } }
}
const sgn2 = v => (v > 0 ? '+' : '') + v.toFixed(2).replace('.', ',');

function renderDeposits() {
  const D = S.data.insights.deposit_behavior;
  if (!D || !D.series.length) { $('dep-verdict').innerHTML = '<p class="hint">No deposits found in the ledger.</p>'; return; }
  const dp = $('dep-pending'); if (dp) dp.hidden = !(S.data.valuation && S.data.valuation.history_pending);
  document.querySelectorAll('#dep-gran .chip').forEach(b => b.classList.toggle('active', b.dataset.g === S.gran));
  document.querySelectorAll('#dep-metric .chip').forEach(b => b.classList.toggle('active', b.dataset.m === S.metric));
  const Y = D.summary, g = Y.groups;
  document.querySelectorAll('#dep-idx .chip').forEach(l => {
    const c = l.querySelector('input'); c.checked = S.idx.has(c.value); l.classList.toggle('on', c.checked);
  });
  ensureOverlay();

  // ---- verdict cards
  const lean = k => g[k].amount_share / Math.max(g[k].baseline_share || 1, .1);
  let pattern, tone = 'warn';
  if (g.down.amount_share >= 15 && lean('down') >= 1.5) pattern = `Dip-buyer: ${pct(g.down.amount_share, 0)} of your money went in after a week when the portfolio fell 2% or more, although such weeks are only ${pct(g.down.baseline_share, 0)} of all days.`;
  else if (g.up.amount_share >= 15 && lean('up') >= 1.5) pattern = `Momentum-chaser: ${pct(g.up.amount_share, 0)} of your money went in after a week when the portfolio rose 2% or more (such weeks are ${pct(g.up.baseline_share, 0)} of all days).`;
  else { pattern = `No clear link to market moves: ${pct(g.flat.amount_share, 0)} of the money went in after a quiet week (a quiet week is ${pct(g.flat.baseline_share, 0)} of all days), ${pct(g.down.amount_share, 0)} after a drop and ${pct(g.up.amount_share, 0)} after a rise.`; tone = 'ok'; }
  $('dep-verdict').innerHTML = [
    [tone, 'Pattern vs. portfolio moves', `${g.down.deposits} / ${g.flat.deposits} / ${g.up.deposits}`, `Deposits after a drop / quiet week / rise (portfolio move in the 5 days before, deposits excluded). ${pattern}`],
    [Y.cash_empty.share >= 30 ? 'warn' : 'ok', 'Top-up when cash ran out', pct(Y.cash_empty.share, 0),
      `${Y.cash_empty.deposits} of ${Y.deposits} deposits arrived with under 1 000 kr cash in the account — you deposit because you want to buy, not on a calendar.`],
    [Y.spent_fast.share >= 70 ? 'warn' : 'ok', 'Invested within 2 days', pct(Y.spent_fast.share, 0),
      `${Y.spent_fast.deposits} deposits were at least 80% spent on buys within 2 days. Money rarely waits; it is deposited in order to be traded.`],
    ['ok', 'Rhythm', `${fmt(Y.avg_deposit)} kr`, `Average deposit; a deposit every ${Y.median_gap_days} days (median). ${Y.deposits} deposits, ${fmt(Y.total)} kr in total.`],
  ].map(([k, t, b, p]) => `<div class="vcard ${k}"><div class="t">${t}</div><div class="big">${b}</div><p>${p}</p></div>`).join('');

  // ---- stacked charts
  const B = bucketSeries(D.series, S.gran);
  const labels = B.map(b => b.key);
  const perf = S.metric === 'perf';
  const unit = { day: 'day', week: 'week (Mon)', month: 'month' }[S.gran];
  $('d-port-title').textContent = perf ? 'Portfolio return, deposits excluded (% since first deposit)' : 'Portfolio value (kr) vs. money put in';
  $('dep-hint').textContent = `${S.idx.size ? (perf ? 'Index lines show the price return of each index since the first deposit, in SEK. ' : 'Index lines show what your deposits would be worth had each one bought the index that day. ') : ''}One column per ${unit}. The portfolio and positions lines show the level at the end of each ${unit}. Hover any chart: the other two follow.`;
  $('dep-legend').innerHTML = `<span class="swatch" style="background:${DEP.dep}"></span>Deposits <span class="swatch" style="background:${DEP.port}"></span>${perf ? 'Return excl. deposits' : 'Portfolio value'} ${perf ? '' : `<span class="swatch" style="background:${DEP.net}"></span>Net deposited so far`} <span class="swatch" style="background:${DEP.held}"></span>Positions held. Value = holdings × Yahoo daily closes + cash (see below).`;
  const xs = { grid: { display: false }, offset: true, ticks: { maxTicksLimit: 8, maxRotation: 0 } };
  const ys = { afterFit: sc => { sc.width = 64; }, grid: { color: C.grid } };
  const noX = { ...xs, ticks: { ...xs.ticks, display: false } };
  const base = { interaction: { mode: 'index', intersect: false }, layout: { padding: { right: 6 } } };
  mkChart('d-dep', { type: 'bar', plugins: [crossPlugin],
    data: { labels, datasets: [{ label: 'Deposited', data: B.map(b => b.deposit), backgroundColor: DEP.dep, borderRadius: 3, maxBarThickness: 28 }] },
    options: { ...base, plugins: { legend: { display: false }, tooltip: { callbacks: {
      title: it => (S.gran === 'week' ? 'Week of ' : '') + it[0].label, label: c => ` Deposited: ${fmt(c.parsed.y)} kr` } } },
      scales: { x: noX, y: { ...ys, beginAtZero: true, ticks: { callback: v => fmt(v), maxTicksLimit: 5 } } } } });
  const portSets = perf
    ? [{ label: 'Return excl. deposits', data: B.map(b => +(b.index - 100).toFixed(2)), borderColor: DEP.port, backgroundColor: DEP.port, borderWidth: 2, pointRadius: 0, tension: .15 }]
    : [{ label: 'Portfolio value', data: B.map(b => b.value), borderColor: DEP.port, backgroundColor: DEP.port, borderWidth: 2, pointRadius: 0, tension: .15 },
       { label: 'Net deposited', data: B.map(b => b.net), borderColor: DEP.net, backgroundColor: DEP.net, borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, stepped: true }];
  // index overlays: price return in % (same unit as the return line) or the "all deposits into the index" value (same unit as the value line)
  const OV = S.overlay && S.overlay.ok ? S.overlay : null;
  const ovNote = [];
  if (S.idx.size && !OV) ovNote.push(S.overlay && S.overlay.error ? `Index data unavailable: ${S.overlay.error}` : 'Loading index data…');
  if (OV && OV.stale) ovNote.push('Index data is the last saved copy (Yahoo unreachable).');
  if (OV) {
    const pos = Object.fromEntries(OV.dates.map((d, i) => [d, i]));
    for (const ix of OV.indices.filter(i => S.idx.has(i.id))) {
      const arr = perf ? ix.perf : ix.dca;
      portSets.push({ label: perf ? `${ix.name} (price return)` : `All deposits into ${ix.name}`, data: B.map(b => arr[pos[b.last]] ?? null),
        borderColor: OV_COLOR[ix.id], backgroundColor: OV_COLOR[ix.id], borderWidth: 1.5, pointRadius: 0, tension: .15, spanGaps: true });
    }
  }
  const ovLegend = portSets.slice(perf ? 1 : 2).map(d => `<span class="swatch" style="background:${d.borderColor}"></span>${d.label}`).join(' ');
  $('dep-legend').innerHTML += ' ' + ovLegend + (ovNote.length ? ` <b>${esc(ovNote.join(' '))}</b>` : '');
  mkChart('d-port', { type: 'line', plugins: [crossPlugin], data: { labels, datasets: portSets },
    options: { ...base, plugins: { legend: { display: false }, tooltip: { callbacks: {
      label: c => perf ? ` ${c.dataset.label}: ${c.parsed.y > 0 ? '+' : ''}${c.parsed.y.toFixed(2).replace('.', ',')}%` : ` ${c.dataset.label}: ${fmt(c.parsed.y)} kr`,
      afterBody: it => perf ? [] : [` Gain vs. deposits: ${sgn(B[it[0].dataIndex].value - B[it[0].dataIndex].net)} kr`] } } },
      scales: { x: noX, y: { ...ys, ticks: { callback: v => perf ? v + '%' : fmt(v), maxTicksLimit: 6 } } } } });
  mkChart('d-held', { type: 'line', plugins: [crossPlugin],
    data: { labels, datasets: [{ label: 'Positions held', data: B.map(b => b.held), borderColor: DEP.held, backgroundColor: DEP.held, borderWidth: 2, pointRadius: 0, stepped: true }] },
    options: { ...base, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` Positions held: ${c.parsed.y}` } } },
      scales: { x: xs, y: { ...ys, beginAtZero: true, ticks: { maxTicksLimit: 4 } } } } });
  linkCharts(['d-dep', 'd-port', 'd-held']);

  renderDepInsights(D, OV);

  $('dep-method').innerHTML = [
    '<b>Portfolio value</b> is the account value of each day: the shares you held that day × Yahoo\'s closing price of that day (in kr with that day\'s exchange rate) + the cash balance. It is the same curve as Net Asset Value on the Portfolio page, and its last day is today\'s live valuation, so every page shows the same number. Funds and holdings Yahoo cannot price use your own trade prices, drawn in a straight line between trades.',
    '<b>Return excl. deposits</b> chains the daily change of the portfolio after removing that day\'s deposits and withdrawals (time-weighted), so adding money never looks like a gain. Deposits count on their booking date.',
        'Index overlay (tick the boxes): Yahoo daily closes for ^OMX, ^GSPC and NQ=F, US indexes converted to SEK with USD/SEK, price indices only (no dividends, no fees). Return view = index price return since the first deposit; value view = every deposit/withdrawal invested in the index on its day.',
    'Not investment advice — this describes your past activity only.',
  ].map(x => `<li>${x}</li>`).join('');
}

// ───────── dividends tab ─────────
const DIV = { net: C.s[2], tax: C.other };
function divBuckets(series, gran) {
  const key = gran === 'day' ? d => d : gran === 'week' ? weekStart : d => d.slice(0, 7);
  const m = new Map();
  for (const r of series) {
    const k = key(r.date), b = m.get(k) || { key: k, net: 0, tax: 0, n: 0 };
    b.net += r.net; b.tax += r.tax; b.n += r.n; m.set(k, b);
  }
  const out = [...m.values()];
  if (gran === 'day' || out.length < 2) return out;
  // show empty weeks / months as gaps instead of skipping them
  const filled = [], by = new Map(out.map(b => [b.key, b])), last = out[out.length - 1].key;
  let cur = out[0].key;
  for (let guard = 0; guard < 3000; guard++) {
    filled.push(by.get(cur) || { key: cur, net: 0, tax: 0, n: 0 });
    if (cur === last) break;
    if (gran === 'week') { const x = new Date(cur + 'T00:00:00'); x.setDate(x.getDate() + 7); cur = iso(x); }
    else { let [y, mo] = cur.split('-').map(Number); mo++; if (mo > 12) { mo = 1; y++; } cur = y + '-' + String(mo).padStart(2, '0'); }
  }
  return filled;
}

function renderDividends() {
  const D = S.data.insights.dividends, o = S.data.insights.overview;
  if (!D) { $('div-kpis').innerHTML = ''; $('div-note').textContent = 'No dividends found in the ledger.'; return; }
  document.querySelectorAll('#div-gran .chip').forEach(b => b.classList.toggle('active', b.dataset.g === S.dgran));
  const Y = D.summary, without = o.all_time_pnl - Y.net;
  const yieldNow = o.holdings_value > 0 ? Y.ttm_net / o.holdings_value * 100 : null;
  $('div-kpis').innerHTML =
    kpi('Dividends received (net)', fmt(Y.net) + ' kr', `${Y.payments} payments from ${Y.payers} companies`, 'pos') +
    kpi('Gross / tax withheld', `${fmt(Y.gross)} / ${fmt(Y.tax)} kr`, `${pct(Y.tax_pct)} withheld at source`) +
    kpi('Last 12 months', fmt(Y.ttm_net) + ' kr', yieldNow == null ? '' : `${pct(yieldNow, 2)} of today's holdings value`) +
    kpi('Average per month', fmt(Y.avg_month) + ' kr', `since ${Y.first} (${Y.months} months)`) +
    kpi('Share of deposits', pct(Y.pct_of_deposits, 2), `of ${fmt(o.net_deposits)} kr deposited`) +
    kpi('Latest payment', Y.last, `${fmt(D.series[D.series.length - 1].net)} kr net that day`);
  $('div-note').innerHTML = `<b>Already counted:</b> dividends are paid into your account, so they are inside the account value and the all-time result (${sgn(o.all_time_pnl)} kr). `
    + `Without them the result would be ${sgn(without)} kr. Nothing was missing from the totals; this tab makes them visible. Amounts are in kr, as booked by Nordnet.`;

  const B = divBuckets(D.series, S.dgran), labels = B.map(b => b.key);
  const base = { interaction: { mode: 'index', intersect: false } };
  const xs = { grid: { display: false }, ticks: { maxTicksLimit: 10, maxRotation: 0, font: { size: 10 } } };
  const ys = { grid: { color: C.grid }, ticks: { callback: v => fmt(v), maxTicksLimit: 5 } };
  mkChart('v-bar', { type: 'bar', plugins: [crossPlugin],
    data: { labels, datasets: [
      { label: 'Net received', data: B.map(b => Math.round(b.net * 100) / 100), backgroundColor: DIV.net, borderRadius: 3, maxBarThickness: 28, stack: 's' },
      { label: 'Tax withheld', data: B.map(b => Math.round(b.tax * 100) / 100), backgroundColor: DIV.tax, borderRadius: 3, maxBarThickness: 28, stack: 's' }] },
    options: { ...base, plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10 } },
        tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${fmt2(c.parsed.y)} kr`,
          footer: it => { const b = B[it[0].dataIndex]; return b.n ? `${b.n} payment${b.n > 1 ? 's' : ''} · gross ${fmt2(b.net + b.tax)} kr` : 'no payments'; } } } },
      scales: { x: { ...xs, stacked: true }, y: { ...ys, stacked: true, beginAtZero: true } } } });
  let acc = 0;
  mkChart('v-cum', { type: 'line', plugins: [crossPlugin],
    data: { labels, datasets: [{ label: 'Total received (net)', data: B.map(b => (acc += b.net, Math.round(acc * 100) / 100)), borderColor: DIV.net, backgroundColor: DIV.net + '22', fill: true, borderWidth: 2, pointRadius: 0, stepped: true }] },
    options: { ...base, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` Total received: ${fmt2(c.parsed.y)} kr` } } },
      scales: { x: xs, y: { ...ys, beginAtZero: true } } } });
  linkCharts(['v-bar', 'v-cum']);

  const mon = Array(12).fill(0), mname = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  D.series.forEach(r => { mon[+r.date.slice(5, 7) - 1] += r.net; });
  mkChart('v-season', { type: 'bar', data: { labels: mname, datasets: [{ data: mon.map(v => Math.round(v * 100) / 100), backgroundColor: DIV.net, borderRadius: 3 }] },
    options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${fmt2(c.parsed.y)} kr` } } },
      scales: { x: { grid: { display: false } }, y: ys } } });

  const top = D.payers.slice(0, 12);
  mkChart('v-payers', { type: 'bar', data: { labels: top.map(p => p.name), datasets: [{ data: top.map(p => p.net), backgroundColor: top.map(p => p.held ? C.s[2] : C.other), borderRadius: 3 }] },
    options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${fmt2(c.parsed.x)} kr net · ${top[c.dataIndex].payments} payments${top[c.dataIndex].held ? '' : ' · sold'}` } } },
      scales: { x: { grid: { color: C.grid }, ticks: { callback: v => fmt(v) } }, y: { grid: { display: false }, ticks: { font: { size: 10 } } } } } });

  const nm = new Set(D.series.map(r => r.date.slice(0, 7))).size, cards = [];
  const card = (sev, t, num, txt) => cards.push(`<div class="finding"><h4><span class="sev ${sev}">${sev === 'info' ? 'NOTE' : 'WATCH'}</span>${t}</h4><div class="num">${num}</div><p>${txt}</p></div>`);
  card('info', 'Dividends in your result', sgn(Y.net) + ' kr',
    `Your all-time result is ${sgn(o.all_time_pnl)} kr including dividends and ${sgn(without)} kr without them. Dividends equal ${pct(Y.pct_of_deposits, 2)} of the money you deposited.`);
  card('info', 'Income rate', yieldNow == null ? '—' : pct(yieldNow, 2),
    `The last 12 months paid ${fmt(Y.ttm_net)} kr net, about ${fmt(Y.ttm_net / 12)} kr a month, against ${fmt(o.holdings_value)} kr in holdings. This is a growth-oriented mix (a broad market index yields roughly 1-2%), so dividends are a bonus rather than income.`);
  card(Y.top3_share > 40 ? 'med' : 'info', 'Spread of payers', pct(Y.top3_share, 0) + ' from top 3',
    `${Y.payers} companies paid something; the three largest (${D.payers.slice(0, 3).map(p => esc(p.name)).join(', ')}) gave ${pct(Y.top3_share, 0)} of the total. Payments arrived in ${nm} of ${Y.months} months, so the flow is ${nm / Y.months > .75 ? 'steady' : 'lumpy'}.`);
  card(Y.tax_pct > 15 ? 'med' : 'info', 'Withholding tax', fmt(Y.tax) + ' kr',
    `${pct(Y.tax_pct)} of the gross dividends was withheld at source, mostly on foreign shares (for example US 15%). Whether part of it can be reclaimed depends on your account type and tax rules; check with Nordnet or Skatteverket.`);
  card('info', 'Sold payers', `${Y.sold_payers} of ${Y.payers}`,
    `${Y.sold_payers} of the dividend-paying companies are no longer held. Their dividends stay in the totals above; with frequent trading the dividend stream keeps restarting from zero.`);
  $('div-insights').innerHTML = cards.join('');

  table('tb-payers', ['Company', 'Status', 'Payments', 'First', 'Last', 'Gross kr', 'Tax kr', 'Net kr'],
    D.payers.map(p => [esc(p.name), p.held ? 'Held' : 'Sold', p.payments, p.first, p.last, fmt2(p.gross), fmt2(p.tax), { v: fmt2(p.net), c: 'pos' }]));

  $('div-method').innerHTML = [
    '<b>Source:</b> ledger rows of type UTDELNING (dividend) and KÄLLSKATT / TYSK SOL SKATT UTD (tax withheld on a dividend), on the Nordnet booking date, in kr.',
    '<b>Net</b> = gross dividend minus withholding tax. This cash is already in the account value, so the all-time result is not changed by this tab.',
    '<b>Not included:</b> accumulating funds and ETFs (they pay no cash dividend), interest, and dividends not yet booked in the ledger (it lags a day).',
    'Not investment advice; this describes past activity only.',
  ].map(x => `<li>${x}</li>`).join('');
}

// ───────── advice tab + Add / trim column (rules in advisor.py, served by /api/advice) ─────────
const ADV_RANK = { TRIM: 0, ADD: 1, BUYBACK: 2, WATCH: 3, REVIEW: 4, CONSOLIDATE: 5, HOLD: 6 };
const ADV_LABEL = { ADD: 'ADD', BUYBACK: 'BUY BACK', WATCH: 'WATCH', TRIM: 'TRIM', CONSOLIDATE: 'CONSOLIDATE', REVIEW: 'REVIEW', HOLD: 'HOLD' };

const advProfile = () => { try { return localStorage.getItem(window.TV ? TV.key('tv_advice_profile') : 'tv_advice_profile') || 'balanced'; } catch (e) { return 'balanced'; } };

async function loadAdvice() {
  if (S.advLoading) return;
  S.advLoading = true;
  try {
    const r = await getJSON('/api/advice?profile=' + advProfile());
    if (r.ok) { S.advice = r; if (S.tab === 'assets') renderTable(derive()); if (S.tab === 'advice') renderAdvice(); }
  } catch (e) { /* column stays empty */ }
  S.advLoading = false;
}

const adviceOf = a => (S.advice && S.advice.assets && S.advice.assets[a.isin]) || null;

function adviceCell(a) {
  const v = adviceOf(a);
  if (!a.held && !v) return '<span class="tag">—</span>';      // closed assets only show a buy-back idea
  if (!v) return '<span class="tag">…</span>';
  const tip = esc(v.reasons.join(' '));
  const amt = v.amount ? `<span class="adv-amt pv">${v.action === 'ADD' || v.action === 'BUYBACK' ? '+' : '−'}${fmt(v.amount)} kr</span>` : '';
  return `<span class="adv ${v.action}" title="${tip}">${ADV_LABEL[v.action] || v.action}</span>${amt}`;
}

function renderAdvice() {
  const A = S.advice;
  if (!A) { $('adv-status').textContent = 'Loading price history from Yahoo for the first time can take up to a minute…'; loadAdvice(); return; }
  const rows = Object.entries(A.assets).map(([isin, v]) => ({ isin, ...v }));
  const Y = A.summary;
  document.querySelectorAll('#adv-profile .chip').forEach(b => b.classList.toggle('active', b.dataset.p === Y.profile));
  $('adv-profile-about').textContent = 'Add / buy back when: ' + Y.profile_about + '. Size, sector and tiny-position rules are the same for all three.';
  $('adv-status').textContent = `Based on ${Y.positions} holdings (${Y.covered} with Yahoo price history), valued ${A.asof.replace('T', ' ')}. Weights are % of holdings.`;
  const sev = { high: 'ACT', med: 'WATCH', info: 'NOTE' };
  $('adv-cards').innerHTML = A.cards.map(c => `<div class="finding"><h4><span class="sev ${c.sev}">${sev[c.sev] || 'NOTE'}</span>${esc(c.title)}</h4><div class="num">${esc(c.num)}</div><p>${esc(c.text)}</p></div>`).join('');

  const th = Object.entries(Y.theme);
  mkChart('a-theme', { type: 'bar', data: { labels: th.map(x => x[0]), datasets: [{ data: th.map(x => x[1]), backgroundColor: th.map(x => x[1] > 40 && x[0] !== 'Unclassified' && x[0] !== 'Funds' ? C.red : C.s[0]), borderRadius: 3 }] },
    options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.parsed.x.toFixed(1)}% of holdings` } } },
      scales: { x: { grid: { color: C.grid }, ticks: { callback: v => v + '%' } }, y: { grid: { display: false }, ticks: { font: { size: 10 } } } } } });
  const ac = Object.entries(Y.counts);
  const accol = { ADD: C.green, BUYBACK: C.s[0], WATCH: C.s[7], TRIM: C.s[3], CONSOLIDATE: C.s[6], REVIEW: C.red, HOLD: C.other };
  mkChart('a-actions', { type: 'bar', data: { labels: ac.map(x => x[0]), datasets: [{ data: ac.map(x => x[1]), backgroundColor: ac.map(x => accol[x[0]]), borderRadius: 3, maxBarThickness: 40 }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { grid: { color: C.grid }, ticks: { precision: 0 } } } } });

  const head = ['Asset', 'Action', 'Weight', 'Amount kr', 'Score', 'Trend', 'RSI 14', '12m momentum', 'From 52w high', 'Why'];
  const line = v => [esc(v.name), `<span class="adv ${v.action}">${ADV_LABEL[v.action]}</span>`, v.closed ? 'not held' : pct(v.weight, 1), { v: `<span class="pv">${v.amount ? fmt(v.amount) : '—'}</span>` },
    v.score || '—', (v.metrics && v.metrics.trend) || '—', v.metrics && v.metrics.rsi != null ? Math.round(v.metrics.rsi) : '—', v.metrics && v.metrics.mom12_1 != null ? pct(v.metrics.mom12_1 * 100, 0) : '—',
    v.metrics && v.metrics.dd52 != null ? pct(v.metrics.dd52 * 100, 0) : '—', { v: `<span class="adv-why">${esc(v.reasons.join(' '))}</span>` }];
  const by = (acts, f) => rows.filter(r => acts.includes(r.action)).sort(f || ((x, y) => y.score - x.score)).map(line);
  table('tb-add', head, by(['ADD', 'BUYBACK', 'WATCH'], (x, y) => (ADV_RANK[x.action] - ADV_RANK[y.action]) || y.score - x.score), 'No add, buy-back or watch ideas right now: nothing is close to oversold (RSI) in an uptrend, or the sector is already over its cap.');
  table('tb-trim', head, by(['TRIM']), 'No position breaks the size or theme limits.');
  table('tb-cons', head, by(['CONSOLIDATE', 'REVIEW'], (x, y) => (ADV_RANK[x.action] - ADV_RANK[y.action]) || y.amount - x.amount), 'Nothing to consolidate.');
  $('adv-method').innerHTML = [
    '<b>TRIM</b>: (1) a position above 4% of holdings is cut back to 4%; (2) in a theme above 40% the holdings of 2.5% or more give back a fifth; (3) <b>take profit</b>: RSI(14) above the profile\'s sell level (Balanced 75) on a holding that is in profit, about a third of it. Strong stocks often stay overbought for weeks, so (3) is discipline, not a prediction.',
    '<b>ADD</b>: weight under 1.5%, the theme not over its cap, the price above its 200-day average (uptrend, no falling knives), 5-25% below the 52-week high, and RSI(14) below the profile\'s buy level (Balanced 35, Conservative 30, Aggressive 40). Fill to about 2% in orders of at least 1 500 kr. Score = momentum rank, pullback depth and low volatility.',
    '<b>WATCH</b>: close to an ADD or BUY BACK signal: same trend and pullback test, but RSI(14) is between the buy level and 10 points above it (Balanced 35-45). No order yet; it tells you which names to look at next and which RSI level to wait for.',
    '<b>BUY BACK</b>: same trend and pullback test applied to positions you have closed (so a good exit is not a lost opportunity), at least 7 days after your last sell, in one order of about 1.5% of the portfolio. The sell price and today\'s price are shown when both are in the same currency.',
    '<b>CONSOLIDATE</b>: under 1 500 kr. A round trip costs about 16 kr courtage and the position cannot change the result; sell it or top it up.',
    '<b>REVIEW</b>: below the 200-day, negative momentum and more than 15% under your cost. Not a sell order: re-check why you own it.',
    '<b>Data</b>: Yahoo adjusted daily closes (2 years, cached 6 h in history_cache.json), live prices for weights, Yahoo sectors, your ledger for cost and unrealised result. Funds without Yahoo history are kept as is.',
    'Not investment advice. Rules limit risk and cost; they do not predict prices. Check tax effects (selling a loss or a gain) and liquidity before acting.',
  ].map(x => `<li>${x}</li>`).join('');
}

// ───────── benchmark score + good practice ─────────
const tone = sc => sc == null ? '' : sc >= 70 ? 'good' : sc >= 40 ? 'mid' : 'bad';

function renderScore() {
  const sc = S.data.insights.scorecard;
  $('score-head').innerHTML = `<div class="score-head"><div class="grade ${tone(sc.overall)}"><b>${sc.grade || '—'}</b><span>${sc.overall ?? '—'} / 100</span></div>
    <p>Overall habit score, weighted by how much each item matters. Averages used: ${fmt(sc.avg_deposited)} kr deposited over ${sc.years} years.</p></div>`;
  const valFmt = i => i.value == null ? '—' : (i.key === 'profit_factor' || i.key === 'turnover_ratio' ? i.value.toFixed(2) + '×' : pct(i.value, 2));
  table('tb-score', ['Measure', 'You', 'Target', 'Poor at', 'Score'],
    sc.items.map(i => [`<span title="${esc(i.why)}">${esc(i.label)}</span><br><span class="tag">${esc(i.unit)}</span>`, valFmt(i),
      `${i.lower_is_better ? '≤' : '≥'} ${i.good}`, `${i.lower_is_better ? '≥' : '≤'} ${i.poor}`,
      { v: `<span class="bar"><i class="${tone(i.score)}" style="width:${i.score ?? 0}%"></i></span>${i.score ?? '—'}` }]));

  // ---- practice list: biggest shortfall x weight first
  const by = Object.fromEntries(sc.items.map(i => [i.key, i]));
  const I = S.data.insights;
  const rtCost = 2 * sc.avg_courtage;
  const num = (k, d = 1) => by[k].value == null ? '—' : by[k].value.toFixed(d);
  const tips = {
    fee_drag: ['Cut the total number of trades', `Costs run at ${num('fee_drag')}% of your deposited money per year. Decide a trade budget (for example 3–5 trades a week) and a monthly fee budget, and stop trading when it is used.`],
    fee_turnover: ['Trade in larger, fewer orders', `Fees took ${num('fee_turnover', 2)}% of everything traded. Save deposits and buy once a week or fortnight instead of whenever cash arrives.`],
    fees_vs_gain: ['Sell only for a gain that clearly beats the round-trip cost', `A buy plus a sell costs about ${fmt(rtCost)} kr. On a 2 000 kr position that is ${pct(rtCost / 2000 * 100, 1)}; require a target well above it (many use 3× the round-trip cost) before entering short-term trades.`],
    small_orders: [`Set a minimum order size of about ${fmt(sc.min_order_for_0_3pct)} kr`, `With about ${fmt2(sc.avg_courtage)} kr courtage per order, ${fmt(sc.min_order_for_0_3pct)} kr keeps commission near 0.3%. ${num('small_orders', 0)}% of your paid trades were under 1 000 kr.`],
    split_rate: ['One order per asset per day', `${I.split_orders.extra_orders} extra same-day orders cost about ${fmt(I.split_orders.avoidable_fees)} kr. Work out the total quantity first and place a single (limit) order.`],
    short_holds: ['Add a cooling-off rule', `${num('short_holds', 0)}% of your sells were within 7 days; the 0–1 day sells lost ${fmt(Math.abs((I.hold_buckets[0] || {}).net || 0))} kr net. Write down a reason and a price level before each buy and avoid selling within a week unless that level is hit.`],
    turnover_ratio: ['Move the core into low-turnover holdings', `You turn over about ${num('turnover_ratio')}× your money each year. Your ledger shows fund purchases (such as the Nordnet index funds) carried 0 kr courtage; a broad index core plus a small active part limits both fees and effort.`],
    profit_factor: ['Review how you cut losers', `Winners and losers roughly cancel (profit factor ${num('profit_factor', 2)}). Your average win is ${fmt(I.sell_quality.avg_win)} kr and average loss ${fmt(Math.abs(I.sell_quality.avg_loss))} kr; define the loss level in advance.`],
    top_weight: ['Watch concentration', `Your largest position is ${num('top_weight', 0)}% of holdings.`],
    fragmentation: ['Consolidate tiny positions', `${num('fragmentation', 0)}% of your holdings are under 2 000 kr. Each was built with several fee-heavy orders; fewer, larger positions are cheaper to manage.`],
  };
  const todo = sc.items.filter(i => i.score != null && i.score < 70 && tips[i.key])
    .sort((a, b) => (100 - b.score) * b.weight - (100 - a.score) * a.weight);
  const good = sc.items.filter(i => i.score != null && i.score >= 70);
  const cards = todo.map((i, n) => `<div class="finding"><h4><span class="sev ${i.score < 40 ? 'high' : 'med'}">#${n + 1}</span>${esc(tips[i.key][0])}</h4>
      <div class="num">${esc(i.label)}: score ${i.score}</div><p>${tips[i.key][1]}</p></div>`);
  if (good.length) cards.push(`<div class="finding"><h4><span class="sev info">KEEP</span>Already good</h4><p>${good.map(i => esc(i.label) + ' (' + i.score + ')').join(' · ')}</p></div>`);
  $('practice').innerHTML = cards.join('');
  loadBenchmark();
}

async function loadBenchmark() {
  const note = $('bench-note');
  try {
    const b = await getJSON('/api/benchmark');
    if (!b.indices || !b.indices.length) throw new Error(b.error || 'unavailable');
    const o = S.data.insights.overview;
    const labels = ['Net deposited', ...b.indices.map(i => 'If in ' + i.name), 'Your account'];
    const vals = [o.net_deposits, ...b.indices.map(i => i.value), o.total_value];
    mkChart('h-bench', { type: 'bar', data: { labels, datasets: [{ data: vals,
        backgroundColor: [C.other, ...b.indices.map(i => OV_COLOR[i.id] || C.s[2]), C.s[0]], borderRadius: 4, maxBarThickness: 46 }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${fmt(c.parsed.y)} kr` } } },
        scales: { x: { grid: { display: false }, ticks: { font: { size: 10 } } }, y: { grid: { color: C.grid }, ticks: { callback: v => fmt(v) } } } } });
    note.innerHTML = b.indices.map(i => `${esc(i.name)}: ${sgn(i.pnl)} kr (${pct(i.pct)}) — your account is <b class="${cls(i.account_minus_index)}">${sgn(i.account_minus_index)} kr</b> ${i.account_minus_index < 0 ? 'behind' : 'ahead'}.`).join('<br>') +
      `<br><span class="tag">Each deposit/withdrawal invested at the next daily close; price indices (no dividends, no fees); data to ${esc(b.as_of || '?')}${b.stale ? ' — offline, using saved data' : ''}.</span>`;
  } catch (e) {
    note.textContent = 'Index comparison unavailable (' + e.message + ').';
  }
}

// ───────── events ─────────
function bind() {
  $('view-chips').addEventListener('click', e => {
    const b = e.target.closest('.chip'); if (!b) return;
    S.view = b.dataset.v; S.sort = { key: 'metric', dir: -1 }; renderAssets();
  });
  [['f-type', 'type'], ['f-ccy', 'ccy'], ['f-dom', 'dom']].forEach(([id, k]) =>
    $(id).addEventListener('change', e => { S[k] = e.target.value; renderAssets(); }));
  let t; $('f-q').addEventListener('input', e => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value; renderAssets(); }, 120); });
  $('asset-table').addEventListener('click', e => {
    const th = e.target.closest('th.sortable');
    if (th) {
      const k = th.dataset.k;
      S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : (k === 'name' || k === 'type' || k === 'ccy' ? 1 : -1) };
      return renderAssets();
    }
    const tr = e.target.closest('tr.row');
    if (tr) { const i = tr.dataset.i; S.open.has(i) ? S.open.delete(i) : S.open.add(i); renderAssets(); }
  });
  $('csv-btn').addEventListener('click', exportCsv);
  $('reload-btn').addEventListener('click', () => load(true));
  document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));
  window.addEventListener('hashchange', () => setTab(tabFromHash()));
  $('dep-gran').addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { S.gran = b.dataset.g; renderDeposits(); } });
  $('dep-idx').addEventListener('change', e => {
    e.target.checked ? S.idx.add(e.target.value) : S.idx.delete(e.target.value);
    renderDeposits();
  });
  $('adv-profile').addEventListener('click', e => {
    const b = e.target.closest('.chip'); if (!b) return;
    try { localStorage.setItem(window.TV ? TV.key('tv_advice_profile') : 'tv_advice_profile', b.dataset.p); } catch (err) { /* private mode */ }
    S.advice = null; $('adv-status').textContent = 'Recalculating…'; loadAdvice();
  });
  $('div-gran').addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { S.dgran = b.dataset.g; renderDividends(); } });
  $('dep-metric').addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { S.metric = b.dataset.m; renderDeposits(); } });
}

function setTab(tab) {
  S.tab = tab;
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $('tab-assets').hidden = tab !== 'assets';
  $('tab-habits').hidden = tab !== 'habits';
  $('tab-deposits').hidden = tab !== 'deposits';
  $('tab-dividends').hidden = tab !== 'dividends';
  $('tab-advice').hidden = tab !== 'advice';
  history.replaceState(null, '', '#' + tab);
  if (S.data) renderTab();
}
function tabFromHash() { const h = location.hash.slice(1); return ['habits', 'deposits', 'dividends', 'advice'].includes(h) ? h : 'assets'; }
function renderTab() {
  S.tabValue = S.data.insights.overview.total_value;
  ({ assets: renderAssets, habits: renderHabits, deposits: renderDeposits, dividends: renderDividends, advice: renderAdvice })[S.tab]();
}

// nothing is fetched or read from per-user storage before auth.js knows who is signed in
(window.TV ? TV.ready : Promise.resolve()).then(() => {
  bind();
  setTab(tabFromHash());
  load(true);
  setInterval(() => load(false), POLL_MS);
  setInterval(refreshSnapshot, SNAP_MS);
});
