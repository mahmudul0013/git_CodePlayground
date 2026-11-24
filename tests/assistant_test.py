"""Assistant check:  python tests/assistant_test.py   (no network: prices, symbols and sectors are made up here)

The plan advice is built by the real advisor.advise() on a made-up portfolio (the same way as tests/advisor_rules_test.py), the
analytics payload is a small made-up one. Every question must pick the expected intent and its answer must contain the figures
recomputed here from that payload / advice with the assistant's own number format. Old questions are in the list too, so a new
keyword cannot steal them."""
import math
import os
import sys
import time
from datetime import date, timedelta

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import advisor, assistant, sectors, symbols   # noqa: E402

res = []


def ok(name, cond, detail=''):
    res.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + str(detail)[:220]) if detail else ''))


kr, pc, n_, num = assistant.kr, assistant.pc, assistant._n, assistant.num


def one(r):
    return r['answer'].replace('\n', ' | ')

# ───── made-up daily histories: weekdays only, ending on the last Friday (as in advisor_rules_test) ─────
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
        elif kind == 'pullback':
            v *= 1.004 if i < N - 15 else 0.993
        elif kind == 'down':
            v *= 1.003 if i < 200 else 0.991
        c.append(round(v, 4))
    return {'at': time.time(), 'd': days(), 'c': c, 'ccy': 'SEK'}


H = {'RISE': series('rise'), 'PULL': series('pullback'), 'DOWN': series('down')}
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
           'unrealized_pct': a[4], 'realized': 100 if a[4] > 0 else -50, 'fees': 40, 'sells': 1, 'buys': 3, 'gav': 50.0, 'price': 55.0,
           'total_pnl': a[3] * a[4] / 100 + (100 if a[4] > 0 else -50)} for a in ASSETS]
assets.append({'isin': 'US0000000099', 'name': 'Strategy A', 'type': 'Stock', 'ccy': 'USD', 'held': False, 'value': 0, 'unrealized': None, 'realized': -234,
               'fees': 30, 'sells': 5, 'buys': 5, 'total_pnl': -234})
holdings = sum(a[3] for a in ASSETS)
cash = 500.0
total = holdings + cash
recent = (date.today() - timedelta(days=5)).isoformat()
trades = [{'isin': 'US0000000001', 'date': recent, 'side': 'BUY', 'qty': 1, 'price': 90.0, 'ccy': 'SEK', 'fee': 9},
          {'isin': 'US0000000002', 'date': recent, 'side': 'SELL', 'qty': 2, 'price': 120.0, 'ccy': 'SEK', 'fee': 9},
          {'isin': 'US0000000006', 'date': '2025-01-10', 'side': 'BUY', 'qty': 5, 'price': 40.0, 'ccy': 'SEK', 'fee': 39}]
nd = 79700.0                                 # result -3 000 kr: the AI chain lost more than half of it ("one bet")
pnl = total - nd
ser = []                                     # daily value series: a peak, then deposits on the way down (timing) and a 25% time-weighted fall
for i in range(40):
    dep = 40000 + i * 1000
    val = dep * (1.10 if i == 15 else 1.0 + 0.004 * min(i, 15) - 0.006 * max(0, i - 15))
    ser.append({'date': (date(2026, 1, 1) + timedelta(days=i)).isoformat(), 'value': round(val), 'net_deposited': dep,
                'index': 100 + 20 * min(i, 15) / 15 - 30 * max(0, i - 15) / 24})
