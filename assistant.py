"""
assistant.py - small rule-based, local assistant for the dashboard ("organic chat and search").

    answer(question, payload, advice) -> {answer, link, confidence, matched, suggestions}

* Pure, deterministic, stdlib only, no network, never logs the question.
* Every number comes from the caller's own `payload` (trade_analytics.get_payload) and `advice` (advisor.advise/get).
* Answers are at most two short lines (about 220 characters). Below 0.5 confidence it says it cannot answer
  and offers up to three nearby questions. It never invents a figure: a missing figure is reported as missing.
* Matching = normalised tokens (Swedish words mapped to English, light stemming, difflib typo tolerance) scored
  against keyword phrases per intent, plus fuzzy matching of asset names (and a few tickers).
"""
import difflib
import math
import re
from datetime import date, datetime

MAX_Q = 300
MAX_ANSWER = 220

# ───────────────────────── text normalisation ─────────────────────────
_FOLD = str.maketrans({'å': 'a', 'ä': 'a', 'ö': 'o', 'é': 'e', 'è': 'e', 'ü': 'u', 'ñ': 'n'})

# Swedish (folded, un-stemmed) -> English tokens. Applied to the question only.
SYN = {
    'vad': ['what'], 'betyder': ['mean'], 'betydelse': ['mean'], 'forklara': ['explain'], 'hur': ['how'], 'mycket': ['much'],
    'manga': ['many'], 'mina': ['my'], 'min': ['my'], 'mitt': ['my'], 'jag': ['i'], 'har': ['have'], 'ar': ['is'],
    'avgift': ['fee'], 'avgifter': ['fee'], 'kostnad': ['fee'], 'kostnader': ['fee'], 'kurtage': ['courtage'],
    'utdelning': ['dividend'], 'utdelningar': ['dividend'], 'innehav': ['holding'], 'innehaven': ['holding'],
    'vinst': ['profit'], 'forlust': ['loss'], 'insattning': ['deposit'], 'insattningar': ['deposit'],
    'varde': ['value'], 'kontovarde': ['account', 'value'], 'portfoljvarde': ['account', 'value'], 'portfolj': ['portfolio'],
    'antal': ['number'], 'storsta': ['biggest'], 'storst': ['biggest'], 'basta': ['best'], 'samsta': ['worst'],
    'kontanter': ['cash'], 'saldo': ['balance'], 'sektor': ['sector'], 'svangning': ['volatility'],
    'omsattning': ['turnover'], 'genomsnittskurs': ['gav'], 'orealiserad': ['unrealised'], 'orealiserade': ['unrealised'],
    'realiserad': ['realised'], 'realiserade': ['realised'], 'totalt': ['total'], 'summa': ['total'],
    'kop': ['buy'], 'kopt': ['bought'], 'kopa': ['buy'], 'kopte': ['bought'], 'salj': ['sell'], 'salt': ['sold'], 'sald': ['sold'],
    'senaste': ['last'], 'sista': ['last'], 'nar': ['when'], 'varfor': ['why'], 'borde': ['should'], 'skatt': ['tax'],
    'risk': ['risk'], 'nedgang': ['drawdown'], 'hjalp': ['help'], 'tack': ['thanks'], 'hej': ['hello'], 'hallo': ['hello'],
    'aktier': ['stock'], 'aktie': ['stock'], 'fonder': ['fund'], 'fond': ['fund'], 'handel': ['trade'], 'affarer': ['trade'],
    'whats': ['what', 'is'], 'whos': ['who', 'is'], 'hows': ['how', 'is'], 'im': ['i'], 'ive': ['i', 'have'],
    'costs': ['fee'], 'cost': ['fee'], 'paid': ['pay'], 'paying': ['pay'], 'pays': ['pay'], 'made': ['make'], 'earn': ['make'], 'earned': ['make'], 'money': ['money'], 'kronor': ['kr'], 'charges': ['fee'], 'commission': ['courtage'], 'worth': ['value'],
    'stocks': ['stock'], 'shares': ['stock'], 'names': ['stock'], 'payout': ['dividend'], 'payouts': ['dividend'],
    'losing': ['loss'], 'lose': ['loss'], 'lost': ['loss'], 'unrealized': ['unrealised'], 'realized': ['realised'], 'gain': ['profit'], 'gains': ['profit'], 'pnl': ['profit'],
}


def _stem(w):
    if len(w) <= 3:
        return w
    for suf in ('ingar', 'ing', 'ernas', 'arna', 'erna', 'ens', 'ers', 'ar', 'er', 'or', 'ed', 'es', 'en', 'et', 'na', 's'):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def _raw_tokens(text):
    t = (text or '').lower().translate(_FOLD).replace("'", '').replace('’', '')
    t = re.sub(r'[^a-z0-9%.&\-\s]', ' ', t)
    out = []
    for w in t.split():
        w = w.strip('.-&')
        if w:
            out.append(w)
    return out


def _question_tokens(text):
    """(stemmed tokens with Swedish mapped to English, stemmed raw tokens for asset names)"""
    raw = _raw_tokens(text)[:60]
    mapped = []
    for w in raw:
        mapped.extend(SYN.get(w, [w]))
    return [_stem(w) for w in mapped], [_stem(w) for w in raw], raw


def _sim(a, b, short=True):
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if min(la, lb) < 3 or abs(la - lb) > 2:
        return 0.0
    if a.startswith('un') != b.startswith('un'):          # realised / unrealised must never be confused
        return 0.0
    if min(la, lb) < 5:                      # short words (keywords only): one inserted / dropped letter, same first letter ("feez" ~ "fee")
        if short and la != lb and abs(la - lb) == 1 and a[0] == b[0] and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85:
            return 0.86
        return 0.0
    if (a.startswith(b) or b.startswith(a)) and min(la, lb) / max(la, lb) >= 0.7:
        return 0.92
    r = difflib.SequenceMatcher(None, a, b).ratio()
    return r if r >= (0.84 if min(la, lb) == 5 else 0.8) else 0.0


def _best(tok, qtoks, short=True):
    return max((_sim(tok, q, short) for q in qtoks), default=0.0)


# ───────────────────────── number formats (same as the dashboard) ─────────────────────────
def _n(x, d=0):
    s = f'{abs(x):,.{d}f}'.replace(',', ' ')
    return s.replace('.', ',') if d else s


def kr(x, sign=False, d=0):
    neg = x < 0 and round(abs(x), d) != 0
    return ('-' if neg else '+' if sign and x > 0 else '') + _n(x, d) + ' kr'


def pc(x, d=1, sign=False):
    neg = x < 0 and round(abs(x), d) != 0
    return ('-' if neg else '+' if sign and x > 0 else '') + _n(x, d) + '%'


def num(x, d=1):
    return ('-' if x < 0 else '') + _n(x, d)


class Missing(Exception):
    """A figure the answer needs is not in the data."""


def need(v, what):
    if v is None:
        raise Missing(what)
    return v


def _clip(s, n):
    s = ' '.join(str(s).split())
    if len(s) <= n:
        return s
    cut = s[:n - 1].rsplit(' ', 1)[0]
    return (cut or s[:n - 1]).rstrip(' ,;:') + '…'


def _fit(text):
    lines = [l for l in str(text).split('\n') if l.strip()][:2]
    if len(lines) == 2:
        lines = [_clip(lines[0], 112), _clip(lines[1], 106)]
    out = '\n'.join(lines)
    if len(out) > MAX_ANSWER:
        out = _clip(lines[0], 110) + ('\n' + _clip(lines[1], MAX_ANSWER - 111) if len(lines) > 1 else '')
    return out


def nm(name, n=24):
    return _clip(name, n)


def two(defn, you=None):
    return defn + ('\n' + you if you else '')


# ───────────────────────── context over the payload ─────────────────────────
class Ctx:
    def __init__(self, payload, advice):
        self.p = payload if isinstance(payload, dict) else {}
        self.I = self.p.get('insights') or {}
        self.ov = self.I.get('overview') or {}
        self.costs = self.I.get('costs') or {}
        self.assets = [a for a in (self.p.get('assets') or []) if isinstance(a, dict)]
        self.trades = [t for t in (self.p.get('trades') or []) if isinstance(t, dict)]
        self.adv = advice if isinstance(advice, dict) and advice.get('ok', True) and advice.get('assets') is not None else None
        self.asset = None
        self.sector = None

    # -- accessors that raise Missing instead of returning made-up numbers
    def ovv(self, key):
        return need(self.ov.get(key), key.replace('_', ' '))

    def section(self, name):
        v = self.I.get(name)
        if not v:
            raise Missing(name.replace('_', ' '))
        return v

    @property
    def held(self):
        return [a for a in self.assets if a.get('held') and a.get('value')]

    @property
    def holdings_value(self):
        v = self.ov.get('holdings_value')
        return v if v else (sum(a['value'] for a in self.held) or None)

    def reports(self):
        r = self.p.get('reports')
        if not isinstance(r, dict) or not r.get('covered'):
            raise Missing('the reports calendar (open the Portfolio page once so it can load from Yahoo)')
        return r

    def advice(self):
        if not self.adv:
            raise Missing('the Add / Trim review (it needs Yahoo price history)')
        return self.adv

    def adv_summary(self):
        return need(self.advice().get('summary'), 'the advice summary')

    def adv_port(self):
        return need(self.adv_summary().get('portfolio'), 'portfolio risk figures')

    def adv_asset(self, isin):
        return (self.advice().get('assets') or {}).get(isin)


