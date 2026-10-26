#!/usr/bin/env python3
"""
trade_analytics.py  -  Nordnet CSV -> analytics JSON for the Analytics page
===========================================================================
Ground truth = two Nordnet exports in the project folder (newest match wins):

    transactions-and-notes-export*.csv   full buy/sell/cash ledger
    Innehav*Export*.csv                  current holdings (prices, GAV)

Nothing is hard-coded to one account or file name: drop a fresh export next to
the old one and the next request re-reads it (cache key = path+mtime+size).

Method notes (also shown on the page):
  * Realised P&L uses the average-cost method (Swedish "genomsnittsmetoden"),
    in SEK, with buy fees inside the cost and sell fees taken off proceeds.
  * Holding period uses FIFO lots (oldest shares sold first).
  * Current quantity is rebuilt from the ledger and cross-checked against the
    holdings export; any difference is reported in `warnings`.
"""

import csv
import io
import glob
import os
import re
import statistics
from collections import defaultdict, deque
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# Transaction types as they appear after Nordnet's Swedish export (escapes keep
# this file ASCII-only and independent of the console encoding).
T_BUY = 'KÖPT'
T_SELL = 'SÅLT'
T_DEPOSIT = {'INSÄTTNING', 'REALTIDSINSÄTTNING'}
T_WITHDRAW = {'UTTAG'}
T_DIVIDEND = {'UTDELNING'}
T_DIV_TAX = {'KÄLLSKATT', 'TYSK SOL SKATT UTD'}
T_INTEREST = {'KAP. DEB RÄNTA', 'KAP ÖVERBEL.RÄNTA'}
T_FEE = {'AVGIFT'}
T_FUND_REFUND = {'ÅTERB FONDAVGIFTER'}
T_CA_IN = {'BYTE INLÄGG VP', 'SPLIT INLÄGG VP', 'INLÄGG FISSION',
           'UTDELNING INLÄGG VP'}
T_CA_OUT = {'BYTE UTTAG VP', 'SPLIT UTTAG VP', 'DECIMALER UTTAG VP'}
T_CA_PAIRED = {'BYTE', 'SPLIT'}          # in/out rows that share a verification no.

EPS = 1e-9


# --------------------------------------------------------------------------
# file discovery + reading
# --------------------------------------------------------------------------
def _file_date(path):
    """YYYY-MM-DD in the file name (Nordnet puts the export date there), else ''."""
    m = re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(path))
    return m.group(0) if m else ''


def _newest(patterns):
    """Latest export: date in the file name wins, file mtime breaks ties / covers undated names."""
    hits = []
    for p in patterns:
        hits += glob.glob(os.path.join(HERE, p))
    hits = [h for h in hits if os.path.isfile(h)]
    return max(hits, key=lambda h: (_file_date(h), os.path.getmtime(h))) if hits else None


def newest_holdings():
    """Path of the latest 'Innehav ... Export' file (the single source for current holdings)."""
    return _newest(['Innehav*Export*.csv'])


def find_sources():
    return {
        'transactions': _newest(['transactions-and-notes-export*.csv']),
        'holdings': newest_holdings(),
    }


def signature():
    """Cheap change detector for the browser to poll."""
    out = {}
    for k, p in find_sources().items():
        if p:
            st = os.stat(p)
            out[k] = {'file': os.path.basename(p), 'mtime': st.st_mtime, 'size': st.st_size}
        else:
            out[k] = None
    return out


def _read_table(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-16', 'utf-8-sig', 'cp1252'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.split('\n', 1)[0]
    delim = '\t' if first.count('\t') >= first.count(';') else ';'
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]


