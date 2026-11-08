/* account.js - upload the two Nordnet files, change password, delete profile, admin (invites + users). */
'use strict';
(function () {
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const MAX = 8 * 1024 * 1024;
  const nf = new Intl.NumberFormat('sv-SE');
  let me = null;

  function say(id, kind, text) {
    const m = $(id); m.hidden = !text; m.className = 'msg ' + (kind || 'err'); m.textContent = text || '';
  }
  async function api(url, method, body) {
    const opt = { method: method || 'GET', cache: 'no-store' };
    if (body !== undefined) { opt.headers = { 'Content-Type': 'application/json' }; opt.body = JSON.stringify(body); }
    const r = await fetch(url, opt);
    let d = {}; try { d = await r.json(); } catch (e) { /* empty */ }
    return { r, d };
  }
  const list = (d, k) => Array.isArray(d) ? d : (d && d[k]) || [];
  function when(v) {
    if (v == null || v === '') return '—';
    if (typeof v === 'number') return new Date(v < 1e12 ? v * 1000 : v).toLocaleString('sv-SE').slice(0, 16);
    return String(v).slice(0, 16).replace('T', ' ');
  }

  // ───────── files ─────────
  const KINDS = {
    holdings: { zone: 'drop-holdings', input: 'in-holdings', st: 'st-holdings' },
    ledger: { zone: 'drop-ledger', input: 'in-ledger', st: 'st-ledger' },
  };
  const WHY = {
    invalid: 'This does not look like the right Nordnet file.',
    accno_mismatch: 'This file belongs to a different Nordnet account than the one already on your profile.',
    accno_taken: 'This Nordnet account number is already used by another profile.',
    too_large: 'The file is too large (limit 8 MB).',
  };

  function renderStatus(s) {
    const h = s.holdings, l = s.ledger;
    $('st-holdings').className = 'st'; $('st-ledger').className = 'st';
    $('st-holdings').innerHTML = h ? `<b class="good">✓ ${esc(h.file || 'holdings file')}</b><br><span class="mut">${esc(h.date || '')} · ${nf.format(h.rows || 0)} rows${s.accno ? ' · account ' + esc(s.accno) : ''}</span>` : '<span class="mut">Not added yet</span>';
    $('st-ledger').innerHTML = l ? `<b class="good">✓ Transactions</b><br><span class="mut">${nf.format(l.rows || 0)} rows · ${esc(l.first_date || '?')} to ${esc(l.last_date || '?')}${s.accno ? ' · account ' + esc(s.accno) : ''}</span>` : '<span class="mut">Not added yet</span>';
    $('drop-holdings').classList.toggle('ok', !!h); $('drop-ledger').classList.toggle('ok', !!l);
    const ready = !!(h && l);
    $('open-btn').classList.toggle('disabled', !ready);
    $('open-hint').textContent = ready ? 'Both files are in. You can replace either one at any time.' : 'Add both files to continue. You can also drop a file onto its box.';
  }

  async function status() {
    const { r, d } = await api('/api/account/status');
    if (r.ok) renderStatus(d.status || d);
  }

  const kr = n => (n > 0 ? '+' : n < 0 ? '−' : '') + nf.format(Math.abs(n)) + ' kr';
  function cmpText(c) {
    if (!c) return '';
    if (c.positions_current != null) {
      const bits = [];
      if (c.added_n) bits.push(c.added_n + ' added' + (c.added.length ? ' (' + c.added.join(', ') + (c.added_n > c.added.length ? ', …' : '') + ')' : ''));
      if (c.removed_n) bits.push(c.removed_n + ' removed' + (c.removed.length ? ' (' + c.removed.join(', ') + (c.removed_n > c.removed.length ? ', …' : '') + ')' : ''));
      if (c.qty_changed) bits.push(c.qty_changed + ' with a changed quantity');
      return ' Compared with the running file (' + c.current_date + '): ' + (bits.length ? bits.join(', ') : 'same positions') + '; total value ' + kr(c.value_diff) + '.';
    }
    return ' Compared with the running file: ' + nf.format(c.rows_current) + ' → ' + nf.format(c.rows_upload) + ' rows (' + (c.first_current || '?') + ' to ' + (c.last_current || '?') + ' → ' + (c.first_upload || '?') + ' to ' + (c.last_upload || '?') + ').';
  }

  async function upload(kind, file, confirm) {
    const k = KINDS[kind], st = $(k.st);
    say('up-msg', '', '');
    if (!file) return;
    if (file.size > MAX) { st.className = 'st err'; st.textContent = WHY.too_large; return; }
    st.className = 'st'; st.innerHTML = '<span class="mut">Checking ' + esc(file.name) + '…</span>';
    try {
      const r = await fetch('/api/upload/' + kind, { method: 'POST', body: file, headers: Object.assign({ 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name) }, confirm ? { 'X-Confirm': 'replace' } : {}) });
      let d = {}; try { d = await r.json(); } catch (e) { /* empty */ }
      if (r.ok && d.ok !== false) {
        const bits = [d.accno && 'account ' + d.accno, d.rows != null && nf.format(d.rows) + ' rows', d.first_date && d.last_date && d.first_date + ' to ' + d.last_date, d.date].filter(Boolean).join(' · ');
        say('up-msg', d.warning ? 'info' : 'ok', (kind === 'holdings' ? 'Holdings' : 'Transactions') + ' file accepted' + (bits ? ': ' + bits : '') + '.' + (d.note ? ' ' + d.note : '') + cmpText(d.compare));
        await status();
      } else if (d.error === 'confirm_needed') {
        await status().catch(() => {});
        st.className = 'st err'; st.textContent = 'Not replaced yet: this file is smaller than the running one.';
        say('up-msg', 'info', (d.message || '') + ' ');
        const b = document.createElement('button'); b.type = 'button'; b.className = 'abtn small'; b.textContent = 'Replace anyway';
        b.addEventListener('click', () => upload(kind, file, true)); $('up-msg').append(b);
      } else {
        await status().catch(() => {});                // keep the other file's status current, then show why this one failed
        st.className = 'st err'; st.textContent = (WHY[d.error] || 'The file was not accepted.') + (d.message ? ' ' + d.message : '');
      }
    } catch (e) { st.className = 'st err'; st.textContent = 'Upload failed. Is the server running?'; }
  }

  function bindFiles() {
    Object.entries(KINDS).forEach(([kind, k]) => {
      const zone = $(k.zone), input = $(k.input);
      zone.querySelector('[data-pick]').addEventListener('click', () => input.click());
      input.addEventListener('change', () => { const f = input.files[0]; input.value = ''; upload(kind, f); });
      ['dragenter', 'dragover'].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add('over'); }));
      ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove('over'); }));
      zone.addEventListener('drop', e => upload(kind, e.dataTransfer.files[0]));
    });
    // a file dropped beside the boxes must not make the browser open it
    window.addEventListener('dragover', e => e.preventDefault());
    window.addEventListener('drop', e => e.preventDefault());
  }

  // ───────── password + delete ─────────
  function bindAccount() {
    $('f-pw').addEventListener('submit', async e => {
      e.preventDefault();
      const o = $('pw-old').value, n = $('pw-new').value;
      if (!o || !n) return say('pw-msg', 'err', 'Fill in the current and the new password.');
      if (n.length < 8) return say('pw-msg', 'err', 'The new password needs at least 8 characters.');
      if (n !== $('pw-new2').value) return say('pw-msg', 'err', 'The two new passwords are different.');
      const { r, d } = await api('/api/auth/password', 'POST', { old: o, new: n });
      if (r.ok && d.ok !== false) { $('f-pw').reset(); say('pw-msg', 'ok', 'Password changed.'); }
      else say('pw-msg', 'err', d.message || (r.status === 429 ? 'Too many attempts. Wait a minute.' : 'The current password is wrong or the new one is not allowed.'));
    });
    // the admin account itself is kept (only files are removed); everyone else loses the whole account
    const admin = me && me.role === 'admin';
    if (admin) {
      $('del-title').textContent = 'Delete my files';
      $('del-hint').textContent = 'Removes your uploaded Nordnet files and your saved baseline from the server. Your admin account stays, so you can upload again. This cannot be undone.';
      $('del-btn').textContent = 'Delete my files';
    }
    $('f-del').addEventListener('submit', async e => {
      e.preventDefault();
      const p = $('del-pass').value;
      if (!p) return say('del-msg', 'err', 'Enter your password to confirm.');
      if (!confirm(admin ? 'Delete all your uploaded files? Your account stays. This cannot be undone.' : 'Delete your profile and all your uploaded files? This cannot be undone.')) return;
      const { r, d } = await api('/api/account/delete', 'POST', { password: p });
      if (!(r.ok && d.ok !== false)) return say('del-msg', 'err', d.message || (r.status === 429 ? 'Too many attempts. Wait a minute.' : 'Wrong password.'));
      if (admin) { $('f-del').reset(); say('del-msg', 'ok', 'Your files were deleted.'); status(); }
      else location.replace('/login.html');
    });
  }

  // ───────── admin ─────────
  function table(id, head, rows, empty) {
    $(id).innerHTML = `<thead><tr>${head.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${
      rows.length ? rows.join('') : `<tr><td colspan="${head.length}" style="color:var(--text-dim);text-align:center;padding:12px">${empty}</td></tr>`}</tbody>`;
  }

  async function loadAdmin() {
    const [inv, usr] = await Promise.all([api('/api/admin/invites'), api('/api/admin/users')]);
    const now = Date.now();
    table('tb-inv', ['Code', 'Created', 'Expires', 'Status', ''], list(inv.d, 'invites').map(i => {
      const open = i.status === 'open';
      const state = i.status === 'used' ? `<span class="tag good">used by ${esc(i.used_by || '?')}</span>` : i.status === 'expired' ? '<span class="tag">expired</span>' : '<span class="tag gold">open</span>';
      const code = open ? (i.code ? `<code>${esc(i.code)}</code>` : '<span class="mut" title="Created before codes were kept. Revoke it and create a new one.">not stored</span>') : '<span class="mut">—</span>';
      const acts = (open && i.code ? '<button type="button" class="abtn small" data-copy>Copy</button> ' : '') + `<button type="button" class="abtn small danger" data-inv-del>${open ? 'Revoke' : 'Remove'}</button>`;
      return `<tr data-inv="${esc(i.id)}" data-code="${esc(i.code || '')}"><td>${code}</td><td>${esc(when(i.created))}</td><td>${esc(when(i.expires))}</td><td>${state}</td><td>${acts}</td></tr>`;
    }), 'No invites yet.');
    table('tb-users', ['Username', 'Role', 'Account', 'Last login', 'Files', ''], list(usr.d, 'users').map(u => {
      const self = me && u.username === me.username;
      return `<tr data-uid="${esc(u.uid)}"><td><b>${esc(u.username)}</b>${self ? ' <span class="tag">you</span>' : ''}</td><td>${esc(u.role)}</td><td>${esc(u.accno || '—')}</td>
        <td>${esc(when(u.last_login))}</td><td>${u.has_files ? '<span class="tag good">yes</span>' : '<span class="tag">no</span>'}</td>
        <td>${self ? '' : `<span class="rst"><button type="button" class="abtn small" data-reset>Reset password</button></span> <button type="button" class="abtn small danger" data-del>Delete</button>`}</td></tr>`;
    }), 'No users.');
  }

  function bindAdmin() {
    $('inv-new').addEventListener('click', async () => {
      say('ad-msg', '', '');
      const { r, d } = await api('/api/admin/invites', 'POST', {});
      if (!r.ok || !d.code) return say('ad-msg', 'err', d.message || 'Could not create an invite.');
      $('inv-val').textContent = d.code; $('inv-exp').textContent = 'expires ' + when(d.expires); $('inv-code').hidden = false;
      loadAdmin();
    });
    $('inv-copy').addEventListener('click', async () => {
      const t = $('inv-val').textContent;
      try { await navigator.clipboard.writeText(t); } catch (e) {
        const s = document.createRange(); s.selectNodeContents($('inv-val')); const g = getSelection(); g.removeAllRanges(); g.addRange(s);
      }
      $('inv-copy').textContent = 'Copied';
      setTimeout(() => { $('inv-copy').textContent = 'Copy'; }, 1500);
    });
    $('tb-inv').addEventListener('click', async e => {
      const tr = e.target.closest('tr[data-inv]'); if (!tr) return;
      if (e.target.closest('[data-copy]')) {
        const t = tr.dataset.code;
        try { await navigator.clipboard.writeText(t); } catch (err) { const s = document.createRange(); s.selectNodeContents(tr.querySelector('code')); const g = getSelection(); g.removeAllRanges(); g.addRange(s); }
        e.target.textContent = 'Copied'; setTimeout(() => { e.target.textContent = 'Copy'; }, 1500);
      } else if (e.target.closest('[data-inv-del]')) {
        const open = !!tr.dataset.code || /open/.test(tr.innerText);
        if (open && !confirm('Revoke this invite code? Anyone holding it will no longer be able to register.')) return;
        const { r, d } = await api('/api/admin/invites/delete', 'POST', { id: tr.dataset.inv });
        say('ad-msg', r.ok && d.ok !== false ? 'ok' : 'err', r.ok && d.ok !== false ? 'Invite removed.' : (d.message || 'Could not remove the invite.'));
        loadAdmin();
      }
    });
    $('tb-users').addEventListener('click', async e => {
      const tr = e.target.closest('tr[data-uid]'); if (!tr) return;
      const uid = tr.dataset.uid, name = tr.querySelector('b').textContent;
      if (e.target.closest('[data-reset]')) {
        tr.querySelector('.rst').innerHTML = '<input type="password" placeholder="new password" autocomplete="new-password"> <button type="button" class="abtn small primary" data-save>Save</button>';
        tr.querySelector('.rst input').focus();
      } else if (e.target.closest('[data-save]')) {
        const v = tr.querySelector('.rst input').value;
        if (v.length < 8) return say('ad-msg', 'err', 'The new password needs at least 8 characters.');
        const { r, d } = await api('/api/admin/users/reset', 'POST', { uid, new: v });
        say('ad-msg', r.ok && d.ok !== false ? 'ok' : 'err', r.ok && d.ok !== false ? 'Password for ' + name + ' was reset.' : (d.message || 'Could not reset the password.'));
        loadAdmin();
      } else if (e.target.closest('[data-del]')) {
        if (!confirm('Delete the user "' + name + '" and all their files? This cannot be undone.')) return;
        const { r, d } = await api('/api/admin/users/delete', 'POST', { uid });
        say('ad-msg', r.ok && d.ok !== false ? 'ok' : 'err', r.ok && d.ok !== false ? 'User ' + name + ' was deleted.' : (d.message || 'Could not delete the user.'));
        loadAdmin();
      }
    });
  }

  // ───────── start ─────────
  (window.TV ? TV.ready : Promise.resolve(null)).then(async u => {
    me = u;
    if (!me) { $('who').textContent = 'Could not reach the server.'; return; }
    $('who').textContent = `Signed in as ${me.username}${me.accno ? ' · Nordnet account ' + me.accno : ''}${me.role === 'admin' ? ' · admin' : ''}`;
    bindFiles(); bindAccount();
    if (me.role === 'admin') { $('admin').hidden = false; bindAdmin(); loadAdmin(); }
    await status();
    if (location.hash) { const t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
  });
})();
