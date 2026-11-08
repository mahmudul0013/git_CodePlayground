"""
profiles.py - per-user data folders and validated uploads.

    <data root>/profiles/<uid>/
        transactions-and-notes-export.csv        full ledger (newest upload replaces it)
        Innehav Tabell Export, accno N, DATE.csv  holdings exports (newest 3 kept)
        parts/aktier-DATE.csv, parts/fonder-DATE.csv  the two older per-table exports (merged into the Innehav file of that date)
        baseline.json                             previous-state snapshot for the last-buy tags
        meta.json                                 row counts / dates of the last uploads (shown on the account page)

The folder name is the random uid, never the username or the account number. File names inside are rebuilt by the
server from validated content; a client-supplied name is never used as a path. Python stdlib only.
"""
import glob
import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

import auth

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_UPLOAD = 8 * 1024 * 1024
KEEP_HOLDINGS = 3
LEDGER_NAME = 'transactions-and-notes-export.csv'
HOLD_RE = re.compile(r'^Innehav Tabell Export, accno (\d{3,20}), (\d{4}-\d{2}-\d{2})\.csv$')
UID_RE = re.compile(r'^[0-9a-f]{16}$')

_LOCK = threading.RLock()


# ───────── validators: use trade_analytics' own parsers when present (worker B), else minimal ones ─────────
def _ta():
    import trade_analytics
    return trade_analytics


def _decode(data):
    for enc in ('utf-16', 'utf-8-sig', 'cp1252'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _table(data):
    text = _decode(data)
    if not text:
        return None, []
    import csv
    first = text.split('\n', 1)[0]
    delim = '\t' if first.count('\t') >= first.count(';') else ';'
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        return None, []
    return [h.replace(' ', ' ').strip().lower() for h in rows[0]], [r for r in rows[1:] if any(c.strip() for c in r)]


def _fallback_ledger(data):
    head, rows = _table(data)
    if not head or 'transaktionstyp' not in head:
        return {'ok': False, 'error': 'This does not look like a Nordnet transactions export (no "Transaktionstyp" column).'}
    ix = next((i for i, h in enumerate(head) if h.startswith('dep')), None)
    if ix is None:
        return {'ok': False, 'error': 'The transactions file has no account (Depå) column.'}
    accs = {r[ix].strip() for r in rows if len(r) > ix and r[ix].strip()}
    if len(accs) != 1:
        return {'ok': False, 'error': f'The transactions file must contain exactly one account (found {len(accs)}).'}
    di = next((i for i, h in enumerate(head) if h.startswith('bokf')), None)
    dates = sorted(r[di].strip() for r in rows if di is not None and len(r) > di and r[di].strip())
    return {'ok': True, 'accno': accs.pop(), 'rows': len(rows), 'first_date': dates[0] if dates else None, 'last_date': dates[-1] if dates else None}


def _fallback_holdings(data, filename):
    m = HOLD_RE.match(os.path.basename(filename or ''))
    if not m:
        return {'ok': False, 'error': 'The holdings file must keep its Nordnet name: "Innehav Tabell Export, accno N, YYYY-MM-DD.csv".'}
    head, rows = _table(data)
    if not head or 'namn' not in head or not any(h.startswith('antal') for h in head):
        return {'ok': False, 'error': 'This does not look like a Nordnet holdings export (no "Namn" / "Antal" columns).'}
    if not rows:
        return {'ok': False, 'error': 'The holdings file has no rows.'}
    return {'ok': True, 'accno': m.group(1), 'date': m.group(2), 'rows': len(rows)}


def validate_ledger(data):
    fn = getattr(_ta(), 'validate_ledger', None)
    try:
        return fn(data) if fn else _fallback_ledger(data)
    except Exception as e:
        return {'ok': False, 'error': f'Could not read the transactions file ({type(e).__name__}).'}


def validate_holdings(data, filename):
    fn = getattr(_ta(), 'validate_holdings', None)
    try:
        return fn(data, filename) if fn else _fallback_holdings(data, filename)
    except Exception as e:
        return {'ok': False, 'error': f'Could not read the holdings file ({type(e).__name__}).'}


# ───────── paths ─────────
def profile_dir(uid, create=False):
    if not isinstance(uid, str) or not UID_RE.match(uid):
        raise ValueError('bad uid')
    d = os.path.join(auth.data_dir(), 'profiles', uid)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _holdings_files(d):
    def key(p):
        m = re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(p))
        return (m.group(0) if m else '', os.path.getmtime(p))
    return sorted((p for p in glob.glob(os.path.join(glob.escape(d), 'Innehav*Export*.csv')) if os.path.isfile(p)), key=key)


