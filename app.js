/* ============================================================
   TRADING DASHBOARD — app.js
   Loads CSV holdings, fetches live prices from Yahoo Finance,
   company logos via Clearbit.
   ============================================================ */

// All Yahoo Finance calls go through server.py's /yahoo/* proxy — no CORS, no
// blocked requests. server.py listens on every interface, so that proxy is
// same-origin whatever hostname the page was opened with (localhost, a LAN IP,
// a machine name). Only a file:// page has no proxy and must call Yahoo direct.
// per-user localStorage key (auth.js adds the user's id suffix so people sharing a browser never share state)
const LS = n => (window.TV ? TV.key(n) : n);
const HAS_PROXY = location.protocol === 'http:' || location.protocol === 'https:';

// ────────────────────────────────────────────────────────────
// CONFIG
// ────────────────────────────────────────────────────────────
const CFG = {
  // One Nordnet export holds every holding: 'Innehav Tabell Export, accno N, DATE.csv'.
  // server.py serves the newest one at /api/holdings (latest file only is ever used).
  holdingsUrl: '/api/holdings',

  // Served by server.py: /yahoo/* is proxied for us — no CORS issues
  // Opened as a file:    direct Yahoo URL (browser/proxy fallbacks in yahooGet)
  yahooBase:  HAS_PROXY ? '/yahoo' : 'https://query1.finance.yahoo.com',

  // Ticker bar symbols + display labels
  tickerSymbols: ['^OMX', '^GDAXI', 'ES=F', 'NQ=F', '^TNX', 'GC=F', 'BTC-USD', 'USDSEK=X', 'EURUSD=X'],
  tickerLabels:  { '^OMX':'OMXS30', '^GDAXI':'DAX', 'ES=F':'SP500F', 'NQ=F':'NASDAQ100F', '^TNX':'US10Y',
                   'GC=F':'GOLD', 'BTC-USD':'BTC/USD', 'USDSEK=X':'USD/SEK', 'EURUSD=X':'EUR/USD' },
  tickerYield:   ['^TNX'],                 // shown as a yield in %, not as a price

  refreshMs:    60_000,       // live-price refresh interval (ms)
  // uploaded files are checked by a small signature request (checkFiles), not by re-reading the CSV
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
  'Arm Holdings ADR':           'ARM',
  'ASML HOLDING':               'ASML.AS',
  'Assa Abloy B':               'ASSA-B.ST',
  'AstraZeneca':                { USD: 'AZN', SEK: 'AZN.ST', default: 'AZN' },
  'Atlas Copco A':              'ATCO-A.ST',
  'Axfood':                     'AXFO.ST',
  'BlackRock':                  'BLK',
  'Bloom Energy A':             'BE',
  'Boston Scientific':          'BSX',
  'Celestica':                  'CLS',
  'Broadcom':                   'AVGO',
  'Chevron':                    'CVX',
  'Cisco Systems':              'CSCO',
  'Coherent':                   'COHR',
  'Clas Ohlson B':              'CLAS-B.ST',
  'Coca-Cola':                  'KO',
  'ConAgra Brands':             'CAG',
  'Delta Air Lines':            'DAL',
  'Eli Lilly':                  'LLY',
  'GE Aerospace':               'GE',
  'General Dynamics':           'GD',
  'Handelsbanken A':            'SHB-A.ST',

  'IBM':                        'IBM',
  'Infineon Technologies AG':   'IFX.DE',
  'Intel':                      'INTC',
  'Investor A':                 'INVE-A.ST',
  'iShares Core MSCI EM IMI UCITS ETF USD (Acc)':                          'IS3N.DE',
  'iShares Dow Jones Global Leaders Screened UCITS ETF USD (Acc)':         'IUSL.DE',
  'JP Morgan Chase':            'JPM',
  'KLA':                        'KLAC',
  'Kongsberg Gruppen':          'KOG.OL',
  'Lockheed Martin Corp.':      'LMT',
  'Lululemon Athletica':        'LULU',
  'Lumentum':                   'LITE',
  'Lundin Gold':                'LUG.ST',
  'Lundin Mining Corporation':  'LUMI.ST',
  'Meta Platforms A':           'META',
  'Micron Technology':          'MU',
  'Microsoft':                  'MSFT',
  'Nebius Group':               'NBIS',
  'Netflix':                    'NFLX',
  'Nike':                       'NKE',
  'Nokia':                      'NOKIA-SEK.ST',
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
  'Sandisk':                    'SNDK',
  'Schneider Electric SE':      'SU.PA',
  'Seagate Technology':         'STX',
  'SEB A':                      'SEB-A.ST',
  'Siemens AG':                 'SIE.DE',
  'Siemens Energy AG':          'ENR.DE',
  'SKF B':                      'SKF-B.ST',
  'SoFi Technologies':          'SOFI',
  'SPDR S&P 500 ETF USD Acc':   'SPY5.DE',
  'SPDR S&P 500 UCITS ETF (Acc)': 'SPYL.DE',
  'Spotify':                    'SPOT',
  'STMicroelectronics NV':      'STMPA.PA',
  'SS SPDR Dow Jones Global Real Estate UCITS ETF': 'SPYJ.DE',
  'Swedbank A':                 'SWED-A.ST',
  'TE Connectivity':            'TEL',
  'Tesla':                      'TSLA',
  'The Trade Desk A':           'TTD',
  'VanEck Defense ETF A USD Acc':   'DFNS.L',
  'VanEck Semiconductor ETF':       'VVSM.DE',
  'Vanguard FTSE All-World High Dividend Yield UCITS ETF - (USD) Acc': 'VGWE.DE',
  'Vanguard S&P 500 UCITS ETF - (USD) Acc': 'VUSA.L',
  'Vår Energi':                 'VAR.OL',
  'Volvo B':                    'VOLV-B.ST',
  'Walmart':                    'WMT',
  'Wärtsilä B':                 'WRT1V.HE',
  'Western Digital':            'WDC',
  'Workday A':                  'WDAY',
  'XACT OMXS30 ESG ETF':        'XACT-OMXS30.ST',
  'Xetra-Gold':                 '4GLD.DE',
  'Xtrackers Artificial Intelligence & Big Data UCITS ETF 1C': 'XAIX.DE',
  'Xtrackers Russell 2000 ETF 1C': 'XRS2.DE',
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
  'Arm Holdings ADR':       'arm.com',
  'ASML HOLDING':           'asml.com',
  'Assa Abloy B':           'assaabloy.com',
  'AstraZeneca':            'astrazeneca.com',
  'Atlas Copco A':          'atlascopco.com',
  'Axfood':                 'axfood.se',
  'BlackRock':              'blackrock.com',
  'Bloom Energy A':         'bloomenergy.com',
  'Boston Scientific':      'bostonscientific.com',
  'Broadcom':               'broadcom.com',
  'Chevron':                'chevron.com',
  'Cisco Systems':          'cisco.com',
  'Coherent':               'coherent.com',
  'Clas Ohlson B':          'clasohlson.com',
  'Coca-Cola':              'coca-cola.com',
  'ConAgra Brands':         'conagrabrands.com',
  'Delta Air Lines':        'delta.com',
  'Eli Lilly':              'lilly.com',
  'GE Aerospace':           'ge.com',
  'General Dynamics':       'gd.com',
  'Handelsbanken A':        'handelsbanken.se',
  'IBM':                    'ibm.com',
  'Infineon Technologies AG': 'infineon.com',
  'Intel':                  'intel.com',
  'Investor A':             'investorab.com',
  'JP Morgan Chase':        'jpmorganchase.com',
  'KLA':                    'kla.com',
  'Kongsberg Gruppen':      'kongsberg.com',
  'Lockheed Martin Corp.':  'lockheedmartin.com',
  'Lululemon Athletica':    'lululemon.com',
  'Lumentum':               'lumentum.com',
  'Lundin Gold':            'lundingold.com',
  'Lundin Mining Corporation': 'lundinmining.com',
  'Meta Platforms A':       'meta.com',
  'Micron Technology':      'micron.com',
  'Microsoft':              'microsoft.com',
  'Netflix':                'netflix.com',
  'Nike':                   'nike.com',
  'Nokia':                  'nokia.com',
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
  'Sandisk':                'sandisk.com',
  'Schneider Electric SE':  'se.com',
  'Seagate Technology':     'seagate.com',
  'SEB A':                  'seb.se',
  'Siemens AG':             'siemens.com',
  'Siemens Energy AG':      'siemens-energy.com',
  'SKF B':                  'skf.com',
  'SoFi Technologies':      'sofi.com',
  'SpaceX':                 'spacex.com',
  'Spotify':                'spotify.com',
  'STMicroelectronics NV':  'st.com',
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
  predictions:   { up: [], down: [] },
  charts:        {},   // canvasId → Chart instance
  displayCur:    'SEK',
  stockFilter:   'ALL',
  stockSearch:   '',
  fundsSearch:   '',
  stockSort:     { col: 'value', dir: 'desc' },
  fundsSort:     { col: 'value', dir: 'desc' },
  snap:          null, // GET /api/snapshot: the server's ONE valuation (totals + every holding). The page does no pricing of its own
  snapByName:    new Map(),   // holding name → snapshot asset
  snapState:     'loading',   // 'loading' | 'ok' | 'failed'
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
  const resp = await fetch(filename + (filename.includes('?') ? '&' : '?') + 't=' + Date.now());
  if (!resp.ok) throw new Error(`Cannot load ${filename}: HTTP ${resp.status}`);

  const src = resp.headers.get('X-Source-File');   // set by /api/holdings
  if (src) S.holdingsFile = decodeURIComponent(src);

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

  // Nordnet writes non-breaking spaces in headers ('Värde SEK') - normalise them
  const headers = lines[0].split('\t').map(h => h.replace(/ /g, ' ').trim());
  return lines.slice(1).map(line => {
    const cols = line.split('\t').map(c => c.trim());
    const obj  = {};
    headers.forEach((h, i) => { obj[h] = cols[i] ?? ''; });
    return obj;
  }).filter(r => r[headers[0]]); // skip empty rows
}

