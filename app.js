/* ============================================================
   TRADING DASHBOARD — app.js
   Loads CSV holdings, fetches live prices from Yahoo Finance,
   renders sparklines via Chart.js, company logos via Clearbit.
   ============================================================ */

// When served from server.py (localhost) all Yahoo Finance calls go through
// the local /yahoo/* proxy — no CORS, no blocked requests.
// When opened from a remote host the full Yahoo URL is used with proxy fallbacks.
const IS_LOCAL = ['localhost', '127.0.0.1', ''].includes(location.hostname);

// ────────────────────────────────────────────────────────────
// CONFIG
// ────────────────────────────────────────────────────────────
const CFG = {
  // Fixed-name files written by nordnet_sync.py; fallback = last Nordnet export
  stocksFile:         'portfolio_stocks.csv',
  fundsFile:          'portfolio_funds.csv',
  stocksFileFallback: 'aktier_kontonummer-66262387_2026-03-26_stocks.csv',
  fundsFileFallback:  'fonder_kontonummer-66262387_2026-03-26_funds.csv',

  // On localhost: /yahoo/* is proxied by server.py — no CORS issues
  // On remote:    direct Yahoo URL (browser/proxy fallbacks in yahooGet)
  yahooBase:  IS_LOCAL ? '/yahoo' : 'https://query1.finance.yahoo.com',

  // Ticker bar symbols + display labels
  tickerSymbols: ['^OMX', '^GDAXI', 'ES=F', 'GC=F', 'USDSEK=X', 'EURUSD=X'],
  tickerLabels:  { '^OMX':'OMXS30', '^GDAXI':'DAX', 'ES=F':'SP500F',
                   'GC=F':'GOLD', 'USDSEK=X':'USD/SEK', 'EURUSD=X':'EUR/USD' },

  refreshMs:    60_000,       // live-price refresh interval (ms)
  csvRefreshMs: 5 * 60_000,  // portfolio CSV re-check interval (ms)
  sparkLimit:   25,           // max sparklines to fetch (rate-limit caution)
};

// ────────────────────────────────────────────────────────────
// TICKER SYMBOL MAP  (stock name → Yahoo Finance symbol)
// ────────────────────────────────────────────────────────────
const TICKER_MAP = {
  'ABB':                        'ABB.ST',
  'AbbVie':                     'ABBV',
  'Advanced Micro Devices':     'AMD',
  'Alfa Laval':                 'ALFA.ST',
  'Alphabet A':                 'GOOGL',
  'Amazon.com':                 'AMZN',
  'American Express':           'AXP',
  'Amphenol':                   'APH',
  'Analog Devices':             'ADI',
  'Apple':                      'AAPL',
  'Applied Materials':          'AMAT',
  'Assa Abloy B':               'ASSA-B.ST',
  'AstraZeneca':                { USD: 'AZN', SEK: 'AZN.ST', default: 'AZN' },
  'Atlas Copco A':              'ATCO-A.ST',
  'Axfood':                     'AXFO.ST',
  'Boston Scientific':          'BSX',
  'Broadcom':                   'AVGO',
  'Chevron':                    'CVX',
  'Clas Ohlson B':              'CLAS-B.ST',
  'Coca-Cola':                  'KO',
  'ConAgra Brands':             'CAG',
  'Delta Air Lines':            'DAL',
  'GE Aerospace':               'GE',
  'General Dynamics':           'GD',
  'Handelsbanken A':            'SHB-A.ST',
  'IBM':                        'IBM',
  'Intel':                      'INTC',
  'Investor A':                 'INVE-A.ST',
  'iShares Core MSCI EM IMI UCITS ETF USD (Acc)':                          'EIMI.L',
  'iShares Dow Jones Global Leaders Screened UCITS ETF USD (Acc)':         'SUSL.L',
  'JP Morgan Chase':            'JPM',
  'Kongsberg Gruppen':          'KOG.OL',
  'Lockheed Martin Corp.':      'LMT',
  'Lululemon Athletica':        'LULU',
  'Lundin Gold':                'LUG.ST',
  'Lundin Mining Corporation':  'LUMI.ST',
  'Meta Platforms A':           'META',
  'Micron Technology':          'MU',
  'Microsoft':                  'MSFT',
  'Nebius Group':               'NBIS',
  'Netflix':                    'NFLX',
  'Nordea Bank':                'NDA-FI.HE',
  'Novo Nordisk B':             'NOVO-B.CO',
  'NVIDIA':                     'NVDA',
  'Oklo A':                     'OKLO',
  'Oracle':                     'ORCL',
  'Palantir Technologies':      'PLTR',
  'QUALCOMM':                   'QCOM',
  'Rivian Automotive A':        'RIVN',
  'RTX':                        'RTX',
  'SAAB B':                     'SAAB-B.ST',
  'SEB A':                      'SEB-A.ST',
  'Siemens AG':                 'SIE.DE',
  'Siemens Energy AG':          'ENR.DE',
  'SKF B':                      'SKF-B.ST',
  'SoFi Technologies':          'SOFI',
  'SPDR S&P 500 ETF USD Acc':   'SPY5.DE',
  'Spotify':                    'SPOT',
  'SS SPDR Dow Jones Global Real Estate UCITS ETF': 'GLRE.L',
  'Swedbank A':                 'SWED-A.ST',
  'TE Connectivity':            'TEL',
  'Tesla':                      'TSLA',
  'The Trade Desk A':           'TTD',
  'VanEck Defense ETF A USD Acc':   'DFNS.L',
  'VanEck Semiconductor ETF':       'SMH',
  'Vanguard FTSE All-World High Dividend Yield UCITS ETF - (USD) Acc': 'VHYL.L',
  'Vanguard S&P 500 UCITS ETF - (USD) Acc': 'VUSA.L',
  'Vår Energi':                 'VAR.OL',
  'Volvo B':                    'VOLV-B.ST',
  'Walmart':                    'WMT',
  'Wärtsilä B':                 'WRT1V.HE',
  'Western Digital':            'WDC',
  'Workday A':                  'WDAY',
  'XACT OMXS30 ESG ETF':        'XACT30.ST',
  'Xetra-Gold':                 '4GLD.DE',
  'Xtrackers Artificial Intelligence & Big Data UCITS ETF 1C': 'XAIX.DE',
};

