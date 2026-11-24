"""
advisor.py - the portfolio plan: one strategy per category (strategy.py), turned into concrete actions for each holding
(Analytics "Advice" tab, Assets table column, Portfolio page idea panels). Python stdlib only.

This is POSITION MANAGEMENT, not a price forecast. The rules come from a 10-year test of your own holdings per category
(strategy_bt.py) and from what is measurable and controllable: the mix against its targets, position size, the weekly
SMA(200) trend, tiny positions and their fee drag, and the money you deposit each month.

    advise(payload, live=None, profile='balanced', settings=None)
      -> {ok, asof, assets: {isin: {...}}, cards: [...], summary: {...}, plan: {...}}

Actions (same names as before so every page keeps working):
  ADD          new money into this holding this month (index funds by the deposit plan; stocks only in an uptrend with RSI(14)
               below the profile's level, and only when their category is under its target)
  BUYBACK      a stock you sold whose category is under target, back in an uptrend and pulled back
  WATCH        close to an ADD: uptrend and category under target, RSI a little above the entry level
  TRIM         a sale: size cap (one stock above 4% of the account), trend exit (the trend half of a category closed a week below
               SMA(200)), regime exit (energy / materials: SMA(50) below SMA(200)). 'when' says this month or queued.
  CONSOLIDATE  under 1 500 kr: sell it or top it up
  REVIEW       a quality holding whose trend broke (SMA(50) below SMA(200)) and that is more than 15% under your cost
  HOLD         nothing to do
There is no RSI take-profit any more: in the tests, RSI above 75 was followed by MORE gains, so profits are taken by size and
category caps only.
"""
import json
import math
import os
import tempfile
import threading
import time
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date

import sectors
import strategy
import symbols

HERE = os.path.dirname(os.path.abspath(__file__))
HIST_FILE = os.path.join(HERE, 'history_cache.json')
HIST_TTL = 6 * 3600
CACHE_SECONDS = 60      # how long a finished answer is reused (live prices move the weights)
HEAD = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

MAX_W = strategy.MAX_W
DUST = strategy.DUST
MIN_ORDER = strategy.MIN_ORDER
BUYBACK_WAIT = 7        # days after the last sell before a buy-back is suggested (0-1 day flips lost money in your history)
BOUNCE_RSI = 45         # a planned sale is best placed on a day the RSI(14) is above this (sell into strength, not into panic)


def _lc(label):
    """'Broad index funds' -> 'broad index funds' inside a sentence; 'AI and semiconductor chain' keeps AI."""
    w = label.split(' ', 1)[0]
    return label if w.isupper() else label[:1].lower() + label[1:]
MAX_BUYBACK = 5
MAX_TRADES_MONTH = 10

PROFILES = {
    'conservative': {'label': 'Conservative', 'about': 'index funds 50%, AI and chips at most 10%; new money into a stock only in an uptrend with RSI(14) below 35'},
    'balanced':     {'label': 'Balanced', 'about': 'index funds 40%, AI and chips at most 15%; new money into a stock only in an uptrend with RSI(14) below 40'},
    'aggressive':   {'label': 'Aggressive', 'about': 'index funds 30%, AI and chips at most 22%; new money into a stock only in an uptrend with RSI(14) below 45'},
}
DEFAULT_PROFILE = 'balanced'

_LOCK = threading.Lock()
_fail = {}                            # symbol -> time of a failed fetch (not retried for an hour)
_hist = None                          # {symbol: {'at': ts, 'c': [closes], 'd': [epoch days]}}
_CACHE_MAX = 6                         # answers kept in memory, least recently used leaves first
_cache = OrderedDict()                 # (owner, payload.generated, live?, profile, settings) -> {'data', 'exp', 'payload'}; per-user data lives ONLY here


# ───────── price history (Yahoo v8 chart, adjusted close, 2 years) ─────────
def _load():
    global _hist
    with _LOCK:
        if _hist is None:
            try:
                with open(HIST_FILE, encoding='utf-8') as f:
                    _hist = json.load(f)
            except Exception:
                _hist = {}
        return _hist


