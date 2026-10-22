/* ============================================================
   asset_chart.js — per-asset price history with BUY/SELL markers.
   Classic script. Public API:  window.AssetChart.render(containerEl, asset)
   Needs Chart.js 4.x (global Chart). Never throws.
   ============================================================ */
(function () {
  'use strict';

  var COL = { grid: '#2A2E39', text: '#D1D4DC', dim: '#787B86', line: '#3987e5',
              buy: '#26A69A', sell: '#EF5350' };
  var FONT = 'Inter, system-ui, sans-serif';
  var seriesCache = new Map();      // symbol|range -> Promise<{meta, pts}>
  var symbolCache = new Map();      // isin|name|ccy -> Promise<symbol obj>
  var charts = new WeakMap();       // canvas -> Chart
  var renderToken = new WeakMap();  // containerEl -> token

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function nf(n, d) {
    if (n == null || isNaN(n)) return '—';
    try { return Number(n).toLocaleString('sv-SE', { maximumFractionDigits: d, minimumFractionDigits: d }).replace('−', '-'); }
    catch (e) { return String(n); }
  }
  function dayTs(iso) { return Date.parse(iso + 'T12:00:00Z'); }
  function tsDate(ts) { return new Date(ts).toISOString().slice(0, 10); }

  function pickRange(firstIso) {
    var days = (Date.now() - dayTs(firstIso)) / 86400000 + 5;
    if (days <= 170) return '6mo';
    if (days <= 350) return '1y';
    if (days <= 710) return '2y';
    if (days <= 1790) return '5y';
    if (days <= 3600) return '10y';
    return 'max';
  }

  function getJSON(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error((j && j.error) || ('HTTP ' + r.status));
        return j;
      });
    });
  }

  function lookupSymbol(asset) {
    var k = [asset.isin, asset.name, asset.ccy].join('|');
    if (!symbolCache.has(k)) {
      var p = getJSON('/api/symbol?isin=' + encodeURIComponent(asset.isin || '') +
        '&name=' + encodeURIComponent(asset.name || '') + '&ccy=' + encodeURIComponent(asset.ccy || ''))
        .catch(function () { symbolCache.delete(k); return { ok: false }; });
      symbolCache.set(k, p);
    }
    return symbolCache.get(k);
  }

  function fetchSeries(symbol, range) {
    var k = symbol + '|' + range;
    if (!seriesCache.has(k)) {
      var p = getJSON('/yahoo/v8/finance/chart/' + encodeURIComponent(symbol) + '?range=' + range + '&interval=1d')
        .then(function (j) {
          var res = j && j.chart && j.chart.result && j.chart.result[0];
          if (!res || !res.timestamp) throw new Error('no data');
          var q = res.indicators && res.indicators.quote && res.indicators.quote[0];
          var cl = (q && q.close) || [];
          var off = (res.meta && res.meta.gmtoffset) || 0;
          var pts = [];
          for (var i = 0; i < res.timestamp.length; i++) {
            if (cl[i] == null || isNaN(cl[i])) continue;
            var d = Math.floor((res.timestamp[i] + off) / 86400) * 86400000 + 43200000;
            pts.push({ x: d, y: cl[i] });
          }
          if (pts.length < 2) throw new Error('too few points');
          return { meta: res.meta || {}, pts: pts };
        })
        .catch(function (e) { seriesCache.delete(k); throw e; });
      seriesCache.set(k, p);
    }
    return seriesCache.get(k);
  }

  function summary(trades, ccy) {
    var b = trades.filter(function (t) { return t.side === 'BUY' || t[2] === 'BUY'; });
    var s = trades.filter(function (t) { return t.side === 'SELL'; });
    function avg(a) {
      var q = 0, v = 0;
      a.forEach(function (t) { q += +t.qty || 0; v += (+t.qty || 0) * (+t.price || 0); });
      return q > 0 ? v / q : null;
    }
    var dates = trades.map(function (t) { return t.date; }).sort();
    return nf(b.length, 0) + ' buys · ' + nf(s.length, 0) + ' sells · avg buy ' +
      (avg(b) == null ? '—' : nf(avg(b), 2) + ' ' + ccy) + ' · avg sell ' +
      (avg(s) == null ? '—' : nf(avg(s), 2) + ' ' + ccy) +
      ' · first ' + (dates[0] || '—') + ' · last ' + (dates[dates.length - 1] || '—');
  }

  function normTrades(asset) {
    var out = [];
    (asset.trades || []).forEach(function (t) {
      if (!t || !t.date) return;
      var side = (t.side || t.type || t.action || '').toString().toUpperCase();
      if (side !== 'BUY' && side !== 'SELL') return;
      out.push({
        date: String(t.date).slice(0, 10), side: side, qty: +t.qty, price: +t.price, ccy: t.ccy || asset.ccy,
        amount: +t.amount, fee: +t.fee, realized: t.realized, x: dayTs(String(t.date).slice(0, 10))
      });
    });
    out.sort(function (a, b) { return a.x - b.x; });
    return out;
  }

  function drawChart(canvas, linePts, trades, yOf, opts) {
    var old = charts.get(canvas);
    if (old) { try { old.destroy(); } catch (e) {} charts.delete(canvas); }
    if (typeof Chart === 'undefined') throw new Error('Chart.js missing');
    var existing = Chart.getChart && Chart.getChart(canvas);
    if (existing) { try { existing.destroy(); } catch (e) {} }

    var maxAmt = trades.reduce(function (m, t) { return Math.max(m, Math.abs(t.amount) || 0); }, 0) || 1;
    function radius(t) {
      var r = 6 + 6 * Math.sqrt(Math.abs(t.amount) / maxAmt || 0);
      return Math.max(6, Math.min(12, r));
    }
    function mk(side) {
      var arr = trades.filter(function (t) { return t.side === side; });
      return arr.map(function (t) { return { x: t.x, y: yOf(t), t: t }; });
    }
    var buys = mk('BUY'), sells = mk('SELL');
    var buyDs = {
      label: 'Buy', data: buys, showLine: false, order: 0,
      pointStyle: 'triangle', rotation: 0, backgroundColor: COL.buy, borderColor: '#0e1118', borderWidth: 1,
      pointRadius: function (c) { return c.raw && c.raw.t ? radius(c.raw.t) : 6; },
      pointHoverRadius: function (c) { return (c.raw && c.raw.t ? radius(c.raw.t) : 6) + 2; }
    };
    var sellDs = {
      label: 'Sell', data: sells, showLine: false, order: 0,
      pointStyle: 'triangle', rotation: 180, backgroundColor: COL.sell, borderColor: '#0e1118', borderWidth: 1,
      pointRadius: buyDs.pointRadius, pointHoverRadius: buyDs.pointHoverRadius
    };
    var lineDs = {
      label: opts.lineLabel, data: linePts, borderColor: opts.faint ? COL.dim : COL.line, borderWidth: 2,
      pointRadius: opts.faint ? 2 : 0, pointHoverRadius: 0, tension: 0, order: 1, fill: false,
      stepped: false, spanGaps: true
    };

    var chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [lineDs, buyDs, sellDs] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
        interaction: { mode: 'nearest', intersect: true },
        font: { family: FONT },
        scales: {
          x: {
            type: 'linear', grid: { color: COL.grid }, border: { color: COL.grid },
            ticks: {
              color: COL.dim, maxTicksLimit: 8, font: { family: FONT, size: 11 },
              callback: function (v) { return tsDate(v); }
            }
          },
          y: {
            grid: { color: COL.grid }, border: { color: COL.grid },
            ticks: { color: COL.dim, font: { family: FONT, size: 11 }, callback: function (v) { return nf(v, v < 10 ? 2 : 0); } }
          }
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: function (it) { return it.datasetIndex > 0; },
            backgroundColor: '#161a23', borderColor: COL.grid, borderWidth: 1,
            titleColor: COL.text, bodyColor: COL.text, titleFont: { family: FONT }, bodyFont: { family: FONT },
            callbacks: {
              title: function (items) { var t = items[0] && items[0].raw && items[0].raw.t; return t ? t.date : ''; },
              label: function (it) {
                var t = it.raw && it.raw.t; if (!t) return '';
                var lines = [t.side + '  qty ' + nf(t.qty, 2) + ' @ ' + nf(t.price, 2) + ' ' + (t.ccy || ''),
                  'Amount ' + nf(t.amount, 0) + ' kr', 'Fee ' + nf(t.fee, 2) + ' kr'];
                if (t.side === 'SELL' && t.realized != null) lines.push('Realised P&L ' + nf(t.realized, 0) + ' kr');
                return lines;
              }
            }
          }
        }
      }
    });
    charts.set(canvas, chart);
    return chart;
  }

  function render(containerEl, asset) {
    try {
      if (!containerEl || !asset) return;
      var token = {};
      renderToken.set(containerEl, token);
      var trades = normTrades(asset);
      var ccy = asset.ccy || '';

      containerEl.innerHTML = '';
      var head = document.createElement('div');
      head.style.cssText = 'font:500 12px ' + FONT + ';color:' + COL.text + ';margin:4px 0 6px';
      head.textContent = (asset.name || '') + (asset.isin ? ' · ' + asset.isin : '');
      var wrap = document.createElement('div');
      wrap.style.cssText = 'position:relative;height:260px;width:100%';
      var canvas = document.createElement('canvas');
      wrap.appendChild(canvas);
      var status = document.createElement('div');
      status.style.cssText = 'font:12px ' + FONT + ';color:' + COL.dim + ';margin-top:6px;line-height:1.5';
      containerEl.appendChild(head);
      containerEl.appendChild(wrap);
      containerEl.appendChild(status);

      var sum = summary(trades, ccy);
      function alive() { return renderToken.get(containerEl) === token && containerEl.isConnected && canvas.isConnected; }
      function setStatus(msg, warn) {
        status.innerHTML = (msg ? '<div style="color:' + (warn ? '#c98500' : COL.dim) + '">' + esc(msg) + '</div>' : '') +
          '<div>' + esc(sum) + '</div>' +
          '<div><span style="color:' + COL.buy + '">&#9650;</span> Buy &nbsp; <span style="color:' + COL.sell +
          '">&#9660;</span> Sell &nbsp; <span style="color:' + COL.line + '">&#9473;</span> ' +
          (status.dataset.mode === 'live' ? 'Daily close' : 'Your trade prices') + '</div>';
      }

      function fallback(reason) {
        if (!alive()) return;
        try {
          status.dataset.mode = 'fallback';
          if (!trades.length) { setStatus('No trades to chart.', true); return; }
          var pts = trades.map(function (t) { return { x: t.x, y: t.price }; });
          drawChart(canvas, pts, trades, function (t) { return t.price; }, { lineLabel: 'Trade price', faint: true });
          setStatus('Live price history unavailable - showing your trade prices only' + (reason ? ' (' + reason + ')' : ''), true);
        } catch (e) { setStatus('Chart unavailable: ' + (e && e.message), true); }
      }

      if (!trades.length) { fallback(''); return; }
      setStatus('Loading price history…');

      lookupSymbol(asset).then(function (sym) {
        if (!alive()) return;
        if (!sym || !sym.ok || !sym.symbol) { fallback('no Yahoo symbol found'); return; }
        var range = pickRange(trades[0].date);
        return fetchSeries(sym.symbol, range).then(function (s) {
          if (!alive()) return;
          var ycur = s.meta && s.meta.currency;
          var tccy = trades.every(function (t) { return t.ccy === trades[0].ccy; }) ? trades[0].ccy : null;
          if (!ycur || !tccy || String(ycur).toUpperCase() !== String(tccy).toUpperCase()) {
            fallback('currency mismatch: trades in ' + (tccy || 'mixed') + ', Yahoo in ' + (ycur || '?'));
            return;
          }
          var firstX = s.pts[0].x, lastX = s.pts[s.pts.length - 1].x + 86400000;
          var inRange = trades.filter(function (t) { return t.x >= firstX - 86400000 && t.x <= lastX; });
          var skipped = trades.length - inRange.length;
          status.dataset.mode = 'live';
          drawChart(canvas, s.pts, inRange, function (t) { return t.price; }, { lineLabel: sym.symbol });
          setStatus(sym.symbol + ' (' + ycur + ')' + (sym.source ? ' · ' + sym.source : '') +
            (skipped ? ' · ' + skipped + ' older trade(s) outside chart range' : ''), false);
        });
      }).catch(function (e) {
        fallback(e && e.message ? e.message : 'fetch failed');
      });
    } catch (e) {
      try { if (typeof console !== 'undefined') console.warn('AssetChart.render failed', e); } catch (_) {}
    }
  }

  window.AssetChart = { render: render };
})();
