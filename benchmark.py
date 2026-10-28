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
SERIES = {'omx': ('^OMX', 'OMXS30 (SEK)'), 'spx': ('^GSPC', 'S&P 500 (USD->SEK)'), 'nq': ('NQ=F', 'Nasdaq 100 futures NQ=F (USD->SEK)'), 'fx': ('USDSEK=X', 'USD/SEK')}

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
        series = {}
        for k, (sym, _) in SERIES.items():
            try:
                series[k] = _fetch_closes(sym, p1, p2)
            except Exception:
                if k in ('omx', 'fx'):          # the others may fail alone
                    raise
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
    for k, mult in (('omx', None), ('spx', ('fx',)), ('nq', ('fx',))):
        if k not in series:
            continue
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


OVERLAY_FILE = os.path.join(HERE, 'benchmark_overlay_cache.json')
OVERLAY_INDICES = [('omx', '^OMX', 'OMXS30', False), ('spx', '^GSPC', 'S&P 500', True),
                   ('nq', 'NQ=F', 'Nasdaq 100 futures (NQ=F)', True)]      # (id, Yahoo symbol, label, USD -> convert)
_ov = {'at': 0, 'key': None, 'data': None}


def overlay(flows, first, last):
    """Daily index curves in SEK for the Deposit behaviour chart, one value per calendar day first..last.
    perf: price return in % since `first` (weekends carry the last close).
    dca:  value of 'every deposit/withdrawal bought the index that day' (same idea as compute()).
    Never raises; falls back to the last saved copy when Yahoo is unreachable."""
    key = (first, last, round(sum(f['amount'] for f in flows), 2), len(flows))
    if _ov['data'] and _ov['key'] == key and time.time() - _ov['at'] < TTL:
        return _ov['data']
    from datetime import date, timedelta
    try:
        p1 = int(datetime.strptime(first, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()) - 7 * 86400
        p2 = int(time.time()) + 86400
        fx = _fetch_closes('USDSEK=X', p1, p2)
        raw = {}
        for iid, sym, _, _ in OVERLAY_INDICES:
            try:
                raw[iid] = _fetch_closes(sym, p1, p2)
            except Exception:
                raw[iid] = None             # one failing index must not hide the others
        if not any(raw.values()):
            raise RuntimeError('Yahoo returned no index data')
        days = []
        d, end = date.fromisoformat(first), date.fromisoformat(last)
        while d <= end:
            days.append(d.isoformat())
            d += timedelta(days=1)
        by_day = {}
        for f in flows:
            by_day[f['date']] = by_day.get(f['date'], 0.0) + f['amount']

        def filled(series):                 # calendar-day close, carrying the last known one forward
            ks, cur, out = sorted(series), None, []
            i = 0
            # seed with the last close before `first`
            while i < len(ks) and ks[i] <= days[0]:
                cur = series[ks[i]]
                i += 1
            for day in days:
                while i < len(ks) and ks[i] <= day:
                    cur = series[ks[i]]
                    i += 1
                out.append(cur)
            return out
        fxd = filled(fx)
        res = {'ok': True, 'stale': False, 'computed': datetime.now().isoformat(timespec='seconds'),
               'dates': days, 'indices': []}
        for iid, _, label, usd in OVERLAY_INDICES:
            if not raw[iid]:
                continue
            px = filled(raw[iid])
            sek = [None if p is None else p * (fxd[i] if usd and fxd[i] else 1.0) for i, p in enumerate(px)]
            base = next((v for v in sek if v), None)
            units, perf, dca = 0.0, [], []
            for day, v in zip(days, sek):
                if v:
                    units += by_day.get(day, 0.0) / v
                perf.append(None if not v or not base else round((v / base - 1) * 100, 3))
                dca.append(None if not v else round(units * v, 2))
            res['indices'].append({'id': iid, 'name': label, 'perf': perf, 'dca': dca})
        _ov.update(at=time.time(), key=key, data=res)
        try:
            json.dump(res, open(OVERLAY_FILE, 'w', encoding='utf-8'))
        except OSError:
            pass
        return res
    except Exception as e:
        if os.path.exists(OVERLAY_FILE):
            try:
                saved = json.load(open(OVERLAY_FILE, encoding='utf-8'))
                saved.update(stale=True, error=str(e))
                return saved
            except Exception:
                pass
        return {'ok': False, 'error': str(e)}


if __name__ == '__main__':
    import sys
    sys.path.insert(0, HERE)
    import trade_analytics as ta
    p = ta.get_payload()
    flows = [{'date': c['date'], 'amount': c['amount']} for c in p['cashflows']]
    print(json.dumps(compute(flows, p['insights']['overview']['total_value']), indent=1))
