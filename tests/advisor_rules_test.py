"""Plan rules check:  python tests/advisor_rules_test.py   (no network: prices, symbols and sectors are made up here)

One strategy per category (strategy.py + advisor.py): categories, the weekly SMA(200) state, settings validation, targets,
the deposit plan, the transition path, and the actions on a made-up portfolio:
size cap, trend exit of the trend half, hold half kept, regime exit, pullback ADD, deposit-plan ADD for index funds,
tiny position, and NO RSI take-profit any more."""
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import advisor, sectors, strategy, symbols   # noqa: E402

res = []


def ok(name, cond, detail=''):
    res.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + str(detail)[:150]) if detail else ''))


# ───── categories ─────
C = strategy.category_of
ok('theme ETF -> AI chain', C({'name': 'VanEck Semiconductor ETF', 'type': 'Stock'}, {'quote_type': 'ETF', 'category': 'Technology'}) == 'ai')
ok('Nordnet index fund -> core', C({'name': 'Nordnet USA Index', 'type': 'Fund'}, {}) == 'core')
ok('broad UCITS ETF -> core', C({'name': 'SPDR S&P 500 UCITS ETF (Acc)', 'type': 'Stock'}, {'quote_type': 'ETF'}) == 'core')
ok('physical gold -> defensive', C({'name': 'Xetra-Gold', 'type': 'ETF/ETC'}, {'quote_type': 'ETF'}) == 'defensive')
ok('metals fund -> energy and materials', C({'name': 'AuAg Essential Metals A', 'type': 'Fund'}, {}) == 'materials')
ok('semiconductor industry -> AI chain', C({'name': 'Micron Technology'}, {'sector': 'Technology', 'industry': 'Semiconductors'}) == 'ai')
ok('AI power name -> AI chain', C({'name': 'GE Vernova'}, {'sector': 'Industrials', 'industry': 'Specialty Industrial Machinery'}) == 'ai')
ok('Alphabet -> big tech', C({'name': 'Alphabet A'}, {'sector': 'Communication Services'}) == 'bigtech')
ok('healthcare -> health', C({'name': 'Novo Nordisk B'}, {'sector': 'Healthcare'}) == 'health')
ok('financials', C({'name': 'BlackRock'}, {'sector': 'Financial Services'}) == 'financials')
ok('energy -> materials', C({'name': 'Chevron'}, {'sector': 'Energy'}) == 'materials')
ok('industrials', C({'name': 'Alfa Laval'}, {'sector': 'Industrials'}) == 'industrials')
ok('user override wins', C({'name': 'Alfa Laval', 'isin': 'SE0000695876'}, {'sector': 'Industrials'}, {'SE0000695876': 'health'}) == 'health')

# ───── made-up daily histories: weekdays only, ending on the last Friday ─────
end = date.today() - timedelta(days=(date.today().weekday() - 4) % 7 or 7)
N = 320


def days(n=N):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.toordinal() - date(1970, 1, 1).toordinal())
        d -= timedelta(days=1)
    return out[::-1]


def series(kind):
    c, v = [], 100.0
    for i in range(N):
        if kind == 'rise':
            v *= 1.003
        elif kind == 'pullback':                       # long rise, then 15 down days: oversold but still above SMA(200)
            v *= 1.004 if i < N - 15 else 0.993
        elif kind == 'down':                           # rise, then a long fall: below SMA(200) and SMA(50) below SMA(200)
            v *= 1.003 if i < 200 else 0.991
        c.append(round(v, 4))
    return {'at': time.time(), 'd': days(), 'c': c, 'ccy': 'SEK'}


