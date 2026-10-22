#!/usr/bin/env python3
"""
benchmark.py  -  "What if every deposit had gone into an index instead?"
=======================================================================
Uses Yahoo Finance daily closes (same hosts as server.py) for
    ^OMX      OMX Stockholm 30     (SEK)
    ^GSPC     S&P 500              (USD, converted with USDSEK=X)
Each deposit/withdrawal from the ledger buys/sells index units at the first
close on or after that date; the units are valued at the latest close.
Price indices only (no dividends), no fees: a simple yardstick, not a
tradable promise. Results are cached in memory (6 h) and on disk
(benchmark_cache.json) so the page still works offline with the last data.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from bisect import bisect_left
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, 'benchmark_cache.json')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                         '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
           'Accept': 'application/json, */*', 'Referer': 'https://finance.yahoo.com/'}
TTL = 6 * 3600
SERIES = {'omx': ('^OMX', 'OMXS30 (SEK)'), 'spx': ('^GSPC', 'S&P 500 (USD->SEK)'), 'fx': ('USDSEK=X', 'USD/SEK')}

_mem = {'at': 0, 'key': None, 'data': None}


def _fetch_closes(symbol, p1, p2):
    q = urllib.parse.quote(symbol)
    path = f'v8/finance/chart/{q}?period1={p1}&period2={p2}&interval=1d'
    last = None
    for host in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com'):
        try:
            req = urllib.request.Request(f'https://{host}/{path}', headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as r:
                d = json.loads(r.read())
            res = d['chart']['result'][0]
            ts = res['timestamp']
            cl = res['indicators']['quote'][0]['close']
            out = {}
            for t, c in zip(ts, cl):
                if c is not None:
                    out[datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m-%d')] = float(c)
            if out:
                return out
        except Exception as e:      # try the next host
            last = e
    raise RuntimeError(f'Yahoo failed for {symbol}: {last}')


def _value_at(dates, closes, d):
    """First close on or after d; after the last close, the last close (same-day deposits)."""
    i = bisect_left(dates, d)
    return closes[dates[min(i, len(dates) - 1)]]


def _simulate(flows, dates, closes, mult=None):
    """mult: optional (dates, closes) FX series multiplied into the price."""
    def px(d):
        p = _value_at(dates, closes, d)
        if p is None:
            return None
        if mult:
            f = _value_at(mult[0], mult[1], d)
            if f is None:
                return None
            p *= f
        return p
    units, invested = 0.0, 0.0
    for f in flows:
        p = px(f['date'])
        if not p:
            continue
        units += f['amount'] / p
        invested += f['amount']
    last = px(dates[-1])
    value = units * last if last else None
    return invested, value


def compute(flows, account_value):
    """flows: [{date, amount}] (deposits +, withdrawals -). Returns dict (never raises)."""
    if not flows:
        return {'ok': False, 'error': 'No deposits found in the ledger.'}
    first = min(f['date'] for f in flows)
    key = (first, round(sum(f['amount'] for f in flows), 2), len(flows))
    if _mem['data'] and _mem['key'] == key and time.time() - _mem['at'] < TTL:
        return _with_account(_mem['data'], account_value)
    p1 = int(datetime.strptime(first, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()) - 7 * 86400
    p2 = int(time.time()) + 86400
    try:
        series = {k: _fetch_closes(sym, p1, p2) for k, (sym, _) in SERIES.items()}
        fresh = True
    except Exception as e:
        if os.path.exists(CACHE_FILE):
            try:
                saved = json.load(open(CACHE_FILE, encoding='utf-8'))
                saved['stale'] = True
                saved['error'] = str(e)
                return _with_account(saved, account_value)
            except Exception:
                pass
        return {'ok': False, 'error': str(e)}
    sdates = {k: sorted(v) for k, v in series.items()}
    flows = sorted(flows, key=lambda f: f['date'])
    res = {'ok': True, 'stale': False, 'computed': datetime.now().isoformat(timespec='seconds'),
           'as_of': sdates['omx'][-1], 'flows': len(flows), 'indices': []}
    for k, mult in (('omx', None), ('spx', ('fx',))):
        inv, val = _simulate(flows, sdates[k], series[k], (sdates['fx'], series['fx']) if mult else None)
        if val is None:
            continue
        res['indices'].append({'id': k, 'name': SERIES[k][1], 'invested': round(inv, 2),
                               'value': round(val, 2), 'pnl': round(val - inv, 2),
                               'pct': round((val - inv) / inv * 100, 2) if inv else None})
    _mem.update(at=time.time(), key=key, data=res)
    try:
        json.dump(res, open(CACHE_FILE, 'w', encoding='utf-8'))
    except OSError:
        pass
    return _with_account(res, account_value)


def _with_account(res, account_value):
    res = dict(res)
    if account_value is not None:
        res['account_value'] = round(account_value, 2)
        for ix in res.get('indices', []):
            ix['account_minus_index'] = round(account_value - ix['value'], 2)
    return res


if __name__ == '__main__':
    import sys
    sys.path.insert(0, HERE)
    import trade_analytics as ta
    p = ta.get_payload()
    flows = [{'date': c['date'], 'amount': c['amount']} for c in p['cashflows']]
    print(json.dumps(compute(flows, p['insights']['overview']['total_value']), indent=1))
