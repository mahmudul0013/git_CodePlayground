"""
symbols.py - resolve (isin, name, ccy, market) -> Yahoo Finance symbol.

Order: persistent cache (symbol_cache.json) -> app.js TICKER_MAP -> Yahoo search by ISIN -> Yahoo search by name.

`market` is the 'Market' column of the Nordnet holdings export, the venue the holding is listed on ('Xetra',
'Euronext Amsterdam', 'New York Stock Exchange', 'Nasdaq Stockholm AB', ...). When it is known, the listing on THAT venue
(Yahoo suffix .DE, .AS, none for US, see _MARKETS) in the export's currency is chosen, because valuation.py accepts a live
price only in the export's currency: the US 'ASML' (USD) can never value the Amsterdam holding (EUR, ASML.AS). An ISIN search
often returns one listing only (EIMI.L for the Xetra IS3N), so the venue's listing is then searched by name and accepted only
when Yahoo gives it the same long name as the ISIN's own listing (same instrument, not a sister share class).
A cached entry that contradicts the market / currency is looked up again (once per market, again after 7 days, at most once an
hour per process); the market used is stored in the entry. Entries with source 'manual' (hand edits) are always kept.
Without a market (funds, closed positions, the older aktier_ / fonder_ exports) the old behaviour applies: cache, map, ISIN
search with a currency preference. Negative results are cached with a timestamp and retried after 7 days.
Only public identifiers (ISIN, instrument name, ticker) are sent to Yahoo. Never raises. Python 3.8+, stdlib only.

    resolve(isin, name, ccy, market=None) -> {symbol, currency, exchange, source} | None
    of(asset)                             -> resolve() for an asset dict {isin, name, ccy, market?}
    get(isin, name, ccy, market=None)     -> {ok: bool, symbol, currency, exchange, source} | {ok: False, error?}
    market_suffix(market)                 -> Yahoo suffix of a Nordnet market ('.DE', '' = US) or None when unknown
"""
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, 'symbol_cache.json')
APP_JS = os.path.join(HERE, 'app.js')
RETRY_AFTER = 7 * 86400
RECHECK_GAP = 3600            # a conflicting cache entry is looked up again at most once an hour per process
TIMEOUT = 8

YAHOO_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/122.0.0.0 Safari/537.36',
    'Accept':          'application/json, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer':         'https://finance.yahoo.com/',
}

_LOCK = threading.Lock()
_RECHECKED = {}               # cache key -> time of the last re-check of a conflicting entry (this process)
_GOOD_TYPES = ('EQUITY', 'ETF', 'MUTUALFUND')

# Yahoo exchange code -> trading currency (best effort)
_EXCH_CCY = {
    'STO': 'SEK', 'NGM': 'SEK', 'OSL': 'NOK', 'CPH': 'DKK', 'HEL': 'EUR', 'GER': 'EUR', 'FRA': 'EUR',
    'STU': 'EUR', 'BER': 'EUR', 'DUS': 'EUR', 'MUN': 'EUR', 'HAM': 'EUR', 'HAN': 'EUR', 'PAR': 'EUR',
    'AMS': 'EUR', 'MIL': 'EUR', 'MCE': 'EUR', 'BRU': 'EUR', 'VIE': 'EUR', 'LIS': 'EUR', 'ISE': 'EUR',
    'LSE': 'GBP', 'IOB': 'USD', 'NMS': 'USD', 'NYQ': 'USD', 'NGM_': 'USD', 'NCM': 'USD', 'ASE': 'USD',
    'PCX': 'USD', 'BTS': 'USD', 'PNK': 'USD', 'OQB': 'USD', 'TOR': 'CAD', 'VAN': 'CAD', 'EBS': 'CHF',
    'SWX': 'CHF', 'JPX': 'JPY', 'HKG': 'HKD', 'TLV': 'ILS',
}

