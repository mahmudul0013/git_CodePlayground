/* ============================================================
   PORTFOLIO HEAT MAP - heatmap.js (Portfolio page, "Heat map" tab)
   Tiles = current holdings from /api/assets (Nordnet holdings export + ledger),
   sector / fund category from /api/sectors (Yahoo Finance via sectors.py).
   ============================================================ */
'use strict';
const Heat = (() => {
const S = { live: null, sig: null, timers: [], data: null, heat: { group: 'cat', color: 'day' }, sectors: null, charts: {}, tab: '' };
const C = { s: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'], other: '#5d6170', grid: '#2A2E39' };
const COUNTRY = { US: 'United States', SE: 'Sweden', NO: 'Norway', DE: 'Germany', GB: 'United Kingdom',
  IE: 'Ireland', LU: 'Luxembourg', NL: 'Netherlands', FI: 'Finland', DK: 'Denmark', CA: 'Canada',
  FR: 'France', KY: 'Cayman Is.', JE: 'Jersey', CH: 'Switzerland', IT: 'Italy', ES: 'Spain', BM: 'Bermuda',
  IL: 'Israel', CN: 'China', TW: 'Taiwan', JP: 'Japan', BE: 'Belgium', AT: 'Austria', '??': 'Unknown' };
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf0 = new Intl.NumberFormat('sv-SE', { maximumFractionDigits: 0 });
const fmt = n => (n == null || isNaN(n)) ? '—' : nf0.format(Math.round(n)).replace('−', '-');
const sgn = n => (n == null || isNaN(n)) ? '—' : (n > 0 ? '+' : '') + fmt(n);
const pct = (n, d = 1) => (n == null || isNaN(n)) ? '—' : n.toFixed(d).replace('.', ',') + '%';
const cls = n => n > 0 ? 'pos' : n < 0 ? 'neg' : '';

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

function doughnut(id, entries, nameFn) {
  const MAX = 7;
  const items = entries.slice(0, MAX);
  const rest = entries.slice(MAX).reduce((s, e) => s + e[1], 0);
  const labels = items.map(e => nameFn(e[0])), data = items.map(e => e[1]);
  const colors = items.map((_, i) => C.s[i]);
  if (rest > 0) { labels.push('Other'); data.push(rest); colors.push(C.other); }
  const total = data.reduce((a, b) => a + b, 0);
  mkChart(id, {
    type: 'doughnut',
    data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: '#1E2130', borderWidth: 2 }] },
    options: { cutout: '58%', plugins: {
      legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, font: { size: 11 }, color: '#D1D4DC',
        generateLabels: ch => ch.data.labels.map((l, i) => ({ text: `${l} ${total ? (data[i] / total * 100).toFixed(0) : 0}%`,
          fillStyle: colors[i], strokeStyle: colors[i], index: i, fontColor: '#D1D4DC' })) } },
      tooltip: { callbacks: { label: c => ` ${c.label}: ${fmt(c.parsed)} kr (${total ? (c.parsed / total * 100).toFixed(1) : 0}%)` } } } },
  });
}

function table(id, head, rows) {
  $(id).innerHTML = `<thead><tr>${head.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${
    rows.map(r => `<tr>${r.map(c => `<td${c && c.c ? ` class="${c.c}"` : ''}>${c && c.v !== undefined ? c.v : c}</td>`).join('')}</tr>`).join('')}</tbody>`;
}

// ───────── render: portfolio heat map tab ─────────
// Tile size = market value (SEK), tile colour = day change or unrealised %, groups = Yahoo sector / type / country.
const HEAT_SCALE = { day: 3, unreal: 25 };               // % at which the colour is fully saturated
const NEUTRAL = [58, 63, 80], GOOD = [27, 138, 127], BAD = [192, 64, 62];

async function ensureSectors() {
  const gen = S.data.generated;
  if (S.sectors && (S.sectors.for === gen || S.sectors.pending_for === gen)) return;
  S.sectors = { ...(S.sectors || {}), pending_for: gen };
  let r;
  try { r = await (await fetch('/api/sectors')).json(); } catch (e) { r = { ok: false, error: String(e), sectors: {} }; }
  S.sectors = { ...r, for: r.pending > 0 ? null : gen, pending_for: null };
  if (S.tab === 'heatmap') renderHeat();
  if (r.pending > 0) setTimeout(ensureSectors, 4000);   // Yahoo lookups still running: ask again
}

function heatCategory(a) {
  const s = S.sectors && S.sectors.sectors && S.sectors.sectors[a.isin];
  if (s) {
    if (s.sector) return s.sector;
    if (s.category) return s.category;
    if (s.quote_type === 'ETF') return 'ETFs';
    if (s.quote_type === 'MUTUALFUND') return 'Funds';
  }
  return a.type === 'ETF/ETC' ? 'ETFs' : a.type === 'Fund' ? 'Funds' : 'Unclassified';
}