// ────────────────────────────────────────────────────────────
// CLEARBIT DOMAIN MAP  (name → domain for logo API)
// ────────────────────────────────────────────────────────────
const DOMAIN_MAP = {
  'ABB':                    'abb.com',
  'AbbVie':                 'abbvie.com',
  'Advanced Micro Devices': 'amd.com',
  'Alfa Laval':             'alfalaval.com',
  'Alphabet A':             'abc.xyz',
  'Amazon.com':             'amazon.com',
  'American Express':       'americanexpress.com',
  'Amphenol':               'amphenol.com',
  'Analog Devices':         'analog.com',
  'Apple':                  'apple.com',
  'Applied Materials':      'appliedmaterials.com',
  'Assa Abloy B':           'assaabloy.com',
  'AstraZeneca':            'astrazeneca.com',
  'Atlas Copco A':          'atlascopco.com',
  'Axfood':                 'axfood.se',
  'Boston Scientific':      'bostonscientific.com',
  'Broadcom':               'broadcom.com',
  'Chevron':                'chevron.com',
  'Clas Ohlson B':          'clasohlson.com',
  'Coca-Cola':              'coca-cola.com',
  'ConAgra Brands':         'conagrabrands.com',
  'Delta Air Lines':        'delta.com',
  'GE Aerospace':           'ge.com',
  'General Dynamics':       'gd.com',
  'Handelsbanken A':        'handelsbanken.se',
  'IBM':                    'ibm.com',
  'Intel':                  'intel.com',
  'Investor A':             'investorab.com',
  'JP Morgan Chase':        'jpmorganchase.com',
  'Kongsberg Gruppen':      'kongsberg.com',
  'Lockheed Martin Corp.':  'lockheedmartin.com',
  'Lululemon Athletica':    'lululemon.com',
  'Lundin Gold':            'lundingold.com',
  'Lundin Mining Corporation': 'lundinmining.com',
  'Meta Platforms A':       'meta.com',
  'Micron Technology':      'micron.com',
  'Microsoft':              'microsoft.com',
  'Netflix':                'netflix.com',
  'Nordea Bank':            'nordea.com',
  'Novo Nordisk B':         'novonordisk.com',
  'NVIDIA':                 'nvidia.com',
  'Oklo A':                 'oklo.com',
  'Oracle':                 'oracle.com',
  'Palantir Technologies':  'palantir.com',
  'QUALCOMM':               'qualcomm.com',
  'Rivian Automotive A':    'rivian.com',
  'RTX':                    'rtx.com',
  'SAAB B':                 'saab.com',
  'SEB A':                  'seb.se',
  'Siemens AG':             'siemens.com',
  'Siemens Energy AG':      'siemens-energy.com',
  'SKF B':                  'skf.com',
  'SoFi Technologies':      'sofi.com',
  'Spotify':                'spotify.com',
  'Swedbank A':             'swedbank.se',
  'Tesla':                  'tesla.com',
  'The Trade Desk A':       'thetradedesk.com',
  'Volvo B':                'volvo.com',
  'Walmart':                'walmart.com',
  'Western Digital':        'wdc.com',
  'Workday A':              'workday.com',
};

// Avatar accent colours for initials fallback
const AVATAR_PALETTE = ['#2962FF','#26A69A','#EF5350','#F7C948','#AB47BC','#26C6DA','#FF7043','#66BB6A','#5C6BC0','#EC407A'];

// ────────────────────────────────────────────────────────────
// APPLICATION STATE
// ────────────────────────────────────────────────────────────
const S = {
  stocks:        [],   // parsed stock objects
  funds:         [],   // parsed fund objects
  quotes:        {},   // symbol → { price, changePercent, change }
  sparkData:     {},   // symbol → number[] (closing prices, 7 days)
  ohlcv:         {},   // symbol → [{t,open,high,low,close,volume}] 30-day
  predictions:   { up: [], down: [] },
  charts:        {},   // canvasId → Chart instance
  displayCur:    'SEK',
  stockFilter:   'ALL',
  stockSearch:   '',
  fundsSearch:   '',
  stockSort:     { col: 'value', dir: 'desc' },
  fundsSort:     { col: 'value', dir: 'desc' },
  fx:            { USD: 9.35, EUR: 10.81, NOK: 0.965, DKK: 1.446, CAD: 6.77 },
  lastBuy:       {},   // name → { qty, price, date } — most-recent purchase detected
  _snapshot:     {},   // previous-load snapshot used for buy detection
};

// ────────────────────────────────────────────────────────────
// CSV PARSING  (handles UTF-16 LE/BE with BOM, Swedish decimals)
// ────────────────────────────────────────────────────────────
function parseSE(str) {
  // Parse Swedish number format: "1 234,56" → 1234.56
  if (!str && str !== 0) return 0;
  const s = String(str).trim().replace(/\u00a0/g, '').replace(/\s/g, '').replace(',', '.');
  const v = parseFloat(s);
  return isNaN(v) ? 0 : v;
}

async function loadCSV(filename) {
  const resp = await fetch(filename);
  if (!resp.ok) throw new Error(`Cannot load ${filename}: HTTP ${resp.status}`);

  const buf  = await resp.arrayBuffer();
  const bytes = new Uint8Array(buf);

  let text;
  if (bytes[0] === 0xFF && bytes[1] === 0xFE) {
    text = new TextDecoder('utf-16le').decode(buf);
  } else if (bytes[0] === 0xFE && bytes[1] === 0xFF) {
    text = new TextDecoder('utf-16be').decode(buf);
  } else {
    text = new TextDecoder('utf-8').decode(buf);
  }

  // Strip BOM
  text = text.replace(/^\uFEFF/, '');

  const lines = text.split(/\r?\n/).filter(l => l.trim());
  if (lines.length < 2) return [];

  const headers = lines[0].split('\t').map(h => h.trim());
  return lines.slice(1).map(line => {
    const cols = line.split('\t').map(c => c.trim());
    const obj  = {};
    headers.forEach((h, i) => { obj[h] = cols[i] ?? ''; });
    return obj;
  }).filter(r => r[headers[0]]); // skip empty rows
}

function buildStock(raw) {
  // Stocks columns: Namn | Valuta | Antal | GAV | Idag % | Senaste kurs |
  //                 Belåningsvärde SEK | Värde | Värde SEK | Avkast. % | Avkast. SEK
  return {
    name:       (raw['Namn'] || '').trim(),
    currency:   (raw['Valuta'] || 'SEK').trim(),
    qty:        parseSE(raw['Antal']),
    gav:        parseSE(raw['GAV']),
    dayChange:  parseSE(raw['Idag %']),
    price:      parseSE(raw['Senaste kurs']),
    value:      parseSE(raw['Värde']),
    valueSEK:   parseSE(raw['Värde SEK']),
    returnPct:  parseSE(raw['Avkast. %']),
    returnSEK:  parseSE(raw['Avkast. SEK']),
    ticker:     null,
    livePrice:  null,
    liveDayPct: null,
  };
}

function buildFund(raw) {
  // Funds columns: Namn | Valuta | Antal | Snittkurs | 1 dag % | Senaste NAV |
  //                Belåningsvärde SEK | Inköpsvärde SEK | Värde SEK | Avkast. % | Avkast. SEK
  const keys = Object.keys(raw);

  // Flexible column detection (handles encoding nuances)
  const find = (...pats) => {
    for (const p of pats) {
      const k = keys.find(k => k.toLowerCase().includes(p.toLowerCase()));
      if (k) return k;
    }
    return null;
  };

  const snittCol    = find('snittkurs', 'snitt', 'avg');
  const navCol      = find('senaste nav', 'nav');
  const dayCol      = find('1 dag', 'idag', 'dag %');
  const purchaseCol = find('inköpsvärde', 'purchase');
  const valueSEKCol = find('värde sek', 'value sek');
  const retPctCol   = find('avkast. %', 'return %', 'avkast %');
  const retAbsCol   = find('avkast. sek', 'return sek', 'avkast sek');

  return {
    name:             (raw['Namn'] || '').trim(),
    currency:         (raw['Valuta'] || 'SEK').trim(),
    qty:              parseSE(raw['Antal']),
    gav:              parseSE(snittCol    ? raw[snittCol]    : '0'),
    dayChange:        parseSE(dayCol      ? raw[dayCol]      : '0'),
    price:            parseSE(navCol      ? raw[navCol]      : '0'),
    purchaseValueSEK: parseSE(purchaseCol ? raw[purchaseCol] : '0'),
    valueSEK:         parseSE(valueSEKCol ? raw[valueSEKCol] : '0'),
    returnPct:        parseSE(retPctCol   ? raw[retPctCol]   : '0'),
    returnSEK:        parseSE(retAbsCol   ? raw[retAbsCol]   : '0'),
    ticker: null,
  };
}