LINKS = {'assets': '/analytics.html#assets', 'habits': '/analytics.html#habits', 'deposits': '/analytics.html#deposits',
         'dividends': '/analytics.html#dividends', 'advice': '/analytics.html#advice', 'portfolio': '/index.html',
         'account': '/account.html'}

# ───────────────────────── intent registry ─────────────────────────
INTENTS = []
_W = {1: 1.0, 2: 2.3, 3: 3.4, 4: 4.2}


def intent(iid, group, kind, kws, example, link=None, neg=(), asset=False):
    def deco(fn):
        INTENTS.append({
            'id': iid, 'group': group, 'kind': kind, 'fn': fn, 'example': example, 'link': LINKS.get(link, link),
            'asset': asset,
            'kws': [[_stem(t) for t in _raw_tokens(k)] for k in kws],
            'neg': [[_stem(t) for t in _raw_tokens(k)] for k in neg],
        })
        return fn
    return deco


def _phrase_score(toks, qtoks):
    sims = [_best(t, qtoks) for t in toks]
    if not sims or min(sims) <= 0:
        return 0.0
    return _W.get(len(toks), 4.2) * (sum(sims) / len(sims))


def _intent_score(it, qtoks):
    hits = sorted((_phrase_score(p, qtoks) for p in it['kws']), reverse=True)
    if not hits or hits[0] <= 0:
        return 0.0
    s = hits[0] + 0.25 * sum(h for h in hits[1:3] if h > 0)
    for n in it['neg']:
        if _phrase_score(n, qtoks) > 0:
            s -= 2.0
    return max(s, 0.0)


# ───────────────────────── asset matching ─────────────────────────
GENERIC = {'inc', 'corp', 'corporation', 'co', 'ltd', 'plc', 'ab', 'as', 'asa', 'sa', 'nv', 'se', 'ag', 'class', 'adr', 'sdb',
           'etf', 'etc', 'ucits', 'index', 'indeks', 'indeksi', 'group', 'holding', 'holdings', 'the', 'of', 'and', 'international',
           'global', 'fund', 'fond', 'ord', 'shs', 'acc', 'dist', 'usd', 'sek', 'eur', 'tax', 'technology', 'technologies',
           'systems', 'company', 'royalties', 'markets', 'a', 'b', 'c', 'ii', '1c', 'b1', 'screened', 'leaders', 'yield', 'high',
           'essential', 'metals', 'bond', 'year', 'treasury', 'dow', 'jones'}

TICKERS = {
    'nvda': 'nvidia', 'mu': 'micron', 'msft': 'microsoft', 'googl': 'alphabet', 'goog': 'alphabet', 'google': 'alphabet',
    'amzn': 'amazon', 'aapl': 'apple', 'amd': 'advanced', 'asml': 'asml', 'lite': 'lumentum', 'sndk': 'sandisk',
    'wdc': 'western', 'stx': 'seagate', 'amat': 'applied', 'lrcx': 'lam', 'avgo': 'broadcom', 'tsm': 'tsmc', 'ko': 'coca-cola',
    'cola': 'coca-cola', 'pg': 'procter', 'tmo': 'thermo', 'lly': 'lilly', 'novo': 'novo', 'nvo': 'novo', 'blk': 'blackrock',
    'mcd': 'mcdonalds', 'wmt': 'walmart', 'qcom': 'qualcomm', 'nxpi': 'nxp', 'stm': 'stmicroelectronics', 'abbv': 'abbvie',
    'mdb': 'mongodb', 'hynix': 'hynix', 'meta': 'meta', 'orcl': 'oracle', 'ibm': 'ibm', 'intc': 'intel', 'snps': 'synopsys',
}


GENERIC_STEMS = {_stem(w) for w in GENERIC} | GENERIC


STOP_Q = {_stem(w) for w in (
    'trade', 'trades', 'trading', 'fee', 'fees', 'stock', 'stocks', 'asset', 'assets', 'position', 'positions', 'holding', 'holdings', 'dividend',
    'dividends', 'profit', 'loss', 'value', 'price', 'cash', 'money', 'market', 'total', 'return', 'result', 'year', 'month', 'week', 'day', 'buy', 'sell',
    'hold', 'share', 'shares', 'order', 'orders', 'cost', 'costs', 'tax', 'much', 'many', 'last', 'best', 'worst', 'most', 'biggest', 'smallest', 'top',
    'made', 'make', 'sold', 'bought', 'doing', 'tell', 'about', 'should', 'good', 'idea', 'add', 'trim', 'review', 'rule', 'flagged', 'marked', 'time',
    'risk', 'score', 'grade', 'rate', 'rates', 'index', 'which', 'what', 'when', 'where', 'who', 'why', 'how', 'have', 'does', 'pay', 'paid', 'long')}


def _name_tokens(name):
    toks = [_stem(w) for w in _raw_tokens(name)]
    distinct = [t for t in toks if t not in GENERIC_STEMS and len(t) >= 3]
    return distinct or [t for t in toks if len(t) >= 2]


def _find_asset(ctx, raw_stems, raw):
    extra = [_stem(TICKERS[w]) for w in raw if w in TICKERS]
    q = [t for t in raw_stems if t not in STOP_Q] + extra
    best, best_key = None, None
    for a in ctx.assets:
        nt = _name_tokens(a.get('name') or '')
        if not nt:
            continue
        sims = [_best(t, q, False) for t in nt]
        got = [s for s in sims if s > 0]
        if not got:
            continue
        frac = len(got) / len(nt)
        if frac < 0.5:
            continue
        if len(nt) == 1 and len(nt[0]) < 4 and got[0] < 1:
            continue
        if len(got) == 1 and len(max((t for t, s in zip(nt, sims) if s > 0), key=len)) < 4 and frac < 1:
            continue
        key = (round(frac * sum(got) / len(got), 3), len(got), 1 if a.get('held') else 0, a.get('value') or 0)
        if best_key is None or key > best_key:
            best, best_key = a, key
    return best


# ───────────────────────── question cues ─────────────────────────
_GLOSS = {'mean', 'meaning', 'define', 'definition', 'explain', 'stand', 'describe'}
_MY = {'my', 'i', 'me', 'mine', 'have', 'did', 'do', 'am', 'paid', 'total', 'how', 'much', 'many', 'number', 'biggest', 'best',
       'worst', 'largest', 'top', 'which', 'when', 'last'}


def _cues(raw, mapped):
    ms = set(mapped)
    has_gloss = bool(ms & {_stem(w) for w in _GLOSS}) or ('what' in ms and ms & {'is', 'are', 'does', 'do'} and not (ms & {'my', 'i', 'me', 'mine'}))
    has_fact = bool(ms & {_stem(w) for w in _MY})
    return has_gloss, has_fact


# ═════════════════════════ GROUP A: glossary + your own number ═════════════════════════
def _sq(ctx):
    return ctx.section('split_orders')


@intent('split_orders', 'glossary', 'gloss', ['split orders', 'split order', 'splitorders', 'splitorder', 'splitting orders', 'split', 'partial fills', 'same day same stock orders'],
        'What does split orders mean?', 'habits')
def i_split(c):
    s = _sq(c)
    return two('Several orders for the same stock, same side, same day, each paying its own courtage.',
               f"You: {_n(s['extra_orders'])} extra orders in {_n(s['groups'])} cases, about {kr(s['avoidable_fees'])} avoidable.")


@intent('courtage', 'glossary', 'gloss', ['courtage', 'commission', 'brokerage', 'broker fee', 'order fee'], 'What is courtage?', 'habits')
def i_courtage(c):
    k = c.costs
    return two("Courtage is the broker's commission charged on each order.",
               f"You paid {kr(need(k.get('courtage'), 'courtage'))} on {_n(need(k.get('paid_trades'), 'paid trades'))} paid trades (avg {num(k.get('avg_fee_per_paid_trade') or 0, 1)} kr).")


@intent('fx_fee', 'glossary', 'gloss', ['fx fee', 'currency fee', 'exchange fee', 'currency conversion', 'valutaavgift', 'fx'], 'What is the FX fee?', 'habits')
def i_fx(c):
    k = c.costs
    return two('The FX fee is the currency-conversion cost on trades in a foreign currency.',
               f"Yours: {kr(need(k.get('fx_fees'), 'FX fees'))} so far, versus {kr(need(k.get('courtage'), 'courtage'))} courtage.")


@intent('gav', 'glossary', 'gloss', ['gav', 'average price', 'average purchase price', 'average cost', 'snittkurs', 'cost basis', 'average buy price'],
        'What is GAV?', 'portfolio')
def i_gav(c):
    h = sorted(c.held, key=lambda a: -a['value'])
    you = None
    if h and h[0].get('gav') is not None and h[0].get('price') is not None:
        a = h[0]
        you = f"E.g. {a['name']}: GAV {num(a['gav'], 2)} {a.get('ccy', '')}, price {num(a['price'], 2)} {a.get('ccy', '')}."
    return two('GAV is your average purchase price per share, including fees.', you)


@intent('real_unreal', 'glossary', 'gloss', ['realised vs unrealised', 'difference realised unrealised', 'realised', 'unrealised', 'open profit', 'locked in'],
        'Realised vs unrealised?', 'assets')
def i_real(c):
    return two('Realised = locked in by selling; unrealised = open gain or loss on what you still hold.',
               f"You: realised {kr(c.ovv('realized'), True)}, unrealised {kr(c.ovv('unrealized'), True)}.")