def has_ledger(uid):
    return os.path.isfile(os.path.join(profile_dir(uid), LEDGER_NAME))


def has_holdings(uid):
    return bool(_holdings_files(profile_dir(uid)))


def has_files(uid):
    return has_ledger(uid) and has_holdings(uid)


def _atomic_write(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _meta(uid):
    try:
        with open(os.path.join(profile_dir(uid), 'meta.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_meta(uid, meta):
    _atomic_write(os.path.join(profile_dir(uid, True), 'meta.json'), json.dumps(meta).encode('utf-8'))


def status(uid):
    d = profile_dir(uid)
    u = auth.get_user(uid) or {}
    meta = _meta(uid)
    hf = _holdings_files(d)
    led = os.path.isfile(os.path.join(d, LEDGER_NAME))
    h = None
    if hf:
        name = os.path.basename(hf[-1])
        m = HOLD_RE.match(name)
        mh = meta.get('holdings') or {}
        rows_n = mh.get('rows') if mh.get('file') == name else _count_rows(Path(hf[-1]).read_bytes())
        h = {'file': name, 'date': m.group(2) if m else mh.get('date'), 'rows': rows_n}
    l = None
    if led:
        ml = meta.get('ledger') or {}
        l = {'rows': ml.get('rows'), 'first_date': ml.get('first_date'), 'last_date': ml.get('last_date')}
    updated = max([os.path.getmtime(p) for p in hf + ([os.path.join(d, LEDGER_NAME)] if led else [])] or [0]) or None
    return {'has_files': bool(h and l), 'accno': u.get('accno'), 'holdings': h, 'ledger': l, 'updated': updated}


# ───────── uploads ─────────
def _err(code, message):
    return {'ok': False, 'error': code, 'message': message}


def _write_baseline(d, prev_path):
    try:
        import nordnet_sync
        snap = nordnet_sync.build_baseline_json(Path(prev_path))
        if snap:
            snap['__ts'] = int(time.time() * 1000)
            _atomic_write(os.path.join(d, 'baseline.json'), json.dumps(snap, ensure_ascii=False).encode('utf-8'))
    except Exception:
        pass     # no baseline just means no gold last-buy tags


def _merge_parts(paths):
    ta = _ta()
    return ta.merge_standard([Path(p).read_bytes() for p in paths])


def _count_rows(data):
    try:
        return len(_ta()._table_from_bytes(data)[1])
    except Exception:
        return None


def _summ(data):
    """{name: (qty, value_sek)} of a standard-layout holdings file, None when unreadable."""
    try:
        ta = _ta()
        h, r = ta._table_from_bytes(data)
        return {k: (x['qty'], x['value_sek']) for k, x in ta._parse_holdings_table(h, r).items()}
    except Exception:
        return None


def _cmp_holdings(cur, new, cur_date, new_date):
    added, removed = sorted(set(new) - set(cur)), sorted(set(cur) - set(new))
    changed = sum(1 for k in set(cur) & set(new) if abs(cur[k][0] - new[k][0]) > 1e-9)
    vc, vn = sum(v for _, v in cur.values()), sum(v for _, v in new.values())
    return {'current_date': cur_date, 'upload_date': new_date, 'positions_current': len(cur), 'positions_upload': len(new),
            'added': added[:5], 'added_n': len(added), 'removed': removed[:5], 'removed_n': len(removed), 'qty_changed': changed,
            'value_current': round(vc), 'value_upload': round(vn), 'value_diff': round(vn - vc)}


def save_upload(uid, kind, data, filename='', confirm=False):
    """Validate and store one uploaded export. Returns {ok, ...} or {ok False, error, message}.
    Holdings: the answer carries `compare` against the file that is running now and `warning: 'older'` when the upload is older.
    Ledger: a smaller or earlier-ending ledger than the running one is NOT stored unless confirm=True (error 'confirm_needed')."""
    if kind not in ('holdings', 'ledger'):
        return _err('invalid', 'Unknown file type.')
    if not isinstance(data, (bytes, bytearray)) or not data:
        return _err('invalid', 'The file is empty.')
    if len(data) > MAX_UPLOAD:
        return _err('too_large', f'The file is larger than {MAX_UPLOAD // (1024 * 1024)} MB.')
    data = bytes(data)
    v = validate_ledger(data) if kind == 'ledger' else validate_holdings(data, filename)
    if not v.get('ok'):
        return _err('invalid', v.get('error') or 'The file could not be read.')
    accno = str(v['accno'])
    part = v.get('kind') if kind == 'holdings' and v.get('kind') in ('aktier', 'fonder') else None
    if kind == 'holdings' and v.get('data'):
        data = bytes(v['data'])                  # standard layout (older aktier_ / fonder_ files are converted)
    with _LOCK:
        me = auth.get_user(uid)
        if not me:
            return _err('invalid', 'Unknown user.')
        if me.get('accno') and me['accno'] != accno:
            return _err('accno_mismatch', f'This file is from account {accno}, but your profile is bound to account {me["accno"]}.')
        owner = auth.accno_owner(accno)
        if owner and owner != uid:
            return _err('accno_taken', f'Account {accno} already belongs to another profile.')
        if not auth.bind_accno(uid, accno):
            return _err('accno_taken', f'Account {accno} could not be bound to your profile.')
        d = profile_dir(uid, True)
        meta = _meta(uid)
        out = {'ok': True, 'accno': accno, 'rows': v.get('rows')}
        if kind == 'ledger':
            cur = meta.get('ledger') if os.path.isfile(os.path.join(d, LEDGER_NAME)) else None
            if cur and cur.get('rows'):
                cmpd = {'rows_current': cur.get('rows'), 'rows_upload': v.get('rows'), 'first_current': cur.get('first_date'), 'last_current': cur.get('last_date'),
                        'first_upload': v.get('first_date'), 'last_upload': v.get('last_date'), 'rows_diff': (v.get('rows') or 0) - cur['rows']}
                smaller = (v.get('rows') or 0) < cur['rows'] or (v.get('last_date') or '') < (cur.get('last_date') or '') or (v.get('first_date') or '') > (cur.get('first_date') or '')
                if smaller and not confirm:
                    return {'ok': False, 'error': 'confirm_needed', 'compare': cmpd,
                            'message': (f'The running transactions file has {cur["rows"]} rows ({cur.get("first_date")} to {cur.get("last_date")}); this one has '
                                        f'{v.get("rows")} rows ({v.get("first_date")} to {v.get("last_date")}). Replacing it would lose {max(0, cur["rows"] - (v.get("rows") or 0))} rows and could hide trades.')}
                out['compare'] = cmpd
            _atomic_write(os.path.join(d, LEDGER_NAME), data)
            meta['ledger'] = {'rows': v.get('rows'), 'first_date': v.get('first_date'), 'last_date': v.get('last_date'), 'uploaded': time.time()}
            out.update(first_date=v.get('first_date'), last_date=v.get('last_date'))
        else:
            name = f'Innehav Tabell Export, accno {accno}, {v["date"]}.csv'
            if part:
                # older one-table exports: keep each part, the Innehav file of that date is the merge of the parts present
                pdir = os.path.join(d, 'parts')
                os.makedirs(pdir, exist_ok=True)
                _atomic_write(os.path.join(pdir, f'{part}-{v["date"]}.csv'), data)
                present = [k for k in ('aktier', 'fonder') if os.path.isfile(os.path.join(pdir, f'{k}-{v["date"]}.csv'))]
                data = _merge_parts([os.path.join(pdir, f'{k}-{v["date"]}.csv') for k in present])
                rows_n = _count_rows(data)
                out['rows'] = rows_n
                missing = [k for k in ('aktier', 'fonder') if k not in present]
                out['note'] = ('Stocks and funds files of this date combined.' if not missing else
                               ('Stocks / ETFs file added. Funds are not included until you upload the matching fonder_kontonummer file of the same date (or the combined Innehav export).'
                                if missing == ['fonder'] else
                                'Funds file added. Stocks and ETFs are not included until you upload the matching aktier_kontonummer file of the same date (or the combined Innehav export).'))
            else:
                try:                              # a full Innehav export of this date supersedes any parts
                    for k in ('aktier', 'fonder'):
                        os.remove(os.path.join(d, 'parts', f'{k}-{v["date"]}.csv'))
                except OSError:
                    pass
                rows_n = v.get('rows')
            before = _holdings_files(d)
            cur_path = before[-1] if before else None
            cur_date = (re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(cur_path)) or [None])[0] if cur_path else None
            if cur_path:
                a_, b_ = _summ(Path(cur_path).read_bytes()), _summ(data)
                if a_ is not None and b_ is not None:
                    out['compare'] = _cmp_holdings(a_, b_, cur_date, v['date'])
                if cur_date and v['date'] < cur_date:
                    out['warning'] = 'older'
                    out['note'] = ((out.get('note') + ' ') if out.get('note') else '') + (f'This export ({v["date"]}) is older than the one running now ({cur_date}). '
                                                                                      f'It is kept as history; the dashboard keeps using {cur_date}.')
                elif cur_date and v['date'] == cur_date:
                    out['note'] = ((out.get('note') + ' ') if out.get('note') else '') + f'It replaces the running file of the same date ({cur_date}).'
            prev = before[-1] if before and os.path.basename(before[-1]) != name else (before[-2] if len(before) > 1 else None)
            _atomic_write(os.path.join(d, name), data)
            files = _holdings_files(d)
            for old in files[:-KEEP_HOLDINGS]:
                try:
                    os.remove(old)
                except OSError:
                    pass
                for k in ('aktier', 'fonder'):
                    mm = re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(old))
                    try:
                        os.remove(os.path.join(d, 'parts', f'{k}-{mm.group(0)}.csv'))
                    except (OSError, AttributeError):
                        pass
            newest = _holdings_files(d)[-1]
            if prev and os.path.basename(newest) == name and os.path.abspath(prev) != os.path.abspath(newest):
                _write_baseline(d, prev)         # the previous export becomes the "before" state of the last-buy tags
            elif len(_holdings_files(d)) >= 2 and not os.path.exists(os.path.join(d, 'baseline.json')):
                _write_baseline(d, _holdings_files(d)[-2])      # an older export uploaded after the newer one still seeds the baseline
            if os.path.basename(newest) == name:
                meta['holdings'] = {'file': name, 'date': v['date'], 'rows': rows_n, 'uploaded': time.time()}
            out.update(date=v['date'], running_date=(re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(newest)) or [None])[0])
        _save_meta(uid, meta)
        return out