// ────────────────────────────────────────────────────────────
// LAST BUY SNAPSHOT TRACKING
// Persists portfolio state in localStorage so new purchases
// are detected on next CSV load and shown as (+qty) / (price)
// ────────────────────────────────────────────────────────────
async function loadLastBuyData() {
  try {
    S.lastBuy   = JSON.parse(localStorage.getItem('portfolio_lastbuy')  || '{}');
    S._snapshot = JSON.parse(localStorage.getItem('portfolio_snapshot') || '{}');
  } catch (_) {
    S.lastBuy   = {};
    S._snapshot = {};
  }

  // Always fetch portfolio_baseline.json (written by nordnet_sync.py just BEFORE
  // overwriting the CSVs).  If the baseline is newer than the localStorage
  // snapshot, use it — this ensures buy detection works after every sync.
  try {
    const resp = await fetch('portfolio_baseline.json?t=' + Date.now());
    if (resp.ok) {
      const baseline = await resp.json();
      const baselineTs = baseline.__ts || 0;
      const localTs    = Number(localStorage.getItem('portfolio_snapshot_ts') || 0);
      if (baselineTs > localTs || !Object.keys(S._snapshot).length) {
        // Baseline is fresher than what's in localStorage — use it
        const clean = Object.fromEntries(
          Object.entries(baseline).filter(([k]) => k !== '__ts'));
        S._snapshot = clean;
        console.log('[snapshot] Seeded from portfolio_baseline.json (ts=' + baselineTs + ')');
      }
    }
  } catch (_) {}
}

/** Compare current holdings to snapshot; record any qty increases as new buys. */
function detectAndSaveBuys() {
  const snap = S._snapshot;
  [...S.stocks, ...S.funds].forEach(item => {
    const prev = snap[item.name];
    if (prev && item.qty > prev.qty + 0.0001) {
      const added    = item.qty - prev.qty;
      // Derive last-buy price from the shift in weighted-average:
      // newAvg * newQty = oldAvg * oldQty + buyPrice * added
      const buyPrice = (item.qty * item.gav - prev.qty * prev.gav) / added;
      S.lastBuy[item.name] = {
        qty:   added,
        price: buyPrice > 0 ? buyPrice : item.gav,
        date:  new Date().toLocaleDateString('sv-SE'),
      };
    }
  });
  localStorage.setItem('portfolio_lastbuy', JSON.stringify(S.lastBuy));
  // Save new snapshot for next comparison
  const newSnap = {};
  [...S.stocks, ...S.funds].forEach(item => {
    newSnap[item.name] = { qty: item.qty, gav: item.gav };
  });
  S._snapshot = newSnap;
  const nowTs = Date.now();
  localStorage.setItem('portfolio_snapshot',    JSON.stringify(newSnap));
  localStorage.setItem('portfolio_snapshot_ts', nowTs);
}

// ────────────────────────────────────────────────────────────
// CSV LOADING WITH FALLBACK + PORTFOLIO RELOAD
// ────────────────────────────────────────────────────────────
async function loadCSVWithFallback(primary, fallback) {
  try { return await loadCSV(primary); }
  catch (_) {
    if (fallback) return await loadCSV(fallback);
    throw _;
  }
}

/** Re-fetch CSVs, detect new buys, re-render tables + refresh prices. */
async function reloadPortfolio() {
  setStatus('loading', 'Refreshing portfolio…');
  try {
    const [stockRows, fundRows] = await Promise.all([
      loadCSVWithFallback(CFG.stocksFile, CFG.stocksFileFallback),
      loadCSVWithFallback(CFG.fundsFile,  CFG.fundsFileFallback),
    ]);
    S.stocks = stockRows.map(buildStock).filter(s => s.name);
    S.funds  = fundRows.map(buildFund).filter(f => f.name);
    S.stocks.forEach(s => { s.ticker = resolveTickerFor(s); });
    S.funds.forEach(f  => { f.ticker = resolveTickerFor(f); });
    detectAndSaveBuys();
    renderAll();
    await refreshPrices();
  } catch (err) {
    console.error('[reloadPortfolio]', err);
    setStatus('', 'Refresh failed: ' + err.message);
  }
}

// ────────────────────────────────────────────────────────────
// TICKER RESOLUTION
// ────────────────────────────────────────────────────────────
function resolveTickerFor(item) {
  const name  = item.name.trim();
  const entry = TICKER_MAP[name];
  if (!entry) return null;
  if (typeof entry === 'object') {
    return entry[item.currency] || entry.default || Object.values(entry)[0];
  }
  return entry;
}

// ────────────────────────────────────────────────────────────
// YAHOO FINANCE API
// Local mode  : /yahoo/* proxied by server.py  — direct fetch, no CORS
// Remote mode : try query1 → query2 → corsproxy.io → allorigins.win
// ────────────────────────────────────────────────────────────
async function yahooGet(url) {
  const tFetch = (u, wrapAO = false) => new Promise((res, rej) => {
    const ctrl = new AbortController();
    const tid  = setTimeout(() => ctrl.abort(), 7000);
    fetch(u, { signal: ctrl.signal, headers: { Accept: 'application/json' } })
      .then(async r => {
        clearTimeout(tid);
        if (!r.ok) return rej(new Error('HTTP ' + r.status));
        const text = await r.text();
        let d;
        try {
          const w = JSON.parse(text);
          d = wrapAO && w.contents ? JSON.parse(w.contents) : w;
        } catch (_) { return rej(new Error('JSON parse fail')); }
        if (d?.error) return rej(new Error('Yahoo error'));
        res(d);
      })
      .catch(e => { clearTimeout(tid); rej(e); });
  });

  if (IS_LOCAL) {
    // server.py proxy: simple, reliable, no CORS
    return tFetch(url);
  }

  // Remote fallback chain
  const ext = 'https://query1.finance.yahoo.com';
  const absUrl = url.startsWith('/') ? ext + url : url;
  try { return await tFetch(absUrl); } catch (_) {}
  try { return await tFetch(absUrl.replace('query1.', 'query2.')); } catch (_) {}
  try { return await tFetch(`https://corsproxy.io/?url=${encodeURIComponent(absUrl)}`); } catch (_) {}
  try { return await tFetch(`https://api.allorigins.win/get?url=${encodeURIComponent(absUrl)}`, true); } catch (_) {}
  throw new Error('All Yahoo Finance routes failed');
}

async function fetchQuotesBatch(symbols) {
  if (!symbols.length) return [];
  const url = `${CFG.yahooBase}/v7/finance/quote?symbols=${symbols.join(',')}&fields=regularMarketPrice,regularMarketChangePercent,regularMarketChange`;
  try {
    const d = await yahooGet(url);
    const results = d?.quoteResponse?.result || [];
    if (!results.length) console.warn('[quotes] empty result for', symbols.join(','));
    return results;
  } catch (e) {
    console.warn('[quotes] all proxies failed for batch:', symbols.slice(0, 3).join(',') + '…', e.message);
    setStatus('error', 'Price feed unavailable — retrying…');
    return [];
  }
}

async function fetchSparkline(symbol) {
  const url = `${CFG.yahooBase}/v8/finance/chart/${symbol}?interval=1d&range=7d&includePrePost=false`;
  try {
    const d = await yahooGet(url);
    const closes = d?.chart?.result?.[0]?.indicators?.quote?.[0]?.close || [];
    return closes.filter(v => v != null);
  } catch (_) {
    return [];
  }
}

