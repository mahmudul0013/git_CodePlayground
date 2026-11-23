"""
strategy_bt.py - the evidence behind strategy.py: which rule worked for which category, tested on YOUR holdings.

For every category, an equal-weight basket of the stocks and funds you hold is tested over up to 10 years of Yahoo daily
adjusted closes (local currency) with 0.3% cost per switch; cash earns nothing; a signal from the close of day t is traded on
day t+1. Rules: buy and hold, weekly close vs SMA(200), half held + half on the weekly rule, SMA(50) above SMA(200), and
dip buying (in at RSI(14) < 40 above SMA(200), out at RSI > 70 or below SMA(200)).

Runs in a background thread (it needs ~10 years of prices per holding, cached for a week in history10_cache.json, public
price data only). Results are kept in memory per user and holdings signature; never written to disk.
"""
import json
import math
import os
import statistics
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
H10_FILE = os.path.join(HERE, 'history10_cache.json')
H10_TTL = 7 * 24 * 3600
RESULT_TTL = 24 * 3600
COST = 0.003
MIN_DAYS = 400
HEAD = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
RULES = ('BH', 'T200W', 'HALFW', 'GX', 'DIP')
LABELS = {'BH': 'Buy and hold', 'T200W': 'Weekly close vs SMA(200)', 'HALFW': 'Half held, half on the weekly SMA(200) rule',
          'GX': 'SMA(50) above SMA(200)', 'DIP': 'Dip buying: in at RSI < 40 above SMA(200), out at RSI > 70'}
PICK = {'core': 'BH', 'ai': 'HALFW', 'bigtech': 'BH', 'health': 'BH', 'industrials': 'HALFW', 'financials': 'BH', 'materials': 'GX', 'defensive': 'BH'}

_LOCK = threading.Lock()
_h10 = None
_results = OrderedDict()          # (owner, signature) -> {'at', 'data'}
_running = set()


def _load():
    global _h10
    with _LOCK:
        if _h10 is None:
            try:
                with open(H10_FILE, encoding='utf-8') as f:
                    _h10 = json.load(f)
            except Exception:
                _h10 = {}
        return _h10