def baseline(uid):
    try:
        with open(os.path.join(profile_dir(uid), 'baseline.json'), encoding='utf-8') as f:
            b = json.load(f)
        return b if isinstance(b, dict) else {}
    except (OSError, ValueError):
        return {}


def import_legacy(uid):
    """Copy the project-folder exports (the pre-multi-user layout) into this profile. The originals stay untouched.
    Copies the ledger and the two newest holdings exports (the older one seeds the last-buy baseline)."""
    res = {'ledger': False, 'holdings': 0, 'error': None}
    led = [p for p in glob.glob(os.path.join(HERE, 'transactions-and-notes-export*.csv')) if os.path.isfile(p)]
    if led:
        newest = max(led, key=os.path.getmtime)
        r = save_upload(uid, 'ledger', Path(newest).read_bytes(), os.path.basename(newest))
        res['ledger'] = bool(r.get('ok'))
        if not r.get('ok'):
            res['error'] = r.get('message')
    hold = [p for p in glob.glob(os.path.join(HERE, 'Innehav*Export*.csv')) if os.path.isfile(p)]
    hold.sort(key=lambda p: (re.findall(r'\d{4}-\d{2}-\d{2}', os.path.basename(p)) or [''])[0])
    for p in hold[-2:]:                                    # oldest of the two first, so the baseline comes from it
        r = save_upload(uid, 'holdings', Path(p).read_bytes(), os.path.basename(p))
        if r.get('ok'):
            res['holdings'] += 1
        elif not res['error']:
            res['error'] = r.get('message')
    return res


def delete_profile(uid):
    with _LOCK:
        d = profile_dir(uid)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        auth.unbind_accno(uid)