// ────────────────────────────────────────────────────────────
// LIVE PRICE UPDATE CYCLE
// ────────────────────────────────────────────────────────────
async function refreshPrices() {
  setStatus('loading', 'Fetching prices…');

  // Assign tickers
  S.stocks.forEach(s => { s.ticker = resolveTickerFor(s); });
  S.funds.forEach(f  => { f.ticker = resolveTickerFor(f); });

  const allSymbols = [
    ...new Set([
      ...S.stocks.filter(s => s.ticker).map(s => s.ticker),
      ...CFG.tickerSymbols,
      ...WATCHLIST.map(w => w.sym),   // ensure watchlist symbols always fetched
    ]),
  ];

  // Batch fetch (15 per request)
  const BATCH = 15;
  for (let i = 0; i < allSymbols.length; i += BATCH) {
    const results = await fetchQuotesBatch(allSymbols.slice(i, i + BATCH));
    results.forEach(q => {
      S.quotes[q.symbol] = {
        price:         q.regularMarketPrice,
        changePercent: q.regularMarketChangePercent,
        change:        q.regularMarketChange,
      };
    });
    if (i + BATCH < allSymbols.length) await sleep(250);
  }

  // Update live FX rate
  const usdSek = S.quotes['USDSEK=X'];
  if (usdSek?.price) S.fx.USD = usdSek.price;

  // Propagate live prices into stock objects
  S.stocks.forEach(s => {
    if (s.ticker && S.quotes[s.ticker]) {
      s.livePrice  = S.quotes[s.ticker].price;
      s.liveDayPct = S.quotes[s.ticker].changePercent;
    }
  });

  renderAll();
  renderWatchlist();
  setStatus('live', 'Live · ' + new Date().toLocaleTimeString());
}

// Sparklines — fetched lazily in the background after first render
async function loadSparklines() {
  const tickers = [...new Set(
    S.stocks.filter(s => s.ticker).map(s => s.ticker),
  )].slice(0, CFG.sparkLimit);

  for (const sym of tickers) {
    if (S.sparkData[sym]) continue;
    const data = await fetchSparkline(sym);
    if (data.length >= 3) S.sparkData[sym] = data;
    await sleep(220);
  }

  // Re-paint sparklines on whatever rows are currently visible
  S.stocks.forEach((s, idx) => {
    if (s.ticker && S.sparkData[s.ticker]) {
      drawSparkline(`spark-s-${idx}`, S.sparkData[s.ticker], s.returnPct >= 0);
    }
  });
}

// ────────────────────────────────────────────────────────────
// FORMATTING HELPERS
// ────────────────────────────────────────────────────────────
function fmtNum(n, dec = 0) {
  if (n == null || isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: dec,
    maximumFractionDigits: Math.max(dec, 2),
  }).format(n);
}

function fmtPct(n) {
  if (n == null || isNaN(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

function displayAmt(sek) {
  if (S.displayCur === 'USD') return '$' + fmtNum(sek / S.fx.USD);
  return fmtNum(sek) + ' kr';
}

function pctClass(n) {
  if (!n || n === 0) return 'flat';
  return n > 0 ? 'pos' : 'neg';
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ────────────────────────────────────────────────────────────
// LOGO / AVATAR
// ────────────────────────────────────────────────────────────
function logoUrl(name) {
  const domain = DOMAIN_MAP[name.trim()];
  return domain ? `https://logo.clearbit.com/${domain}?size=24` : null;
}

function avatarColor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (Math.imul(31, h) + name.charCodeAt(i)) | 0;
  return AVATAR_PALETTE[Math.abs(h) % AVATAR_PALETTE.length];
}

function buildLogoEl(name) {
  const wrap = document.createElement('div');
  wrap.className = 'logo-cell';

  const url = logoUrl(name);
  if (url) {
    const img  = new Image();
    img.className = 'company-logo';
    img.alt       = name;
    img.src       = url;
    img.onerror   = () => { wrap.innerHTML = ''; wrap.appendChild(buildInitialsEl(name)); };
    wrap.appendChild(img);
  } else {
    wrap.appendChild(buildInitialsEl(name));
  }
  return wrap;
}

function buildInitialsEl(name) {
  const words = name.trim().split(/\s+/);
  const initials = words.slice(0, 2).map(w => w[0]).join('').toUpperCase();
  const el = document.createElement('div');
  el.className = 'company-initials';
  el.style.background = avatarColor(name);
  el.textContent = initials;
  return el;
}

// ────────────────────────────────────────────────────────────
// SPARKLINE RENDERING (Chart.js)
// ────────────────────────────────────────────────────────────
function drawSparkline(canvasId, data, isPositive) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !data || data.length < 2) return;

  const color = isPositive ? '#26A69A' : '#EF5350';
  const fill  = isPositive ? 'rgba(38,166,154,0.12)' : 'rgba(239,83,80,0.12)';

  if (S.charts[canvasId]) {
    S.charts[canvasId].destroy();
    delete S.charts[canvasId];
  }

  S.charts[canvasId] = new Chart(canvas, {
    type: 'line',
    data: {
      labels: data.map((_, i) => i),
      datasets: [{
        data,
        borderColor:     color,
        backgroundColor: fill,
        borderWidth:     1.5,
        pointRadius:     0,
        tension:         0.3,
        fill:            true,
      }],
    },
    options: {
      responsive:  false,
      animation:   false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false } },
    },
  });
}

// ────────────────────────────────────────────────────────────
// RENDER — TICKER BAR
// ────────────────────────────────────────────────────────────
function renderTickerBar() {
  const track = document.getElementById('ticker-track');
  if (!track) return;

  const segment = CFG.tickerSymbols.map(sym => {
    const q     = S.quotes[sym];
    const label = CFG.tickerLabels[sym] || sym;
    if (!q) {
      return `<span class="ticker-item">
        <span class="t-name">${label}</span>
        <span class="t-price">—</span>
      </span>`;
    }
    const up  = q.changePercent >= 0;
    const cls = up ? 'up' : 'down';
    const arr = up ? '▲' : '▼';
    return `<span class="ticker-item">
      <span class="t-name">${label}</span>
      <span class="t-price">${fmtNum(q.price, 2)}</span>
      <span class="t-chg ${cls}">${arr}${fmtPct(q.changePercent)}</span>
    </span>`;
  }).join('');

  // Duplicate for seamless CSS loop
  track.innerHTML = segment + segment;
}

