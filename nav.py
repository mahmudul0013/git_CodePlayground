"""
nav.py - net asset value (NAV) history of one portfolio: the whole account and every category (Yahoo sector, the same
grouping as the heat map). Python stdlib only.

Method, day by day (weekdays from the first transaction to today):
  shares_i(day)  = position after the last trade of that asset on or before the day (from the ledger)
  price_i(day)   = Yahoo daily close of the listing (NOT dividend adjusted: it must be the price you could trade at),
                   converted to SEK with that day's FX rate; assets Yahoo cannot price (funds, unmatched symbols) use your
                   own trade prices, drawn in a straight line between trades and to today's export price
  split fix      = when your trade price and Yahoo's close differ by a clean factor (2x, 3x, 10x ...) the asset was split;
                   the factor is applied until your next trade so history stays continuous
  NAV            = sum(shares * price) + cash balance of the ledger
  growth (TWR)   = time-weighted: r(day) = (NAV(day) - deposits(day)) / NAV(day-1) - 1, chained; a deposit is never a gain.
                   Category growth is the price return of yesterday's holdings in that category (buys and sells do not count).

The Yahoo price history is public data and is shared by all users (nav_price_cache.json, 6 h); what is computed from it is
per user and cached per owner (10 minutes, at most 6 owners).
"""
import bisect
import json
import os
import re
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone

import sectors
import symbols

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, 'nav_price_cache.json')
PRICE_TTL = 6 * 3600
FAIL_RETRY = 3600
CURVE_TTL = 600
HEAD = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
SPLIT_FACTORS = (20, 10, 5, 4, 3, 2, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 1 / 20)
PENCE = {'GBp': ('GBP', .01), 'GBX': ('GBP', .01), 'ILA': ('ILS', .01), 'ZAc': ('ZAR', .01)}

_LOCK = threading.Lock()
_prices = None                       # {symbol: {'at','p1','ccy','d':[iso],'c':[close]}}
_fail = {}                           # symbol -> time of the last failed fetch
_curves = OrderedDict()              # owner -> {'key', 'data', 'exp'}


# ───────── price history (public, shared) ─────────
def _load():
    global _prices
    with _LOCK:
        if _prices is None:
            try:
                with open(CACHE_FILE, encoding='utf-8') as f:
                    _prices = json.load(f)
            except Exception:
                _prices = {}
        return _prices


