#!/usr/bin/env python3
"""
nordnet_sync.py — Nordnet holdings export sync
==============================================
Nordnet now exports ALL holdings (stocks, ETFs, funds) in one file:
  Innehav Tabell Export, accno 66262387, YYYY-MM-DD.csv
The dashboard and the Analytics page always use the NEWEST such file in this
folder (date in the file name wins, file mtime breaks ties).

This script:
  * copies new exports from your Downloads folder into the project folder
  * saves the previous export's positions as portfolio_baseline.json so the
    Portfolio page can show "last buy" (qty / price) after a new export

USAGE
-----
  python nordnet_sync.py              # rebuild baseline from the 2 newest exports in this folder
  python nordnet_sync.py --watch      # watch Downloads, copy new exports here (+ baseline)
  python nordnet_sync.py --watch --interval 60
  python nordnet_sync.py --api        # fetch live positions via a Nordnet session token (.env)
  python nordnet_sync.py --baseline   # same as the default

CREDENTIALS (API mode only)
---------------------------
.env in this folder:
  NORDNET_SESSION_TOKEN=<SESSION cookie from a logged-in browser>
  NORDNET_ACCOUNT=66262387
"""

import os
import sys
import time
import shutil
import re
import csv
import json
import argparse
from datetime import date
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

SCRIPT_DIR    = Path(__file__).parent.resolve()
ACCOUNT_NUM   = os.environ.get('NORDNET_ACCOUNT', '66262387')
DOWNLOADS_DIR = Path.home() / 'Downloads'

# ── .env loader ────────────────────────────────────────────────────────────────

def load_env():
    env_path = SCRIPT_DIR / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

# ── File-watcher mode ──────────────────────────────────────────────────────────

HOLDINGS_PATTERN = f'Innehav*Export*{ACCOUNT_NUM}*.csv'
BASELINE_OUT     = SCRIPT_DIR / 'portfolio_baseline.json'

# ── CSV parser (matches app.js: UTF-16LE/BE + Swedish decimals) ────────────────

def parse_se(s: str) -> float:
    """'1 234,56' -> 1234.56"""
    if not s:
        return 0.0
    s = s.strip().replace('\xa0', '').replace('\u00a0', '').replace(' ', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0

def parse_nordnet_csv(path: Path) -> list[dict]:
    """Read a Nordnet CSV (UTF-16 LE/BE with BOM, tab-separated)."""
    raw = path.read_bytes()
    if raw[:2] == b'\xff\xfe':
        text = raw.decode('utf-16-le')
    elif raw[:2] == b'\xfe\xff':
        text = raw.decode('utf-16-be')
    else:
        text = raw.decode('utf-8')
    text = text.lstrip('\ufeff')
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split('\t')]
    rows = []
    for line in lines[1:]:
        cols = [c.strip() for c in line.split('\t')]
        row = {headers[i]: cols[i] if i < len(cols) else '' for i in range(len(headers))}
        if row.get(headers[0]):          # skip blank rows
            rows.append(row)
    return rows

def export_date(p: Path) -> str:
    """YYYY-MM-DD from the export file name ('' if absent)."""
    m = re.search(r'\d{4}-\d{2}-\d{2}', p.name)
    return m.group(0) if m else ''

def sort_exports(paths) -> list[Path]:
    """Oldest -> newest: date in the file name first, mtime as tie-breaker."""
    return sorted(paths, key=lambda p: (export_date(p), p.stat().st_mtime))

def list_exports(folder: Path) -> list[Path]:
    return sort_exports(p for p in folder.glob(HOLDINGS_PATTERN) if p.is_file())

def build_baseline_json(path: Path) -> dict:
    """
    Parse one holdings export into the snapshot format used by app.js:
      { "Stock Name": { "qty": 5.0, "gav": 250.0 }, ... }
    """
    snap = {}
    for row in parse_nordnet_csv(path):
        name = row.get('Namn', '').strip()
        if not name:
            continue
        keys = list(row.keys())
        qty_key = next((k for k in keys if 'antal' in k.lower()), None)
        gav_key = next((k for k in keys if k.strip() == 'GAV/snittkurs'
                        or 'snittkurs' in k.lower() or k.strip() == 'GAV'), None)
        snap[name] = {
            'qty': parse_se(row.get(qty_key, '0')) if qty_key else 0.0,
            'gav': parse_se(row.get(gav_key, '0')) if gav_key else 0.0,
        }
    return snap

def save_baseline(src: Path | None = None) -> bool:
    """Write portfolio_baseline.json from `src` (default: second-newest export in the folder)."""
    if src is None:
        exports = list_exports(SCRIPT_DIR)
        if len(exports) < 2:
            print('[baseline] Need at least two Innehav exports to build a baseline '
                  f'(found {len(exports)}).')
            return False
        src = exports[-2]
    snap = build_baseline_json(src)
    if not snap:
        print(f'[baseline] {src.name} has no readable rows.')
        return False
    # __ts (Unix ms) lets app.js know this baseline is newer than localStorage
    snap['__ts'] = int(time.time() * 1000)
    BASELINE_OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[baseline] {src.name} -> {BASELINE_OUT.name} ({len(snap) - 1} positions)')
    return True

def copy_new_exports(src_folder: Path) -> bool:
    """Copy exports from src_folder that are not yet in the project folder. Rebuild baseline if any."""
    copied = False
    for src in list_exports(src_folder):
        dst = SCRIPT_DIR / src.name
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            continue
        shutil.copy2(src, dst)
        print(f'[sync] Copied {src.name}')
        copied = True
    if copied:
        save_baseline()
    return copied