// ────────────────────────────────────────────────────────────
// RENDER — SUMMARY CARDS
// ────────────────────────────────────────────────────────────
function renderSummaryCards() {
  const totalSEK  = S.stocks.reduce((a, s) => a + s.valueSEK, 0)
                  + S.funds.reduce((a, f)  => a + f.valueSEK, 0);
  const returnSEK = S.stocks.reduce((a, s) => a + s.returnSEK, 0)
                  + S.funds.reduce((a, f)  => a + f.returnSEK, 0);
  const costSEK   = totalSEK - returnSEK;
  const retPct    = costSEK > 0 ? (returnSEK / costSEK) * 100 : 0;

  // Day P&L (use live day% when available)
  let dayPnL = 0;
  S.stocks.forEach(s => {
    const pct = (s.liveDayPct ?? s.dayChange) || 0;
    dayPnL += s.valueSEK * (pct / 100);
  });
  S.funds.forEach(f => { dayPnL += f.valueSEK * ((f.dayChange || 0) / 100); });
  const dayPct = totalSEK > 0 ? (dayPnL / totalSEK) * 100 : 0;

  // Allocation (EU = non-USD stocks + funds; US = USD stocks)
  const euSEK = S.stocks.filter(s => s.currency !== 'USD').reduce((a, s) => a + s.valueSEK, 0)
              + S.funds.reduce((a, f) => a + f.valueSEK, 0);
  const usSEK = S.stocks.filter(s => s.currency === 'USD').reduce((a, s) => a + s.valueSEK, 0);
  const euPct = totalSEK ? ((euSEK / totalSEK) * 100).toFixed(0) : 0;
  const usPct = totalSEK ? ((usSEK / totalSEK) * 100).toFixed(0) : 0;

  // Set values
  setText('cv-total',    displayAmt(totalSEK));
  setText('cv-total-alt', S.displayCur === 'SEK'
    ? `≈ $${fmtNum(totalSEK / S.fx.USD)}`
    : `≈ ${fmtNum(totalSEK)} kr`);

  setCard('cv-day',    displayAmt(dayPnL), pctClass(dayPnL));
  setCard('cv-day-pct', fmtPct(dayPct),   pctClass(dayPct), true);

  setCard('cv-return',     displayAmt(returnSEK), pctClass(returnSEK));
  setCard('cv-return-pct', fmtPct(retPct),        pctClass(retPct), true);

  setText('cv-usdsek', fmtNum(S.fx.USD, 4) + ' kr');
  document.getElementById('cv-allocation').innerHTML =
    `<span class="alloc-eu">EU ${euPct}%</span> · <span class="alloc-us">US ${usPct}%</span>`;
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function setCard(id, val, cls, isSub = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = val;
  el.className = (isSub ? 'card-sub' : 'card-value') + ' ' + cls;
}

// ────────────────────────────────────────────────────────────
// RENDER — STOCKS TABLE
// ────────────────────────────────────────────────────────────
function getVisibleStocks() {
  let rows = S.stocks.filter(s => {
    if (S.stockFilter !== 'ALL' && s.currency !== S.stockFilter) return false;
    if (S.stockSearch) {
      const q = S.stockSearch.toLowerCase();
      return s.name.toLowerCase().includes(q) || (s.ticker || '').toLowerCase().includes(q);
    }
    return true;
  });

  const { col, dir } = S.stockSort;
  rows.sort((a, b) => {
    const av = sortVal(a, col), bv = sortVal(b, col);
    if (typeof av === 'string') return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    return dir === 'asc' ? av - bv : bv - av;
  });
  return rows;
}

function sortVal(item, col) {
  switch (col) {
    case 'name':      return item.name;
    case 'currency':  return item.currency;
    case 'qty':       return item.qty;
    case 'gav':       return item.gav;
    case 'price':     return item.livePrice ?? item.price;
    case 'change':    return item.liveDayPct ?? item.dayChange;
    case 'value':     return item.valueSEK;
    case 'returnPct': return item.returnPct;
    case 'returnAbs': return item.returnSEK;
    default:          return 0;
  }
}

function renderStocksTable() {
  const tbody = document.getElementById('stocks-tbody');
  if (!tbody) return;

  const rows = getVisibleStocks();
  document.getElementById('stocks-count').textContent = rows.length;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="loading-row">No holdings match the current filter.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map(s => stockRow(s)).join('');

  // Inject DOM-based logo + sparkline (can't do this in innerHTML)
  rows.forEach(s => {
    const idx = S.stocks.indexOf(s);
    const logoCell = document.getElementById(`sl-${idx}`);
    if (logoCell) logoCell.appendChild(buildLogoEl(s.name));
    if (s.ticker && S.sparkData[s.ticker]) {
      drawSparkline(`spark-s-${idx}`, S.sparkData[s.ticker], s.returnPct >= 0);
    }
  });
}

function stockRow(s) {
  const idx       = S.stocks.indexOf(s);
  const price     = s.livePrice  ?? s.price;
  const dayPct    = s.liveDayPct ?? s.dayChange;
  const valDisp   = displayAmt(s.valueSEK);
  const retDisp   = displayAmt(s.returnSEK);
  const liveMark  = s.livePrice ? '' : 'style="opacity:0.7"';

  // Last-buy annotation: show (+qty) and (buy price) if a new purchase was detected
  const lb       = S.lastBuy[s.name];
  const qtyDec   = s.qty % 1 !== 0 ? 4 : 0;
  const qtyCell  = lb
    ? `${fmtNum(s.qty, qtyDec)}<span class="lb-tag">(+${fmtNum(lb.qty, lb.qty % 1 ? 4 : 0)})</span>`
    : fmtNum(s.qty, qtyDec);
  const priceCell = lb
    ? `${fmtNum(price, 2)}<span class="lb-tag">(${fmtNum(lb.price, 2)})</span>`
    : fmtNum(price, 2);

  return `<tr>
    <td class="col-logo" id="sl-${idx}"></td>
    <td class="col-name">
      <div class="name-cell">
        <span class="stock-name" title="${escHtml(s.name)}">${escHtml(s.name)}</span>
        ${s.ticker ? `<span class="stock-ticker">${s.ticker}</span>` : ''}
      </div>
    </td>
    <td class="col-cur"><span class="cur-badge">${s.currency}</span></td>
    <td>${qtyCell}</td>
    <td ${liveMark}>${fmtNum(s.gav, 2)}</td>
    <td ${liveMark}>${priceCell}</td>
    <td class="${pctClass(dayPct)}">${fmtPct(dayPct)}</td>
    <td>${valDisp}</td>
    <td class="${pctClass(s.returnPct)}">${fmtPct(s.returnPct)}</td>
    <td class="${pctClass(s.returnSEK)}">${retDisp}</td>
    <td class="col-spark">
      <canvas id="spark-s-${idx}" width="80" height="32" class="sparkline-canvas"></canvas>
    </td>
  </tr>`;
}

// ────────────────────────────────────────────────────────────
// RENDER — FUNDS TABLE
// ────────────────────────────────────────────────────────────
function getVisibleFunds() {
  let rows = S.funds.filter(f => {
    if (!S.fundsSearch) return true;
    return f.name.toLowerCase().includes(S.fundsSearch.toLowerCase());
  });

  const { col, dir } = S.fundsSort;
  rows.sort((a, b) => {
    const av = sortVal(a, col), bv = sortVal(b, col);
    if (typeof av === 'string') return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    return dir === 'asc' ? av - bv : bv - av;
  });
  return rows;
}

function renderFundsTable() {
  const tbody = document.getElementById('funds-tbody');
  if (!tbody) return;

  const rows = getVisibleFunds();
  document.getElementById('funds-count').textContent = rows.length;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="loading-row">No funds match the filter.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map(f => fundRow(f)).join('');

  rows.forEach(f => {
    const idx      = S.funds.indexOf(f);
    const logoCell = document.getElementById(`fl-${idx}`);
    if (logoCell) logoCell.appendChild(buildLogoEl(f.name));
  });
}

function fundRow(f) {
  const idx      = S.funds.indexOf(f);
  const valDisp  = displayAmt(f.valueSEK);
  const retDisp  = displayAmt(f.returnSEK);

  const lb        = S.lastBuy[f.name];
  const qtyCell   = lb
    ? `${fmtNum(f.qty, 4)}<span class="lb-tag">(+${fmtNum(lb.qty, 4)})</span>`
    : fmtNum(f.qty, 4);
  const priceCell = lb
    ? `${fmtNum(f.price, 2)}<span class="lb-tag">(${fmtNum(lb.price, 2)})</span>`
    : fmtNum(f.price, 2);

  return `<tr>
    <td class="col-logo" id="fl-${idx}"></td>
    <td class="col-name">
      <div class="name-cell">
        <span class="stock-name" title="${escHtml(f.name)}">${escHtml(f.name)}</span>
      </div>
    </td>
    <td class="col-cur"><span class="cur-badge">${f.currency}</span></td>
    <td>${qtyCell}</td>
    <td>${fmtNum(f.gav, 2)}</td>
    <td>${priceCell}</td>
    <td class="${pctClass(f.dayChange)}">${fmtPct(f.dayChange)}</td>
    <td>${valDisp}</td>
    <td class="${pctClass(f.returnPct)}">${fmtPct(f.returnPct)}</td>
    <td class="${pctClass(f.returnSEK)}">${retDisp}</td>
    <td class="col-spark">
      <canvas id="spark-f-${idx}" width="80" height="32" class="sparkline-canvas"></canvas>
    </td>
  </tr>`;
}

// ────────────────────────────────────────────────────────────
// RENDER — WATCHLIST SIDEBAR
// ────────────────────────────────────────────────────────────
const WATCHLIST = [
  { sym: '^OMX',    label: 'OMXS30' },
  { sym: '^GDAXI',  label: 'DAX' },
  { sym: 'ES=F',    label: 'S&P 500F' },
  { sym: 'GC=F',    label: 'Gold' },
  { sym: 'USDSEK=X',label: 'USD/SEK' },
  { sym: 'NVDA',    label: 'NVIDIA' },
  { sym: 'AAPL',    label: 'Apple' },
  { sym: 'MSFT',    label: 'Microsoft' },
  { sym: 'TSLA',    label: 'Tesla' },
  { sym: 'META',    label: 'Meta' },
  { sym: 'NOVO-B.CO', label: 'Novo Nordisk' },
];

function renderWatchlist() {
  const el = document.getElementById('watchlist-container');
  if (!el) return;

  el.innerHTML = WATCHLIST.map(({ sym, label }) => {
    const q   = S.quotes[sym];
    const up  = q ? q.changePercent >= 0 : null;
    const cls = up === null ? 'flat' : up ? 'up' : 'down';
    const shortSym = sym.replace(/[^=F]/g, s => s).replace('^', '').replace('=X', '').replace('=F', '');

    return `<div class="wl-item">
      <div class="wl-left">
        <span class="wl-sym">${escHtml(shortSym)}</span>
        <span class="wl-name">${escHtml(label)}</span>
      </div>
      <div class="wl-right">
        <span class="wl-price">${q ? fmtNum(q.price, 2) : '—'}</span>
        <span class="wl-chg ${cls}">${q ? fmtPct(q.changePercent) : '—'}</span>
      </div>
    </div>`;
  }).join('');
}

// ────────────────────────────────────────────────────────────
// TECHNICAL ANALYSIS — TOMORROW'S SIGNALS
// 8-factor model: MACD · RSI · Bollinger · Stochastic ·
//                 SMA crossover · Volume · Pivot Points · ROC
// ────────────────────────────────────────────────────────────

/** Fetch ~60 trading days OHLCV (MACD needs 35+ days) */
async function fetchOHLCV(symbol) {
  const url = `${CFG.yahooBase}/v8/finance/chart/${symbol}?interval=1d&range=3mo&includePrePost=false`;
  try {
    const d = await yahooGet(url);
    const r = d?.chart?.result?.[0];
    if (!r) return null;
    const ts = r.timestamp || [];
    const q  = r.indicators?.quote?.[0] || {};
    const items = ts.map((t, i) => ({
      t,
      open:   q.open?.[i]   ?? null,
      high:   q.high?.[i]   ?? null,
      low:    q.low?.[i]    ?? null,
      close:  q.close?.[i]  ?? null,
      volume: q.volume?.[i] ?? null,
    })).filter(x => x.close != null && x.high != null && x.low != null);
    return items.length >= 20 ? items : null;
  } catch (_) {
    return null;
  }
}

/** Build EMA series starting after the seed period */
function emaArray(data, period) {
  if (data.length < period) return [];
  const k   = 2 / (period + 1);
  let   ema = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
  const out = [];
  for (let i = period; i < data.length; i++) {
    ema = data[i] * k + ema * (1 - k);
    out.push(ema);
  }
  return out;
}

/** Wilder RSI (14-period) */
function calcRSI(closes, period = 14) {
  if (closes.length < period + 1) return 50;
  let gSum = 0, lSum = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) gSum += d; else lSum -= d;
  }
  let avgG = gSum / period, avgL = lSum / period;
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgG = (avgG * (period - 1) + Math.max(0,  d)) / period;
    avgL = (avgL * (period - 1) + Math.max(0, -d)) / period;
  }
  return avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
}