def _save():
    with _LOCK:
        snap = dict(_prices or {})
    try:
        fd, tmp = tempfile.mkstemp(dir=HERE, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(snap, f)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        pass


def _fetch(sym, p1):
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d'
           % (urllib.parse.quote(sym), p1, int(time.time()) + 86400))
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEAD), timeout=20) as r:
        res = json.load(r)['chart']['result'][0]
    off = (res.get('meta') or {}).get('gmtoffset') or 0
    ts = res.get('timestamp') or []
    cl = ((res.get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
    rows = {}
    for t, c in zip(ts, cl):
        if c is not None:
            rows[datetime.fromtimestamp(t + off, timezone.utc).date().isoformat()] = round(float(c), 4)
    days = sorted(rows)
    return {'at': time.time(), 'p1': p1, 'ccy': (res.get('meta') or {}).get('currency'), 'd': days, 'c': [rows[d] for d in days]}


_bg = {'busy': False}


def _refresh_in_background(syms, p1):
    """Refresh stale price series on a daemon thread (one at a time); callers keep using the old data meanwhile."""
    with _LOCK:
        if _bg['busy']:
            return
        _bg['busy'] = True

    def work():
        try:
            cache = _load()
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(_fetch, s, p1): s for s in syms}
                for f, s in futs.items():
                    try:
                        r = f.result(timeout=60)
                        if r['d']:
                            with _LOCK:
                                cache[s] = r
                    except Exception:
                        _fail[s] = time.time()
            _save()
        finally:
            with _LOCK:
                _bg['busy'] = False
    threading.Thread(target=work, daemon=True).start()


def _histories(syms, p1, budget, fetch=True):
    """{symbol: entry} for the symbols; fetches what is missing / stale / too short in parallel for up to `budget` s."""
    cache = _load()
    now = time.time()
    # missing or too short: needed now. Older than the TTL: still usable, refreshed in the background so a page never waits for it.
    todo = [s for s in syms if (s not in cache or cache[s].get('p1', 1 << 60) > p1) and now - _fail.get(s, 0) > FAIL_RETRY]
    stale = [s for s in syms if s in cache and s not in todo and now - cache[s].get('at', 0) > PRICE_TTL and now - _fail.get(s, 0) > FAIL_RETRY]
    if stale and fetch:
        _refresh_in_background(stale, p1)
    pending = 0
    if todo and fetch:
        ex = ThreadPoolExecutor(max_workers=8)
        futs = {ex.submit(_fetch, s, p1): s for s in todo}
        done, notdone = wait(list(futs), timeout=budget)
        changed = False
        for f in done:
            s = futs[f]
            try:
                r = f.result()
                if not r['d']:
                    raise ValueError('no rows')
                with _LOCK:
                    cache[s] = r
                changed = True
            except Exception:
                _fail[s] = time.time()
        pending = len(notdone)
        ex.shutdown(wait=False, cancel_futures=True)
        if changed:
            _save()
    return {s: cache[s] for s in syms if s in cache}, pending


# ───────── small helpers ─────────
def _weekdays(a, b):
    d, out = a, []
    while d <= b:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _ffill(days, closes, grid):
    """Closes aligned on `grid` (last known close carried forward; None before the first bar)."""
    out, j, last = [], 0, None
    for g in grid:
        while j < len(days) and days[j] <= g:
            last = closes[j]
            j += 1
        out.append(last)
    return out


def _interp(points, grid):
    """Linear interpolation of [(iso date, value)] on `grid`, flat outside the points."""
    if not points:
        return [None] * len(grid)
    pts = sorted(points)
    xs = [date.fromisoformat(d).toordinal() for d, _ in pts]
    ys = [v for _, v in pts]
    out = []
    for g in grid:
        x = date.fromisoformat(g).toordinal()
        i = bisect.bisect_right(xs, x)
        if i == 0:
            out.append(ys[0])
        elif i >= len(xs):
            out.append(ys[-1])
        else:
            x0, x1 = xs[i - 1], xs[i]
            out.append(ys[i - 1] + (ys[i] - ys[i - 1]) * ((x - x0) / (x1 - x0) if x1 > x0 else 0))
    return out


def _category(a, info):
    """Same rule as heatCategory() in heatmap.js."""
    s = (info or {}).get(a['isin']) or {}
    if s.get('sector'):
        return s['sector']
    if s.get('category'):
        return s['category']
    if s.get('quote_type') == 'ETF':
        return 'ETFs'
    if s.get('quote_type') == 'MUTUALFUND':
        return 'Funds'
    return 'ETFs' if a.get('type') == 'ETF/ETC' else 'Funds' if a.get('type') == 'Fund' else 'Unclassified'


def _snap(ratio):
    """Nearest clean split factor, or 1 when the prices agree (ratio within 25%)."""
    if 0.8 <= ratio <= 1.25:
        return 1.0
    best = min(SPLIT_FACTORS, key=lambda f: abs(ratio / f - 1))
    return best if abs(ratio / best - 1) < 0.12 else 1.0


# ───────── the curve ─────────
def curve(payload, today=None, budget=40, fetch=True):
    today = today or date.today()
    dep = (((payload.get('insights') or {}).get('deposit_behavior')) or {}).get('series') or []
    trades = payload.get('trades') or []
    assets = [a for a in payload.get('assets') or [] if a.get('isin')]
    if not dep or not trades:
        return {'ok': False, 'error': 'no_history', 'message': 'Not enough transactions to draw a curve yet.'}
    first = date.fromisoformat(dep[0]['date'])
    grid = _weekdays(first, today)
    if len(grid) < 2:
        return {'ok': False, 'error': 'no_history', 'message': 'Not enough history to draw a curve yet.'}
    n = len(grid)
    pos = {g: k for k, g in enumerate(grid)}

    # cash and cumulative net deposits on the grid (ledger rows are calendar days; later days carry the last row)
    cash_by = {r['date']: r['cash'] for r in dep}
    nd_by = {r['date']: r['net_deposited'] for r in dep}
    cash, nd, lc, ln = [], [], 0.0, 0.0
    for g in grid:
        lc, ln = cash_by.get(g, lc), nd_by.get(g, ln)       # ledger rows are daily; days after the last row carry it forward
        cash.append(lc)
        nd.append(ln)

    # symbols, then history
    sym_of = {}
    for a in assets:
        r = symbols.resolve(a['isin'], a['name'], a.get('ccy'))
        if r and r.get('symbol') and not r['symbol'].startswith('0P'):
            sym_of[a['isin']] = r['symbol']
    p1 = int(datetime.combine(first - timedelta(days=10), datetime.min.time(), tzinfo=timezone.utc).timestamp())
    hist, pending = _histories(sorted(set(sym_of.values())), p1, budget, fetch)
    # FX: SEK per unit of every listing currency
    codes = set()
    for s, h in hist.items():
        c = (h.get('ccy') or 'SEK')
        codes.add(PENCE.get(c, (c, 1))[0])
    codes.discard('SEK')
    fx_hist, fx_pending = _histories(sorted(f'{c}SEK=X' for c in codes), p1, budget, fetch)
    pending += fx_pending
    fx_on = {}
    for c in codes:
        h = fx_hist.get(f'{c}SEK=X')
        if h:
            fx_on[c] = _ffill(h['d'], h['c'], grid)

    sec_info, sec_pending = sectors.batch([{'isin': a['isin'], 'name': a['name'], 'ccy': a.get('ccy')} for a in assets], budget=6 if fetch else 0.1)
    pending += 1 if sec_pending else 0

    by_isin = {}
    for t in trades:
        by_isin.setdefault(t['isin'], []).append(t)

    cats = {}          # name -> {'v': [...], 'rn': [...]}
    asset_cat = {}
    est_val_last = yahoo_val_last = 0.0
    est_names = []
    snap_names = []
    rejected = []
    for a in assets:
        isin = a['isin']
        tl = sorted(by_isin.get(isin, []), key=lambda t: (t['date'], str(t.get('id', ''))))
        if not tl:
            continue
        ev_d, ev_q = [], []
        for t in tl:
            if ev_d and ev_d[-1] == t['date']:
                ev_q[-1] = t['pos_after']
            else:
                ev_d.append(t['date'])
                ev_q.append(t['pos_after'])
        qty = [0.0] * n
        for k, g in enumerate(grid):
            i = bisect.bisect_right(ev_d, g)
            qty[k] = ev_q[i - 1] if i else 0.0
        if not any(qty):
            continue

        # fallback prices from your own trades (SEK per unit)
        pts = [(t['date'], t['gross'] / t['qty']) for t in tl if t.get('qty') and t.get('gross')]
        if a.get('held') and a.get('qty') and a.get('value'):
            pts.append((grid[-1], a['value'] / a['qty']))
        fb = _interp(pts, grid)

        sym = sym_of.get(isin)
        h = hist.get(sym) if sym else None
        raw, f = None, [1.0] * n
        used_yahoo = False
        if h:
            ccy = h.get('ccy') or 'SEK'
            code, unit = PENCE.get(ccy, (ccy, 1.0))
            fxs = [1.0] * n if code == 'SEK' else fx_on.get(code)
            if fxs is not None:
                cl = _ffill(h['d'], h['c'], grid)
                raw = [(c * unit * x if (c is not None and x is not None) else None) for c, x in zip(cl, fxs)]
                used_yahoo = any(v is not None for v in raw)
        if raw is None:
            raw = [None] * n
        # split factor: your trade price vs Yahoo's close on the trade day (only when both are in the same currency)
        if used_yahoo and h:
            cl_local = _ffill(h['d'], h['c'], grid)
            marks = []
            for t in tl:
                j = pos.get(t['date'])
                if j is None:                                  # trade on a weekend / holiday: use the next grid day
                    j = bisect.bisect_left(grid, t['date'])
                if j < n and cl_local[j] and t.get('price') and str(t.get('ccy') or '').upper() == str(h.get('ccy') or '').upper():
                    marks.append((j, _snap(t['price'] / cl_local[j])))
            if marks:
                marks.sort()
                cur_f, mi = 1.0, 0
                for k in range(n):
                    while mi < len(marks) and marks[mi][0] <= k:
                        cur_f = marks[mi][1]
                        mi += 1
                    f[k] = cur_f
                if any(x != 1.0 for x in f):
                    snap_names.append(a['name'])
        # trust check: Yahoo's price in SEK must agree with what you actually paid / what the export says; a symbol that points at
        # another instrument (a US ticker for a euro-listed UCITS fund ...) is dropped and the asset falls back to your own prices
        if used_yahoo:
            rat = []
            for t in tl:
                j = pos.get(t['date'], bisect.bisect_left(grid, t['date']))
                if j < n and raw[j] and t.get('qty') and t.get('gross'):
                    rat.append((t['gross'] / t['qty']) / (raw[j] * f[j]))
            if a.get('held') and a.get('qty') and a.get('value') and raw[-1]:
                rat.append((a['value'] / a['qty']) / (raw[-1] * f[-1]))
            rat.sort()
            med = rat[len(rat) // 2] if rat else 1.0
            if not (0.6 <= med <= 1.7):
                raw, f, used_yahoo = [None] * n, [1.0] * n, False
                rejected.append(a['name'])
        price = [(r if r is not None else b) for r, b in zip(raw, fb)]
        cat = _category(a, sec_info)
        asset_cat[isin] = cat
        c = cats.setdefault(cat, {'v': [0.0] * n, 'rn': [0.0] * n})
        for k in range(n):
            if price[k] is None:
                continue
            c['v'][k] += qty[k] * price[k] * f[k]
            if k:
                c['rn'][k] += qty[k - 1] * (price[k] - price[k - 1]) * f[k - 1]
        last_v = qty[-1] * (price[-1] or 0) * f[-1]
        if used_yahoo:
            yahoo_val_last += last_v
        elif qty[-1] > 0:
            est_val_last += last_v
            est_names.append((last_v, a['name']))

    # totals and time-weighted indices
    hold = [sum(c['v'][k] for c in cats.values()) for k in range(n)]
    nav = [hold[k] + cash[k] for k in range(n)]
    twr = [100.0]
    for k in range(1, n):
        prev = nav[k - 1]
        r = ((nav[k] - (nd[k] - nd[k - 1])) / prev - 1) if prev > 0 else 0.0
        twr.append(twr[-1] * (1 + r))
    out_cats = {}
    for name, c in cats.items():
        idx, base = [100.0], 100.0
        for k in range(1, n):
            pv = c['v'][k - 1]
            r = c['rn'][k] / pv if pv > 1e-9 else 0.0
            base *= 1 + r
            idx.append(base)
        first_pos = next((k for k, v in enumerate(c['v']) if v > 1e-6), None)
        if first_pos is None:
            continue
        out_cats[name] = {'value': [round(v, 2) for v in c['v']], 'twr': [round(x, 3) for x in idx], 'first': first_pos}
    order = sorted(out_cats, key=lambda k: -out_cats[k]['value'][-1])
    ov = (payload.get('insights') or {}).get('overview') or {}
    exp_total = ov.get('total_value')
    hf = ((payload.get('sources') or {}).get('holdings') or {}).get('file') or ''
    m = re.search(r'\d{4}-\d{2}-\d{2}', hf)
    k_exp = max(0, bisect.bisect_right(grid, m.group(0)) - 1) if m else n - 1       # last weekday on or before the export date
    diff = round((nav[k_exp] / exp_total - 1) * 100, 2) if exp_total else None
    cov_total = (yahoo_val_last + est_val_last) or 1.0
    return {
        'ok': True, 'asof': datetime.now().isoformat(timespec='seconds'), 'today': today.isoformat(), 'pending': pending,
        'dates': grid,
        'total': {'nav': [round(v, 2) for v in nav], 'cash': [round(v, 2) for v in cash], 'net_deposits': [round(v, 2) for v in nd], 'twr': [round(x, 3) for x in twr]},
        'categories': out_cats, 'order': order, 'asset_cat': asset_cat,
        'coverage': {'yahoo_pct': round(yahoo_val_last / cov_total * 100, 1), 'estimated': [x[1] for x in sorted(est_names, reverse=True)[:6]],
                     'split_fixed': snap_names[:6], 'symbol_rejected': rejected[:8], 'nav_vs_export_pct': diff, 'export_date': grid[k_exp]},
        'summary': _summary(grid, nav, nd, twr, today),
    }


# ───────── range statistics (the page recomputes the same on its own, this feeds the assistant / tests) ─────────
def range_start(grid, key, today):
    if key == 'max':
        return 0
    if key == 'ytd':
        cut = date(today.year, 1, 1).isoformat()
    else:
        days = {'1w': 7, '1m': 30, '3m': 91, '1y': 365, '3y': 1096}[key]
        cut = (today - timedelta(days=days)).isoformat()
    return min(bisect.bisect_left(grid, cut), len(grid) - 1)


def _summary(grid, nav, nd, twr, today):
    out = {'nav': round(nav[-1], 2), 'net_deposits': round(nd[-1], 2), 'first_date': grid[0], 'ranges': {}}
    for key in ('1w', '1m', '3m', 'ytd', '1y', '3y', 'max'):
        s = range_start(grid, key, today)
        peak, dd = twr[s], 0.0
        for v in twr[s:]:
            peak = max(peak, v)
            dd = min(dd, v / peak - 1)
        out['ranges'][key] = {'from': grid[s], 'twr_pct': round((twr[-1] / twr[s] - 1) * 100, 2), 'change': round(nav[-1] - nav[s], 2),
                              'deposits': round(nd[-1] - nd[s], 2), 'max_drop_pct': round(dd * 100, 2)}
    return out


# ───────── anchor to the live valuation (valuation.py) ─────────
def anchored(c, snap):
    """The same curve with its LAST day replaced by the live valuation: account value, cash and every category value are the
    snapshot's, so the tile on the Portfolio page, the Analytics tiles and the last point of this chart are the same number.
    The growth index takes the last step from that value. Earlier days stay the daily-close reconstruction."""
    if not c or not c.get('ok') or not snap or not snap.get('ok'):
        return c
    t = snap['totals']
    n = len(c['dates'])
    k = n - 1
    out = dict(c)
    tot = {key: list(vals) for key, vals in c['total'].items()}
    tot['nav'][k] = round(t['account'], 2)
    tot['cash'][k] = round(t['cash'], 2)
    prev = tot['nav'][k - 1]
    nd = tot['net_deposits']
    r = ((tot['nav'][k] - (nd[k] - nd[k - 1])) / prev - 1) if prev > 0 else 0.0
    tot['twr'][k] = round(tot['twr'][k - 1] * (1 + r), 3)
    out['total'] = tot
    by_cat = {}
    for isin, a in snap['assets'].items():
        cat = (c.get('asset_cat') or {}).get(isin)
        if cat:
            by_cat[cat] = by_cat.get(cat, 0.0) + a['value']
    cats = {}
    for name, cv in c['categories'].items():
        cc = dict(cv)
        cc['value'] = list(cv['value'])
        cc['value'][k] = round(by_cat.get(name, 0.0), 2)
        cats[name] = cc
    out['categories'] = cats
    out['order'] = sorted(cats, key=lambda x: -cats[x]['value'][-1])
    today = date.fromisoformat(c['today'])
    out['summary'] = _summary(c['dates'], tot['nav'], nd, tot['twr'], today)
    cov = dict(c.get('coverage') or {})
    cov['anchored_to'] = snap.get('asof')
    out['coverage'] = cov
    return out


# ───────── per-owner cache ─────────
def get(owner, payload, fetch=True):
    key = (payload.get('generated'), date.today().isoformat(), bool(fetch))
    with _LOCK:
        e = _curves.get(owner)
        if e and e['key'][:2] == key[:2] and time.time() < e['exp']:
            _curves.move_to_end(owner)
            return e['data']
    data = curve(payload, fetch=fetch)
    with _LOCK:
        _curves[owner] = {'key': key, 'data': data, 'exp': time.time() + (60 if (data.get('pending') or not data.get('ok')) else CURVE_TTL)}
        _curves.move_to_end(owner)
        while len(_curves) > 6:
            _curves.popitem(last=False)
    return data


def cached_curve(owner):
    """The finished curve of this owner or None (never fetches anything)."""
    with _LOCK:
        e = _curves.get(owner)
    d = e['data'] if e else None
    return d if d and d.get('ok') else None


def cached_summary(owner):
    """The summary of a finished curve of this owner, or None (never fetches anything)."""
    with _LOCK:
        e = _curves.get(owner)
    d = e['data'] if e else None
    return d.get('summary') if d and d.get('ok') else None


def forget(owner):
    with _LOCK:
        _curves.pop(owner, None)