# Nordnet 'Market' -> Yahoo symbol suffix ('' = a US exchange, no suffix). Tried in order on the folded name (lower case,
# Nordic letters folded): the Nordic 'Nasdaq ...' venues come before the bare US 'Nasdaq'.
_MARKETS = tuple((re.compile(p), s) for p, s in (
    (r'copenhagen|denmark|danmark', '.CO'),
    (r'helsinki|finland', '.HE'),
    (r'iceland|reykjavik', '.IC'),
    (r'tallinn', '.TL'), (r'\briga\b', '.RG'), (r'vilnius', '.VS'),
    (r'oslo|norway|norge|merkur', '.OL'),
    (r'stockholm|sweden|sverige|first north|\bngm\b|nordic growth|spotlight|nordic sme', '.ST'),
    (r'amsterdam', '.AS'), (r'paris', '.PA'), (r'brussel|bruxelles', '.BR'), (r'lisbon|lisboa', '.LS'),
    (r'dublin|irish', '.IR'), (r'milan|milano|borsa italiana', '.MI'),
    (r'xetra|deutsche borse', '.DE'), (r'frankfurt', '.F'), (r'stuttgart', '.SG'),
    (r'london|\blse\b', '.L'),
    (r'tsx venture|tsxv', '.V'), (r'toronto|\btsx\b', '.TO'),
    (r'\bsix\b|swiss|zurich', '.SW'),
    (r'vienna|wiener|wien\b', '.VI'),
    (r'madrid|\bbme\b', '.MC'),
    (r'new york|nyse|nasdaq|amex|arca|cboe|bats|\bus\b|united states', ''),
))
# Yahoo suffix -> trading currency. '.L' and '.SW' trade in several currencies (GBp / USD / EUR, CHF / USD): no guess there,
# the candidate's chart answers.
_SFX_CCY = {
    '.ST': 'SEK', '.OL': 'NOK', '.CO': 'DKK', '.HE': 'EUR', '.IC': 'ISK', '.TL': 'EUR', '.RG': 'EUR', '.VS': 'EUR',
    '.AS': 'EUR', '.PA': 'EUR', '.BR': 'EUR', '.LS': 'EUR', '.IR': 'EUR', '.MI': 'EUR', '.DE': 'EUR', '.F': 'EUR',
    '.SG': 'EUR', '.VI': 'EUR', '.MC': 'EUR', '.TO': 'CAD', '.V': 'CAD', '': 'USD',
}
_MULTI_CCY = ('.L', '.IL', '.SW')
_OTC = ('PNK', 'OQB', 'OQX', 'OEM', 'OGM', 'OTC')      # US over-the-counter lines are not the NYSE / Nasdaq listing
_FOLD = str.maketrans({'ø': 'o', 'ö': 'o', 'å': 'a', 'ä': 'a', 'æ': 'ae', 'ü': 'u', 'é': 'e', 'è': 'e', '&': ' and '})


def _fold(s):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(s or '').lower().translate(_FOLD)).split())


def market_suffix(market):
    """Yahoo suffix of a Nordnet market name ('.DE' for 'Xetra', '' for a US exchange); None when empty or unknown."""
    m = _fold(market)
    if not m:
        return None
    for rx, sfx in _MARKETS:
        if rx.search(m):
            return sfx
    return None


def _suffix(symbol):
    s = str(symbol or '').upper()
    return s[s.rfind('.'):] if '.' in s else ''


def _sym_ccy(symbol, exchange=None):
    """Trading currency told by the symbol suffix (or the Yahoo exchange code); None when it cannot be told."""
    sfx = _suffix(symbol)
    if sfx in _SFX_CCY:
        return _SFX_CCY[sfx]
    if sfx in _MULTI_CCY:
        return None
    return _EXCH_CCY.get(exchange)


def _on_venue(symbol, exchange, want):
    """Is the listing on the venue with Yahoo suffix `want` (None = any venue)?"""
    if want is None:
        return True
    if _suffix(symbol) != want:
        return False
    return want != '' or str(exchange or '').upper() not in _OTC


def _conflicts(ent, want, ccy):
    """Does a cached listing contradict the holding's venue (suffix `want`) or the export currency `ccy`?"""
    sym = ent.get('symbol')
    if not sym or sym.startswith('0P'):
        return False                                  # Nordnet funds: valued from the export, never re-checked
    if not _on_venue(sym, ent.get('exchange'), want):
        return True
    c = ent.get('currency') or _sym_ccy(sym, ent.get('exchange'))
    return bool(ccy and c and c.upper() != ccy.upper())


def _score(ent, want, ccy):
    """How well a listing suits the holding: the currency counts most (valuation.py needs it), then the venue."""
    sym = ent.get('symbol') or ''
    c = ent.get('currency') or _sym_ccy(sym, ent.get('exchange'))
    cur = 2 if not ccy or (c and c.upper() == ccy.upper()) else 1 if not c else 0
    return cur * 2 + (1 if _on_venue(sym, ent.get('exchange'), want) else 0)


# ───────── cache ─────────
def _load_cache():
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_cache(cache):
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix='.symcache_', suffix='.tmp', dir=os.path.dirname(CACHE_FILE) or '.')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        try:
            if tmp:
                os.unlink(tmp)
        except Exception:
            pass


def _key(isin, name):
    isin = (isin or '').strip().upper()
    return isin if isin else 'NAME:' + (name or '').strip().lower()


def _out(ent):
    return {k: ent.get(k) for k in ('symbol', 'currency', 'exchange', 'source')}