@intent('turnover', 'glossary', 'gloss', ['turnover', 'turn over', 'traded volume', 'how much traded'], 'What is turnover?', 'habits')
def i_turn(c):
    it = _score_item(c, 'turnover_ratio')
    t = c.ovv('turnover')
    return two('Turnover is the total value bought plus sold; a high figure means high fees.',
               f"You traded {kr(t)}" + (f", about {num(it['value'], 1)}x your money a year." if it and it.get('value') is not None else '.'))


def _score_item(c, key):
    for i in (c.I.get('scorecard') or {}).get('items') or []:
        if i.get('key') == key:
            return i
    return None


@intent('profit_factor', 'glossary', 'gloss', ['profit factor', 'win loss ratio', 'payoff ratio', 'wins vs losses'], 'What is profit factor?', 'habits')
def i_pf(c):
    s = c.section('sell_quality')
    return two('Profit factor = money won on winning sells divided by money lost on losing sells; above 1 is good.',
               f"Yours is {num(need(s.get('profit_factor'), 'profit factor'), 2)} (wins {kr(s['gross_wins'])}, losses {kr(s['gross_losses'])}).")


@intent('win_rate', 'glossary', 'fact', ['win rate', 'hit rate', 'winning trades', 'how many sells profit', 'percent winners'], 'What is my win rate?', 'habits')
def i_win(c):
    s = c.section('sell_quality')
    return two(f"{pc(need(s.get('win_rate'), 'win rate'))} of your {_n(s['sells'])} sells made a profit.",
               f"Average win {kr(s['avg_win'])}, average loss {kr(s['avg_loss'])}.")


@intent('habit_score', 'glossary', 'gloss', ['habit score', 'trading score', 'my grade', 'score', 'grade', 'trading habits'], 'What is my habit score?', 'habits')
def i_habit(c):
    sc = c.section('scorecard')
    items = [i for i in sc.get('items') or [] if i.get('score') is not None]
    worst = sorted(items, key=lambda i: -(100 - i['score']) * i.get('weight', 1))[:2]
    return two('A 0-100 grade of your trading habits (fees, order size, holding time...) against rule-of-thumb targets.',
               f"You: {sc.get('overall')}/100 ({sc.get('grade')}); weakest: " + ', '.join(i['label'] for i in worst) + '.')


@intent('same_day', 'glossary', 'gloss', ['same day trades', 'same day', 'day trading', 'day trade', 'buy and sell same day', 'intraday'],
        'What are same-day trades?', 'habits')
def i_sameday(c):
    s = c.section('same_day')
    return two('Buying and selling the same asset on the same day, which mostly just costs fees.',
               f"You: {_n(s['count'])} cases, fees {kr(s['fees'])}, realised {kr(s['realized'], True)}.")


@intent('rebuys', 'glossary', 'gloss', ['rebuy', 'rebuys', 'buy back quickly', 'sold and bought again', 'bought back', 're buy'], 'What are rebuys?', 'habits')
def i_rebuy(c):
    s = c.section('rebuys')
    return two('Selling a stock and buying it back within 14 days.',
               f"You: {_n(s['count'])} times, net effect {kr(s['net_effect'], True)} before {kr(s['fees'])} fees; {_n(s['worse'])} were worse.")


@intent('hold_time', 'glossary', 'gloss', ['holding time', 'hold time', 'holding period', 'how long hold', 'days held', 'median hold'], 'How long do I hold?', 'habits')
def i_hold(c):
    s = c.section('sell_quality')
    return two('Holding time = days between buying and selling (first in, first out).',
               f"Yours: median {num(need(s.get('median_hold_days'), 'median hold'), 0)} days, average {num(s['avg_hold_days'], 0)}; {_n(s['sold_within_7d'])} of {_n(s['sells'])} sells within a week.")


@intent('drawdown', 'glossary', 'gloss', ['drawdown', 'max drop', 'peak to trough', 'worst fall', 'biggest fall'], 'What is drawdown?', 'advice')
def i_dd(c):
    p = c.adv_port()
    return two('Drawdown is the fall from a peak to the next low point.',
               f"Last year with today's weights: worst {pc(p['max_dd'] * 100, 0)}.")


@intent('volatility', 'glossary', 'gloss', ['volatility', 'volatile', 'how risky', 'standard deviation', 'swings'], 'What is volatility?', 'advice')
def i_vol(c):
    p = c.adv_port()
    return two('Volatility is how much the value typically swings in a year.',
               f"Your portfolio: about {pc(p['vol'] * 100, 0)} a year (daily moves of the last 12 months).")


@intent('correlation', 'glossary', 'gloss', ['correlation', 'correlated', 'move together', 'diversification'], 'What is correlation?', 'advice')
def i_corr(c):
    p = c.adv_port()
    return two('Correlation shows how alike two holdings move: 1 = identical, 0 = unrelated.',
               f"Average among your top {p['n']}: {num(p['corr'], 2)}.")


@intent('eff_bets', 'glossary', 'gloss', ['effective bets', 'independent bets', 'how diversified', 'real diversification', 'effective number'],
        'What are effective bets?', 'advice')
def i_eff(c):
    s = c.adv_summary(); p = c.adv_port()
    return two('Effective bets = how many independent positions your holdings really behave like.',
               f"You hold {_n(s['positions'])} positions, which act like about {num(p['eff_n'], 0)}.")


@intent('sma200', 'glossary', 'gloss', ['200 day average', '200 day', 'sma200', 'moving average', 'uptrend', 'downtrend', 'trend'], 'What is the 200-day average?', 'advice')
def i_sma(c):
    a = _adv_held(c)
    dn = sum(1 for v in a if (v.get('metrics') or {}).get('trend') == 'down')
    up = sum(1 for v in a if (v.get('metrics') or {}).get('trend') == 'up')
    return two('The 200-day average is the long-term trend line; price above it (and the 50-day above it) = uptrend.',
               f"Your holdings: {up} in uptrend, {dn} in downtrend.")


@intent('momentum', 'glossary', 'gloss', ['12 1 momentum', 'momentum', '12 month momentum', 'twelve month momentum'], 'What is 12-1 momentum?', 'advice')
def i_mom(c):
    a = [(v['name'], v['metrics']['mom12_1']) for v in _adv_held(c)
         if v.get('name') and (v.get('metrics') or {}).get('mom12_1') is not None]
    top = max(a, key=lambda x: x[1]) if a else None
    return two('Return over the last 12 months, skipping the latest month; positive = the stock has been rising.',
               f"Highest in your portfolio: {top[0]} {pc(top[1] * 100, 0, True)}." if top else None)


@intent('rsi', 'glossary', 'gloss', ['rsi', 'relative strength index', 'overbought', 'oversold'], 'What is RSI?', 'advice')
def i_rsi(c):
    a = [(v.get('metrics') or {}).get('rsi') for v in _adv_held(c)]
    a = [x for x in a if x is not None]
    return two('RSI (14 days) measures the speed of recent moves, 0-100. Add ideas start below 35 (in an uptrend), profit-taking above 75 (Balanced).',
               f"Yours: {sum(1 for x in a if x > 75)} above 75, {sum(1 for x in a if x < 35)} below 35, {sum(1 for x in a if x < 40)} below 40." if a else None)


@intent('watch_idea', 'glossary', 'gloss', ['watch idea', 'watch', 'what does watch mean', 'close to a buy signal', 'watch list', 'watchlist idea'], 'What does WATCH mean?', 'advice')
def i_watch(c):
    n = sum(1 for v in c.advice().get('assets', {}).values() if v.get('action') == 'WATCH') if c.adv else None
    return two('WATCH means close to a buy signal: the stock is in an uptrend and pulled back, and its RSI(14) is within 10 points above the buy level (Balanced 35). No order yet.',
               f'Right now {n} on watch. TRIM WATCH is the mirror: a holding in profit whose RSI is close to the take-profit level.' if n is not None else None)


@intent('pullback', 'glossary', 'gloss', ['pullback', 'pulled back', 'below 52 week high', '52 week high', 'dip', 'from the high'], 'What is a pullback?', 'advice')
def i_pull(c):
    a = [(v.get('metrics') or {}).get('dd52') for v in _adv_held(c) if (v.get('metrics') or {}).get('dd52') is not None]
    n = sum(1 for x in a if -0.25 <= x <= -0.05)
    return two('A pullback is the distance below the 52-week high; the ADD rule wants a dip inside a rising trend.',
               f"{n} of your holdings are 5-25% below their high." if a else None)


def _adv_held(c):
    return [v for v in (c.advice().get('assets') or {}).values() if not v.get('closed')]


def _count_adv(c, action):
    a = c.advice().get('assets') or {}
    xs = [v for v in a.values() if v.get('action') == action]
    return xs, sum(v.get('amount') or 0 for v in xs)


@intent('add_rule', 'glossary', 'gloss', ['add rule', 'what is add', 'add idea', 'add suggestion', 'add means'], 'What does ADD mean?', 'advice', asset=False)
def i_add(c):
    xs, tot = _count_adv(c, 'ADD')
    return two('ADD: a small position in an uptrend that pulled back; the rule fills it to about 2% of the portfolio.',
               f"Now: {len(xs)} ADD ideas, {kr(tot)} in total. Rule-based idea, not a forecast.")


@intent('trim_rule', 'glossary', 'gloss', ['trim rule', 'what is trim', 'trim idea', 'trim means', 'trim suggestion'], 'What does TRIM mean?', 'advice')
def i_trim(c):
    xs, tot = _count_adv(c, 'TRIM')
    return two('TRIM: sell part of a position above 4% of the portfolio, or a big holding in a sector above 40%.',
               f"Now: {len(xs)} TRIM ideas, {kr(tot)} in total. Risk rule, not a forecast.")


