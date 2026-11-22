/* ============================================================
   PLAN & ADVICE TAB — plan.js  (analytics.html #tab-advice)
   One strategy per category (strategy.py / advisor.py, served by /api/advice), the evidence behind it
   (/api/plan/evidence, a 10-year test of your own holdings per category) and your plan settings (/api/plan/settings).
   Loaded after analytics.js and uses its helpers ($, esc, fmt, pct, sgn, mkChart, table, kpi, getJSON, S, loadAdvice, advProfile).
   Colours are read from the CSS tokens at render time and charts are redrawn on 'tvthemechange'.
   ============================================================ */
'use strict';
const Plan = (() => {
  const P = { built: false, ev: null, evTries: 0, evTimer: 0, settings: null, cats: [], open: new Set(), saving: false };
  const tok = n => (window.TVTheme ? TVTheme.css(n) : getComputedStyle(document.documentElement).getPropertyValue(n).trim()) || '#888';
  const CATCOL = { core: '--s1', ai: '--s2', bigtech: '--s3', health: '--s4', industrials: '--s5', financials: '--s6', materials: '--s7', defensive: '--s8', cash: '--text-dim' };
  const col = k => tok(CATCOL[k] || '--text-dim');
  const RULE_TXT = { size_cap: 'size cap', trend_exit: 'trend exit', regime_exit: 'regime exit', pullback: 'pullback in an uptrend', deposit_plan: 'deposit plan',
    consolidate: 'tiny position', review: 'review', hold_half: 'hold half', near_entry: 'close to an entry', buyback: 'buy back', core: 'index fund', fixed: 'defensive' };
  const kr = n => `<span class="pv">${fmt(n)}</span>`;

  function skeleton() {
    $('plan-root').innerHTML = `
      <div class="pl-head">
        <div><span class="lbl">Profile (targets)</span><div class="chips" id="pl-profile" role="group" aria-label="Profile">
          <button class="chip" data-p="conservative">Conservative</button><button class="chip" data-p="balanced">Balanced</button><button class="chip" data-p="aggressive">Aggressive</button></div></div>
        <form class="pl-settings" id="pl-settings" novalidate>
          <label for="pl-dep">Monthly deposit, kr<input id="pl-dep" type="number" min="0" max="1000000" step="500" inputmode="numeric"></label>
          <label for="pl-red">Reduce over-target groups, kr / month<input id="pl-red" type="number" min="0" max="1000000" step="500" inputmode="numeric"></label>
          <label for="pl-opp">Opportunity cash, %<input id="pl-opp" class="pct" type="number" min="0" max="20" step="0.5" inputmode="decimal"></label>
          <button class="btn" type="submit" id="pl-save">Save plan</button>
          <span class="pl-saved" id="pl-saved" role="status" aria-live="polite"></span>
        </form>
      </div>
      <p class="hint" id="pl-status"></p>
      <h2 class="sec">Where your portfolio stands</h2>
      <section id="pl-kpis" class="kpi-row"></section>
      <section id="pl-cards" class="findings"></section>

      <h2 class="sec">This month</h2>
      <section class="grid g3">
        <div class="panel"><h3 id="pl-dep-title">Next deposit</h3><div class="tbl-wrap"><table id="pl-deposit"></table></div><p class="hint" id="pl-dep-note"></p></div>
        <div class="panel"><h3>Sell this month</h3><div class="tbl-wrap"><table id="pl-sells"></table></div><p class="hint" id="pl-sell-note"></p></div>
        <div class="panel"><h3>Buy, buy back and watch</h3><div class="tbl-wrap"><table id="pl-buys"></table></div><p class="hint" id="pl-buy-note"></p></div>
      </section>

      <h2 class="sec">One strategy per category</h2>
      <section class="grid g2">
        <div class="panel"><h3>Share of the account: today against target</h3><div class="cv tall"><canvas id="pl-cw" role="img" aria-label="Bars of each category's share of the account today and its target"></canvas></div>
          <div class="pl-key"><span><i style="background:var(--text-dim)"></i>Today</span><span><i style="background:var(--s1)"></i>Target</span></div></div>
        <div class="panel"><h3>Lifetime result per category, kr</h3><div class="cv tall"><canvas id="pl-life" role="img" aria-label="Bars of lifetime result per category"></canvas></div>
          <p class="hint">Unrealised plus realised (realised is already after fees), sold positions included. Dividends are not split by category.</p></div>
      </section>
      <section class="panel"><div class="tbl-wrap"><table id="pl-cats" class="pl-cats"></table></div></section>

      <h2 class="sec">Holdings by category</h2>
      <p class="hint">Click a category to open it. "Weekly trend" is the last weekly close against the simple 200-day average, SMA(200). If a holding sits in the wrong group, choose another category; the plan is recalculated.</p>
      <section class="panel"><div class="tbl-wrap"><table id="pl-hold"></table></div></section>

      <h2 class="sec">The evidence: which rule worked for which category</h2>
      <p class="hint" id="pl-ev-status"></p>
      <section class="grid g2">
        <div class="panel"><h3>Yearly return (CAGR)</h3><div class="cv tall"><canvas id="pl-ev-cagr" role="img" aria-label="Yearly return per category, buy and hold against the chosen rule"></canvas></div></div>
        <div class="panel"><h3>Worst fall from a peak</h3><div class="cv tall"><canvas id="pl-ev-dd" role="img" aria-label="Worst fall per category, buy and hold against the chosen rule"></canvas></div></div>
      </section>
      <div class="pl-key"><span><i style="background:var(--text-dim)"></i>Buy and hold</span><span><i style="background:var(--s1)"></i>Rule used for the category</span></div>
      <ul class="pl-findings" id="pl-ev-find"></ul>
      <details class="panel"><summary>Every rule in every category</summary><div class="tbl-wrap"><table id="pl-ev-all"></table></div></details>

      <h2 class="sec">How you follow the five popular strategies</h2>
      <section class="grid g2">
        <div class="panel"><h3>Fit from 0 to 10</h3><div class="cv"><canvas id="pl-fit" role="img" aria-label="Bars of fit to five strategies"></canvas></div></div>
        <div class="panel"><div class="tbl-wrap"><table id="pl-fit-t"></table></div></div>
      </section>

      <h2 class="sec">The transition</h2>
      <section class="grid g2">
        <div class="panel"><h3 id="pl-drift-title">Share over 36 months</h3><div class="cv tall"><canvas id="pl-drift" role="img" aria-label="Lines of a category's share under three paths"></canvas></div>
          <div class="pl-key"><span><i style="background:var(--s1)"></i>The plan</span><span><i style="background:var(--s3)"></i>Only new money redirected</span><span><i style="background:var(--s2)"></i>Invest as now</span><span><i class="dash"></i>Target</span></div>
          <p class="hint" id="pl-drift-note"></p></div>
        <div class="panel"><h3>Stress test: result in % under three scenarios</h3><div class="cv tall"><canvas id="pl-stress" role="img" aria-label="Bars of scenario results for today's mix and the target mix"></canvas></div>
          <div class="pl-key"><span><i style="background:var(--text-dim)"></i>Today's mix</span><span><i style="background:var(--s1)"></i>Target mix</span></div>
          <p class="hint" id="pl-stress-note"></p></div>
      </section>

      <section class="panel pl-answer"><h3>What "200-day average" and "weekly close" mean here</h3>
        <p>The 200-day average is the <b>simple moving average of the last 200 daily closes, SMA(200)</b>, adjusted for dividends and splits (about ten months). It is the same kind of line as an SMA 200 on Nordnet's daily chart; small differences come from dividend adjustment and from the listing used (some holdings are tracked on their US or home listing).</p>
        <p>The trend rule looks only at the <b>last close of each week</b>. One weekly close below SMA(200) takes the trend half out; one weekly close back above it brings it back. There is no "wait two weeks" in the rule: the weekly check already filters most false signals, and in the test it halved the number of switches compared with checking every day.</p>
        <p>RSI(14) here averages the last 14 daily changes (Cutler). Nordnet and TradingView use Wilder's smoothing, so their RSI can read a few points different.</p></section>
      <section class="panel method"><h3>Rules that apply to every category</h3><ul id="pl-rules"></ul></section>
      <section class="panel method"><h3>How to read this</h3><ul id="pl-method"></ul></section>`;
    $('pl-profile').addEventListener('click', e => {
      const b = e.target.closest('.chip'); if (!b) return;
      try { localStorage.setItem(window.TV ? TV.key('tv_advice_profile') : 'tv_advice_profile', b.dataset.p); } catch (err) { /* private mode */ }
      S.advice = null; $('pl-status').textContent = 'Recalculating…'; P.ev = null; loadAdvice();
    });
    $('pl-settings').addEventListener('submit', e => { e.preventDefault(); save(); });
    $('pl-hold').addEventListener('click', e => {
      const g = e.target.closest('tr.grp'); if (!g) return;
      const k = g.dataset.k; P.open.has(k) ? P.open.delete(k) : P.open.add(k); holdings();
    });
    $('pl-hold').addEventListener('keydown', e => {
      const g = e.target.closest('tr.grp'); if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); g.click(); }
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
      fillSettings();
    } catch (e) { /* the form keeps its defaults */ }
  }
  function fillSettings() {
    const s = P.settings; if (!s) return;
    if (document.activeElement && document.activeElement.closest && document.activeElement.closest('#pl-settings')) return;
    $('pl-dep').value = s.deposit; $('pl-red').value = s.reduce; $('pl-opp').value = s.opportunity_pct;
  }
  async function save(extra) {
    if (P.saving) return;
    const body = extra || { deposit: +$('pl-dep').value, reduce: +$('pl-red').value, opportunity_pct: +$('pl-opp').value };
    const msg = $('pl-saved'); msg.classList.remove('err'); msg.textContent = 'Saving…'; P.saving = true;
    try {
      const r = await fetch('/api/plan/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json();
      if (!r.ok || !j.ok) throw new Error(j.message || j.error || ('HTTP ' + r.status));
      P.settings = j.settings; fillSettings();
      msg.textContent = 'Saved. Recalculating…';
      S.advice = null; await loadAdvice();
      msg.textContent = 'Saved.';
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
    const prof = (typeof advProfile === 'function') ? advProfile() : 'balanced';
    document.querySelectorAll('#pl-profile .chip').forEach(b => b.classList.toggle('active', b.dataset.p === ((A && A.summary.profile) || prof)));
    if (!A) { $('pl-status').textContent = 'Loading price history from Yahoo for the first time can take up to a minute…'; loadAdvice(); return; }
    if (!A.plan) { $('pl-status').textContent = 'The server has not been updated to the per-category plan yet.'; return; }
    const L = A.plan, Y = A.summary;
    $('pl-status').textContent = `${Y.profile_about[0].toUpperCase() + Y.profile_about.slice(1)}. Based on ${Y.positions} holdings (${Y.covered} with Yahoo price history), valued ${A.asof.replace('T', ' ')}. Weights are % of the whole account, cash included.${A.partial ? ' Some price history is still loading; this refreshes by itself.' : ''}`;
    kpis(L); cards(A); month(A); catTable(L); holdings(); fitTable(L); notes(L); charts(); evidence(true);
    if (A.partial) setTimeout(() => { if (S.tab === 'advice') { S.advice = null; loadAdvice(); } }, 20000);
  }

  function kpis(L) {
    const c = Object.fromEntries(L.categories.map(x => [x.key, x]));
    const worst = L.categories.filter(x => x.key !== 'core').sort((a, b) => b.gap - a.gap)[0];
    $('pl-kpis').innerHTML =
      kpi('Account value', kr(L.total) + ' kr', 'holdings plus cash') +
      kpi('Index funds', pct(c.core.pct, 0), `target ${pct(c.core.target, 0)}`, c.core.status === 'under' ? 'neg' : '') +
      kpi(esc(worst.label), pct(worst.pct, 0), `target ${pct(worst.target, 0)}`, worst.status === 'over' ? 'neg' : '') +
      kpi('Stock money in an uptrend', pct(L.up_pct, 0), 'weekly close above SMA(200)', L.up_pct < 40 ? 'neg' : L.up_pct >= 60 ? 'pos' : '') +
      kpi('Opportunity cash', kr(L.cash) + ' kr', `target ${fmt(c.cash.target / 100 * L.total)} kr`, L.cash < c.cash.target / 100 * L.total * .5 ? 'neg' : '') +
      kpi('Trades, last 30 days', fmt(L.trading.trades_30d), `budget ${L.trading.max_trades} · fees ${fmt(L.trading.fees_30d)} kr`, L.trading.trades_30d > L.trading.max_trades ? 'neg' : 'pos');
  }

  function cards(A) {
    const sev = { high: 'ACT', med: 'WATCH', info: 'NOTE' };
    $('pl-cards').innerHTML = A.cards.map(c => `<div class="finding"><h4><span class="sev ${c.sev}">${sev[c.sev] || 'NOTE'}</span>${esc(c.title)}</h4><div class="num">${esc(c.num)}</div><p>${esc(c.text)}</p></div>`).join('');
  }

  function month(A) {
    const L = A.plan, rows = Object.entries(A.assets).map(([isin, v]) => ({ isin, ...v }));
    const dep = L.settings.deposit;
    $('pl-dep-title').textContent = `Next deposit: ${fmt(dep)} kr`;
    const drows = [];
    L.deposit_plan.forEach(d => {
      drows.push([`<span class="sw" style="background:${col(d.cat)}"></span><b>${esc(d.label)}</b>`, { v: kr(d.amount) + ' kr', c: 'num' }]);
      (d.where || []).forEach(w => drows.push([`<span class="pl-small">&nbsp;&nbsp;&nbsp;→ ${esc(w.name)}</span>`, { v: `<span class="pl-small">${kr(w.amount)} kr</span>` }]));
      if (d.cat === 'cash') drows.push([`<span class="pl-small">&nbsp;&nbsp;&nbsp;→ stays as cash on the account</span>`, '']);
    });
    table('pl-deposit', ['Goes to', 'Amount'], drows, dep ? 'Nothing is under its target.' : 'Set a monthly deposit above.');
    $('pl-dep-note').textContent = 'Split over the groups furthest under their target. A stock group only gets money when one of its stocks has an entry signal; otherwise its share waits in the index funds. Orders under 2 500 kr are merged.';

    const sells = rows.filter(r => r.action === 'TRIM' && r.when !== 'later').sort((a, b) => a.amount - b.amount);
    const srows = sells.map(r => {
      const rsi = r.metrics && r.metrics.rsi != null ? Math.round(r.metrics.rsi) : null;
      const ok = rsi == null || rsi > 45;
      return [esc(r.name), `<span class="pl-small">${esc(RULE_TXT[r.rule] || r.rule || '')}</span>`, { v: kr(r.amount) + ' kr' },
        `<span class="pill ${ok ? 'ok' : 'wait'}" title="Planned sales go on a day the RSI(14) is above 45 (into strength), at the latest within 4 weeks">${rsi == null ? 'any day' : ok ? 'RSI ' + rsi + ': OK today' : 'RSI ' + rsi + ': wait for a bounce'}</span>`];
    });
    const tiny = rows.filter(r => r.action === 'CONSOLIDATE');
    table('pl-sells', ['Holding', 'Rule', 'Amount', 'When'], srows, 'No sale is due this month.');
    const tot = sells.reduce((s, r) => s + r.amount, 0);
    $('pl-sell-note').innerHTML = `${sells.length} sales, ${kr(tot)} kr.` + (L.queued ? ` ${L.queued} more (${kr(L.queued_kr)} kr) are queued for the next months by the ${fmt(L.settings.reduce)} kr monthly reduction budget.` : '') +
      (tiny.length ? ` ${tiny.length} tiny positions (${kr(tiny.reduce((s, r) => s + r.amount, 0))} kr) can be sold or topped up: ${tiny.slice(0, 6).map(r => esc(r.name)).join(', ')}${tiny.length > 6 ? '…' : ''}.` : '');

    const buys = rows.filter(r => ['ADD', 'BUYBACK', 'WATCH'].includes(r.action) && r.rule !== 'deposit_plan').sort((a, b) => (ADV_RANK[a.action] - ADV_RANK[b.action]) || b.score - a.score);
    table('pl-buys', ['Holding', 'Idea', 'RSI 14', 'Amount'], buys.map(r => [esc(r.name) + `<br><span class="pl-small">${esc(r.category_label || '')}</span>`,
      `<span class="adv ${r.action}" title="${esc(r.reasons.join(' '))}">${ADV_LABEL[r.action]}</span>`,
      r.metrics && r.metrics.rsi != null ? Math.round(r.metrics.rsi) : '—', { v: r.amount ? kr(r.amount) + ' kr' : '—' }]),
      'No stock idea this month: every group under its target lacks a stock in an uptrend with a low RSI. New money goes to the index funds.');
    $('pl-buy-note').textContent = `Stocks get new money only in an uptrend (weekly close above SMA(200)), with RSI(14) below ${L.rsi_add} and only when their group is under its target. RSI is used only to time new money, never to sell.`;
  }

  function catTable(L) {
    const st = { over: 'over target', under: 'under target', ok: 'on target' };
    const max = Math.max(60, ...L.categories.map(c => Math.max(c.pct, c.target)));
    table('pl-cats', ['Category', 'Now', 'Target', 'Status', 'Weekly trend', 'Strategy'], L.categories.map(c => [
      `<span class="sw" style="background:${col(c.key)}"></span>${esc(c.label)}<br><span class="pl-small">${c.n} holdings · ${kr(c.kr)} kr</span>`,
      { v: `<span class="bar" title="${pct(c.pct, 1)} now, target ${pct(c.target, 0)}"><i style="width:${c.pct / max * 100}%;background:${col(c.key)}"></i><b style="left:${c.target / max * 100}%"></b></span>${pct(c.pct, 1)}` },
      pct(c.target, 0), `<span class="pill ${c.status}">${st[c.status]} ${c.gap > 0 ? '+' : ''}${c.gap.toFixed(0)} pts</span>`,
      c.n_trend ? `${c.n_up} of ${c.n_trend} above` : '—', { v: esc(c.strategy), c: 'strat' }]));
  }

  function holdings() {
    const A = S.advice; if (!A || !A.plan) return;
    const ov = (P.settings && P.settings.overrides) || {};
    const opts = (P.cats.length ? P.cats : A.plan.categories.filter(c => c.key !== 'cash').map(c => ({ key: c.key, label: c.label })));
    const by = {};
    Object.entries(A.assets).filter(([, v]) => !v.closed).forEach(([isin, v]) => (by[v.category] = by[v.category] || []).push({ isin, ...v }));
    let html = '<thead><tr><th>Holding</th><th>Value kr</th><th>% of account</th><th>vs your cost</th><th>Weekly trend</th><th>vs SMA(200)</th><th>RSI 14</th><th>Action</th><th>Category</th><th>Why</th></tr></thead><tbody>';
    A.plan.categories.forEach(c => {
      const xs = (by[c.key] || []).sort((a, b) => b.weight - a.weight);
      if (!xs.length) return;
      const open = P.open.has(c.key);
      html += `<tr class="grp" data-k="${c.key}" tabindex="0" aria-expanded="${open}"><td colspan="10"><span class="chev">${open ? '▾' : '▸'}</span><span class="sw" style="background:${col(c.key)}"></span>${esc(c.label)} · ${xs.length} · ${pct(c.pct, 1)} (target ${pct(c.target, 0)}) · ${esc(c.strategy)}</td></tr>`;
      if (!open) return;
      xs.forEach(v => {
        const m = v.metrics || {}, a = (S.data && S.data.assets || []).find(x => x.isin === v.isin) || {};
        const wk = m.wk_up == null ? '<span class="pill na">no data</span>' : `<span class="pill ${m.wk_up ? 'up' : 'down'}" title="last weekly close ${m.wk_date}">${m.wk_up ? 'above' : 'below'} · ${m.wk_weeks} wk</span>`;
        const sel = `<select data-isin="${v.isin}" aria-label="Category of ${esc(v.name)}"><option value="">auto</option>${opts.map(o => `<option value="${o.key}"${ov[v.isin] === o.key ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
        const amt = v.amount ? ` <span class="adv-amt pv">${v.action === 'ADD' || v.action === 'BUYBACK' ? '+' : '−'}${fmt(v.amount)}</span>` : '';
        html += `<tr class="${ov[v.isin] ? 'ovr' : ''}"><td>${esc(v.name)}${v.keep ? ' <span class="tag" title="kept as the hold half of this category">hold half</span>' : ''}</td><td>${kr(a.value)}</td><td>${pct(v.weight, 1)}</td>
          <td class="${cls(a.unrealized_pct)}">${a.unrealized_pct == null ? '—' : pct(a.unrealized_pct, 0)}</td><td>${wk}</td><td>${m.wk_dist == null ? '—' : pct(m.wk_dist * 100, 0)}</td><td>${m.rsi == null ? '—' : Math.round(m.rsi)}</td>
          <td><span class="adv ${v.action}">${ADV_LABEL[v.action] || v.action}</span>${amt}${v.when === 'later' ? ' <span class="tag">queued</span>' : ''}</td><td>${sel}</td><td class="why">${esc(v.reasons.join(' '))}</td></tr>`;
      });
    });
    $('pl-hold').innerHTML = html + '</tbody>';
  }

  function fitTable(L) {
    table('pl-fit-t', ['Strategy', 'Your account', 'The rule'], L.fit.map(f => [`<b>${esc(f.label)}</b><br><span class="pl-small">${f.score} of 10</span>`, { v: esc(f.measure), c: 'why' }, { v: esc(f.rule), c: 'why' }]));
    document.querySelectorAll('#pl-fit-t td.why').forEach(td => { td.style.whiteSpace = 'normal'; td.style.minWidth = '180px'; });
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
      '<b>Averaging down</b> is not a rule here. Adding to a loser only to lower the average price is a trap when the group is over its target or the stock is below its SMA(200): your average cost does not change what the stock does next. New money goes to a stock only in an uptrend, with a low RSI, in a group under its target.',
      '<b>Review:</b> on the first Sunday of the month. Rebalance when a group is 5 points off its target, using deposits first.',
    ].map(x => `<li>${x}</li>`).join('');
    $('pl-method').innerHTML = [
      '<b>Categories</b> come from the fund name and Yahoo sector and industry; the AI and semiconductor chain is chips, chip equipment, memory and storage, optics, AI hardware, AI power and AI cloud, plus theme ETFs. Change any holding in the table above.',
      '<b>Hold half / trend half:</b> in a half-trend group the theme ETFs and the 5 largest stocks are the hold half (kept through the trend, capped at 4% each). The other stocks are the trend half and follow the weekly SMA(200) rule.',
      '<b>ISK account:</b> selling has no tax effect, so losses are cut on the rules alone. The yearly ISK tax depends on the account value, not on trading.',
      '<b>Data:</b> Yahoo adjusted daily closes (2 years for the signals, 10 years for the evidence), live prices for weights, your ledger for cost and result. Funds without Yahoo history are kept as they are.',
      'Not investment advice. Rules limit risk and cost; they do not predict prices.',
    ].map(x => `<li>${x}</li>`).join('');
  }

  // ───────── charts (colours from tokens at render time) ─────────
  function axes() {
    return { grid: { color: tok('--border') }, ticks: { color: tok('--text-dim') }, border: { color: tok('--border') } };
  }
  function charts() {
    const A = S.advice; if (!A || !A.plan) return;
    const L = A.plan, cats = L.categories, ax = axes();
    const cut = (s, n) => s.length > n ? s.slice(0, n - 1) + '…' : s;
    mkChart('pl-cw', { type: 'bar', data: { labels: cats.map(c => c.label), datasets: [
        { label: 'Today', data: cats.map(c => c.pct), backgroundColor: tok('--text-dim'), borderRadius: 3, maxBarThickness: 14 },
        { label: 'Target', data: cats.map(c => c.target), backgroundColor: tok('--s1'), borderRadius: 3, maxBarThickness: 14 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${c.parsed.x.toFixed(1)}%` } } },
        scales: { x: { ...ax, ticks: { ...ax.ticks, callback: v => v + '%' } }, y: { ...ax, grid: { display: false }, ticks: { ...ax.ticks, callback(v) { return cut(this.getLabelForValue(v), 22); } } } } } });
    const lk = cats.filter(c => L.lifetime[c.key]).map(c => c.key);
    mkChart('pl-life', { type: 'bar', data: { labels: lk.map(k => cats.find(c => c.key === k).label), datasets: [{ data: lk.map(k => L.lifetime[k].life),
        backgroundColor: lk.map(k => L.lifetime[k].life < 0 ? tok('--red') : tok('--green')), borderRadius: 3, maxBarThickness: 18 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => { const x = L.lifetime[lk[c.dataIndex]]; return [` Result ${sgn(x.life)} kr`, ` Unrealised ${sgn(x.unreal)}, realised ${sgn(x.realized)}`, ` Fees paid ${fmt(x.fees)} kr`, ` Now ${fmt(x.value)} kr in ${x.n} holdings`]; } } } },
        scales: { x: { ...ax, ticks: { ...ax.ticks, callback: v => fmt(v / 1000) + 'k' } }, y: { ...ax, grid: { display: false }, ticks: { ...ax.ticks, callback(v) { return cut(this.getLabelForValue(v), 22); } } } } } });
    mkChart('pl-fit', { type: 'bar', data: { labels: L.fit.map(f => f.label), datasets: [{ data: L.fit.map(f => f.score), backgroundColor: tok('--s1'), borderRadius: 3, maxBarThickness: 18 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.parsed.x} of 10` } } },
        scales: { x: { ...ax, min: 0, max: 10, ticks: { ...ax.ticks, stepSize: 2 } }, y: { ...ax, grid: { display: false }, ticks: { ...ax.ticks, callback(v) { return cut(this.getLabelForValue(v), 24); } } } } } });
    const T = L.transition, k = T.over[0] || 'core', lab = cats.find(c => c.key === k).label, tgt = L.targets[k];
    $('pl-drift-title').textContent = `${lab}: share of the account over ${T.months} months`;
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
        scales: { x: { ...ax, grid: { display: false } }, y: { ...ax, ticks: { ...ax.ticks, callback: v => v + '%' } } } } });
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
    const lab = Object.fromEntries(A.plan.categories.map(c => [c.key, c.label]));
    const keys = A.plan.categories.map(c => c.key).filter(k => E.categories[k]);
    const start = keys.map(k => E.categories[k].start).sort()[0];
    st.textContent = `An equal-weight basket of the holdings in each category, tested from ${start} to today with 0.3% cost per switch (local currencies, no tax). It uses only stocks you hold today, which flatters buy and hold; trend rules were chosen for the fall they prevent, not for return.` + (E.stale ? ' Refreshing in the background.' : '');
    const ax = axes(), cut = (s, n) => s.length > n ? s.slice(0, n - 1) + '…' : s;
    const pair = (metric, id) => mkChart(id, { type: 'bar', data: { labels: keys.map(k => lab[k]), datasets: [
        { label: 'Buy and hold', data: keys.map(k => E.categories[k].rules.BH[metric]), backgroundColor: tok('--text-dim'), borderRadius: 3, maxBarThickness: 12 },
        { label: 'Rule used', data: keys.map(k => E.categories[k].rules[E.categories[k].pick][metric]), backgroundColor: tok('--s1'), borderRadius: 3, maxBarThickness: 12 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.datasetIndex ? E.labels[E.categories[keys[c.dataIndex]].pick] : 'Buy and hold'}: ${c.parsed.x}%` } } },
        scales: { x: { ...ax, ticks: { ...ax.ticks, callback: v => v + '%' } }, y: { ...ax, grid: { display: false }, ticks: { ...ax.ticks, callback(v) { return cut(this.getLabelForValue(v), 22); } } } } } });
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
    let h = '<thead><tr><th>Category / rule</th><th>CAGR</th><th>Worst fall</th><th>Return / vol</th><th>Return / worst fall</th><th>Time invested</th><th>Switches a year</th><th>2022</th><th>Last year</th><th>This year</th></tr></thead><tbody>';
    const yr = new Date().getFullYear();
    keys.forEach(k => {
      const c = E.categories[k];
      h += `<tr><td colspan="10"><b>${esc(lab[k])}</b> <span class="pl-small">${c.n} holdings, from ${c.start}</span></td></tr>`;
      Object.entries(c.rules).forEach(([r, o]) => {
        const y = o.years || {};
        h += `<tr class="${r === c.pick ? 'pick' : ''}"><td>${esc(E.labels[r])}${r === c.pick ? ' <span class="tag">used</span>' : ''}</td><td>${o.cagr}%</td><td>${o.mdd}%</td><td>${o.ret_vol ?? '—'}</td><td>${o.ret_mdd ?? '—'}</td><td>${o.invested}%</td><td>${o.switch_py}</td>
          <td>${y['2022'] != null ? y['2022'] + '%' : '—'}</td><td>${y[yr - 1] != null ? y[yr - 1] + '%' : '—'}</td><td>${y[yr] != null ? y[yr] + '%' : '—'}</td></tr>`;
      });
    });
    $('pl-ev-all').innerHTML = h + '</tbody>';
  }

  return { render };
})();
window.Plan = Plan;