ser[-1].update(value=round(total), net_deposited=nd)
payload = {
    'generated': 'test', 'assets': assets, 'trades': trades,
    'vol': {'US0000000001': {'daily': 4.2, 'annual': 66.7, 'avg_abs': 3.1, 'days': 63}, 'SE0000000011': {'daily': 0.9, 'annual': 14.3, 'avg_abs': 0.7, 'days': 63}},
    'nav': {'nav': total, 'net_deposits': nd, 'first_date': '2025-06-20', 'from_high_pct': -21.37,
            'ranges': {'ytd': {'twr_pct': -7.61}, '1m': {'twr_pct': -9.29}, 'max': {'twr_pct': -9.17, 'max_drop_pct': -26.13}}},
    'insights': {
        'overview': {'cash_balance': cash, 'total_value': total, 'holdings_value': holdings, 'all_time_pnl': pnl, 'all_time_pnl_pct': pnl / nd * 100,
                     'net_deposits': nd, 'deposits': nd + 100, 'withdrawals': 100, 'deposit_count': 30, 'trades': 640, 'buys': 400, 'sells': 240,
                     'realized': 1200.0, 'unrealized': -2795.0, 'held_assets': len(ASSETS), 'distinct_assets': len(ASSETS) + 1, 'first_date': '2025-06-20',
                     'last_date': '2026-11-20', 'days_span': 518, 'active_days': 200, 'turnover': 950000},
        'costs': {'broker_total': 4200.0, 'courtage': 4000.0, 'fx_fees': 200.0, 'paid_trades': 600, 'avg_fee_per_paid_trade': 6.7, 'pct_of_net_deposits': 4.6,
                  'fee_vs_realized_gross': 120.0},
        'sell_quality': {'realized_before_fees': 3500.0, 'realized_net': 1200.0, 'avg_hold_days': 40, 'median_hold_days': 12, 'sold_within_7d': 80, 'sells': 240,
                         'win_rate': 55.0, 'avg_win': 300.0, 'avg_loss': -250.0, 'profit_factor': 1.32, 'gross_wins': 9000.0, 'gross_losses': 6800.0},
        'split_orders': {'extra_orders': 45, 'groups': 30, 'avoidable_fees': 640.0},
        'dividends': {'summary': {'net': 880.0, 'gross': 1000.0, 'tax': 120.0, 'tax_pct': 12.0, 'payers': 6, 'ttm_net': 700.0, 'avg_month': 58.0,
                                  'by_year': {'2025': 300.0, '2026': 580.0}, 'top3_share': 70.0}, 'payers': [], 'series': []},
        'deposit_behavior': {'series': ser, 'summary': {'avg_deposit': 3000, 'median_gap_days': 14}},
    },
}
adv = advisor.advise(payload, None, 'balanced', {'deposit': 10000, 'reduce': 15000, 'opportunity_pct': 5})
ok('advice built from the made-up portfolio', adv.get('ok') and adv.get('plan'), adv.get('error'))

# trend states the made-up histories cannot produce on every weekday: set them on the advice, as the weekly rule would
A = {v['name']: (i, v) for i, v in adv['assets'].items()}
A['Seagate Technology'][1]['metrics'].update(wk_weeks=1)                                  # fell below SMA(200) at the last weekly close
A['NVIDIA'][1]['metrics'].update(live_up=False, live_dist=-0.01)                          # today below, last weekly close above: may flip Friday
A['Alfa Laval'][1]['metrics'].update(wk_flips12=4)                                         # choppy
L, S = adv['plan'], adv['summary']
cats = {c['key']: c for c in L['categories']}
life = L['lifetime']
sells = L['sells_now']
ov = payload['insights']['overview']
rows = [v for v in adv['assets'].values() if not v.get('closed') and (v.get('metrics') or {}).get('wk_up') is not None]
up = [v for v in rows if v['metrics']['wk_up']]
rules = {c['key']: c['rule'] for c in L['categories']}
half = [v for v in adv['assets'].values() if not v.get('closed') and rules[v['category']] == 'half_trend']
mu = A['Micron Technology'][1]
idx = [x['index'] for x in ser]
dd = (idx[-1] / max(idx) - 1) * 100
months = round((date(2026, 11, 20) - date(2025, 6, 20)).days / 30.44)
fit = {f['key']: f for f in L['fit']}
T = L['transition']
dep_core = next(x for x in L['deposit_plan'] if x['cat'] == 'core')