H = {'RISE': series('rise'), 'PULL': series('pullback'), 'DOWN': series('down')}
wt = strategy.weekly_trend(H['RISE'])
ok('weekly trend: steady rise is above SMA(200) for many weeks', wt and wt['up'] and wt['weeks'] > 10 and wt['regime_up'], wt and (wt['up'], wt['weeks']))
wt = strategy.weekly_trend(H['DOWN'])
ok('weekly trend: long fall is below SMA(200), SMA(50) below SMA(200)', wt and not wt['up'] and not wt['regime_up'], wt and (wt['up'], wt['dist']))
# the current week is not finished: a Wednesday close must not count as a weekly close
mid = dict(H['RISE'])
wed = end + timedelta(days=5)                          # the Wednesday after the last Friday
mid = {'d': H['RISE']['d'] + [wed.toordinal() - date(1970, 1, 1).toordinal() - 2, wed.toordinal() - date(1970, 1, 1).toordinal() - 1, wed.toordinal() - date(1970, 1, 1).toordinal()],
       'c': H['RISE']['c'] + [1.0, 1.0, 1.0]}           # crash below SMA(200) on Mon-Wed of the running week
wt = strategy.weekly_trend(mid, today=wed)
ok('an unfinished week is ignored (the rule waits for Friday), live state warns', wt and wt['up'] and not wt['live_up'], wt and (wt['up'], wt['live_up']))

# ───── settings ─────
s = strategy.clean_settings({'deposit': 10000, 'reduce': 15000, 'opportunity_pct': 5, 'overrides': {'SE0000695876': 'health'}})
ok('valid settings pass', s['deposit'] == 10000 and s['overrides'] == {'SE0000695876': 'health'})
for bad, why in (({'deposit': -1, 'reduce': 0, 'opportunity_pct': 5}, 'negative deposit'), ({'deposit': 1, 'reduce': 0, 'opportunity_pct': 50}, 'cash above 20%'),
                 ({'deposit': 1, 'reduce': 0, 'opportunity_pct': 5, 'overrides': {'x': 'ai'}}, 'override key not an ISIN'),
                 ({'deposit': 1, 'reduce': 0, 'opportunity_pct': 5, 'overrides': {'SE0000695876': 'cash'}}, 'cash is not a holding category'),
                 ({'deposit': 'abc', 'reduce': 0, 'opportunity_pct': 5}, 'not a number')):
    try:
        strategy.clean_settings(bad)
        ok('rejects ' + why, False)
    except ValueError:
        ok('rejects ' + why, True)
ok('the profile is a saved setting', strategy.clean_settings({'profile': 'aggressive'}, partial=True) == {'profile': 'aggressive'})
try:
    strategy.clean_settings({'profile': 'wild'}, partial=True)
    ok('rejects an unknown profile', False)
except ValueError:
    ok('rejects an unknown profile', True)
for prof in strategy.TARGETS:
    ok(f'{prof} targets sum to 100', abs(sum(strategy.targets(prof, strategy.DEFAULT_SETTINGS).values()) - 100) < 1e-9)
t = strategy.targets('balanced', {'opportunity_pct': 8})
ok('more opportunity cash comes out of the core', t['cash'] == 8 and t['core'] == 47, t)

# ───── deposit plan and transition ─────
cat_kr = {k: 0.0 for k in strategy.ORDER}
cat_kr.update(core=10000, ai=50000, bigtech=5000, health=5000, industrials=5000, financials=3000, materials=3000, defensive=2000, cash=500)
tg = strategy.targets('balanced', strategy.DEFAULT_SETTINGS)
dp = strategy.deposit_plan(cat_kr, sum(cat_kr.values()), tg, 10000, {})
ok('deposit plan spends exactly the deposit', sum(x['amount'] for x in dp) == 10000, dp)
ok('nothing of the deposit goes to an over-target group', all(x['cat'] != 'ai' for x in dp))
ok('without stock entry signals the stock groups\' share waits in the core', dp[0]['cat'] == 'core' and all(x['cat'] in ('core', 'cash', 'defensive') for x in dp), dp)
tr = strategy.transition(cat_kr, tg, 10000, 15000, months=36)
ok('transition: the over-target group falls under the plan', tr['paths']['plan']['ai'][24] < tr['paths']['deposits_only']['ai'][24] < tr['paths']['status_quo']['ai'][24], [tr['paths'][k]['ai'][24] for k in ('plan', 'deposits_only', 'status_quo')])
ok('transition: status quo keeps the mix', abs(tr['paths']['status_quo']['ai'][36] - tr['paths']['status_quo']['ai'][0]) < 0.2)
ok('transition: months to target band reported', tr['over'] == ['ai'] and tr['months_to_band'] is not None, (tr['over'], tr['months_to_band']))

