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
import threading
from collections import OrderedDict, defaultdict, deque
from datetime import date, datetime, timedelta

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


def _base(base_dir):
    """Folder that holds one profile's CSVs; None = the project folder (CLI use, legacy single-user layout)."""
    return os.path.abspath(base_dir) if base_dir else HERE


def _newest(patterns, base_dir=None):
    """Latest export: date in the file name wins, file mtime breaks ties / covers undated names."""
    base = _base(base_dir)
    hits = []
    for p in patterns:
        hits += glob.glob(os.path.join(glob.escape(base), p))
    hits = [h for h in hits if os.path.isfile(h)]
    return max(hits, key=lambda h: (_file_date(h), os.path.getmtime(h))) if hits else None


def newest_holdings(base_dir=None):
    """Path of the latest 'Innehav ... Export' file (the single source for current holdings)."""
    return _newest(['Innehav*Export*.csv'], base_dir)


def find_sources(base_dir=None):
    return {
        'transactions': _newest(['transactions-and-notes-export*.csv'], base_dir),
        'holdings': newest_holdings(base_dir),
    }


def signature(base_dir=None):
    """Cheap change detector for the browser to poll."""
    out = {}
    for k, p in find_sources(base_dir).items():
        if p:
            st = os.stat(p)
            out[k] = {'file': os.path.basename(p), 'mtime': st.st_mtime, 'size': st.st_size}
        else:
            out[k] = None
    return out


def _table_from_bytes(raw, encodings=None):
    """(header, rows) from the raw bytes of a Nordnet CSV; raises ValueError when nothing usable is in it.
    Without `encodings` the order follows the file: UTF-16 when it has a UTF-16 BOM or NUL bytes (Nordnet's own exports),
    otherwise UTF-8 then cp1252 (decoding such text as UTF-16 can 'succeed' with garbage)."""
    if encodings is None:
        utf16 = raw[:2] in (b'\xff\xfe', b'\xfe\xff') or b'\x00' in raw[:200]
        encodings = ('utf-16', 'utf-8-sig', 'cp1252') if utf16 else ('utf-8-sig', 'cp1252')
    text = None
    for enc in encodings:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None or not text.strip():
        raise ValueError('unreadable or empty')
    first = text.split('\n', 1)[0]
    delim = '\t' if first.count('\t') >= first.count(';') else ';'
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        raise ValueError('unreadable or empty')
    return rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]


def _read_table(path):
    with open(path, 'rb') as f:
        return _table_from_bytes(f.read())


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
    return _parse_ledger_table(*_read_table(path))


def _parse_ledger_table(header, rows):
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
    return _parse_holdings_table(*_read_table(path))


def _parse_holdings_table(header, rows):
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
# upload validation (pure: bytes in, verdict out; used by profiles.py before anything is stored)
# --------------------------------------------------------------------------
HOLDINGS_NAME_RE = re.compile(r'^Innehav Tabell Export, accno (\d{4,20}), (\d{4}-\d{2}-\d{2})\.csv$', re.I)
# Older Nordnet exports, one file per table: aktier_kontonummer-N_DATE.csv (stocks / ETFs: GAV instead of GAV/snittkurs plus
# an extra native-currency 'Värde' column) and fonder_kontonummer-N_DATE.csv (funds: Snittkurs, 1 dag %, Senaste NAV,
# Inköpsv. SEK, no ISIN). Converted to the standard layout on upload; the two files of one date are combined by profiles.py.
AKTIER_NAME_RE = re.compile(r'^aktier_kontonummer-(\d{4,20})_(\d{4}-\d{2}-\d{2})\.csv$', re.I)
FONDER_NAME_RE = re.compile(r'^fonder_kontonummer-(\d{4,20})_(\d{4}-\d{2}-\d{2})\.csv$', re.I)
_ACCNO_RE = re.compile(r'^\d{4,20}$')


def _verdict(ok, error=None, **kw):
    out = {'ok': ok, 'error': error, 'accno': None, 'rows': 0}
    out.update(kw)
    return out


