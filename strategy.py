"""
strategy.py - one strategy per category (Python stdlib only). Used by advisor.py.

Why per category: a 10-year test (2017-2026) of equal-weight baskets of the holdings in each category showed
  * broad index funds: buy and hold beat every timing rule by far (12.3% a year against 4.9-8.6%) -> never timed;
  * AI and semiconductor chain (the most volatile group): holding half and running half on the weekly SMA(200) rule had the
    best return per unit of volatility and cut the worst fall from -43% to -37% -> 'half_trend';
  * quality groups (big tech, healthcare and consumer, financials): buy and hold was best on return and on return per unit
    of volatility -> 'quality' (hold, add new money on pullbacks in an uptrend, review when the trend breaks with a loss);
  * energy and materials: SMA(50) above SMA(200) gave the best return per unit of worst fall -> 'regime';
  * dip buying in and out on RSI was the weakest rule everywhere -> RSI only times when NEW money goes in, never a sale.
The test used today's holdings (survivors), so buy-and-hold looks better than it will be; trend rules were therefore chosen by
the size of the fall they prevent, not by return.

"200-day average" = SMA(200): simple average of the last 200 daily closes (dividend/split adjusted). The trend rule looks at the
LAST CLOSE OF EACH WEEK (fewer false signals than daily): weekly close above SMA(200) = in, below = out. One weekly close decides.
"""
import json
import math
import os
import re
from datetime import date

# ───────── categories ─────────
# key: (label, rule, short description of the strategy)
CATS = {
    'core':        ('Broad index funds', 'core', 'Buy and hold with monthly saving. Never timed.'),
    'ai':          ('AI and semiconductor chain', 'half_trend', 'Hold half (theme ETFs and up to 5 leaders), run the other half on the weekly SMA(200) rule. Hard cap.'),
    'bigtech':     ('Big tech and software', 'quality', 'Quality, buy and hold. New money on pullbacks in an uptrend.'),
    'health':      ('Healthcare and consumer', 'quality', 'Defensive anchor, buy and hold. New money on pullbacks.'),
    'industrials': ('Industrials and defence', 'half_trend', 'Buy and hold the leaders, the rest on the weekly SMA(200) rule.'),
    'financials':  ('Financials', 'quality', 'Buy and hold. New money on pullbacks in an uptrend.'),
    'materials':   ('Energy and materials', 'regime', 'Hold while SMA(50) is above SMA(200); out when it falls below.'),
    'defensive':   ('Gold, bonds and real estate', 'fixed', 'Fixed weight, no timing; topped up with deposits.'),
    'cash':        ('Opportunity cash', 'cash', 'Cash for opportunities and for the panic ladder.'),
}
ORDER = ['core', 'ai', 'bigtech', 'health', 'industrials', 'financials', 'materials', 'defensive', 'cash']

# target % of the whole account (holdings + cash) per profile; each column sums to 100
TARGETS = {
    'conservative': {'core': 60, 'ai': 10, 'bigtech': 6, 'health': 7, 'industrials': 4, 'financials': 3, 'materials': 2, 'defensive': 4, 'cash': 4},
    'balanced':     {'core': 50, 'ai': 15, 'bigtech': 7, 'health': 7, 'industrials': 5, 'financials': 3, 'materials': 3, 'defensive': 5, 'cash': 5},
    'aggressive':   {'core': 40, 'ai': 22, 'bigtech': 9, 'health': 7, 'industrials': 6, 'financials': 4, 'materials': 4, 'defensive': 3, 'cash': 5},
}
RSI_ADD = {'conservative': 35, 'balanced': 40, 'aggressive': 45}     # new money into a stock only below this RSI(14), and only in an uptrend
KEEP_LEADERS = 5        # single names kept as the 'hold half' of a half_trend category (theme ETFs are always kept)
BAND = 5.0              # %-points: a category further than this from its target is over / under weight
MAX_W = 4.0             # % of the account: one stock never more than this
DUST = 1500             # kr: below this a position cannot move the result; sell it or top it up
MIN_ORDER = 2500        # kr: smaller orders are mostly courtage
STRESS = {              # illustrative shocks in %, per category (not forecasts)
    'AI repeat of this year': {'ai': -55, 'core': -15, 'cash': 0, 'defensive': 0, '_other': -20},
    'Broad bear market':      {'ai': -50, 'core': -30, 'cash': 0, 'defensive': 3, '_other': -35},
    'AI recovers':            {'ai': 40, 'core': 10, 'cash': 0, 'defensive': 2, '_other': 10},
}