# ───── the whole plan on a made-up portfolio ─────
# total 76 200 kr: AI chain 29% (over its 15% target), index funds 45% (under 50%), big tech 6% (under 7%)
ASSETS = [  # isin, name, type, value, unrealised %, symbol, sector, industry
    ('US0000000001', 'Micron Technology', 'Stock', 9000, -20, 'RISE', 'Technology', 'Semiconductors'),
    ('US0000000002', 'NVIDIA', 'Stock', 3000, 10, 'RISE', 'Technology', 'Semiconductors'),
    ('US0000000003', 'ASML Holding', 'Stock', 2900, -5, 'RISE', 'Technology', 'Semiconductor Equipment & Materials'),
    ('US0000000004', 'Advanced Micro Devices', 'Stock', 2800, -10, 'RISE', 'Technology', 'Semiconductors'),
    ('US0000000005', 'Applied Materials', 'Stock', 2700, -10, 'RISE', 'Technology', 'Semiconductor Equipment & Materials'),
    ('US0000000006', 'Seagate Technology', 'Stock', 2000, -30, 'DOWN', 'Technology', 'Computer Hardware'),
    ('US0000000007', 'Alphabet A', 'Stock', 2500, 50, 'RISE', 'Communication Services', 'Internet Content'),
    ('US0000000008', 'Microsoft', 'Stock', 2000, 5, 'PULL', 'Technology', 'Software - Infrastructure'),
    ('US0000000009', 'Chevron', 'Stock', 2500, -5, 'DOWN', 'Energy', 'Oil & Gas Integrated'),
    ('US0000000010', 'Coca-Cola', 'Stock', 800, 4, 'RISE', 'Consumer Defensive', 'Beverages'),
    ('DK0000000013', 'Novo Nordisk B', 'Stock', 3000, -5, 'RISE', 'Healthcare', 'Drug Manufacturers'),
    ('US0000000014', 'BlackRock', 'Stock', 3000, 10, 'RISE', 'Financial Services', 'Asset Management'),
    ('SE0000000015', 'Alfa Laval', 'Stock', 3000, 3, 'RISE', 'Industrials', 'Specialty Industrial Machinery'),
    ('DE0000000016', 'Xetra-Gold', 'ETF/ETC', 3000, 2, None, None, None),
    ('SE0000000011', 'Nordnet USA Index', 'Fund', 20000, 8, None, None, None),
    ('SE0000000012', 'Nordnet Sverige Index', 'Fund', 14000, 8, None, None, None),
]
sym = {a[0]: a[5] for a in ASSETS if a[5]}
symbols.resolve = lambda isin, name, ccy: {'symbol': sym[isin]} if isin in sym else None
advisor._histories = lambda syms, budget=45: {s: H[s] for s in syms if s in H}
sectors.batch = lambda items, budget=0: ({a[0]: {'sector': a[6], 'industry': a[7], 'quote_type': 'EQUITY' if a[2] == 'Stock' else 'MUTUALFUND'} for a in ASSETS if a[6]}, 0)
assets = [{'isin': a[0], 'name': a[1], 'type': a[2], 'ccy': 'SEK', 'held': True, 'qty': 10, 'value': a[3], 'unrealized': a[3] * a[4] / 100,
           'unrealized_pct': a[4], 'realized': 0, 'fees': 0, 'sells': 0} for a in ASSETS]
