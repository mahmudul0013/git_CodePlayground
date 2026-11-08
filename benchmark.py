#!/usr/bin/env python3
"""
benchmark.py  -  "What if every deposit had gone into an index instead?"
=======================================================================
Uses Yahoo Finance daily closes (same hosts as server.py) for
    ^OMX      OMX Stockholm 30     (SEK)
    ^GSPC     S&P 500              (USD, converted with USDSEK=X)
    NQ=F      Nasdaq 100 futures   (USD, converted with USDSEK=X)
Each deposit/withdrawal from the ledger buys/sells index units at the first
close on or after that date; the units are valued at the latest close.
Price indices only (no dividends), no fees: a simple yardstick, not a
tradable promise.

Multi-user note: ONLY the public index closes are cached (in memory 6 h and in benchmark_series_cache.json so the page
still works offline). Every result that depends on a user's deposits is computed per call from that user's flows and
never stored, so one user can never be served another user's numbers.
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(HERE, 'benchmark_series_cache.json')      # index closes only
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                         '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
           'Accept': 'application/json, */*', 'Referer': 'https://finance.yahoo.com/'}
TTL = 6 * 3600
RETRY_AFTER = 60       # seconds before a failed Yahoo download is tried again while older data is served
SERIES = {'omx': ('^OMX', 'OMXS30 (SEK)'), 'spx': ('^GSPC', 'S&P 500 (USD->SEK)'), 'nq': ('NQ=F', 'Nasdaq 100 futures NQ=F (USD->SEK)'), 'fx': ('USDSEK=X', 'USD/SEK')}
OVERLAY_INDICES = [('omx', '^OMX', 'OMXS30', False), ('spx', '^GSPC', 'S&P 500', True),
                   ('nq', 'NQ=F', 'Nasdaq 100 futures (NQ=F)', True)]      # (id, Yahoo symbol, label, USD -> convert)

_raw = {'at': 0, 'p1': None, 'series': None, 'fail_at': 0, 'error': None}      # public index data, shared by all users
_raw_lock = threading.Lock()                                                    # also stops N users downloading the same series at once


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


def _load_disk():
    try:
        with open(RAW_FILE, encoding='utf-8') as f:
            d = json.load(f)
        if d.get('series') and d.get('p1') is not None and d['series'].get('omx') and d['series'].get('fx'):
            return d
    except Exception:
        pass
    return None


def _raw_series(p1):
    """Index closes {omx, spx, nq, fx -> {date: close}} reaching back to at least epoch second p1.
    -> (series, stale, error). Raises RuntimeError when Yahoo is unreachable and nothing was ever saved."""
    with _raw_lock:
        now = time.time()
        r = _raw
        if r['series'] and r['p1'] <= p1 and now - r['at'] < TTL:
            return r['series'], False, None
        if r['series'] is None:
            disk = _load_disk()
            if disk:                                 # warm start after a restart; stale until Yahoo answers
                r.update(p1=disk['p1'], series=disk['series'], at=disk.get('at', 0))
                if r['p1'] <= p1 and now - r['at'] < TTL:
                    return r['series'], False, None
        if r['series'] and now - r['fail_at'] < RETRY_AFTER:
            return r['series'], True, r['error']
        want = p1 if r['p1'] is None else min(p1, r['p1'])
        try:
            series = {}
            for k, (sym, _) in SERIES.items():
                try:
                    series[k] = _fetch_closes(sym, want, int(now) + 86400)
                except Exception:
                    if k in ('omx', 'fx'):          # the others may fail alone
                        raise
            r.update(at=now, p1=want, series=series, fail_at=0, error=None)
            try:
                tmp = RAW_FILE + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump({'at': now, 'p1': want, 'series': series}, f)
                os.replace(tmp, RAW_FILE)
            except OSError:
                pass
            return series, False, None
        except Exception as e:
            r.update(fail_at=now, error=str(e))
            if r['series']:
                return r['series'], True, str(e)
            raise RuntimeError(str(e))


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


def _p1(first):
    return int(datetime.strptime(first, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()) - 7 * 86400


def compute(flows, account_value):
    """flows: [{date, amount}] (deposits +, withdrawals -). Pure function of the flows plus public index data. Never raises."""
    if not flows:
        return {'ok': False, 'error': 'No deposits found in the ledger.'}
    try:
        first = min(f['date'] for f in flows)
        series, stale, err = _raw_series(_p1(first))
        sdates = {k: sorted(v) for k, v in series.items()}
        flows = sorted(flows, key=lambda f: f['date'])
        res = {'ok': True, 'stale': stale, 'computed': datetime.now().isoformat(timespec='seconds'),
               'as_of': sdates['omx'][-1], 'flows': len(flows), 'indices': []}
        if stale:
            res['error'] = err
        for k, mult in (('omx', None), ('spx', ('fx',)), ('nq', ('fx',))):
            if k not in series:
                continue
            inv, val = _simulate(flows, sdates[k], series[k], (sdates['fx'], series['fx']) if mult else None)
            if val is None:
                continue
            res['indices'].append({'id': k, 'name': SERIES[k][1], 'invested': round(inv, 2),
                                   'value': round(val, 2), 'pnl': round(val - inv, 2),
                                   'pct': round((val - inv) / inv * 100, 2) if inv else None})
        return _with_account(res, account_value)
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _with_account(res, account_value):
    res = dict(res)
    if account_value is not None:
        res['account_value'] = round(account_value, 2)
        for ix in res.get('indices', []):
            ix['account_minus_index'] = round(account_value - ix['value'], 2)
    return res


def overlay(flows, first, last):
    """Daily index curves in SEK for the Deposit behaviour chart, one value per calendar day first..last.
    perf: price return in % since `first` (weekends carry the last close).
    dca:  value of 'every deposit/withdrawal bought the index that day' (same idea as compute()).
    Pure function of the flows plus public index data; never raises; falls back to the last saved index data."""
    try:
        series, stale, err = _raw_series(_p1(first))
        fx = series['fx']
        raw = {iid: series.get(iid) for iid, _, _, _ in OVERLAY_INDICES}      # one missing index must not hide the others
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

        def filled(s):                      # calendar-day close, carrying the last known one forward
            ks, cur, out = sorted(s), None, []
            i = 0
            # seed with the last close before `first`
            while i < len(ks) and ks[i] <= days[0]:
                cur = s[ks[i]]
                i += 1
            for day in days:
                while i < len(ks) and ks[i] <= day:
                    cur = s[ks[i]]
                    i += 1
                out.append(cur)
            return out
        fxd = filled(fx)
        res = {'ok': True, 'stale': stale, 'computed': datetime.now().isoformat(timespec='seconds'),
               'dates': days, 'indices': []}
        if stale:
            res['error'] = err
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
        return res
    except Exception as e:
        return {'ok': False, 'error': str(e)}


if __name__ == '__main__':
    import sys
    sys.path.insert(0, HERE)
    import trade_analytics as ta
    p = ta.get_payload()
    flows = [{'date': c['date'], 'amount': c['amount']} for c in p['cashflows']]
    print(json.dumps(compute(flows, p['insights']['overview']['total_value']), indent=1))