def validate_ledger(data):
    """Is `data` a Nordnet 'transactions-and-notes-export' (UTF-16, tab separated) of exactly ONE account?
    -> {ok, error, accno, rows, first_date, last_date}. Never raises, never touches the disk."""
    def bad(msg):
        return _verdict(False, msg, first_date=None, last_date=None)
    try:
        if not data:
            return bad('The file is empty.')
        try:
            header, rows = _table_from_bytes(data, ('utf-16',))
        except ValueError:
            return bad('Not a Nordnet transactions export (a UTF-16 text file is expected).')
        dep = _col(header, 'depå', 'depa')
        if _col(header, 'transaktionstyp') is None or dep is None:
            return bad('Not a Nordnet transactions export (the Transaktionstyp / Depå columns are missing).')
        try:
            ledger = _parse_ledger_table(header, rows)
        except ValueError as e:
            return bad(str(e))
        if not ledger:
            return bad('No transaction rows could be read.')
        if len(rows) - len(ledger) > max(5, len(rows) // 20):
            return bad(f'{len(rows) - len(ledger)} of {len(rows)} rows could not be read.')
        accs = {re.sub(r'[\s-]', '', r[dep]) for r in rows if dep < len(r) and r[dep].strip()}
        if not accs:
            return bad('No account number found in the Depå column.')
        if len(accs) > 1:
            return bad('The file mixes several accounts (' + ', '.join(sorted(accs)[:3]) + '); export one account at a time.')
        acc = accs.pop()
        if not _ACCNO_RE.match(acc):
            return bad('Unexpected account number in the Depå column.')
        dates = [t['date'] for t in ledger]
        return _verdict(True, None, accno=acc, rows=len(ledger), first_date=min(dates), last_date=max(dates))
    except Exception:
        return bad('The file could not be read as a Nordnet transactions export.')


STD_HEADER = ['Namn', 'Valuta', 'Antal', 'GAV/snittkurs', 'Idag %', 'Senaste kurs', 'Belåningsv.\xa0SEK', 'Värde\xa0SEK',
              'Avkast. %', 'Avkast.\xa0SEK', 'ISIN', 'Market']
_STD_FROM = [('namn',), ('valuta',), ('antal',), ('gav/snittkurs', 'gav', 'snittkurs'), ('idag %', '1 dag %'),
             ('senaste kurs', 'senaste nav'), ('belåningsv. sek',), ('värde sek',), ('avkast. %',), ('avkast. sek',), ('isin',), ('market',)]


def _std_bytes(rows):
    lines = ['\t'.join(STD_HEADER)] + ['\t'.join(r) for r in rows]
    return ('\ufeff' + '\r\n'.join(lines) + '\r\n').encode('utf-16-le')


def _standard_holdings(header, rows):
    """Bytes of any Nordnet holdings table (Innehav, aktier_kontonummer or fonder_kontonummer layout) in the standard
    'Innehav Tabell Export' layout: GAV / Snittkurs -> GAV/snittkurs, 1 dag % -> Idag %, Senaste NAV -> Senaste kurs,
    extra 'Värde' (native currency) and 'Inköpsv. SEK' dropped, ISIN / Market added empty when the old file has none."""
    norm = [h.strip().lower().replace('\xa0', ' ') for h in header]
    pos = [next((norm.index(n) for n in names if n in norm), None) for names in _STD_FROM]
    return _std_bytes([[(r[i].strip() if i is not None and i < len(r) else '') for i in pos] for r in rows])


def merge_standard(parts):
    """One standard-layout table from several standard-layout parts (stocks file + funds file of the same date)."""
    rows = []
    for raw in parts:
        _, r = _table_from_bytes(raw)
        rows.extend(r)
    return _std_bytes(rows)


def validate_holdings(data, filename):
    """Is `data` a Nordnet holdings export? The name may be 'Innehav Tabell Export, accno N, YYYY-MM-DD.csv' or the older
    'aktier_kontonummer-N_YYYY-MM-DD.csv' (stocks / ETFs only; converted to the standard layout, returned in 'data').
    -> {ok, error, accno, date, rows, data, kind ('innehav'|'aktier'|'fonder'), note}. Never raises, never touches the disk."""
    def bad(msg):
        return _verdict(False, msg, date=None)
    try:
        base = os.path.basename(str(filename or '').replace('\\', '/')).strip()
        kind = 'innehav'
        m = HOLDINGS_NAME_RE.match(base)
        if not m:
            m = AKTIER_NAME_RE.match(base)
            kind = 'aktier'
        if not m:
            m = FONDER_NAME_RE.match(base)
            kind = 'fonder'
        if not m:
            return bad("The file name must look like 'Innehav Tabell Export, accno 12345678, 2026-01-31.csv', 'aktier_kontonummer-12345678_2026-01-31.csv' or 'fonder_kontonummer-12345678_2026-01-31.csv' (the account number and date are read from it).")
        try:
            datetime.strptime(m.group(2), '%Y-%m-%d')
        except ValueError:
            return bad('The date in the file name is not a real date.')
        if not data:
            return bad('The file is empty.')
        try:
            header, rows = _table_from_bytes(data)
        except ValueError:
            return bad('The file is empty or not readable text.')
        if _col(header, 'namn') is None or _col(header, 'värde sek') is None:
            return bad('Not a Nordnet holdings export (the Namn / Värde SEK columns are missing).')
        holdings = _parse_holdings_table(header, rows)
        if not holdings or not any(h['value_sek'] for h in holdings.values()):
            return bad('No holdings rows with a value were found.')
        std = None if kind == 'innehav' else _standard_holdings(header, rows)
        return _verdict(True, None, accno=m.group(1), date=m.group(2), rows=len(holdings), data=std or data, kind=kind, note=None)
    except Exception:
        return bad('The file could not be read as a Nordnet holdings export.')


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
                if h['qty'] > st['qty']:
                    # holdings export is live; the ledger books a trade only after the next day's close
                    warnings.append(f"{name}: holdings show {h['qty']:g} but the ledger only has "
                                    f"{st['qty']:g} - probably bought today and not booked in the "
                                    f"ledger yet (re-export the ledger tomorrow).")
                else:
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
# deposit behaviour: when does money go in, and what was the portfolio doing?
# --------------------------------------------------------------------------
def dividend_analysis(ledger, assets, net_deposits, all_time_pnl, today=None):
    """Dividends received (UTDELNING) and the withholding tax booked against them (KÄLLSKATT etc.), from the ledger.
    They are already inside the account value (they land in cash), so the all-time result includes them; this
    only makes them visible: totals, per day / month, per asset and the yearly trend."""
    held = {a['isin']: a.get('held') for a in assets}
    days = defaultdict(lambda: {'gross': 0.0, 'tax': 0.0, 'n': 0})
    per = defaultdict(lambda: {'name': '', 'isin': '', 'gross': 0.0, 'tax': 0.0, 'n': 0, 'last': '', 'first': ''})
    for t in ledger:
        ty = t['type']
        if ty not in T_DIVIDEND and ty not in T_DIV_TAX:
            continue
        d = t['book']
        p = per[t['isin'] or t['name']]
        p['name'] = t['name'] or p['name']; p['isin'] = t['isin'] or p['isin']
        if ty in T_DIVIDEND:
            days[d]['gross'] += t['amount']; days[d]['n'] += 1
            p['gross'] += t['amount']; p['n'] += 1
            p['last'] = max(p['last'], d); p['first'] = min(p['first'] or d, d)
        else:
            days[d]['tax'] += -t['amount']; p['tax'] += -t['amount']
    if not days:
        return None
    series = [{'date': d, 'gross': round(v['gross'], 2), 'tax': round(v['tax'], 2),
               'net': round(v['gross'] - v['tax'], 2), 'n': v['n']} for d, v in sorted(days.items())]
    gross = sum(r['gross'] for r in series); tax = sum(r['tax'] for r in series)
    last = date.fromisoformat(series[-1]['date'])
    ref = today or max(last, date.today())
    ttm_from = (ref - timedelta(days=365)).isoformat()
    ttm = sum(r['net'] for r in series if r['date'] >= ttm_from)
    first = date.fromisoformat(series[0]['date'])
    months = max(1, (ref.year - first.year) * 12 + ref.month - first.month + 1)
    by_year = defaultdict(float)
    for r in series:
        by_year[r['date'][:4]] += r['net']
    payers = sorted(({'name': v['name'], 'isin': v['isin'], 'gross': round(v['gross'], 2), 'tax': round(v['tax'], 2),
                      'net': round(v['gross'] - v['tax'], 2), 'payments': v['n'], 'first': v['first'], 'last': v['last'],
                      'held': bool(held.get(v['isin']))} for v in per.values() if v['n']), key=lambda x: -x['net'])
    net = gross - tax
    top3 = sum(p['net'] for p in payers[:3])
    return {
        'series': series, 'payers': payers,
        'summary': {'gross': round(gross, 2), 'tax': round(tax, 2), 'net': round(net, 2), 'payments': sum(r['n'] for r in series),
                    'payers': len(payers), 'first': series[0]['date'], 'last': series[-1]['date'], 'ttm_net': round(ttm, 2),
                    'avg_month': round(net / months, 2), 'months': months,
                    'pct_of_deposits': round(net / net_deposits * 100, 2) if net_deposits else None,
                    'pct_of_result': round(net / all_time_pnl * 100, 1) if all_time_pnl and all_time_pnl > 0 else None,
                    'tax_pct': round(tax / gross * 100, 1) if gross else None,
                    'top3_share': round(top3 / net * 100, 1) if net > 0 else None,
                    'by_year': {k: round(v, 2) for k, v in sorted(by_year.items())},
                    'sold_payers': sum(1 for p in payers if not p['held'])},
    }


def deposit_behavior(trades, cash_events, assets, holdings_value, cash_balance):
    """Daily series of deposits, positions held, estimated portfolio value and a return index that
    ignores deposits (so a deposit never looks like a gain), plus one row per deposit day.

    No historical price feed is used: each position is priced from your own trades (SEK per share) and,
    for assets still held, drawn in a straight line to today's price from the holdings export. The
    curve is an estimate - it misses moves between your trades."""
    if not cash_events and not trades:
        return None
    flow = defaultdict(float)            # deposits + withdrawals (book date)
    dep = defaultdict(float)
    other = defaultdict(float)           # dividends, tax, interest, fees (book date)
    for d, kind, amt in cash_events:
        if kind == 'deposit':
            dep[d] += amt
            flow[d] += amt
        elif kind == 'withdrawal':
            flow[d] += amt
        else:
            other[d] += amt
    by_day = defaultdict(list)
    for t in trades:
        by_day[t['date']].append(t)
    first = min([d for d, _, _ in cash_events] + [t['date'] for t in trades])
    last = max([d for d, _, _ in cash_events] + [t['date'] for t in trades])
    day, end = date.fromisoformat(first), date.fromisoformat(last)

    pts = defaultdict(list)              # isin -> [(ordinal day, SEK price)]
    for t in trades:
        if t['price']:
            pts[t['isin']].append((date.fromisoformat(t['date']).toordinal(), t['price'] * (t['fx'] or 1.0)))
    for a in assets:
        if a.get('held') and a.get('qty') and a.get('value') and a['isin'] in pts:
            pts[a['isin']].append((end.toordinal(), a['value'] / a['qty']))

    def price_at(isin, o):
        p = pts[isin]
        for (o1, p1), (o2, p2) in zip(p, p[1:]):
            if o1 <= o <= o2:
                return p1 if o2 == o1 else p1 + (p2 - p1) * (o - o1) / (o2 - o1)
        return p[-1][1] if o > p[-1][0] else p[0][1]

    qty = {}
    cash_now, cum_dep, idx, prev_v = 0.0, 0.0, 100.0, 0.0
    series = []
    while day <= end:
        d = day.isoformat()
        buys = 0.0
        for t in by_day.get(d, ()):
            if t['side'] == 'BUY':
                cash_now -= t['amount']
                buys += t['amount']
            else:
                cash_now += t['amount']
            qty[t['isin']] = t['pos_after']
        cash_now += flow[d] + other[d]
        cum_dep += flow[d]
        value = cash_now + sum(q * price_at(i, day.toordinal()) for i, q in qty.items() if q > 1e-6 and pts[i])
        if prev_v > 500:
            idx *= (value - flow[d]) / prev_v
        prev_v = value
        series.append({'date': d, 'deposit': round(dep[d], 2), 'buys': round(buys, 2),
                       'cash': round(cash_now, 2), 'value': round(value, 2),
                       'net_deposited': round(cum_dep, 2),
                       'held': sum(1 for q in qty.values() if q > 1e-6), 'index': round(idx, 3)})
        day += timedelta(days=1)

    dates = [r['date'] for r in series]
    pos = {d: i for i, d in enumerate(dates)}

    def ret(i, n):                       # return of the index over the n days ending the day before i
        a, b = i - 1 - n, i - 1
        return (series[b]['index'] / series[a]['index'] - 1) * 100 if a >= 0 else None

    peak, dd_at = 0.0, []
    for r in series:
        peak = max(peak, r['index'])
        dd_at.append((r['index'] / peak - 1) * 100)

    events = []
    for i, r in enumerate(series):
        if r['deposit'] <= 0:
            continue
        spent = sum(x['buys'] for x in series[i:i + 3])
        events.append({'date': r['date'], 'amount': r['deposit'],
                       'cash_before': series[i - 1]['cash'] if i else 0.0,
                       'perf_5d': None if ret(i, 5) is None else round(ret(i, 5), 2),
                       'drawdown': round(dd_at[i - 1], 2) if i else 0.0,
                       'next_5d': None if i + 5 >= len(series) else
                       round((series[i + 5]['index'] / series[i]['index'] - 1) * 100, 2),
                       'spent_pct': round(min(spent / r['deposit'], 1.0) * 100)})

    def bucket(v):
        return None if v is None else 'down' if v <= -2 else 'up' if v >= 2 else 'flat'
    tot = sum(e['amount'] for e in events) or 1.0
    base_days = [bucket(ret(i, 5)) for i in range(len(series))]
    base_days = [b for b in base_days if b]
    groups = {}
    for k in ('down', 'flat', 'up'):
        ev = [e for e in events if bucket(e['perf_5d']) == k]
        groups[k] = {'deposits': len(ev), 'amount': round(sum(e['amount'] for e in ev), 2),
                     'amount_share': round(sum(e['amount'] for e in ev) / tot * 100, 1),
                     'baseline_share': round(base_days.count(k) / len(base_days) * 100, 1) if base_days else None}
    deep = [e for e in events if e['drawdown'] <= -5]
    empty = [e for e in events if e['cash_before'] < 1000]
    quick = [e for e in events if e['spent_pct'] >= 80]
    summary = {
        'deposits': len(events), 'total': round(tot, 2), 'groups': groups,
        'deep_drawdown': {'deposits': len(deep), 'amount_share': round(sum(e['amount'] for e in deep) / tot * 100, 1),
                          'baseline_share': round(sum(1 for x in dd_at if x <= -5) / len(dd_at) * 100, 1)},
        'cash_empty': {'deposits': len(empty), 'share': round(len(empty) / len(events) * 100, 1) if events else None},
        'spent_fast': {'deposits': len(quick), 'share': round(len(quick) / len(events) * 100, 1) if events else None},
        'avg_deposit': round(tot / len(events), 2) if events else None,
        'median_gap_days': None,
    }
    gaps = sorted((date.fromisoformat(b['date']) - date.fromisoformat(a['date'])).days
                  for a, b in zip(events, events[1:]))
    if gaps:
        summary['median_gap_days'] = gaps[len(gaps) // 2]
    return {'series': series, 'events': events, 'summary': summary,
            'est_end_value': series[-1]['value'] if series else None,
            'true_end_value': round(holdings_value + cash_balance, 2)}



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
_CACHE_MAX = 6                         # profiles kept in memory (least recently used leaves first)
_cache = OrderedDict()                 # base dir -> {'key': file signature, 'data': payload}
_cache_lock = threading.Lock()         # guards _cache and _dir_locks only; never held while parsing
_dir_locks = {}                        # base dir -> lock, so one profile is parsed once but others are never blocked


def _compute_payload(src, base):
    ledger = parse_ledger(src['transactions'])
    holdings = parse_holdings(src['holdings'])
    trades, assets, cash, cash_events, balance, warnings = build(ledger, holdings)
    if not src['holdings']:
        warnings.append('No Innehav*Export*.csv found - current values and unrealised P&L are unavailable.')
    insights = analyse(trades, assets, cash, cash_events, balance, holdings)
    ov = insights['overview']
    insights['deposit_behavior'] = deposit_behavior(trades, cash_events, assets, ov['holdings_value'], ov['cash_balance'])
    insights['dividends'] = dividend_analysis(ledger, assets, ov['net_deposits'], ov['all_time_pnl'])
    return {
        'generated': datetime.now().isoformat(timespec='seconds'),
        'sources': signature(base),
        'warnings': warnings,
        'trades': trades,
        'assets': assets,
        'insights': insights,
        'cashflows': [{'date': d, 'kind': k, 'amount': round(a, 2)} for d, k, a in cash_events if k in ('deposit', 'withdrawal')],
    }


def get_payload(base_dir=None):
    """Analytics payload of the CSVs in `base_dir` (None = project folder). Cached per folder, re-parsed when a file changes."""
    base = _base(base_dir)
    src = find_sources(base)
    if not src['transactions']:
        return {'error': 'No transactions-and-notes-export*.csv found for this profile.', 'code': 'no_files',
                'sources': signature(base)}
    key = tuple((p, os.path.getmtime(p), os.path.getsize(p)) if p else None for p in src.values())

    def hit():
        e = _cache.get(base)
        if e and e['key'] == key:
            _cache.move_to_end(base)
            return e['data']
        return None

    with _cache_lock:
        d = hit()
        lock = _dir_locks.setdefault(base, threading.Lock())
    if d is not None:
        return d
    with lock:                          # one parse per folder at a time; other folders run in parallel
        with _cache_lock:
            d = hit()
        if d is not None:
            return d
        payload = _compute_payload(src, base)
        with _cache_lock:
            _cache[base] = {'key': key, 'data': payload}
            _cache.move_to_end(base)
            while len(_cache) > _CACHE_MAX:
                old, _ = _cache.popitem(last=False)
                _dir_locks.pop(old, None)
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