payload = {'assets': assets, 'trades': [], 'insights': {'overview': {'cash_balance': 0}, 'sell_quality': {'avg_hold_days': 40}}, 'generated': 'x'}
r = advisor.advise(payload, None, 'balanced', {'deposit': 10000, 'reduce': 15000, 'opportunity_pct': 5})
A = {v['name']: v for v in r['assets'].values()}
total = sum(a[3] for a in ASSETS)
ok('size cap: one stock above 4% of the account is cut back', A['Micron Technology']['action'] == 'TRIM' and A['Micron Technology']['rule'] == 'size_cap'
   and abs(A['Micron Technology']['amount'] - (9000 - 0.04 * total)) <= 500, (A['Micron Technology']['action'], A['Micron Technology']['amount']))
ok('hold half: the largest AI names are kept through the trend', all(A[n]['action'] == 'HOLD' and A[n]['keep'] for n in ('NVIDIA', 'ASML Holding', 'Advanced Micro Devices', 'Applied Materials')),
   [(n, A[n]['action']) for n in ('NVIDIA', 'ASML Holding')])
ok('trend half: a weekly close below SMA(200) is a sale (trend exit)', A['Seagate Technology']['action'] == 'TRIM' and A['Seagate Technology']['rule'] == 'trend_exit'
   and A['Seagate Technology']['amount'] == 2000, A['Seagate Technology'])
ok('no RSI take-profit: an overbought holding in profit is held', A['Alphabet A']['action'] == 'HOLD', (A['Alphabet A']['action'], A['Alphabet A']['reasons'][0][:60]))
ok('pullback in an uptrend in a group under target -> ADD', A['Microsoft']['action'] == 'ADD' and A['Microsoft']['rule'] in ('pullback',), (A['Microsoft']['action'], A['Microsoft']['rule']))
ok('energy: SMA(50) below SMA(200) -> regime exit', A['Chevron']['action'] == 'TRIM' and A['Chevron']['rule'] == 'regime_exit', A['Chevron']['rule'])
ok('tiny position -> CONSOLIDATE', A['Coca-Cola']['action'] == 'CONSOLIDATE', A['Coca-Cola']['action'])
ok('index funds get new money from the deposit plan', A['Nordnet USA Index']['action'] == 'ADD' and A['Nordnet USA Index']['amount'] > 0, A['Nordnet USA Index'])
P = r['plan']
ok('plan: the deposit plan spends the monthly deposit', sum(x['amount'] for x in P['deposit_plan']) == 10000, P['deposit_plan'])
ok('plan: categories carry target, status and weekly trend counts', all({'key', 'pct', 'target', 'status', 'n_up'} <= set(c) for c in P['categories']))
ok('plan: AI chain over target, core under target', {c['key']: c['status'] for c in P['categories']}['ai'] == 'over' and {c['key']: c['status'] for c in P['categories']}['core'] == 'under')
ok('plan: five strategy-fit ratings 0-10', len(P['fit']) == 5 and all(0 <= f['score'] <= 10 for f in P['fit']))
ok('plan: stress test for today and target', set(P['stress']['now']) == set(P['stress']['target']) == set(strategy.STRESS))
ok('counts have no TRIMWATCH any more', 'TRIMWATCH' not in r['summary']['counts'], r['summary']['counts'])
ok('every action has a reason', all(v['reasons'] for v in r['assets'].values()))
r2 = advisor.advise(payload, None, 'aggressive', {'deposit': 10000, 'reduce': 15000, 'opportunity_pct': 5})
ok('aggressive has a higher AI target than balanced', {c['key']: c['target'] for c in r2['plan']['categories']}['ai'] > {c['key']: c['target'] for c in P['categories']}['ai'])
print(f'{sum(res)}/{len(res)} passed')
sys.exit(0 if all(res) else 1)
