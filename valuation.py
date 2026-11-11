"""
valuation.py - the ONE place where the portfolio is valued. Python stdlib only.

Every page, tile, table, chart, the advice weights, the heat map, the growth curve and the chat read the numbers built here, so
the same thing can never show two different values. The browser does no pricing of its own.

Definitions (these names and meanings are used on every page):
  Holdings value   = sum of shares x price of the holdings today, in kr
  Account value    = Holdings value + cash balance of the ledger (also called net asset value, NAV)
  Unrealised       = Holdings value - what the current holdings cost (cost = Nordnet export value - Nordnet export return)
  All-time result  = Account value - net deposits (all money in minus money out; includes dividends, fees, realised and unrealised)
  Growth (TWR)     = time-weighted return of the account: deposits are never growth (see nav.py)
  Today's P&L      = sum of (value - value / (1 + today's change)) over the holdings, i.e. the change measured on yesterday's value

Price used per holding: the live Yahoo price when it is in the same currency as the Nordnet export and within 0.5x-2x of the
export price (otherwise the symbol is another instrument or listing and is ignored); funds and unmatched symbols keep the
Nordnet export value. Value = export value x (live price / export price), so currency conversion is the export's own.

TOLERANCE: numbers that come from the same snapshot are identical. A check between two DIFFERENT routes to the same quantity
(for example the growth curve rebuilt from daily closes and the snapshot) may differ by rounding and FX; that is accepted
up to max(5 kr, 0.05% of the figure). tests/consistency_test.py enforces it.
"""
import re

TOLERANCE_KR = 5.0
TOLERANCE_REL = 0.0005


def allowed(x):
    """Largest accepted difference for a figure of size x."""
    return max(TOLERANCE_KR, TOLERANCE_REL * abs(x))


def agree(a, b):
    return a is not None and b is not None and abs(a - b) <= allowed(max(abs(a), abs(b)))


def _export_date(payload):
    f = (((payload.get('sources') or {}).get('holdings')) or {}).get('file') or ''
    m = re.search(r'\d{4}-\d{2}-\d{2}', f)
    return m.group(0) if m else None


def snapshot(payload, quotes=None, now=None):
    """Value the holdings of `payload` (one user's analytics payload) with the live `quotes` {isin: {price, currency, change_pct, symbol}}.
    -> {ok, asof, export_date, assets: {isin: {...}}, totals: {...}}"""
    quotes = quotes or {}
    ov = (payload.get('insights') or {}).get('overview') or {}
    assets, live_n = {}, 0
    for a in payload.get('assets') or []:
        if not (a.get('held') and a.get('value') and a.get('isin')):
            continue
        v_exp = float(a['value'])
        cost = v_exp - float(a.get('unrealized') or 0.0)
        price, day, live, symbol = a.get('price'), a.get('day_pct'), False, None
        v = v_exp
        q = quotes.get(a['isin'])
        if q and q.get('price') and a.get('price') and not str(q.get('symbol') or '').startswith('0P') \
                and str(q.get('currency') or '').upper() == str(a.get('ccy') or '').upper():
            r = q['price'] / a['price']
            if 0.5 < r < 2:
                v, price, live, symbol = v_exp * r, q['price'], True, q.get('symbol')
                if q.get('change_pct') is not None:
                    day = q['change_pct']
        unreal = v - cost
        day_pnl = (v - v / (1 + day / 100)) if day is not None and day > -99 else 0.0
        live_n += live
        assets[a['isin']] = {
            'name': a['name'], 'ccy': a.get('ccy'), 'type': a.get('type'), 'qty': a.get('qty'),
            'price': price, 'price_export': a.get('price'), 'live': live, 'symbol': symbol,
            'value': round(v, 2), 'value_export': round(v_exp, 2), 'cost': round(cost, 2),
            'unrealized': round(unreal, 2), 'unrealized_pct': round(unreal / cost * 100, 2) if cost > 0 else a.get('unrealized_pct'),
            'day_pct': day, 'day_pnl': round(day_pnl, 2),
        }
    holdings = sum(x['value'] for x in assets.values())
    holdings_exp = sum(x['value_export'] for x in assets.values())
    cash = float(ov.get('cash_balance') or 0.0)
    cost = sum(x['cost'] for x in assets.values())
    unreal = sum(x['unrealized'] for x in assets.values())
    day_pnl = sum(x['day_pnl'] for x in assets.values())
    nd = float(ov.get('net_deposits') or 0.0)
    account = holdings + cash
    for x in assets.values():
        x['weight'] = round(x['value'] / holdings * 100, 3) if holdings else 0.0
    totals = {
        'holdings': round(holdings, 2), 'holdings_export': round(holdings_exp, 2), 'cash': round(cash, 2), 'account': round(account, 2),
        'cost': round(cost, 2), 'unrealized': round(unreal, 2), 'unrealized_pct': round(unreal / cost * 100, 2) if cost > 0 else None,
        'net_deposits': round(nd, 2), 'all_time': round(account - nd, 2), 'all_time_pct': round((account - nd) / nd * 100, 2) if nd else None,
        'day_pnl': round(day_pnl, 2), 'day_pct': round(day_pnl / (holdings - day_pnl) * 100, 2) if holdings - day_pnl > 0 else None,
        'positions': len(assets), 'live_positions': live_n,
    }
    return {'ok': True, 'asof': (now or __import__('datetime').datetime.now()).isoformat(timespec='seconds'),
            'export_date': _export_date(payload), 'assets': assets, 'totals': totals}


def apply(payload, snap):
    """A copy of the analytics payload in which every value-dependent figure is the snapshot's (assets, overview, weight-based
    habit scores, dividend share of the result). The cached original is not touched."""
    import trade_analytics as ta
    p = dict(payload)
    assets = []
    for a in payload.get('assets') or []:
        s = snap['assets'].get(a.get('isin'))
        if not s:
            assets.append(a)
            continue
        b = dict(a)
        b.update(value=s['value'], price=s['price'], unrealized=s['unrealized'], unrealized_pct=s['unrealized_pct'], day_pct=s['day_pct'], live=s['live'])
        b['total_pnl'] = round((a.get('realized') or 0.0) + s['unrealized'], 2)
        assets.append(b)
    ins = dict(payload['insights'])
    t = snap['totals']
    ov = dict(ins['overview'])
    ov.update(holdings_value=t['holdings'], total_value=t['account'], unrealized=t['unrealized'], all_time_pnl=t['all_time'], all_time_pnl_pct=t['all_time_pct'])
    ins['overview'] = ov
    try:
        ins['scorecard'] = ta.build_scorecard(ins, payload.get('trades') or [], assets, ins.get('cumulative') or [])
    except Exception:
        pass                                                  # keep the export-based scorecard rather than fail the page
    dv = ins.get('dividends')
    if dv and dv.get('summary'):
        dv = dict(dv)
        sm = dict(dv['summary'])
        sm['pct_of_result'] = round(sm['net'] / t['all_time'] * 100, 1) if t['all_time'] and t['all_time'] > 0 else None
        dv['summary'] = sm
        ins['dividends'] = dv
    p['assets'], p['insights'] = assets, ins
    p['valuation'] = {'asof': snap['asof'], 'export_date': snap['export_date'], 'live_positions': t['live_positions'], 'positions': t['positions']}
    return p
