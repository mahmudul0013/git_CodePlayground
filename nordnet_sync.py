#!/usr/bin/env python3
"""
nordnet_sync.py — Nordnet Portfolio CSV Sync
=============================================
Fetches your current holdings from Nordnet and writes two CSV files
that the trading dashboard picks up automatically:
  portfolio_stocks.csv
  portfolio_funds.csv

USAGE
-----
  # One-shot fetch
  python nordnet_sync.py

  # Watch your Downloads folder for new Nordnet exports and copy them
  python nordnet_sync.py --watch

  # Run once, then every N minutes (no Nordnet credentials needed)
  python nordnet_sync.py --watch --interval 60

CREDENTIALS (for API mode)
--------------------------
Create a file called .env in the same folder:
  NORDNET_USER=your-username-or-email
  NORDNET_PASS=your-password
  NORDNET_ACCOUNT=66262387   # your account number

Or set these as environment variables before running.

NOTE: Nordnet uses BankID / 2FA for web login, which makes full
automation difficult.  The --watch mode is the recommended approach:
  1. Export CSVs from nordnet.se (Mitt Nordnet -> Depå -> Exportera)
  2. Save them to your Downloads folder
  3. This script detects the new files and copies them here.
"""

import os
import sys
import time
import shutil
import glob
import csv
import json
import argparse
from datetime import date
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

SCRIPT_DIR    = Path(__file__).parent.resolve()
STOCKS_OUT    = SCRIPT_DIR / 'portfolio_stocks.csv'
FUNDS_OUT     = SCRIPT_DIR / 'portfolio_funds.csv'
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

STOCKS_PATTERN  = f'aktier_kontonummer-{ACCOUNT_NUM}_*.csv'
FUNDS_PATTERN   = f'fonder_kontonummer-{ACCOUNT_NUM}_*.csv'
BASELINE_OUT    = SCRIPT_DIR / 'portfolio_baseline.json'

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

def build_baseline_json(stocks_path: Path | None, funds_path: Path | None) -> dict:
    """
    Parse old CSV files into the snapshot format used by app.js:
      { "Stock Name": { "qty": 5.0, "gav": 250.0 }, ... }
    """
    snap = {}
    sources = []
    if stocks_path and stocks_path.exists():
        sources.append((stocks_path, 'GAV'))
    if funds_path and funds_path.exists():
        sources.append((funds_path, 'Snittkurs'))

    for path, gav_col_hint in sources:
        rows = parse_nordnet_csv(path)
        if not rows:
            continue
        keys = list(rows[0].keys())
        # Find qty and gav column names flexibly
        qty_key = next((k for k in keys if 'antal' in k.lower()), None)
        gav_key = next((k for k in keys if k.strip() == gav_col_hint), None) \
               or next((k for k in keys if 'snittkurs' in k.lower() or k.strip() == 'GAV'), None)
        for row in rows:
            name = row.get('Namn', '').strip()
            if not name or not qty_key:
                continue
            snap[name] = {
                'qty': parse_se(row.get(qty_key, '0')),
                'gav': parse_se(row.get(gav_key, '0')) if gav_key else 0.0,
            }
    return snap

def save_baseline(stocks_src: Path | None = None, funds_src: Path | None = None):
    """Build baseline JSON from given (or current portfolio) CSV files."""
    import time as _time
    s = stocks_src or STOCKS_OUT
    f = funds_src  or FUNDS_OUT
    snap = build_baseline_json(s if s.exists() else None,
                               f if f.exists() else None)
    if snap:
        # __ts (Unix ms) lets app.js know this baseline is newer than localStorage
        snap['__ts'] = int(_time.time() * 1000)
        BASELINE_OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'[baseline] Saved {len(snap)} positions -> {BASELINE_OUT.name}')
    else:
        print('[baseline] Nothing to save (no readable CSV found).')

def find_latest(folder: Path, pattern: str) -> Path | None:
    matches = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None

def copy_if_newer(src: Path, dst: Path) -> bool:
    """Copy src -> dst if src is newer.  Saves baseline BEFORE overwriting.  Returns True if copied."""
    if not src.exists():
        return False
    if dst.exists() and src.stat().st_mtime <= dst.stat().st_mtime:
        return False
    # Save the CURRENT (about-to-be-replaced) portfolio as baseline so app.js
    # can detect the diff on next load
    if dst == STOCKS_OUT and STOCKS_OUT.exists():
        save_baseline()   # reads current STOCKS_OUT + FUNDS_OUT
    shutil.copy2(src, dst)
    print(f'[sync] Copied {src.name} -> {dst.name}')
    return True

def watch_mode(interval_seconds: int = 60):
    print(f'[watch] Monitoring {DOWNLOADS_DIR} every {interval_seconds}s …')
    print(f'        Looking for:  {STOCKS_PATTERN}')
    print(f'                      {FUNDS_PATTERN}')
    print('        Press Ctrl+C to stop.\n')
    while True:
        stocks_src = find_latest(DOWNLOADS_DIR, STOCKS_PATTERN)
        funds_src  = find_latest(DOWNLOADS_DIR, FUNDS_PATTERN)
        if stocks_src:
            copy_if_newer(stocks_src, STOCKS_OUT)
        if funds_src:
            copy_if_newer(funds_src, FUNDS_OUT)
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