// Combined export columns: Namn | Valuta | Antal | GAV/snittkurs | Idag % | Senaste kurs |
//                          Belåningsv. SEK | Värde SEK | Avkast. % | Avkast. SEK
function buildHolding(raw) {
  const qty   = parseSE(raw['Antal']);
  const price = parseSE(raw['Senaste kurs']);
  const valueSEK  = parseSE(raw['Värde SEK']);
  const returnSEK = parseSE(raw['Avkast. SEK']);
  return {
    name:       (raw['Namn'] || '').trim(),
    currency:   (raw['Valuta'] || 'SEK').trim(),
    qty,
    gav:        parseSE(raw['GAV/snittkurs']),
    dayChange:  parseSE(raw['Idag %']),
    price,
    value:      qty * price,
    valueSEK,
    returnPct:  parseSE(raw['Avkast. %']),
    returnSEK,
    ticker:     null,
    livePrice:  null,
    liveDayPct: null,
  };
}

// The export has no instrument type. Mutual funds (Nordnet index funds, Allemansfond, AuAg)
// go to the Funds table; stocks, ETFs and ETCs go to Stocks. Same rule as trade_analytics.py.
function isFundName(name) {
  const n = name.toLowerCase();
  if (/(etf|etc|ucits)/.test(n) || n.includes('xetra-gold')) return false;
  return ['index', 'indeks', 'indeksi', 'allemansfond', ' fund', 'fond', 'auag',
          'nordea alfa', 'global index'].some(w => n.includes(w));
}