DEFAULT_SETTINGS = {'deposit': 10000, 'reduce': 15000, 'opportunity_pct': 5.0, 'overrides': {}}
SETTINGS_FILE = 'plan_settings.json'

_INDEX_WORDS = re.compile(r'\b(index|indeks|indeksi|s&p 500|msci|ftse|stoxx|omxs30|nasdaq-100|nasdaq 100|russell|all-world|world|global leaders|total market|em imi|emerging)\b', re.I)
_THEME_ETF = re.compile(r'semiconductor|artificial intelligence|\bai\b|robotics|big data|cloud|cyber', re.I)
_DEFENSIVE = re.compile(r'gold|silver|treasury|bond|obligation|ränte|rante|real estate|reit|inflation', re.I)
_GOLD_MINERS = re.compile(r'metals|miners|mining', re.I)
AI_NAMES = ('Nebius', 'CoreWeave', 'Bloom Energy', 'GE Vernova', 'Siemens Energy', 'Schneider', 'Oklo', 'Synopsys', 'Cadence', 'Dell',
            'Sandisk', 'Western Digital', 'Seagate', 'Celestica', 'Coherent', 'Lumentum', 'Fabrinet', 'Arm Holdings', 'SK hynix', 'Marvell',
            'Anthropic', 'Vertiv', 'Super Micro', 'Broadcom', 'Taiwan Semiconductor', 'Credo', 'Astera', 'Pure Storage', 'NetApp')
AI_INDUSTRIES = ('Semiconductor', 'Computer Hardware', 'Electronic Components', 'Communication Equipment', 'Scientific & Technical Instruments')
BIGTECH_NAMES = ('Alphabet', 'Microsoft', 'Apple', 'Amazon', 'Meta Platforms', 'Netflix', 'Tesla', 'MongoDB', 'IBM', 'Oracle', 'Salesforce',
                 'Adobe', 'ServiceNow', 'Palantir', 'Shopify', 'Spotify', 'Uber', 'SAP')


def category_of(asset, sec=None, overrides=None):
    """Category key of one asset: user override first, then fund / ETF name rules, then Yahoo sector and industry."""
    isin = asset.get('isin')
    if overrides and isin in overrides and overrides[isin] in CATS:
        return overrides[isin]
    name = (asset.get('name') or '').strip()
    sec = sec or {}
    sector, industry, qtype = sec.get('sector') or '', sec.get('industry') or '', (sec.get('quote_type') or '').upper()
    fundlike = asset.get('type') in ('Fund', 'ETF/ETC') or qtype in ('ETF', 'MUTUALFUND') or bool(sec.get('category')) or ' ETF' in name or 'UCITS' in name
    if fundlike:
        if _THEME_ETF.search(name):
            return 'ai'
        if _DEFENSIVE.search(name) and not _GOLD_MINERS.search(name):
            return 'defensive'
        if _GOLD_MINERS.search(name):
            return 'materials'
        if _INDEX_WORDS.search(name) or asset.get('type') == 'Fund':
            return 'core'
    if name.startswith(AI_NAMES) or any(i in industry for i in AI_INDUSTRIES):
        return 'ai'
    if name.startswith(BIGTECH_NAMES) or sector in ('Technology', 'Communication Services'):
        return 'bigtech'
    if sector in ('Healthcare', 'Consumer Defensive', 'Consumer Cyclical'):
        return 'health'
    if sector in ('Financial Services', 'Real Estate'):
        return 'financials'
    if sector in ('Energy', 'Basic Materials'):
        return 'materials'
    if sector in ('Industrials', 'Utilities'):
        return 'industrials'
    if fundlike:
        return 'core'
    return 'bigtech' if 'tech' in industry.lower() else 'industrials'


