#!/usr/bin/env python3
"""
server.py  —  Trading Dashboard  (file server + Yahoo Finance proxy)
====================================================================
Serves dashboard files AND proxies Yahoo Finance API calls via /yahoo/*.

The v7 quote batch API now requires Yahoo auth (crumb/cookie).
This proxy transparently translates v7 batch requests into v8 chart
requests (which need no auth) and reassembles the v7 response format
so the browser JS doesn't need any changes.

Usage:
    python server.py            # port 8000
    python server.py --port 9000

Then open:  http://localhost:8000
"""

import http.server
import socketserver
import urllib.request
import urllib.error
import urllib.parse
import json
import sys
import os
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PORT = 8000

YAHOO_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/122.0.0.0 Safari/537.36',
    'Accept':          'application/json, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer':         'https://finance.yahoo.com/',
}

EXECUTOR = ThreadPoolExecutor(max_workers=10)


def _fetch_yahoo(path: str) -> bytes:
    """Fetch path from query1 or query2 with fallback."""
    for host in ['query1.finance.yahoo.com', 'query2.finance.yahoo.com']:
        url = f'https://{host}/{path}'
        try:
            req = urllib.request.Request(url, headers=YAHOO_HEADERS)
            with urllib.request.urlopen(req, timeout=12) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise      # no point retrying
        except Exception:
            continue
    raise RuntimeError(f'All Yahoo hosts failed for /{path}')


def _quote_from_chart(symbol: str) -> dict | None:
    """
    Fetch one symbol via v8/finance/chart (no auth required) and return
    a dict in v7/finance/quote result format:
      { symbol, regularMarketPrice, regularMarketChangePercent, regularMarketChange }
    """
    try:
        path = f'v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=1d&includePrePost=false'
        raw  = _fetch_yahoo(path)
        d    = json.loads(raw)
        meta = d['chart']['result'][0]['meta']
        price    = meta.get('regularMarketPrice') or meta.get('previousClose', 0)
        prev     = meta.get('chartPreviousClose') or meta.get('previousClose', price)
        change   = round(price - prev, 4)
        chg_pct  = round((change / prev * 100) if prev else 0, 4)
        return {
            'symbol':                    meta.get('symbol', symbol),
            'regularMarketPrice':        price,
            'regularMarketChangePercent': chg_pct,
            'regularMarketChange':        change,
            'regularMarketPreviousClose': prev,
        }
    except Exception:
        return None


def _handle_v7_quote(query_string: str) -> bytes:
    """
    Translate a v7/finance/quote?symbols=A,B,C request into parallel
    v8/finance/chart requests and return a v7-compatible JSON response.
    """
    params  = urllib.parse.parse_qs(query_string)
    symbols = []
    for s in params.get('symbols', []):
        symbols.extend(s.split(','))
    symbols = [s.strip() for s in symbols if s.strip()]

    if not symbols:
        return json.dumps({'quoteResponse': {'result': [], 'error': None}}).encode()

    results = [None] * len(symbols)
    futures = {EXECUTOR.submit(_quote_from_chart, sym): i
               for i, sym in enumerate(symbols)}
    for fut in as_completed(futures):
        idx = futures[fut]
        try:
            q = fut.result()
            if q:
                results[idx] = q
        except Exception:
            pass

    return json.dumps({
        'quoteResponse': {
            'result': [r for r in results if r],
            'error':  None,
        }
    }).encode()


class DashboardHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path.startswith('/yahoo/'):
            self._proxy_yahoo()
        else:
            super().do_GET()

    def _proxy_yahoo(self):
        raw_path = self.path[7:]   # strip '/yahoo/'

        # Split path from query string
        if '?' in raw_path:
            path_part, qs = raw_path.split('?', 1)
        else:
            path_part, qs = raw_path, ''

        try:
            # v7 quote: translate to v8 chart (no auth needed)
            if path_part.startswith('v7/finance/quote'):
                data  = _handle_v7_quote(qs)
                ctype = 'application/json'
            else:
                # All other endpoints (v8/chart, v8/spark, etc.) pass through
                data  = _fetch_yahoo(raw_path)
                ctype = 'application/json'

            self.send_response(200)
            self.send_header('Content-Type',  ctype)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()

        except Exception as e:
            try:
                self.send_error(502, f'Proxy error: {e}')
            except Exception:
                pass

    def log_message(self, fmt, *args):
        msg  = fmt % args
        path = str(args[0]) if args else ''
        if '/yahoo/' in path:
            sys.stdout.write(f'[proxy] {msg}\n')
        elif any(c in msg for c in ('4', '5')) and (' 4' in msg or ' 5' in msg):
            sys.stdout.write(f'[http]  {msg}\n')


def main():
    parser = argparse.ArgumentParser(description='Trading Dashboard server')
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args()

    os.chdir(Path(__file__).parent)
    socketserver.TCPServer.allow_reuse_address = True

    with socketserver.TCPServer(('', args.port), DashboardHandler) as httpd:
        print(f'\n  Dashboard  ->  http://localhost:{args.port}')
        print(f'  Yahoo proxy: /yahoo/v7/quote -> v8/chart (no auth required)')
        print('  Press Ctrl+C to stop\n')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nStopped.')


if __name__ == '__main__':
    main()
