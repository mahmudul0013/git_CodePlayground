"""
symbols.py - resolve (isin, name, ccy) -> Yahoo Finance symbol.

Order: persistent cache (symbol_cache.json) -> app.js TICKER_MAP -> Yahoo search by ISIN.
Negative results are cached with a timestamp and retried after 7 days.
Never raises. Python 3.8+, stdlib only.

    resolve(isin, name, ccy) -> {symbol, currency, exchange, source} | None
    get(isin, name, ccy)     -> {ok: bool, symbol, currency, exchange, source} | {ok: False, error?}
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


# ───────── cache ─────────
def _load_cache():
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_cache(cache):
    try:
        fd, tmp = tempfile.mkstemp(prefix='.symcache_', suffix='.tmp', dir=HERE)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _key(isin, name):
    isin = (isin or '').strip().upper()
    return isin if isin else 'NAME:' + (name or '').strip().lower()


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


# ───────── Yahoo search ─────────
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


def _search(isin, ccy):
    """Returns (result|None, ok) - ok False means network failure (do not cache negative)."""
    q = urllib.parse.quote(isin)
    raw = _fetch('v1/finance/search?q=%s&quotesCount=6&newsCount=0' % q)
    if raw is None:
        return None, False
    try:
        quotes = json.loads(raw).get('quotes') or []
    except Exception:
        return None, False
    good = [x for x in quotes if x.get('symbol') and
            (x.get('quoteType') or '').upper() in _GOOD_TYPES]
    if not good:
        return None, True
    pick = good[0]
    want = (ccy or '').upper()
    if want and len(good) > 1:
        for x in good:
            if _EXCH_CCY.get(x.get('exchange')) == want:
                pick = x
                break
    exch = pick.get('exchange')
    return {'symbol': pick['symbol'], 'currency': _EXCH_CCY.get(exch),
            'exchange': exch, 'source': 'yahoo_search'}, True


# ───────── public ─────────
def resolve(isin, name, ccy):
    try:
        key = _key(isin, name)
        now = time.time()
        with _LOCK:
            cache = _load_cache()
            ent = cache.get(key)
            if isinstance(ent, dict):
                if ent.get('symbol'):
                    return {k: ent.get(k) for k in ('symbol', 'currency', 'exchange', 'source')}
                if now - float(ent.get('checked', 0)) < RETRY_AFTER:
                    return None

        res = _from_map(name, ccy)
        ok = True
        if not res and (isin or '').strip():
            res, ok = _search(isin.strip().upper(), ccy)
        if not res and not (isin or '').strip():
            ok = True

        with _LOCK:
            cache = _load_cache()
            ent = cache.get(key)
            if isinstance(ent, dict) and ent.get('symbol'):   # manual/concurrent entry wins
                return {k: ent.get(k) for k in ('symbol', 'currency', 'exchange', 'source')}
            if res:
                cache[key] = dict(res, name=name, checked=now)
                _save_cache(cache)
            elif ok:
                cache[key] = {'symbol': None, 'name': name, 'checked': now}
                _save_cache(cache)
        return res
    except Exception:
        return None


def get(isin, name, ccy):
    try:
        r = resolve(isin, name, ccy)
        if r:
            d = {'ok': True}
            d.update(r)
            return d
        return {'ok': False, 'symbol': None}
    except Exception as e:
        return {'ok': False, 'symbol': None, 'error': str(e)}


if __name__ == '__main__':
    import sys
    print(json.dumps(get(*(sys.argv[1:4] + [''] * 3)[:3]), indent=2))