@intent('buyback_rule', 'glossary', 'gloss', ['buy back', 'buyback', 'buy back rule', 'buy back idea', 'what is buy back'], 'What is BUY BACK?', 'advice', neg=['rebuy'])
def i_bb(c):
    xs, tot = _count_adv(c, 'BUYBACK')
    return two('BUY BACK: a position you sold that is back in an uptrend after a pullback (one order, about 1.5%).',
               f"Now: {len(xs)} buy-back ideas, {kr(tot)}. Rule-based, not a forecast.")


@intent('consolidate_rule', 'glossary', 'gloss', ['consolidate', 'consolidation', 'what is consolidate', 'dust', 'dust positions', 'tiny positions', 'small positions under'],
        'What does CONSOLIDATE mean?', 'advice')
def i_cons(c):
    xs, tot = _count_adv(c, 'CONSOLIDATE')
    return two('CONSOLIDATE: positions under 1 500 kr; courtage eats any gain, so sell or top them up.',
               f"You have {len(xs)} such positions worth {kr(tot)} together.")


@intent('review_rule', 'glossary', 'gloss', ['review', 'what is review', 'review flag', 'review means'], 'What does REVIEW mean?', 'advice')
def i_rev(c):
    xs, _ = _count_adv(c, 'REVIEW')
    return two('REVIEW: in a downtrend with negative momentum and over 15% under your cost; re-check why you own it.',
               f"Now: {len(xs)} holdings flagged." + (' ' + ', '.join(nm(v['name']) for v in xs[:2]) if xs else ''))


@intent('profiles', 'glossary', 'gloss', ['conservative', 'balanced', 'aggressive', 'entry profile', 'profile', 'entry rules', 'strictness'],
        'What are the Conservative / Balanced / Aggressive profiles?', 'advice')
def i_prof(c):
    s = c.adv_summary()
    return two('Profiles set how strict ADD and BUY BACK are: Conservative waits for a bounce, Aggressive buys any dip.',
               f"Active: {s.get('profile')}: {s.get('profile_about')}.")


@intent('twr', 'glossary', 'gloss', ['time weighted return', 'twr', 'return excluding deposits', 'return without deposits', 'performance without deposits'],
        'What is time-weighted return?', 'deposits')
def i_twr(c):
    ser = (c.I.get('deposit_behavior') or {}).get('series') or []
    idx = ser[-1].get('index') if ser else None
    return two('Time-weighted return strips out deposits, so adding money never looks like a gain.',
               f"Yours since {ser[0]['date']}: {pc(idx - 100, 1, True)}." if idx is not None else None)


@intent('net_deposits', 'glossary', 'fact', ['net deposits', 'deposited', 'money i put in', 'total deposits', 'how much deposited', 'insattningar'], 'How much have I deposited?', 'deposits')
def i_dep(c):
    return two(f"You deposited {kr(c.ovv('net_deposits'))} net ({_n(c.ovv('deposit_count'))} deposits, {kr(c.ovv('withdrawals'))} withdrawn).",
               'Net deposits = deposits minus withdrawals; the base for your all-time result.')


@intent('all_time', 'glossary', 'fact', ['all time result', 'all time', 'total result', 'overall result', 'how am i doing', 'am i up or down', 'total profit', 'total return', 'in profit', 'my profit', 'profit', 'losing money'],
        'What is my all-time result?', 'assets', neg=['realised', 'unrealised', 'biggest', 'worst', 'most', 'dividend', 'fee'])
def i_all(c):
    return two(f"All-time result: {kr(c.ovv('all_time_pnl'), True)} ({pc(c.ovv('all_time_pnl_pct'), 1, True)}) on {kr(c.ovv('net_deposits'))} deposited.",
               'It is account value minus net deposits, after fees and including dividends.')


@intent('div_gross_net', 'glossary', 'gloss', ['gross net dividend', 'dividend gross', 'dividend net', 'dividend after tax', 'withholding tax', 'dividend tax', 'tax on dividends', 'kallskatt'],
        'What is dividend withholding tax?', 'dividends')
def i_divtax(c):
    s = c.I.get('dividends', {}).get('summary') or {}
    g, t = need(s.get('gross'), 'dividends'), s['tax']
    return two('Dividends are paid gross; foreign shares have tax withheld at source, so net = gross minus tax.',
               f"You: gross {kr(g)}, tax {kr(t)} ({pc(s['tax_pct'])}), net {kr(s['net'])}.")


@intent('sector_cap', 'glossary', 'gloss', ['sector cap', 'theme cap', 'sector limit', 'concentration', 'concentrated', 'too much technology', 'theme concentration'],
        'What is the sector cap?', 'advice')
def i_cap(c):
    th = c.adv_summary().get('theme') or {}
    top = next(((k, v) for k, v in th.items() if k not in ('Unclassified', 'Funds')), None)
    return two('The sector cap is 40%: above it, new ADDs there are blocked and the largest holdings give back a fifth.',
               f"Your top sector, {top[0]}, is {pc(top[1], 0)}." if top else None)


@intent('fragmentation', 'glossary', 'gloss', ['fragmentation', 'too many positions', 'too many stocks', 'how many positions should', 'over diversified', 'number of holdings'],
        'Do I have too many positions?', 'advice')
def i_frag(c):
    s = c.adv_summary()
    small = len([a for a in c.held if a['value'] / (c.holdings_value or 1) < 0.01])
    return two(f"{_n(s['positions'])} positions is a lot; 20-30 of at least 1.5-2% each is easier to follow and cheaper.",
               f"{_n(small)} of yours are below 1% of the portfolio.")


@intent('fee_drag', 'glossary', 'gloss', ['fee drag', 'annual cost', 'cost drag', 'yearly fees', 'fees per year'], 'What is fee drag?', 'habits')
def i_drag(c):
    it = need(_score_item(c, 'fee_drag'), 'the fee drag')
    return two('Fee drag = fees per year as a share of the money you have deposited; low-cost investing stays near 1%.',
               f"Yours: {pc(it['value'])} a year (target {num(it['good'], 1)}%).")


@intent('min_order', 'glossary', 'gloss', ['minimum order', 'min order size', 'order size', 'order size fees', 'avoid high fees', 'what order size', 'small orders', 'how big should orders', 'smallest order'],
        'What order size avoids high fees?', 'habits')
def i_minorder(c):
    sc = c.section('scorecard'); st = c.I.get('small_trades') or {}
    return two(f"An order of about {kr(need(sc.get('min_order_for_0_3pct'), 'minimum order'))} keeps courtage near 0,3%.",
               f"{_n(st.get('count', 0))} of your trades had fees of 1% or more ({kr(st.get('fees', 0))}).")


@intent('small_trades', 'glossary', 'fact', ['small trades', 'high fee trades', 'trades high fees', 'how many trades high fee', 'expensive trades', 'fee over 1%'], 'How many trades had high fees?', 'habits')
def i_small(c):
    st = c.section('small_trades')
    return two('Small trades are orders where the fee was 1% or more of the trade value.',
               f"You: {_n(st['count'])} such trades, {kr(st['fees'])} in fees.")


@intent('deposit_timing', 'glossary', 'fact', ['deposit timing', 'when do i deposit', 'deposit after drop', 'deposit after crash', 'deposits after falls', 'do i buy the dip'],
        'Do I deposit after market drops?', 'deposits')
def i_dtime(c):
    g = ((c.I.get('deposit_behavior') or {}).get('summary') or {}).get('groups', {}).get('down')
    g = need(g, 'deposit timing')
    return two(f"{pc(g['amount_share'])} of your deposit money arrived after a 5-day portfolio drop; random timing would give {pc(g['baseline_share'])}.",
               'Deposits after drops may mean you add when prices are lower.')


@intent('trades_per_day', 'glossary', 'fact', ['trades per day', 'busiest day', 'most trades one day', 'trading frequency', 'how often do i trade', 'active days'],
        'How often do I trade?', 'habits')
def i_rhythm(c):
    r = c.section('rhythm')
    b = (r.get('busiest_days') or [{}])[0]
    return two(f"On active days you average {num(r['trades_per_active_day'], 0)} trades.",
               f"Busiest day: {b.get('date')} with {b.get('trades')} trades.")


@intent('weekday', 'glossary', 'fact', ['weekday', 'which weekday', 'weekday trade', 'which day do i trade', 'trade most on', 'best day of week', 'day of the week'], 'Which weekday do I trade most?', 'habits')
def i_weekday(c):
    w = c.section('weekday')
    t = max(w, key=lambda x: x['trades'])
    return two(f"You trade most on {t['day']} ({_n(t['trades'])} trades, {kr(t['fees'])} fees).",
               'Counts all your trades by weekday.')


@intent('benchmark', 'glossary', 'gloss', ['benchmark', 'compare index', 'vs s&p', 'vs index', 'beat the market', 'beat index', 'beating the index', 'beating the market', 'beat market', 'versus omx', 'index comparison', 'omxs30', 'nasdaq', 's&p 500', 'better than the index'],
        'Am I beating the index?', 'habits')
def i_bench(c):
    return two('The Trading habits tab compares your account with putting every deposit into OMXS30, S&P 500 or Nasdaq 100.',
               'That needs live index prices, so I cannot give the figure here.')


@intent('live_values', 'help', 'help', ['live prices', 'live', 'values live', 'why different value', 'is it live', 'snapshot', 'real time', 'refresh', 'price update', 'how fresh'],
        'Are the values live?', 'portfolio')
def i_live(c):
    return 'Totals use live Yahoo prices where a symbol is known; the holdings export is only a snapshot from the day you made it.'