// ────────────────────────────────────────────────────────────
// LAST BUY SNAPSHOT TRACKING
// Persists portfolio state in localStorage so new purchases
// are detected on next CSV load and shown as (+qty) / (price)
// ────────────────────────────────────────────────────────────
async function loadLastBuyData() {
  try {
    S.lastBuy   = JSON.parse(localStorage.getItem(LS('portfolio_lastbuy'))  || '{}');
    S._snapshot = JSON.parse(localStorage.getItem(LS('portfolio_snapshot')) || '{}');
  } catch (_) {
    S.lastBuy   = {};
    S._snapshot = {};
  }

  // Always fetch the profile's baseline from /api/baseline (built by the server from the previous export; was portfolio_baseline.json, written by nordnet_sync.py, just BEFORE
  // overwriting the CSVs).  If the baseline is newer than the localStorage
  // snapshot, use it — this ensures buy detection works after every sync.
  try {
    const resp = await fetch('/api/baseline?t=' + Date.now(), { cache: 'no-store' });
    if (resp.ok) {
      const baseline = await resp.json();
      const baselineTs = baseline.__ts || 0;
      const localTs    = Number(localStorage.getItem(LS('portfolio_snapshot_ts')) || 0);
      if (baselineTs > localTs || !Object.keys(S._snapshot).length) {
        // Baseline is fresher than localStorage — replace snapshot AND wipe stale
        // lastBuy so detectAndSaveBuys() starts clean from this known-good baseline
        const clean = Object.fromEntries(
          Object.entries(baseline).filter(([k]) => k !== '__ts'));
        S._snapshot = clean;
        S.lastBuy   = {};
        console.log('[snapshot] Seeded from the profile baseline (ts=' + baselineTs + ')');
      }
    }
  } catch (_) {}
}

/** Compare current holdings to snapshot; record any qty increases or new positions as buys. */
function detectAndSaveBuys() {
  const snap        = S._snapshot;
  const hasSnapshot = Object.keys(snap).length > 0;

  // Clear lastBuy for positions no longer held
  const currentNames = new Set([...S.stocks, ...S.funds].map(item => item.name));
  Object.keys(S.lastBuy).forEach(name => {
    if (!currentNames.has(name)) delete S.lastBuy[name];
  });

  [...S.stocks, ...S.funds].forEach(item => {
    const prev = snap[item.name];
    if (hasSnapshot && !prev) {
      // Brand-new position not in previous snapshot — entire qty is the buy
      S.lastBuy[item.name] = {
        qty:   item.qty,
        price: item.gav,
        date:  new Date().toLocaleDateString('sv-SE'),
      };
    } else if (prev && item.qty > prev.qty + 0.0001) {
      const added    = item.qty - prev.qty;
      // Derive last-buy price from the shift in weighted-average:
      // newAvg * newQty = oldAvg * oldQty + buyPrice * added
      const buyPrice = (item.qty * item.gav - prev.qty * prev.gav) / added;
      S.lastBuy[item.name] = {
        qty:   added,
        price: buyPrice > 0 ? buyPrice : item.gav,
        date:  new Date().toLocaleDateString('sv-SE'),
      };
    } else if (prev && item.qty < prev.qty - 0.0001) {
      // Qty decreased (partial sale) — clear stale annotation
      delete S.lastBuy[item.name];
    }
    // qty unchanged: preserve existing lastBuy (last-buy context still relevant)
  });
  localStorage.setItem(LS('portfolio_lastbuy'), JSON.stringify(S.lastBuy));
  // Save new snapshot for next comparison
  const newSnap = {};
  [...S.stocks, ...S.funds].forEach(item => {
    newSnap[item.name] = { qty: item.qty, gav: item.gav };
  });
  S._snapshot = newSnap;
  const nowTs = Date.now();
  localStorage.setItem(LS('portfolio_snapshot'),    JSON.stringify(newSnap));
  localStorage.setItem(LS('portfolio_snapshot_ts'), nowTs);
}

// ────────────────────────────────────────────────────────────
// CSV LOADING WITH FALLBACK + PORTFOLIO RELOAD
// ────────────────────────────────────────────────────────────
/** Load the newest holdings export and split it into { stocks, funds }. */
async function loadHoldings() {
  const rows = await loadCSV(CFG.holdingsUrl);
  const all  = rows.map(buildHolding).filter(h => h.name);
  return { stocks: all.filter(h => !isFundName(h.name)),
           funds:  all.filter(h =>  isFundName(h.name)) };
}

/** Re-fetch CSVs, detect new buys, re-render tables + refresh prices. */
// Uploaded files: a small signature check; the holdings, plan and calendar are reloaded only when a file really changed
async function checkFiles() {
  try {
    const sig = JSON.stringify(await (await fetch('/api/trades/status', { cache: 'no-store' })).json());
    if (S.filesSig && sig !== S.filesSig) {
      S.filesSig = sig;
      await reloadPortfolio();
      loadPredictions(); loadReports();
      window.dispatchEvent(new CustomEvent('tvfiles'));
      return;
    }
    S.filesSig = sig;
  } catch (e) { /* server briefly busy: next check */ }
}

async function reloadPortfolio() {
  setStatus('loading', 'Refreshing portfolio…');
  try {
    const { stocks, funds } = await loadHoldings();
    S.stocks = stocks;
    S.funds  = funds;
    applySnapshot();                                  // keep the last valuation on the new rows until a fresh one arrives
    S.stocks.forEach(s => { s.ticker = resolveTickerFor(s); });
    S.funds.forEach(f  => { f.ticker = resolveTickerFor(f); });
    detectAndSaveBuys();
    renderAll();
    await Promise.all([refreshSnapshot(), refreshPrices()]);
  } catch (err) {
    console.error('[reloadPortfolio]', err);
    setStatus('', 'Refresh failed: ' + err.message);
  }
}