CASES = [   # question, intent id, figures the answer must contain
    # ── the plan (new) ──
    ('What is the short verdict?', 'verdict', [kr(pnl, True), pc(pnl / nd * 100, 1, True), kr(nd), kr(-life['ai']['life']), kr(pnl - life['ai']['life'], True), n_(640), f'{months} months', kr(4200), kr(3500)]),
    ('Why am I losing money?', 'verdict', [kr(pnl, True), kr(-life['ai']['life'])]),
    ('Where was the money lost?', 'lifetime', [kr(life['ai']['life'], True)]),
    ('How much did I lose in AI?', 'lifetime', [kr(life['ai']['life'], True), kr(life['ai']['unreal'], True), kr(life['ai']['realized'], True), kr(life['ai']['fees'])]),
    ('What are my category targets?', 'cat_targets', [pc(cats['ai']['pct']), 'index 50', 'AI 15', 'cash 5']),
    ('What is my target mix?', 'cat_targets', ['Balanced targets']),
    ('Is my AI share too high?', 'category', ['Yes.', pc(cats['ai']['pct']), pc(cats['ai']['target'], 0), kr(cats['ai']['kr']), f"{cats['ai']['n_up']} of {cats['ai']['n_trend']}"]),
    ('How much healthcare do I have?', 'category', [pc(cats['health']['pct']), kr(cats['health']['kr'])]),
    ('What is the core?', 'category', [pc(cats['core']['pct']), pc(cats['core']['target'], 0)]),
    ('Which profile is active?', 'profiles', ['Balanced', '60/10/35', '50/15/40', '40/22/45']),
    ('What does the aggressive profile change?', 'profiles', ['Aggressive would set index funds 40%']),
    # the split is a share of every deposit (as on the Plan tab); an amount in the question is split by those shares
    ('Where does my next deposit go?', 'deposit_plan', ['Each deposit:'] + [f"{x['pct']}%" for x in L['deposit_plan']] + [f"{w['pct']}%" for w in dep_core['where']]),
    ('Where does my next 10 000 kr go?', 'deposit_plan', [kr(10000)] + [kr(10000 * x['pct'] / 100) for x in L['deposit_plan']]),
    ('Where does my next 20 000 kr go?', 'deposit_plan', [kr(20000)] + [kr(20000 * x['pct'] / 100) for x in L['deposit_plan']]),
    ('What should I sell this month?', 'trim_list', [str(len(sells)), kr(sum(x['amount'] for x in sells)), kr(max(x['amount'] for x in sells))]),
    ('What sales are due?', 'trim_list', [kr(sum(x['amount'] for x in sells))]),
    ('Why sell Micron?', 'asset_advice', [kr(mu['amount']), 'size cap']),
    ('What are queued sales?', 'queued', [f"{L['queued']} queued" if L['queued'] else 'Nothing is queued', kr(15000)]),
    ('Which holdings crossed SMA(200) this week?', 'signals_week', ['Seagate Technology', '1 fell below']),
    ('Which holdings may change on Friday?', 'signals_friday', ['NVIDIA (now below)']),
    ('Which holdings are choppy?', 'signals_choppy', ['Alfa Laval (4x)']),
    ('What are trend signals?', 'trend_signals', [f'{len(up)} above', f'{len(rows) - len(up)} below', '1 changed this week', '1 may change Friday', '1 choppy']),
    ('What is the weekly close rule?', 'weekly_rule', ['trend-half sales']),
    ('What is hold half vs trend half?', 'hold_half', [f"{sum(1 for v in half if v['keep'])} hold half", f"{sum(1 for v in half if not v['keep'])} trend half"]),
    ('Is Micron in an uptrend?', 'asset_trend', ['uptrend' if mu['metrics']['wk_up'] else 'downtrend', pc(mu['metrics']['wk_dist'] * 100, 0, True), mu['metrics']['wk_since']]),
    ('Which category is Seagate in?', 'asset_category', ['AI and semiconductor chain', 'trend half']),
    ('How volatile is Micron?', 'asset_vol', ['4,2% a day', '67%']),
    ('What is Vol 3M?', 'vol3m', ['Micron Technology 4,2%']),
    ('What is opportunity cash?', 'opp_cash', [kr(L['cash']), kr(L['targets']['cash'] / 100 * L['total'])]),
    ('What should I do if the market crashes?', 'panic', [pc(-21.37, 1), 'growth curve', 'step 2']),   # the growth curve, not the estimate
    ('What is my trading budget?', 'trading_budget', [f"{L['trading']['trades_30d']} trades", kr(L['trading']['fees_30d']), kr(L['trading']['fee_budget_year'])]),
    ('How many trades this month?', 'trading_budget', [f"{L['trading']['trades_30d']} trades"]),
    ('How much did I pay in fees the last 30 days?', 'trading_budget', [kr(L['trading']['fees_30d'])]),
    ('How well do I follow index investing?', 'strategy_fit', [f"{fit['index']['score']} of 10"]),
    ('How well do I follow the popular strategies?', 'strategy_fit', [f"index saving {fit['index']['score']}", f"momentum {fit['momentum']['score']}"]),
    ('What is the stress test?', 'stress', [pc(v, 1, True) for v in L['stress']['now'].values()]),
    ('How long until I am on target?', 'transition', [f"about {T['months_to_band']} months" if T['months_to_band'] is not None else 'not within']),
    ('Which rule works per category?', 'evidence', ['Plan & advice']),
    ('What is trend health?', 'trend_health', [pc(L['up_pct'], 0)]),
    ('What are the general rules?', 'general_rules', ['no averaging down']),
    ('How do I switch to dark mode?', 'theme_help', ['sun / moon']),
    ('Where do I find the trend signals?', 'where_ui', ['left sidebar']),
    ('What is RSI?', 'rsi', [f"below {L['rsi_add']}", 'no RSI take-profit']),
    ('What is the 200-day average?', 'sma200', ['SMA(200)', 'weekly close']),
    ('What does TRIM mean?', 'trim_rule', ['Never on RSI']),
    ('What is the sector cap?', 'sector_cap', [kr(15000)]),
    # ── older questions that must keep their answers ──
    ('What does split orders mean?', 'split_orders', ['45 extra orders', kr(640)]),
    ('What are my total fees?', 'fees_total', [kr(4200)]),
    ('How much did I pay in fees?', 'fees_total', [kr(4200)]),
    ('What is my all-time result?', 'all_time', [kr(pnl, True)]),
    ('What is the result on deposits?', 'all_time', [kr(pnl, True)]),
    ('How much have I deposited?', 'net_deposits', [kr(nd)]),
    ('How many trades have I made?', 'trade_counts', ['640 trades']),
    ('Which asset lost me the most?', 'worst_realised', ['Micron Technology']),
    ('Which is my biggest holding?', 'biggest_holding', ['Nordnet USA Index']),
    ('How much cash do I have?', 'cash', [kr(cash)]),
    ('What is my account value?', 'account_value', [kr(total)]),
    ('How risky is my portfolio?', 'risk_summary', []),
    ('What is my plan this month?', 'month_plan', ['Each deposit:', f"{L['deposit_plan'][0]['pct']}%", f'{len(sells)} ('] ),
    ('Should I average down?', 'average_down', ['trap']),
    ('What does WATCH mean?', 'watch_idea', ['close to an entry']),
    ('How much has my portfolio grown this year?', 'nav_growth', ['-7,6%']),
    ('Will Micron go up tomorrow?', 'forecast', ["can't predict"]),
    ('How is Micron doing?', 'asset_summary', [kr(9000)]),
    ('How is Strategy A doing?', 'asset_summary', ['Strategy A', 'closed position']),
    ('How much do I own of ASML?', 'asset_value', [kr(2900)]),
    ('Which stocks should I add?', 'add_list', ['Buy ideas']),
    ('What is my win rate?', 'win_rate', ['55,0%']),
    ('Hello', 'greeting', []),
]
for q, iid, want in CASES:
    r = assistant.answer(q, payload, adv)
    got = (r['matched'] or '').split(' ')[0]
    miss = [w for w in want if w not in r['answer']]
    broken = any(s in r['answer'] for s in ("I couldn't", "I don't have", "can't answer"))
    ok(f'{q} -> {iid}', got == iid and not miss and not broken and r['confidence'] >= 0.5,
       f"got {got} {r['confidence']}" + (f' missing {miss}' if miss else '') + ' | ' + r['answer'].replace('\n', ' | '))
    lines = r['answer'].split('\n')
    if len(lines) > 2 or len(r['answer']) > assistant.MAX_ANSWER:
        ok(f'{q}: at most two lines, {assistant.MAX_ANSWER} characters', False, r['answer'])