# ───────── weekly SMA(200) trend ─────────
_EPOCH = date(1970, 1, 1).toordinal()


def _day(d):
    return date.fromordinal(int(d) + _EPOCH)


def weekly_trend(h, today=None):
    """Trend state of one daily history {'d': [epoch days], 'c': [adjusted closes]}.
    up: the last COMPLETED week's close is above that day's SMA(200). weeks: how many weekly closes in a row the state has held.
    live_up: today's close vs SMA(200) (early warning only; the rule waits for the weekly close). regime_up: SMA(50) > SMA(200)."""
    if not h or len(h.get('c') or []) < 205:
        return None
    c, d = h['c'], h['d']
    n = len(c)
    s200 = [None] * n
    run = sum(c[:200])
    s200[199] = run / 200
    for i in range(200, n):
        run += c[i] - c[i - 200]
        s200[i] = run / 200
    s50 = sum(c[-50:]) / 50
    today = today or date.today()
    # last bar of each ISO week
    ends, prev_key = [], None
    for i in range(199, n):
        key = _day(d[i]).isocalendar()[:2]
        if key != prev_key:
            ends.append(i)
            prev_key = key
        else:
            ends[-1] = i
    last_day = _day(d[ends[-1]])
    if last_day.isocalendar()[:2] == today.isocalendar()[:2] and today.weekday() < 5 and last_day.weekday() < 4:
        ends = ends[:-1]                      # this week is not finished yet: its close is not a weekly close
    if not ends:
        return None
    states = [c[i] > s200[i] for i in ends]
    up = states[-1]
    weeks = 0
    for st in reversed(states):
        if st != up:
            break
        weeks += 1
    i = ends[-1]
    since = _day(d[ends[len(states) - weeks]]).isoformat()                         # the weekly close that started the current state
    flips12 = sum(1 for a, b in zip(states[-13:], states[-12:]) if a != b)          # changes over the last 12 weekly closes (choppy = unreliable)
    return {'up': up, 'weeks': weeks, 'since': since, 'flips12': flips12, 'hist': states[-8:],
            'date': _day(d[i]).isoformat(), 'close': round(c[i], 4), 'sma200': round(s200[i], 4),
            'dist': round(c[i] / s200[i] - 1, 4), 'live_up': c[-1] > s200[-1], 'live_dist': round(c[-1] / s200[-1] - 1, 4),
            'regime_up': s50 > s200[-1], 'sma50': round(s50, 4), 'sma200_now': round(s200[-1], 4)}


# ───────── settings (per user, in the user's own profile folder) ─────────
def load_settings(folder):
    s = dict(DEFAULT_SETTINGS, overrides={})
    try:
        with open(os.path.join(folder, SETTINGS_FILE), encoding='utf-8') as f:
            raw = json.load(f)
        s.update(clean_settings(raw, partial=True))
    except Exception:
        pass
    return s


def clean_settings(raw, partial=False):
    """Validated copy of user input. Raises ValueError with a readable message."""
    if not isinstance(raw, dict):
        raise ValueError('Settings must be an object.')
    out = {}

    def num(k, lo, hi):
        if k not in raw:
            if partial:
                return
            raise ValueError(f'{k} is missing.')
        try:
            v = float(raw[k])
        except (TypeError, ValueError):
            raise ValueError(f'{k} must be a number.')
        if not (lo <= v <= hi) or math.isnan(v):
            raise ValueError(f'{k} must be between {lo:g} and {hi:g}.')
        out[k] = round(v, 2) if k == 'opportunity_pct' else int(round(v))
    num('deposit', 0, 1_000_000)
    num('reduce', 0, 1_000_000)
    num('opportunity_pct', 0, 20)
    if 'overrides' in raw:
        ov = raw['overrides']
        if not isinstance(ov, dict) or len(ov) > 500:
            raise ValueError('overrides must be an object.')
        good = {}
        for k, v in ov.items():
            if not (isinstance(k, str) and re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]', k)):
                raise ValueError('An override key is not an ISIN.')
            if v not in CATS or v == 'cash':
                raise ValueError(f'Unknown category: {str(v)[:30]}')
            good[k] = v
        out['overrides'] = good
    return out