// ────────────────────────────────────────────────────────────
// TICKER RESOLUTION
// ────────────────────────────────────────────────────────────
function resolveTickerFor(item) {
  // Once the server has valued the portfolio its symbol is the only one used (it is the instrument the price comes from);
  // a holding whose live price is not trusted gets no symbol rather than the symbol of some other instrument.
  if (S.snap) {
    const a = S.snapByName.get(item.name.trim());
    return a && a.live ? a.symbol : null;
  }
  // before the snapshot arrives (or when it failed): the static map, only for the small ticker label in the name cell
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
// Served by server.py : /yahoo/* proxied same-origin — direct fetch, no CORS
// Anything else / proxy down : query1 → query2 → corsproxy.io → allorigins.win
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

  // server.py proxy: simple, reliable, no CORS. Reachable on any hostname,
  // so this is the first try for localhost and LAN clients alike.
  if (HAS_PROXY) {
    try { return await tFetch(url); } catch (_) {}
  }

  // Fallback chain — drop the proxy prefix and talk to Yahoo directly
  const ext    = 'https://query1.finance.yahoo.com';
  const path   = url.replace(/^\/yahoo/, '');
  const absUrl = path.startsWith('/') ? ext + path : path;
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

// ────────────────────────────────────────────────────────────
// LIVE VALUATION
// The server (valuation.py) values the portfolio once: GET /api/snapshot. Rows and tiles only copy those numbers.
// Yahoo quotes fetched here are for the ticker bar and the USD/SEK display rate, never for a holding's value.
// ────────────────────────────────────────────────────────────
function applySnapshot() {
  if (!S.snap) return;
  S.snapByName = new Map(Object.values(S.snap.assets).map(a => [a.name.trim(), a]));
  [...S.stocks, ...S.funds].forEach(r => {
    const a = S.snapByName.get(r.name.trim());
    if (!a) return;                                   // e.g. an export row without a position: keeps its export numbers
    r.valueSEK   = a.value;
    r.returnSEK  = a.unrealized;
    r.returnPct  = a.unrealized_pct;
    r.dayChange  = a.day_pct;
    r.liveDayPct = a.day_pct;
    r.livePrice  = a.live ? a.price : null;
    r.vol        = a.vol_3m ? a.vol_3m.daily : null;
    r.volInfo    = a.vol_3m || null;
  });
}

async function refreshSnapshot() {
  try {
    const r = await fetch('/api/snapshot', { cache: 'no-store' });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.message || d.error || ('HTTP ' + r.status));
    S.snap = d;
    S.snapState = 'ok';
    applySnapshot();
    window.dispatchEvent(new CustomEvent('tvsnapshot', { detail: d }));     // the heat map reuses this valuation instead of asking again
    setStatus('live', 'Live · ' + d.asof.slice(11, 16), 'Live prices ' + d.asof.slice(11, 19) + (S.holdingsFile ? ' · holdings file: ' + S.holdingsFile.replace(/^Innehav Tabell Export, /, '') : ''));
  } catch (e) {
    console.warn('[snapshot]', e.message);
    if (!S.snap) S.snapState = 'failed';              // a failed refresh keeps the last good snapshot
    setStatus('', S.snap ? 'Last valuation' : 'No live prices', S.snap ? 'Live prices: refresh failed, showing the last valuation' : 'Live prices unavailable');
  }
  S.stocks.forEach(s => { s.ticker = resolveTickerFor(s); });
  S.funds.forEach(f  => { f.ticker = resolveTickerFor(f); });
  renderAll();
}

