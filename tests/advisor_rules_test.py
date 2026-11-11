"""Rule check of advisor.py with made-up price histories (no network, no files): run   python tests/advisor_rules_test.py
Proves: buy only when RSI(14) is below the profile's buy level AND the price is in an uptrend (no falling knives); the profiles differ by
5 RSI points; an overbought holding in profit gets a take-profit idea (a third of it), one at a loss does not."""
import os
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import advisor, sectors, symbols   # noqa: E402

res = []


def ok(name, cond, detail=''):
    res.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + str(detail)[:140]) if detail else ''))


# ---- entry test on feature dictionaries
base = {'trend': 'up', 'rsi': 33.0, 'dd52': -0.12, 'mom12_1': 0.3}
P = advisor.PROFILES
ok('profiles differ by 5 RSI points (buy 30 / 35 / 40, take profit 80 / 75 / 70)',
   (P['conservative']['rsi_buy'], P['balanced']['rsi_buy'], P['aggressive']['rsi_buy']) == (30, 35, 40)
   and (P['conservative']['rsi_sell'], P['balanced']['rsi_sell'], P['aggressive']['rsi_sell']) == (80, 75, 70))
ok('balanced buys at RSI 33 in an uptrend', advisor._entry_ok(dict(base), P['balanced']))
ok('balanced does NOT buy at RSI 37 (needs below 35)', not advisor._entry_ok(dict(base, rsi=37.0), P['balanced']))
ok('aggressive buys at RSI 37 (below 40)', advisor._entry_ok(dict(base, rsi=37.0), P['aggressive']))
ok('conservative does NOT buy at RSI 33 (needs below 30)', not advisor._entry_ok(dict(base), P['conservative']))
ok('conservative buys at RSI 28', advisor._entry_ok(dict(base, rsi=28.0), P['conservative']))
ok('no buy below the 200-day average, even at RSI 20 (falling knife)', not advisor._entry_ok(dict(base, trend='down', rsi=20.0), P['balanced']))
ok('aggressive accepts a mixed trend, balanced does not', advisor._entry_ok(dict(base, trend='mixed'), P['aggressive']) and not advisor._entry_ok(dict(base, trend='mixed'), P['balanced']))
ok('no buy when it has not pulled back at all (within 5% of the high)', not advisor._entry_ok(dict(base, dd52=-0.02), P['balanced']))
ok('no buy after a crash beyond the allowed pullback (balanced 40%, aggressive 60%)', not advisor._entry_ok(dict(base, dd52=-0.45), P['balanced']) and advisor._entry_ok(dict(base, dd52=-0.45), P['aggressive']) and advisor._entry_ok(dict(base, dd52=-0.30), P['balanced']))
ok('WATCH band: RSI 35-45 is close to a signal, not a signal', advisor._entry_ok(dict(base, rsi=40.0), P['balanced'], watch=True) and not advisor._entry_ok(dict(base, rsi=40.0), P['balanced']) and not advisor._entry_ok(dict(base, rsi=33.0), P['balanced'], watch=True) and not advisor._entry_ok(dict(base, rsi=48.0), P['balanced'], watch=True))
ok('WATCH never applies below the 200-day average', not advisor._entry_ok(dict(base, rsi=40.0, trend='down'), P['balanced'], watch=True))
ok('missing RSI never buys', not advisor._entry_ok(dict(base, rsi=None), P['balanced']))

# ---- end to end on a made-up portfolio
N = 260
def series(first, daily, days_a, daily_b, days_b):
    c, v = [], first
    for i in range(N):
        v *= 1 + (daily if i < N - days_b else daily_b)
        c.append(round(v, 4))
    return c
hist = {
    'AAA.ST': series(100, 0.004, 0, 0.025, 15),        # long rise, then 15 hot days: overbought, in profit
    'BBB.ST': series(100, 0.003, 0, -0.015, 15),       # long rise, then 15 down days: oversold pullback inside an uptrend
    'CCC.ST': series(100, -0.003, 0, -0.015, 15),      # long decline, then more: oversold but BELOW the 200-day average
    'LOS.ST': series(100, 0.004, 0, 0.025, 15),        # overbought like AAA but the position is at a loss
}
now = time.time()
for s in hist:
    hist[s] = {'at': now, 'c': hist[s], 'd': list(range(N)), 'ccy': 'SEK'}
