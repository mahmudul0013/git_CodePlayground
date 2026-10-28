"""
sectors.py - sector / category of each holding from Yahoo Finance.

Stocks:       v1/finance/search (no login)   -> sector + industry
ETFs / funds: v10/quoteSummary (needs a cookie+crumb, fetched here) -> fundProfile.categoryName
Nothing is guessed: when Yahoo has no answer the asset is returned with category None and the page
shows it as 'Unclassified'. Results are cached in sector_cache.json (30 days; misses retried after 3 days).
Python stdlib only; never raises.

    batch(assets, budget=40) -> ({isin: info}, pending_count)
"""
import http.cookiejar
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait

import symbols

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, 'sector_cache.json')
TTL_OK, TTL_MISS = 30 * 86400, 3 * 86400
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/122.0.0.0 Safari/537.36')
_LOCK = threading.Lock()
_crumb = {'opener': None, 'value': None, 'at': 0}


def _load():
    try:
        with open(CACHE_FILE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(cache):
    try:
        tmp = CACHE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=1, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass


def _get(url, opener=None, timeout=9):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json, */*',
                                               'Referer': 'https://finance.yahoo.com/'})
    r = (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout))
    return r.read().decode('utf-8', 'replace')


def _search(q):
    for host in ('query2', 'query1'):
        try:
            d = json.loads(_get('https://%s.finance.yahoo.com/v1/finance/search?q=%s&quotesCount=5&newsCount=0'
                                % (host, urllib.parse.quote(q))))
            return d.get('quotes') or []
        except Exception:
            continue
    return None


def _crumb_opener():
    with _LOCK:
        if _crumb['value'] and time.time() - _crumb['at'] < 3600:
            return _crumb['opener'], _crumb['value']
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        try:
            _get('https://fc.yahoo.com', op)
        except Exception:
            pass                            # answers 404 but sets the cookie
        try:
            v = _get('https://query2.finance.yahoo.com/v1/test/getcrumb', op).strip()
        except Exception:
            return None, None
        if not v or '<' in v:
            return None, None
        _crumb.update(opener=op, value=v, at=time.time())
        return op, v


def _fund_category(symbol):
    op, crumb = _crumb_opener()
    if not op:
        return None
    try:
        d = json.loads(_get('https://query2.finance.yahoo.com/v10/finance/quoteSummary/%s?modules=fundProfile&crumb=%s'
                            % (urllib.parse.quote(symbol), urllib.parse.quote(crumb)), op))
        fp = d['quoteSummary']['result'][0].get('fundProfile') or {}
        return fp.get('categoryName') or None
    except Exception:
        return None


def _lookup(isin, name, ccy):
    sym = (symbols.resolve(isin, name, ccy) or {}).get('symbol')
    quotes = _search(sym) if sym else None
    if not quotes and isin:
        quotes = _search(isin)
    if quotes is None:
        return None                                      # network failure: do not cache
    q = next((x for x in quotes if sym and x.get('symbol') == sym), None) or (quotes[0] if quotes else None)
    out = {'symbol': (q or {}).get('symbol') or sym, 'quote_type': (q or {}).get('quoteType'),
           'sector': None, 'industry': None, 'category': None}
    if q:
        out['sector'] = q.get('sectorDisp') or q.get('sector')
        out['industry'] = q.get('industryDisp') or q.get('industry')
        if q.get('quoteType') in ('ETF', 'MUTUALFUND') and out['symbol']:
            out['category'] = _fund_category(out['symbol'])
    return out


def _one(a, cache):
    key = a['isin']
    ent = cache.get(key)
    now = time.time()
    if ent and now - ent.get('checked', 0) < (TTL_OK if ent.get('sector') or ent.get('category') else TTL_MISS):
        return key, ent
    res = _lookup(a['isin'], a['name'], a.get('ccy'))
    if res is None:
        return key, ent                                  # stale or none
    res['checked'] = now
    res['name'] = a['name']
    with _LOCK:
        c = _load()
        c[key] = res
        _save(c)
    return key, res


def batch(assets, budget=40):
    """assets: [{isin, name, ccy}]. Looks up what is missing in parallel for up to `budget` seconds."""
    cache = _load()
    out, todo = {}, []
    now = time.time()
    for a in assets:
        ent = cache.get(a['isin'])
        fresh = ent and now - ent.get('checked', 0) < (TTL_OK if ent.get('sector') or ent.get('category') else TTL_MISS)
        if fresh:
            out[a['isin']] = ent
        else:
            todo.append(a)
            if ent:
                out[a['isin']] = ent
    pending = 0
    if todo:
        ex = ThreadPoolExecutor(max_workers=8)
        futs = [ex.submit(_one, a, cache) for a in todo]
        done, notdone = wait(futs, timeout=budget)
        for f in done:
            try:
                k, v = f.result()
                if v:
                    out[k] = v
            except Exception:
                pass
        pending = len(notdone)
        ex.shutdown(wait=False, cancel_futures=True)
    return out, pending
