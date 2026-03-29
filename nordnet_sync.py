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

STOCKS_PATTERN = f'aktier_kontonummer-{ACCOUNT_NUM}_*.csv'
FUNDS_PATTERN  = f'fonder_kontonummer-{ACCOUNT_NUM}_*.csv'

def find_latest(folder: Path, pattern: str) -> Path | None:
    matches = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None

def copy_if_newer(src: Path, dst: Path) -> bool:
    """Copy src -> dst if src is newer.  Returns True if copied."""
    if not src.exists():
        return False
    if dst.exists() and src.stat().st_mtime <= dst.stat().st_mtime:
        return False
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
    Look for dated Nordnet CSVs already in the project folder
    and copy the newest ones to the fixed-name output files.
    """
    stocks_src = find_latest(SCRIPT_DIR, STOCKS_PATTERN)
    funds_src  = find_latest(SCRIPT_DIR, FUNDS_PATTERN)
    copied = False
    if stocks_src:
        shutil.copy2(stocks_src, STOCKS_OUT)
        print(f'[copy] {stocks_src.name} -> {STOCKS_OUT.name}')
        copied = True
    if funds_src:
        shutil.copy2(funds_src, FUNDS_OUT)
        print(f'[copy] {funds_src.name} -> {FUNDS_OUT.name}')
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
    parser.add_argument('--interval', type=int, default=60,
                        help='Watch interval in seconds (default: 60)')
    args = parser.parse_args()

    if args.watch:
        watch_mode(args.interval)
    elif args.api:
        api_mode()
    else:
        # Default: copy newest dated files already in the project folder
        if not copy_existing():
            print('\nOptions:')
            print('  python nordnet_sync.py --watch   (auto-copy from Downloads)')
            print('  python nordnet_sync.py --api     (fetch via Nordnet API)')

if __name__ == '__main__':
    main()
