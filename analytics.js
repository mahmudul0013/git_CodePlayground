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
  sort: { key: 'metric', dir: -1 }, open: new Set(), charts: {},
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
async function load(force) {
  try {
    const sig = await getJSON('/api/trades/status');
    const sigStr = JSON.stringify(sig);
    if (!force && sigStr === S.sig && S.data) { setSync(true); return; }
    const data = await getJSON('/api/trades');
    S.sig = sigStr;
    S.data = data;
    index();
    setSync(true);
    renderAll();
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
  if (S.tab === 'assets') renderAssets(); else renderHabits();
}

function kpi(l, v, s, c) {
  return `<div class="kpi"><div class="l">${l}</div><div class="v ${c || ''}">${v}</div><div class="s">${s || ''}</div></div>`;
}

function renderKpis() {
  const o = S.data.insights.overview, c = S.data.insights.costs;
  $('kpis').innerHTML =
    kpi('Account value', fmt(o.total_value) + ' kr', `holdings ${fmt(o.holdings_value)} + cash ${fmt(o.cash_balance)}`) +
    kpi('Deposited (net)', fmt(o.net_deposits) + ' kr', `${o.deposit_count} deposits`) +
    kpi('All-time result', sgn(o.all_time_pnl) + ' kr', o.all_time_pnl_pct == null ? '' : `${pct(o.all_time_pnl_pct, 2)} on deposits`, cls(o.all_time_pnl)) +
    kpi('Broker costs paid', fmt(c.broker_total) + ' kr', `${pct(c.pct_of_net_deposits)} of deposits · ${pct(c.pct_of_turnover, 2)} of turnover`, 'neg') +
    kpi('Realised (after fees)', sgn(o.realized) + ' kr', `${o.sells} sells`, cls(o.realized)) +
    kpi('Unrealised', sgn(o.unrealized) + ' kr', `${o.held_assets} open positions`, cls(o.unrealized)) +
    kpi('Data range', `${o.first_date.slice(2)} → ${o.last_date.slice(2)}`, `${o.trades} trades · ${o.distinct_assets} assets`);
}

// ───────── render: assets tab ─────────
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

  // kpis for the filtered set
  const sum = f => list.reduce((s, r) => s + (f(r) || 0), 0);
  const mt = sum(r => r.metric);
  $('asset-kpis').innerHTML =
    kpi('Assets', list.length, `${list.filter(r => r.a.held).length} held now`) +
    kpi(metricName(v), fmt(mt), v.id === 'current' ? 'sum of current holdings' : '') +
    kpi('Realised (all-time)', sgn(sum(r => r.a.realized)), 'closed trades, after fees', cls(sum(r => r.a.realized))) +
    kpi('Unrealised', sgn(sum(r => r.a.unrealized)), 'open positions', cls(sum(r => r.a.unrealized))) +
    kpi('Fees paid (all-time)', fmt(sum(r => r.a.fees)), `${sum(r => r.a.trades.length)} trades`);

  // charts
  const group = key => {
    const m = new Map();
    for (const r of list) if (r.metric > 0) m.set(r.a[key], (m.get(r.a[key]) || 0) + r.metric);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  };
  const mn = metricName(v);
  $('t-type').textContent = 'By type · ' + mn;
  $('t-ccy').textContent = 'By currency · ' + mn;
  $('t-dom').textContent = 'By country (ISIN) · ' + mn;
  $('t-top').textContent = 'Top assets · ' + mn;
  doughnut('c-type', group('type'), k => k);
  doughnut('c-ccy', group('ccy'), k => k);
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
    col('name', 'Asset'), col('type', 'Type'), col('ccy', 'Ccy'), col('status', 'Status'),
    col('qty', 'Qty'), col('value', 'Value kr'),
    col('bought', 'Bought kr' + win), col('sold', 'Sold kr' + win), col('trades', 'Buys / sells' + win),
    col('last_buy', 'Last buy'), col('last_sell', 'Last sell'),
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
      <td class="tag">${esc(a.type)}</td><td class="tag">${esc(a.ccy)}</td>
      <td><span class="badge ${a.held ? 'held' : 'closed'}">${a.held ? 'Held' : 'Closed'}</span></td>
      <td>${a.held ? fmt2(a.qty).replace(/,00$/, '') : '—'}</td><td>${a.held ? fmt(a.value) : '—'}</td>
      <td>${fmt(w.bought)}</td><td>${fmt(w.sold)}</td><td>${w.nb} / ${w.ns}</td>
      <td class="tag">${a.last_buy || '—'}</td><td class="tag">${a.last_sell || '—'}</td>
      <td>${fmt(a.fees)}</td><td class="${cls(a.realized)}">${sgn(a.realized)}</td>
      <td class="${cls(a.unrealized)}">${a.held ? sgn(a.unrealized) : '—'}</td><td class="${cls(a.total_pnl)}">${sgn(a.total_pnl)}</td></tr>`;
    if (open) h += `<tr class="detail"><td colspan="${cols.length}">${detail(a)}</td></tr>`;
    return h;
  }).join('');
  const sum = f => list.reduce((s, r) => s + (f(r) || 0), 0);
  const foot = `<tr><td>Total (${list.length})</td><td></td><td></td><td></td><td></td><td>${fmt(sum(r => r.a.value))}</td>
    <td>${fmt(sum(r => r.w.bought))}</td><td>${fmt(sum(r => r.w.sold))}</td><td>${sum(r => r.w.nb)} / ${sum(r => r.w.ns)}</td><td></td><td></td>
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
        backgroundColor: [C.other, ...b.indices.map((_, k) => C.s[k === 0 ? 0 : 2]), C.s[1]], borderRadius: 4, maxBarThickness: 46 }] },
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
  window.addEventListener('hashchange', () => setTab(location.hash === '#habits' ? 'habits' : 'assets'));
}

function setTab(tab) {
  S.tab = tab;
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $('tab-assets').hidden = tab !== 'assets';
  $('tab-habits').hidden = tab !== 'habits';
  history.replaceState(null, '', tab === 'habits' ? '#habits' : '#assets');
  if (S.data) (tab === 'assets' ? renderAssets : renderHabits)();
}

bind();
setTab(location.hash === '#habits' ? 'habits' : 'assets');
load(true);
setInterval(() => load(false), POLL_MS);