function heatColor(v, kind) {
  if (v == null || isNaN(v)) return `rgb(${NEUTRAL})`;
  const t = Math.min(Math.abs(v) / HEAT_SCALE[kind], 1), to = v >= 0 ? GOOD : BAD;
  return `rgb(${NEUTRAL.map((n, i) => Math.round(n + (to[i] - n) * t))})`;
}

// squarified treemap: items [{v}] sorted by v desc -> [{item, x, y, w, h}]
function squarify(items, x, y, w, h) {
  const out = [], total = items.reduce((s, i) => s + i.v, 0);
  if (!total || w <= 0 || h <= 0) return out;
  let rest = items.map(i => ({ i, a: i.v / total * w * h }));
  const worst = (row, side) => {
    const s = row.reduce((t, r) => t + r.a, 0), mx = Math.max(...row.map(r => r.a)), mn = Math.min(...row.map(r => r.a));
    return Math.max(side * side * mx / (s * s), s * s / (side * side * mn));
  };
  while (rest.length) {
    const side = Math.min(w, h);
    const row = [rest[0]]; let k = 1;
    while (k < rest.length && worst([...row, rest[k]], side) <= worst(row, side)) row.push(rest[k++]);
    const s = row.reduce((t, r) => t + r.a, 0);
    if (w >= h) { const cw = s / h; let cy = y; for (const r of row) { const rh = r.a / cw; out.push({ item: r.i, x, y: cy, w: cw, h: rh }); cy += rh; } x += cw; w -= cw; }
    else { const rh = s / w; let cx = x; for (const r of row) { const rw = r.a / rh; out.push({ item: r.i, x: cx, y, w: rw, h: rh }); cx += rw; } y += rh; h -= rh; }
    rest = rest.slice(row.length);
  }
  return out;
}

function heatGroups() {
  const keyFn = { cat: heatCategory, type: a => a.type, country: a => COUNTRY[a.domicile] || a.domicile }[S.heat.group];
  const mk = S.heat.color === 'day' ? 'day_pct' : 'unrealized_pct';
  const held = liveAssets().filter(a => a.value > 0);   // also today's buys the ledger does not show yet
  const total = held.reduce((s, a) => s + a.value, 0);
  const m = new Map();
  for (const a of held) {
    const k = keyFn(a) || 'Unclassified';
    if (!m.has(k)) m.set(k, { name: k, v: 0, items: [], pnl: 0, day: 0 });
    const g = m.get(k);
    g.v += a.value; g.items.push({ a, v: a.value, m: a[mk] });
    g.pnl += a.unrealized || 0;
    g.day += a.day_pct != null ? a.value * a.day_pct / 100 / (1 + a.day_pct / 100) : 0;   // today's change in kr
  }
  const groups = [...m.values()].sort((x, y) => y.v - x.v);
  for (const g of groups) {
    g.items.sort((x, y) => y.v - x.v);
    g.weight = g.v / total * 100;
    g.metric = g.items.reduce((s, i) => s + (i.m ?? 0) * i.v, 0) / g.v;       // value-weighted average of the colour metric
  }
  return { groups, total, held: held.length };
}

