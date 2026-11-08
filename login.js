/* login.js - first-run setup, sign in, register with an invite code. All text from the server is shown with textContent. */
'use strict';
(function () {
  const $ = id => document.getElementById(id);
  const forms = { login: $('f-login'), register: $('f-register'), setup: $('f-setup') };
  const TITLES = {
    login: ['Sign in', 'Your portfolio is private to your account.'],
    register: ['Create your account', 'You need an invite code from the admin.'],
    setup: ['Welcome', 'First start: create the admin account. The setup code is printed in the server window.'],
  };
  let timer = 0;

  function say(kind, text) {
    const m = $('msg');
    m.hidden = !text; m.className = 'msg ' + (kind || 'err'); m.textContent = text || '';
  }
  function show(name) {
    Object.entries(forms).forEach(([k, f]) => { f.hidden = k !== name; });
    $('ttl').textContent = TITLES[name][0]; $('sub').textContent = TITLES[name][1];
    say('', '');
    const first = forms[name].querySelector('input'); if (first) first.focus();
  }
  document.querySelectorAll('[data-show]').forEach(b => b.addEventListener('click', () => show(b.dataset.show)));

  // only same-site paths are accepted as the page to return to
  function nextUrl() {
    const n = new URLSearchParams(location.search).get('next');
    return n && n.charAt(0) === '/' && n.charAt(1) !== '/' && n.indexOf('\\') < 0 ? n : '/index.html';
  }

  async function post(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    let d = {}; try { d = await r.json(); } catch (e) { /* empty body */ }
    return { r, d };
  }

  function lock(btn, secs) {
    clearInterval(timer);
    const label = btn.dataset.label || (btn.dataset.label = btn.textContent);
    let left = Math.max(1, Math.ceil(secs));
    btn.disabled = true;
    const tick = () => {
      if (left <= 0) { clearInterval(timer); btn.disabled = false; btn.textContent = label; say('', ''); return; }
      const m = Math.floor(left / 60), s = String(left % 60).padStart(2, '0');
      say('err', `Too many attempts. Try again in ${m}:${s}.`); btn.textContent = `Wait ${m}:${s}`; left--;
    };
    tick(); timer = setInterval(tick, 1000);
  }

  function explain(r, d, btn) {
    if (r.status === 429 || d.error === 'locked') { lock(btn, d.retry_after || 60); return; }
    const text = {
      bad: 'Wrong username or password.',
      bad_credentials: 'Wrong username or password.',
      csrf: 'The browser request was refused. Reload the page and try again.',
    }[d.error];
    say('err', text || d.message || (d.error ? String(d.error) : 'Something went wrong (HTTP ' + r.status + ').'));
  }

  // after a successful sign-in: no files yet -> upload screen, otherwise where the user was heading
  async function arrive() {
    let me = null;
    try { me = (await (await fetch('/api/auth/me', { cache: 'no-store' })).json()).user; } catch (e) { /* fall through */ }
    location.replace(me && me.has_files ? nextUrl() : '/account.html#upload');
  }

  function need(cond, text) { if (!cond) say('err', text); return cond; }

  forms.login.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = $('l-go'), username = $('l-user').value.trim(), password = $('l-pass').value;
    if (!need(username && password, 'Enter your username and password.')) return;
    btn.disabled = true; say('', '');
    try {
      const { r, d } = await post('/api/auth/login', { username, password });
      if (r.ok && d.ok !== false) return arrive();
      explain(r, d, btn);
    } catch (err) { say('err', 'Cannot reach the server. Is it running?'); }
    if (!btn.textContent.startsWith('Wait')) btn.disabled = false;
  });

  forms.register.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = $('r-go'), code = $('r-code').value.trim(), username = $('r-user').value.trim(), password = $('r-pass').value;
    if (!need(code && username && password, 'Fill in all fields.')) return;
    if (!need(password.length >= 8, 'The password needs at least 8 characters.')) return;
    if (!need(password === $('r-pass2').value, 'The two passwords are different.')) return;
    btn.disabled = true; say('', '');
    try {
      const { r, d } = await post('/api/auth/register', { code, username, password });
      if (r.ok && d.ok !== false) {
        const l = await post('/api/auth/login', { username, password });      // register may or may not sign in
        if (l.r.ok) return arrive();
        say('ok', 'Account created. Sign in with your new username.'); show('login'); $('l-user').value = username;
      } else explain(r, d, btn);
    } catch (err) { say('err', 'Cannot reach the server. Is it running?'); }
    if (!btn.textContent.startsWith('Wait')) btn.disabled = false;
  });

  forms.setup.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = $('s-go'), setup_code = $('s-code').value.trim(), username = $('s-user').value.trim(), password = $('s-pass').value;
    if (!need(setup_code && username && password, 'Fill in all fields.')) return;
    if (!need(password.length >= 8, 'The password needs at least 8 characters.')) return;
    if (!need(password === $('s-pass2').value, 'The two passwords are different.')) return;
    btn.disabled = true; say('', '');
    try {
      const { r, d } = await post('/api/auth/setup', { setup_code, username, password, import_existing: $('s-import').checked });
      if (r.ok && d.ok !== false) {
        const l = await post('/api/auth/login', { username, password });
        if (l.r.ok) return arrive();
        say('ok', 'Admin account created. Sign in now.'); show('login'); $('l-user').value = username;
      } else explain(r, d, btn);
    } catch (err) { say('err', 'Cannot reach the server. Is it running?'); }
    if (!btn.textContent.startsWith('Wait')) btn.disabled = false;
  });

  (async function start() {
    let st = {};
    try { st = await (await fetch('/api/auth/state', { cache: 'no-store' })).json(); } catch (e) { say('err', 'Cannot reach the server. Is it running?'); }
    if (st.setup_needed) return show('setup');
    // already signed in (cookie still valid): go straight on
    try {
      const r = await fetch('/api/auth/me', { cache: 'no-store' });
      if (r.ok && (await r.json()).user) return arrive();
    } catch (e) { /* show the form */ }
    show('login');
  })();
})();
