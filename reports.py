"""
reports.py - upcoming company reports (earnings) and ex-dividend dates of the current holdings, from Yahoo Finance.
Python stdlib only.

Yahoo quoteSummary `calendarEvents` (needs the cookie + crumb that sectors.py already handles) gives, per symbol, the next
earnings date (a date range while it is only an estimate), the average EPS estimate and the ex-dividend / payment dates.
Those are PUBLIC per-symbol facts, so they are cached for everybody in report_cache.json (12 h; a failed lookup is retried
after 1 h). Which of them show up for a user is decided from that user's holdings only.

    upcoming(payload, today=None, budget=25) -> {ok, today, groups:{today,tomorrow,week,later}, counts, covered, pending, ...}
"""
import json
import os
import tempfile
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone

import sectors
import symbols

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, 'report_cache.json')
TTL_OK = 12 * 3600
TTL_MISS = 3600
WEEK_DAYS = 7
LATER_DAYS = 30

_LOCK = threading.Lock()
_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_FILE, encoding='utf-8') as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _save():
    try:
        fd, tmp = tempfile.mkstemp(dir=HERE, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(_cache, f)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        pass


def _day(ts):
    """Yahoo timestamp (seconds) -> 'YYYY-MM-DD' (UTC date, which is what Yahoo shows for the calendar)."""
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat()
    except Exception:
        return None


def _fetch(sym):
    op, crumb = sectors._crumb_opener()
    if not op:
        raise RuntimeError('no crumb')
    url = ('https://query2.finance.yahoo.com/v10/finance/quoteSummary/%s?modules=calendarEvents&crumb=%s'
           % (urllib.parse.quote(sym), urllib.parse.quote(crumb)))
    d = json.loads(sectors._get(url, op, timeout=12))
    res = (d.get('quoteSummary') or {}).get('result') or []
    ce = (res[0].get('calendarEvents') if res else None) or {}
    e = ce.get('earnings') or {}
    dates = [_day(x.get('raw')) for x in (e.get('earningsDate') or []) if x.get('raw')]
    dates = [x for x in dates if x]
    eps = (e.get('earningsAverage') or {}).get('raw')
    return {
        'at': time.time(),
        'earnings': {'date': dates[0], 'end': dates[-1] if len(dates) > 1 else None,
                     'estimate': bool(e.get('isEarningsDateEstimate')), 'eps': eps} if dates else None,
        'ex_div': _day((ce.get('exDividendDate') or {}).get('raw')),
        'pay_div': _day((ce.get('dividendDate') or {}).get('raw')),
    }


def _events_for(syms, budget, fetch=True):
    """{symbol: entry} for the symbols, fetching what is missing or stale in parallel for up to `budget` seconds
    (fetch=False: cache only, never touches the network)."""
    c = _load()
    now = time.time()
    todo = []
    for s in syms:
        ent = c.get(s)
        ttl = TTL_OK if ent and not ent.get('miss') else TTL_MISS
        if not ent or now - ent.get('at', 0) > ttl:
            todo.append(s)
    pending = 0
    if todo and fetch:
        ex = ThreadPoolExecutor(max_workers=6)
        futs = {ex.submit(_fetch, s): s for s in todo}
        done, notdone = wait(list(futs), timeout=budget)
        changed = False
        for f in done:
            s = futs[f]
            try:
                r = f.result()
            except Exception:
                r = {'at': time.time(), 'miss': True, 'earnings': None, 'ex_div': None, 'pay_div': None}
            with _LOCK:
                c[s] = r
            changed = True
        pending = len(notdone)
        ex.shutdown(wait=False, cancel_futures=True)
        if changed:
            with _LOCK:
                _save()
    return {s: c[s] for s in syms if s in c}, pending


def _bucket(days):
    return 'today' if days == 0 else 'tomorrow' if days == 1 else 'week' if days <= WEEK_DAYS else 'later'


def upcoming(payload, today=None, budget=25, fetch=True):
    """Upcoming reports / ex-dividend dates of the held stocks and ETFs in `payload` (one user's data)."""
    today = today or date.today()
    held = [a for a in payload.get('assets', []) if a.get('held') and a.get('value') and a.get('isin')]
    total = sum(a['value'] for a in held) or 1.0
    sym_of = {}
    for a in held:
        r = symbols.resolve(a['isin'], a['name'], a.get('ccy'))
        if r and r.get('symbol') and not r['symbol'].startswith('0P'):
            sym_of[a['isin']] = r['symbol']
    ev, pending = _events_for(sorted(set(sym_of.values())), budget, fetch)
    by_isin = {}
    groups = {'today': [], 'tomorrow': [], 'week': [], 'later': []}
    stale = covered = 0
    for a in held:
        s = sym_of.get(a['isin'])
        e = ev.get(s)
        if not e or e.get('miss'):
            continue
        covered += 1
        w = round(a['value'] / total * 100, 2)
        by_isin[a['isin']] = {'name': a['name'], 'earnings': e.get('earnings'), 'ex_div': e.get('ex_div'), 'pay_div': e.get('pay_div')}
        items = []
        er = e.get('earnings')
        if er:
            dd = date.fromisoformat(er['date'])
            if dd < today:
                stale += 1                                  # Yahoo has not rolled the date forward yet
            else:
                items.append({'kind': 'earnings', 'date': er['date'], 'end': er.get('end'), 'estimate': er.get('estimate'), 'eps': er.get('eps')})
        for key, kind in (('ex_div', 'ex_dividend'),):
            if e.get(key) and date.fromisoformat(e[key]) >= today:
                items.append({'kind': kind, 'date': e[key], 'end': None, 'estimate': False, 'eps': None})
        for it in items:
            days = (date.fromisoformat(it['date']) - today).days
            if days > LATER_DAYS:
                continue
            groups[_bucket(days)].append({**it, 'days': days, 'name': a['name'], 'isin': a['isin'], 'symbol': s, 'weight': w, 'ccy': a.get('ccy')})
    for g in groups.values():
        g.sort(key=lambda x: (x['date'], x['kind'] != 'earnings', -x['weight']))
    return {'ok': True, 'today': today.isoformat(), 'groups': groups,
            'counts': {k: len(v) for k, v in groups.items()}, 'covered': covered, 'holdings': len(held),
            'stale': stale, 'pending': pending, 'by_isin': by_isin, 'asof': datetime.now().isoformat(timespec='seconds')}