sym_of = {'A': 'AAA.ST', 'B': 'BBB.ST', 'C': 'CCC.ST', 'L': 'LOS.ST'}
advisor._histories = lambda syms, budget=45: {s: hist[s] for s in syms if s in hist}
symbols.resolve = lambda isin, name, ccy: {'symbol': sym_of[isin]} if isin in sym_of else None
sectors.batch = lambda items, budget=0: ({}, 0)

def asset(isin, name, value, unreal_pct):
    return {'isin': isin, 'name': name, 'ccy': 'SEK', 'type': 'Stock', 'held': True, 'qty': 10, 'price': value / 10, 'value': value,
            'unrealized': value * unreal_pct / 100, 'unrealized_pct': unreal_pct, 'sells': 0}
assets = [asset('A', 'Alpha', 9000, 80), asset('B', 'Beta', 2500, -5), asset('C', 'Gamma', 2500, -30), asset('L', 'Lossy', 9000, -20)]
assets += [dict(asset(f'F{i}', f'Filler {i}', 8000, 5)) for i in range(40)]
# a tiny oversold holding in an uptrend must be a top-up (ADD), not 'consolidate'; a holding with RSI 36-44 in an uptrend is WATCH
def find_series(lo, hi):
    # a rise, then a choppy decline (down days bigger than up days): RSI in the middle band, price still above its 200-day average
    for up, down in ((0.009, -0.014), (0.008, -0.013), (0.01, -0.016), (0.007, -0.012)):
        c, v = [], 100.0
        for i in range(N):
            if i < N - 30:
                v *= 1.003
            else:
                v *= 1 + (up if (i % 2 == 0) else down)
            c.append(round(v, 4))
        f = advisor._features(c)
        if lo < f['rsi'] < hi and f['trend'] == 'up' and f['dd52'] <= -0.06:
            return c
    raise SystemExit('no test series with RSI in %s-%s' % (lo, hi))
hist['TNY.ST'] = {'at': now, 'c': series(100, 0.003, 0, -0.015, 15), 'd': list(range(N)), 'ccy': 'SEK'}
hist['WCH.ST'] = {'at': now, 'c': find_series(36, 44), 'd': list(range(N)), 'ccy': 'SEK'}
sym_of.update({'T': 'TNY.ST', 'W': 'WCH.ST'})
assets += [asset('T', 'Tiny', 300, -2), asset('W', 'Watchme', 2500, 3)]
payload = {'assets': assets, 'trades': [], 'insights': {}, 'generated': 'x'}
r = advisor.advise(payload, None, 'balanced')
A = r['assets']
ok('overbought holding in profit -> TRIM take-profit of about a third', A['A']['action'] == 'TRIM' and 2500 <= A['A']['amount'] <= 3500 and 'RSI(14)' in A['A']['reasons'][0], (A['A']['action'], A['A']['amount']))
ok('overbought holding at a loss -> no take-profit', A['L']['action'] != 'TRIM', A['L']['action'])
ok('oversold pullback in an uptrend, small weight -> ADD (balanced)', A['B']['action'] == 'ADD' and 'RSI(14)' in A['B']['reasons'][0], (A['B']['action'], A['B']['reasons'][0][:70]))
ok('oversold but below the 200-day average -> no ADD', A['C']['action'] != 'ADD', A['C']['action'])
ok('tiny oversold holding in an uptrend -> ADD (top-up), not CONSOLIDATE', A['T']['action'] == 'ADD' and 'tops it up' in A['T']['reasons'][0], (A['T']['action'], A['T']['reasons'][0][-60:]))
ok('RSI 36-44 in an uptrend, small weight -> WATCH with the level to wait for', A['W']['action'] == 'WATCH' and 'Wait for the RSI to dip below 35' in A['W']['reasons'][0], (A['W']['action'], A['W']['reasons'][0][:80]))
ok('counts include WATCH', r['summary']['counts'].get('WATCH', 0) >= 1, r['summary']['counts'])
r2 = advisor.advise(payload, None, 'conservative')
ok('conservative also finds the deeply oversold pullback', r2['assets']['B']['action'] == 'ADD')
r3 = advisor.advise(payload, None, 'aggressive')
ok('aggressive take-profit also fires on the hot holding', r3['assets']['A']['action'] == 'TRIM')
print(f'{sum(res)}/{len(res)} passed')
sys.exit(0 if all(res) else 1)