async function refreshPrices() {
  // ticker bar + the USD/SEK rate used by the SEK/USD display toggle
  const results = await fetchQuotesBatch(CFG.tickerSymbols);
  results.forEach(q => {
    S.quotes[q.symbol] = { price: q.regularMarketPrice, changePercent: q.regularMarketChangePercent, change: q.regularMarketChange };
  });
  const usdSek = S.quotes['USDSEK=X'];
  if (usdSek?.price) S.fx.USD = usdSek.price;
  renderAll();
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

// phones: whole kronor and one decimal for % (the same numbers, less noise; the tables fit the screen)
const NARROW = window.matchMedia ? window.matchMedia('(max-width: 560px)') : { matches: false };
function fmtPct(n) {
  if (n == null || isNaN(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(NARROW.matches ? 1 : 2)}%`;
}

function displayAmt(sek) {
  const r = v => NARROW.matches && v != null && !isNaN(v) ? Math.round(v) : v;
  if (S.displayCur === 'USD') return '$' + fmtNum(r(sek / S.fx.USD));
  return fmtNum(r(sek)) + ' kr';
}
if (NARROW.addEventListener) NARROW.addEventListener('change', () => { if (typeof renderAll === 'function') renderAll(); });

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
      <span class="t-price">${CFG.tickerYield.includes(sym) ? q.price.toFixed(2) + '%' : fmtNum(q.price, sym === 'BTC-USD' ? 0 : 2)}</span>
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
  const t = S.snap && S.snap.totals;
  const sub = html => { const el = document.getElementById('cv-total-alt'); if (el) el.innerHTML = html; };
  if (t) {
    // Account value = holdings + cash; All-time result = account value - net deposits; Today's P&L on yesterday's value.
    // Every figure is the server's (valuation.py); nothing is summed from the table rows.
    const alt = S.displayCur === 'SEK' ? `≈ $${fmtNum(t.account / S.fx.USD)}` : `≈ ${fmtNum(t.account)} kr`;
    setCard('cv-total', displayAmt(t.account), '');
    sub(`<span class="pv">holdings ${displayAmt(t.holdings)} · cash ${displayAmt(t.cash)}</span><br>${alt}`);
    setCard('cv-day', displayAmt(t.day_pnl), pctClass(t.day_pnl));
    setCard('cv-day-pct', fmtPct(t.day_pct), pctClass(t.day_pct), true);
    setCard('cv-return', displayAmt(t.all_time), pctClass(t.all_time));
    setCard('cv-return-pct', `${fmtPct(t.all_time_pct)} on deposits · unrealised ${displayAmt(t.unrealized)}`, pctClass(t.all_time), true);
  } else {
    // no valuation yet, or the server could not make one: no number derived from rows is shown as a total
    const failed = S.snapState === 'failed';
    const rows = [...S.stocks, ...S.funds];
    setCard('cv-total', failed ? displayAmt(rows.reduce((a, r) => a + r.valueSEK, 0)) : '—', '');
    sub(failed ? 'holdings at the Nordnet export · cash not included' : 'loading live prices…');
    setCard('cv-day', '—', '');
    setCard('cv-day-pct', failed ? 'unavailable' : 'loading live prices…', '', true);
    setCard('cv-return', '—', '');
    setCard('cv-return-pct', failed ? 'unavailable' : 'loading live prices…', '', true);
  }

  // allocation (EU = everything except USD stocks, US = USD stocks), from the snapshot's values
  let eu = 0, us = 0;
  if (t) Object.values(S.snap.assets).forEach(a => { if (a.ccy === 'USD' && a.type !== 'Fund') us += a.value; else eu += a.value; });
  const tot = eu + us;
  setText('cv-usdsek', fmtNum(S.fx.USD, 4) + ' kr');
  document.getElementById('cv-allocation').innerHTML = tot
    ? `<span class="alloc-eu">EU ${(eu / tot * 100).toFixed(0)}%</span> · <span class="alloc-us">US ${(us / tot * 100).toFixed(0)}%</span>`
    : '<span class="alloc-eu">EU —%</span> · <span class="alloc-us">US —%</span>';
  renderValuationStatus();
}

// One dim line under the tiles that says what the numbers are made of.
function renderValuationStatus() {
  const el = document.getElementById('valuation-status');
  if (!el) return;
  const exp = (S.snap && S.snap.export_date) || ((S.holdingsFile || '').match(/\d{4}-\d{2}-\d{2}/) || [''])[0];
  if (!S.snap) {
    el.textContent = S.snapState === 'failed' ? `Live prices unavailable, showing the Nordnet export of ${exp || 'an earlier date'}.` : 'Valuing the portfolio with live prices…';
    return;
  }
  const t = S.snap.totals, extra = S.stocks.length + S.funds.length - t.positions;
  el.textContent = `Valued ${S.snap.asof.slice(11, 16)} with live prices for ${t.live_positions} of ${t.positions} holdings; the others at the Nordnet export of ${exp}.`
    + (extra > 0 ? ` ${extra} export row${extra > 1 ? 's' : ''} without a position ${extra > 1 ? 'are' : 'is'} listed but not counted.` : '')
    + (S.holdingsFile ? ` Source: ${S.holdingsFile.replace(/^Innehav Tabell Export, /, '')}.` : '');
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

// Daily volatility over 3 months (server: volatility.py, in the snapshot): colour only when it is high
function volCell(x) {
  const v = x.vol, i = x.volInfo;
  if (v == null || !i) return '<td class="col-vol" title="No Yahoo price history for this holding">—</td>';
  const cls = v >= 5 ? 'vol-high' : v >= 3 ? 'vol-mid' : '';
  const tip = `Daily volatility over the last 3 months (${i.days} trading days): the typical size of a one-day move. About ${i.annual}% a year; the average absolute daily move is ${String(i.avg_abs).replace('.', ',')}%.`;
  return `<td class="col-vol ${cls}" title="${escHtml(tip)}">${v.toFixed(2)}%</td>`;
}

// Day %: bold when today's move is at least twice the usual daily move (the Vol 3M column right before it); the tooltip says how many times
function dayCell(pct, x) {
  const v = x.vol, z = (v && pct != null && !isNaN(pct)) ? pct / v : null;
  const tip = z == null ? '' : ` title="Today's move is ${Math.abs(z).toFixed(1)}x its usual daily move (3-month volatility ${v.toFixed(2)}%)"`;
  return `<td class="${pctClass(pct)}${z != null && Math.abs(z) >= 2 ? ' big-move' : ''}"${tip}>${fmtPct(pct)}</td>`;
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
    case 'vol':       return item.vol ?? -1;          // holdings without history sort last when descending
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

  // Inject the DOM-based logo (can't do this in innerHTML)
  rows.forEach(s => {
    const idx = S.stocks.indexOf(s);
    const logoCell = document.getElementById(`sl-${idx}`);
    if (logoCell) logoCell.appendChild(buildLogoEl(s.name));
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
    ${volCell(s)}
    ${dayCell(dayPct, s)}
    <td>${valDisp}</td>
    <td class="${pctClass(s.returnPct)}">${fmtPct(s.returnPct)}</td>
    <td class="${pctClass(s.returnSEK)}">${retDisp}</td>
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
    ${volCell(f)}
    ${dayCell(f.dayChange, f)}
    <td>${valDisp}</td>
    <td class="${pctClass(f.returnPct)}">${fmtPct(f.returnPct)}</td>
    <td class="${pctClass(f.returnSEK)}">${retDisp}</td>
  </tr>`;
}

// ────────────────────────────────────────────────────────────
// TECHNICAL ANALYSIS — TOMORROW'S SIGNALS
// 8-factor model: MACD · RSI · Bollinger · Stochastic ·
//                 SMA crossover · Volume · Pivot Points · ROC
// ────────────────────────────────────────────────────────────

/** Fetch ~60 trading days OHLCV (MACD needs 35+ days) */
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

// ────────────────────────────────────────────────────────────
// REPORTS CALENDAR — earnings + ex-dividend dates of the holdings (server: reports.py, Yahoo calendarEvents)
// ────────────────────────────────────────────────────────────
async function loadReports() {
  const badge = document.getElementById('rep-badge');
  try {
    const r = await (await fetch('/api/reports', { cache: 'no-store' })).json();
    if (!r.ok) throw new Error(r.message || r.error || 'no data');
    S.reports = r;
    renderReports();
    if (r.pending) setTimeout(loadReports, 15_000);        // first load is still fetching dates from Yahoo: ask again soon
  } catch (e) {
    console.warn('[reports]', e.message);
    if (badge) badge.textContent = 'unavailable';
  }
}

function renderReports() {
  const r = S.reports, el = document.getElementById('rep-list'), badge = document.getElementById('rep-badge');
  if (!r || !el) return;
  const c = r.counts;
  if (badge) badge.textContent = (c.today + c.tomorrow + c.week) + (r.pending ? ' · loading' : '');
  const fmtD = d => new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  const item = x => {
    const earn = x.kind === 'earnings';
    const tip = [x.name, earn ? 'Earnings report' : 'Ex-dividend date', fmtD(x.date) + (x.estimate ? ' (date still an estimate)' : ''), x.weight.toFixed(1) + '% of your portfolio', earn && x.eps != null ? 'Analysts expect EPS ' + fmtNum(x.eps, 2) : ''].filter(Boolean).join(' · ');
    return `<div class="rep-item${x.weight >= 2 ? ' big' : ''}" title="${escHtml(tip)}">
      <div class="rep-top"><span class="rep-name">${escHtml(x.name)}</span><span class="rep-tag ${earn ? 'rep-earn' : 'rep-div'}">${earn ? 'EARN' : 'EX-DIV'}</span></div>
      <div class="rep-sub">${fmtD(x.date)}${x.estimate ? ' (est.)' : ''} · ${x.weight.toFixed(1)}%</div></div>`;
  };
  const sec = (title, hint, list) => `<div class="rep-sec"><span>${title}</span><em>${hint}</em><i>${list.length}</i></div>`
    + (list.length ? list.map(item).join('') : '<div class="rep-none">Nothing</div>');
  const g = r.groups;
  el.innerHTML = sec('Today', fmtD(r.today), g.today) + sec('Tomorrow', '', g.tomorrow) + sec('This week', 'next 7 days', g.week)
    + (r.stale ? `<div class="rep-foot">${r.stale} holdings just reported; Yahoo has no new date yet.</div>` : '');
}

// ────────────────────────────────────────────────────────────
// TREND SIGNALS — sidebar summary of the weekly SMA(200) state of every holding (from /api/advice, the same data as the plan)
//   Changed this week      the last weekly close crossed SMA(200)        -> what the category rule does with it
//   May change on Friday   today's price is on the other side of SMA(200) than the last weekly close (the rule waits for Friday)
//   Changed in 2-4 weeks   recent crosses that still matter
// Choppy names (3+ crosses in 12 weeks) are marked: their signal is unreliable.
// ────────────────────────────────────────────────────────────
const SIG_SHORT = { core: 'Index', ai: 'AI / chips', bigtech: 'Big tech', health: 'Health / consumer', industrials: 'Industrials', financials: 'Financials', materials: 'Energy / materials', defensive: 'Gold / bonds' };

function signalAction(v, m, over) {
  const half = v.category === 'ai' || v.category === 'industrials';
  if (v.action === 'TRIM' && v.rule === 'trend_exit') return ['sell', v.when === 'later' ? 'Sell (queued): trend half out' : 'Sell: trend half out'];
  if (v.action === 'TRIM' && v.rule === 'regime_exit') return ['sell', 'Sell: SMA(50) below SMA(200)'];
  if (v.action === 'TRIM' && v.rule === 'size_cap') return ['sell', 'Trim to 4%'];
  if (v.category === 'core' || v.category === 'defensive') return ['keep', 'No timing: keep buying monthly'];
  if (!m.wk_up) return half && v.keep ? ['keep', 'Hold half: keep'] : ['keep', 'Uptrend lost: no new money'];
  if (v.action === 'ADD' || v.action === 'BUYBACK') return ['buy', 'New money OK'];
  if (half && !v.keep) return over ? ['keep', 'Back in trend; group over target'] : ['buy', 'Trend half may come back'];
  return ['keep', 'Uptrend: hold'];
}

function renderSignals() {
  const el = document.getElementById('sig-list'), badge = document.getElementById('sig-badge');
  const r = S.adviceFull;
  if (!el || !r || !r.assets) return;
  const over = new Set(((r.plan && r.plan.categories) || []).filter(c => c.status === 'over').map(c => c.key));
  const rows = Object.values(r.assets).filter(v => !v.closed && v.metrics && v.metrics.wk_up != null);
  if (!rows.length) { el.innerHTML = '<div class="rep-none">Price history is still loading…</div>'; return; }
  const up = rows.filter(v => v.metrics.wk_up), down = rows.filter(v => !v.metrics.wk_up);
  const wUp = up.reduce((s, v) => s + v.weight, 0), wDown = down.reduce((s, v) => s + v.weight, 0), wt = (wUp + wDown) || 1;
  const lastWeek = rows.map(v => v.metrics.wk_date).sort().pop();
  const fmtD = d => new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  const pctS = x => (x > 0 ? '+' : '') + (x * 100).toFixed(1) + '%';
  const item = (v, live) => {
    const m = v.metrics, isUp = live ? m.live_up : m.wk_up;
    const [kind, act] = live ? ['warn', m.live_up ? 'Above now: Friday\'s close decides' : 'Below now: Friday\'s close decides'] : signalAction(v, m, over.has(v.category));
    const dist = live ? m.live_dist : m.wk_dist;
    const strip = (m.wk_hist || []).map(u => `<i class="${u ? 'u' : ''}"></i>`).join('');
    const chop = m.wk_flips12 >= 3 ? `<span class="sig-chop" title="${m.wk_flips12} changes in the last 12 weekly closes: the signal is unreliable for this holding">choppy</span>` : '';
    const tip = [v.name, (SIG_SHORT[v.category] || v.category), live ? `Today ${pctS(m.live_dist)} vs SMA(200); last weekly close ${pctS(m.wk_dist)}` : `Weekly close ${pctS(m.wk_dist)} vs SMA(200) since ${m.wk_since} (${m.wk_weeks} week${m.wk_weeks > 1 ? 's' : ''})`,
      `${v.weight.toFixed(1)}% of account`, act].join(' · ');
    return `<div class="sig-item ${isUp ? 'up' : 'down'}${v.weight >= 2 ? ' big' : ''}" title="${escHtml(tip)}">
      <div class="rep-top"><span class="sig-arrow">${isUp ? '▲' : '▼'}</span><span class="rep-name">${escHtml(v.name)}</span><span class="sig-dist">${pctS(dist)}</span></div>
      <div class="rep-sub">${escHtml(SIG_SHORT[v.category] || '')} · ${live ? 'today' : 'since ' + fmtD(m.wk_since)} · ${v.weight.toFixed(1)}%<span class="sig-strip" aria-hidden="true">${strip}</span>${chop}</div>
      <span class="sig-act ${kind}">${escHtml(act)}</span></div>`;
  };
  const byRisk = (a, b) => (a.metrics.wk_up - b.metrics.wk_up) || b.weight - a.weight;          // turned down first, then by size
  const week = rows.filter(v => v.metrics.wk_weeks === 1).sort(byRisk);
  const maybe = rows.filter(v => v.metrics.live_up !== v.metrics.wk_up).sort((a, b) => b.weight - a.weight);
  const recent = rows.filter(v => v.metrics.wk_weeks >= 2 && v.metrics.wk_weeks <= 4).sort(byRisk);
  const sec = (title, hint, list, live) => `<div class="rep-sec"><span>${title}</span><em>${hint}</em><i>${list.length}</i></div>`
    + (list.length ? list.map(v => item(v, live)).join('') : '<div class="rep-none">Nothing</div>');
  el.innerHTML = `<div class="sig-sum" title="Share of the stock and fund money (with price history) whose last weekly close was above / below its simple 200-day average">
      <b class="up">▲ ${up.length}</b> above · <b class="down">▼ ${down.length}</b> below SMA(200)
      <div class="sig-bar"><i class="up" style="width:${(wUp / wt * 100).toFixed(1)}%"></i><i class="down" style="width:${(wDown / wt * 100).toFixed(1)}%"></i></div>
      ${(wUp / wt * 100).toFixed(0)}% of the money in an uptrend · weekly close ${lastWeek ? fmtD(lastWeek) : '—'}</div>`
    + sec('Changed this week', lastWeek ? 'close ' + fmtD(lastWeek) : '', week, false)
    + sec('May change on Friday', 'price now', maybe, true)
    + sec('Changed in 2–4 weeks', '', recent, false)
    + '<a class="sig-link" href="analytics.html#advice">Every holding by category → Plan &amp; advice</a>';
  if (badge) badge.textContent = String(week.length + maybe.length);
}

function bindSidebarFolds() {
  document.querySelectorAll('#sidebar .side-fold').forEach(b => {
    const panel = document.getElementById(b.dataset.panel), key = LS('tv_fold_' + b.dataset.panel);
    const set = folded => {
      panel.classList.toggle('folded', folded);
      b.setAttribute('aria-expanded', folded ? 'false' : 'true');
      b.setAttribute('aria-label', (folded ? 'Expand ' : 'Collapse ') + panel.querySelector('.sidebar-title').textContent.toLowerCase());
    };
    try { set(localStorage.getItem(key) === '1'); } catch (e) { /* private mode */ }
    b.addEventListener('click', () => {
      const f = !panel.classList.contains('folded');
      set(f);
      try { localStorage.setItem(key, f ? '1' : '0'); } catch (e) { /* private mode */ }
    });
  });
}

/**
 * Add / Trim ideas (replaces the old "Tomorrow's Signals").
 * The old 8-indicator next-day score was back-tested on 77 holdings over 5 years and had no predictive power
 * (Strong Buy: avg -0.25% next day, 43% up days), so the ideas now come from advisor.py (/api/advice):
 * position size, theme concentration, tiny positions / fees and trend health. Rules and back-test: Analytics -> Advice.
 */
async function loadPredictions() {
  const badge = document.getElementById('pred-badge');
  try {
    const r = await (await fetch('/api/advice', { cache: 'no-store' })).json();       // the profile saved in the plan settings
    if (!r.ok) throw new Error(r.error || 'no data');
    const named = Object.entries(r.assets).map(([isin, v]) => ({ isin, ...v }));
    const stock = n => S.stocks.find(s => s.name === n) || S.funds.find(f => f.name === n);
    const mk = v => ({ ...v, stock: stock(v.name) });
    const ORDER_UP = { ADD: 0, BUYBACK: 1, WATCH: 2 }, ORDER_DOWN = { TRIM: 0, REVIEW: 1, CONSOLIDATE: 2 };
    S.predictions = {
      // stock ideas first (pullbacks in an uptrend, buy-backs), then index funds from the deposit plan, then the ones that are close (WATCH)
      up:   named.filter(v => ['ADD', 'BUYBACK', 'WATCH'].includes(v.action))
                 .sort((a, b) => (ORDER_UP[a.action] - ORDER_UP[b.action]) || ((a.rule === 'deposit_plan') - (b.rule === 'deposit_plan')) || b.score - a.score || b.amount - a.amount).slice(0, 5).map(mk),
      // sales due this month (size cap, trend exit, regime exit), review flags, then tiny positions; queued sales are left for later months
      down: named.filter(v => ['TRIM', 'REVIEW', 'CONSOLIDATE'].includes(v.action) && v.when !== 'later')
                 .sort((a, b) => (ORDER_DOWN[a.action] - ORDER_DOWN[b.action]) || b.score - a.score || b.amount - a.amount)
                 .slice(0, 5).map(mk),
    };
    S.planInfo = r.plan || null;
    S.adviceFull = r;
    renderSignals();
    S.adviceCounts = r.summary.counts;
    renderPredictions();
  } catch (e) {
    console.warn('[advice]', e.message);
    if (badge) badge.textContent = 'Advice unavailable (' + e.message + ')';
    const sl = document.getElementById('sig-list');
    if (sl && !S.adviceFull) sl.innerHTML = '<div class="rep-none">Signals unavailable right now</div>';
  }
}

function renderPredictions() {
  const upEl = document.getElementById('pred-up-list'), downEl = document.getElementById('pred-down-list');
  const badge = document.getElementById('pred-badge');
  if (!upEl || !downEl) return;
  const c = S.adviceCounts || {};
  if (badge) badge.textContent = `${c.ADD || 0} add · ${c.BUYBACK || 0} buy back · ${c.WATCH || 0} watch · ${c.TRIM || 0} sell · ${c.CONSOLIDATE || 0} consolidate · ${c.REVIEW || 0} review · ${new Date().toLocaleTimeString()}`;

  const card = (e, rank) => {
    const watch = e.action === 'WATCH', up = e.action === 'ADD' || e.action === 'BUYBACK', cls = watch ? 'signal-watch' : up ? 'signal-bull' : 'signal-bear';
    const RULE = { size_cap: 'size cap', trend_exit: 'trend exit', regime_exit: 'regime exit', pullback: 'pullback in an uptrend', deposit_plan: 'deposit plan', consolidate: 'tiny position', review: 'review', near_entry: 'close to an entry', buyback: 'buy back' };
    const rsi = e.metrics && e.metrics.rsi != null ? 'RSI ' + Math.round(e.metrics.rsi) : '';
    const sign = up ? '+' : '−';
    const why = (e.reasons[0] || '').replace(/\s+/g, ' ');
    return `<div class="pred-card">
      <span class="pred-rank">${rank}</span>
      <div class="pred-logo-wrap" data-logo="${escHtml(e.name)}"></div>
      <div class="pred-info">
        <div class="pred-name" title="${escHtml(e.name)}">${escHtml(e.name)}</div>
        <div class="pred-ticker"><span class="pred-signal-label ${cls}">${e.action === 'BUYBACK' ? 'BUY BACK' : e.action === 'TRIM' ? 'SELL' : e.action}</span>&nbsp;${e.closed ? 'sold earlier, not held' : e.weight.toFixed(1) + '% of account'} · ${escHtml(e.category_label || e.sector)}</div>
        <div class="pred-signals" title="${escHtml(e.reasons.join(' '))}">${escHtml(why)}</div>
      </div>
      <div class="pred-right">
        <div class="pred-prob${watch ? '' : ' pv'}">${watch ? rsi : e.deposit_pct != null ? e.deposit_pct + '% of deposit' : e.amount ? sign + fmtNum(e.amount, 0) + ' kr' : '—'}</div>
        <div class="pred-bar-wrap"><div class="pred-bar-fill" style="width:${Math.max(8, Math.min(100, e.score))}%"></div></div>
        <div class="pred-rsi">${watch ? 'close to an entry' : escHtml(RULE[e.rule] || ('priority ' + e.score))}</div>
      </div>
    </div>`;
  };
  upEl.innerHTML   = S.predictions.up.length   ? S.predictions.up.map((e, i) => card(e, i + 1)).join('')   : '<div class="pred-loading">No new money is due by the plan right now</div>';
  downEl.innerHTML = S.predictions.down.length ? S.predictions.down.map((e, i) => card(e, i + 1)).join('') : '<div class="pred-loading">No sale is due this month by the category rules</div>';
  document.querySelectorAll('#predictions-section [data-logo]').forEach(el => { el.appendChild(buildLogoEl(el.dataset.logo)); });
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
// msg = the short header text; title = the full detail (tooltip of the dot and the text; phones show only the dot)
function setStatus(type, msg, title) {
  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('last-updated-time');
  if (text) { text.textContent = msg; text.title = title || msg; }
  if (dot)  { dot.className = `dot ${type}`; dot.title = title || msg; }
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

  // Nav tabs — one continuous page: Portfolio scrolls to the top, Heat map to the heat map section below the tables.
  const body = document.getElementById('scroll-body');
  const heat = document.getElementById('heatmap-section');
  const setActive = view => document.querySelectorAll('.nav-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === view));
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      // scroll only the content area (never scrollIntoView: it can also move the header/ticker ancestors)
      if (tab.dataset.tab === 'heatmap' && heat && body) body.scrollTo({ top: heat.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - 14, behavior: 'smooth' });
      else body?.scrollTo({ top: 0, behavior: 'smooth' });
    });
  });
  // highlight the tab that matches what is on screen
  if (body && heat) body.addEventListener('scroll', () => {
    setActive(heat.getBoundingClientRect().top < body.getBoundingClientRect().top + body.clientHeight * 0.5 ? 'heatmap' : 'portfolio');
  }, { passive: true });
  // the heat map loads and keeps itself in sync as soon as the page opens
  if (typeof Heat !== 'undefined') Heat.show();
}