/** SMA of last N values */
function calcSMA(arr, period) {
  if (arr.length < period) return null;
  return arr.slice(-period).reduce((a, b) => a + b, 0) / period;
}

/** Classic floor-trader pivot points */
function calcPivots(h, l, c) {
  const pp = (h + l + c) / 3;
  return { pp, r1: 2*pp - l, r2: pp + (h - l), s1: 2*pp - h, s2: pp - (h - l) };
}

/**
 * MACD (12, 26, 9)
 * Returns { macd, signal, histogram, crossoverBull, crossoverBear }
 * or null if not enough data.
 */
function calcMACD(closes) {
  const e12 = emaArray(closes, 12);
  const e26 = emaArray(closes, 26);
  if (e12.length < 9 || e26.length < 9) return null;
  const len     = Math.min(e12.length, e26.length);
  const macdArr = Array.from({ length: len }, (_, i) =>
    e12[e12.length - len + i] - e26[e26.length - len + i]);
  const sigArr  = emaArray(macdArr, 9);
  if (!sigArr.length) return null;
  const macd    = macdArr[macdArr.length - 1];
  const signal  = sigArr[sigArr.length - 1];
  const prevM   = macdArr[macdArr.length - 2];
  const prevS   = sigArr.length >= 2 ? sigArr[sigArr.length - 2] : null;
  return {
    macd, signal,
    histogram:     macd - signal,
    crossoverBull: prevS != null && prevM <= prevS && macd > signal,
    crossoverBear: prevS != null && prevM >= prevS && macd < signal,
  };
}

/** Bollinger Bands (20, 2σ) */
function calcBB(closes, period = 20) {
  if (closes.length < period) return null;
  const sl  = closes.slice(-period);
  const sma = sl.reduce((a, b) => a + b, 0) / period;
  const std = Math.sqrt(sl.reduce((a, b) => a + (b - sma) ** 2, 0) / period);
  return { upper: sma + 2*std, middle: sma, lower: sma - 2*std };
}

/** Stochastic %K (14-period raw, no smoothing) */
function calcStochK(data, period = 14) {
  if (data.length < period) return null;
  const sl = data.slice(-period);
  const hh = Math.max(...sl.map(d => d.high));
  const ll = Math.min(...sl.map(d => d.low));
  return hh === ll ? 50 : ((data[data.length - 1].close - ll) / (hh - ll)) * 100;
}

/**
 * 8-factor technical scoring.
 * Indicators:  MACD (3pt) · RSI (2pt) · Bollinger (2pt) ·
 *              Stochastic (2pt) · SMA crossover (2.5pt) ·
 *              Volume (1.5pt) · Pivot (1pt) · ROC-5 (1pt)
 * Max absolute score ≈ 15.
 * Returns { score, confidence, direction, signals, rsi, stochK, macdState, currentPrice }
 */
