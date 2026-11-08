/* Scalable charts and layout helpers. Load right after Chart.js and BEFORE app.js / analytics.js, so the Chart.js
   defaults below are in place before the first chart is created (responsive.css does the CSS side).
   - Chart.js defaults by screen width (font, legend, ticks); re-applied on rotation / resize
   - debounced resize + orientation handling: every chart is resized and refitted, custom renderers (heat map) get a resize event
   - Portfolio page: the reports-calendar sidebar becomes a slide-in drawer on narrow screens (button injected here)
   - warns in the console when the viewport meta tag is missing */
'use strict';
(function () {
  if (window.__tvResponsive) return;
  window.__tvResponsive = true;

  const vw = () => document.documentElement.clientWidth || window.innerWidth;

  // ───────── viewport meta check ─────────
  const meta = document.querySelector('meta[name="viewport"]');
  if (!meta || !/width\s*=\s*device-width/.test(meta.content)) console.warn('[responsive] <meta name="viewport" content="width=device-width, initial-scale=1"> is missing: phones will render the desktop layout.');

  // ───────── Chart.js defaults ─────────
  function applyDefaults() {
    if (!window.Chart) return;
    const D = Chart.defaults, w = vw(), narrow = w < 600, mid = w < 900;
    D.responsive = true;
    D.maintainAspectRatio = false;
    D.devicePixelRatio = Math.min(window.devicePixelRatio || 1, 3);          // crisp (vector text) on phones, without huge canvases
    D.font.size = narrow ? 11 : 12;
    const L = D.plugins.legend.labels;
    L.boxWidth = narrow ? 8 : 10; L.boxHeight = narrow ? 8 : 10; L.padding = narrow ? 8 : 12;
    L.font = Object.assign({}, L.font, { size: narrow ? 11 : 12 });
    D.elements.point.radius = narrow ? 0 : D.elements.point.radius;
    D.elements.line.borderWidth = narrow ? 1.5 : 2;
    D.elements.bar.borderWidth = 0;
    const lim = narrow ? 5 : mid ? 7 : 10;
    for (const k of ['linear', 'logarithmic', 'category', 'time']) {
      const s = D.scales && D.scales[k];
      if (s && s.ticks) { s.ticks.maxTicksLimit = lim; s.ticks.autoSkipPadding = narrow ? 14 : 6; }
    }
    if (D.scale && D.scale.ticks) { D.scale.ticks.autoSkipPadding = narrow ? 14 : 6; if (narrow) D.scale.ticks.maxRotation = 0; }
  }
  applyDefaults();

  // ───────── refit on resize / rotation (debounced) ─────────
  let lastW = vw(), timer = 0, synthetic = false;
  function refit(fromEvent) {
    const w = vw();
    applyDefaults();
    if (window.Chart && Chart.instances) {
      Object.values(Chart.instances).forEach(c => { try { c.resize(); if (Math.abs(w - lastW) > 40) c.update('none'); } catch (e) { /* chart being destroyed */ } });
    }
    // custom renderers (heat map treemap) listen to window resize only: tell them when the size changed without a real resize event
    if (!fromEvent && Math.abs(w - lastW) > 1) { synthetic = true; const ev = new Event('resize'); ev.__tvr = 1; window.dispatchEvent(ev); synthetic = false; }
    lastW = w;
    if (w > 900) document.body && document.body.classList.remove('wl-open');
  }
  function schedule(fromEvent) { clearTimeout(timer); timer = setTimeout(() => refit(fromEvent), 150); }
  window.addEventListener('resize', e => { if (!e.__tvr && !synthetic) schedule(true); });
  window.addEventListener('orientationchange', () => schedule(true));
  // second pass after rotation: browsers report the final size a little late
  window.addEventListener('orientationchange', () => setTimeout(() => refit(true), 450));

  document.addEventListener('DOMContentLoaded', () => {
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => { if (Math.abs(vw() - lastW) > 1) schedule(false); });
      ro.observe(document.documentElement);
      const heat = document.getElementById('heat-map');
      if (heat) new ResizeObserver(() => { if (Math.abs(vw() - lastW) <= 1) { /* container changed on its own (sidebar, scrollbar) */ synthetic = true; const ev = new Event('resize'); ev.__tvr = 1; window.dispatchEvent(ev); synthetic = false; } }).observe(heat);
    }

    // ───────── tab bar (Analytics): the active tab scrolls into view inside the bar, never scrolls the page ─────────
    const tabs = document.querySelector('.tabs');
    if (tabs) {
      const show = () => { const t = tabs.querySelector('.tab.active'); if (t && tabs.scrollWidth > tabs.clientWidth) tabs.scrollTo({ left: Math.max(0, t.offsetLeft - (tabs.clientWidth - t.offsetWidth) / 2), behavior: 'smooth' }); };
      tabs.addEventListener('click', () => setTimeout(show, 0));
      setTimeout(show, 400);
    }

    // ───────── watchlist drawer (Portfolio page, narrow screens) ─────────
    const side = document.getElementById('sidebar'), head = document.querySelector('#main-header .header-left');
    if (side && head) {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.id = 'wl-toggle'; btn.className = 'wl-toggle';
      btn.setAttribute('aria-controls', 'sidebar'); btn.setAttribute('aria-expanded', 'false'); btn.setAttribute('aria-label', 'Show reports calendar');
      btn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h10"/></svg>';
      head.insertBefore(btn, head.firstChild);
      const back = document.createElement('div'); back.id = 'wl-backdrop'; document.body.appendChild(back);
      const set = on => {
        document.body.classList.toggle('wl-open', on);
        btn.setAttribute('aria-expanded', on ? 'true' : 'false'); btn.setAttribute('aria-label', on ? 'Hide reports calendar' : 'Show reports calendar');
      };
      btn.addEventListener('click', () => set(!document.body.classList.contains('wl-open')));
      back.addEventListener('click', () => set(false));
      document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.body.classList.contains('wl-open')) { set(false); btn.focus(); } });
    }
  });
})();