@intent('privacy_toggle', 'help', 'help', ['hide numbers', 'privacy', 'hide values', 'eye button', 'blur', 'hide balance'], 'How do I hide my numbers?', 'portfolio')
def i_priv(c):
    return 'Click the eye button in the header: money values blur on both pages and the choice is remembered.'


@intent('upload_help', 'help', 'help', ['upload', 'upload files', 'upload csv', 'new data', 'new export', 'update data', 'replace files', 'import csv', 'how do i update'], 'How do I upload new data?', 'account')
def i_upload(c):
    return 'Open your user menu, choose Upload / replace files, and pick the holdings CSV and the transactions CSV from Nordnet.'


@intent('help', 'help', 'help', ['help', 'what can you do', 'what can i ask', 'commands', 'examples', 'how do you work'], 'What can I ask?', None)
def i_help(c):
    return two('Ask about your fees, positions, dividends, habits or any term (split orders, GAV, RSI, TRIM...).',
               'Name a stock for its value, fees, last buy or why it is flagged.')


@intent('greeting', 'help', 'help', ['hello', 'hi', 'hey', 'good morning', 'good evening'], 'Hello', None)
def i_hi(c):
    return 'Hi! Ask me about your fees, positions, dividends or any term you see on the page.'


@intent('thanks', 'help', 'help', ['thanks', 'thank you', 'cheers', 'great', 'perfect'], 'Thanks', None)
def i_thanks(c):
    return "You're welcome! Ask me anything else about your portfolio."


@intent('account_help', 'help', 'help', ['change password', 'password', 'log out', 'logout', 'sign out', 'invite', 'delete account', 'delete my data', 'account settings'],
        'How do I change my password?', 'account')
def i_account(c):
    return 'Open your user menu (top right): Account lets you change the password, upload files, delete your profile, or log out.'


@intent('forecast', 'help', 'help', ['predict', 'forecast', 'tomorrow', 'go up', 'go down', 'will rise', 'will fall', 'next week', 'next month', 'price target', 'crash', 'future price', 'will it', 'guarantee'],
        'Will Micron go up tomorrow?', 'advice')
def i_forecast(c):
    return two("I can't predict prices; nobody reliably can.", 'The Add / Trim ideas are rule-based on size, sector and trend, not forecasts.')


SECTOR_ALIASES = {'tech': 'Technology', 'technology': 'Technology', 'semiconductor': 'Technology', 'semis': 'Technology', 'chips': 'Technology',
                  'industrial': 'Industrials', 'industrials': 'Industrials', 'health': 'Healthcare', 'healthcare': 'Healthcare',
                  'pharma': 'Healthcare', 'financial': 'Financial Services', 'financials': 'Financial Services', 'finance': 'Financial Services',
                  'banks': 'Financial Services', 'communication': 'Communication Services', 'energy': 'Energy', 'utilities': 'Utilities',
                  'materials': 'Basic Materials', 'funds': 'Funds', 'unclassified': 'Unclassified'}


def _find_sector(ctx, raw):
    th = (ctx.adv.get('summary') or {}).get('theme') if ctx.adv else None
    if not th:
        return None
    for w in raw:
        name = SECTOR_ALIASES.get(w) or next((k for k in th if k.lower() == w), None)
        if name in th:
            return name
    return None


@intent('sector_weight', 'portfolio', 'fact', ['sector', 'exposure', 'weight', 'percent', 'share', 'allocation', 'how much', 'portfolio'],
        'How much technology do I have?', 'advice')
def f_sectorw(c):
    th = c.adv_summary().get('theme') or {}
    sec = need(c.sector, 'a matching sector')
    names = sorted(((v.get('weight') or 0, v['name']) for v in (c.advice().get('assets') or {}).values() if v.get('sector') == sec and not v.get('closed')), reverse=True)[:2]
    return two(f"{sec} is {pc(th[sec], 0)} of holdings" + (' (above the 40% sector cap).' if th[sec] > 40 and sec not in ('Funds', 'Unclassified') else '.'),
               ('Biggest: ' + ', '.join(f'{nm(n)} {pc(w)}' for w, n in names) + '.') if names else None)


# ═════════════════════════ GROUP B: portfolio facts ═════════════════════════
@intent('account_value', 'portfolio', 'fact', ['account value', 'portfolio value', 'total value', 'how much is my portfolio worth', 'how much money do i have', 'net worth', 'total portfolio', 'total worth', 'portfolio worth'],
        'What is my account value?', 'portfolio')
def f_value(c):
    return two(f"Account value (export snapshot): {kr(c.ovv('total_value'))}.",
               f"Holdings {kr(c.ovv('holdings_value'))} plus cash {kr(c.ovv('cash_balance'))}; the Portfolio page shows it live.")


@intent('holdings_value', 'portfolio', 'fact', ['holdings value', 'value of holdings', 'invested', 'invested amount', 'stock value'], 'What are my holdings worth?', 'portfolio')
def f_hv(c):
    return f"Holdings are worth {kr(c.ovv('holdings_value'))} across {_n(c.ovv('held_assets'))} positions (export snapshot)."


@intent('cash', 'portfolio', 'fact', ['cash balance', 'cash', 'how much cash', 'cash do i have', 'free cash', 'idle cash', 'available cash', 'buying power', 'balance'], 'How much cash do I have?', 'portfolio')
def f_cash(c):
    v = c.ovv('total_value')
    cash = c.ovv('cash_balance')
    return f"Cash balance: {kr(cash)} ({pc(cash / v * 100 if v else 0)} of the account)."


@intent('deposits_total', 'portfolio', 'fact', ['total deposited', 'deposits total', 'number of deposits', 'how many deposits', 'average deposit', 'withdrawals'],
        'How many deposits have I made?', 'deposits')
def f_deps(c):
    d = (c.I.get('deposit_behavior') or {}).get('summary') or {}
    return two(f"{_n(c.ovv('deposit_count'))} deposits totalling {kr(c.ovv('deposits'))}; withdrawn {kr(c.ovv('withdrawals'))}.",
               f"Average deposit {kr(d['avg_deposit'])}, typically every {d['median_gap_days']} days." if d.get('avg_deposit') else None)


@intent('all_time_pct', 'portfolio', 'fact', ['all time percent', 'return percent', 'total return percent', 'percent return', 'how many percent', 'return since start'],
        'What is my total return in %?', 'assets')
def f_pct(c):
    return f"Since the start: {pc(c.ovv('all_time_pnl_pct'), 1, True)} ({kr(c.ovv('all_time_pnl'), True)}) on net deposits of {kr(c.ovv('net_deposits'))}."


@intent('fees_total', 'portfolio', 'fact', ['total fees', 'fees paid', 'how much fees', 'broker costs', 'fees so far', 'what have i paid in fees', 'all fees', 'how much pay', 'what did i pay', 'fee', 'fees'],
        'What are my total fees?', 'habits')
def f_fees(c):
    k = c.costs
    return two(f"Broker costs so far: {kr(need(k.get('broker_total'), 'broker costs'))}, {pc(k['pct_of_net_deposits'])} of your deposits.",
               f"Courtage {kr(k['courtage'])}, FX {kr(k['fx_fees'])}, {_n(k['paid_trades'])} paid trades.")


@intent('fees_vs_gain', 'portfolio', 'fact', ['fees vs profit', 'fees profit', 'fees compared to profit', 'fees eat profit', 'fees against gains', 'fees bigger than profit', 'fees higher than profit', 'fees more than profit'],
        'Are my fees bigger than my profit?', 'habits')
def f_fvg(c):
    k, s = c.costs, c.I.get('sell_quality') or {}
    return two(f"Fees were {pc(need(k.get('fee_vs_realized_gross'), 'fees vs profit'), 0)} of the gross profit made by selling.",
               f"Realised before fees {kr(s['realized_before_fees'], True)}, after fees {kr(s['realized_net'], True)}." if s.get('realized_net') is not None else None)


@intent('realised_total', 'portfolio', 'fact', ['realised profit', 'realised', 'realised result', 'realised total', 'how much profit have i made selling', 'sold profit'], 'What is my realised profit?', 'assets')
def f_real(c):
    return f"Realised (after fees): {kr(c.ovv('realized'), True)} from {_n(c.ovv('sells'))} sells."


@intent('unrealised_total', 'portfolio', 'fact', ['unrealised profit', 'unrealised result', 'open positions result', 'paper loss', 'paper profit', 'unrealised total'],
        'What is my unrealised result?', 'assets')
def f_unreal(c):
    return f"Unrealised on open positions: {kr(c.ovv('unrealized'), True)} across {_n(c.ovv('held_assets'))} holdings (export snapshot)."


@intent('positions_count', 'portfolio', 'fact', ['how many positions', 'number of positions', 'number position', 'number holding', 'number stock', 'how many stocks', 'how many holdings', 'positions', 'how many assets do i own'],
        'How many positions do I hold?', 'assets', neg=['closed', 'sold out', 'under'])
def f_pos(c):
    return two(f"You hold {_n(c.ovv('held_assets'))} positions and have traded {_n(c.ovv('distinct_assets'))} assets in total.",
               f"{_n(c.ovv('distinct_assets') - c.ovv('held_assets'))} are closed.")


def _weight(c, a):
    hv = c.holdings_value
    return a['value'] / hv * 100 if hv else None


@intent('biggest_holding', 'portfolio', 'fact', ['biggest holding', 'biggest', 'largest', 'largest position', 'biggest position', 'largest holding', 'top holdings', 'top positions', 'what do i own most of', 'biggest stock'],
        'Which is my biggest holding?', 'assets')