def save_settings(folder, raw):
    cur = load_settings(folder)
    cur.update(clean_settings(raw, partial=True))
    tmp = os.path.join(folder, SETTINGS_FILE + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cur, f, indent=1)
    os.replace(tmp, os.path.join(folder, SETTINGS_FILE))
    return cur


# ───────── portfolio-level helpers ─────────
def targets(profile, settings):
    t = dict(TARGETS.get(profile) or TARGETS['balanced'])
    opp = float(settings.get('opportunity_pct', t['cash']))
    diff = opp - t['cash']
    t['cash'] = opp
    t['core'] = max(0.0, t['core'] - diff)          # more opportunity cash comes out of the core, and the other way round
    return t


def _round500(x):
    return int(round(x / 500.0)) * 500


def core_split(core_assets):
    """Where core money goes: the broadest index funds you already own (global > USA / S&P 500 > Sweden / Nordic > emerging)."""
    def rank(n):
        n = n.lower()
        if re.search(r'all-world|world|global|acwi', n): return 0
        if re.search(r's&p 500|usa|us index|nasdaq|russell', n): return 1
        if re.search(r'sverige|omxs30|sweden|nordic|norge|suomi', n): return 2
        if re.search(r'emerging|em imi|\bem\b', n): return 3
        return 4
    xs = sorted(core_assets, key=lambda a: (rank(a['name']), -a['value']))
    pick = xs[:3]
    shares = [0.5, 0.3, 0.2][:len(pick)]
    tot = sum(shares) or 1
    return [(a, s / tot) for a, s in zip(pick, shares)]


def deposit_plan(cat_kr, total, tg, deposit, buy_ideas):
    """Split the next monthly deposit over the categories furthest under target. buy_ideas: {cat: [names with an entry signal]}.
    Quality / trend categories get money only when one of their stocks has an entry signal; otherwise it goes to the core."""
    if deposit <= 0:
        return []
    after = total + deposit
    gap = {k: max(0.0, tg[k] / 100 * after - cat_kr.get(k, 0)) for k in ORDER}
    for k in ORDER:
        if CATS[k][1] in ('quality', 'half_trend', 'regime') and not buy_ideas.get(k):
            gap['core'] += gap[k]          # no stock in that group has an entry signal: the money waits in the core instead
            gap[k] = 0
    tot_gap = sum(gap.values())
    if tot_gap <= 0:
        return [{'cat': 'core', 'amount': deposit}]
    raw = {k: deposit * g / tot_gap for k, g in gap.items() if g > 0}
    small = [k for k, v in raw.items() if v < MIN_ORDER and k != 'cash']
    for k in small:                                   # too small for an order: merge into the biggest share
        big = max(raw, key=raw.get)
        if big != k:
            raw[big] += raw.pop(k)
    out = [{'cat': k, 'amount': _round500(v)} for k, v in sorted(raw.items(), key=lambda x: -x[1]) if _round500(v) > 0]
    diff = deposit - sum(x['amount'] for x in out)
    if out:
        out[0]['amount'] += diff
    return out