function scoreTechnicals(data) {
  if (!data || data.length < 20) return null;

  const closes = data.map(d => d.close);
  const last   = data[data.length - 1];
  const cur    = last.close;

  const rsi    = calcRSI(closes);
  const macd   = calcMACD(closes);
  const bb     = calcBB(closes);
  const stochK = calcStochK(data);
  const sma5   = calcSMA(closes, 5);
  const sma20  = calcSMA(closes, 20);
  const sma5p  = calcSMA(closes.slice(0, -1), 5);
  const sma20p = calcSMA(closes.slice(0, -1), 20);
  const pivots = calcPivots(last.high, last.low, last.close);

  let score = 0;
  const signals = [];

  // ── 1. MACD (max ±3) ────────────────────────────────────
  if (macd) {
    if      (macd.crossoverBull)                         { score += 3.0; signals.push('MACD bullish cross'); }
    else if (macd.crossoverBear)                         { score -= 3.0; signals.push('MACD bearish cross'); }
    else if (macd.macd > macd.signal && macd.macd > 0)  { score += 2.0; signals.push('MACD uptrend'); }
    else if (macd.macd < macd.signal && macd.macd < 0)  { score -= 2.0; signals.push('MACD downtrend'); }
    else if (macd.macd > macd.signal)                    { score += 1.0; signals.push('MACD positive'); }
    else                                                 { score -= 1.0; signals.push('MACD negative'); }
  }

  // ── 2. RSI (max ±2) ─────────────────────────────────────
  if      (rsi < 30) { score += 2.0; signals.push('RSI oversold'); }
  else if (rsi < 40) { score += 1.0; signals.push('RSI weak'); }
  else if (rsi > 70) { score -= 2.0; signals.push('RSI overbought'); }
  else if (rsi > 60) { score -= 1.0; signals.push('RSI high'); }

  // ── 3. Bollinger Bands (max ±2) ─────────────────────────
  if (bb) {
    const bbPct = (cur - bb.lower) / (bb.upper - bb.lower); // 0 = at lower, 1 = at upper
    if      (cur  < bb.lower)  { score += 2.0; signals.push('BB oversold'); }
    else if (bbPct < 0.15)     { score += 1.5; signals.push('BB near lower'); }
    else if (cur  > bb.upper)  { score -= 2.0; signals.push('BB overbought'); }
    else if (bbPct > 0.85)     { score -= 1.5; signals.push('BB near upper'); }
  }

  // ── 4. Stochastic %K (max ±2) ───────────────────────────
  if (stochK != null) {
    if      (stochK < 20) { score += 2.0; signals.push('Stoch oversold'); }
    else if (stochK < 30) { score += 1.0; signals.push('Stoch low'); }
    else if (stochK > 80) { score -= 2.0; signals.push('Stoch overbought'); }
    else if (stochK > 70) { score -= 1.0; signals.push('Stoch high'); }
  }

  // ── 5. SMA crossover (max ±2.5) ─────────────────────────
  if (sma5 && sma20 && sma5p != null && sma20p != null) {
    const above    = sma5  > sma20;
    const wasAbove = sma5p > sma20p;
    if      ( above && !wasAbove) { score += 2.5; signals.push('Golden cross'); }
    else if (!above &&  wasAbove) { score -= 2.5; signals.push('Death cross'); }
    else if  (above)              { score += 1.0; signals.push('Above MA'); }
    else                          { score -= 1.0; signals.push('Below MA'); }
  }

  // ── 6. Volume confirmation (max ±1.5) ───────────────────
  if (data.length >= 5) {
    const avgVol  = data.slice(-5).reduce((a, d) => a + (d.volume || 0), 0) / 5;
    const lastVol = last.volume || 0;
    const chg     = last.close - data[data.length - 2].close;
    if (lastVol > avgVol * 1.3) {
      if (chg > 0) { score += 1.5; signals.push('High-vol up day'); }
      else         { score -= 1.5; signals.push('High-vol down day'); }
    }
  }

  // ── 7. Pivot Points (max ±1) ────────────────────────────
  const near = 0.012;
  if (Math.abs(cur - pivots.s1) / cur < near) { score += 1.0; signals.push('At S1 support'); }
  if (Math.abs(cur - pivots.s2) / cur < near) { score += 0.5; signals.push('At S2 support'); }
  if (Math.abs(cur - pivots.r1) / cur < near) { score -= 1.0; signals.push('At R1 resistance'); }
  if (Math.abs(cur - pivots.r2) / cur < near) { score -= 0.5; signals.push('At R2 resistance'); }
  score += cur > pivots.pp ? 0.3 : -0.3;

  // ── 8. Rate of Change 5-day (max ±1) ────────────────────
  if (closes.length >= 6) {
    const roc = (closes[closes.length-1] - closes[closes.length-6]) / closes[closes.length-6] * 100;
    if      (roc >  3) { score += 1.0; signals.push(`ROC +${roc.toFixed(1)}%`); }
    else if (roc >  1) { score += 0.5; signals.push(`ROC +${roc.toFixed(1)}%`); }
    else if (roc < -3) { score -= 1.0; signals.push(`ROC ${roc.toFixed(1)}%`); }
    else if (roc < -1) { score -= 0.5; signals.push(`ROC ${roc.toFixed(1)}%`); }
  }

  // Signal strength: how much do indicators agree? (0–92%)
  const MAX_SCORE = 15;
  const confidence = Math.min(92, Math.round(Math.abs(score) / MAX_SCORE * 100));
  const macdState  = macd ? (macd.macd > macd.signal ? 'bull' : 'bear') : '—';

  return {
    score,
    confidence,
    direction: score >= 0 ? 'up' : 'down',
    signals:   signals.slice(0, 4),
    rsi:       +rsi.toFixed(1),
    stochK,
    macdState,
    currentPrice: cur,
    pivots,
  };
}

/** Signal label from score magnitude */
function signalLabel(score, direction) {
  const abs = Math.abs(score);
  const up  = direction === 'up';
  if (abs >= 7) return up ? 'Strong Buy'  : 'Strong Sell';
  if (abs >= 4) return up ? 'Buy'         : 'Sell';
  return               up ? 'Weak Buy'    : 'Weak Sell';
}

/** Background: fetch OHLCV for all portfolio stocks, score them, render widget */
async function loadPredictions() {
  const tickers = [...new Set(S.stocks.filter(s => s.ticker).map(s => s.ticker))];
  const badge   = document.getElementById('pred-badge');
  if (badge) badge.textContent = `Analyzing ${tickers.length} stocks…`;

  const scored = [];
  for (const sym of tickers) {
    if (!S.ohlcv[sym]) {
      const data = await fetchOHLCV(sym);
      if (data) S.ohlcv[sym] = data;
    }
    if (S.ohlcv[sym]) {
      const result = scoreTechnicals(S.ohlcv[sym]);
      if (result) {
        const stock = S.stocks.find(s => s.ticker === sym);
        scored.push({ sym, stock, ...result });
      }
    }
    await sleep(200);
  }

  // All scored stocks — take top 5 by score (up) and bottom 5 by score (down)
  const upList   = scored.filter(x => x.score > 0).sort((a, b) => b.score - a.score).slice(0, 5);
  const downList = scored.filter(x => x.score < 0).sort((a, b) => a.score - b.score).slice(0, 5);

  S.predictions = { up: upList, down: downList };
  renderPredictions();
}