def f_big(c):
    h = sorted(c.held, key=lambda a: -a['value'])[:3]
    need(h or None, 'holdings')
    return two(f"Biggest: {h[0]['name']}, {kr(h[0]['value'])} ({pc(_weight(c, h[0]))} of holdings).",
               'Next: ' + ', '.join(f"{nm(a['name'])} {pc(_weight(c, a))}" for a in h[1:]) + '.' if len(h) > 1 else None)


@intent('smallest_holding', 'portfolio', 'fact', ['smallest holding', 'smallest position', 'tiniest position', 'lowest value position'], 'Which is my smallest holding?', 'assets')
def f_small(c):
    h = sorted(c.held, key=lambda a: a['value'])
    need(h or None, 'holdings')
    return f"Smallest: {h[0]['name']}, only {kr(h[0]['value'])} ({pc(_weight(c, h[0]), 2)} of holdings)."


@intent('top_sector', 'portfolio', 'fact', ['top sector', 'biggest sector', 'which sector', 'sector split', 'sector weights', 'sector exposure', 'how much technology', 'sectors'],
        'Which is my top sector?', 'advice')
def f_sector(c):
    th = list(c.adv_summary().get('theme', {}).items())
    need(th or None, 'sector weights')
    return two(f"Top sector: {th[0][0]} at {pc(th[0][1], 0)} of holdings.",
               'Next: ' + ', '.join(f'{k} {pc(v, 0)}' for k, v in th[1:3]) + '.')


@intent('dividends_total', 'portfolio', 'fact', ['total dividends', 'how much dividend', 'dividends received', 'dividends so far', 'dividend income', 'my dividends', 'dividend', 'dividends'],
        'How much dividend have I received?', 'dividends', neg=['most', 'best', 'top', 'last', 'latest', 'year', 'tax', 'withholding'])
def f_div(c):
    s = c.I.get('dividends', {}).get('summary') or {}
    need(s.get('net'), 'dividends')
    return two(f"Dividends: {kr(s['net'])} net ({kr(s['gross'])} gross, {kr(s['tax'])} tax) from {_n(s['payers'])} companies.",
               f"Last 12 months {kr(s['ttm_net'])}, about {kr(s['avg_month'])} a month.")


@intent('dividends_year', 'portfolio', 'fact', ['dividends by year', 'dividend this year', 'dividends year', 'dividend year', 'last 12 months dividend', 'dividends 2026', 'dividends 2025', 'dividend per year', 'yearly dividends', 'dividends last 12 months', 'dividend last year'],
        'How much dividend this year?', 'dividends')
def f_divyear(c):
    s = c.I.get('dividends', {}).get('summary') or {}
    by = need(s.get('by_year'), 'dividends by year')
    return two('Net dividends by year: ' + ', '.join(f'{y} {kr(v)}' for y, v in by.items()) + '.',
               f"Last 12 months: {kr(s['ttm_net'])}.")


@intent('last_dividend', 'portfolio', 'fact', ['last dividend', 'latest dividend', 'most recent dividend', 'when was my last dividend'], 'When was my last dividend?', 'dividends')
def f_lastdiv(c):
    ser = need((c.I.get('dividends') or {}).get('series') or None, 'dividends')
    r = ser[-1]
    return f"Latest dividend booked {r['date']}: {kr(r['net'], d=2)} net."


@intent('top_payers', 'portfolio', 'fact', ['top dividend payers', 'best dividend stocks', 'most dividends', 'paid the most', 'pay the most dividend', 'dividend payers', 'biggest dividend', 'top dividend', 'best dividend'],
        'Which stocks paid the most dividends?', 'dividends')
def f_payers(c):
    p = need((c.I.get('dividends') or {}).get('payers') or None, 'dividend payers')[:3]
    return two('Top dividend payers (net): ' + ', '.join(f"{nm(x['name'])} {kr(x['net'])}" for x in p) + '.',
               f"Together {pc(c.I['dividends']['summary']['top3_share'], 0)} of all dividends.")


@intent('trade_counts', 'portfolio', 'fact', ['how many trades', 'number of trades', 'how many buys', 'how many sells', 'trades count', 'total trades', 'how many orders'],
        'How many trades have I made?', 'habits')
def f_trades(c):
    return two(f"{_n(c.ovv('trades'))} trades: {_n(c.ovv('buys'))} buys and {_n(c.ovv('sells'))} sells.",
               f"Over {_n(c.ovv('days_span'))} days, active on {_n(c.ovv('active_days'))} of them.")


@intent('best_realised', 'portfolio', 'fact', ['best trade', 'best realised', 'most profitable stock', 'biggest winner', 'best performer', 'best stock', 'my best asset', 'most money', 'made the most', 'most profit', 'best asset'],
        'Which asset made me the most money?', 'assets')
def f_best(c):
    a = max(c.assets, key=lambda a: a.get('total_pnl') or 0, default=None)
    need(a, 'assets')
    return f"Best total P&L: {a['name']} {kr(a['total_pnl'], True)} (realised {kr(a['realized'], True)}, unrealised {kr(a['unrealized'] or 0, True)})."


@intent('worst_realised', 'portfolio', 'fact', ['worst trade', 'worst realised', 'biggest loser', 'worst performer', 'worst stock', 'lost the most', 'my worst asset', 'lost most money', 'worst asset', 'loss the most'],
        'Which asset lost me the most?', 'assets')
def f_worst(c):
    a = min(c.assets, key=lambda a: a.get('total_pnl') or 0, default=None)
    need(a, 'assets')
    return f"Worst total P&L: {a['name']} {kr(a['total_pnl'], True)} (realised {kr(a['realized'], True)}, unrealised {kr(a['unrealized'] or 0, True)})."


@intent('biggest_unrealised_loss', 'portfolio', 'fact', ['biggest unrealised loss', 'most underwater', 'biggest paper loss', 'holding down the most', 'worst open position', 'biggest open loss'],
        'Which holding is down the most?', 'assets')
def f_ul(c):
    h = sorted((a for a in c.held if a.get('unrealized') is not None), key=lambda a: a['unrealized'])
    need(h or None, 'holdings')
    return two(f"Most underwater: {h[0]['name']}, {kr(h[0]['unrealized'], True)} ({pc(h[0]['unrealized_pct'], 0, True)}).",
               f"Next: {nm(h[1]['name'])} {kr(h[1]['unrealized'], True)}." if len(h) > 1 else None)


@intent('biggest_unrealised_gain', 'portfolio', 'fact', ['biggest unrealised gain', 'most profitable holding', 'best open position', 'holding up the most', 'biggest open profit'],
        'Which holding is up the most?', 'assets')
def f_ug(c):
    h = sorted((a for a in c.held if a.get('unrealized') is not None), key=lambda a: -a['unrealized'])
    need(h or None, 'holdings')
    return f"Most in profit: {h[0]['name']}, {kr(h[0]['unrealized'], True)} ({pc(h[0]['unrealized_pct'], 0, True)})."


@intent('under_1500', 'portfolio', 'fact', ['positions under 1500', 'small positions', 'how many tiny positions', 'under 1500 kr', 'positions below 1500'], 'How many positions are under 1 500 kr?', 'advice')
def f_u1500(c):
    xs = [a for a in c.held if a['value'] < 1500]
    return two(f"{len(xs)} positions are under 1 500 kr, {kr(sum(a['value'] for a in xs))} together.",
               'Smallest: ' + ', '.join(f"{nm(a['name'])} {kr(a['value'])}" for a in sorted(xs, key=lambda a: a['value'])[:2]) + '.' if xs else None)


@intent('data_range', 'portfolio', 'fact', ['date range', 'data range', 'since when', 'first trade', 'first deposit', 'how long have i invested', 'start date'], 'Since when is my data?', 'habits')
def f_range(c):
    return f"Your data runs from {c.ovv('first_date')} to {c.ovv('last_date')} ({_n(c.ovv('days_span'))} days)."


@intent('advice_summary', 'portfolio', 'fact', ['what should i do', 'suggestions', 'add trim ideas', 'ideas', 'what to buy', 'what to sell', 'advice', 'recommendations', 'rebalance', 'actions'],
        'What are the add / trim ideas?', 'advice')
def f_advice(c):
    cnt = c.adv_summary().get('counts') or {}
    return two(f"Rule-based ideas now: {cnt.get('ADD', 0)} add, {cnt.get('BUYBACK', 0)} buy back, {cnt.get('TRIM', 0)} trim, {cnt.get('CONSOLIDATE', 0)} consolidate, {cnt.get('REVIEW', 0)} review.",
               'Not a forecast; see the Advice tab for reasons and amounts.')


@intent('add_list', 'portfolio', 'fact', ['which to add', 'what should i add', 'should add', 'which add', 'add ideas', 'what to add', 'stocks to add', 'which stocks to buy more of', 'add candidates', 'buy more of'],
        'Which stocks should I add?', 'advice')
def f_addlist(c):
    xs, _ = _count_adv(c, 'ADD')
    xs = sorted(xs, key=lambda v: -(v.get('score') or 0))[:3]
    return two(('Add ideas: ' + ', '.join(f"{nm(v['name'])} {kr(v['amount'])}" for v in xs) + '.') if xs else 'No add ideas right now under your active profile.',
               'Rule-based ideas, not a forecast.')


@intent('trim_list', 'portfolio', 'fact', ['which to trim', 'what should i trim', 'should trim', 'which trim', 'trim ideas', 'what to trim', 'what to reduce', 'which to sell', 'should sell', 'trim candidates'],
        'Which stocks should I trim?', 'advice')
