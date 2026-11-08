/* Small local assistant: round chat button (every page), compact panel, optional header search in #ask-slot.
   Questions go to POST /api/ask {q}; answers are computed on the server from this user's own data (assistant.py).
   Messages live in memory only (max 20); nothing is stored in the browser. Works without window.TV. */
(function () {
  'use strict';
  if (window.__tvAssistant) return;
  window.__tvAssistant = true;

  const MAX_MSGS = 20;
  const POOL = [
    'What are my total fees?', 'What does split orders mean?', 'Which is my biggest holding?', 'How much dividend have I received?',
    'What is my all-time result?', 'Why is my habit score low?', 'What does TRIM mean?', 'How many positions are under 1 500 kr?',
    'Which stocks should I add?', 'What is courtage?', 'Which holding is down the most?', 'How risky is my portfolio?',
    'What is the 200-day average?', 'How many trades have I made?', 'What is profit factor?', 'Which is my top sector?',
  ];
  const LINK_LABEL = { advice: 'Advice', habits: 'Trading habits', deposits: 'Deposit behaviour', dividends: 'Dividends', assets: 'Assets' };
  const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  let panel, msgs, input, sendBtn, fab, chipsEl, searchEl;
  let open = false, busy = false, poolAt = 0, count = 0;
  const history = []; let hAt = 0;

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // money amounts get class pv so the privacy toggle (html.privacy .pv) blurs them
  const KR = /[+\-−]?\d[\d\s ]*(?:,\d+)?\s?kr\b/g;
  const fmtLine = t => esc(t).replace(KR, m => `<span class="pv">${m}</span>`);

  function icon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M9 11h6M9 14h4"/></svg>';
  }

  function build() {
    fab = document.createElement('button');
    fab.id = 'as-fab'; fab.type = 'button'; fab.setAttribute('aria-label', 'Ask about your portfolio'); fab.setAttribute('aria-expanded', 'false');
    fab.setAttribute('aria-controls', 'as-panel'); fab.title = 'Ask about your portfolio  ( / )'; fab.innerHTML = icon();
    fab.addEventListener('click', () => toggle());

    panel = document.createElement('section');
    panel.id = 'as-panel'; panel.hidden = true; panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Ask about your portfolio');
    panel.innerHTML =
      '<div class="as-head"><b>Ask your portfolio</b><small>answers come from your own data</small>'
      + '<button type="button" id="as-close" aria-label="Close">×</button></div>'
      + '<div id="as-msgs" role="log" aria-live="polite"></div>'
      + '<div id="as-chips"></div>'
      + '<form id="as-form" autocomplete="off"><input id="as-input" type="text" maxlength="300" placeholder="Ask or search…" aria-label="Your question">'
      + '<button type="submit" id="as-send">Ask</button></form>';
    document.body.appendChild(panel);
    document.body.appendChild(fab);

    msgs = panel.querySelector('#as-msgs'); input = panel.querySelector('#as-input'); sendBtn = panel.querySelector('#as-send');
    chipsEl = panel.querySelector('#as-chips');
    panel.querySelector('#as-close').addEventListener('click', () => toggle(false));
    panel.querySelector('#as-form').addEventListener('submit', e => { e.preventDefault(); submit(input.value); });
    chipsEl.addEventListener('click', e => { const b = e.target.closest('.as-chip'); if (b) submit(b.dataset.q); });
    msgs.addEventListener('click', e => { const a = e.target.closest('.as-link'); if (a) { e.preventDefault(); go(a.getAttribute('href')); } });
    input.addEventListener('keydown', e => {
      if (e.key === 'ArrowUp' && history.length) { e.preventDefault(); hAt = Math.max(0, hAt - 1); input.value = history[hAt] || ''; }
      else if (e.key === 'ArrowDown' && history.length) { e.preventDefault(); hAt = Math.min(history.length, hAt + 1); input.value = history[hAt] || ''; }
    });

    const slot = document.getElementById('ask-slot');
    if (slot) {
      searchEl = document.createElement('input');
      searchEl.type = 'search'; searchEl.className = 'as-search'; searchEl.placeholder = 'Ask or search…  ( / )'; searchEl.setAttribute('aria-label', 'Ask or search');
      searchEl.maxLength = 300;
      searchEl.addEventListener('keydown', e => {
        if (e.key === 'Enter' && searchEl.value.trim()) { const q = searchEl.value; searchEl.value = ''; toggle(true); submit(q); }
        else if (e.key === 'Escape') searchEl.blur();
      });
      slot.appendChild(searchEl);
    }
    greet(); chips(null);
  }

  function chips(list) {
    let qs = list;
    if (!qs || !qs.length) { qs = []; for (let i = 0; i < 4; i++) qs.push(POOL[(poolAt + i) % POOL.length]); }
    chipsEl.innerHTML = qs.slice(0, 4).map(q => `<button type="button" class="as-chip" data-q="${esc(q)}">${esc(q)}</button>`).join('');
  }

  function greet() {
    add('bot', 'Hi! Ask about your fees, positions, dividends or any term you see on the page. Name a stock to see its figures.');
  }

  function add(kind, html, cls) {
    const d = document.createElement('div');
    d.className = 'as-msg as-' + (kind === 'me' ? 'me' : 'bot') + (cls ? ' ' + cls : '');
    d.innerHTML = html;
    msgs.appendChild(d);
    count++;
    while (msgs.children.length > MAX_MSGS) msgs.removeChild(msgs.firstChild);
    msgs.scrollTop = msgs.scrollHeight;
    return d;
  }

  function typing() {
    const d = document.createElement('div');
    d.className = 'as-msg as-bot as-typing'; d.setAttribute('aria-label', 'Thinking'); d.innerHTML = '<i></i><i></i><i></i>';
    msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight;
    return d;
  }

  function linkChip(link) {
    if (!link) return '';
    const hash = (link.split('#')[1] || '');
    let label = LINK_LABEL[hash] ? `Open ${LINK_LABEL[hash]} tab` : /account/.test(link) ? 'Open Account' : /index/.test(link) ? 'Open Portfolio' : 'Open';
    return `<a class="as-link" href="${esc(link)}">${esc(label)}</a>`;
  }

  function go(link) {
    if (!link) return;
    const [path, hash] = link.split('#');
    const here = location.pathname.split('/').pop() || 'index.html';
    if (path.split('/').pop() === here && hash) {
      const tab = document.querySelector(`.tab[data-tab="${hash.replace(/"/g, '')}"]`);
      if (tab) { tab.click(); toggle(false); return; }
    }
    location.href = link;
  }

  function render(data) {
    const lines = String(data.answer || '').split('\n').filter(Boolean).slice(0, 2);
    const low = (data.confidence != null && data.confidence < 0.5);
    let html = lines.map((l, i) => `<div class="l${i + 1}">${fmtLine(l)}</div>`).join('');
    if (!low) html += linkChip(data.link);
    add('bot', html, low ? 'as-low' : '');
    chips(low && Array.isArray(data.suggestions) ? data.suggestions : null);
  }

  async function submit(text) {
    const q = String(text || '').trim().slice(0, 300);
    if (!q || busy) return;
    busy = true; sendBtn.disabled = true; input.value = '';
    history.push(q); if (history.length > 30) history.shift(); hAt = history.length;
    poolAt = (poolAt + 1) % POOL.length;
    add('me', esc(q));
    const t0 = Date.now(), dots = typing();
    let data = null, status = 0;
    try {
      const r = await fetch('/api/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-TV': '1' }, credentials: 'same-origin', body: JSON.stringify({ q }),
      });
      status = r.status;
      if (r.ok) { const j = await r.json(); data = j && j.answer !== undefined ? j : (j && j.result) || null; }
    } catch (e) { data = null; }
    const wait = reduce ? 0 : Math.max(0, 380 - (Date.now() - t0));          // a short beat so it feels like a reply, not a flash
    setTimeout(() => {
      dots.remove();
      if (data && data.answer !== undefined) render(data);
      else if (status !== 401 && status !== 409) add('bot', '<div class="l1">Assistant unavailable.</div>', 'as-low');   // 401 / 409: the page wrapper redirects
      busy = false; sendBtn.disabled = false;
      if (open) input.focus();
    }, wait);
  }

  function toggle(force) {
    open = typeof force === 'boolean' ? force : !open;
    panel.hidden = !open;
    fab.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) { poolAt = (poolAt + 4) % POOL.length; if (msgs.children.length <= 1) chips(null); setTimeout(() => input.focus(), 30); }
    else if (document.activeElement && panel.contains(document.activeElement)) fab.focus();
  }

  document.addEventListener('keydown', e => {
    if (!panel) return;
    if (e.key === 'Escape' && open) { toggle(false); return; }
    if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const t = e.target, tag = t && t.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
      e.preventDefault();
      if (searchEl && searchEl.offsetParent !== null) searchEl.focus(); else { toggle(true); }
    }
  });

  function init() { if (!document.getElementById('as-fab')) build(); }
  window.TVAssistant = { open: () => toggle(true), close: () => toggle(false), ask: q => { toggle(true); submit(q); } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
