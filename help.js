/* Tile help: a small "i" button on every tile, card, chart panel and table header that has a known label.
   Tap/click opens a popover with a 1-2 line answer. Nothing in the HTML has to change: targets are found by selector,
   re-rendered content is picked up by a MutationObserver.

   Answer order: 1) POST /api/ask {q} (definition + the user's own number, from the profile data)
                 2) static fallback below (definition only, no numbers) when the request fails, times out,
                    the endpoint does not exist yet, or its confidence is under 0.5.

   To add a tile: append a row to HELP = [label regex (tested on the lower-cased, simplified label), question for /api/ask,
   fallback text]. First matching row wins. window.TVHelp.unmatched lists labels that have a target but no row. */
'use strict';
(function () {
  if (window.TVHelp) return;

  // ───────────────────────── label -> question -> fallback ─────────────────────────
  const HELP = [
    // ---- Portfolio page: summary, ideas, tables
    [/^total portfolio value/, 'what is my account value', 'Account value = holdings at live prices + cash. The same number everywhere in the app.'],
    [/^today s p&l/, "what is today's P&L", "Today's P&L = what the holdings gained or lost today, measured on yesterday's value (so -5% of a position is -5% of what it was worth yesterday)."],
    [/^total return$/, 'what is the all time result', 'All-time result = account value minus all the money you put in (net deposits): your real result, after fees and including dividends.'],
    [/^usd\/sek/, 'what is the usd sek rate', "Today's price of one US dollar in kronor, used to convert USD holdings to SEK."],
    [/^reports calendar/, 'which of my stocks report this week', 'Upcoming earnings reports and ex-dividend dates of your stocks from Yahoo Finance: today, tomorrow, this week and the next 30 days. Funds and ETFs have none.'],
    [/^change in range/, 'what does change in range mean', 'How much the account value moved in the chosen range. It includes the money you deposited, so the line under it splits it: deposited, and the real result (market, dividends, fees).'],
    [/^net asset value/, 'what is net asset value', 'Everything the account is worth on each day: holdings at the closing prices of each day plus cash. The growth view removes deposits, so only real performance shows.'],
    [/^add \/ trim ideas/, 'what are add and trim ideas', 'Rule-based ideas from position size, sector concentration, tiny positions and trend health. A to-check list, not a price forecast.'],
    [/^add \/ buy back/, 'what is an add or buy back idea', 'Small or sold positions in an uptrend that pulled back 5-25% from their 52-week high. Rule-based, not a forecast.'],
    [/^trim \/ consolidate/, 'what do trim consolidate and review mean', 'TRIM: position or sector too big. CONSOLIDATE: under 1 500 kr. REVIEW: downtrend and over 15% under your cost.'],
    [/^stocks & etfs/, 'what is in the stocks and etfs table', 'Every stock, ETF and ETC you hold: quantity, average cost, live price, today and return. Click a header to sort.'],
    [/^funds$/, 'what is in the funds table', 'Your mutual funds. The price is the fund NAV and keeps the export values, not live quotes.'],
    [/^(qty|units)$/, 'what is quantity', 'Number of shares or fund units you own. Gold (+n) marks units added since the last export.'],
    [/^(gav|avg nav)$/, 'what is gav', 'GAV = your average purchase price per share including fees. For funds: average NAV paid.'],
    [/^(price|nav)$/, 'what is the price column', 'Latest price per share (live from Yahoo). For funds the NAV, the fund price per unit.'],
    [/^day %$/, 'what is day percent', "Today's price change in %, measured from the previous close."],
    [/^value$/, 'what is the value column', 'Current market value of the position in kr.'],
    [/^return %$/, 'what is return percent', 'Unrealised return in % on what the position cost you.'],
    [/^return$/, 'what is the return column', 'Unrealised gain or loss in kr: value minus what you paid.'],
    [/^7d$/, 'what is the 7d column', 'The last 7 days of closing prices as a small line; green if the position is up over your cost.'],
    // ---- Portfolio page: heat map
    [/^portfolio heat map/, 'what is the heat map', 'Every holding as a tile: size = market value, colour = today or unrealised return, grouped by Yahoo sector, type or country.'],
    [/^group by/, 'what does group by do', 'How tiles are grouped: Yahoo sector, asset type or country.'],
    [/^colour shows/, 'what does the heat map colour show', "Tile colour is today's change or unrealised return vs cost: green up, red down, grey little change."],
    [/^distribution/, 'what is the distribution chart', 'Share of the portfolio value per group.'],
    [/^breakdown/, 'what is the breakdown table', 'The same groups as a table with value, weight, today and unrealised return.'],
    [/^concentration/, 'what is concentration', 'Notes on how much of the portfolio sits in the biggest groups and positions.'],
    // ---- Analytics: summary tiles
    [/^account value/, 'what is account value', 'Account value = holdings value (shares x price today) + the cash balance. One number, the same on the Portfolio page, Analytics and the growth curve.'],
    [/^deposited/, 'what are net deposits', 'All money you put in, minus withdrawals.'],
    [/^(all time|all-time) result/, 'what is the all time result', 'All-time result = account value - net deposits: your real profit or loss including realised, unrealised, dividends and all costs.'],
    [/^broker costs/, 'what are broker costs', 'Courtage, FX fees, interest and other charges paid to Nordnet since the start.'],
    [/^realised/, 'what is realised profit', 'Profit or loss locked in by selling (average-cost method, after fees).'],
    [/^unrealised/, 'what is unrealised profit', 'Unrealised = holdings value now minus what the current holdings cost. Paper profit or loss: it becomes real only when you sell.'],
    [/^data range/, 'what is the data range', 'First and last date in your transactions export, with the number of trades and assets.'],
    [/^assets$/, 'how many assets match the view', 'How many assets match the chosen view and filters.'],
    [/^fees paid/, 'what are fees paid', 'Total trade fees paid on the assets in the current view.'],
    // ---- Analytics: dividends
    [/^dividends received (net)?$|^dividends received$/, 'what are dividends received', 'Dividends paid into your account after withholding tax.'],
    [/^gross \/ tax withheld/, 'what is withholding tax on dividends', 'Gross dividend before tax and the tax withheld at source, mostly on foreign shares.'],
    [/^last 12 months/, 'what are dividends for the last 12 months', 'Net dividends received over the last 12 months and what that is of your holdings value.'],
    [/^average per month/, 'what is the average dividend per month', 'Net dividends divided by the months since your first dividend.'],
    [/^share of deposits/, 'what share of deposits are dividends', 'Net dividends as a percentage of the money you deposited.'],
    [/^latest payment/, 'when was the latest dividend', 'Date of the most recent dividend and what it paid net that day.'],
    [/^dividends in your result/, 'how much do dividends add to my result', 'Dividends are already inside the all-time result; this shows the result without them.'],
    [/^income rate/, 'what is my dividend income rate', 'Net dividends of the last 12 months as % of your holdings value.'],
    [/^spread of payers/, 'how spread are my dividend payers', 'How much of the dividends comes from the three largest payers and how regular the payments are.'],
    [/^withholding tax/, 'what is withholding tax', 'Tax taken from a dividend at source, before it reaches you.'],
    [/^sold payers/, 'what are sold dividend payers', 'Companies that paid you dividends but are no longer in the portfolio.'],
    [/^dividends received kr/, 'what does the dividends chart show', 'Dividends per day, week or month: net in green, tax withheld in grey.'],
    [/^total received so far/, 'what is the dividends running total', 'Running total of net dividends received.'],
    [/^top dividend payers/, 'who are my top dividend payers', 'Companies that paid the most net dividends. Green = still held, grey = sold.'],
    [/^net dividends per calendar month/, 'which months do dividends arrive', 'Net dividends added up by calendar month, to show when money usually arrives.'],
    [/^all dividend payers/, 'what is the dividend payers table', 'Every company that paid a dividend: payments, first and last date, gross, tax and net.'],
    [/^what the dividends tell you/, 'what do the dividend insights mean', 'Short notes on how dividends affect your result, income rate, spread and tax.'],
    // ---- Analytics: advice
    [/^entry rules/, 'what are the entry profiles', 'Conservative, Balanced or Aggressive: how strict the add and buy-back test is (pullback size, RSI, trend, waiting time).'],
    [/^where your portfolio stands/, 'what do the advice cards show', 'Size, concentration, risk and trend checks of the whole portfolio.'],
    [/^too many small positions/, 'what are too many small positions', 'Many tiny holdings cost courtage, cannot move the result and are hard to follow.'],
    [/^theme concentration/, 'what is theme concentration', 'Share of the portfolio in one Yahoo sector. Above 40% new adds are blocked and the largest names trimmed.'],
    [/^risk of the portfolio/, 'what do volatility drawdown and correlation mean', 'Volatility = yearly up/down swing; max drop = worst fall from a peak; correlation = how together holdings move.'],
    [/^trend health/, 'what is trend health', 'Share of holdings below both their 50- and 200-day averages.'],
    [/^size of the proposed changes/, 'how big are the proposed changes', 'Total kr of the add and trim ideas; sells can fund the buys.'],
    [/^theme yahoo sector|^theme weights/, 'what do the theme weights show', 'Share of holdings per Yahoo sector. Red bars are above the 40% cap.'],
    [/^suggested actions/, 'what are the suggested actions', 'How many holdings fall into ADD, BUY BACK, TRIM, CONSOLIDATE, REVIEW or HOLD.'],
    [/^add and buy back ideas/, 'what are add and buy back ideas', 'Holdings below 1.5% weight, and positions you closed, that are in an uptrend and pulled back.'],
    [/^trim ideas/, 'what are trim ideas', 'Positions over 4% of holdings, or large names in a sector over 40%. Risk rules only.'],
    [/^consolidate and review/, 'what are consolidate and review', 'CONSOLIDATE: under 1 500 kr. REVIEW: downtrend, negative momentum and over 15% under your cost.'],
    [/^how the rules work/, 'how do the add trim rules work', 'The exact thresholds behind ADD, BUY BACK, TRIM, CONSOLIDATE and REVIEW.'],
    [/^action$/, 'what is the action column', 'ADD, BUY BACK, TRIM, CONSOLIDATE or REVIEW; HOLD means nothing to do.'],
    [/^weight$/, 'what is weight', 'Share of the portfolio value in this position.'],
    [/^amount( kr)?$/, 'what is the suggested amount', 'Rounded kr to buy or sell to reach the target weight.'],
    [/^score$/, 'what is score', 'A 0-100 rating: how close you are to good practice (benchmark) or how strongly an idea ranks (advice).'],
    [/^trend$/, 'what is trend', 'up = price above its 200-day average with the 50-day above it; down = the opposite; mixed in between.'],
    [/^12m momentum/, 'what is 12-1 momentum', 'Price change over 12 months, skipping the most recent month.'],
    [/^from 52w high/, 'what is the distance from the 52 week high', 'How far the price is below its highest price of the last year.'],
    [/^why$/, 'why was this idea suggested', 'The rule that fired for this holding.'],
    [/^add \/ trim$/, 'what is the add trim column', 'Rule-based idea for the holding: ADD, TRIM, CONSOLIDATE, REVIEW or BUY BACK. Hover the badge for the reason.'],
    // ---- Analytics: asset explorer
    [/^by type/, 'what does by type show', 'Value (or the chosen measure) split by asset type: stock, fund, ETF.'],
    [/^by country/, 'what does by country show', 'Split by the country in the ISIN code, which is the legal home of the security.'],
    [/^top assets/, 'what are the top assets', 'The largest assets by the chosen measure.'],
    [/^(currently held|sold out|all assets|assets|bought|sold)\b.*assets?$/, 'what is this assets table', 'One row per asset with value, flows, fees and results. Click a row for its trades.'],
    [/^status$/, 'what is status', 'Held = you own it now; Closed = fully sold.'],
    [/^type ccy$/, 'what are type and currency', 'Asset type and the currency it trades in.'],
    [/^(bought|sold) kr/, 'what are bought and sold kr', 'Kr bought or sold in the chosen time window (or all-time).'],
    [/^buys \/ sells/, 'what are buys and sells', 'Number of buy and sell orders.'],
    [/^fees kr/, 'what are fees kr', 'Trade fees paid on this asset, courtage plus FX.'],
    [/^total p&l/, 'what is total pnl', 'Realised plus unrealised result of the asset. Dividends are not included here.'],
    // ---- Analytics: habits and costs
    [/^broker costs$/, 'what are broker costs', 'Courtage, FX fees, interest and other charges paid to Nordnet since the start.'],
    [/^account result after all costs/, 'what is the account result after all costs', 'Account value minus net deposits, after every broker cost.'],
    [/^fees vs\. profit|^fees vs profit/, 'what are fees vs profit made by selling', 'Trade fees as a share of the profit your sells made before fees.'],
    [/^win rate/, 'what is win rate', 'Share of sells that made a profit, with average win and loss.'],
    [/^benchmark score/, 'what is the habit score', 'A 0-100 rating of costs, trade size, holding time and concentration against common good-practice targets.'],
    [/^good practice/, 'what is good practice', 'The habits that would improve your score most, biggest shortfall first.'],
    [/^where trading is unnecessary/, 'where is trading unnecessary or expensive', 'Patterns that cost money: split orders, same-day round trips, quick rebuys.'],
    [/^patterns over time/, 'what are the patterns over time', 'Fees, results, trades and volume over time.'],
    [/^fees and results by trade size/, 'how do fees depend on trade size', 'Small orders pay a higher fee percentage; short holds tend to lose.'],
    [/^details$/, 'what are the details tables', 'Cost breakdown and the most expensive trading patterns.'],
    [/^cumulative fees vs realised/, 'what is cumulative fees vs realised pnl', 'Running total of fees paid against realised profit after fees.'],
    [/^positions held over time/, 'how many positions do i hold over time', 'Number of different assets held on each date.'],
    [/^trades per month/, 'how many trades per month', 'Buys and sells per month.'],
    [/^fees per month/, 'how much fees per month', 'Trade fees paid per month.'],
    [/^buy vs sell volume/, 'what is buy vs sell volume', 'Kr bought and sold per month.'],
    [/^trades by weekday/, 'which weekday do i trade most', 'Number of trades per weekday.'],
    [/^fee as % of trade value/, 'what is the fee percentage by trade size', 'Fee as % of the trade value, grouped by order size.'],
    [/^realised p&l by holding time/, 'what is realised pnl by holding time', 'Result of sells grouped by how long you held the position.'],
    [/^cost breakdown/, 'what is the cost breakdown', 'Courtage, FX fees, interest and other costs added up.'],
    [/^most traded assets/, 'what are the most traded assets', 'Assets with six or more trades, with their fees and results.'],
    [/^largest split orders/, 'what are split orders', 'Several orders for the same asset, day and side. One larger order would cost less courtage.'],
    [/^costliest same day/, 'what is a same day round trip', 'Buying and selling the same asset on one day. Usually loses to the fees.'],
    [/^worst sell then rebuy/, 'what is a sell then rebuy', 'Selling an asset and buying it back within 14 days, often at a worse price.'],
    [/^busiest days/, 'what are my busiest trading days', 'Days with the most orders.'],
    [/^data & method/, 'how is this calculated', 'Where the numbers come from and how they are calculated.'],
    [/^measure$/, 'what are the benchmark measures', 'Each habit that makes up the score.'],
    [/^(you|target|poor at)$/, 'what are target and poor at', 'Your value, the good-practice target and the level where the score hits zero.'],
    // ---- Analytics: deposit behaviour
    [/^rhythm/, 'what is deposit rhythm', 'Average deposit and how often you deposit.'],
    [/^(deposits|dividends) per/, 'what does the per day week month switch do', 'Group the columns by day, week or month.'],
    [/^portfolio line shows/, 'what does the portfolio line show', 'Estimated portfolio value in kr, or its return with deposits removed.'],
    [/^compare with/, 'what does compare with do', 'Overlay a price index in SEK: OMXS30, S&P 500 or Nasdaq 100 futures.'],
    [/^deposits kr$/, 'what is the deposits chart', 'Money deposited per day, week or month.'],
    [/^portfolio value|^return excl/, 'what is the estimated portfolio value', 'Cash plus positions priced from your own trades; an estimate, not a market history.'],
    [/^positions held$/, 'what is positions held', 'Number of different assets held at the time.'],
    [/^insights from your portfolio/, 'what are the deposit insights', 'Notes on return vs market, risk, idle cash and deposit timing.'],
    [/^monthly return/, 'what is the monthly return chart', 'Monthly return with deposits removed, you vs the S&P 500.'],
    [/^what moved you away/, 'what moved me away from the index', 'Contribution of costs, timing and picking vs putting every deposit into the index.'],
    [/^how to read this/, 'how do i read this tab', 'Method notes for the charts on this tab.'],
    [/^insights$/, 'what are the insights', 'Notes calculated from your own data.'],
    // ---- deposit and habit insight cards
    [/^cash sitting idle/, 'how much cash sits idle', 'Share of days the account held more than a small amount of uninvested cash.'],
    [/^deposit timing/, 'how is my deposit timing', 'Whether money goes in after drops, in quiet weeks or after rises (portfolio move in the 5 days before).'],
    [/^invested within 2 days/, 'how fast do i invest deposits', 'Share of deposits that are bought into positions within two days.'],
    [/^money per position/, 'how much money per position', 'Average size of a holding and what share of the portfolio it is.'],
    [/^pattern vs\. portfolio moves|^pattern vs portfolio moves/, 'what is the deposit pattern', 'Deposits after a drop / in a quiet week / after a rise, and what that says about your timing.'],
    [/^risk taken/, 'how much risk have i taken', 'Volatility and the worst fall of the portfolio, with deposits removed.'],
    [/^top up when cash ran out/, 'what is a top up when cash ran out', 'Deposits made when the cash balance was almost empty.'],
    [/^why you are behind|^your return vs the market/, 'why am i behind the index', 'Your return with deposits removed against the index, and what costs and picking took away.'],
    [/^trading rhythm/, 'what is trading rhythm', 'How often you trade, and how many orders on an active day.'],
    [/^where your results were best/, 'where were my results best', 'The holding times and trade sizes where your sells made the most.'],
    [/^fees that wiped out the gain/, 'what are fees that wiped out the gain', 'Sells where the fees were larger than the profit.'],
    [/^many small orders|^same order split into pieces/, 'what are split orders', 'Several orders for the same asset, day and side. One larger order would cost less courtage.'],
    [/^same day buy and sell/, 'what is a same day round trip', 'Buying and selling the same asset on one day. Usually loses to the fees.'],
    [/^sell then buy back|^sold within 1 day/, 'what is a sell then rebuy', 'Selling an asset and buying it back soon after, often at a worse price.'],
    [/^if every deposit had gone into an index/, 'what if every deposit went into an index', 'Your deposits invested in OMXS30 or the S&P 500 on the same days, against your actual account value.'],
    [/^back test on your holdings/, 'what did the back test show', 'How the old signal and the new rules did on your holdings over 2021-2026.'],
    [/^(cut the total number of trades|trade in larger fewer orders|set a minimum order size|one order per asset per day|add a cooling off|move the core into low turnover|review how you cut losers|sell only for a gain|watch concentration|consolidate tiny positions)/, 'how do i improve my trading habits', 'A habit that would improve your score; the number shows how far you are from the target.'],
    [/^already good/, 'which habits are already good', 'Habits that already meet the good-practice target.'],
    // ---- table headers (Portfolio heat map, trade tables, dividend payers)
    [/^(market )?value (kr|sek)$|^market value$/, 'what is market value', 'Current value of the position in kr.'],
    [/^category$/, 'what is category', 'The Yahoo sector (or type / country) the holding is grouped under.'],
    [/^cur$/, 'what is cur', 'Currency the holding is listed in.'],
    [/^holdings$/, 'how many holdings per group', 'Number of holdings in the group.'],
    [/^today$/, 'what is today in the breakdown', "Today's change of the group, weighted by position value."],
    [/^avoidable kr/, 'what is avoidable kr', 'Fees that one larger order instead of several small ones would have saved.'],
    [/^(buy|sell) kr\/sh/, 'what is price per share in kr', 'Price per share converted to kr.'],
    [/^effect kr/, 'what is the effect of a rebuy', 'What the sell and the later buy-back cost or gained together.'],
    [/^fee %/, 'what is fee percent', 'Fee as % of the trade value.'],
    [/^fee eaten/, 'what is fee eaten', 'Share of the gross gain that the fees ate.'],
    [/^net kr/, 'what is net kr', 'Result after fees.'],
    [/^(orders|trades|sells)$/, 'what are orders', 'Number of orders.'],
    [/^turnover kr/, 'what is turnover', 'Total kr bought plus sold.'],
    [/^trade size kr/, 'what is trade size', 'Order size bucket in kr.'],
    [/^(gross|tax) kr/, 'what are gross and tax kr', 'Dividend before tax, and the tax withheld at source.'],
    [/^payments$/, 'what are payments', 'Number of dividend payments received.'],
    [/^(company|asset)$/, 'what is this column', 'The company or asset name.'],
    [/^(first|last)$/, 'what are first and last', 'Date of the first and the most recent payment.'],
    [/^(held|rebought|date|side|sold|total|note|item|sek)$/, 'what does this column mean', 'Detail column of the table; the title above says what is listed.'],
  ];

  // ───────────────────────── targets: where an icon may go ─────────────────────────
  const TARGETS = [
    '#summary-cards .card-label', '#predictions-section .section-title', '#predictions-section .pred-panel-title',
    '.table-header-row .section-title', '#heatmap-section .section-title', '#heatmap-section .lbl', '#heatmap-section .hm-panel > h3',
    '.kpi .l', '.vcard .t', '.finding h4', '.panel h3', '.sec', '.dep-controls .lbl',
    'table thead th',
  ];
  const SKIP_CHILD = '.tv-help, .sev, .sort-icon, .arr, .count-badge, .pred-badge, .swatch, .pred-meta, .n';
  const API_Q_TIMEOUT = 4500, CACHE_MS = 5 * 60e3, FALLBACK_CACHE_MS = 60e3;

  const unmatched = new Set();
  const norm = s => s.toLowerCase().replace(/[’']/g, ' ').replace(/[^a-z0-9åäö%&/.$\s-]/g, ' ').replace(/-/g, ' ').replace(/\s+/g, ' ').trim();
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function labelOf(el) {
    let s = '';
    el.childNodes.forEach(n => {
      if (n.nodeType === 3) s += n.nodeValue;
      else if (n.nodeType === 1 && !n.matches(SKIP_CHILD)) s += n.textContent;
    });
    return s.replace(/\s+/g, ' ').trim();
  }
  function lookup(label) {
    const n = norm(label.replace(/^[▲▼]\s*/, ''));
    if (!n) return null;
    for (const row of HELP) if (row[0].test(n)) return { q: row[1], def: row[2] };
    return null;
  }

  // ───────────────────────── icon injection ─────────────────────────
  const ICON = '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false"><circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="6.2" r="1.1" fill="currentColor"/><path d="M10 9v5.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none"/></svg>';

  function inject(el) {
    if (el.querySelector(':scope > .tv-help')) return false;
    if (el.closest('.detail-inner, #asset-table tfoot, .tv-pop')) return false;
    const label = labelOf(el);
    if (!label || label.length > 90) return false;
    const hit = lookup(label);
    if (!hit) { unmatched.add(label); return false; }
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'tv-help';
    b.setAttribute('aria-label', 'Explain ' + label);
    b.setAttribute('aria-haspopup', 'dialog'); b.setAttribute('aria-expanded', 'false');
    b.innerHTML = ICON;
    b._tv = { label, q: hit.q, def: hit.def };
    const badge = el.querySelector(':scope > .pred-badge, :scope > .count-badge');   // keep the icon next to the title, before its badge
    if (badge) el.insertBefore(b, badge); else el.appendChild(b);
    return true;
  }

  // runs once per frame, before paint: rebuilt tiles get their icon back without a visible flicker
  let scanQueued = false;
  function scan() {
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(() => {
      scanQueued = false;
      document.querySelectorAll(TARGETS.join(',')).forEach(el => { if (el.offsetParent !== null || el.closest('thead')) inject(el); });
      reanchor();
    });
  }

  // ───────────────────────── answers ─────────────────────────
  const cache = new Map();
  let apiOffUntil = 0;                                   // endpoint answered 404/405/501: do not ask again for a while
  async function answer(e) {
    const c = cache.get(e.q);
    if (c && Date.now() < c.until) return c.v;
    let v = null;
    if (Date.now() >= apiOffUntil) try {
      const ac = new AbortController(), to = setTimeout(() => ac.abort(), API_Q_TIMEOUT);
      const r = await fetch('/api/ask', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-TV': '1' }, body: JSON.stringify({ q: e.q }), signal: ac.signal });
      clearTimeout(to);
      if (r.status === 404 || r.status === 405 || r.status === 501) apiOffUntil = Date.now() + 5 * 60e3;
      if (r.ok) {
        const j = await r.json();
        if (j && j.answer && (j.confidence == null || j.confidence >= 0.5)) v = { text: String(j.answer), link: j.link || null, live: true };
      }
    } catch (_) { /* endpoint missing or slow: use the fallback */ }
    if (!v) v = { text: e.def, link: null, live: false };
    cache.set(e.q, { until: Date.now() + (v.live ? CACHE_MS : FALLBACK_CACHE_MS), v });
    return v;
  }

  const KR = /[+\-−]?\d[\d\s ]*(?:,\d+)?\s?kr\b/g;
  function fmtAnswer(v) {
    let h = esc(v.text);
    if (v.live && document.documentElement.classList.contains('privacy')) h = h.replace(KR, m => '<span class="pv">' + m + '</span>');
    return h;
  }
  const safeLink = l => typeof l === 'string' && /^\/[A-Za-z0-9_./#?=&-]*$/.test(l) && l.replace(/^\//, '') !== (location.pathname.replace(/^\//, '') + location.hash);

  // ───────────────────────── popover ─────────────────────────
  let pop = null, anchor = null, anchorKey = '', token = 0, openedAt = 0, lastTop = 0, lastLeft = 0;
  // The pages re-render tiles and tables on every live-price refresh; the icon is rebuilt under an open popover.
  // A key (label + nearest id'd container) lets the popover move to the new icon instead of vanishing.
  const keyOf = b => b._tv.label + '|' + ((b.closest('[id]') || {}).id || '');
  function reanchor() {
    if (!anchor || anchor.isConnected) return;
    const nb = [...document.querySelectorAll('.tv-help')].find(b => keyOf(b) === anchorKey);
    if (!nb) { close(false); return; }
    anchor = nb; nb.setAttribute('aria-expanded', 'true'); place();
  }

  function place() {
    if (!pop || !anchor) return;
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const icon = anchor.querySelector('svg') || anchor, r = icon.getBoundingClientRect();
    const w = Math.min(280, vw - 16);
    pop.style.width = w + 'px';
    const h = pop.offsetHeight;
    let left = r.left + r.width / 2 - w / 2;
    left = Math.max(8, Math.min(left, vw - w - 8));
    const below = vh - r.bottom, above = r.top;
    const down = below >= h + 12 || below >= above;
    let top = down ? r.bottom + 8 : r.top - h - 8;
    top = Math.max(8, Math.min(top, vh - h - 8));
    lastTop = r.top; lastLeft = r.left;
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
    pop.style.maxHeight = (vh - 16) + 'px';
    pop.classList.toggle('up', !down);
    pop.style.setProperty('--ax', Math.max(14, Math.min(w - 14, r.left + r.width / 2 - left)) + 'px');
  }

  function open(btn) {
    if (anchor === btn) { close(true); return; }
    close(false);
    anchor = btn; anchorKey = keyOf(btn); openedAt = Date.now(); btn.setAttribute('aria-expanded', 'true');
    const id = ++token, info = btn._tv;
    pop = document.createElement('div');
    pop.className = 'tv-pop'; pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-label', info.label); pop.tabIndex = -1;
    pop.innerHTML = '<button type="button" class="tv-pop-x" aria-label="Close">×</button><h5>' + esc(info.label) + '</h5><p class="tv-pop-a" aria-live="polite"><span class="tv-wait">Calculating…</span></p>';
    document.body.appendChild(pop);
    place();
    pop.focus({ preventScroll: true });
    answer(info).then(v => {
      if (!pop || id !== token) return;
      const p = pop.querySelector('.tv-pop-a');
      p.innerHTML = fmtAnswer(v) + (safeLink(v.link) ? ' <a href="' + esc(v.link) + '">Open →</a>' : '');
      place();
    });
  }

  function close(restoreFocus) {
    if (!pop && !anchor) return;
    let a = anchor;
    const key = anchorKey;
    if (pop) pop.remove();
    pop = null; anchor = null; token++;
    if (a) {
      a.setAttribute('aria-expanded', 'false');
      if (restoreFocus && !a.isConnected) a = [...document.querySelectorAll('.tv-help')].find(b => keyOf(b) === key) || null;   // re-rendered meanwhile
      if (restoreFocus && a && a.isConnected) a.focus({ preventScroll: true });
    }
  }

  document.addEventListener('click', e => {
    const x = e.target.closest && e.target.closest('.tv-pop-x');
    if (x) { close(true); return; }
    const b = e.target.closest && e.target.closest('.tv-help');
    if (b) { e.preventDefault(); e.stopPropagation(); open(b); }
  }, true);
  document.addEventListener('pointerdown', e => {
    if (!pop) return;
    if (e.target.closest('.tv-pop') || e.target.closest('.tv-help')) return;
    close(false);
  }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && pop) { e.stopPropagation(); close(true); } }, true);
// Scrolling closes the popover, but only when the icon really moved: re-rendering a table clamps its scroll position and fires
  // scroll events without moving anything, and events within 300 ms of opening are layout/focus side effects (late events on phones).
  document.addEventListener('scroll', e => {
    if (!pop || Date.now() - openedAt < 300 || (e.target.nodeType === 1 && e.target.closest('.tv-pop'))) return;
    if (!anchor || !anchor.isConnected) return;                 // re-render in progress: reanchor() decides
    const r = (anchor.querySelector('svg') || anchor).getBoundingClientRect();
    if (Math.abs(r.top - lastTop) < 3 && Math.abs(r.left - lastLeft) < 3) return;
    close(false);
  }, true);
  window.addEventListener('resize', () => close(false));
  window.addEventListener('orientationchange', () => close(false));

  // ───────────────────────── start ─────────────────────────
  function start() {
    scan();
    new MutationObserver(recs => {
      // our own icons / popover do not count; a tab being shown or hidden does (static headings become visible)
      const real = recs.some(r => r.type === 'attributes' || [...r.addedNodes, ...r.removedNodes].some(n => !(n.nodeType === 1 && n.matches('.tv-help, .tv-pop'))));
      if (real) scan();
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();

  window.TVHelp = { HELP, scan, unmatched: () => [...unmatched].sort(), count: () => document.querySelectorAll('.tv-help').length };
})();