def _save():
    tmp = None
    try:
        with _LOCK:
            snap = dict(_h10)
        fd, tmp = tempfile.mkstemp(dir=HERE, prefix='h10_', suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(snap, f, separators=(',', ':'))
        os.replace(tmp, H10_FILE)
    except Exception:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def _fetch(sym):
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?range=10y&interval=1d' % urllib.parse.quote(sym)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEAD), timeout=20) as r:
        res = json.load(r)['chart']['result'][0]
    q = res['indicators']['quote'][0]
    adj = (res['indicators'].get('adjclose') or [{}])[0].get('adjclose') or q['close']
    rows = [(t // 86400, a) for t, a in zip(res['timestamp'], adj) if a]
    return {'at': time.time(), 'd': [x[0] for x in rows], 'c': [round(x[1], 5) for x in rows]}


def _histories(syms):
    h = _load()
    todo = [s for s in syms if s not in h or time.time() - h[s].get('at', 0) > H10_TTL]
    if todo:
        with ThreadPoolExecutor(6) as ex:
            for s, r in zip(todo, ex.map(lambda s: _try(s), todo)):
                if r:
                    with _LOCK:
                        h[s] = r
        _save()
    return {s: h[s] for s in syms if s in h}


def _try(s):
    try:
        return _fetch(s)
    except Exception:
        return None


def _rsi(c, i, n=14):
    g = l = 0.0
    for k in range(i - n + 1, i + 1):
        d = c[k] - c[k - 1]
        g += max(d, 0); l += max(-d, 0)
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


_EPOCH = date(1970, 1, 1).toordinal()


def _positions(c, d):
    """Position (0..1) held during day i+1, decided at the close of day i, for each rule."""
    n = len(c)
    s200, s50 = [None] * n, [None] * n
    run = sum(c[:200])
    for i in range(199, n):
        if i > 199:
            run += c[i] - c[i - 200]
        s200[i] = run / 200
        s50[i] = sum(c[i - 49:i + 1]) / 50
    pos = {k: [0.0] * n for k in RULES}
    week, dip = 0, 0
    for i in range(199, n):
        up = c[i] > s200[i]
        last_of_week = i == n - 1 or date.fromordinal(d[i + 1] + _EPOCH).isocalendar()[:2] != date.fromordinal(d[i] + _EPOCH).isocalendar()[:2]
        if last_of_week or i == 199:
            week = 1 if up else 0
        r = _rsi(c, i)
        if dip == 0 and up and r < 40:
            dip = 1
        elif dip == 1 and (r > 70 or not up):
            dip = 0
        pos['BH'][i] = 1.0
        pos['T200W'][i] = week
        pos['HALFW'][i] = 0.5 + 0.5 * week
        pos['GX'][i] = 1.0 if s50[i] > s200[i] else 0.0
        pos['DIP'][i] = dip
    return pos


def run(baskets, hist):
    """baskets: {cat: [symbol, ...]}, hist: {symbol: {'d','c'}} -> per category and rule: CAGR, volatility, worst fall, ..."""
    out = {}
    for cat, syms in baskets.items():
        items = [hist[s] for s in syms if s in hist and len(hist[s]['c']) >= MIN_DAYS]
        if not items:
            continue
        daily = {k: defaultdict(list) for k in RULES}
        switches = {k: 0.0 for k in RULES}
        inv = {k: [] for k in RULES}
        name_years = 0.0
        for h in items:
            c, d = h['c'], h['d']
            pos = _positions(c, d)
            name_years += (len(c) - 200) / 252
            for k in RULES:
                p = pos[k]
                for i in range(200, len(c)):
                    ret = p[i - 1] * (c[i] / c[i - 1] - 1)
                    if i >= 201 and p[i - 1] != p[i - 2]:
                        ch = abs(p[i - 1] - p[i - 2])
                        ret -= COST * ch
                        switches[k] += ch
                    daily[k][d[i]].append(ret)
                    inv[k].append(p[i - 1])
        res = {}
        for k in RULES:
            ds = sorted(daily[k])
            rets, eq, by_year = [], 1.0, defaultdict(lambda: 1.0)
            pk, mdd = 1.0, 0.0
            for day in ds:
                x = statistics.fmean(daily[k][day])
                rets.append(x)
                eq *= 1 + x
                pk = max(pk, eq)
                mdd = min(mdd, eq / pk - 1)
                by_year[date.fromordinal(day + _EPOCH).year] *= 1 + x
            yrs = len(rets) / 252
            cagr = eq ** (1 / yrs) - 1 if yrs > 0 else 0
            vol = statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 1 else 0
            res[k] = {'cagr': round(cagr * 100, 1), 'vol': round(vol * 100, 1), 'ret_vol': round(cagr / vol, 2) if vol else None,
                      'mdd': round(mdd * 100, 1), 'ret_mdd': round(cagr / -mdd, 2) if mdd else None,
                      'invested': round(statistics.fmean(inv[k]) * 100) if inv[k] else 0,
                      'switch_py': round(switches[k] / name_years, 1) if name_years else 0,
                      'years': {str(y): round((v - 1) * 100, 1) for y, v in sorted(by_year.items())}}
        first = min(h['d'][200] for h in items)
        out[cat] = {'n': len(items), 'start': date.fromordinal(first + _EPOCH).isoformat(), 'rules': res, 'pick': PICK.get(cat, 'BH')}
    return out


def _release():
    """Drop the 10-year prices from memory (about 30 MB as Python objects) once no test is running; the file stays on disk."""
    global _h10
    with _LOCK:
        if not _running:
            _h10 = None


def _job(key, baskets):
    try:
        syms = sorted({s for v in baskets.values() for s in v})
        hist = _histories(syms)
        data = {'ok': True, 'pending': False, 'computed': time.strftime('%Y-%m-%dT%H:%M:%S'), 'labels': LABELS, 'categories': run(baskets, hist),
                'excluded': sorted(s for s in syms if s not in hist or len(hist[s]['c']) < MIN_DAYS)}
        del hist
    except Exception as e:
        data = {'ok': False, 'pending': False, 'error': type(e).__name__}
    with _LOCK:
        _results[key] = {'at': time.time(), 'data': data}
        _results.move_to_end(key)
        while len(_results) > 8:
            _results.popitem(last=False)
        _running.discard(key)
    _release()


def evidence(owner, baskets):
    """Cached result for this user and holdings, or {'pending': True} while a background run computes it."""
    sig = json.dumps({k: sorted(v) for k, v in sorted(baskets.items())})
    key = (owner, sig)
    with _LOCK:
        e = _results.get(key)
        if e and time.time() - e['at'] < RESULT_TTL:
            return e['data']
        start = key not in _running
        if start:
            _running.add(key)
    if start:
        threading.Thread(target=_job, args=(key, baskets), daemon=True).start()
    if e:                                     # stale result while a fresh one is computed
        return dict(e['data'], stale=True)
    return {'ok': True, 'pending': True}


def forget(owner):
    with _LOCK:
        for k in [k for k in _results if k[0] == owner]:
            del _results[k]