def _num(s):
    if s is None:
        return None
    s = s.replace('\xa0', '').replace(' ', '').replace('−', '-').replace(',', '.')
    if s in ('', '-'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _n0(s):
    v = _num(s)
    return 0.0 if v is None else v


def _col(header, *names, after=None):
    """Index of the first header equal to one of names (optionally after a column)."""
    norm = [h.strip().lower().replace('\xa0', ' ') for h in header]
    start = 0 if after is None else after + 1
    for i in range(start, len(norm)):
        if norm[i] in names:
            return i
    return None


# --------------------------------------------------------------------------
# ledger parsing
# --------------------------------------------------------------------------
def parse_ledger(path):
    header, rows = _read_table(path)
    c = {
        'id': _col(header, 'id'),
        'book': _col(header, 'bokföringsdag'),
        'trade': _col(header, 'affärsdag'),
        'type': _col(header, 'transaktionstyp'),
        'name': _col(header, 'värdepapper'),
        'isin': _col(header, 'isin'),
        'qty': _col(header, 'antal'),
        'price': _col(header, 'kurs'),
        'fee': _col(header, 'total avgift'),
        'amount': _col(header, 'belopp'),
        'cost': _col(header, 'inköpsvärde'),
        'result': _col(header, 'resultat'),
        'balance': _col(header, 'saldo'),
        'fx': _col(header, 'växlingskurs'),
        'text': _col(header, 'transaktionstext'),
        'verif': _col(header, 'verifikationsnummer'),
        'courtage': _col(header, 'courtage'),
    }
    missing = [k for k in ('id', 'trade', 'type', 'amount') if c[k] is None]
    if missing:
        raise ValueError('Transactions CSV is missing columns: ' + ', '.join(missing))
    c['amount_ccy'] = c['amount'] + 1
    c['cost_ccy'] = None if c['cost'] is None else c['cost'] + 1
    c['result_ccy'] = None if c['result'] is None else c['result'] + 1
    c['courtage_ccy'] = None if c['courtage'] is None else c['courtage'] + 1

    def g(r, k):
        i = c.get(k)
        return r[i].strip() if i is not None and i < len(r) else ''

    out = []
    for r in rows:
        tdate = g(r, 'trade') or g(r, 'book')
        try:
            datetime.strptime(tdate, '%Y-%m-%d')
        except ValueError:
            continue
        if g(r, 'type') == '':
            continue
        out.append({
            'id': int(_n0(g(r, 'id'))),
            'date': tdate,
            'book': g(r, 'book') or tdate,
            'type': g(r, 'type').upper(),
            'name': g(r, 'name'),
            'isin': g(r, 'isin'),
            'qty': _n0(g(r, 'qty')),
            'price': _num(g(r, 'price')),
            'fee': _n0(g(r, 'fee')),
            'amount': _n0(g(r, 'amount')),
            'ccy': (g(r, 'cost_ccy') if g(r, 'cost') else '') or g(r, 'result_ccy') or 'SEK',
            'fx': _num(g(r, 'fx')),
            'result': _num(g(r, 'result')),
            'balance': _num(g(r, 'balance')),
            'text': g(r, 'text'),
            'verif': g(r, 'verif'),
            'courtage': _n0(g(r, 'courtage')),
            'cost_native': _num(g(r, 'cost')),
        })
    out.sort(key=lambda t: (t['date'], t['id']))
    return out


def parse_holdings(path):
    if not path:
        return {}
    header, rows = _read_table(path)
    ix = {
        'name': _col(header, 'namn'), 'ccy': _col(header, 'valuta'),
        'qty': _col(header, 'antal'), 'gav': _col(header, 'gav/snittkurs', 'gav', 'snittkurs'),
        'day': _col(header, 'idag %', '1 dag %'),
        'price': _col(header, 'senaste kurs', 'senaste nav'),
        'value': _col(header, 'värde sek'), 'pct': _col(header, 'avkast. %'),
        'pnl': _col(header, 'avkast. sek'),
    }
    out = {}
    for r in rows:
        if ix['name'] is None or ix['name'] >= len(r):
            continue
        name = r[ix['name']].strip()
        if not name:
            continue

        def v(k):
            return _num(r[ix[k]]) if ix[k] is not None and ix[k] < len(r) else None
        out[name] = {
            'name': name, 'ccy': r[ix['ccy']].strip() if ix['ccy'] is not None else '',
            'qty': v('qty') or 0.0, 'gav': v('gav'), 'day_pct': v('day'),
            'price': v('price'), 'value_sek': v('value') or 0.0,
            'pnl_pct': v('pct'), 'pnl_sek': v('pnl') or 0.0,
        }
    return out


# --------------------------------------------------------------------------
# classification (heuristic, name/ISIN based - nothing external is looked up)
# --------------------------------------------------------------------------
def classify_type(name, courtage_seen, trades_seen):
    n = name.lower()
    if 'mini l' in n or 'mini s' in n or 'turbo' in n:
        return 'Leveraged cert'
    if re.search(r'(etf|etc|ucits)', n) or 'xetra-gold' in n:
        return 'ETF/ETC'
    fundish = ('index', 'indeks', 'indeksi', 'allemansfond', ' fund', 'fond', 'auag',
               'nordea alfa', 'global index')
    if any(w in n for w in fundish):
        return 'Fund'
    return 'Stock'


def domicile(isin):
    return isin[:2].upper() if isin and len(isin) >= 2 and isin[:2].isalpha() else '??'


# --------------------------------------------------------------------------
# core engine
# --------------------------------------------------------------------------
def build(ledger, holdings):
    warnings = []

    # ---- corporate-action aliasing: BYTE/SPLIT pairs share a verification no.
    by_verif = defaultdict(list)
    for t in ledger:
        if t['verif'] and any(t['type'].startswith(p) for p in T_CA_PAIRED):
            by_verif[t['verif']].append(t)
    alias = {}
    for rows in by_verif.values():
        outs = [t for t in rows if t['type'] in T_CA_OUT]
        ins = [t for t in rows if t['type'] in T_CA_IN]
        if outs and ins and outs[0]['isin'] and ins[0]['isin'] and outs[0]['isin'] != ins[0]['isin']:
            alias[outs[0]['isin']] = ins[0]['isin']

    def canon(isin):
        seen = set()
        while isin in alias and isin not in seen:
            seen.add(isin)
            isin = alias[isin]
        return isin

    pos = {}                                  # canon isin -> state
    pending_cost = defaultdict(float)         # verif -> cost carried across a swap
    trades = []
    cash = defaultdict(float)
    cash_events = []
    last_balance = None

    def state(isin, name):
        if isin not in pos:
            pos[isin] = {'isin': isin, 'name': name, 'qty': 0.0, 'cost': 0.0, 'lots': deque(),
                         'ccy': 'SEK', 'last_name_date': ''}
        return pos[isin]

    for t in ledger:
        if t['balance'] is not None:
            last_balance = t['balance']
        ty = t['type']
        if ty in (T_BUY, T_SELL):
            isin = canon(t['isin'])
            st = state(isin, t['name'])
            if t['date'] >= st['last_name_date']:
                st['name'], st['last_name_date'] = t['name'], t['date']
            st['ccy'] = t['ccy']
            fx = t['fx'] if t['fx'] else 1.0
            value_sek = abs(t['amount'])
            fee = t['fee']
            courtage = t['courtage']
            row = {
                'id': t['id'], 'date': t['date'], 'side': 'BUY' if ty == T_BUY else 'SELL',
                'isin': isin, 'name': t['name'], 'qty': t['qty'], 'price': t['price'],
                'ccy': t['ccy'], 'fx': fx, 'amount': round(value_sek, 2),
                'fee': round(fee, 2), 'courtage': round(courtage, 2),
                'fx_fee': round(max(fee - courtage, 0.0), 2),
                'realized': None, 'hold_days': None, 'min_hold_days': None,
                'nordnet_result': None,
            }
            d = date.fromisoformat(t['date'])
            if ty == T_BUY:
                st['cost'] += value_sek                   # Belopp already includes the fee
                st['qty'] += t['qty']
                st['lots'].append([d, t['qty']])
                row['gross'] = round(value_sek - fee, 2)
            else:
                q = t['qty']
                if q > st['qty'] + 1e-6:
                    warnings.append(f"Sold {q} of {t['name']} on {t['date']} but ledger shows "
                                    f"{st['qty']:.4f} held (earlier history missing?).")
                q_eff = min(q, st['qty'])
                avg = st['cost'] / st['qty'] if st['qty'] > EPS else 0.0
                cost_removed = avg * q_eff
                proceeds = value_sek                       # Belopp already net of the fee
                row['realized'] = round(proceeds - cost_removed, 2)
                row['gross'] = round(value_sek + fee, 2)
                row['realized_gross'] = round(proceeds + fee - cost_removed, 2)
                row['cost_basis'] = round(cost_removed, 2)
                # FIFO holding period
                need, wsum, wq, mn = q_eff, 0.0, 0.0, None
                while need > 1e-9 and st['lots']:
                    lot = st['lots'][0]
                    take = min(lot[1], need)
                    age = (d - lot[0]).days
                    wsum += age * take
                    wq += take
                    mn = age if mn is None else min(mn, age)
                    lot[1] -= take
                    need -= take
                    if lot[1] <= 1e-9:
                        st['lots'].popleft()
                if wq > 0:
                    row['hold_days'] = round(wsum / wq, 1)
                    row['min_hold_days'] = mn
                st['qty'] -= q_eff
                st['cost'] -= cost_removed
                if st['qty'] < 1e-9:
                    st['qty'], st['cost'] = 0.0, 0.0
                if t['result'] is not None:
                    row['nordnet_result'] = round(t['result'] * fx, 2)
            row['pos_after'] = round(st['qty'], 6)
            trades.append(row)
        elif ty in T_CA_IN or ty in T_CA_OUT:
            isin = canon(t['isin'])
            st = state(isin, t['name'])
            if t['date'] >= st['last_name_date']:
                st['name'], st['last_name_date'] = t['name'], t['date']
            if ty in T_CA_OUT:
                q = min(t['qty'], st['qty'])
                avg = st['cost'] / st['qty'] if st['qty'] > EPS else 0.0
                if t['verif']:
                    pending_cost[t['verif']] += avg * q
                st['cost'] -= avg * q
                need = q
                while need > 1e-9 and st['lots']:
                    lot = st['lots'][0]
                    take = min(lot[1], need)
                    lot[1] -= take
                    need -= take
                    if lot[1] <= 1e-9:
                        st['lots'].popleft()
                st['qty'] -= q
                if st['qty'] < 1e-9:
                    st['qty'], st['cost'] = 0.0, 0.0
            else:
                carried = pending_cost.pop(t['verif'], 0.0) if t['verif'] else 0.0
                st['qty'] += t['qty']
                st['cost'] += carried
                st['lots'].append([date.fromisoformat(t['date']), t['qty']])
        elif ty in T_DEPOSIT:
            cash['deposits'] += t['amount']
            cash_events.append((t['book'], 'deposit', t['amount']))
        elif ty in T_WITHDRAW:
            cash['withdrawals'] += -t['amount']
            cash_events.append((t['book'], 'withdrawal', t['amount']))
        elif ty in T_DIVIDEND:
            cash['dividends'] += t['amount']
            cash_events.append((t['book'], 'dividend', t['amount']))
        elif ty in T_DIV_TAX:
            cash['dividend_tax'] += -t['amount']
            cash_events.append((t['book'], 'tax', t['amount']))
        elif ty in T_INTEREST:
            cash['interest'] += -t['amount']
            cash_events.append((t['book'], 'interest', t['amount']))
        elif ty in T_FEE:
            cash['other_fees'] += -t['amount']
            cash_events.append((t['book'], 'other_fee', t['amount']))
        elif ty in T_FUND_REFUND:
            cash['fee_refunds'] += t['amount']
            cash_events.append((t['book'], 'refund', t['amount']))
        elif ty == 'DECIMALER LIKVID':
            cash['other_income'] += t['amount']

    # ---- asset table ---------------------------------------------------------
    h_by_name = {k.strip(): v for k, v in holdings.items()}
    assets = {}
    for tr in trades:
        a = assets.setdefault(tr['isin'], {
            'isin': tr['isin'], 'buys': 0, 'sells': 0, 'qty_bought': 0.0, 'qty_sold': 0.0,
            'bought_sek': 0.0, 'sold_sek': 0.0, 'fees': 0.0, 'realized': 0.0,
            'first_buy': None, 'last_buy': None, 'first_sell': None, 'last_sell': None,
        })
        a['fees'] += tr['fee']
        if tr['side'] == 'BUY':
            a['buys'] += 1
            a['qty_bought'] += tr['qty']
            a['bought_sek'] += tr['amount']
            a['first_buy'] = a['first_buy'] or tr['date']
            a['last_buy'] = tr['date']
        else:
            a['sells'] += 1
            a['qty_sold'] += tr['qty']
            a['sold_sek'] += tr['amount']
            a['first_sell'] = a['first_sell'] or tr['date']
            a['last_sell'] = tr['date']
            a['realized'] += tr['realized'] or 0.0

    matched_holdings = set()
    for isin, a in assets.items():
        st = pos[isin]
        name = st['name'].strip()
        a['name'] = name
        a['ccy'] = st['ccy']
        a['qty'] = round(st['qty'], 6)
        a['held'] = st['qty'] > 1e-6
        a['cost_basis'] = round(st['cost'], 2)
        courtage_seen = sum(t['courtage'] for t in trades if t['isin'] == isin)
        a['type'] = classify_type(name, courtage_seen, a['buys'] + a['sells'])
        a['domicile'] = domicile(isin)
        h = h_by_name.get(name)
        if h:
            matched_holdings.add(name)
            a['price'] = h['price']
            a['gav'] = h['gav']
            a['value'] = round(h['value_sek'], 2)
            a['unrealized'] = round(h['pnl_sek'], 2)
            a['unrealized_pct'] = h['pnl_pct']
            a['day_pct'] = h['day_pct']
            a['ccy'] = h['ccy'] or a['ccy']
            if abs(h['qty'] - st['qty']) > 1e-3:
                warnings.append(f"{name}: ledger quantity {st['qty']:.4f} differs from holdings "
                                f"export {h['qty']:.4f}.")
        else:
            a['price'] = a['gav'] = a['unrealized_pct'] = a['day_pct'] = None
            a['value'] = 0.0
            a['unrealized'] = 0.0
            if a['held']:
                warnings.append(f"{name}: held per ledger ({st['qty']:.4f}) but missing from "
                                f"holdings export - value shown as 0.")
        for k in ('bought_sek', 'sold_sek', 'fees', 'realized', 'qty_bought', 'qty_sold'):
            a[k] = round(a[k], 4 if k.startswith('qty') else 2)
        a['total_pnl'] = round(a['realized'] + a['unrealized'], 2)
    for name, h in h_by_name.items():
        if name not in matched_holdings and (h['qty'] or h['value_sek']):
            warnings.append(f"Holdings export row '{name}' (qty {h['qty']}) has no matching trades.")

    asset_list = sorted(assets.values(), key=lambda a: -(a['value'] or 0))

    return trades, asset_list, dict(cash), cash_events, last_balance, warnings


# --------------------------------------------------------------------------
# habit analysis
# --------------------------------------------------------------------------
def _bucket(v, edges, labels):
    for e, lab in zip(edges, labels):
        if v < e:
            return lab
    return labels[-1]


def analyse(trades, assets, cash, cash_events, balance, holdings):
    out = {}
    buys = [t for t in trades if t['side'] == 'BUY']
    sells = [t for t in trades if t['side'] == 'SELL']
    total_fee = sum(t['fee'] for t in trades)
    courtage = sum(t['courtage'] for t in trades)
    fx_fee = sum(t['fx_fee'] for t in trades)
    turnover = sum(t['amount'] for t in trades)
    first = trades[0]['date'] if trades else None
    last = trades[-1]['date'] if trades else None
    days_span = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1 if trades else 0
    active_days = len({t['date'] for t in trades})

    deposits = cash.get('deposits', 0.0)
    withdrawals = cash.get('withdrawals', 0.0)
    holdings_value = sum(h['value_sek'] for h in holdings.values())
    net_dep = deposits - withdrawals
    total_value = holdings_value + (balance or 0.0)
    realized = sum(t['realized'] or 0.0 for t in sells)
    unrealized = sum(a['unrealized'] for a in assets)

    interest = cash.get('interest', 0.0)
    other_fees = cash.get('other_fees', 0.0)
    refunds = cash.get('fee_refunds', 0.0)
    broker_cost = total_fee + interest + other_fees - refunds
    out['overview'] = {
        'first_date': first, 'last_date': last, 'days_span': days_span, 'active_days': active_days,
        'trades': len(trades), 'buys': len(buys), 'sells': len(sells),
        'distinct_assets': len(assets), 'held_assets': sum(1 for a in assets if a['held']),
        'turnover': round(turnover, 2),
        'buy_volume': round(sum(t['amount'] for t in buys), 2),
        'sell_volume': round(sum(t['amount'] for t in sells), 2),
        'deposits': round(deposits, 2), 'deposit_count': sum(1 for e in cash_events if e[1] == 'deposit'),
        'withdrawals': round(withdrawals, 2), 'net_deposits': round(net_dep, 2),
        'cash_balance': round(balance or 0.0, 2), 'holdings_value': round(holdings_value, 2),
        'total_value': round(total_value, 2),
        'all_time_pnl': round(total_value - net_dep, 2),
        'all_time_pnl_pct': round((total_value - net_dep) / net_dep * 100, 2) if net_dep else None,
        'realized': round(realized, 2), 'unrealized': round(unrealized, 2),
        'dividends': round(cash.get('dividends', 0.0), 2),
        'dividend_tax': round(cash.get('dividend_tax', 0.0), 2),
    }

    out['costs'] = {
        'trade_fees': round(total_fee, 2), 'courtage': round(courtage, 2), 'fx_fees': round(fx_fee, 2),
        'interest': round(interest, 2), 'other_fees': round(other_fees, 2),
        'fee_refunds': round(refunds, 2), 'broker_total': round(broker_cost, 2),
        'pct_of_turnover': round(total_fee / turnover * 100, 3) if turnover else None,
        'pct_of_net_deposits': round(broker_cost / net_dep * 100, 2) if net_dep else None,
        'avg_fee_per_paid_trade': round(total_fee / max(1, sum(1 for t in trades if t['fee'] > 0)), 2),
        'paid_trades': sum(1 for t in trades if t['fee'] > 0),
        'free_trades': sum(1 for t in trades if t['fee'] == 0),
        'fee_buy': round(sum(t['fee'] for t in buys), 2),
        'fee_sell': round(sum(t['fee'] for t in sells), 2),
        'dividend_tax': round(cash.get('dividend_tax', 0.0), 2),
        'fee_vs_realized_gross': None,
    }

    # ---- fees by trade size (paid trades only) -------------------------------
    edges = [500, 1000, 2500, 5000, 10000]
    labels = ['< 500', '500-1k', '1k-2.5k', '2.5k-5k', '5k-10k', '> 10k']
    bk = {l: {'bucket': l, 'trades': 0, 'turnover': 0.0, 'fees': 0.0} for l in labels}
    for t in trades:
        if t['fee'] <= 0:
            continue
        b = bk[_bucket(t['amount'], edges, labels)]
        b['trades'] += 1
        b['turnover'] += t['amount']
        b['fees'] += t['fee']
    out['fee_by_size'] = [dict(b, turnover=round(b['turnover'], 2), fees=round(b['fees'], 2),
                               fee_pct=round(b['fees'] / b['turnover'] * 100, 3) if b['turnover'] else None)
                          for b in bk.values()]
    small = [t for t in trades if t['fee'] > 0 and t['fee'] / max(t['amount'], 1) >= 0.01]
    out['small_trades'] = {
        'count': len(small), 'fees': round(sum(t['fee'] for t in small), 2),
        'turnover': round(sum(t['amount'] for t in small), 2),
        'definition': 'trades where the fee was 1% or more of the trade value',
    }

    # ---- order splitting: same day + same asset + same side, >1 order -----------
    groups = defaultdict(list)
    for t in trades:
        groups[(t['date'], t['isin'], t['side'])].append(t)
    split_groups, extra_orders, avoidable = [], 0, 0.0
    for (d, isin, side), g in groups.items():
        if len(g) > 1 and any(x['fee'] > 0 for x in g):
            fees = sorted((x['fee'] for x in g), reverse=True)
            save = sum(fees[1:])
            extra_orders += len(g) - 1
            avoidable += save
            split_groups.append({'date': d, 'name': g[0]['name'].strip(), 'side': side,
                                 'orders': len(g), 'fees': round(sum(fees), 2),
                                 'avoidable': round(save, 2),
                                 'amount': round(sum(x['amount'] for x in g), 2)})
    split_groups.sort(key=lambda x: -x['avoidable'])
    out['split_orders'] = {
        'groups': len(split_groups), 'extra_orders': extra_orders,
        'avoidable_fees': round(avoidable, 2), 'top': split_groups[:12],
        'note': 'Estimate: if each group had been one order, you would have paid only the largest fee of the group.',
    }

    # ---- same-day round trips ---------------------------------------------------
    sameday = []
    by_day_asset = defaultdict(lambda: {'BUY': [], 'SELL': []})
    for t in trades:
        by_day_asset[(t['date'], t['isin'])][t['side']].append(t)
    for (d, isin), g in by_day_asset.items():
        if g['BUY'] and g['SELL']:
            fees = sum(x['fee'] for x in g['BUY'] + g['SELL'])
            sameday.append({'date': d, 'name': g['BUY'][0]['name'].strip(), 'fees': round(fees, 2),
                            'realized': round(sum(x['realized'] or 0 for x in g['SELL']), 2),
                            'buy_amount': round(sum(x['amount'] for x in g['BUY']), 2),
                            'sell_amount': round(sum(x['amount'] for x in g['SELL']), 2)})
    sameday.sort(key=lambda x: -x['fees'])
    out['same_day'] = {
        'count': len(sameday), 'fees': round(sum(x['fees'] for x in sameday), 2),
        'realized': round(sum(x['realized'] for x in sameday), 2), 'top': sameday[:10],
    }

    # ---- holding period vs outcome -------------------------------------------------
    hb_edges = [2, 8, 31, 91, 366]
    hb_labels = ['0-1 d', '2-7 d', '8-30 d', '31-90 d', '91-365 d', '> 1 y']
    hb = {l: {'bucket': l, 'sells': 0, 'wins': 0, 'net': 0.0, 'gross': 0.0, 'fees': 0.0,
              'fee_eaten': 0, 'turnover': 0.0} for l in hb_labels}
    for t in sells:
        if t['hold_days'] is None:
            continue
        b = hb[_bucket(t['hold_days'], hb_edges, hb_labels)]
        b['sells'] += 1
        b['wins'] += 1 if (t['realized'] or 0) > 0 else 0
        b['net'] += t['realized'] or 0
        b['gross'] += t.get('realized_gross', 0) or 0
        b['fees'] += t['fee']
        b['turnover'] += t['amount']
        if (t.get('realized_gross') or 0) > 0 and (t['realized'] or 0) <= 0:
            b['fee_eaten'] += 1
    out['hold_buckets'] = [dict(b, net=round(b['net'], 2), gross=round(b['gross'], 2),
                                fees=round(b['fees'], 2), turnover=round(b['turnover'], 2),
                                win_rate=round(b['wins'] / b['sells'] * 100, 1) if b['sells'] else None)
                           for b in hb.values()]

    # ---- sell quality --------------------------------------------------------------
    sold = [t for t in sells if t['realized'] is not None]
    wins = [t['realized'] for t in sold if t['realized'] > 0]
    losses = [t['realized'] for t in sold if t['realized'] < 0]
    fee_eaten = [t for t in sold if (t.get('realized_gross') or 0) > 0 and t['realized'] <= 0]
    thin = [t for t in sold if t['realized'] > 0 and t['fee'] > 0.5 * (t.get('realized_gross') or 1e9)]
    holds = [t['hold_days'] for t in sold if t['hold_days'] is not None]
    out['sell_quality'] = {
        'sells': len(sold), 'wins': len(wins), 'losses': len(losses),
        'win_rate': round(len(wins) / len(sold) * 100, 1) if sold else None,
        'avg_win': round(statistics.mean(wins), 2) if wins else None,
        'avg_loss': round(statistics.mean(losses), 2) if losses else None,
        'payoff_ratio': round(statistics.mean(wins) / abs(statistics.mean(losses)), 2) if wins and losses else None,
        'profit_factor': round(sum(wins) / abs(sum(losses)), 2) if losses else None,
        'gross_wins': round(sum(wins), 2), 'gross_losses': round(sum(losses), 2),
        'realized_net': round(sum(t['realized'] for t in sold), 2),
        'realized_before_fees': round(sum(t.get('realized_gross', 0) or 0 for t in sold), 2),
        'fee_eaten_count': len(fee_eaten),
        'fee_eaten_fees': round(sum(t['fee'] for t in fee_eaten), 2),
        'thin_profit_count': len(thin),
        'median_hold_days': round(statistics.median(holds), 1) if holds else None,
        'avg_hold_days': round(statistics.mean(holds), 1) if holds else None,
        'sold_within_7d': sum(1 for h in holds if h <= 7),
        'sold_within_30d': sum(1 for h in holds if h <= 30),
        'median_sell_size': round(statistics.median(t['amount'] for t in sells), 2) if sells else None,
    }
    out['costs']['fee_vs_realized_gross'] = (
        round(total_fee / out['sell_quality']['realized_before_fees'] * 100, 1)
        if out['sell_quality']['realized_before_fees'] > 0 else None)

    # ---- sell then rebuy (whipsaw) -----------------------------------------------------
    rebuys = []
    per_asset = defaultdict(list)
    for t in trades:
        per_asset[t['isin']].append(t)
    for isin, ts in per_asset.items():
        for i, s in enumerate(ts):
            if s['side'] != 'SELL' or not s['price']:
                continue
            sd = date.fromisoformat(s['date'])
            for b in ts[i + 1:]:
                gap = (date.fromisoformat(b['date']) - sd).days
                if gap > 14:
                    break
                if b['side'] == 'SELL':
                    break
                if b['side'] == 'BUY' and b['price'] and gap >= 0 and b['date'] != s['date']:
                    q = min(s['qty'], b['qty'])
                    effect = (s['price'] * (s['fx'] or 1) - b['price'] * (b['fx'] or 1)) * q
                    rebuys.append({'name': s['name'].strip(), 'sold': s['date'], 'rebought': b['date'],
                                   'gap_days': gap, 'sell_price': s['price'], 'buy_price': b['price'],
                                   'ccy': s['ccy'], 'sell_price_sek': round(s['price'] * (s['fx'] or 1), 2),
                                   'buy_price_sek': round(b['price'] * (b['fx'] or 1), 2), 'effect': round(effect, 2),
                                   'fees': round(s['fee'] + b['fee'], 2)})
                    break
    worse = [r for r in rebuys if r['effect'] < 0]
    out['rebuys'] = {
        'count': len(rebuys), 'worse': len(worse), 'better': len(rebuys) - len(worse),
        'net_effect': round(sum(r['effect'] for r in rebuys), 2),
        'fees': round(sum(r['fees'] for r in rebuys), 2),
        'worst': sorted(rebuys, key=lambda r: r['effect'])[:8],
        'note': 'Sell followed by a re-buy of the same asset within 14 days (not the same day). '
                'Effect = (sell price - re-buy price) x shares, in SEK; fees shown separately.',
    }

    # ---- asset churn ranking ---------------------------------------------------------------
    churn = []
    for a in assets:
        n = a['buys'] + a['sells']
        if n >= 6:
            churn.append({'name': a['name'], 'trades': n, 'buys': a['buys'], 'sells': a['sells'],
                          'fees': a['fees'], 'realized': a['realized'], 'unrealized': a['unrealized'],
                          'total_pnl': a['total_pnl'], 'turnover': round(a['bought_sek'] + a['sold_sek'], 2),
                          'held': a['held'], 'type': a['type']})
    churn.sort(key=lambda x: -x['trades'])
    out['churn_assets'] = churn[:25]

    # ---- rhythm ------------------------------------------------------------------------------
    wd = defaultdict(lambda: {'trades': 0, 'fees': 0.0})
    names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    per_day = defaultdict(int)
    monthly = defaultdict(lambda: {'month': '', 'buys': 0, 'sells': 0, 'buy_sek': 0.0, 'sell_sek': 0.0,
                                   'fees': 0.0, 'realized': 0.0, 'trades': 0, 'deposits': 0.0})
    for t in trades:
        w = names[date.fromisoformat(t['date']).weekday()]
        wd[w]['trades'] += 1
        wd[w]['fees'] += t['fee']
        per_day[t['date']] += 1
        m = monthly[t['date'][:7]]
        m['month'] = t['date'][:7]
        m['trades'] += 1
        m['fees'] += t['fee']
        if t['side'] == 'BUY':
            m['buys'] += 1
            m['buy_sek'] += t['amount']
        else:
            m['sells'] += 1
            m['sell_sek'] += t['amount']
            m['realized'] += t['realized'] or 0
    for d, kind, amt in cash_events:
        if kind == 'deposit':
            m = monthly[d[:7]]
            m['month'] = d[:7]
            m['deposits'] += amt
    out['weekday'] = [{'day': n, 'trades': wd[n]['trades'], 'fees': round(wd[n]['fees'], 2)} for n in names]
    out['monthly'] = [dict(m, buy_sek=round(m['buy_sek'], 2), sell_sek=round(m['sell_sek'], 2),
                           fees=round(m['fees'], 2), realized=round(m['realized'], 2),
                           deposits=round(m['deposits'], 2))
                      for _, m in sorted(monthly.items())]
    busy = sorted(per_day.items(), key=lambda kv: -kv[1])
    out['rhythm'] = {
        'trades_per_active_day': round(len(trades) / active_days, 1) if active_days else None,
        'busiest_days': [{'date': d, 'trades': n} for d, n in busy[:8]],
        'days_with_10plus': sum(1 for n in per_day.values() if n >= 10),
        'active_day_share': round(active_days / days_span * 100, 1) if days_span else None,
    }

    # ---- cumulative series for the timeline chart ----------------------------------------------
    events = defaultdict(lambda: {'fees': 0.0, 'realized': 0.0, 'net_deposit': 0.0, 'dividends': 0.0})
    for t in trades:
        events[t['date']]['fees'] += t['fee']
        events[t['date']]['realized'] += t['realized'] or 0
    for d, kind, amt in cash_events:
        if kind in ('deposit', 'withdrawal'):
            events[d]['net_deposit'] += amt
        elif kind == 'dividend':
            events[d]['dividends'] += amt
    cum, c_fee, c_real, c_dep, c_div = [], 0.0, 0.0, 0.0, 0.0
    for d in sorted(events):
        e = events[d]
        c_fee += e['fees']
        c_real += e['realized']
        c_dep += e['net_deposit']
        c_div += e['dividends']
        cum.append({'date': d, 'fees': round(c_fee, 2), 'realized': round(c_real, 2),
                    'net_deposits': round(c_dep, 2), 'dividends': round(c_div, 2)})
    out['cumulative'] = cum

    # ---- held-asset count over time ---------------------------------------------------------------
    open_set, series = set(), []
    for d in sorted({t['date'] for t in trades}):
        for t in [x for x in trades if x['date'] == d]:
            if t['pos_after'] > 1e-6:
                open_set.add(t['isin'])
            else:
                open_set.discard(t['isin'])
        series.append({'date': d, 'held': len(open_set)})
    out['held_over_time'] = series
    out['scorecard'] = build_scorecard(out, trades, assets, cum)
    return out



# --------------------------------------------------------------------------
# benchmark scorecard
# --------------------------------------------------------------------------
# Rule-of-thumb targets chosen for a long-term retail investor. They are NOT
# an official standard - tune them here. score = 100 at `good`, 0 at `poor`
# (linear in between); lower_is_better flips the direction.
BENCHMARKS = [
    # key, label, unit, good, poor, lower_is_better, weight, why
    ('fee_drag', 'Annual cost drag', '% of avg. deposited / yr', 1.0, 5.0, True, 3,
     'Every krona of fees must be earned back before you make a profit. Low-cost investing usually stays near or below 1% a year.'),
    ('fee_turnover', 'Fees vs. amount traded', '% of turnover', 0.10, 0.40, True, 2,
     'Courtage plus FX cost per krona traded. Large, infrequent orders sit near the low end.'),
    ('fees_vs_gain', 'Fees vs. profit from selling', '% of gross sell profit', 20, 100, True, 3,
     'Above 100% the broker earned more from your sells than you did.'),
    ('small_orders', 'Small orders', '% of paid trades < 1 000 kr', 10, 50, True, 2,
     'A flat ~9 kr courtage on a small order is a high percentage cost.'),
    ('split_rate', 'Split orders', '% of trades that were extra same-day orders', 2, 15, True, 2,
     'Several orders for the same asset on the same day each pay courtage.'),
    ('short_holds', 'Quick sells', '% of sells within 7 days', 10, 40, True, 2,
     'Very short holds mostly pay fees twice for small price moves.'),
    ('turnover_ratio', 'Portfolio turnover', 'x avg. deposited / yr', 1.0, 6.0, True, 2,
     'Buy volume plus sell volume, halved, per year relative to money in the account. Long-term portfolios often run near 1x or less.'),
    ('profit_factor', 'Profit factor on sells', 'wins / losses', 1.5, 1.0, False, 2,
     'Total gains divided by total losses on closed sells (after fees). Below 1.0 means losers outweigh winners.'),
    ('top_weight', 'Largest position', '% of holdings', 10, 30, True, 1,
     'Concentration risk: how much one holding can hurt you.'),
    ('fragmentation', 'Tiny positions', '% of positions < 2 000 kr', 10, 50, True, 1,
     'Many very small holdings cost attention and each has been bought and sold with its own fees.'),
]


def _score(value, good, poor, lower_better):
    if value is None:
        return None
    if lower_better:
        t = (poor - value) / (poor - good) if poor != good else 1.0
    else:
        t = (value - poor) / (good - poor) if good != poor else 1.0
    return round(max(0.0, min(1.0, t)) * 100)


def _grade(score):
    return 'A' if score >= 85 else 'B' if score >= 70 else 'C' if score >= 55 else 'D' if score >= 40 else 'E' if score >= 25 else 'F'


def build_scorecard(out, trades, assets, cum):
    o, c, sq = out['overview'], out['costs'], out['sell_quality']
    years = max(o['days_span'], 1) / 365.0
    # time-weighted average of net deposits over the whole period
    avg_dep, prev_d, prev_v, acc = 0.0, None, 0.0, 0.0
    if cum:
        d0 = date.fromisoformat(o['first_date'])
        d1 = date.fromisoformat(o['last_date'])
        prev_d = d0
        for e in cum:
            d = date.fromisoformat(e['date'])
            acc += prev_v * (d - prev_d).days
            prev_d, prev_v = d, e['net_deposits']
        acc += prev_v * (d1 - prev_d).days + prev_v
        avg_dep = acc / max((d1 - d0).days + 1, 1)
    paid = [t for t in trades if t['fee'] > 0]
    held = [a for a in assets if a['held'] and a['value']]
    tot = sum(a['value'] for a in held)
    vals = {
        'fee_drag': (c['trade_fees'] + c['interest'] + c['other_fees'] - c['fee_refunds']) / years / avg_dep * 100 if avg_dep else None,
        'fee_turnover': c['pct_of_turnover'],
        'fees_vs_gain': c['fee_vs_realized_gross'],
        'small_orders': sum(1 for t in paid if t['amount'] < 1000) / len(paid) * 100 if paid else None,
        'split_rate': out['split_orders']['extra_orders'] / len(trades) * 100 if trades else None,
        'short_holds': sq['sold_within_7d'] / sq['sells'] * 100 if sq['sells'] else None,
        'turnover_ratio': (o['turnover'] / 2) / years / avg_dep if avg_dep else None,
        'profit_factor': sq['profit_factor'],
        'top_weight': max(a['value'] for a in held) / tot * 100 if held and tot else None,
        'fragmentation': sum(1 for a in held if a['value'] < 2000) / len(held) * 100 if held else None,
    }
    items, wsum, ssum = [], 0, 0.0
    for key, label, unit, good, poor, lower, weight, why in BENCHMARKS:
        v = vals.get(key)
        sc = _score(v, good, poor, lower)
        items.append({'key': key, 'label': label, 'unit': unit, 'value': None if v is None else round(v, 2),
                      'good': good, 'poor': poor, 'lower_is_better': lower, 'weight': weight,
                      'score': sc, 'why': why})
        if sc is not None:
            wsum += weight
            ssum += sc * weight
    total = round(ssum / wsum) if wsum else None
    avg_courtage = (c['courtage'] / len(paid)) if paid else 9.0
    return {
        'overall': total, 'grade': _grade(total) if total is not None else None, 'items': items,
        'avg_deposited': round(avg_dep, 2), 'years': round(years, 2),
        'min_order_for_0_3pct': round(avg_courtage / 0.003, -2),
        'avg_courtage': round(avg_courtage, 2),
        'note': 'Targets are rule-of-thumb values chosen for a long-term retail investor, not an official standard. '
                'Edit BENCHMARKS in trade_analytics.py to change them.',
    }

# --------------------------------------------------------------------------
# public entry
# --------------------------------------------------------------------------
_cache = {'key': None, 'data': None}


def get_payload():
    src = find_sources()
    if not src['transactions']:
        return {'error': 'No transactions-and-notes-export*.csv found in the project folder.',
                'sources': signature()}
    key = tuple((p, os.path.getmtime(p), os.path.getsize(p)) if p else None for p in src.values())
    if _cache['key'] == key:
        return _cache['data']
    ledger = parse_ledger(src['transactions'])
    holdings = parse_holdings(src['holdings'])
    trades, assets, cash, cash_events, balance, warnings = build(ledger, holdings)
    if not src['holdings']:
        warnings.append('No Innehav*Export*.csv found - current values and unrealised P&L are unavailable.')
    insights = analyse(trades, assets, cash, cash_events, balance, holdings)
    payload = {
        'generated': datetime.now().isoformat(timespec='seconds'),
        'sources': signature(),
        'warnings': warnings,
        'trades': trades,
        'assets': assets,
        'insights': insights,
        'cashflows': [{'date': d, 'kind': k, 'amount': round(a, 2)} for d, k, a in cash_events if k in ('deposit', 'withdrawal')],
    }
    _cache.update(key=key, data=payload)
    return payload


if __name__ == '__main__':
    import json
    import sys
    p = get_payload()
    if '--full' in sys.argv:
        print(json.dumps(p, indent=1, ensure_ascii=False))
    else:
        q = dict(p)
        q['trades'] = f"<{len(p.get('trades', []))} trades>"
        q['assets'] = f"<{len(p.get('assets', []))} assets>"
        print(json.dumps(q, indent=1, ensure_ascii=False))