# plan words are never read as a company: "strategies" is not Strategy A, "investing" not an Investor holding
for q in ('How well do I follow the popular strategies?', 'What are the general rules?', 'How much energy and materials do I have?'):
    r = assistant.answer(q, payload, adv)
    ok(f'no asset matched in "{q}"', '·' not in (r['matched'] or ''), r['matched'])

# the 10-year evidence is used when the caller passes it, and the answer says where it is computed when not
ev = {'ok': True, 'pending': False, 'categories': {'ai': {'n': 6, 'start': '2017-09-05', 'pick': 'HALFW', 'rules': {
    'BH': {'cagr': 34.0, 'mdd': -42.5}, 'HALFW': {'cagr': 28.9, 'mdd': -36.1}, 'T200W': {'cagr': 20.0, 'mdd': -30.0}}}}}
r = assistant.answer('Which rule works for AI?', dict(payload, evidence=ev), adv)
ok('evidence per category from the 10-year test', r['matched'] == 'evidence' and '28,9%' in r['answer'] and '-36%' in r['answer'] and '34,0%' in r['answer'], one(r))
r = assistant.answer('Which rule works for AI?', payload, adv)
ok('evidence without the test says where it is computed', 'Plan & advice' in r['answer'], one(r))

# missing advice: a clear "not in your data" sentence, never an exception or a made-up figure
r = assistant.answer('What is the short verdict?', payload, None)
ok('no advice -> says the figure is missing', "I don't have" in r['answer'], r['answer'])
r = assistant.answer('Which holdings crossed SMA(200) this week?', payload, {'ok': False, 'error': 'no holdings'})
ok('failed advice -> says the figure is missing', "I don't have" in r['answer'], r['answer'])

# amounts named in a question
ok('deposit shares add up to 100% (category and funds within it)', sum(x['pct'] for x in L['deposit_plan']) == 100 and sum(w['pct'] for w in dep_core['where']) == dep_core['pct'],
   [(x['cat'], x['pct'], [w['pct'] for w in x.get('where') or []]) for x in L['deposit_plan']])
ok('amount parsing', [assistant._amount(s) for s in ('next 10 000 kr', '10000', '15k', 'sma 200 this week', '2 500 kr')] == [10000, 10000, 15000, None, 2500])

# the sell list uses the Plan tab's rounding: RSI 45.1 reads "RSI 45: wait for a bounce"
ok_now = sum(1 for x in sells if x['rsi'] is None or math.floor(x['rsi'] + 0.5) > 45)
r = assistant.answer('What should I sell this month?', payload, adv)
ok('sales OK today counted like the Plan tab', f'{ok_now} OK today' in r['answer'], one(r))

print(f'{sum(res)}/{len(res)} passed')
sys.exit(0 if all(res) else 1)