# ───────── TICKER_MAP seed ─────────
def _ticker_map():
    """Parse TICKER_MAP from app.js -> {lower name: str | {ccy: sym}}"""
    out = {}
    try:
        with open(APP_JS, 'r', encoding='utf-8') as f:
            src = f.read()
        m = re.search(r'const\s+TICKER_MAP\s*=\s*\{(.*?)\n\};', src, re.S)
        if not m:
            return out
        body = m.group(1)
        for line in body.splitlines():
            line = line.split('//')[0].strip()
            mm = re.match(r"""^(['"])(.+?)\1\s*:\s*(.+?),?\s*$""", line)
            if not mm:
                continue
            k, v = mm.group(2).strip().lower(), mm.group(3).strip().rstrip(',').strip()
            sm = re.match(r"""^(['"])(.+?)\1$""", v)
            if sm:
                out[k] = sm.group(2)
            elif v.startswith('{'):
                out[k] = {a: b for _, a, b in
                          [(0, x[0], x[2]) for x in re.findall(r"""(\w+)\s*:\s*(['"])(.+?)\2""", v)]}
    except Exception:
        pass
    return out


def _from_map(name, ccy):
    try:
        v = _ticker_map().get((name or '').strip().lower())
        if isinstance(v, dict):
            v = v.get((ccy or '').upper()) or v.get('default') or next(iter(v.values()), None)
        if v:
            return {'symbol': v, 'currency': None, 'exchange': None, 'source': 'ticker_map'}
    except Exception:
        pass
    return None