// ────────────────────────────────────────────────────────────
// INITIALIZATION
// ────────────────────────────────────────────────────────────
async function init() {
  setStatus('loading', 'Loading portfolio…');

  // Load persisted last-buy data from previous session (async: may seed from baseline file)
  await loadLastBuyData();

  try {
    // Load the newest holdings export (stocks + funds in one file)
    const { stocks, funds } = await loadHoldings();
    S.stocks = stocks;
    S.funds  = funds;

    // Resolve Yahoo Finance tickers
    S.stocks.forEach(s => { s.ticker = resolveTickerFor(s); });
    S.funds.forEach(f  => { f.ticker = resolveTickerFor(f); });

    // Detect any new purchases since last session
    detectAndSaveBuys();

    // First render with CSV data only
    renderAll();
    bindEvents();
    bindSidebarFolds();

    setStatus('loading', 'Valuing the portfolio…');

    // The server's valuation (rows, tiles) and the ticker bar quotes
    await Promise.all([refreshSnapshot(), refreshPrices()]);

    // Background jobs on one light schedule (pulse.js): paused while the tab is hidden, slower when the market is closed.
    //   Correct, current numbers come first: valuation every 30 s in market hours (15 min when closed: prices do not move) ·
    //   ticker 1 min / 5 min (BTC trades all week) · plan and trend signals 10 min / 1 h
    //   (signals change at the weekly close) · reports calendar 6 h · uploaded files: a small signature check every 2 / 10 min
    loadPredictions();
    loadReports();
    TVPulse.every('snapshot', refreshSnapshot, { open: 30_000, closed: 15 * 60_000 });
    TVPulse.every('ticker', refreshPrices, { open: CFG.refreshMs, closed: 5 * 60_000 });
    TVPulse.every('advice', loadPredictions, { open: 10 * 60_000, closed: 60 * 60_000 });
    TVPulse.every('reports', loadReports, { open: 6 * 3600_000, closed: 6 * 3600_000 });
    TVPulse.every('files', checkFiles, { open: 2 * 60_000, closed: 10 * 60_000 });
    checkFiles();                                     // baseline signature

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

document.addEventListener('DOMContentLoaded', () => (window.TV ? TV.ready : Promise.resolve()).then(init));