function renderHeat() {
  if (!S.data) return;
  ensureSectors();
  document.querySelectorAll('#heat-group .chip').forEach(b => b.classList.toggle('active', b.dataset.g === S.heat.group));
  document.querySelectorAll('#heat-color .chip').forEach(b => b.classList.toggle('active', b.dataset.c === S.heat.color));
  const { groups, total, held } = heatGroups();
  const kind = S.heat.color, unit = kind === 'day' ? 'today' : 'vs. your cost (GAV)';
  const loading = S.heat.group === 'cat' && (!S.sectors || S.sectors.pending > 0 || S.sectors.pending_for);
  $('heat-hint').textContent = `${held} holdings, ${fmt(total)} kr. Tile size = market value, colour = change ${unit}`
    + (S.heat.group === 'cat' ? '. Category = sector from Yahoo Finance for stocks; ETFs and funds have no sector there and are grouped as ETFs / Funds.' : '.')
    + (loading ? ' Looking up categories…' : '');
  $('heat-scale').innerHTML = `<span>−${HEAT_SCALE[kind]}%</span><i style="background:linear-gradient(90deg,rgb(${BAD}),rgb(${NEUTRAL}),rgb(${GOOD}))"></i><span>+${HEAT_SCALE[kind]}%</span>`;

  const box = $('heat-map'), W = box.clientWidth, H = box.clientHeight, HEAD = 20;
  const tip = $('heat-tip');
  const el = (c, st, html) => `<div class="${c}" style="left:${st.x}px;top:${st.y}px;width:${st.w}px;height:${st.h}px;${st.bg ? 'background:' + st.bg : ''}">${html || ''}</div>`;
  let html = '';
  const data = [];
  for (const gr of squarify(groups, 0, 0, W, H)) {
    const g = gr.item, gx = gr.x + 1, gy = gr.y + 1, gw = gr.w - 2, gh = gr.h - 2;
    const head = gh > 44 && gw > 60;
    html += `<div class="hm-group" style="left:${gx}px;top:${gy}px;width:${gw}px;height:${gh}px"></div>`;
    if (head) html += `<div class="hm-title" style="left:${gx + 4}px;top:${gy + 2}px;width:${gw - 8}px">${esc(g.name)} · ${g.weight.toFixed(1).replace('.', ',')}%</div>`;
    const top = head ? HEAD : 0;
    for (const t of squarify(g.items, gx + 1, gy + top + 1, gw - 2, gh - top - 2)) {
      const a = t.item.a, id = data.push({ a, g }) - 1;
      const big = t.w > 64 && t.h > 36, mid = t.w > 34 && t.h > 20;
      const m = t.item.m, label = m == null ? '' : (m > 0 ? '+' : '') + m.toFixed(1).replace('.', ',') + '%';
      html += `<div class="hm-tile" data-i="${id}" style="left:${t.x}px;top:${t.y}px;width:${t.w - 1}px;height:${t.h - 1}px;background:${heatColor(m, kind)}">`
        + (mid ? `<b style="font-size:${big ? 12 : 10}px">${esc(a.name)}</b>` : '') + (big ? `<span>${label}</span>` : '') + '</div>';
    }
  }
  box.innerHTML = html;
  const move = e => {
    const t = e.target.closest('.hm-tile');
    if (!t) { tip.hidden = true; return; }
    const { a, g } = data[+t.dataset.i], s = S.sectors && S.sectors.sectors && S.sectors.sectors[a.isin] || {};
    tip.innerHTML = `<b>${esc(a.name)}</b><br>${fmt(a.value)} kr · ${(a.value / total * 100).toFixed(1).replace('.', ',')}% of portfolio<br>`
      + `Today: <span class="${cls(a.day_pct)}">${a.day_pct == null ? '—' : pct(a.day_pct, 2)}</span> · Unrealised: <span class="${cls(a.unrealized)}">${sgn(a.unrealized)} kr (${a.unrealized_pct == null ? '—' : pct(a.unrealized_pct, 1)})</span><br>`
      + `${esc(g.name)}${s.industry ? ' · ' + esc(s.industry) : ''} · ${esc(a.type)} · ${esc(COUNTRY[a.domicile] || a.domicile)}`;
    tip.hidden = false;
    const r = box.getBoundingClientRect();
    tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 270) + 'px';
    tip.style.top = Math.min(e.clientY - r.top + 14, r.height - 90) + 'px';
  };
  box.onmousemove = move; box.onmouseleave = () => { tip.hidden = true; };

  // ---- distribution: doughnut + table
  const gname = { cat: 'category', type: 'type', country: 'country' }[S.heat.group];
  $('heat-pie-title').textContent = `Distribution by ${gname} (share of market value)`;
  doughnut('h-pie', groups.map(g => [g.name, g.v]), k => k);
  const dayKr = groups.reduce((s, g) => s + g.day, 0);
  table('tb-heat', [gname[0].toUpperCase() + gname.slice(1), 'Value kr', 'Weight', 'Holdings', 'Unrealised kr', S.heat.color === 'day' ? 'Today' : 'vs. cost'],
    groups.map(g => [esc(g.name), fmt(g.v), g.weight.toFixed(1).replace('.', ',') + '%', g.items.length,
      { v: sgn(g.pnl), c: cls(g.pnl) }, { v: (g.metric > 0 ? '+' : '') + g.metric.toFixed(2).replace('.', ',') + '%', c: cls(g.metric) }]));

  // ---- concentration read-out
  const plural = gname === 'category' ? 'categories' : gname + 's';
  const top3 = groups.slice(0, 3), topAsset = [...groups.flatMap(g => g.items)].sort((x, y) => y.v - x.v).slice(0, 5);
  const hhi = groups.reduce((s, g) => s + (g.weight / 100) ** 2, 0);
  $('heat-notes').innerHTML = [
    `Biggest ${plural}: ${top3.map(g => `<b>${esc(g.name)}</b> ${g.weight.toFixed(0)}%`).join(', ')} — together ${top3.reduce((s, g) => s + g.weight, 0).toFixed(0)}% of the portfolio.`,
    `Biggest holdings: ${topAsset.map(i => `${esc(i.a.name)} ${(i.v / total * 100).toFixed(1).replace('.', ',')}%`).join(', ')}.`,
    `Spread across ${groups.length} ${plural} (concentration index ${hhi.toFixed(2).replace('.', ',')}; 1 = everything in one, ${(1 / groups.length).toFixed(2).replace('.', ',')} = perfectly even).`,
    S.heat.color === 'day' ? `Today the portfolio moved about ${sgn(dayKr)} kr (from the holdings export's day change).` : `Open positions are ${sgn(groups.reduce((s, g) => s + g.pnl, 0))} kr vs. your average cost.`,
  ].map(x => `<li>${x}</li>`).join('');
}