def _save():
    try:
        with _LOCK:
            snap = dict(_hist)             # other users' threads may add symbols while we write
        fd, tmp = tempfile.mkstemp(dir=HERE, prefix='hist_', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(snap, f)
            os.replace(tmp, HIST_FILE)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
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
    todo = [s for s in syms if (s not in h or time.time() - h[s]['at'] > HIST_TTL) and time.time() - _fail.get(s, 0) > 3600]
    if todo:
        ex = ThreadPoolExecutor(max_workers=8)
        futs = {ex.submit(_fetch, s): s for s in todo}
        done, _ = wait(list(futs), timeout=budget)
        changed = False
        for f in done:
            try:
                with _LOCK:
                    h[futs[f]] = f.result()
                changed = True
            except Exception:
                _fail[futs[f]] = time.time()
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
    """RSI(14) as the average gain / average loss of the last 14 daily changes (Cutler's version; Nordnet and TradingView
    use Wilder's smoothing, which can read a few points different)."""
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


def _n(x):
    return f'{x:,.0f}'.replace(',', ' ')


_round500 = strategy._round500


def _metrics(f, wt):
    m = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in (f or {}).items() if k in ('trend', 'vs200', 'mom12_1', 'rsi', 'dd52', 'vol', 'ret21')}
    if wt:
        m.update(wk_up=wt['up'], wk_weeks=wt['weeks'], wk_date=wt['date'], wk_dist=wt['dist'], live_up=wt['live_up'], live_dist=wt['live_dist'],
                 regime_up=wt['regime_up'], wk_since=wt['since'], wk_flips12=wt['flips12'], wk_hist=wt['hist'])
    return m


def _wk_phrase(wt):
    if not wt:
        return 'no price history'
    side = 'above' if wt['up'] else 'below'
    weeks = f"{wt['weeks']} week{'s' if wt['weeks'] != 1 else ''}"
    return f"weekly close {side} SMA(200) ({wt['dist'] * 100:+.0f}%, {weeks} in a row, {wt['date']})"