def f_trimlist(c):
    xs, _ = _count_adv(c, 'TRIM')
    xs = sorted(xs, key=lambda v: -(v.get('score') or 0))[:3]
    return two(('Trim ideas: ' + ', '.join(f"{nm(v['name'])} {kr(v['amount'])}" for v in xs) + '.') if xs else 'No trim ideas: nothing breaks the size or sector limits.',
               'Risk rules (position and sector size), not a forecast.')


@intent('buyback_list', 'portfolio', 'fact', ['which to buy back', 'stocks buy back', 'sold stocks buy back', 'could buy back', 'which buy back', 'buy back ideas', 'what sold stocks to buy back', 'buy back candidates', 'rebuy candidates'],
        'Which sold stocks could I buy back?', 'advice')
def f_bblist(c):
    xs, _ = _count_adv(c, 'BUYBACK')
    xs = sorted(xs, key=lambda v: -(v.get('score') or 0))[:3]
    return two(('Buy-back ideas: ' + ', '.join(f"{nm(v['name'])} {kr(v['amount'])}" for v in xs) + '.') if xs else 'No buy-back ideas right now.',
               'Rule-based, not a forecast.')


@intent('risk_summary', 'portfolio', 'fact', ['how risky is my portfolio', 'portfolio risk', 'risk level', 'my volatility', 'my drawdown', 'how much could i lose', 'risk'],
        'How risky is my portfolio?', 'advice')
def f_risk(c):
    p = c.adv_port()
    return two(f"Last year with today's weights: volatility {pc(p['vol'] * 100, 0)}, worst fall {pc(p['max_dd'] * 100, 0)}.",
               f"Top {p['n']} holdings correlate {num(p['corr'], 2)}, like about {num(p['eff_n'], 0)} independent bets.")


@intent('closed_count', 'portfolio', 'fact', ['closed positions', 'positions closed', 'have closed', 'how many closed', 'sold out', 'how many stocks have i sold', 'positions i exited'], 'How many positions have I closed?', 'assets')
def f_closed(c):
    return f"{_n(c.ovv('distinct_assets') - c.ovv('held_assets'))} of the {_n(c.ovv('distinct_assets'))} assets you traded are closed."


@intent('churn', 'portfolio', 'fact', ['most traded', 'most traded stock', 'most trade', 'trade the most', 'where do i trade most', 'churn', 'overtraded', 'most trades in one stock'], 'Which stock do I trade the most?', 'habits', neg=['weekday', 'day of the week'])
def f_churn(c):
    ch = need(c.I.get('churn_assets') or None, 'trading churn')[0]
    return f"Most traded: {ch['name']} with {_n(ch['trades'])} trades, {kr(ch['fees'])} fees, total P&L {kr(ch['total_pnl'], True)}."


@intent('warnings', 'portfolio', 'fact', ['data warnings', 'data problems', 'mismatch', 'is my data ok', 'data notes', 'ledger mismatch'], 'Are there data problems?', 'assets')
def f_warn(c):
    w = c.p.get('warnings') or []
    return (f"{len(w)} data note(s): {_clip(w[0], 140)}" if w else 'No data warnings: the ledger matches your holdings export.')


# ═════════════════════════ GROUP C: per-asset ═════════════════════════
def _asset_trades(c, a):
    return [t for t in c.trades if t.get('isin') == a.get('isin')]


def _dshort(d):
    try:
        return datetime.strptime(d, '%Y-%m-%d').strftime('%a %d %b')
    except Exception:
        return d


@intent('reports_week', 'portfolio', 'fact', ['reports this week', 'earnings this week', 'who reports', 'upcoming earnings', 'earnings today', 'earnings tomorrow', 'reports tomorrow', 'reports today', 'earnings calendar', 'report calendar', 'reporting this week', 'upcoming reports', 'next earnings', 'earnings dates', 'rapporter', 'rapport'],
        'Which of my stocks report this week?', 'portfolio')
def f_reports(c):
    r = c.reports()
    g = r['groups']
    e = [x for k in ('today', 'tomorrow', 'week') for x in g[k] if x['kind'] == 'earnings']
    n = r['counts']
    first = f"Earnings: {sum(1 for x in g['today'] if x['kind'] == 'earnings')} today, {sum(1 for x in g['tomorrow'] if x['kind'] == 'earnings')} tomorrow, {sum(1 for x in g['week'] if x['kind'] == 'earnings')} later this week (7 days)."
    if not e:
        return two(first, f"Ex-dividend dates in 7 days: {sum(1 for k in ('today', 'tomorrow', 'week') for x in g[k] if x['kind'] == 'ex_dividend')}. See the Reports calendar on the Portfolio page.")
    urgent = [x for k in ('today', 'tomorrow') for x in g[k] if x['kind'] == 'earnings']
    if urgent:
        return two(first, ('Today/tomorrow: ' + ', '.join(f"{x['name']} ({pc(x['weight'])})" for x in sorted(urgent, key=lambda x: -x['weight'])[:3]) + '.'))
    top = sorted(e, key=lambda x: -x['weight'])[:2]
    return two(first, 'Biggest: ' + ', '.join(f"{x['name']} {_dshort(x['date'])} ({pc(x['weight'])})" for x in top) + '.')


@intent('asset_report', 'asset', 'fact', ['report', 'reports', 'earnings', 'results', 'when report', 'next earnings', 'reporting date', 'quarterly'], 'When does Micron report?', 'portfolio', asset=True)
def a_report(c):
    a = c.asset
    ent = (c.reports().get('by_isin') or {}).get(a.get('isin'))
    if not ent:
        raise Missing(f"a report date for {a['name']} (funds and ETFs have none, or Yahoo has no data)")
    er, today = ent.get('earnings'), (c.reports().get('today') or '')
    parts = []
    if er and er['date'] >= today:
        days = (datetime.strptime(er['date'], '%Y-%m-%d') - datetime.strptime(today, '%Y-%m-%d')).days
        when = 'today' if days == 0 else 'tomorrow' if days == 1 else f'in {days} days'
        parts.append(f"{a['name']} reports {_dshort(er['date'])} ({when}), {'date still an estimate' if er.get('estimate') else 'date confirmed'}.")
        if er.get('eps') is not None:
            parts.append(f"Analysts expect EPS {num(er['eps'], 2)}.")
    else:
        parts.append(f"{a['name']} has no new report date yet; it has probably just reported.")
    if ent.get('ex_div') and ent['ex_div'] >= today:
        parts.append(f"Next ex-dividend date {_dshort(ent['ex_div'])}.")
    return two(parts[0], ' '.join(parts[1:]) or None)


@intent('asset_exdiv', 'asset', 'fact', ['ex dividend', 'exdividend', 'ex div', 'ex dividend date', 'dividend date', 'when dividend', 'next dividend', 'dividend payment date'], 'When is the next ex-dividend date for Apple?', 'portfolio', asset=True)
def a_exdiv(c):
    a = c.asset
    ent = (c.reports().get('by_isin') or {}).get(a.get('isin'))
    if not ent:
        raise Missing(f"dividend dates for {a['name']} (funds and ETFs have none, or Yahoo has no data)")
    today = c.reports().get('today') or ''
    ex, pay = ent.get('ex_div'), ent.get('pay_div')
    if ex and ex >= today:
        days = (datetime.strptime(ex, '%Y-%m-%d') - datetime.strptime(today, '%Y-%m-%d')).days
        when = 'today' if days == 0 else 'tomorrow' if days == 1 else f'in {days} days'
        return two(f"{a['name']}: ex-dividend {_dshort(ex)} ({when}); you need to own it before that day.",
                   (f"Payment {_dshort(pay)}." if pay and pay >= today else None))
    return f"{a['name']}: no upcoming ex-dividend date in Yahoo yet" + (f" (last was {_dshort(ex)})." if ex else '.')


@intent('nav_growth', 'portfolio', 'fact', ['net asset value', 'nav', 'growth curve', 'portfolio growth', 'how much has my portfolio grown', 'ytd', 'year to date', 'return this year', 'growth this year', 'performance this year', 'return last month', 'time weighted return', 'twr', 'how has my portfolio performed', 'portfolio performance'],
        'How much has my portfolio grown this year?', 'portfolio')
def f_nav(c):
    s = c.p.get('nav')
    if not isinstance(s, dict) or not s.get('ranges'):
        raise Missing('the growth curve (open the Portfolio page once so it can load)')
    r = s['ranges']
    return two(f"Net asset value {kr(s['nav'])}. This year {pc(r['ytd']['twr_pct'], 1, True)}, last month {pc(r['1m']['twr_pct'], 1, True)} (time-weighted: deposits are not growth).",
               f"Since {s['first_date']}: {pc(r['max']['twr_pct'], 1, True)}, worst drop {pc(r['max']['max_drop_pct'])}; {kr(s['net_deposits'])} deposited.")


@intent('asset_summary', 'asset', 'fact', ['how is', 'tell me about', 'about', 'info', 'status'], 'How is Micron doing?', 'assets', asset=True)
def a_summary(c):
    a = c.asset
    adv = c.adv_asset(a['isin']) if c.adv else None
    if a.get('held') and a.get('value'):
        w = _weight(c, a)
        s = f"{a['name']}: {kr(a['value'])} ({pc(w)} of holdings), unrealised {kr(a.get('unrealized') or 0, True)} ({pc(a.get('unrealized_pct') or 0, 0, True)})."
    else:
        s = f"{a['name']}: closed position, realised {kr(a.get('realized') or 0, True)} over {_n(a.get('buys', 0))} buys and {_n(a.get('sells', 0))} sells."
    return two(s, f"Rule-based idea: {'BUY BACK' if adv['action'] == 'BUYBACK' else adv['action']}, not a forecast." if adv else None)


