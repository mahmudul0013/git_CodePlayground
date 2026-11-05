"""
advisor.py - rule-based Add / Trim review of the current holdings (Analytics "Advice" tab, Assets table column,
Portfolio page "Add / Trim ideas"). Python stdlib only.

This is POSITION MANAGEMENT, not a price forecast. A backtest on 77 holdings (5 years of Yahoo daily data, 70 000
samples) showed no predictive power in the old next-day indicator score, and "trim when overbought" would have cut
winners that kept rising. So actions come from what is measurable and controllable:
  * position size vs a cap, theme (Yahoo sector) concentration, tiny positions and their fee drag,
  * trend health (50/200-day averages, 12-1 month momentum) used only as a tilt for ADD and a flag for REVIEW,
  * volatility, drawdown from the 52-week high, correlation of the whole portfolio.

    advise(payload, quotes_by_isin=None) -> {ok, asof, assets: {isin: {...}}, cards: [...], summary: {...}}
"""
import json
import math
import os
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date

import sectors
import symbols

HERE = os.path.dirname(os.path.abspath(__file__))
HIST_FILE = os.path.join(HERE, 'history_cache.json')
HIST_TTL = 6 * 3600
HEAD = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

MAX_W = 4.0          # % of holdings: above this a position is trimmed back
TARGET_W = 2.0       # % of holdings: ADD fills up to this
ADD_BELOW_W = 1.5    # only positions below this weight are ADD candidates
THEME_CAP = 40.0     # % of holdings in one Yahoo sector: no new ADDs there, largest names trimmed
DUST = 1500          # kr: positions below this cost more attention and fees than they can earn
MIN_ORDER = 1500     # kr: smaller orders are mostly courtage

_LOCK = threading.Lock()
_hist = None                          # {symbol: {'at': ts, 'c': [closes], 'd': [epoch days]}}
_cache = {'key': None, 'data': None}


# ───────── price history (Yahoo v8 chart, adjusted close, 2 years) ─────────
def _load():
    global _hist
    if _hist is None:
        try:
            with open(HIST_FILE, encoding='utf-8') as f:
                _hist = json.load(f)
        except Exception:
            _hist = {}
    return _hist


