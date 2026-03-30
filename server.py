#!/usr/bin/env python3
"""
server.py  —  Trading Dashboard  (file server + Yahoo Finance proxy)
====================================================================
Serves all dashboard files AND proxies Yahoo Finance API calls through
/yahoo/* so the browser never hits CORS restrictions.

Usage:
    python server.py            # port 8000
    python server.py --port 9000

Then open:  http://localhost:8000
"""

import http.server
import socketserver
import urllib.request
import urllib.error
import sys
import os
import argparse
from pathlib import Path

PORT = 8000

YAHOO_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/122.0.0.0 Safari/537.36',
    'Accept':          'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer':         'https://finance.yahoo.com/',
    'Origin':          'https://finance.yahoo.com',
}


class DashboardHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path.startswith('/yahoo/'):
            self._proxy_yahoo()
        else:
            super().do_GET()

    def _proxy_yahoo(self):
        """Forward /yahoo/<path+query> -> https://query{1,2}.finance.yahoo.com/<path+query>"""
        path = self.path[7:]          # strip leading '/yahoo/'
        hosts = ['query1.finance.yahoo.com', 'query2.finance.yahoo.com']

        last_err = None
        for host in hosts:
            target = f'https://{host}/{path}'
            try:
                req = urllib.request.Request(target, headers=YAHOO_HEADERS)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data   = resp.read()
                    ctype  = resp.headers.get('Content-Type', 'application/json')

                self.send_response(200)
                self.send_header('Content-Type',  ctype)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)
                return

            except urllib.error.HTTPError as e:
                last_err = f'HTTP {e.code} from {host}'
                if e.code in (401, 403, 404):
                    break          # no point retrying auth/not-found errors

            except Exception as e:
                last_err = str(e)

        # All hosts failed
        self.send_error(502, f'Yahoo Finance proxy error: {last_err}')

    def log_message(self, fmt, *args):
        # Show proxy calls; suppress noisy static-file logs
        msg = fmt % args
        if '/yahoo/' in (args[0] if args else ''):
            sys.stdout.write(f'[proxy] {msg}\n')
        elif ' 4' in msg or ' 5' in msg:          # only log errors for static files
            sys.stdout.write(f'[http]  {msg}\n')


def main():
    parser = argparse.ArgumentParser(description='Trading Dashboard server')
    parser.add_argument('--port', type=int, default=PORT,
                        help=f'Port to listen on (default: {PORT})')
    args = parser.parse_args()

    os.chdir(Path(__file__).parent)  # always serve from the project folder

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('', args.port), DashboardHandler) as httpd:
        print(f'\n  Dashboard  ->  http://localhost:{args.port}')
        print(f'  Yahoo proxy  /yahoo/* -> query{{1,2}}.finance.yahoo.com')
        print('  Press Ctrl+C to stop\n')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nStopped.')


if __name__ == '__main__':
    main()