/** Render the predictions widget */
function renderPredictions() {
  const upEl   = document.getElementById('pred-up-list');
  const downEl = document.getElementById('pred-down-list');
  const badge  = document.getElementById('pred-badge');
  if (!upEl || !downEl) return;

  const total = S.predictions.up.length + S.predictions.down.length;
  if (badge) badge.textContent = total
    ? `${total} signals · ${new Date().toLocaleTimeString()}`
    : 'No signals — check console for CORS errors';

  const buildCard = (entry, rank) => {
    const { sym, stock, confidence, rsi, signals, currentPrice, stochK, macdState, score } = entry;
    const name   = stock?.name || sym;
    const price  = currentPrice ? fmtNum(currentPrice, 2) : '—';
    const label  = signalLabel(score, entry.direction);
    const lCls   = entry.direction === 'up' ? 'signal-bull' : 'signal-bear';
    const stoch  = stochK != null ? `Stoch ${stochK.toFixed(0)}` : '';
    return `<div class="pred-card">
      <span class="pred-rank">${rank}</span>
      <div class="pred-logo-wrap" id="plogo-${sym.replace(/[^a-zA-Z0-9]/g, '')}"></div>
      <div class="pred-info">
        <div class="pred-name" title="${escHtml(name)}">${escHtml(name)}</div>
        <div class="pred-ticker">${escHtml(sym)}&nbsp;<span class="pred-signal-label ${lCls}">${label}</span></div>
        <div class="pred-signals">${signals.map(escHtml).join(' · ')}</div>
      </div>
      <div class="pred-right">
        <div class="pred-prob">${confidence}%</div>
        <div class="pred-price">${price}</div>
        <div class="pred-bar-wrap"><div class="pred-bar-fill" style="width:${confidence}%"></div></div>
        <div class="pred-rsi">RSI ${rsi} · ${stoch} · MACD ${macdState}</div>
      </div>
    </div>`;
  };

  upEl.innerHTML   = S.predictions.up.length
    ? S.predictions.up.map((e, i) => buildCard(e, i + 1)).join('')
    : '<div class="pred-loading">No bullish setups in portfolio</div>';

  downEl.innerHTML = S.predictions.down.length
    ? S.predictions.down.map((e, i) => buildCard(e, i + 1)).join('')
    : '<div class="pred-loading">No bearish setups in portfolio</div>';

  // Inject company logos
  [...S.predictions.up, ...S.predictions.down].forEach(entry => {
    const el = document.getElementById('plogo-' + entry.sym.replace(/[^a-zA-Z0-9]/g, ''));
    if (el && entry.stock) el.appendChild(buildLogoEl(entry.stock.name));
  });
}

// ────────────────────────────────────────────────────────────
// RENDER ALL
// ────────────────────────────────────────────────────────────
function renderAll() {
  renderTickerBar();
  renderSummaryCards();
  renderStocksTable();
  renderFundsTable();
}

// ────────────────────────────────────────────────────────────
// STATUS HELPER
// ────────────────────────────────────────────────────────────
function setStatus(type, msg) {
  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('last-updated-time');
  if (text) text.textContent = msg;
  if (dot)  dot.className = `dot ${type}`;
}

// ────────────────────────────────────────────────────────────
// EVENT HANDLERS
// ────────────────────────────────────────────────────────────
function bindEvents() {
  // Currency display toggle
  document.getElementById('currency-toggle')?.addEventListener('click', () => {
    S.displayCur = S.displayCur === 'SEK' ? 'USD' : 'SEK';
    document.getElementById('currency-label-left').textContent  = S.displayCur;
    document.getElementById('currency-label-left').className    = 'cur-active';
    document.getElementById('currency-label-right').textContent = S.displayCur === 'SEK' ? 'USD' : 'SEK';
    document.getElementById('currency-label-right').className   = 'cur-inactive';
    renderAll();
  });

  // Currency filter tabs
  document.getElementById('currency-filter-tabs')?.addEventListener('click', e => {
    const btn = e.target.closest('.filter-tab');
    if (!btn) return;
    document.querySelectorAll('#currency-filter-tabs .filter-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    S.stockFilter = btn.dataset.filter;
    renderStocksTable();
  });

  // Search boxes
  document.getElementById('stocks-search')?.addEventListener('input', e => {
    S.stockSearch = e.target.value.trim();
    renderStocksTable();
  });

  document.getElementById('funds-search')?.addEventListener('input', e => {
    S.fundsSearch = e.target.value.trim();
    renderFundsTable();
  });

  // Column sorting — stocks
  document.getElementById('stocks-table')?.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (S.stockSort.col === col) {
        S.stockSort.dir = S.stockSort.dir === 'asc' ? 'desc' : 'asc';
      } else {
        S.stockSort = { col, dir: 'desc' };
      }
      document.querySelectorAll('#stocks-table th').forEach(t => t.classList.remove('sort-asc', 'sort-desc'));
      th.classList.add(S.stockSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
      renderStocksTable();
    });
  });

  // Column sorting — funds
  document.getElementById('funds-table')?.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (S.fundsSort.col === col) {
        S.fundsSort.dir = S.fundsSort.dir === 'asc' ? 'desc' : 'asc';
      } else {
        S.fundsSort = { col, dir: 'desc' };
      }
      document.querySelectorAll('#funds-table th').forEach(t => t.classList.remove('sort-asc', 'sort-desc'));
      th.classList.add(S.fundsSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
      renderFundsTable();
    });
  });

  // Manual portfolio refresh button
  document.getElementById('refresh-portfolio-btn')?.addEventListener('click', reloadPortfolio);

  // Nav tabs — Portfolio shows everything; Stocks/Funds filter visible sections
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const view = tab.dataset.tab;
      const pred    = document.getElementById('predictions-section');
      const stocks  = document.getElementById('stocks-section');
      const funds   = document.getElementById('funds-section');
      if (view === 'portfolio') {
        pred.style.display   = '';
        stocks.style.display = '';
        funds.style.display  = '';
      } else if (view === 'stocks') {
        pred.style.display   = 'none';
        stocks.style.display = '';
        funds.style.display  = 'none';
      } else if (view === 'funds') {
        pred.style.display   = 'none';
        stocks.style.display = 'none';
        funds.style.display  = '';
      }
    });
  });
}

// ────────────────────────────────────────────────────────────
// INITIALIZATION
// ────────────────────────────────────────────────────────────
async function init() {
  setStatus('loading', 'Loading portfolio…');

  // Load persisted last-buy data from previous session (async: may seed from baseline file)
  await loadLastBuyData();

  try {
    // Load and parse both CSV files in parallel (try fixed names, fallback to dated)
    const [stockRows, fundRows] = await Promise.all([
      loadCSVWithFallback(CFG.stocksFile, CFG.stocksFileFallback),
      loadCSVWithFallback(CFG.fundsFile,  CFG.fundsFileFallback),
    ]);

    S.stocks = stockRows.map(buildStock).filter(s => s.name);
    S.funds  = fundRows.map(buildFund).filter(f => f.name);

    // Resolve Yahoo Finance tickers
    S.stocks.forEach(s => { s.ticker = resolveTickerFor(s); });
    S.funds.forEach(f  => { f.ticker = resolveTickerFor(f); });

    // Detect any new purchases since last session
    detectAndSaveBuys();

    // First render with CSV data only
    renderAll();
    renderWatchlist();
    bindEvents();

    setStatus('loading', 'Fetching live prices…');

    // Fetch live prices (async)
    await refreshPrices();

    // Background: load sparklines + prediction signals
    loadSparklines();
    loadPredictions();

    // Auto-refresh prices every minute
    setInterval(refreshPrices, CFG.refreshMs);

    // Auto-reload portfolio CSVs every 5 minutes (picks up nordnet_sync.py output)
    setInterval(reloadPortfolio, CFG.csvRefreshMs);

  } catch (err) {
    console.error('[init]', err);
    setStatus('', 'Error: ' + err.message);
    const msg = `<tr><td colspan="11" class="loading-row" style="color:var(--red)">
      Failed to load data: ${escHtml(err.message)}</td></tr>`;
    const sb = document.getElementById('stocks-tbody');
    const fb = document.getElementById('funds-tbody');
    if (sb) sb.innerHTML = msg;
    if (fb) fb.innerHTML = msg;
  }
}

document.addEventListener('DOMContentLoaded', init);