def watch_mode(interval_seconds: int = 60):
    print(f'[watch] Monitoring {DOWNLOADS_DIR} every {interval_seconds}s ...')
    print(f'        Looking for:  {HOLDINGS_PATTERN}')
    print('        Press Ctrl+C to stop.\n')
    while True:
        copy_new_exports(DOWNLOADS_DIR)
        time.sleep(interval_seconds)

# ── Nordnet REST API mode ──────────────────────────────────────────────────────
# Nordnet's public API: https://www.nordnet.se/api/2/
# Auth: HTTP Basic (base64 username:password) + TOTP/BankID
#
# Due to BankID 2FA requirements, API mode requires a valid session token.
# Session tokens can be captured from browser DevTools (Network tab) after
# logging in manually, then pasted into .env as NORDNET_SESSION_TOKEN.

try:
    import urllib.request, urllib.error, base64, ssl
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

NORDNET_API  = 'https://www.nordnet.se/api/2'
SESSION_FILE = SCRIPT_DIR / '.nordnet_session.json'

def api_headers(session_token: str) -> dict:
    return {
        'Accept':           'application/json',
        'Accept-Language':  'sv-SE',
        'Cookie':           f'NEXT_LOCALE=sv; SESSION={session_token}',
    }

def api_get(path: str, session_token: str) -> dict:
    url = NORDNET_API + path
    req = urllib.request.Request(url, headers=api_headers(session_token))
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read())

def fetch_positions_api(session_token: str, account_id: str) -> dict:
    """
    Returns raw positions list from /accounts/{id}/positions
    Each position has keys like:
      instrument.name, instrument.currency, qty,
      average_purchase_price.value, main_market_price.value,
      profit_loss_acc.value, market_value_acc.value
    """
    data = api_get(f'/accounts/{account_id}/positions', session_token)
    return data

HOLDINGS_COLUMNS = ['Namn', 'Valuta', 'Antal', 'GAV/snittkurs', 'Idag %', 'Senaste kurs',
                    'Belåningsv. SEK', 'Värde SEK', 'Avkast. %', 'Avkast. SEK']

def positions_to_csv_rows(positions: list) -> list[dict]:
    """Convert Nordnet position objects to rows in the combined 'Innehav' export format."""
    rows = []
    for pos in positions:
        instr = pos.get('instrument', {})
        val   = pos.get('market_value_acc', {}).get('value', 0)
        ret   = pos.get('profit_loss_acc', {}).get('value', 0)
        ret_pct = (ret / (val - ret) * 100) if (val - ret) > 0 else 0
        rows.append({
            'Namn': instr.get('name', ''), 'Valuta': instr.get('currency', 'SEK'),
            'Antal': pos.get('qty', 0),
            'GAV/snittkurs': pos.get('average_purchase_price', {}).get('value', 0),
            'Idag %': 0,
            'Senaste kurs': pos.get('main_market_price', {}).get('value', 0),
            'Belåningsv. SEK': 0, 'Värde SEK': val,
            'Avkast. %': round(ret_pct, 2), 'Avkast. SEK': ret,
        })
    return rows

def write_csv(rows: list[dict], out_path: Path):
    if not rows:
        print(f'[api] No data to write to {out_path.name}')
        return
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=HOLDINGS_COLUMNS, delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
    print(f'[api] Wrote {len(rows)} rows -> {out_path.name}')

def api_mode():
    load_env()
    session_token = os.environ.get('NORDNET_SESSION_TOKEN', '')
    if not session_token:
        print("""
[api] No NORDNET_SESSION_TOKEN found.

To get your session token:
  1. Open nordnet.se in Chrome/Firefox
  2. Log in normally (BankID etc.)
  3. Open DevTools -> Network -> filter "api/2"
  4. Find any request, copy the SESSION cookie value
  5. Add to .env:  NORDNET_SESSION_TOKEN=<value>

Then re-run: python nordnet_sync.py
""")
        sys.exit(1)

    account_id = os.environ.get('NORDNET_ACCOUNT', ACCOUNT_NUM)
    print(f'[api] Fetching positions for account {account_id} …')

    try:
        positions = fetch_positions_api(session_token, account_id)
        all_pos   = positions if isinstance(positions, list) else positions.get('positions', [])

        out = SCRIPT_DIR / f'Innehav Tabell Export, accno {account_id}, {date.today().isoformat()}.csv'
        write_csv(positions_to_csv_rows(all_pos), out)
        save_baseline()   # baseline = the export before this one
        print('[api] Done. The dashboard picks it up within 5 minutes.')

    except urllib.error.HTTPError as e:
        if e.code == 401:
            print('[api] Session expired. Please refresh your NORDNET_SESSION_TOKEN.')
        else:
            print(f'[api] HTTP error {e.code}: {e.reason}')
        sys.exit(1)
    except Exception as e:
        print(f'[api] Error: {e}')
        sys.exit(1)

# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Sync Nordnet portfolio to dashboard CSV files')
    parser.add_argument('--watch',    action='store_true',
                        help='Watch Downloads folder for new Nordnet exports')
    parser.add_argument('--api',      action='store_true',
                        help='Fetch live data via Nordnet API (needs SESSION token)')
    parser.add_argument('--baseline', action='store_true',
                        help='Rebuild portfolio_baseline.json from the second-newest export')
    parser.add_argument('--interval', type=int, default=60,
                        help='Watch interval in seconds (default: 60)')
    args = parser.parse_args()

    if args.watch:
        watch_mode(args.interval)
    elif args.api:
        api_mode()
    else:
        # Default (and --baseline): exports are already in this folder - refresh the baseline
        save_baseline()

if __name__ == '__main__':
    main()