@intent('asset_return', 'asset', 'fact', ['doing', 'perform', 'performance', 'return', 'profit', 'loss', 'unrealised', 'result', 'up or down', 'pnl'], 'How is Micron doing?', 'assets', asset=True)
def a_return(c):
    a = c.asset
    if a.get('held') and a.get('value'):
        return two(f"{a['name']}: unrealised {kr(a.get('unrealized') or 0, True)} ({pc(a.get('unrealized_pct') or 0, 1, True)}) on {kr(a['value'])}.",
                   f"Realised so far {kr(a.get('realized') or 0, True)}; total P&L {kr(a.get('total_pnl') or 0, True)}.")
    return two(f"{a['name']} is closed: total P&L {kr(a.get('total_pnl') or 0, True)} (all realised).",
               f"{_n(a.get('buys', 0))} buys, {_n(a.get('sells', 0))} sells, fees {kr(a.get('fees') or 0)}.")


@intent('asset_value', 'asset', 'fact', ['how much of', 'how much do i own', 'value', 'weight', 'size', 'quantity', 'qty', 'how many shares', 'do i own', 'do i hold', 'position', 'own', 'invested'],
        'How much do I own of ASML?', 'assets', asset=True)
def a_value(c):
    a = c.asset
    if not (a.get('held') and a.get('value')):
        return f"You do not hold {a['name']} now (closed position)."
    q = a['qty']
    return two(f"{a['name']}: {_n(q, 4 if q % 1 else 0)} {'share' if q == 1 else 'shares'} worth {kr(a['value'])}, {pc(_weight(c, a))} of holdings.",
               f"GAV {num(a['gav'], 2)} {a.get('ccy', '')}, price {num(a['price'], 2)} {a.get('ccy', '')}." if a.get('gav') is not None and a.get('price') is not None else None)


@intent('asset_fees', 'asset', 'fact', ['fee', 'fees', 'courtage', 'pay', 'broker'], 'How much did I pay in fees on ASML?', 'assets', asset=True)
def a_fees(c):
    a = c.asset
    n = a.get('buys', 0) + a.get('sells', 0)
    return two(f"Fees on {a['name']}: {kr(a.get('fees') or 0)} over {_n(n)} trades.",
               f"Bought {kr(a.get('bought_sek') or 0)}, sold {kr(a.get('sold_sek') or 0)}.")


@intent('asset_last', 'asset', 'fact', ['last buy', 'last bought', 'when did i buy', 'last sell', 'last sold', 'when did i sell', 'last trade', 'latest', 'recent', 'when'],
        'When did I last buy ASML?', 'assets', asset=True)
def a_last(c):
    a = c.asset
    ts = sorted(_asset_trades(c, a), key=lambda t: (t['date'], t.get('id') or 0))
    buys = [t for t in ts if t.get('side') == 'BUY']
    sells = [t for t in ts if t.get('side') == 'SELL']
    parts = []
    if buys:
        t = buys[-1]
        parts.append(f"last buy {t['date']} ({num(t['qty'], 4 if t['qty'] % 1 else 0)} at {num(t['price'], 2)} {t.get('ccy', '')})")
    if sells:
        t = sells[-1]
        parts.append(f"last sell {t['date']} ({num(t['qty'], 4 if t['qty'] % 1 else 0)} at {num(t['price'], 2)} {t.get('ccy', '')})")
    need(parts or None, f"trades for {a['name']}")
    return f"{a['name']}: " + '; '.join(parts) + '.'


@intent('asset_trades', 'asset', 'fact', ['trades', 'how many times', 'orders', 'traded', 'bought', 'sold', 'buys', 'sells'], 'How many times did I trade ASML?', 'assets', asset=True)
def a_trades(c):
    a = c.asset
    return two(f"{a['name']}: {_n(a.get('buys', 0))} buys and {_n(a.get('sells', 0))} sells.",
               f"First buy {a.get('first_buy') or '-'}, last trade {max(a.get('last_buy') or '', a.get('last_sell') or '') or '-'}.")


@intent('asset_dividends', 'asset', 'fact', ['dividend', 'dividends', 'yield', 'paid out', 'payout'], 'How much dividend from Novo Nordisk?', 'dividends', asset=True)
def a_div(c):
    a = c.asset
    for p in (c.I.get('dividends') or {}).get('payers') or []:
        if p.get('isin') == a.get('isin'):
            return two(f"{a['name']} paid {kr(p['net'], d=2)} net ({kr(p['gross'], d=2)} gross) in {p['payments']} payment(s).",
                       f"First {p['first']}, last {p['last']}.")
    return f"No dividends recorded from {a['name']}."


@intent('asset_advice', 'asset', 'fact', ['why', 'should i', 'should', 'trim', 'add', 'sell', 'reduce', 'buy', 'buy more', 'top up', 'recommend', 'suggest', 'idea', 'advice', 'flag', 'marked', 'rule', 'reason', 'good idea',
                                           'keep', 'increase', 'hold or', 'buy back', 'consolidate', 'review'],
        'Why is ASML marked TRIM?', 'advice', asset=True)
def a_advice(c):
    a = c.asset
    adv = c.adv_asset(a['isin'])
    if adv is None:
        c.advice()
        return f"No idea for {a['name']} right now: a closed position needs an uptrend and a pullback to be flagged for buy back."
    label = {'BUYBACK': 'BUY BACK'}.get(adv['action'], adv['action'])
    amt = f" ~{kr(adv['amount'])}" if adv.get('amount') else ''
    return two(f"{a['name']}: {label}{amt}. Rule-based idea, not a forecast.", _clip((adv.get('reasons') or [''])[0], 150))


# ═════════════════════════ matching + answer ═════════════════════════
DEFAULT_SUGGESTIONS = ['What are my total fees?', 'What does split orders mean?', 'Which is my biggest holding?']


def _rank(ctx, qtoks, cues, asset):
    has_gloss, has_fact = cues
    ranked = []
    for it in INTENTS:
        if it['asset'] and not asset:
            continue
        if it['id'] == 'sector_weight' and not getattr(ctx, 'sector', None):
            continue
        if asset and not it['asset'] and it['group'] not in ('help',):
            s0 = _intent_score(it, qtoks)
            s = s0 * 0.55                      # a named asset makes an asset question much more likely
        else:
            s = _intent_score(it, qtoks)
        if s <= 0 and not (it['id'] == 'asset_summary' and asset):
            continue
        if it['asset']:
            s += 1.0                           # an asset was named: asset intents get a head start
        if it['kind'] == 'gloss':
            s += 0.8 if has_gloss else 0.5 if has_fact else 0.2
        elif it['kind'] == 'fact':
            s += 0.8 if has_fact else 0.3 if has_gloss else 0.2
        elif it['kind'] == 'help':
            s += 0.5
        if it['id'] == 'asset_summary':
            s += 0.9                          # a bare asset name always gets a summary
        if it['id'] == 'sector_weight' and getattr(ctx, 'sector', None):
            s += 2.5
        ranked.append((s, it))
    ranked.sort(key=lambda x: -x[0])
    return ranked


def _run(it, ctx):
    try:
        return _fit(it['fn'](ctx))
    except Missing as m:
        return _fit(f"I don't have {m} in your data yet.")
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, AttributeError):
        return "I couldn't work that figure out from your data."


def answer(question, payload, advice=None):
    base = {'answer': '', 'link': None, 'confidence': 0.0, 'matched': None, 'suggestions': []}
    try:
        q = question if isinstance(question, str) else ''
        q = q.strip()[:MAX_Q]
        if not q:
            base['answer'] = 'Ask me about your fees, positions, dividends or a term like "split orders".'
            base['suggestions'] = DEFAULT_SUGGESTIONS[:]
            return base
        ctx = Ctx(payload, advice)
        mapped, stems, raw = _question_tokens(q)
        asset = _find_asset(ctx, stems, raw)
        ctx.asset = asset
        ctx.sector = None if asset else _find_sector(ctx, raw)
        cues = _cues(raw, mapped)
        ranked = _rank(ctx, mapped, cues, asset)
        if ranked:
            best_s, best = ranked[0]
            conf = 1 - math.exp(-best_s / 1.15)
            if len(ranked) > 1 and ranked[1][0] >= 0.85 * best_s and ranked[1][1]['id'] != best['id'] and ranked[1][1]['link'] != best['link']:
                conf *= 0.8
            if asset and best['asset']:
                conf = max(conf, 0.62)
            if asset is None and not best['asset'] and len(mapped) > 14 and best_s < 2.2:
                conf *= 0.8                     # long, rambling question matched on one loose word
            conf = round(min(conf, 0.99), 2)
        else:
            best, conf = None, 0.0
        if best is None or conf < 0.5:
            sug = []
            for s, it in ranked[:6]:
                if it['example'] not in sug and (not it['asset'] or asset):
                    sug.append(it['example'])
                if len(sug) == 3:
                    break
            for d in DEFAULT_SUGGESTIONS:
                if len(sug) < 3 and d not in sug:
                    sug.append(d)
            base.update(answer="I can't answer that from your data. Try one of these:", confidence=conf, suggestions=sug[:3])
            return base
        text = _run(best, ctx)
        label = best['id'] + (f' · {asset["name"]}' if asset and best['asset'] else '')
        base.update(answer=text, link=best['link'], confidence=conf, matched=label)
        return base
    except Exception:       # the assistant must never break the page
        base['answer'] = "I couldn't work that out from your data."
        return base
