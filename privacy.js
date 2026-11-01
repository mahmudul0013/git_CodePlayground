/* Master privacy toggle (eye button in the header). One switch for both pages; remembered in localStorage.
   Masking is visual only (CSS blur / hidden chart labels) - the numbers are still in the page source.

   What it hides when on:
     - anything with class "pv" (mark new private numbers with it)
     - summary / KPI rows and headline numbers (see privacy.css)
     - table columns whose header is a money or size column (kr, SEK, Value, Return, Qty, ...)
     - "... kr" amounts written inside sentences (insight cards, notes)
     - kr axes and tooltips of charts (detected from their callbacks)                                         */
'use strict';
(function () {
  const KEY = 'tv_privacy';
  const root = document.documentElement;
  const get = () => { try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; } };
  const on = () => root.classList.contains('privacy');

  // ---------- 1. money / size table columns -> class pv on their cells ----------
  const MONEY_HEAD = /(^|\s)(kr|sek)(\b|\/)|^(value|return|realised|unrealised|total|net|qty|units|position after)$/i;
  function maskTables() {
    document.querySelectorAll('table').forEach(t => {
      const heads = [...t.querySelectorAll('thead th')];
      if (!heads.length) return;
      const idx = heads.map((th, i) => MONEY_HEAD.test(th.textContent.replace(/[↕↑↓▲▼]/g, '').trim()) ? i : -1).filter(i => i >= 0);
      if (!idx.length) return;
      t.querySelectorAll('tbody tr').forEach(tr => {
        if (tr.cells.length !== heads.length) return;           // expanded detail rows etc.
        idx.forEach(i => tr.cells[i].classList.add('pv'));
      });
    });
  }

  // ---------- 2. "1 234 kr" inside running text -> <span class="pv"> ----------
  const TEXT_SEL = '.vcard p, .finding p, .finding .tip, #bench-note, #dep-hint, .method li, #heat-notes li';
  const KR = /[+\-−]?\d[\d\s ]*(?:,\d+)?\s?kr\b/g, KR_HAS = new RegExp(KR.source);   // KR_HAS has no lastIndex state
  function maskText() {
    document.querySelectorAll(TEXT_SEL).forEach(el => {
      const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
        acceptNode: n => n.parentElement.closest('.pv') ? NodeFilter.FILTER_REJECT : (KR_HAS.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT)
      });
      const hits = []; while (w.nextNode()) hits.push(w.currentNode);
      hits.forEach(n => {
        KR.lastIndex = 0;
        const frag = document.createDocumentFragment(); let last = 0, m;
        const s = n.nodeValue;
        while ((m = KR.exec(s))) {
          frag.append(s.slice(last, m.index));
          const sp = document.createElement('span'); sp.className = 'pv'; sp.textContent = m[0]; frag.append(sp);
          last = m.index + m[0].length;
        }
        frag.append(s.slice(last));
        n.replaceWith(frag);
      });
    });
  }

  let timer = 0;
  const scan = () => { clearTimeout(timer); timer = setTimeout(() => { maskTables(); maskText(); }, 120); };

  // ---------- 3. Chart.js: hide kr axes and tooltips while privacy is on ----------
  const src = f => (typeof f === 'function' ? f.toString() : '');
  const isMoneyScale = s => /fmt\(|\bkr\b/.test(src(s && s.ticks && s.ticks.callback));
  const isMoneyTip = o => Object.values((o.plugins && o.plugins.tooltip && o.plugins.tooltip.callbacks) || {}).some(f => /\bkr\b|fmt\(/.test(src(f)));
  // Works on the raw user options (chart.config.options); the resolved chart.options is a proxy and must not be written to.
  function applyToChart(chart) {
    const hide = on(), o = chart.config.options || {}, mem = chart.$pv || (chart.$pv = {});
    for (const [id, s] of Object.entries(o.scales || {})) {
      if (!isMoneyScale(s)) continue;
      s.ticks = s.ticks || {};
      if (!(id in mem)) mem[id] = s.ticks.display !== false;
      s.ticks.display = hide ? false : mem[id];
    }
    const tip = o.plugins && o.plugins.tooltip;
    if (tip && isMoneyTip(o)) {
      if (!('tip' in mem)) mem.tip = tip.enabled !== false;
      tip.enabled = hide ? false : mem.tip;
    }
  }
  const chartPlugin = { id: 'tvPrivacy', beforeInit: applyToChart };
  const refreshCharts = () => { if (window.Chart && Chart.instances) Object.values(Chart.instances).forEach(c => { try { applyToChart(c); c.update('none'); } catch (e) { /* chart being destroyed */ } }); };
  if (window.Chart) Chart.register(chartPlugin);

  // ---------- toggle ----------
  const apply = state => {
    root.classList.toggle('privacy', state);
    const b = document.getElementById('privacy-btn');
    if (b) { b.setAttribute('aria-pressed', state ? 'true' : 'false'); b.title = state ? 'Values hidden - click to show' : 'Hide portfolio values'; }
    refreshCharts();
  };
  apply(get());                                    // before first paint: no flash of the real numbers
  document.addEventListener('DOMContentLoaded', () => {
    apply(get());
    const b = document.getElementById('privacy-btn');
    if (b) b.addEventListener('click', () => { const s = !get(); try { localStorage.setItem(KEY, s ? '1' : '0'); } catch (e) { /* private mode */ } apply(s); });
    new MutationObserver(scan).observe(document.body, { childList: true, subtree: true });
    scan();
  });
  window.addEventListener('storage', e => { if (e.key === KEY) apply(get()); });   // another open tab/page follows
})();
