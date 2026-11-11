"""Logic check of nav.py with a tiny synthetic world (no network, no files): run   python tests/nav_math_test.py
Proves: NAV = holdings + cash; a deposit is never growth; +10% on a holding that is 25% of the account = +2.5% total;
category growth ignores buys / sells; a split without a trade does not create growth; a wrong Yahoo symbol is rejected."""
import os, sys
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the project folder
sys.path.insert(0, PROJ); os.chdir(PROJ)
from datetime import date, timedelta
import nav, symbols, sectors
res = []
def ok(n, c, d=''):
    res.append(c); print(('PASS ' if c else 'FAIL ') + n + ('  ' + str(d)[:150] if d else ''))

# --- synthetic world: 12 weekdays, one SEK stock "AAA" (Technology) and one "BBB" (Energy)
days = nav._weekdays(date(2026, 1, 5), date(2026, 1, 20))          # Mon 5 Jan .. Tue 20 Jan
price_aaa = {d: 100.0 for d in days}
for d in days[6:]: price_aaa[d] = 110.0                              # +10% on the 7th day, stays
price_bbb = {d: 50.0 for d in days}
hist = {'AAA.ST': {'at': 1e12, 'p1': 0, 'ccy': 'SEK', 'd': days, 'c': [price_aaa[d] for d in days]},
        'BBB.ST': {'at': 1e12, 'p1': 0, 'ccy': 'SEK', 'd': days, 'c': [price_bbb[d] for d in days]}}
nav._histories = lambda syms, p1, budget, fetch=True: ({s: hist[s] for s in syms if s in hist}, 0)
symbols.resolve = lambda isin, name, ccy: {'symbol': {'A': 'AAA.ST', 'B': 'BBB.ST'}[isin]}
sectors.batch = lambda items, budget=0: ({'A': {'sector': 'Technology'}, 'B': {'sector': 'Energy'}}, 0)

def trade(d, isin, side, qty, price):
    return {'id': d + isin, 'date': d, 'isin': isin, 'side': side, 'qty': qty, 'price': price, 'ccy': 'SEK', 'gross': qty * price, 'amount': qty * price, 'fee': 0}
# day0: deposit 10 000, buy 50 AAA @100 (=5000).  day3: deposit 10 000 more, buy 100 BBB @50 (=5000).  AAA +10% on day 6.
trades = [dict(trade(days[0], 'A', 'BUY', 50, 100), pos_after=50), dict(trade(days[3], 'B', 'BUY', 100, 50), pos_after=100)]
series, cash, nd = [], 0.0, 0.0
for k, d in enumerate(days):
    if k == 0: nd += 10000; cash += 10000 - 5000
    if k == 3: nd += 10000; cash += 10000 - 5000
    series.append({'date': d, 'cash': cash, 'net_deposited': nd})
payload = {'insights': {'deposit_behavior': {'series': series}, 'overview': {'total_value': 1}}, 'trades': trades,
           'assets': [{'isin': 'A', 'name': 'AAA', 'ccy': 'SEK', 'type': 'Stock', 'held': True, 'qty': 50, 'value': 5500}, {'isin': 'B', 'name': 'BBB', 'ccy': 'SEK', 'type': 'Stock', 'held': True, 'qty': 100, 'value': 5000}],
           'sources': {}}
d = nav.curve(payload, today=date(2026, 1, 20), budget=1)
ok('curve builds', d['ok'], d.get('error'))
nv, tw = d['total']['nav'], d['total']['twr']
ok('NAV = holdings + cash every day', all(abs(nv[k] - (sum(c['value'][k] for c in d['categories'].values()) + d['total']['cash'][k])) < 0.01 for k in range(len(nv))))
ok('day 0: NAV 10 000 (5 000 shares + 5 000 cash)', abs(nv[0] - 10000) < 0.01, nv[0])
ok('second deposit raises NAV by 10 000 but NOT the growth index', abs(nv[3] - 20000) < 0.01 and abs(tw[3] - 100) < 1e-6, (nv[3], tw[3]))
# day 6: AAA 50 sh x 10 = +500 on NAV 20 000 -> +2.5% total, category AAA +10%
ok('stock +10% with 25% of NAV in it = +2.5% total growth', abs(tw[6] / tw[5] - 1 - 0.025) < 1e-6, round(tw[6] / tw[5] - 1, 6))
ok('Technology category growth +10%, Energy 0%', abs(d['categories']['Technology']['twr'][6] / d['categories']['Technology']['twr'][5] - 1 - 0.10) < 1e-6 and abs(d['categories']['Energy']['twr'][-1] - 100) < 1e-6)
ok('Energy category starts on the day it was bought', d['categories']['Energy']['first'] == 3 and d['categories']['Energy']['value'][2] == 0)
ok('buying shares is not growth in the category either (Technology index flat before day 6)', all(abs(x - 100) < 1e-6 for x in d['categories']['Technology']['twr'][:6]))
ok('final value matches', abs(nv[-1] - 20500) < 0.01, nv[-1])
ok('summary ranges present', set(d['summary']['ranges']) == {'1w', '1m', '3m', 'ytd', '1y', '3y', 'max'} and d['summary']['ranges']['max']['twr_pct'] > 2.4)

# --- a 2:1 split without a trade: Yahoo's history is split adjusted, our trade price is the old price
days2 = nav._weekdays(date(2026, 1, 5), date(2026, 1, 16))
adj = {d: 50.0 for d in days2}                                       # adjusted close (after the split the real price is 50, before it was 100)
hist2 = {'AAA.ST': {'at': 1e12, 'p1': 0, 'ccy': 'SEK', 'd': days2, 'c': [adj[d] for d in days2]}}
nav._histories = lambda syms, p1, budget, fetch=True: ({s: hist2[s] for s in syms if s in hist2}, 0)
t2 = [dict(trade(days2[0], 'A', 'BUY', 50, 100), pos_after=50)]       # bought 50 @100 before the split; ledger later shows 100 shares
s2 = [{'date': d, 'cash': 5000, 'net_deposited': 10000} for d in days2]
p2 = {'insights': {'deposit_behavior': {'series': s2}, 'overview': {}}, 'trades': t2, 'assets': [{'isin': 'A', 'name': 'AAA', 'ccy': 'SEK', 'type': 'Stock', 'held': False, 'qty': 0, 'value': 0}], 'sources': {}}
d2 = nav.curve(p2, today=date(2026, 1, 16), budget=1)
ok('split detected: 50 shares bought at 100 are valued at 5 000, not 2 500', abs(d2['total']['nav'][0] - 10000) < 0.01 and 'AAA' in d2['coverage']['split_fixed'], (d2['total']['nav'][0], d2['coverage']['split_fixed']))
ok('a split does not create fake growth', all(abs(x - 100) < 1e-6 for x in d2['total']['twr']))

# --- a symbol that is another instrument (6x too expensive) is rejected and the asset uses your trade prices
hist3 = {'AAA.ST': {'at': 1e12, 'p1': 0, 'ccy': 'SEK', 'd': days2, 'c': [600.0 for _ in days2]}}
nav._histories = lambda syms, p1, budget, fetch=True: ({s: hist3[s] for s in syms if s in hist3}, 0)
d3 = nav.curve(p2, today=date(2026, 1, 16), budget=1)
ok('wrong symbol (6x the price you paid) is rejected, value stays at your price', 'AAA' in d3['coverage']['symbol_rejected'] and abs(d3['total']['nav'][0] - 10000) < 0.01, d3['coverage']['symbol_rejected'])
print(f'{sum(res)}/{len(res)} passed')
