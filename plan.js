/* ============================================================
   PLAN & ADVICE TAB — plan.js  (analytics.html #tab-advice)
   One strategy per category (strategy.py / advisor.py, served by /api/advice), the evidence behind it
   (/api/plan/evidence, a 10-year test of your own holdings per category) and your plan settings (/api/plan/settings).
   Loaded after analytics.js and uses its helpers ($, esc, fmt, pct, sgn, cls, mkChart, table, getJSON, S, loadAdvice).
   Layout: verdict and a few tiles first, then where the money went and how you invest, this month, the categories, every
   holding, the evidence, the transition. Tables never scroll sideways (class 'stack', responsive.css); the reason behind an
   action sits behind an (i) button. Colours are read from the CSS tokens at render time; charts redraw on 'tvthemechange'.
   ============================================================ */
'use strict';
const Plan = (() => {
  const P = { built: false, ev: null, evTries: 0, evTimer: 0, settings: null, cats: [], open: new Set(), saving: false };
  const tok = n => (window.TVTheme ? TVTheme.css(n) : getComputedStyle(document.documentElement).getPropertyValue(n).trim()) || '#888';
  const RULE_TXT = { size_cap: 'size cap', trend_exit: 'trend exit', regime_exit: 'regime exit', pullback: 'pullback in an uptrend', deposit_plan: 'deposit plan',
    consolidate: 'tiny position', review: 'review', hold_half: 'hold half', near_entry: 'close to an entry', buyback: 'buy back', core: 'index fund', fixed: 'defensive' };
  const kr = n => `<span class="pv nw">${fmt(n)} kr</span>`;
  const krAbs = n => kr(Math.abs(n));
  const lab = s => String(s).replace(/"/g, '&quot;');
  const lc = s => /^[A-Z]{2}/.test(s) ? s : s.charAt(0).toLowerCase() + s.slice(1);      // 'AI and ...' keeps its capitals
  let whyN = 0;
  const whyBtn = (text, name) => { const id = 'plw' + (++whyN); return [`<button type="button" class="why-btn" aria-expanded="false" aria-controls="${id}" aria-label="Why: ${lab(name)}" title="Why">i</button>`, id, text]; };
  const whyRow = (id, text, span) => `<tr class="why-row" id="${id}" hidden><td colspan="${span}">${esc(text)}</td></tr>`;

  function skeleton() {
    $('plan-root').innerHTML = `
      <div class="pl-head">
        <div><span class="lbl">Profile (targets)</span><div class="chips" id="pl-profile" role="radiogroup" aria-label="Profile">
          <button class="chip" role="radio" data-p="conservative">Conservative</button><button class="chip" role="radio" data-p="balanced">Balanced</button><button class="chip" role="radio" data-p="aggressive">Aggressive</button></div></div>
        <span class="pl-saved" id="pl-saved" role="status" aria-live="polite"></span>
      </div>
      <p class="hint pl-explain">The profile sets the target mix (index funds 60 / 50 / 40%, AI and chips at most 10 / 15 / 22%) and how low the RSI must be before new money goes into a stock (35 / 40 / 45). A click applies it at once and saves it for your account, so the Portfolio page, this tab, the assistant and every device use the same plan.</p>
      <p class="hint" id="pl-status"></p>

      <section class="panel pl-verdict"><h3>The short verdict</h3><div id="pl-verdict"></div></section>
      <section id="pl-kpis" class="kpi-row"></section>

      <section class="grid g2">
        <div class="panel"><h3>Where the money was lost</h3><div class="cv tall"><canvas id="pl-life" role="img" aria-label="Bars of the lifetime result per category"></canvas></div>
          <p class="hint" id="pl-life-note">Unrealised plus realised result of every holding ever owned in the category (realised is already after fees). Dividends are not split by category.</p></div>
        <div class="panel"><h3>How well you follow each popular strategy</h3><div class="cv tall"><canvas id="pl-fit" role="img" aria-label="Bars of fit from 0 to 10 to five popular strategies"></canvas></div>
          <p class="hint">A rating from 0 to 10, from the measures below.</p></div>
      </section>
      <section class="panel"><h3>The measures behind those ratings</h3><div class="tbl-wrap"><table id="pl-fit-t"></table></div></section>

      <h2 class="sec">This month</h2>
      <section class="grid g2">
        <div class="panel"><h3 id="pl-dep-title">Each deposit goes to</h3><div class="tbl-wrap"><table id="pl-deposit"></table></div><p class="hint" id="pl-dep-note"></p></div>
        <div class="panel"><h3>Sell this month</h3><div class="tbl-wrap scroll"><table id="pl-sells"></table></div><p class="hint" id="pl-sell-note"></p></div>
      </section>

      <h2 class="sec">One strategy per category</h2>
      <section class="panel"><div class="tbl-wrap"><table id="pl-cats"></table></div></section>

      <h2 class="sec">Holdings by category</h2>
      <p class="hint">Click a category to open it. "Weekly trend" is the last weekly close against the simple 200-day average, SMA(200). Tap (i) for the reason behind an action. If a holding sits in the wrong group, choose another category; the plan is recalculated.</p>
      <section class="panel"><div class="tbl-wrap scroll tall"><table id="pl-hold"></table></div></section>

      <h2 class="sec">The evidence: which rule worked for which category</h2>
      <p class="hint" id="pl-ev-status"></p>
      <section class="grid g2">
        <div class="panel"><h3>Yearly return (CAGR)</h3><div class="cv tall"><canvas id="pl-ev-cagr" role="img" aria-label="Yearly return per category, buy and hold against the rule used"></canvas></div></div>
        <div class="panel"><h3>Worst fall from a peak</h3><div class="cv tall"><canvas id="pl-ev-dd" role="img" aria-label="Worst fall per category, buy and hold against the rule used"></canvas></div></div>
      </section>
      <div class="pl-key"><span><i style="background:var(--text-dim)"></i>Buy and hold</span><span><i style="background:var(--s1)"></i>Rule used for the category</span></div>
      <ul class="pl-findings" id="pl-ev-find"></ul>
      <details class="panel"><summary>Every rule in every category</summary><div class="tbl-wrap scroll tall"><table id="pl-ev-all"></table></div></details>

      <h2 class="sec">The transition</h2>
      <section class="grid g2">
        <div class="panel"><h3 id="pl-drift-title">Share over 36 months</h3><div class="cv tall"><canvas id="pl-drift" role="img" aria-label="Lines of a category's share under three paths"></canvas></div>
          <div class="pl-key"><span><i style="background:var(--s1)"></i>The plan</span><span><i style="background:var(--s3)"></i>Only new money redirected</span><span><i style="background:var(--s2)"></i>Invest as now</span><span><i class="dash"></i>Target</span></div>
          <p class="hint" id="pl-drift-note"></p></div>
        <div class="panel"><h3>Stress test: result in % under three scenarios</h3><div class="cv tall"><canvas id="pl-stress" role="img" aria-label="Bars of scenario results for today's mix and the target mix"></canvas></div>
          <div class="pl-key"><span><i style="background:var(--text-dim)"></i>Today's mix</span><span><i style="background:var(--s1)"></i>Target mix</span></div>
          <p class="hint" id="pl-stress-note"></p></div>
      </section>

      <section class="panel method"><h3>Rules that apply to every category</h3><ul id="pl-rules"></ul></section>
      <details class="panel method"><summary>What "200-day average" and "weekly close" mean, and how to read this tab</summary><ul id="pl-method"></ul></details>`;
    $('pl-profile').addEventListener('click', e => {
      const b = e.target.closest('.chip'); if (!b || b.classList.contains('active')) return;
      document.querySelectorAll('#pl-profile .chip').forEach(x => { x.classList.toggle('active', x === b); x.setAttribute('aria-checked', String(x === b)); });
      save({ profile: b.dataset.p });                                  // saved for the account, then the plan is recalculated
    });
    const root = $('plan-root');
    root.addEventListener('click', e => {
      const w = e.target.closest('.why-btn');
      if (w) {
        const row = document.getElementById(w.getAttribute('aria-controls'));
        if (row) { row.hidden = !row.hidden; w.setAttribute('aria-expanded', String(!row.hidden)); }
        return;
      }
      const g = e.target.closest('#pl-hold tr.grp');
      if (g && !e.target.closest('select, button')) { const k = g.dataset.k; P.open.has(k) ? P.open.delete(k) : P.open.add(k); holdings(); }
    });
    $('pl-hold').addEventListener('keydown', e => {
      const g = e.target.closest('tr.grp'); if (g && e.target === g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); g.click(); }
    });
    $('pl-hold').addEventListener('change', e => {
      const s = e.target.closest('select[data-isin]'); if (!s) return;
      const ov = Object.assign({}, (P.settings && P.settings.overrides) || {});
      if (s.value) ov[s.dataset.isin] = s.value; else delete ov[s.dataset.isin];
      save({ overrides: ov });
    });
    window.addEventListener('tvthemechange', () => { if (S.tab === 'advice' && S.advice) { charts(); evidence(); } });
    P.built = true;
  }

  // ───────── settings ─────────
  async function loadSettings() {
    try {
      const r = await getJSON('/api/plan/settings');
      P.settings = r.settings; P.cats = r.categories;
    } catch (e) { /* the defaults stay */ }
  }
  // saves the profile or a category override for the account (server, data/profiles/<id>/plan_settings.json), then recalculates
  async function save(body) {
    if (P.saving) return;
    const msg = $('pl-saved'); msg.classList.remove('err'); msg.textContent = 'Saving…'; P.saving = true;
    try {
      const r = await fetch('/api/plan/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json();
      if (!r.ok || !j.ok) throw new Error(j.message || j.error || ('HTTP ' + r.status));
      P.settings = j.settings;
      msg.textContent = 'Saved for your account. Recalculating…';
      P.ev = null;
      await loadAdvice();
      msg.textContent = body.profile ? `${body.profile[0].toUpperCase() + body.profile.slice(1)} profile saved for your account.` : 'Category saved for your account.';
    } catch (e) {
      msg.classList.add('err'); msg.textContent = 'Not saved: ' + e.message;
    }
    P.saving = false;
  }

  // ───────── main render ─────────
  function render() {
    if (!P.built) skeleton();
    if (!P.settings) loadSettings();
    const A = S.advice;
    const prof = (A && A.summary.profile) || (P.settings && P.settings.profile) || 'balanced';
    document.querySelectorAll('#pl-profile .chip').forEach(b => { b.classList.toggle('active', b.dataset.p === prof); b.setAttribute('aria-checked', String(b.dataset.p === prof)); });
    if (!A) { $('pl-status').textContent = 'Loading price history from Yahoo for the first time can take up to a minute…'; loadAdvice(); return; }
    if (!A.plan) { $('pl-status').textContent = 'The server has not been updated to the per-category plan yet.'; return; }
    const L = A.plan, Y = A.summary;
    $('pl-status').textContent = `${Y.profile_about[0].toUpperCase() + Y.profile_about.slice(1)}. Valued ${A.asof.replace('T', ' ')}; weights are % of the whole account, cash included.${A.partial ? ' Some price history is still loading; this refreshes by itself.' : ''}`;
    whyN = 0;
    verdict(A); kpis(A); fitTable(L); month(A); catTable(L); holdings(); notes(L); charts(); evidence(true);
    if (A.partial) setTimeout(() => { if (S.tab === 'advice') loadAdvice(); }, 20000);
  }

  // The verdict in a few sentences, from your own numbers (the same values as the tiles at the top of the page)
  function verdict(A) {
    const D = S.data, L = A.plan;
    if (!D) { $('pl-verdict').innerHTML = ''; return; }
    const o = D.insights.overview, life = L.lifetime, cats = Object.fromEntries(L.categories.map(c => [c.key, c]));
    const res = o.all_time_pnl, out = [];
    const keys = Object.keys(life).filter(k => life[k].n || life[k].life).sort((a, b) => life[a].life - life[b].life);
    out.push(res < 0
      ? `The account is ${krAbs(res)} below the ${kr(o.net_deposits)} you deposited (${pct(o.all_time_pnl_pct, 1)}).`
      : `The account is ${kr(res)} above the ${kr(o.net_deposits)} you deposited (+${pct(o.all_time_pnl_pct, 1)}).`);
    const w = keys[0];
    if (w && life[w].life < 0 && res < 0 && -life[w].life >= 0.5 * -res) {
      const rest = res - life[w].life;
      out.push(`<b>One bet:</b> ${pct(cats[w].pct, 0)} of the money is in ${esc(lc(cats[w].label))} (target ${pct(cats[w].target, 0)}). It has lost ${krAbs(life[w].life)} of the ${krAbs(res)} total; everything else together is ${rest >= 0 ? '+' : '−'}${krAbs(rest)}, dividends included.`);
    } else if (w && life[w].life < 0) {
      out.push(`The largest loss is in ${esc(lc(cats[w].label))}: ${krAbs(life[w].life)}.`);
    }
    const fees = D.insights.costs.broker_total, gross = (D.insights.sell_quality || {}).realized_before_fees;
    const months = Math.max(1, Math.round((new Date(o.last_date) - new Date(o.first_date)) / (30.44 * 864e5)));
    if (gross != null && fees > Math.max(gross, 0)) {
      out.push(`<b>One habit:</b> ${fmt(o.trades)} trades in ${months} months cost ${kr(fees)} in fees, more than the ${kr(gross)} you made from selling before fees.`);
    } else if (fees > 0.02 * o.net_deposits) {
      out.push(`<b>Costs:</b> ${fmt(o.trades)} trades in ${months} months cost ${kr(fees)} in fees (${pct(fees / o.net_deposits * 100, 1)} of your deposits).`);
    }
    const ser = D.insights.deposit_behavior && D.insights.deposit_behavior.series;
    if (ser && ser.length > 30) {
      let b = 0;
      ser.forEach((x, i) => { if (x.value - x.net_deposited > ser[b].value - ser[b].net_deposited) b = i; });
      const pk = ser[b], gain = pk.value - pk.net_deposited, after = o.net_deposits - pk.net_deposited;
      const since = (o.total_value - o.net_deposits) - gain;
      if (gain > 0 && after > 0.15 * o.net_deposits && since < 0) {
        out.push(`<b>One timing problem:</b> ${kr(after)} (${pct(after / o.net_deposits * 100, 0)} of all deposits) went in after ${new Date(pk.date + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}, when the account was ${kr(gain)} above what you had put in. Since then it has lost ${krAbs(since)} against your deposits.`);
      }
    }
    const good = keys.filter(k => life[k].life > 0 && life[k].n).map(k => esc(lc(cats[k].label)));
    if (good.length) out.push(`<b>What worked:</b> ${good.join(', ')} ${good.length > 1 ? 'are' : 'is'} in profit.`);
    const eff = A.summary.portfolio && A.summary.portfolio.eff_n;
    if (eff) out.push(`The ${A.summary.positions} positions behave like about ${eff.toFixed(1)} independent bets.`);
    $('pl-verdict').innerHTML = `<p>${out.join(' ')}</p>`;
  }

  function kpis(A) {
    const L = A.plan, D = S.data, c = Object.fromEntries(L.categories.map(x => [x.key, x]));
    const worst = L.categories.filter(x => x.key !== 'core' && x.key !== 'cash').sort((a, b) => b.gap - a.gap)[0];
    const o = D && D.insights.overview, T = L.transition;
    $('pl-kpis').innerHTML =
      (o ? kpi('Result on deposits', `${o.all_time_pnl < 0 ? '−' : '+'}${krAbs(o.all_time_pnl)}`, `account ${fmt(o.total_value)} kr · deposited ${fmt(o.net_deposits)} kr`, cls(o.all_time_pnl)) : '') +
      kpi('Index funds', pct(c.core.pct, 0), `target ${pct(c.core.target, 0)}`, c.core.status === 'under' ? 'neg' : '') +
      kpi(esc(worst.label), pct(worst.pct, 0), `target ${pct(worst.target, 0)}${worst.status === 'over' && T.months_to_band != null ? ` · on target in ~${T.months_to_band} months` : ''}`, worst.status === 'over' ? 'neg' : '') +
      kpi('Stock money in an uptrend', pct(L.up_pct, 0), 'weekly close above SMA(200)', L.up_pct < 40 ? 'neg' : L.up_pct >= 60 ? 'pos' : '') +
      kpi('Trades, last 30 days', fmt(L.trading.trades_30d), `budget ${L.trading.max_trades} · fees ${fmt(L.trading.fees_30d)} kr`, L.trading.trades_30d > L.trading.max_trades ? 'neg' : 'pos');
  }

  function month(A) {
    const L = A.plan, rows = Object.entries(A.assets).map(([isin, v]) => ({ isin, ...v }));
    const dep = L.settings.deposit;
    // shares of every deposit: true for any amount (kr only as a fallback for an older server answer)
    const pc = (p, amt) => `<span class="nw">${p != null ? p + '%' : kr(amt)}</span>`;
    let h = '<thead><tr><th>Goes to</th><th>Share</th></tr></thead><tbody>';
    L.deposit_plan.forEach(d => {
      h += `<tr><td data-label=""><b>${esc(d.label)}</b></td><td data-label="Share">${pc(d.pct, d.amount)}</td></tr>`;
      (d.where || []).forEach(w => { h += `<tr class="sub"><td data-label=""><span class="pl-small">→ ${esc(w.name)}</span></td><td data-label=""><span class="pl-small">${pc(w.pct, w.amount)}</span></td></tr>`; });
      if (d.cat === 'cash') h += `<tr class="sub"><td data-label="" colspan="2"><span class="pl-small">→ stays as cash on the account</span></td></tr>`;
    });
    if (!L.deposit_plan.length) h += `<tr><td colspan="2" class="pl-empty">${dep ? 'Nothing is under its target.' : 'No monthly deposit is set in the plan.'}</td></tr>`;
    const el = $('pl-deposit'); el.className = 'stack'; el.innerHTML = h + '</tbody>';
    $('pl-dep-note').textContent = 'Share of every deposit, whatever the amount: split over the groups furthest under their target. A stock group gets money only when one of its stocks has an entry signal; otherwise its share waits in the index funds. Orders under 2 500 kr are merged.';

    const sells = rows.filter(r => r.action === 'TRIM' && r.when !== 'later').sort((a, b) => a.amount - b.amount);
    let s = '<thead><tr><th>Holding</th><th>Amount</th><th>When</th><th></th></tr></thead><tbody>';
    sells.forEach((r, i) => {
      const rsi = r.metrics && r.metrics.rsi != null ? Math.round(r.metrics.rsi) : null;
      const okNow = rsi == null || rsi > 45;
      const [btn, id, text] = whyBtn(r.reasons.join(' '), r.name);
      s += `<tr><td data-label="">${esc(r.name)}<br><span class="pl-small">${esc(RULE_TXT[r.rule] || r.rule || '')}</span></td><td data-label="Amount">${kr(r.amount)}</td>
        <td data-label="When"><span class="pill ${okNow ? 'ok' : 'wait'}" title="Planned sales go on a day the RSI(14) is above 45 (into strength), at the latest within 4 weeks">${rsi == null ? 'any day' : okNow ? `RSI ${rsi}: OK today` : `RSI ${rsi}: wait for a bounce`}</span></td>
        <td data-label="" class="why-cell">${btn}</td></tr>${whyRow(id, text, 4)}`;
    });
    if (!sells.length) s += '<tr><td colspan="4" class="pl-empty">No sale is due this month.</td></tr>';
    const se = $('pl-sells'); se.className = 'stack'; se.innerHTML = s + '</tbody>';
    const tiny = rows.filter(r => r.action === 'CONSOLIDATE');
    const tot = sells.reduce((x, r) => x + r.amount, 0);
    $('pl-sell-note').innerHTML = `${sells.length} sales, ${kr(tot)}.` + (L.queued ? ` ${L.queued} more (${kr(L.queued_kr)}) are queued for the next months by the ${fmt(L.settings.reduce)} kr monthly reduction budget.` : '') +
      (tiny.length ? ` ${tiny.length} tiny positions (${kr(tiny.reduce((x, r) => x + r.amount, 0))}) can be sold or topped up.` : '') + ' Buy ideas are on the Portfolio page.';
  }

  function catTable(L) {
    const st = { over: 'over target', under: 'under target', ok: 'on target' };
    const max = Math.max(60, ...L.categories.map(c => Math.max(c.pct, c.target)));
    let h = '<thead><tr><th>Category and strategy</th><th>Now / target</th><th>Status</th><th>Above SMA(200)</th></tr></thead><tbody>';
    L.categories.forEach(c => {
      h += `<tr><td data-label="">${esc(c.label)} <span class="pl-small">· ${c.n} holdings · ${kr(c.kr)}</span><br><span class="pl-strat">${esc(c.strategy)}</span></td>
        <td data-label="Now / target"><span class="bar ${c.status}" aria-hidden="true"><i style="width:${c.pct / max * 100}%"></i><b style="left:${c.target / max * 100}%"></b></span><span class="nw">${pct(c.pct, 1)} / ${pct(c.target, 0)}</span></td>
        <td data-label="Status"><span class="pill ${c.status}">${st[c.status]} ${c.gap > 0 ? '+' : ''}${c.gap.toFixed(0)} pts</span></td>
        <td data-label="Above SMA(200)" title="holdings whose last weekly close was above their 200-day average"><span class="nw">${c.n_trend ? `${c.n_up} of ${c.n_trend}` : '—'}</span></td></tr>`;
    });
    const el = $('pl-cats'); el.className = 'stack pl-cats'; el.innerHTML = h + '</tbody>';
  }

  function holdings() {
    const A = S.advice; if (!A || !A.plan) return;
    const ov = (P.settings && P.settings.overrides) || {};
    const opts = (P.cats.length ? P.cats : A.plan.categories.filter(c => c.key !== 'cash').map(c => ({ key: c.key, label: c.label })));
    const by = {};
    Object.entries(A.assets).filter(([, v]) => !v.closed).forEach(([isin, v]) => (by[v.category] = by[v.category] || []).push({ isin, ...v }));
    const N = 9;
    let html = '<thead><tr><th>Holding</th><th>Value</th><th>% of account</th><th>vs your cost</th><th>Weekly trend</th><th>vs SMA(200)</th><th>RSI 14</th><th>Action</th><th>Category</th></tr></thead><tbody>';
    A.plan.categories.forEach(c => {
      const xs = (by[c.key] || []).sort((a, b) => b.weight - a.weight);
      if (!xs.length) return;
      const open = P.open.has(c.key);
      html += `<tr class="grp" data-k="${c.key}" tabindex="0" aria-expanded="${open}"><td colspan="${N}"><span class="chev" aria-hidden="true">${open ? '▾' : '▸'}</span>${esc(c.label)} <span class="pl-small">${xs.length} holdings · ${pct(c.pct, 1)} of the account · target ${pct(c.target, 0)}</span> <span class="pill ${c.status}">${c.status === 'over' ? 'over target' : c.status === 'under' ? 'under target' : 'on target'}</span></td></tr>`;
      if (!open) return;
      xs.forEach(v => {
        const m = v.metrics || {}, a = (S.data && S.data.assets || []).find(x => x.isin === v.isin) || {};
        const wk = m.wk_up == null ? '<span class="pill na">no data</span>' : `<span class="pill ${m.wk_up ? 'up' : 'down'}" title="${m.wk_up ? 'Above' : 'Below'} SMA(200) at ${m.wk_weeks} weekly close${m.wk_weeks > 1 ? 's' : ''} in a row (last ${m.wk_date})" aria-label="${m.wk_up ? 'above' : 'below'} SMA(200) for ${m.wk_weeks} week${m.wk_weeks > 1 ? 's' : ''}">${m.wk_up ? '▲' : '▼'} ${m.wk_weeks} wk</span>`;
        const sel = `<select data-isin="${v.isin}" aria-label="Category of ${lab(v.name)}"><option value="">auto</option>${opts.map(o => `<option value="${o.key}"${ov[v.isin] === o.key ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
        const amt = v.amount ? ` <span class="adv-amt pv">${v.action === 'ADD' || v.action === 'BUYBACK' ? '+' : '−'}${fmt(v.amount)}</span>` : '';
        const [btn, id, text] = whyBtn(v.reasons.join(' '), v.name);
        html += `<tr class="${ov[v.isin] ? 'ovr' : ''}"><td data-label="">${esc(v.name)}${v.keep ? ' <span class="tag" title="kept as the hold half of this category">hold half</span>' : ''}</td>
          <td data-label="Value">${kr(a.value)}</td><td data-label="% of account">${pct(v.weight, 1)}</td>
          <td data-label="vs your cost" class="${cls(a.unrealized_pct)}">${a.unrealized_pct == null ? '—' : pct(a.unrealized_pct, 0)}</td><td data-label="Weekly trend">${wk}</td>
          <td data-label="vs SMA(200)">${m.wk_dist == null ? '—' : pct(m.wk_dist * 100, 0)}</td><td data-label="RSI 14">${m.rsi == null ? '—' : Math.round(m.rsi)}</td>
          <td data-label="Action" class="span2"><span class="nw"><span class="adv ${v.action}">${ADV_LABEL[v.action] || v.action}</span>${amt}${v.when === 'later' ? ' <span class="tag">queued</span>' : ''} ${btn}</span></td>
          <td data-label="Category" class="span2">${sel}</td></tr>${whyRow(id, text, N)}`;
      });
    });
    const el = $('pl-hold'); el.className = 'stack wide'; el.innerHTML = html + '</tbody>';
  }

  function fitTable(L) {
    let h = '<thead><tr><th>Strategy</th><th>Your account</th><th>The rule of the strategy</th></tr></thead><tbody>';
    L.fit.forEach(f => { h += `<tr><td data-label=""><b>${esc(f.label)}</b> <span class="pl-small nw">${f.score} of 10</span></td><td data-label="Your account" class="txt">${esc(f.measure)}</td><td data-label="The rule" class="txt">${esc(f.rule)}</td></tr>`; });
    const el = $('pl-fit-t'); el.className = 'stack pl-text'; el.innerHTML = h + '</tbody>';
  }

  function notes(L) {
    const s = L.stress.shocks, keys = Object.keys(s);
    $('pl-stress-note').textContent = 'Shocks used (AI chain / index funds / other stocks / gold, bonds, cash): ' + keys.map(k => `${k}: ${s[k].ai} / ${s[k].core} / ${s[k]._other} / ${s[k].defensive}`).join(' · ') + '. Illustrations, not forecasts.';
    const T = L.transition;
    $('pl-drift-note').textContent = T.over.length
      ? `Prices held flat, so only the mix changes: ${fmt(L.settings.deposit)} kr deposited a month, at most ${fmt(L.settings.reduce)} kr a month reduced in the over-target group. ` + (T.months_to_band != null ? `Back within 5 points of target after about ${T.months_to_band} months.` : 'Not back within 5 points of target in three years: raise the deposit or the reduction.')
      : 'No group is more than 5 points over its target; the line shows the index-fund share.';
    $('pl-rules').innerHTML = [
      '<b>Deposits:</b> one automatic deposit on a fixed date each month. A lump sum larger than three months of deposits is spread over three months. New money goes to the group furthest under its target.',
      `<b>Size:</b> one stock at most 4% of the account and at most 20 single stocks. Orders of at least 2 500 kr. At most ${L.trading.max_trades} trades a month, no same-day buy and sell of one stock, fees under ${fmt(L.trading.fee_budget_year)} kr a year (0.5%).`,
      '<b>Sales:</b> a planned sale goes on a day the RSI(14) is above 45 (into strength, not into panic), at the latest within 4 weeks. Profits are taken by the size and category caps, not by RSI: RSI above 75 was followed by more gains in the test.',
      '<b>Opportunity cash:</b> kept for a pullback in an uptrend (weekly close above SMA(200), RSI(14) below 35) in a group under its target, at most two such trades open at once, and for the panic ladder. It is refilled from deposits.',
      '<b>Panic protocol:</b> account 10% below its high: pause stock buys, deposits still go to the index funds. 20% below: sell only by rule, look only on Sundays. 30% below: invest the opportunity cash in three steps. Any unplanned sale waits 48 hours and needs one written sentence.',
      '<b>Averaging down</b> is not a rule here. Adding to a loser only to lower the average price is a trap when the group is over its target or the stock is below its SMA(200): your average cost does not change what the stock does next.',
      '<b>Review:</b> on the first Sunday of the month. Rebalance when a group is 5 points off its target, using deposits first.',
    ].map(x => `<li>${x}</li>`).join('');
    $('pl-method').innerHTML = [
      '<b>200-day average</b> = the simple moving average of the last 200 daily closes, SMA(200), adjusted for dividends and splits (about ten months). It is the same kind of line as an SMA 200 on Nordnet\'s daily chart; small differences come from dividend adjustment and from the listing used.',
      '<b>Weekly close:</b> the trend rule looks only at the last close of each week. One weekly close below SMA(200) takes the trend half out; one weekly close back above brings it back. In the test this halved the number of switches compared with checking every day.',
      '<b>RSI(14)</b> here averages the last 14 daily changes (Cutler). Nordnet and TradingView use Wilder\'s smoothing, so their RSI can read a few points different.',
      '<b>Categories</b> come from the fund name and Yahoo sector and industry; the AI and semiconductor chain is chips, chip equipment, memory and storage, optics, AI hardware, AI power and AI cloud, plus theme ETFs. Change any holding in the table above.',
      '<b>Hold half / trend half:</b> in a half-trend group the theme ETFs and the 5 largest stocks are the hold half (kept through the trend, capped at 4% each). The other stocks are the trend half and follow the weekly SMA(200) rule.',
      '<b>ISK account:</b> selling has no tax effect, so losses are cut on the rules alone. The yearly ISK tax depends on the account value, not on trading.',
      'Not investment advice. Rules limit risk and cost; they do not predict prices.',
    ].map(x => `<li>${x}</li>`).join('');
  }

  // ───────── charts (colours from tokens at render time) ─────────
  function axes() {
    return { grid: { color: tok('--border') }, ticks: { color: tok('--text-dim') }, border: { color: tok('--border') } };
  }
  const cut = (s, n) => s.length > n ? s.slice(0, n - 1) + '…' : s;
  function charts() {
    const A = S.advice; if (!A || !A.plan) return;
    const L = A.plan, cats = L.categories, ax = axes();
    const vw = document.documentElement.clientWidth || 1000, narrow = vw < 600, lw = narrow ? 16 : vw < 1100 ? 26 : 34;
    const lk = cats.filter(c => L.lifetime[c.key] && (L.lifetime[c.key].n || L.lifetime[c.key].life)).map(c => c.key).sort((a, b) => L.lifetime[a].life - L.lifetime[b].life);
    mkChart('pl-life', { type: 'bar', data: { labels: lk.map(k => cats.find(c => c.key === k).label), datasets: [{ data: lk.map(k => L.lifetime[k].life),
        backgroundColor: lk.map(k => L.lifetime[k].life < 0 ? tok('--red') : tok('--green')), borderRadius: 3, maxBarThickness: 18 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => { const x = L.lifetime[lk[c.dataIndex]]; return [` Result ${sgn(x.life)} kr`, ` Unrealised ${sgn(x.unreal)}, realised ${sgn(x.realized)}`, ` Fees paid ${fmt(x.fees)} kr`, ` Now ${fmt(x.value)} kr in ${x.n} holdings`]; } } } },
        scales: { x: { ...ax, ticks: { ...ax.ticks, callback: v => fmt(v / 1000) + 'k' } }, y: { ...ax, grid: { display: false }, ticks: { ...ax.ticks, callback(v) { return cut(this.getLabelForValue(v), lw); } } } } } });
    mkChart('pl-fit', { type: 'bar', data: { labels: L.fit.map(f => f.label), datasets: [{ data: L.fit.map(f => f.score), backgroundColor: tok('--s1'), borderRadius: 3, maxBarThickness: 18 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.parsed.x} of 10` } } },
        scales: { x: { ...ax, min: 0, max: 10, ticks: { ...ax.ticks, stepSize: 2 } }, y: { ...ax, grid: { display: false }, ticks: { ...ax.ticks, callback(v) { return cut(this.getLabelForValue(v), lw); } } } } } });
    const T = L.transition, k = T.over[0] || 'core', lab0 = cats.find(c => c.key === k).label, tgt = L.targets[k];
    $('pl-drift-title').textContent = `${lab0}: share of the account over ${T.months} months`;
    const months = T.paths.plan[k].map((_, i) => i);
    const ln = (label, data, c, dash) => ({ label, data, borderColor: c, backgroundColor: c, borderWidth: dash ? 1 : 2, borderDash: dash || [], pointRadius: 0, pointHoverRadius: dash ? 0 : 4, tension: 0 });
    mkChart('pl-drift', { type: 'line', data: { labels: months, datasets: [ln('The plan', T.paths.plan[k], tok('--s1')), ln('Only new money redirected', T.paths.deposits_only[k], tok('--s3')),
        ln('Invest as now', T.paths.status_quo[k], tok('--s2')), ln('Target', months.map(() => tgt), tok('--text-dim'), [4, 4])] },
      options: { interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false }, tooltip: { callbacks: { title: i => 'Month ' + i[0].label, label: c => ` ${c.dataset.label}: ${c.parsed.y.toFixed(1)}%` } } },
        scales: { x: { ...ax, grid: { display: false }, title: { display: true, text: 'Months from now', color: tok('--text-dim') }, ticks: { ...ax.ticks, maxTicksLimit: 7 } }, y: { ...ax, min: 0, ticks: { ...ax.ticks, callback: v => v + '%' } } } } });
    const sk = Object.keys(L.stress.now);
    mkChart('pl-stress', { type: 'bar', data: { labels: sk, datasets: [
        { label: "Today's mix", data: sk.map(x => L.stress.now[x]), backgroundColor: tok('--text-dim'), borderRadius: 3, maxBarThickness: 34 },
        { label: 'Target mix', data: sk.map(x => L.stress.target[x]), backgroundColor: tok('--s1'), borderRadius: 3, maxBarThickness: 34 }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${c.parsed.y > 0 ? '+' : ''}${c.parsed.y}%` } } },
        scales: { x: { ...ax, grid: { display: false }, ticks: { ...ax.ticks, callback(v) { return narrow ? cut(this.getLabelForValue(v), 12) : this.getLabelForValue(v); } } }, y: { ...ax, ticks: { ...ax.ticks, callback: v => v + '%' } } } } });
  }

  // ───────── evidence (background 10-year test) ─────────
  async function evidence(fetchIt) {
    const A = S.advice; if (!A || !A.plan) return;
    if (fetchIt && (!P.ev || P.ev.pending)) {
      try { P.ev = await getJSON('/api/plan/evidence?profile=' + A.summary.profile); } catch (e) { P.ev = { ok: false, error: e.message }; }
    }
    const E = P.ev, st = $('pl-ev-status');
    if (!E) return;
    if (E.pending) {
      st.textContent = 'Testing up to 10 years of prices for your holdings in the background (about a minute the first time)…';
      clearTimeout(P.evTimer);
      if (P.evTries++ < 30) P.evTimer = setTimeout(() => { if (S.tab === 'advice') evidence(true); }, 6000);
      return;
    }
    if (!E.ok) { st.textContent = 'The test could not run right now (' + (E.error || 'unknown') + ').'; return; }
    P.evTries = 0;
    const labs = Object.fromEntries(A.plan.categories.map(c => [c.key, c.label]));
    const keys = A.plan.categories.map(c => c.key).filter(k => E.categories[k]);
    const start = keys.map(k => E.categories[k].start).sort()[0];
    st.textContent = `An equal-weight basket of the holdings in each category, tested from ${start} to today with 0.3% cost per switch (local currencies, no tax). It uses only stocks you hold today, which flatters buy and hold; trend rules were chosen for the fall they prevent, not for return.` + (E.stale ? ' Refreshing in the background.' : '');
    const ax = axes(), lw = (document.documentElement.clientWidth || 1000) < 600 ? 14 : 22;
    const pair = (metric, id) => mkChart(id, { type: 'bar', data: { labels: keys.map(k => labs[k]), datasets: [
        { label: 'Buy and hold', data: keys.map(k => E.categories[k].rules.BH[metric]), backgroundColor: tok('--text-dim'), borderRadius: 3, maxBarThickness: 12 },
        { label: 'Rule used', data: keys.map(k => E.categories[k].rules[E.categories[k].pick][metric]), backgroundColor: tok('--s1'), borderRadius: 3, maxBarThickness: 12 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.datasetIndex ? E.labels[E.categories[keys[c.dataIndex]].pick] : 'Buy and hold'}: ${c.parsed.x}%` } } },
        scales: { x: { ...ax, ticks: { ...ax.ticks, callback: v => v + '%' } }, y: { ...ax, grid: { display: false }, ticks: { ...ax.ticks, callback(v) { return cut(this.getLabelForValue(v), lw); } } } } } });
    pair('cagr', 'pl-ev-cagr'); pair('mdd', 'pl-ev-dd');
    const f = [];
    const bhBest = keys.filter(k => Object.values(E.categories[k].rules).every(r => r.cagr <= E.categories[k].rules.BH.cagr + 0.05)).length;
    f.push(`Buy and hold had the highest yearly return in ${bhBest} of ${keys.length} categories. The trend rules mainly reduce the worst fall and cost return in a rising market.`);
    const dipWorst = keys.filter(k => { const r = E.categories[k].rules; return Object.keys(r).every(x => r.DIP.cagr <= r[x].cagr); }).length;
    f.push(`Dip buying in and out on RSI was the weakest rule in ${dipWorst} of ${keys.length} categories; it sits in cash most of the time. That is why RSI only times new money here.`);
    if (E.categories.ai) { const r = E.categories.ai.rules; f.push(`AI and semiconductor chain: half held and half on the weekly rule gave ${r.HALFW.cagr}% a year with a worst fall of ${r.HALFW.mdd}% (return per unit of volatility ${r.HALFW.ret_vol}), against ${r.BH.cagr}% and ${r.BH.mdd}% (${r.BH.ret_vol}) for buy and hold.`); }
    if (E.categories.core) { const r = E.categories.core.rules; f.push(`Index funds: buy and hold ${r.BH.cagr}% a year; the weekly trend rule ${r.T200W.cagr}% and half-and-half ${r.HALFW.cagr}%. The core is never timed.`); }
    if (E.categories.materials) { const r = E.categories.materials.rules; f.push(`Energy and materials: SMA(50) above SMA(200) gave a worst fall of ${r.GX.mdd}% against ${r.BH.mdd}% for buy and hold (return per unit of worst fall ${r.GX.ret_mdd} against ${r.BH.ret_mdd}).`); }
    $('pl-ev-find').innerHTML = f.map(x => `<li>${esc(x)}</li>`).join('');
    const yr = new Date().getFullYear();
    let h = '<thead><tr><th>Rule</th><th>CAGR</th><th>Worst fall</th><th>Return / vol</th><th>Return / worst fall</th><th>Time invested</th><th>Switches a year</th><th>2022</th><th>Last year</th><th>This year</th></tr></thead><tbody>';
    keys.forEach(k => {
      const c = E.categories[k];
      h += `<tr class="grp"><td colspan="10">${esc(labs[k])} <span class="pl-small">${c.n} holdings, tested from ${c.start}</span></td></tr>`;
      Object.entries(c.rules).forEach(([r, o]) => {
        const y = o.years || {};
        h += `<tr class="${r === c.pick ? 'pick' : ''}"><td data-label="">${esc(E.labels[r])}${r === c.pick ? ' <span class="tag">used</span>' : ''}</td><td data-label="CAGR">${o.cagr}%</td><td data-label="Worst fall">${o.mdd}%</td>
          <td data-label="Return / vol">${o.ret_vol ?? '—'}</td><td data-label="Return / worst fall">${o.ret_mdd ?? '—'}</td><td data-label="Time invested">${o.invested}%</td><td data-label="Switches a year">${o.switch_py}</td>
          <td data-label="2022">${y['2022'] != null ? y['2022'] + '%' : '—'}</td><td data-label="Last year">${y[yr - 1] != null ? y[yr - 1] + '%' : '—'}</td><td data-label="This year">${y[yr] != null ? y[yr] + '%' : '—'}</td></tr>`;
      });
    });
    const el = $('pl-ev-all'); el.className = 'stack wide'; el.innerHTML = h + '</tbody>';
  }

  return { render };
})();
window.Plan = Plan;
