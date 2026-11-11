/* Net asset value growth curve (Portfolio page). Data: GET /api/nav (server: nav.py, where the calculation lives).
   One chart space. Time range (single choice) x view (Value kr / Growth %) x smoothing x categories (multi choice, same Yahoo
   sectors as the heat map). Every change rescales the axes. Growth % is time-weighted, so a deposit is never shown as growth.

   Smoothing is for the drawing only: the line is a short triangular moving average (its first and last point stay exact) drawn
   as a monotone curve (no overshoot). The tooltip and the tiles always show the exact daily values from the server. */
'use strict';
(function () {
  const RANGES = [['1w', '1W'], ['1m', '1M'], ['3m', '3M'], ['ytd', 'YTD'], ['1y', '1Y'], ['3y', '3Y'], ['max', 'Max']];
  const MODES = [['value', 'Value (kr)'], ['growth', 'Growth (%)']];
  const SMOOTH = [['off', 'Off'], ['light', 'Light'], ['strong', 'Strong']];
  const SMOOTH_R = { off: 0, light: 2, strong: 5 };                          // radius of the moving average in trading days (before the short-range cap)
  // bright, well separated hues for a dark background, assigned to a curve while it is selected (no two selected curves share one).
  // Gold and white are reserved: white = whole account, gold = money deposited.
  const PALETTE = ['#4C9AFF', '#FF7A45', '#2EC4A0', '#B388FF', '#FF6FB5', '#22D3EE', '#A3E635', '#FF5C5C'];
  const DASHES = [[], [], [], [], [], [8, 3], [2, 3], [10, 3, 2, 3]];       // curves 6-8 also differ by line style (colour-blind friendly)
  const TOTAL = '__total', TOTAL_COLOR = '#FFFFFF', DEPOSIT_COLOR = '#F7C948', MAX_CURVES = 8;
  const GAIN = 'rgba(38, 166, 154, .26)', LOSS = 'rgba(239, 83, 80, .28)';
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf0 = new Intl.NumberFormat('sv-SE', { maximumFractionDigits: 0 });
  const kr = v => nf0.format(Math.round(v)).replace('−', '-') + ' kr';
  const sgnKr = v => (v > 0 ? '+' : v < 0 ? '-' : '') + nf0.format(Math.abs(Math.round(v))) + ' kr';
  const pct = (v, d = 1) => (v > 0 ? '+' : v < 0 ? '-' : '') + Math.abs(v).toFixed(d).replace('.', ',') + '%';
  const compact = v => { const a = Math.abs(v); return (v < 0 ? '-' : '') + (a >= 1e6 ? (a / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace('.', ',') + ' M' : a >= 1e3 ? nf0.format(Math.round(a / 1e3)) + 'k' : nf0.format(Math.round(a))); };
  const store = {
    get: (k, d) => { try { const x = localStorage.getItem(window.TV ? TV.key(k) : k); return x == null ? d : JSON.parse(x); } catch (e) { return d; } },
    set: (k, v) => { try { localStorage.setItem(window.TV ? TV.key(k) : k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
  };

  const S = { data: null, range: 'max', mode: 'value', smooth: 'light', sel: [TOTAL], colors: new Map(), chart: null, chartMode: null, timer: 0 };

  // ───────── data helpers ─────────
  function startIndex(key) {
    const d = S.data.dates, last = new Date(d[d.length - 1] + 'T00:00:00');
    if (key === 'max') return 0;
    let cut;
    if (key === 'ytd') cut = new Date(last.getFullYear(), 0, 1);
    else { cut = new Date(last); const n = { '1w': 7, '1m': 30, '3m': 91, '1y': 365, '3y': 1096 }[key]; cut.setDate(cut.getDate() - n); }
    const iso = cut.getFullYear() + '-' + String(cut.getMonth() + 1).padStart(2, '0') + '-' + String(cut.getDate()).padStart(2, '0');
    let i = d.findIndex(x => x >= iso);
    if (i < 0) i = d.length - 1;
    return Math.min(i, d.length - 2);
  }
  const labelOf = k => k === TOTAL ? 'Total NAV' : k;
  function colorOf(k) {
    if (k === TOTAL) return TOTAL_COLOR;
    if (!S.colors.has(k)) {
      const used = new Set(S.colors.values());
      S.colors.set(k, PALETTE.find(c => !used.has(c)) || PALETTE[S.colors.size % PALETTE.length]);
    }
    return S.colors.get(k);
  }
  const dashOf = k => k === TOTAL ? [] : DASHES[Math.max(0, PALETTE.indexOf(colorOf(k)))] || [];
  // exact values of one curve for the chosen range / view (server numbers; growth is re-based to 0 at the start of the range)
  function seriesFor(k, s) {
    const D = S.data, n = D.dates.length - s;
    const src = k === TOTAL ? D.total : D.categories[k];
    if (!src) return null;
    const value = k === TOTAL ? D.total.nav : src.value, twr = src.twr;
    const out = new Array(n).fill(null);
    if (S.mode === 'value') {
      for (let i = 0; i < n; i++) { const v = value[s + i]; out[i] = (k === TOTAL || v > 0.5) ? v : null; }
    } else {
      const first = k === TOTAL ? s : Math.max(s, src.first);
      const base = twr[first];
      for (let i = first - s; i < n; i++) out[i] = (twr[s + i] / base - 1) * 100;
    }
    return out;
  }
  // drawing only: triangular-weighted centred moving average per unbroken run of data; the window shrinks towards both ends so the
  // first and last point are exact; short runs (1W) are left alone
  function smoothed(arr, base) {
    if (!base) return arr.slice();
    const n = arr.length, out = new Array(n).fill(null);
    let i = 0;
    while (i < n) {
      if (arr[i] == null) { i++; continue; }
      let j = i; while (j < n && arr[j] != null) j++;
      const r0 = Math.min(base, Math.floor((j - i) / 12));
      for (let k = i; k < j; k++) {
        const r = Math.min(r0, k - i, j - 1 - k);
        let sw = 0, sv = 0;
        for (let d = -r; d <= r; d++) { const w = r + 1 - Math.abs(d); sw += w; sv += w * arr[k + d]; }
        out[k] = sv / sw;
      }
      i = j;
    }
    return out;
  }

  // ───────── controls ─────────
  function seg(id, items, current, onPick) {
    const el = $(id);
    el.innerHTML = items.map(([v, t]) => `<button type="button" role="radio" aria-checked="${v === current}" data-v="${v}">${t}</button>`).join('');
    el.onclick = e => { const b = e.target.closest('button'); if (b) onPick(b.dataset.v); };
  }
  function drawControls() {
    seg('nav-range', RANGES, S.range, v => { S.range = v; store.set('nav_range', v); drawControls(); render(); });
    seg('nav-mode', MODES, S.mode, v => { S.mode = v; store.set('nav_mode', v); drawControls(); render(); });
    seg('nav-smooth', SMOOTH, S.smooth, v => { S.smooth = v; store.set('nav_smooth', v); drawControls(); render(); });
    const D = S.data, tot = D.total.nav[D.total.nav.length - 1];
    const cats = D.order.map(k => ({ k, w: D.categories[k].value[D.categories[k].value.length - 1] / (tot - D.total.cash[D.total.cash.length - 1] || 1) * 100 }));
    const chips = [{ k: TOTAL, w: null }].concat(cats);
    $('nav-cats').innerHTML = chips.map(({ k, w }) => {
      const on = S.sel.includes(k), col = on ? colorOf(k) : '';
      return `<label class="nav-cat ${on ? 'on' : ''}" ${on ? `style="color:${col}"` : ''} title="${k === TOTAL ? 'Whole account: holdings + cash' : esc(k) + ' (Yahoo sector, as in the heat map)'}">
        <input type="checkbox" value="${esc(k)}" ${on ? 'checked' : ''}><i ${on ? `style="background:${col}"` : ''}></i><b style="font-weight:600;color:var(--text)">${esc(labelOf(k))}</b>${w != null ? `<span>${w >= 1 ? Math.round(w) : w.toFixed(1)}%</span>` : ''}</label>`;
    }).join('');
    $('nav-cats').onchange = e => {
      const k = e.target.value;
      if (e.target.checked) {
        if (S.sel.length >= MAX_CURVES) { e.target.checked = false; note('Up to ' + MAX_CURVES + ' curves at once keeps the chart readable. Untick one first.'); return; }
        S.sel.push(k);
      } else {
        if (S.sel.length === 1) { e.target.checked = true; return; }       // the chart always shows at least one curve
        S.sel = S.sel.filter(x => x !== k); S.colors.delete(k);
      }
      store.set('nav_sel', S.sel); drawControls(); render();
    };
  }

  // ───────── chart ─────────
  const crossPlugin = { id: 'navCross', afterDatasetsDraw(ch) {
    const a = ch.tooltip && ch.tooltip.getActiveElements ? ch.tooltip.getActiveElements() : [];
    if (!a.length) return;
    const x = a[0].element.x, { top, bottom } = ch.chartArea, g = ch.ctx;
    g.save(); g.strokeStyle = '#787B86'; g.lineWidth = 1; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(x, top); g.lineTo(x, bottom); g.stroke(); g.restore();
  } };
  // direct labels at the right end of every line (so colour is never the only way to tell the lines apart)
  const endLabels = { id: 'navEnd', afterDatasetsDraw(ch) {
    const pad = ch.options.layout.padding.right;
    if (!pad || pad < 30) return;
    const g = ch.ctx, items = [], { top, bottom } = ch.chartArea;
    ch.data.datasets.forEach((ds, i) => {
      if (!ds.endLabel) return;
      let k = ds.data.length - 1; while (k >= 0 && ds.data[k] == null) k--;
      const el = k >= 0 && ch.getDatasetMeta(i).data[k];
      if (el) items.push({ x: el.x, y: el.y, text: ds.endLabel, color: ds.borderColor });
    });
    items.sort((a, b) => a.y - b.y);
    const gap = 13;
    for (let i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < gap) items[i].y = items[i - 1].y + gap;
    if (items.length && items[items.length - 1].y > bottom) { const sh = items[items.length - 1].y - bottom; items.forEach(it => { it.y -= sh; }); }
    if (items.length && items[0].y < top) { const sh = top - items[0].y; items.forEach(it => { it.y += sh; }); }
    g.save(); g.font = '600 11px Inter, system-ui, sans-serif'; g.textBaseline = 'middle';
    items.forEach(it => { g.fillStyle = it.color; g.fillText(it.text, it.x + 7, it.y); });
    g.restore();
  } };
  const shortDate = (iso, long) => { const d = new Date(iso + 'T00:00:00'); return long ? d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }); };
  const rawAt = (it) => { const r = it.dataset.raw; return r ? r[it.dataIndex] : it.parsed.y; };

  function makeChart() {
    if (S.chart) S.chart.destroy();
    const value = S.mode === 'value', Ch = window.Chart;
    S.chartMode = S.mode;
    S.chart = new Ch($('nav-chart'), {
      type: 'line', data: { labels: [], datasets: [] }, plugins: [crossPlugin, endLabels],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, spanGaps: false,
        layout: { padding: { top: 8, right: 6 } },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            // exact daily values (the drawn line may be smoothed); sorted high to low
            itemSort: (a, b) => (rawAt(b) ?? -1e18) - (rawAt(a) ?? -1e18),
            filter: it => rawAt(it) != null,
            callbacks: {
              title: it => it.length ? shortDate(it[0].label, true) : '',
              label: c => value ? ` ${c.dataset.label}: ${kr(rawAt(c))}` : ` ${c.dataset.label}: ${pct(rawAt(c), 2)}`,
              footer: its => {
                if (!value) return '';
                const t = its.find(x => x.dataset.label === 'Total NAV'), dp = its.find(x => x.dataset.label === 'Net deposited');
                if (!t || !dp) return '';
                const g = rawAt(t) - rawAt(dp);
                return `Gain vs deposited: ${sgnKr(g)} (${pct(g / rawAt(dp) * 100, 1)})`;
              },
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 11 },
            callback(v) { const iso = this.getLabelForValue(v); const n = S.data.dates.length - startIndex(S.range); return n > 190 ? new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { month: 'short', year: '2-digit' }) : shortDate(iso); } } },
          y: { grace: '6%', grid: { color: c => (!value && c.tick && c.tick.value === 0) ? '#787B86' : '#2A2E39' },
            ticks: { maxTicksLimit: 6, font: { size: 11 }, callback: value ? (v => compact(v) + ' kr') : (v => v + '%') } },
        },
      },
    });
  }

  function render() {
    const D = S.data; if (!D) return;
    const s = startIndex(S.range), dates = D.dates.slice(s);
    // KPIs for the whole account over the chosen range (deposits shown apart from growth) - always exact numbers
    const nav = D.total.nav, tw = D.total.twr, nd = D.total.net_deposits;
    const e = nav.length - 1, ret = (tw[e] / tw[s] - 1) * 100;
    let peak = tw[s], dd = 0; for (let i = s; i <= e; i++) { peak = Math.max(peak, tw[i]); dd = Math.min(dd, tw[i] / peak - 1); }
    const chg = nav[e] - nav[s], dep = nd[e] - nd[s];
    const cls = v => v > 0 ? 'up' : v < 0 ? 'down' : '';
    $('nav-kpis').innerHTML =
      `<div class="nav-kpi"><div class="l">Net asset value</div><div class="v pv">${kr(nav[e])}</div><div class="s">${shortDate(D.dates[e], true)} · holdings + cash</div></div>
       <div class="nav-kpi"><div class="l">Change in range</div><div class="v pv ${cls(chg)}">${sgnKr(chg)}</div><div class="s pv">${kr(dep)} deposited · result ${sgnKr(chg - dep)}</div></div>
       <div class="nav-kpi"><div class="l">Growth (time-weighted)</div><div class="v ${cls(ret)}">${pct(ret, 2)}</div><div class="s">deposits excluded, after fees</div></div>
       <div class="nav-kpi"><div class="l">Largest drop</div><div class="v ${cls(dd)}">${pct(dd * 100, 1)}</div><div class="s">peak to trough in range</div></div>`;
    $('nav-badge').textContent = `${shortDate(D.dates[s], true)} → ${shortDate(D.dates[e], true)}`;

    const datasets = [], base = SMOOTH_R[S.smooth];
    S.sel.forEach(k => {
      const raw = seriesFor(k, s); if (!raw) return;
      const total = k === TOTAL;
      datasets.push({
        label: labelOf(k), data: smoothed(raw, base), raw, borderColor: colorOf(k), backgroundColor: colorOf(k), borderWidth: total ? 3 : 2, borderDash: dashOf(k),
        pointRadius: 0, pointHoverRadius: 4, pointHoverBackgroundColor: colorOf(k), tension: 0, cubicInterpolationMode: base ? 'monotone' : 'default',
        order: total ? 0 : 1, endLabel: total ? (S.mode === 'value' ? 'NAV' : 'Total') : (k.length > 15 ? k.slice(0, 14) + '…' : k),
      });
    });
    if (S.mode === 'value' && S.sel.includes(TOTAL)) {
      const dep = nd.slice(s);
      datasets.push({ label: 'Net deposited', data: dep, raw: dep, borderColor: DEPOSIT_COLOR, backgroundColor: DEPOSIT_COLOR, borderWidth: 2, borderDash: [7, 4], pointRadius: 0, pointHoverRadius: 0, stepped: 'before', order: 2, endLabel: 'Deposited' });
      // the area between the NAV and the money put in = gain (green) or loss (red)
      const ti = datasets.findIndex(d => d.label === 'Total NAV'), di = datasets.length - 1;
      if (ti >= 0) datasets[ti].fill = { target: di, above: GAIN, below: LOSS };
    }
    const empty = !datasets.length || datasets.every(d => d.data.every(v => v == null));
    $('nav-empty').hidden = !empty;
    if (!S.chart || S.chartMode !== S.mode) makeChart();
    // value view: an account never goes below 0, so the axis starts at 0 or just under the lowest point (no wasted negative space)
    const ys = S.chart.options.scales.y;
    if (S.mode === 'value') {
      const all = datasets.flatMap(d => d.data).filter(v => v != null);
      if (all.length) { const lo = Math.min(...all), hi = Math.max(...all); ys.min = Math.max(0, lo - (hi - lo) * 0.06); } else delete ys.min;
    } else delete ys.min;
    // room on the right for the end labels (skipped on narrow screens, where the pills below the chart are the legend)
    const wide = $('nav-chart').clientWidth >= 520;
    let pad = 6;
    if (wide && datasets.length) { const g = S.chart.ctx; g.save(); g.font = '600 11px Inter, system-ui, sans-serif'; pad = Math.ceil(Math.max(...datasets.map(d => g.measureText(d.endLabel || '').width))) + 14; g.restore(); }
    S.chart.options.layout.padding.right = pad;
    S.chart.data.labels = dates; S.chart.data.datasets = datasets; S.chart.update('none');
    $('nav-chart').setAttribute('aria-label', `Net asset value from ${shortDate(D.dates[s], true)} to ${shortDate(D.dates[e], true)}: from ${kr(nav[s])} to ${kr(nav[e])}, growth ${pct(ret, 1)}. Showing ${S.sel.map(labelOf).join(', ')}.`);
    note();
  }

  function note(extra) {
    const D = S.data, c = D.coverage || {};
    const est = (c.estimated || []).length ? ` ${c.estimated.length > 3 ? c.estimated.length + ' holdings' : c.estimated.join(', ')} use your own trade prices (no Yahoo price series).` : '';
    const rej = (c.symbol_rejected || []).length ? ` Yahoo symbol not trusted for ${c.symbol_rejected.join(', ').replace(/\.$/, '')}.` : '';
    const recon = c.nav_vs_export_pct != null ? ` On ${c.export_date} the curve is within ${Math.abs(c.nav_vs_export_pct).toFixed(1)}% of your Nordnet export.` : '';
    const sm = S.smooth !== 'off' ? ' Lines are smoothed for readability only; the tooltip and tiles show the exact daily values.' : '';
    const fill = (S.mode === 'value' && S.sel.includes(TOTAL)) ? ' Green area = gain over the money you put in (gold dashed line), red = loss.' : '';
    $('nav-note').innerHTML = (extra ? `<b>${esc(extra)}</b> ` : '')
      + `Rebuilt from your transactions and Yahoo daily closes (${Math.round(c.yahoo_pct || 0)}% of today's holdings priced from Yahoo).${esc(est)}${esc(rej)}${esc(recon)}${fill}${sm} `
      + (S.mode === 'growth' ? 'Total growth includes dividends and fees; a category shows the price growth of what you held in it.' : 'Categories show the market value of what you held in each Yahoo sector.');
  }

  // ───────── load ─────────
  async function load() {
    clearTimeout(S.timer);
    try {
      const r = await fetch('/api/nav', { cache: 'no-store' });
      const d = await r.json();
      if (!d.ok) { $('nav-badge').textContent = 'Not available'; $('nav-empty').hidden = false; $('nav-empty').textContent = d.message || 'The growth curve could not be built yet.'; return; }
      const first = !S.data;
      S.data = d;
      S.sel = S.sel.filter(k => k === TOTAL || d.categories[k]); if (!S.sel.length) S.sel = [TOTAL];
      $('nav-empty').textContent = 'Nothing to show for this selection and range.';
      drawControls(); render();
      if (first) $('nav-chart').closest('.nav-card').dataset.ready = '1';
      if (d.pending) { $('nav-badge').textContent += ' · loading prices'; S.timer = setTimeout(load, 20000); }
      else S.timer = setTimeout(load, 10 * 60 * 1000);
    } catch (e) {
      $('nav-badge').textContent = 'Not available';
      S.timer = setTimeout(load, 60000);
    }
  }

  function init() {
    if (!$('nav-section') || !window.Chart) return;
    S.range = store.get('nav_range', 'max'); S.mode = store.get('nav_mode', 'value'); S.smooth = store.get('nav_smooth', 'light'); S.sel = store.get('nav_sel', [TOTAL]);
    if (!SMOOTH_R.hasOwnProperty(S.smooth)) S.smooth = 'light';
    if (!Array.isArray(S.sel) || !S.sel.length) S.sel = [TOTAL];
    load();
  }
  (window.TV && TV.ready ? TV.ready : Promise.resolve()).then(() => { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init(); });
  window.NavCurve = { refresh: load, smoothed };
})();