def transition(cat_kr, tg, deposit, reduce, months=36):
    """Share of the over-target categories and of the core over time, prices held flat (only the mix changes).
    plan: deposits to the categories under target + reductions of at most `reduce` kr a month in the over-target ones;
    deposits_only: deposits to the categories under target, nothing sold; status_quo: deposits in today's mix."""
    total0 = sum(cat_kr.values()) or 1
    keys = list(ORDER)

    def run(kind):
        s = {k: cat_kr.get(k, 0.0) for k in keys}
        path = [dict(s)]
        for _ in range(months):
            s = dict(s)
            tot = sum(s.values()) + deposit
            if kind == 'status_quo':
                for k in keys:
                    s[k] += deposit * (cat_kr.get(k, 0) / total0)
            else:
                cash_in = deposit
                if kind == 'plan':
                    for k in keys:
                        over = s[k] - tg[k] / 100 * tot
                        if over > 0 and CATS[k][1] in ('half_trend', 'regime', 'quality') and over > BAND / 100 * tot * 0.2:
                            cut = min(reduce * (over / max(1, sum(max(0, s[j] - tg[j] / 100 * tot) for j in keys))), over)
                            s[k] -= cut
                            cash_in += cut
                gaps = {k: max(0.0, tg[k] / 100 * tot - s[k]) for k in keys}
                g = sum(gaps.values())
                for k in keys:
                    s[k] += cash_in * (gaps[k] / g if g else (1 if k == 'core' else 0))
            path.append(s)
        return path

    out = {}
    for kind in ('plan', 'deposits_only', 'status_quo'):
        p = run(kind)
        out[kind] = {k: [round(x[k] / sum(x.values()) * 100, 1) for x in p] for k in keys}
    over = [k for k in keys if cat_kr.get(k, 0) / total0 * 100 > tg[k] + BAND]
    hit = None
    if over:
        for m in range(months + 1):
            if all(out['plan'][k][m] <= tg[k] + BAND for k in over):
                hit = m
                break
    return {'months': months, 'paths': out, 'over': over, 'months_to_band': hit}


def stress(weights):
    """Portfolio result in % for each scenario, weights = {cat: %}."""
    res = {}
    for name, sh in STRESS.items():
        res[name] = round(sum(w / 100 * sh.get(k, sh['_other']) for k, w in weights.items()), 1)
    return res


def fit_scores(m):
    """0-10 ratings against the five popular strategies, from measurable facts m. Each item: (score, measure text)."""
    def clamp(x):
        return int(max(0, min(10, round(x))))
    return [
        {'key': 'index', 'label': 'Index funds with regular saving', 'score': clamp(m['core_pct'] / 50 * 10),
         'measure': f"{m['core_pct']:.0f}% of the account is in broad index funds; the rule is 50% or more.",
         'rule': 'Own the whole market, add every month, never time it.'},
        {'key': 'trend', 'label': 'Trend following', 'score': clamp(m['up_pct'] / 10),
         'measure': f"{m['up_pct']:.0f}% of the stock money had its last weekly close above SMA(200).",
         'rule': 'Hold what is above SMA(200); leave on a weekly close below it.'},
        {'key': 'quality', 'label': 'Value and quality', 'score': clamp(10 - max(0, m['positions'] - 30) / 10 - (2 if m['tiny'] > 5 else 0) - (3 if (m['avg_hold'] or 999) < 90 else 0)),
         'measure': f"{m['positions']} positions (the rule is 15 to 30), {m['tiny']} under {DUST} kr" + (f", a sale is held {m['avg_hold']:.0f} days on average." if m['avg_hold'] else '.'),
         'rule': 'Few good businesses, bought at a discount and held for years.'},
        {'key': 'momentum', 'label': 'Momentum', 'score': clamp(m['mom_pct'] / 10),
         'measure': f"{m['mom_pct']:.0f}% of the stock money is in names with positive 12-month momentum and an uptrend.",
         'rule': 'Hold the leaders; sell what drops out of the top group each month.'},
        {'key': 'allocation', 'label': 'Diversified mix and rebalancing', 'score': clamp(10 - m['distance'] / 6),
         'measure': f"The mix is {m['distance']:.0f} points away from its targets; the largest group is {m['top_label']} at {m['top_pct']:.0f}%" + (f"; the 30 largest act like {m['eff_n']:.1f} independent bets." if m.get('eff_n') else '.'),
         'rule': 'Assets that behave differently, restored to fixed weights on a schedule.'},
    ]
