/* auth.js - loaded FIRST on every page (before privacy.js / app.js / analytics.js).
   - wraps window.fetch: same-origin credentials, X-TV header on every non-GET (CSRF guard), 401 -> login, 409 no_files -> upload
   - window.TV = { me, sid, ready, key(name), logout() }: the signed-in user; `ready` resolves once /api/auth/me answered
   - renders the user menu into #user-menu (username, upload / replace files, account, admin, log out)
   Pages must not fetch or read per-user localStorage before TV.ready resolves. */
'use strict';
(function () {
  const PATH = location.pathname.toLowerCase();
  const PUBLIC = /\/login\.html$/.test(PATH);           // no session needed, no redirects
  const ACCOUNT = /\/account\.html$/.test(PATH);        // handles 409 itself
  const origFetch = window.fetch.bind(window);
  const never = new Promise(() => {});                  // keeps a page quiet while the browser navigates away
  let leaving = false;
  const go = url => { if (!leaving) { leaving = true; location.replace(url); } return never; };
  const here = () => location.pathname + location.search + location.hash;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sameOrigin = u => { try { return new URL(u, location.href).origin === location.origin; } catch (e) { return false; } };

  window.fetch = function (input, init) {
    if (typeof input !== 'string' && !(input instanceof URL)) return origFetch(input, init);
    const url = String(input);
    if (!sameOrigin(url)) return origFetch(input, init);            // Yahoo / logo hosts etc. stay untouched
    init = Object.assign({}, init || {}, { credentials: 'same-origin' });
    const m = (init.method || 'GET').toUpperCase();
    if (m !== 'GET' && m !== 'HEAD') { const h = new Headers(init.headers || {}); h.set('X-TV', '1'); init.headers = h; }
    return origFetch(url, init).then(async r => {
      if (PUBLIC) return r;
      if (r.status === 401) {
        let d = null; try { d = await r.clone().json(); } catch (e) { /* not json */ }
        if (!d || d.error === 'auth') return go('/login.html?next=' + encodeURIComponent(here()));
      } else if (r.status === 409 && !ACCOUNT) {
        let d = null; try { d = await r.clone().json(); } catch (e) { /* not json */ }
        if (d && d.error === 'no_files') return go('/account.html#upload');
      }
      return r;
    });
  };

  // per-user localStorage keys written by earlier single-user versions belong to the admin (the owner): move them once
  const LEGACY = ['portfolio_lastbuy', 'portfolio_snapshot', 'portfolio_snapshot_ts', 'tv_privacy', 'tv_advice_profile'];
  function migrate() {
    if (!TV.me || TV.me.role !== 'admin') return;
    try {
      LEGACY.forEach(n => {
        const v = localStorage.getItem(n);
        if (v !== null && localStorage.getItem(TV.key(n)) === null) localStorage.setItem(TV.key(n), v);
        if (v !== null) localStorage.removeItem(n);
      });
    } catch (e) { /* private mode */ }
  }

  const TV = window.TV = {
    me: null, sid: '', ready: null,
    key: name => TV.sid ? name + ':' + TV.sid : name,
    async logout() {
      try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (e) { /* leave anyway */ }
      leaving = true; location.replace('/login.html');
    },
  };

  function menu() {
    const host = document.getElementById('user-menu');
    if (!host || !TV.me) return;
    const u = TV.me, name = esc(u.username);
    host.innerHTML = `<div class="um"><button type="button" class="um-btn" aria-haspopup="menu" aria-expanded="false" title="${name}">
        <span class="um-av">${esc((u.username || '?').charAt(0).toUpperCase())}</span><span class="um-name">${name}</span>
        <svg class="um-caret" width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M2 3.5l3 3 3-3"/></svg></button>
      <div class="um-pop" role="menu" hidden>
        <div class="um-head"><b>${name}</b><small>${u.accno ? 'Account ' + esc(u.accno) : 'No account yet'}${u.role === 'admin' ? ' · admin' : ''}</small></div>
        <a role="menuitem" href="/account.html#upload">Upload / replace files</a>
        <a role="menuitem" href="/account.html">Account</a>
        ${u.role === 'admin' ? '<a role="menuitem" href="/account.html#admin">Admin</a>' : ''}
        <button role="menuitem" type="button" data-act="logout">Log out</button>
      </div></div>`;
    const btn = host.querySelector('.um-btn'), pop = host.querySelector('.um-pop');
    const set = open => { pop.hidden = !open; btn.setAttribute('aria-expanded', open ? 'true' : 'false'); };
    btn.addEventListener('click', e => { e.stopPropagation(); set(pop.hidden); });
    pop.addEventListener('click', e => { if (e.target.closest('[data-act=logout]')) TV.logout(); });
    document.addEventListener('click', e => { if (!host.contains(e.target)) set(false); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
  }

  if (PUBLIC) {
    TV.ready = Promise.resolve(null);
  } else {
    TV.ready = fetch('/api/auth/me', { cache: 'no-store' }).then(async r => {
      const d = await r.json();
      if (!r.ok || !d.user) throw new Error(d.error || 'HTTP ' + r.status);
      TV.me = d.user; TV.sid = d.user.sid || '';
      migrate();
      if (!d.user.has_files && !ACCOUNT) return go('/account.html#upload');
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', menu); else menu();
      return d.user;
    }).catch(e => { TV.error = e.message; return null; });          // server unreachable: pages show their own errors
  }
})();