// ───────── live prices (Yahoo) on top of the CSV holdings ─────────
// Holdings export gives quantity, cost and the price at export time. A live Yahoo quote replaces the day change, and
// (same currency only) rescales the market value and unrealised P&L by live price / export price.
function liveAssets() {
  const q = S.live && S.live.quotes || {};
  return S.data.assets.map(a => {
    const l = q[a.isin];
    if (!l || !a.value) return a;
    // Yahoo fund pages (0P...) carry a NAV from another day than Nordnet's: keep the export for those
    if (/^0P/.test(l.symbol || '')) return a;
    const sameCcy = String(l.currency || '').toUpperCase() === String(a.ccy || '').toUpperCase();
    const ratio = a.price ? l.price / a.price : null;
    // same currency but a very different price = Yahoo symbol is another instrument: do not trust it at all
    if (sameCcy && !(ratio > .5 && ratio < 2)) return a;
    const out = { ...a, live: true, day_pct: l.change_pct ?? a.day_pct, live_price: l.price, live_ccy: l.currency };
    if (sameCcy) {                                   // rescale value and unrealised P&L by live / export price
      const cost = a.value - a.unrealized;
      out.value = a.value * ratio;
      out.unrealized = out.value - cost;
      out.unrealized_pct = cost > 0 ? out.unrealized / cost * 100 : a.unrealized_pct;
    }
    return out;
  });
}

function status() {
  const el = $('heat-status');
  if (!S.data) return;
  const la = liveAssets(), n = la.filter(a => a.value > 0).length, k = la.filter(a => a.live).length;
  const t = S.live && S.live.asof ? S.live.asof.slice(11, 19) : null;
  const f = S.data.sources && S.data.sources.holdings;
  el.innerHTML = `<span class="dot ${k ? 'live' : ''}"></span>${k ? `Live Yahoo prices for ${k} of ${n} holdings · updated ${t}` : 'Live prices unavailable — showing the holdings export'}`
    + ` · holdings file: ${esc(f ? f.file : 'none')}. Nordnet funds and holdings Yahoo can't match keep the export values.`;
}

// ───────── load + public API ─────────
async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  const d = await r.json();
  if (!r.ok || d.error) throw new Error(d.error || 'HTTP ' + r.status);
  return d;
}

async function load() {
  try {
    S.data = await getJSON('/api/assets');
    $('heat-error').hidden = true;
    renderHeat();
    status();
    refreshLive();
  } catch (e) {
    $('heat-error').hidden = false;
    $('heat-error').textContent = 'Could not load holdings: ' + e.message + '. Start the app with python server.py.';
  }
}

async function refreshLive() {
  if (S.tab !== 'heatmap' || !S.data) return;
  try {
    S.live = await getJSON('/api/live');
    renderHeat();
    status();
  } catch (e) { /* keep the last prices; the status line shows what is current */ }
}

// while the tab is open: new CSV on disk -> reload holdings; every 30 s -> fresh Yahoo prices
async function checkCsv() {
  if (S.tab !== 'heatmap') return;
  try {
    const sig = JSON.stringify(await getJSON('/api/trades/status'));
    if (S.sig && sig !== S.sig) { S.sig = sig; S.sectors = null; S.live = null; await load(); return; }
    S.sig = sig;
  } catch (e) { /* server briefly busy */ }
}

function show() {
  S.tab = 'heatmap';
  S.sig = null;
  checkCsv();                       // baseline signature of the CSV files
  load();
  S.timers.forEach(clearInterval);
  S.timers = [setInterval(checkCsv, 10000), setInterval(refreshLive, 30000)];
}
function hide() { S.tab = ''; S.timers.forEach(clearInterval); S.timers = []; }

function bind() {
  $('heat-group').addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { S.heat.group = b.dataset.g; renderHeat(); } });
  $('heat-color').addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { S.heat.color = b.dataset.c; renderHeat(); } });
  window.addEventListener('resize', () => { if (S.tab === 'heatmap') renderHeat(); });
  $('heat-refresh').addEventListener('click', () => { S.sectors = null; S.live = null; load(); });
}
bind();
return { show, hide };
})();