def _save():
    try:
        fd, tmp = tempfile.mkstemp(dir=HERE, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(_hist, f)
        os.replace(tmp, HIST_FILE)
    except Exception:
        pass


def _fetch(sym):
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d' % urllib.request.quote(sym)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEAD), timeout=15) as r:
        res = json.load(r)['chart']['result'][0]
    q = res['indicators']['quote'][0]
    adj = (res['indicators'].get('adjclose') or [{}])[0].get('adjclose') or q['close']
    rows = [(t // 86400, a) for t, a in zip(res['timestamp'], adj) if a]
    return {'at': time.time(), 'd': [r[0] for r in rows], 'c': [round(r[1], 4) for r in rows], 'ccy': res['meta'].get('currency')}


def _histories(syms, budget=45):
    h = _load()
    todo = [s for s in syms if s not in h or time.time() - h[s]['at'] > HIST_TTL]
    if todo:
        ex = ThreadPoolExecutor(max_workers=6)
        futs = {ex.submit(_fetch, s): s for s in todo}
        done, _ = wait(list(futs), timeout=budget)
        changed = False
        for f in done:
            try:
                with _LOCK:
                    h[futs[f]] = f.result()
                changed = True
            except Exception:
                pass
        ex.shutdown(wait=False, cancel_futures=True)
        if changed:
            _save()
    return {s: h[s] for s in syms if s in h}


# ───────── indicators ─────────
def _sma(c, n):
    return sum(c[-n:]) / n if len(c) >= n else None


def _std(a):
    m = sum(a) / len(a)
    return math.sqrt(sum((x - m) ** 2 for x in a) / len(a))


def _rsi(c, n=14):
    if len(c) <= n:
        return None
    g = l = 0.0
    for i in range(len(c) - n, len(c)):
        d = c[i] - c[i - 1]
        g += max(d, 0); l += max(-d, 0)
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def _features(c):
    if len(c) < 60:
        return None
    n = len(c)
    s50, s200 = _sma(c, 50), _sma(c, 200)
    f = {
        'last': c[-1], 'sma50': s50, 'sma200': s200,
        'vs200': c[-1] / s200 - 1 if s200 else None,
        'ext50': c[-1] / s50 - 1 if s50 else None,
        'mom12_1': c[-22] / c[-253] - 1 if n >= 253 else None,
        'ret21': c[-1] / c[-22] - 1 if n >= 22 else None,
        'rsi': _rsi(c),
        'dd52': c[-1] / max(c[-252:]) - 1,
        'vol': _std([c[i] / c[i - 1] - 1 for i in range(n - 60, n)]) * math.sqrt(252) if n >= 61 else None,
    }
    if s200:
        f['trend'] = 'up' if c[-1] > s200 and s50 > s200 else 'down' if c[-1] < s200 and s50 < s200 else 'mixed'
    else:
        f['trend'] = 'n/a'
    return f


def _pct_rank(vals, v):
    v_ok = sorted(x for x in vals if x is not None)
    return sum(x <= v for x in v_ok) / len(v_ok) if v_ok and v is not None else .5


def _n(x):
    return f'{x:,.0f}'.replace(',', ' ')


def _round500(x):
    return int(round(x / 500.0)) * 500


# ───────── main ─────────
def advise(payload, live=None):
    """live: optional {isin: {'price', 'currency'}} to value positions at today's price."""
    live = live or {}
    held = [a for a in payload['assets'] if a.get('held') and a.get('value') and a.get('isin')]
    if not held:
        return {'ok': False, 'error': 'no holdings'}
    syms, sym_of = [], {}
    for a in held:
        r = symbols.resolve(a['isin'], a['name'], a.get('ccy'))
        if r and not r['symbol'].startswith('0P'):
            sym_of[a['isin']] = r['symbol']; syms.append(r['symbol'])
    hist = _histories(sorted(set(syms)))
    sec, _pending = sectors.batch([{'isin': a['isin'], 'name': a['name'], 'ccy': a.get('ccy')} for a in held], budget=8)

    # value each holding at the newest price (same guard as the heat map: same currency, ratio 0.5-2)
    rows = []
    for a in held:
        val = a['value']
        h = hist.get(sym_of.get(a['isin']))
        l = live.get(a['isin'])
        px, ccy = None, None
        if l and l.get('price'):
            px, ccy = l['price'], l.get('currency')
        elif h:
            px, ccy = h['c'][-1], h.get('ccy')
        if px and a.get('price') and str(ccy or '').upper() == str(a.get('ccy', '')).upper():
            ratio = px / a['price']
            if .5 < ratio < 2:
                val = a['value'] * ratio
        rows.append({'a': a, 'val': val, 'h': h})
    total = sum(r['val'] for r in rows)
    for r in rows:
        r['w'] = r['val'] / total * 100
        r['f'] = _features(r['h']['c']) if r['h'] else None
        s = sec.get(r['a']['isin']) or {}
        r['sector'] = s.get('sector') or s.get('category') or ('Funds' if r['a'].get('type') == 'Fund' else 'Unclassified')
        r['industry'] = s.get('industry')

    # theme concentration
    theme = {}
    for r in rows:
        theme[r['sector']] = theme.get(r['sector'], 0) + r['w']
    top_sector = max(theme, key=theme.get)
    over_theme = {k for k, v in theme.items() if v > THEME_CAP and k not in ('Unclassified', 'Funds')}

    moms = [r['f']['mom12_1'] for r in rows if r['f'] and r['f']['mom12_1'] is not None]
    vols = [r['f']['vol'] for r in rows if r['f'] and r['f']['vol'] is not None]

    out = {}
    for r in sorted(rows, key=lambda x: -x['val']):
        a, f, w = r['a'], r['f'], r['w']
        up = a.get('unrealized_pct')
        res = {'name': a['name'], 'action': 'HOLD', 'amount': 0, 'weight': round(w, 2), 'sector': r['sector'], 'reasons': [], 'score': 0,
               'metrics': {}, 'target_weight': None}
        if f:
            res['metrics'] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items() if k in ('trend', 'vs200', 'mom12_1', 'rsi', 'dd52', 'vol', 'ret21')}
        why = res['reasons']
        done = False
        # 1) risk: oversized position
        if w > MAX_W:
            cut = (w - MAX_W) / 100 * total
            res.update(action='TRIM', amount=_round500(max(cut, MIN_ORDER)), target_weight=MAX_W, score=min(100, int(w / MAX_W * 50)))
            why.append(f'{w:.1f}% of the portfolio is above the {MAX_W:.0f}% single-position cap; one stock should not decide the result.')
            done = True
        # 2) theme concentration: largest names of an over-weight sector give some back
        if not done and r['sector'] in over_theme and w >= 2.5:
            cut = w * 0.2 / 100 * total
            res.update(action='TRIM', amount=_round500(max(cut, MIN_ORDER)), target_weight=round(w * 0.8, 2), score=min(100, int(theme[r['sector']])))
            why.append(f'{r["sector"]} is {theme[r["sector"]]:.0f}% of the portfolio (cap {THEME_CAP:.0f}%); trimming a fifth of a large {r["sector"].lower()} holding lowers the shared risk without selling the idea.')
            done = True
        # 3) tiny position
        if not done and a['value'] < DUST:
            res.update(action='CONSOLIDATE', amount=int(a['value']), score=40)
            why.append(f'Only {a["value"]:.0f} kr. A round trip costs about {2 * 8:.0f} kr in courtage and it cannot move the result; sell it or top up to a meaningful size.')
            done = True
        # 4) broken trend with a large loss: review (flag only, backtest shows no sell edge)
        if not done and f and f['trend'] == 'down' and (f['mom12_1'] or 0) < 0 and up is not None and up < -15:
            res.update(action='REVIEW', score=55)
            why.append(f'Below its 200-day average, negative 12-month momentum and {up:.0f}% under your cost. Decide if the original reason still holds; if not, selling frees capital for better uses.')
            done = True
        # 5) ADD candidates: small weight, uptrend, pulled back, not stretched, theme not already over the cap
        if not done and f and w < ADD_BELOW_W and f['trend'] == 'up' and (f['mom12_1'] or 0) > 0 \
                and -0.25 <= f['dd52'] <= -0.05 and (f['rsi'] or 50) < 68 and r['sector'] not in over_theme:
            need = (TARGET_W - w) / 100 * total
            mp, vp = _pct_rank(moms, f['mom12_1']), _pct_rank(vols, f['vol'])
            pull = min(1.0, (-f['dd52'] - .05) / .15)
            res.update(action='ADD', amount=_round500(max(need, MIN_ORDER)), target_weight=TARGET_W,
                       score=int(100 * (.5 * mp + .25 * pull + .25 * (1 - vp))))
            why.append(f'Uptrend (above 200-day), 12-month momentum {f["mom12_1"] * 100:+.0f}%, pulled back {f["dd52"] * 100:.0f}% from its 52-week high, and only {w:.1f}% of the portfolio. Fill up to about {TARGET_W:.0f}%.')
            done = True
        if not done:
            if f and f['trend'] == 'up':
                why.append('Healthy trend, no action needed.' if w >= ADD_BELOW_W else 'Uptrend but not pulled back enough to add now.')
            elif f and f['trend'] == 'down':
                why.append('Below its long-term trend; held at its small size.')
            elif not f:
                why.append('No Yahoo price history (fund or unmatched): kept as is.')
            else:
                why.append('No clear signal.')
        if r['sector'] in over_theme and res['action'] == 'HOLD' and w < ADD_BELOW_W and f and f['trend'] == 'up':
            why.append(f'No add: {r["sector"]} is already {theme[r["sector"]]:.0f}% of the portfolio.')
        out[a['isin']] = res

    # ───── portfolio level: volatility, drawdown, correlation from the last year of daily returns ─────
    port = _portfolio_stats(rows, total)

    n_dust = sum(1 for r in rows if r['a']['value'] < DUST)
    dust_val = sum(r['a']['value'] for r in rows if r['a']['value'] < DUST)
    below1 = sum(1 for r in rows if r['w'] < 1)
    wt = [r for r in rows if r['f'] and r['f']['trend'] == 'down']
    wt_pct = sum(r['w'] for r in wt)
    broken_loss = sum(1 for r in rows if out[r['a']['isin']]['action'] == 'REVIEW')
    cards = []

    def card(sev, title, num, text):
        cards.append({'sev': sev, 'title': title, 'num': num, 'text': text})

    card('high' if len(rows) > 40 else 'med', 'Too many small positions', f'{len(rows)} positions',
         f'{below1} are below 1% and {n_dust} are under {DUST} kr ({_n(dust_val)} kr in total). The biggest is {max(r["w"] for r in rows):.1f}%, so no single holding matters, but you pay courtage on each, cannot follow them all, and the whole behaves like an index with extra costs. A realistic target is 20-30 positions of at least 1.5-2% each.')
    tech_names = ', '.join(r['a']['name'] for r in sorted(rows, key=lambda x: -x['w']) if r['sector'] == top_sector)[:140]
    card('high' if theme[top_sector] > THEME_CAP else 'med', 'Theme concentration', f'{top_sector} {theme[top_sector]:.0f}%',
         f'The {len(rows)} names are not {len(rows)} independent bets. {top_sector} is {theme[top_sector]:.0f}% of the portfolio ({tech_names}...). They fall together in a sector sell-off; the Advice column therefore trims the largest of them and blocks new adds there.')
    if port:
        card('high' if port['max_dd'] < -.25 else 'med', 'Risk of the portfolio as it stands now', f'vol {port["vol"] * 100:.0f}% · max drop {port["max_dd"] * 100:.0f}%',
             f'Over the last year, with today\'s weights, the portfolio moved about {port["vol"] * 100:.0f}% a year up or down and its worst peak-to-trough fall was {port["max_dd"] * 100:.0f}%. The average correlation between your top {port["n"]} holdings is {port["corr"]:.2f}, which behaves like roughly {port["eff_n"]:.0f} independent bets rather than {len(rows)}.')
    card('med' if wt_pct > 25 else 'info', 'Trend health', f'{wt_pct:.0f}% in downtrend',
         f'{len(wt)} holdings ({wt_pct:.0f}% of value) trade below both 50- and 200-day averages; {broken_loss} of them are also more than 15% under your cost and flagged REVIEW. Downtrends are not a sell signal on their own (the backtest found no edge), but they are where the original reason for owning should be re-checked.')
    adds = [v for v in out.values() if v['action'] == 'ADD']
    trims = [v for v in out.values() if v['action'] == 'TRIM']
    card('info', 'Size of the proposed changes', f'+{_n(sum(v["amount"] for v in out.values() if v["action"] == "ADD"))} / -{_n(sum(v["amount"] for v in trims))} kr',
         f'{len(adds)} ADD ideas and {len(trims)} TRIM ideas. Execute with few, larger orders (at least {MIN_ORDER} kr) and let sells fund the buys so no new deposit is needed.')

    summary = {'positions': len(rows), 'total': round(total), 'theme': {k: round(v, 1) for k, v in sorted(theme.items(), key=lambda x: -x[1])},
               'counts': {k: sum(1 for v in out.values() if v['action'] == k) for k in ('ADD', 'TRIM', 'CONSOLIDATE', 'REVIEW', 'HOLD')},
               'portfolio': port, 'covered': sum(1 for r in rows if r['f']) , 'asof': date.today().isoformat()}
    return {'ok': True, 'asof': time.strftime('%Y-%m-%dT%H:%M:%S'), 'assets': out, 'cards': cards, 'summary': summary}


def _portfolio_stats(rows, total):
    """Daily returns of today's weights over the last ~250 common days; vol, max drawdown, avg pairwise correlation."""
    use = [r for r in rows if r['h'] and len(r['h']['c']) >= 200]
    if len(use) < 5:
        return None
    use.sort(key=lambda r: -r['w'])
    maps = [dict(zip(r['h']['d'], r['h']['c'])) for r in use]
    days = sorted(set.intersection(*[set(m) for m in maps[:max(5, len(use) // 2)]]))[-251:]
    if len(days) < 120:
        return None
    wsum = sum(r['w'] for r in use)
    rets = []
    for r, m in zip(use, maps):
        series, prev = [], None
        for d in days:
            v = m.get(d, prev)
            series.append(None if v is None or prev is None else v / prev - 1)
            prev = v if v is not None else prev
        rets.append(series[1:])
    port = []
    for i in range(len(days) - 1):
        port.append(sum(use[j]['w'] / wsum * (rets[j][i] or 0) for j in range(len(use))))
    vol = _std(port) * math.sqrt(252)
    eq, peak, dd = 1.0, 1.0, 0.0
    for x in port:
        eq *= 1 + x; peak = max(peak, eq); dd = min(dd, eq / peak - 1)
    top = [x for x in rets[:30]]
    cs = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            a = [x or 0 for x in top[i]]; b = [x or 0 for x in top[j]]
            ma, mb = sum(a) / len(a), sum(b) / len(b)
            va = sum((x - ma) ** 2 for x in a); vb = sum((x - mb) ** 2 for x in b)
            if va > 0 and vb > 0:
                cs.append(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb))
    corr = sum(cs) / len(cs) if cs else 0
    n = len(top)
    eff = n / (1 + (n - 1) * max(corr, 0)) if n else 0
    return {'vol': round(vol, 4), 'max_dd': round(dd, 4), 'corr': round(corr, 3), 'n': n, 'eff_n': round(eff, 1), 'days': len(port)}


def get(payload, live=None):
    """Cached per payload version and calendar hour (single slot, memory stays flat)."""
    key = (payload.get('generated'), time.strftime('%Y%m%d%H'), bool(live))
    with _LOCK:
        if _cache['key'] == key:
            return _cache['data']
    data = advise(payload, live)
    with _LOCK:
        _cache['key'], _cache['data'] = key, data
    return data