def positions_to_csv_rows(positions: list, is_fund: bool) -> list[dict]:
    """Convert Nordnet position objects to rows matching the CSV format."""
    rows = []
    for pos in positions:
        instr = pos.get('instrument', {})
        name  = instr.get('name', '')
        cur   = instr.get('currency', 'SEK')
        qty   = pos.get('qty', 0)
        avg   = pos.get('average_purchase_price', {}).get('value', 0)
        price = pos.get('main_market_price', {}).get('value', 0)
        val   = pos.get('market_value_acc', {}).get('value', 0)
        ret   = pos.get('profit_loss_acc', {}).get('value', 0)
        ret_pct = (ret / (val - ret) * 100) if (val - ret) > 0 else 0

        if is_fund:
            rows.append({
                'Namn': name, 'Valuta': cur, 'Antal': qty,
                'Snittkurs': avg, '1 dag %': 0,
                'Senaste NAV': price,
                'Belåningsvärde SEK': 0,
                'Inköpsvärde SEK': val - ret,
                'Värde SEK': val,
                'Avkast. %': round(ret_pct, 2),
                'Avkast. SEK': ret,
            })
        else:
            rows.append({
                'Namn': name, 'Valuta': cur, 'Antal': qty,
                'GAV': avg, 'Idag %': 0,
                'Senaste kurs': price,
                'Belåningsvärde SEK': 0,
                'Värde': qty * price,
                'Värde SEK': val,
                'Avkast. %': round(ret_pct, 2),
                'Avkast. SEK': ret,
            })
    return rows

def write_csv(rows: list[dict], out_path: Path):
    if not rows:
        print(f'[api] No data to write to {out_path.name}')
        return
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter='\t')
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

        # Nordnet instrument types: 1=equity, 2=fund
        stocks = [p for p in all_pos if p.get('instrument', {}).get('instrument_type') != 'FUND']
        funds  = [p for p in all_pos if p.get('instrument', {}).get('instrument_type') == 'FUND']

        # Save current portfolio as baseline BEFORE overwriting, so the dashboard
        # can detect new buys by comparing old vs new on next load
        if STOCKS_OUT.exists():
            save_baseline()
        write_csv(positions_to_csv_rows(stocks, is_fund=False), STOCKS_OUT)
        write_csv(positions_to_csv_rows(funds,  is_fund=True),  FUNDS_OUT)
        print('[api] Done. The dashboard will pick up new files within 5 minutes.')

    except urllib.error.HTTPError as e:
        if e.code == 401:
            print('[api] Session expired. Please refresh your NORDNET_SESSION_TOKEN.')
        else:
            print(f'[api] HTTP error {e.code}: {e.reason}')
        sys.exit(1)
    except Exception as e:
        print(f'[api] Error: {e}')
        sys.exit(1)

# ── Quick copy of existing dated files ─────────────────────────────────────────

def copy_existing():
    """
    Find all dated Nordnet CSVs in the project folder, pick the two newest
    (old vs new), save baseline from the older one, then promote the newer
    one to the fixed output filenames.
    """
    all_stocks = sorted(SCRIPT_DIR.glob(STOCKS_PATTERN), key=lambda p: p.stat().st_mtime)
    all_funds  = sorted(SCRIPT_DIR.glob(FUNDS_PATTERN),  key=lambda p: p.stat().st_mtime)

    # Filter out the fixed output files themselves
    all_stocks = [p for p in all_stocks if p.name != STOCKS_OUT.name]
    all_funds  = [p for p in all_funds  if p.name != FUNDS_OUT.name]

    copied = False

    if len(all_stocks) >= 2:
        import time as _time
        old_stocks, new_stocks = all_stocks[-2], all_stocks[-1]
        baseline_funds = all_funds[-2] if len(all_funds) >= 2 else None
        print(f'[baseline] Using {old_stocks.name} as previous snapshot')
        snap = build_baseline_json(old_stocks, baseline_funds)
        snap['__ts'] = int(_time.time() * 1000)
        BASELINE_OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'[baseline] Saved {len(snap) - 1} positions -> {BASELINE_OUT.name}')
        shutil.copy2(new_stocks, STOCKS_OUT)
        print(f'[copy] {new_stocks.name} -> {STOCKS_OUT.name}')
        copied = True
    elif len(all_stocks) == 1:
        # Only one file — no diff possible, just promote it
        shutil.copy2(all_stocks[0], STOCKS_OUT)
        print(f'[copy] {all_stocks[0].name} -> {STOCKS_OUT.name}')
        copied = True

    if len(all_funds) >= 2:
        new_funds = all_funds[-1]
        shutil.copy2(new_funds, FUNDS_OUT)
        print(f'[copy] {new_funds.name} -> {FUNDS_OUT.name}')
        copied = True
    elif len(all_funds) == 1:
        shutil.copy2(all_funds[0], FUNDS_OUT)
        print(f'[copy] {all_funds[0].name} -> {FUNDS_OUT.name}')
        copied = True

    if not copied:
        print('[copy] No dated Nordnet CSV files found in project folder.')
    return copied

# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Sync Nordnet portfolio to dashboard CSV files')
    parser.add_argument('--watch',    action='store_true',
                        help='Watch Downloads folder for new Nordnet exports')
    parser.add_argument('--api',      action='store_true',
                        help='Fetch live data via Nordnet API (needs SESSION token)')
    parser.add_argument('--baseline', action='store_true',
                        help='(Re)generate portfolio_baseline.json from current portfolio_stocks/funds.csv')
    parser.add_argument('--interval', type=int, default=60,
                        help='Watch interval in seconds (default: 60)')
    args = parser.parse_args()

    if args.watch:
        watch_mode(args.interval)
    elif args.api:
        api_mode()
    elif args.baseline:
        save_baseline()
    else:
        # Default: copy newest dated files already in the project folder
        if not copy_existing():
            print('\nOptions:')
            print('  python nordnet_sync.py --watch      (auto-copy from Downloads)')
            print('  python nordnet_sync.py --api        (fetch via Nordnet API)')
            print('  python nordnet_sync.py --baseline   (rebuild baseline snapshot)')

if __name__ == '__main__':
    main()