# ───────── main ─────────
def advise(payload, live=None, profile=DEFAULT_PROFILE, settings=None):
    """live is unused (the payload is already live-valued by valuation.apply); kept for the old call signature."""
    profile = profile if profile in PROFILES else DEFAULT_PROFILE
    settings = dict(strategy.DEFAULT_SETTINGS, **(settings or {}))
    overrides = settings.get('overrides') or {}
    held = [a for a in payload['assets'] if a.get('held') and a.get('value') and a.get('isin')]
    if not held:
        return {'ok': False, 'error': 'no holdings'}
    closed = [a for a in payload['assets'] if not a.get('held') and a.get('isin') and a.get('sells')]
    syms, sym_of = [], {}
    for a in held + closed:
        r = symbols.of(a)                      # the listing on the holding's market (closed positions: none known)
        if r and r.get('symbol') and not r['symbol'].startswith('0P'):
            sym_of[a['isin']] = r['symbol']; syms.append(r['symbol'])
    hist = _histories(sorted(set(syms)))
    partial = any(s not in hist and time.time() - _fail.get(s, 0) > 3600 for s in syms)
    sec, _pending = sectors.batch([{'isin': a['isin'], 'name': a['name'], 'ccy': a.get('ccy'), 'market': a.get('market') or ''} for a in held + closed], budget=8)
    partial = partial or bool(_pending)
    last_sell = {}
    for t in payload.get('trades', []):
        if t.get('side') == 'SELL' and (t['isin'] not in last_sell or t['date'] >= last_sell[t['isin']]['date']):
            last_sell[t['isin']] = t

    ov = (payload.get('insights') or {}).get('overview') or {}
    cash = max(0.0, float(ov.get('cash_balance') or 0))
    tg = strategy.targets(profile, settings)
    rsi_add = strategy.RSI_ADD[profile]

    rows = []
    for a in held:
        h = hist.get(sym_of.get(a['isin']))
        s = sec.get(a['isin']) or {}
        rows.append({'a': a, 'val': a['value'], 'h': h, 'f': _features(h['c']) if h else None, 'wt': strategy.weekly_trend(h),
                     'cat': strategy.category_of(a, s, overrides), 'sector': s.get('sector') or s.get('category') or ('Funds' if a.get('type') == 'Fund' else 'Unclassified'),
                     'fundlike': a.get('type') in ('Fund', 'ETF/ETC') or (s.get('quote_type') or '').upper() in ('ETF', 'MUTUALFUND') or bool(s.get('category'))})
    hold_total = sum(r['val'] for r in rows)
    total = hold_total + cash
    for r in rows:
        r['w'] = r['val'] / total * 100
    cat_kr = {k: 0.0 for k in strategy.ORDER}
    for r in rows:
        cat_kr[r['cat']] += r['val']
    cat_kr['cash'] += cash
    cat_pct = {k: v / total * 100 for k, v in cat_kr.items()}
    status = {k: ('over' if cat_pct[k] > tg[k] + strategy.BAND else 'under' if cat_pct[k] < tg[k] - strategy.BAND else 'ok') for k in strategy.ORDER}
    under = {k for k in strategy.ORDER if cat_pct[k] < tg[k]}            # any gap counts for new money

    # 'hold half' of every half_trend category: theme ETFs plus the largest single names
    keep = set()
    for k in strategy.ORDER:
        if strategy.CATS[k][1] != 'half_trend':
            continue
        members = sorted((r for r in rows if r['cat'] == k), key=lambda r: -r['val'])
        keep |= {r['a']['isin'] for r in members if r['fundlike']}
        keep |= {r['a']['isin'] for r in [m for m in members if not m['fundlike']][:strategy.KEEP_LEADERS]}

    out, sells = {}, []
    for r in sorted(rows, key=lambda x: -x['val']):
        a, f, wt, w, k = r['a'], r['f'], r['wt'], r['w'], r['cat']
        rule = strategy.CATS[k][1]
        up = a.get('unrealized_pct')
        rsi = f['rsi'] if f else None
        res = {'name': a['name'], 'action': 'HOLD', 'amount': 0, 'weight': round(w, 2), 'sector': r['sector'], 'category': k,
               'category_label': strategy.CATS[k][0], 'rule': None, 'when': None, 'reasons': [], 'score': 0, 'symbol': sym_of.get(a['isin']),
               'metrics': _metrics(f, wt), 'target_weight': None, 'keep': a['isin'] in keep}
        why = res['reasons']

        def sell(amount, rule_id, text, when='now', score=60):
            amt = max(_round500(amount), MIN_ORDER) if amount >= MIN_ORDER / 2 else amount
            res.update(action='TRIM', amount=int(min(a['value'], amt)), rule=rule_id, when=when, score=score)
            why.append(text)

        # 1) size cap: one stock never above MAX_W % of the account (funds and the core are exempt; a tiny excess is not worth an order)
        if w > MAX_W and not r['fundlike'] and rule not in ('core', 'fixed') and (w - MAX_W) / 100 * total >= MIN_ORDER / 2:
            sell((w - MAX_W) / 100 * total, 'size_cap', f'{w:.1f}% of the account is above the {MAX_W:.0f}% cap for one stock; sell the part above it.', score=min(100, int(w / MAX_W * 50)))
        # 2) half_trend categories: the trend half follows the weekly SMA(200) rule, the hold half is kept
        elif rule == 'half_trend':
            if a['isin'] in keep:
                why.append(f'Hold half of {_lc(strategy.CATS[k][0])}: kept through the trend (capped at {MAX_W:.0f}%); {_wk_phrase(wt)}.')
                res['rule'] = 'hold_half'
                if wt and wt['up'] and k in under and rsi is not None and rsi < rsi_add:
                    res.update(action='ADD', rule='pullback', score=int(100 - rsi))
                    why.append(f'Category under its target and RSI(14) {rsi:.0f} is below {rsi_add}: new money may go here.')
            elif wt and not wt['up']:
                sells.append((r, 'trend_exit'))
                res.update(rule='trend_exit')
                why.append(f'Trend half: {_wk_phrase(wt)}. Rule: out until a weekly close is back above SMA(200).')
            elif wt and wt['up'] and k in under and rsi is not None and rsi < rsi_add:
                res.update(action='ADD', rule='pullback', score=int(100 - rsi))
                why.append(f'Trend half in: {_wk_phrase(wt)}; category under its target and RSI(14) {rsi:.0f} below {rsi_add}.')
            else:
                why.append(f'Trend half in: {_wk_phrase(wt)}.' if wt else 'No price history: kept as is.')
        # 3) regime categories (energy, materials): hold while SMA(50) > SMA(200)
        elif rule == 'regime':
            if wt and not wt['regime_up']:
                sell(a['value'], 'regime_exit', f'SMA(50) {wt["sma50"]:.4g} is below SMA(200) {wt["sma200_now"]:.4g}: the regime is down. Rule for {_lc(strategy.CATS[k][0])}: out until SMA(50) crosses back above.', score=65)
            elif wt and k in under and rsi is not None and rsi < rsi_add:
                res.update(action='ADD', rule='pullback', score=int(100 - rsi))
                why.append(f'Regime up (SMA(50) above SMA(200)), category under target, RSI(14) {rsi:.0f}.')
            else:
                why.append('Regime up: SMA(50) above SMA(200); hold.' if wt else 'No price history: kept as is.')
        # 4) quality categories: buy and hold; review a broken trend with a loss
        elif rule == 'quality':
            if wt and not wt['regime_up'] and up is not None and up < -15:
                res.update(action='REVIEW', rule='review', score=55)
                why.append(f'SMA(50) is below SMA(200) and the position is {up:.0f}% under your cost. Not a sell order: check that the business case still holds.')
            elif wt and wt['up'] and k in under and rsi is not None and rsi < rsi_add and w < MAX_W - 1:
                res.update(action='ADD', rule='pullback', score=int(100 - rsi))
                why.append(f'Uptrend ({_wk_phrase(wt)}), {_lc(strategy.CATS[k][0])} under its target and RSI(14) {rsi:.0f} below {rsi_add}: a pullback worth new money.')
            elif wt and wt['up'] and k in under and rsi is not None and rsi < rsi_add + 10:
                res.update(action='WATCH', rule='near_entry', score=int(max(1, 100 - (rsi - rsi_add) * 8)))
                why.append(f'Close to an entry: uptrend and category under target, RSI(14) {rsi:.0f} (new money below {rsi_add}).')
            else:
                why.append(f'Buy and hold ({_wk_phrase(wt)}).' if wt else 'Buy and hold; no price history.')
        # 5) core and fixed: never timed; new money comes from the deposit plan below
        else:
            why.append('Index fund: buy and hold, never timed. New money by the deposit plan.' if rule == 'core' else 'Defensive holding: fixed weight, topped up by the deposit plan.')
            res['rule'] = 'core' if rule == 'core' else 'fixed'

        # tiny positions: sell or top up
        if res['action'] == 'HOLD' and a['value'] < DUST and res.get('rule') not in ('trend_exit',) and rule not in ('core', 'fixed'):
            res.update(action='CONSOLIDATE', amount=int(a['value']), rule='consolidate', score=40)
            why.append(f'Only {a["value"]:.0f} kr: a round trip costs about 16 kr and it cannot move the result. Sell it or top it up to at least {MIN_ORDER} kr.')
        out[a['isin']] = res

    # ───── trend-half exits: immediate, or staged by the monthly reduction budget while the category is over its target ─────
    budget = {k: settings['reduce'] for k in strategy.ORDER if status[k] == 'over'}
    for r, rid in sorted(sells, key=lambda x: (x[0]['val'])):          # smallest first: they also clean up the list
        a, k = r['a'], r['cat']
        res = out[a['isin']]
        if k in budget:
            when = 'now' if budget[k] >= min(a['value'], MIN_ORDER) or a['value'] < DUST else 'later'
            if when == 'now':
                budget[k] -= a['value']
        else:
            when = 'now'
        res.update(action='TRIM', amount=int(a['value']), when=when, score=70 if when == 'now' else 30)
        res['reasons'].append('This month: sell on a day the RSI(14) is above 45 (into strength), at the latest within 4 weeks.' if when == 'now'
                              else f'Queued: the {settings["reduce"]:,} kr monthly reduction budget is used by smaller names first.'.replace(',', ' '))

    # ───── deposit plan: next month's deposit to the categories under target ─────
    buy_ideas = {}
    for isin, v in out.items():
        if v['action'] in ('ADD',) and v['category'] not in ('core', 'defensive'):
            buy_ideas.setdefault(v['category'], []).append(isin)
    dplan = strategy.deposit_plan(cat_kr, total, tg, settings['deposit'], buy_ideas)
    core_rows = [r for r in rows if r['cat'] == 'core']
    def_rows = [r for r in rows if r['cat'] == 'defensive']
    for item in dplan:
        k = item['cat']
        item['label'] = strategy.CATS[k][0]
        item['where'] = []
        wts = []                                      # each name's share of the category, for its % of the deposit
        if k == 'core' and core_rows:
            for r, share in strategy.core_split([{'name': x['a']['name'], 'value': x['val'], 'isin': x['a']['isin']} for x in core_rows]):
                amt = _round500(item['amount'] * share)
                if amt > 0:
                    item['where'].append({'isin': r['isin'], 'name': r['name'], 'amount': amt})
                    wts.append(share)
        elif k == 'defensive' and def_rows:
            r = max(def_rows, key=lambda x: x['val'])
            item['where'].append({'isin': r['a']['isin'], 'name': r['a']['name'], 'amount': item['amount']})
            wts.append(1)
        elif k in buy_ideas:
            ideas = sorted(buy_ideas[k], key=lambda i: -out[i]['score'])[:max(1, item['amount'] // MIN_ORDER)]
            each = _round500(item['amount'] / len(ideas))
            for i in ideas:
                item['where'].append({'isin': i, 'name': out[i]['name'], 'amount': each})
                wts.append(1)
        for wh, p in zip(item['where'], strategy.pct_split(wts, item.get('pct', 0))):
            wh['pct'] = p
        for wh in item['where']:
            if wh['isin'] in out:
                o = out[wh['isin']]
                if o['action'] in ('HOLD', 'ADD', 'CONSOLIDATE', 'WATCH'):
                    o.update(action='ADD', amount=wh['amount'], deposit_pct=wh['pct'], rule=o.get('rule') if o.get('rule') == 'pullback' else 'deposit_plan', score=max(o['score'], 50))
                    o['reasons'].append(f'Deposit plan: {_n(wh["amount"])} kr of next month\'s deposit goes here ({_lc(item["label"])} is under its target).')

    # ───── buy-backs: closed stocks whose category is under target, in an uptrend and pulled back ─────
    bb = []
    for a in closed:
        h = hist.get(sym_of.get(a['isin']))
        f, wt = (_features(h['c']), strategy.weekly_trend(h)) if h else (None, None)
        if not (f and wt and wt['up'] and f['rsi'] is not None and f['rsi'] < rsi_add):
            continue
        k = strategy.category_of(a, sec.get(a['isin']) or {}, overrides)
        if k not in under or strategy.CATS[k][1] in ('core', 'fixed'):
            continue
        ls = last_sell.get(a['isin'])
        days = (date.today() - date.fromisoformat(ls['date'])).days if ls else None
        if days is not None and days < BUYBACK_WAIT:
            continue
        bb.append((a, f, wt, k, ls))
    bb.sort(key=lambda x: x[1]['rsi'])
    for a, f, wt, k, ls in bb[:MAX_BUYBACK]:
        when = f'Sold {ls["date"]}. ' if ls else ''
        out[a['isin']] = {'name': a['name'], 'action': 'BUYBACK', 'closed': True, 'amount': max(MIN_ORDER, _round500(0.01 * total)), 'weight': 0.0,
                          'target_weight': None, 'sector': (sec.get(a['isin']) or {}).get('sector') or 'Unclassified', 'category': k,
                          'category_label': strategy.CATS[k][0], 'rule': 'buyback', 'when': 'now', 'score': int(100 - f['rsi']), 'symbol': sym_of.get(a['isin']),
                          'metrics': _metrics(f, wt), 'keep': False,
                          'reasons': [f'{when}Not held. {strategy.CATS[k][0]} is under its target, {_wk_phrase(wt)} and RSI(14) {f["rsi"]:.0f} is below {rsi_add}: a pullback in an uptrend.']}

    # ───── portfolio level ─────
    port = _portfolio_stats(rows, hold_total)
    stock_rows = [r for r in rows if strategy.CATS[r['cat']][1] not in ('core', 'fixed') and r['wt']]
    sv = sum(r['val'] for r in stock_rows) or 1
    up_pct = sum(r['val'] for r in stock_rows if r['wt']['up']) / sv * 100
    mom_pct = sum(r['val'] for r in stock_rows if r['wt']['up'] and r['f'] and (r['f']['mom12_1'] or 0) > 0) / sv * 100
    sq = (payload.get('insights') or {}).get('sell_quality') or {}
    distance = sum(abs(cat_pct[k] - tg[k]) for k in strategy.ORDER) / 2
    top = max((k for k in strategy.ORDER if k != 'core'), key=lambda k: cat_pct[k])
    fit = strategy.fit_scores({'core_pct': cat_pct['core'], 'core_target': tg['core'], 'up_pct': up_pct, 'positions': len(rows), 'tiny': sum(1 for r in rows if r['val'] < DUST),
                               'avg_hold': sq.get('avg_hold_days'), 'mom_pct': mom_pct, 'distance': distance, 'top_label': strategy.CATS[top][0],
                               'top_pct': cat_pct[top], 'eff_n': port['eff_n'] if port else None})

    # lifetime result per category, closed positions included (realised is already after fees)
    life = {k: {'life': 0.0, 'unreal': 0.0, 'realized': 0.0, 'fees': 0.0, 'value': 0.0, 'n': 0} for k in strategy.ORDER if k != 'cash'}
    for a in payload['assets']:
        if not a.get('isin'):
            continue
        k = strategy.category_of(a, sec.get(a['isin']) or {}, overrides)
        L = life[k]
        L['unreal'] += a.get('unrealized') or 0
        L['realized'] += a.get('realized') or 0
        L['fees'] += a.get('fees') or 0
        if a.get('held') and a.get('value'):
            L['value'] += a['value']; L['n'] += 1
    for L in life.values():
        L['life'] = L['unreal'] + L['realized']
        for x in L:
            L[x] = round(L[x]) if x != 'n' else L[x]

    # trading budget: the last 30 days
    cutoff = date.fromordinal(date.today().toordinal() - 30).isoformat()
    recent = [t for t in payload.get('trades', []) if t.get('date', '') >= cutoff]
    trading = {'trades_30d': len(recent), 'fees_30d': round(sum(t.get('fee') or 0 for t in recent)), 'max_trades': MAX_TRADES_MONTH,
               'fee_budget_year': round(total * 0.005)}

    cats = []
    for k in strategy.ORDER:
        members = [r for r in rows if r['cat'] == k]
        mv = sum(r['val'] for r in members if r['wt']) or 0
        cats.append({'key': k, 'label': strategy.CATS[k][0], 'rule': strategy.CATS[k][1], 'strategy': strategy.CATS[k][2],
                     'kr': round(cat_kr[k]), 'pct': round(cat_pct[k], 1), 'target': round(tg[k], 1), 'gap': round(cat_pct[k] - tg[k], 1),
                     'status': status[k], 'n': len(members),
                     'up_pct': round(sum(r['val'] for r in members if r['wt'] and r['wt']['up']) / mv * 100) if mv else None,
                     'n_up': sum(1 for r in members if r['wt'] and r['wt']['up']), 'n_trend': sum(1 for r in members if r['wt'])})
    sells_now = [dict(isin=i, name=v['name'], category=v['category'], amount=v['amount'], rule=v['rule'], rsi=v['metrics'].get('rsi'))
                 for i, v in out.items() if v['action'] == 'TRIM' and v.get('when') == 'now']
    queued = [i for i, v in out.items() if v['action'] == 'TRIM' and v.get('when') == 'later']
    tr = strategy.transition(cat_kr, tg, settings['deposit'], settings['reduce'])
    plan = {'profile': profile, 'settings': settings, 'targets': tg, 'categories': cats, 'deposit_plan': dplan,
            'sells_now': sorted(sells_now, key=lambda x: x['amount']), 'queued': len(queued), 'queued_kr': round(sum(out[i]['amount'] for i in queued)),
            'transition': tr, 'stress': {'now': strategy.stress(cat_pct), 'target': strategy.stress(tg), 'shocks': strategy.STRESS},
            'fit': fit, 'lifetime': life, 'trading': trading, 'total': round(total), 'cash': round(cash), 'rsi_add': rsi_add,
            'up_pct': round(up_pct), 'baskets': {k: sorted({v['symbol'] for v in out.values() if v.get('category') == k and v.get('symbol') and not v.get('closed')}) for k in strategy.ORDER if k != 'cash'}}

    # ───── cards (the verdict in a few lines) ─────
    cards = []

    def card(sev, title, num, text):
        cards.append({'sev': sev, 'title': title, 'num': num, 'text': text})

    worst = max(strategy.ORDER, key=lambda k: cat_pct[k] - tg[k])
    if status[worst] == 'over':
        months = tr['months_to_band']
        card('high', 'The biggest risk is one group', f'{strategy.CATS[worst][0]} {cat_pct[worst]:.0f}% (target {tg[worst]:.0f}%)',
             f'{strategy.CATS[worst][0]} is {cat_pct[worst] - tg[worst]:.0f} points over its target. No new money goes there; the trend half leaves by the weekly rule and '
             f'up to {_n(settings["reduce"])} kr a month is reduced. With {_n(settings["deposit"])} kr deposited a month it is back within {strategy.BAND:.0f} points of target '
             + (f'in about {months} months.' if months is not None else 'only after more than three years: raise the deposit or the reduction.'))
    core_gap = tg['core'] - cat_pct['core']
    if core_gap > strategy.BAND:
        card('high', 'The core is missing', f'index funds {cat_pct["core"]:.0f}% (target {tg["core"]:.0f}%)',
             'For broad index funds, buy and hold beat every timing rule over ten years' + (', and in your account they have made money while the stock groups lost' if life['core']['life'] > 0 > sum(v['life'] for k, v in life.items() if k != 'core') else '') +
             f'. {_n(core_gap / 100 * total)} kr is missing; the deposit plan sends most new money there.')
    if stock_rows:
        card('high' if up_pct < 40 else 'med' if up_pct < 60 else 'info', 'Trend health (weekly close vs SMA(200))', f'{up_pct:.0f}% of stock money in an uptrend',
             f'{sum(1 for r in stock_rows if not r["wt"]["up"])} of {len(stock_rows)} stocks closed last week below their 200-day simple average. For the trend half of a category that is a sell rule; '
             f'for quality stocks it is only a reason to stop adding.')
    if port:
        card('high' if port['max_dd'] < -.25 else 'med', 'Risk of the portfolio as it stands now', f'vol {port["vol"] * 100:.0f}% · max drop {port["max_dd"] * 100:.0f}%',
             f'With today\'s weights the holdings moved about {port["vol"] * 100:.0f}% a year and fell at most {port["max_dd"] * 100:.0f}% over the last year. The {port["n"]} largest act like '
             f'{port["eff_n"]:.1f} independent bets.')
    card('med' if trading['trades_30d'] > MAX_TRADES_MONTH else 'info', 'Trading budget', f'{trading["trades_30d"]} trades in 30 days (budget {MAX_TRADES_MONTH})',
         f'Fees in the last 30 days: {_n(trading["fees_30d"])} kr. Budget: at most {MAX_TRADES_MONTH} trades a month and {_n(trading["fee_budget_year"])} kr a year (0.5% of the account).')
    if cash < tg['cash'] / 100 * total - MIN_ORDER:
        card('med', 'Opportunity cash', f'{_n(cash)} kr (target {_n(tg["cash"] / 100 * total)} kr)',
             'The cash reserve is for opportunities (a pullback in an uptrend) and for the panic ladder. It is refilled from deposits first.')

    counts = {k: sum(1 for v in out.values() if v['action'] == k) for k in ('ADD', 'BUYBACK', 'WATCH', 'TRIM', 'CONSOLIDATE', 'REVIEW', 'HOLD')}
    theme = {}
    for r in rows:
        theme[r['sector']] = theme.get(r['sector'], 0) + r['w']
    # summary.total = holdings value (its meaning since the first version); plan.total is the account value incl. cash
    summary = {'positions': len(rows), 'total': round(hold_total), 'theme': {k: round(v, 1) for k, v in sorted(theme.items(), key=lambda x: -x[1])},
               'counts': counts, 'profile': profile, 'profile_about': PROFILES[profile]['about'], 'portfolio': port,
               'covered': sum(1 for r in rows if r['f']), 'asof': date.today().isoformat()}
    return {'ok': True, 'partial': partial, 'asof': time.strftime('%Y-%m-%dT%H:%M:%S'), 'assets': out, 'cards': cards, 'summary': summary, 'plan': plan}


def _portfolio_stats(rows, total):
    """Daily returns of today's weights over the last ~250 common days; vol, max drawdown, avg pairwise correlation."""
    use = [r for r in rows if r['h'] and len(r['h']['c']) >= 200]
    if len(use) < 5:
        return None
    use.sort(key=lambda r: -r['val'])
    maps = [dict(zip(r['h']['d'], r['h']['c'])) for r in use]
    days = sorted(set.intersection(*[set(m) for m in maps[:max(5, len(use) // 2)]]))[-251:]
    if len(days) < 120:
        return None
    wsum = sum(r['val'] for r in use)
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
        port.append(sum(use[j]['val'] / wsum * (rets[j][i] or 0) for j in range(len(use))))
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


def get(payload, live=None, profile=DEFAULT_PROFILE, owner=None, settings=None):
    """Advice for one user, cached per (owner, payload version, live flag, profile, settings) for CACHE_SECONDS.
    `owner` is the profile's id: two users never share an entry. Without an owner (CLI use) the entry is also bound to the
    payload object itself, so even a careless caller cannot be served another user's answer."""
    key = (owner, payload.get('generated'), bool(live), profile, json.dumps(settings or {}, sort_keys=True))
    now = time.time()
    with _LOCK:
        e = _cache.get(key)
        if e and now < e['exp'] and (owner is not None or e['payload'] is payload):
            _cache.move_to_end(key)
            return e['data']
    data = advise(payload, live, profile, settings)
    with _LOCK:
        # price history / sectors still loading in the background: retry soon instead of holding a partial answer
        _cache[key] = {'data': data, 'payload': payload if owner is None else None,
                       'exp': time.time() + (90 if data.get('partial') else CACHE_SECONDS)}
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return data


def forget(owner):
    """Drop everything cached for one user (called when the profile is deleted, its files are replaced or its plan settings change)."""
    with _LOCK:
        for k in [k for k in _cache if k[0] == owner]:
            del _cache[k]