# ───────── Yahoo ─────────
def _fetch(path):
    for host in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com'):
        try:
            req = urllib.request.Request('https://%s/%s' % (host, path), headers=YAHOO_HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                return None
        except Exception:
            continue
    return None


def _quotes(q, n=10):
    """Yahoo search hits (equities, ETFs, funds) for one public query, an ISIN or an instrument name; None = no answer."""
    raw = _fetch('v1/finance/search?q=%s&quotesCount=%d&newsCount=0' % (urllib.parse.quote(q), n))
    if raw is None:
        return None
    try:
        quotes = json.loads(raw).get('quotes') or []
    except Exception:
        return None
    return [x for x in quotes if x.get('symbol') and (x.get('quoteType') or '').upper() in _GOOD_TYPES]


def _chart_ccy(symbol):
    """Trading currency Yahoo reports for a symbol (v8 chart meta); None when it cannot be fetched."""
    raw = _fetch('v8/finance/chart/%s?range=1d&interval=1d' % urllib.parse.quote(symbol))
    if not raw:
        return None
    try:
        return json.loads(raw)['chart']['result'][0]['meta'].get('currency') or None
    except Exception:
        return None


def _hit(x, source='yahoo_search', currency=None):
    return {'symbol': x['symbol'], 'currency': currency or _sym_ccy(x['symbol'], x.get('exchange')),
            'exchange': x.get('exchange'), 'source': source}


def _pick_ccy(good, ccy):
    """The old choice: Yahoo's first hit, or the first one whose exchange trades in `ccy`."""
    pick = good[0]
    want = (ccy or '').upper()
    if want and len(good) > 1:
        for x in good:
            if _EXCH_CCY.get(x.get('exchange')) == want:
                pick = x
                break
    return {'symbol': pick['symbol'], 'currency': _EXCH_CCY.get(pick.get('exchange')),
            'exchange': pick.get('exchange'), 'source': 'yahoo_search'}


def _search(isin, ccy):
    """Returns (result|None, ok) - ok False means network failure (do not cache negative)."""
    good = _quotes(isin, 6)
    if good is None:
        return None, False
    return (_pick_ccy(good, ccy) if good else None), True


def _on_market(hits, want, ccy, checks):
    """First hit on the venue `want` whose currency is `ccy` (told by the suffix, else by its chart; at most `checks[0]`
    chart calls in all). -> result | None"""
    if not hits:
        return None
    ccy = (ccy or '').upper()
    fit, unknown = [], []
    for x in hits:
        if not _on_venue(x['symbol'], x.get('exchange'), want):
            continue
        c = _sym_ccy(x['symbol'], x.get('exchange'))
        if not ccy or (c and c.upper() == ccy):
            fit.append(x)
        elif not c:
            unknown.append(x)
    if fit:
        return _hit(fit[0])
    for x in unknown:
        if checks[0] <= 0:
            break
        checks[0] -= 1
        c = _chart_ccy(x['symbol'])
        if c and c.upper() == ccy:
            return _hit(x, currency=c)
    return None


def _lookup(isin, name, ccy, want):
    """Best listing for a holding on the venue with Yahoo suffix `want` -> (result|None, ok); ok False = Yahoo did not answer
    (nothing is cached then)."""
    seed = _from_map(name, ccy)
    if want is None:                                           # no market: the old order (map, then ISIN search)
        if seed:
            return seed, True
        if not isin:
            return None, True
        return _search(isin, ccy)

    if seed and not _conflicts(seed, want, ccy):
        return seed, True
    ok, checks = True, [3]
    by_isin = []
    if isin:
        by_isin = _quotes(isin)
        if by_isin is None:
            return seed, False
        best = _on_market(by_isin, want, ccy, checks)
        if best:
            return best, True
    # The ISIN search shows only some listings: search by the instrument's Yahoo long name (from the ISIN hits) and by the
    # Nordnet name, each also cut after 'ETF' (Yahoo finds nothing for some long share-class names). A hit counts only with
    # the same long name as an ISIN hit, or (no ISIN hits) when it contains every word of the Nordnet name.
    ids = {_fold(x.get('longname')) for x in by_isin if x.get('longname')}
    words = set(_fold(name).split())
    queries = []
    for q in [x.get('longname') for x in by_isin] + [name]:
        q = (q or '').strip()
        cut = re.match(r'(.*?\bETF)\b', q, re.I)
        for v in (q, cut.group(1) if cut else ''):
            if v and _fold(v) not in [_fold(y) for y in queries]:
                queries.append(v)
    found = []
    for q in queries[:4]:
        hits = _quotes(q, 20)
        if hits is None:
            ok = False
            continue
        if ids:
            hits = [x for x in hits if _fold(x.get('longname')) in ids]
        else:
            hits = [x for x in hits if words and words <= set(_fold(x.get('longname') or x.get('shortname')).split())]
        found += hits
        best = _on_market(hits, want, ccy, checks)
        if best:
            return best, True
    # nothing on that venue: a listing of the same instrument in the export currency (still valued live), else what the old
    # order gave (map, then the first ISIN hit)
    best = _on_market(by_isin + found, None, ccy, checks)
    if best:
        return best, ok
    return (seed or (_pick_ccy(by_isin, ccy) if by_isin else None)), ok


# ───────── public ─────────
def resolve(isin, name, ccy, market=None):
    try:
        key = _key(isin, name)
        isin = (isin or '').strip().upper()
        market = (market or '').strip()
        want = market_suffix(market)
        now = time.time()
        old = None
        with _LOCK:
            ent = _load_cache().get(key)
            if isinstance(ent, dict):
                fresh = now - float(ent.get('checked', 0) or 0) < RETRY_AFTER
                if ent.get('symbol'):
                    settled = (ent.get('source') == 'manual' or want is None or not _conflicts(ent, want, ccy)
                               or (ent.get('market') == market and fresh))
                else:                                           # a miss: retried after a week, or now for a new market
                    settled = fresh and (want is None or ent.get('market') == market)
                if settled or now - _RECHECKED.get(key, 0) < RECHECK_GAP:
                    return _out(ent) if ent.get('symbol') else None
                _RECHECKED[key] = now
                old = ent if ent.get('symbol') else None        # listed elsewhere than the holding: look again

        res, ok = _lookup(isin, name, ccy, want)
        if res and old and res.get('symbol') != old.get('symbol') and _score(res, want, ccy) <= _score(old, want, ccy):
            res = None                                          # not better than what we had: keep it (no churn)

        with _LOCK:
            cache = _load_cache()
            ent = cache.get(key)
            if isinstance(ent, dict) and ent.get('symbol') and (ent.get('source') == 'manual' or old is None):
                return _out(ent)                                # manual / concurrent entry wins
            if not ok:
                return _out(old) if old else res                # Yahoo did not answer: keep what we had, cache nothing
            if res:
                new = dict(res, name=name, checked=now)
                if old and old.get('symbol') != res.get('symbol'):
                    new['was'] = old.get('symbol')
            elif old:
                new = dict(old, checked=now)                    # nothing better on that market: keep it, look again in a week
                res = _out(old)
            else:
                new = {'symbol': None, 'name': name, 'checked': now}
            if want is not None:
                new.update(market=market, ccy=(ccy or '').upper() or None)
            cache[key] = new
            _save_cache(cache)
        return res
    except Exception:
        return None


def of(asset):
    """resolve() for an asset dict {isin, name, ccy, market?}; the market is passed only when the holdings export gave one."""
    a = asset or {}
    if a.get('market'):
        return resolve(a.get('isin'), a.get('name'), a.get('ccy'), market=a['market'])
    return resolve(a.get('isin'), a.get('name'), a.get('ccy'))


def get(isin, name, ccy, market=None):
    try:
        r = resolve(isin, name, ccy, market) if market else resolve(isin, name, ccy)
        if r:
            d = {'ok': True}
            d.update(r)
            return d
        return {'ok': False, 'symbol': None}
    except Exception as e:
        return {'ok': False, 'symbol': None, 'error': str(e)}


if __name__ == '__main__':
    import sys
    print(json.dumps(get(*(sys.argv[1:5] + [''] * 4)[:4]), indent=2))
