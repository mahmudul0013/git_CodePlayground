#!/usr/bin/env python3
"""
server.py  -  Trading Dashboard (multi-user: login, per-user profiles, JSON API, Yahoo proxy)
==============================================================================================
One process, one port, many users. Every data route resolves the caller from the session cookie and reads only that
user's profile folder (data/profiles/<uid>/); the browser never supplies a user id or a path.

    python server.py            # port 8000
    python server.py --port 9000

First start (no users yet): the console prints a one-time setup code. Open /login.html, enter it and create the admin.
The admin then creates single-use invite codes for the other users (Account -> Admin).

The Yahoo v7 quote batch API needs auth now, so /yahoo/v7/finance/quote is translated into v8 chart requests.
"""

import argparse
import hashlib
import http.server
import socket
import inspect
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import auth                  # accounts, invites, sessions
import profiles              # per-user folders + validated uploads
import trade_analytics       # Nordnet CSV -> analytics JSON (Analytics page)
import symbols               # ISIN/name -> Yahoo symbol (cached, public data)
import benchmark             # index buy-and-hold comparison (Yahoo daily closes)
import sectors               # sector / fund category per holding (Yahoo)
import advisor               # rule-based add / trim review (history cache, no forecasts)
import reports               # upcoming earnings / ex-dividend dates of the holdings (Yahoo calendarEvents)

PORT = 8000
ROOT = os.path.dirname(os.path.abspath(__file__))
REAL_ROOT = os.path.realpath(ROOT)
COOKIE = 'tv_session'
COOKIE_MAX_AGE = 30 * 86400
MAX_JSON = 64 * 1024
ASK_PER_MINUTE = 30

# Static files: ONLY these types, only directly in the project folder (never data/, .py, .json, .csv, .bat, .md, .env, dotfiles).
STATIC_TYPES = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.ico': 'image/x-icon', '.png': 'image/png', '.svg': 'image/svg+xml', '.webp': 'image/webp', '.woff2': 'font/woff2',
}
STATIC_NAME = re.compile(r'^/[A-Za-z0-9_][A-Za-z0-9_.-]*$')

YAHOO_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/122.0.0.0 Safari/537.36',
    'Accept':          'application/json, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer':         'https://finance.yahoo.com/',
}

EXECUTOR = ThreadPoolExecutor(max_workers=10)


# ───────────────────────── Yahoo helpers (public market data, shared by all users) ─────────────────────────
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
    syms = []
    for s in params.get('symbols', []):
        syms.extend(s.split(','))
    syms = [s.strip() for s in syms if s.strip()][:60]

    if not syms:
        return json.dumps({'quoteResponse': {'result': [], 'error': None}}).encode()

    results = [None] * len(syms)
    futures = {EXECUTOR.submit(_quote_from_chart, sym): i for i, sym in enumerate(syms)}
    for fut in as_completed(futures):
        idx = futures[fut]
        try:
            q = fut.result()
            if q:
                results[idx] = q
        except Exception:
            pass

    return json.dumps({'quoteResponse': {'result': [r for r in results if r], 'error': None}}).encode()


def _live_quote(symbol: str) -> dict | None:
    """Last price, previous session close and currency of one symbol (v8 chart, no login needed).
    The previous close is taken from the daily bars. meta.chartPreviousClose is NOT used:
    with range=5d it is the close from before the whole window, which turned a -5% day into +9%."""
    try:
        res = json.loads(_fetch_yahoo(f'v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=5d&includePrePost=false'))['chart']['result'][0]
        meta = res['meta']
        price = meta.get('regularMarketPrice')
        if not price:
            return None
        # previous close = last valid daily close dated BEFORE the current session (exchange-local dates). The latest
        # bar can be today's still-open session with a null close (European listings), so it must not be counted.
        off = meta.get('gmtoffset') or 0
        day = lambda t: (t + off) // 86400
        sess = day(meta.get('regularMarketTime') or res['timestamp'][-1])
        prev = None
        for t, c in zip(res.get('timestamp') or [], res['indicators']['quote'][0]['close']):
            if c is not None and day(t) < sess:
                prev = c
        return {'symbol': meta.get('symbol', symbol), 'price': price, 'prev': prev, 'currency': meta.get('currency'),
                'change_pct': round((price / prev - 1) * 100, 4) if prev else None,
                'time': meta.get('regularMarketTime'), 'state': meta.get('marketState')}
    except Exception:
        return None


# Per-symbol quote cache (25 s) shared by every user: prices are public data, so two users holding the same stock
# cost one Yahoo call. What a user receives is still built from that user's own holdings only.
_QCACHE = {}
_QLOCK = threading.Lock()
_QTTL = 25


def _quote_cached(sym):
    now = time.time()
    with _QLOCK:
        e = _QCACHE.get(sym)
        if e and now - e[0] < _QTTL:
            return e[1]
    q = _live_quote(sym)
    with _QLOCK:
        _QCACHE[sym] = (time.time(), q)
        if len(_QCACHE) > 800:                       # bounded: forget what is stale
            cut = time.time() - 300
            for k in [k for k, v in _QCACHE.items() if v[0] < cut]:
                _QCACHE.pop(k, None)
            if len(_QCACHE) > 800:
                for k in list(_QCACHE)[:400]:
                    _QCACHE.pop(k, None)
    return q


def _live_quotes(assets) -> dict:
    """Yahoo quotes for every given asset that has a Yahoo symbol: {isin: quote}."""
    syms = {}
    for a in assets:
        r = symbols.resolve(a['isin'], a['name'], a.get('ccy'))
        if r and r.get('symbol'):
            syms[a['isin']] = r['symbol']
    futs = {EXECUTOR.submit(_quote_cached, sym): isin for isin, sym in syms.items()}
    out = {}
    for f in as_completed(futs):
        try:
            q = f.result()
            if q:
                out[futs[f]] = q
        except Exception:
            pass
    return out


# ───────────────────────── per-user data helpers ─────────────────────────
class ApiError(Exception):
    def __init__(self, status, error, message=None, **extra):
        super().__init__(error)
        self.status, self.error, self.message, self.extra = status, error, message, extra


_ULOCKS = {}
_ULOCKS_LOCK = threading.Lock()
_ASK = defaultdict(deque)
_ASK_LOCK = threading.Lock()


def _uid_lock(uid):
    with _ULOCKS_LOCK:
        return _ULOCKS.setdefault(uid, threading.Lock())


def _supports(fn, param):
    try:
        return param in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _payload(uid):
    """Analytics payload of THIS user's profile folder only."""
    if not profiles.has_ledger(uid):
        raise ApiError(409, 'no_files', 'Upload your two Nordnet files first.')
    if not _supports(trade_analytics.get_payload, 'base_dir'):
        raise ApiError(503, 'backend_not_ready', 'The analytics engine is not per-user yet.')
    with _uid_lock(uid):
        p = trade_analytics.get_payload(profiles.profile_dir(uid))
    if 'error' in p:
        raise ApiError(409 if p.get('code') == 'no_files' else 500, p.get('code') or 'server', p['error'])
    return p


def _held(p):
    return [{'isin': x['isin'], 'name': x['name'], 'ccy': x.get('ccy')} for x in p['assets'] if x.get('value') and x.get('isin')]


def _advice(uid, p, live, profile):
    if _supports(advisor.get, 'owner'):
        return advisor.get(p, live, profile, owner=uid)
    return advisor.advise(p, live, profile)          # uncached rather than a cache shared between users


def _forget(uid):
    """Drop the per-user advice cache (new files or a deleted profile). No-op if the advisor has no such hook."""
    fn = getattr(advisor, 'forget', None)
    if fn:
        fn(uid)


def _me(u):
    return {'username': u['username'], 'role': u['role'], 'sid': auth.sid_of(u['uid']), 'accno': u.get('accno'),
            'has_files': profiles.has_files(u['uid'])}


# ───────────────────────── HTTP handler ─────────────────────────
class DashboardHandler(http.server.BaseHTTPRequestHandler):

    timeout = 30                  # a stalled client can hold its own thread for at most 30 s
    server_version = 'TradeView'
    sys_version = ''

    # ---- plumbing ----
    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def log_request(self, code='-', size='-'):
        try:
            if int(code) >= 400:
                sys.stdout.write(f'[http] {self.command} {getattr(self, "route", "?")} {code}\n')   # never the query or cookies
        except Exception:
            pass

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=b'', ctype='application/json; charset=utf-8', headers=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, code, obj, headers=None):
        self._send(code, json.dumps(obj).encode('utf-8'), headers=headers)

    def _cookie_token(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == COOKIE:
                return v
        return None

    def _set_cookie(self, token, max_age=COOKIE_MAX_AGE):
        return {'Set-Cookie': f'{COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}'}

    def _json_body(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            raise ApiError(400, 'invalid', 'Bad Content-Length.')
        if n > MAX_JSON:
            raise ApiError(413, 'too_large', 'Request too large.')
        raw = self.rfile.read(n) if n > 0 else b''
        if not raw:
            return {}
        try:
            d = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, 'invalid', 'Body must be JSON.')
        if not isinstance(d, dict):
            raise ApiError(400, 'invalid', 'Body must be a JSON object.')
        return d

    def _csrf_ok(self):
        if self.headers.get('X-TV') != '1':
            return False
        origin = self.headers.get('Origin')
        if origin is not None:
            host = (self.headers.get('Host') or '').lower()
            if urllib.parse.urlsplit(origin).netloc.lower() != host:
                return False
        return True

    # ---- verbs ----
    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def _deny(self):
        self.route = urllib.parse.urlsplit(self.path).path
        self._json(405, {'error': 'method_not_allowed'}, {'Allow': 'GET, POST'})

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _deny      # no CORS preflight is ever answered

    def _dispatch(self, method):
        try:
            url = urllib.parse.urlsplit(self.path)
            self.route, self.query = url.path, urllib.parse.parse_qs(url.query)
            if method == 'POST' and not self._csrf_ok():
                if self.route.startswith('/api/upload/'):
                    self.close_connection = True
                return self._json(403, {'error': 'csrf', 'message': 'Missing or foreign request header.'})
            if self.route.startswith('/yahoo/'):
                return self._proxy_yahoo(method)
            if self.route.startswith('/api/'):
                return self._api(method)
            if method != 'GET':
                return self._json(405, {'error': 'method_not_allowed'})
            return self._static()
        except ApiError as e:
            body = {'error': e.error, **e.extra}
            if e.message:
                body['message'] = e.message
            self._json(e.status, body, getattr(e, 'headers', None))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:                       # never leak internals or data in an error message
            sys.stdout.write(f'[error] {type(e).__name__} on {getattr(self, "route", "?")}\n')
            try:
                self._json(500, {'error': 'server'})
            except Exception:
                pass

    # ---- static (allow-list) ----
    def _static(self):
        path = urllib.parse.unquote(self.route)
        if path == '/':
            return self._send(302, b'', 'text/plain', {'Location': '/index.html'})
        name = path[1:]
        if not STATIC_NAME.match(path) or os.path.splitext(name)[1].lower() not in STATIC_TYPES:
            return self._send(404, b'Not found', 'text/plain; charset=utf-8')
        full = os.path.join(ROOT, name)
        if not os.path.isfile(full) or os.path.dirname(os.path.realpath(full)) != REAL_ROOT:
            return self._send(404, b'Not found', 'text/plain; charset=utf-8')
        with open(full, 'rb') as f:
            data = f.read()
        self._send(200, data, STATIC_TYPES[os.path.splitext(name)[1].lower()])

    # ---- API routing ----
    def _api(self, method):
        route = self.route.rstrip('/') or '/'
        table = self.ROUTES.get(route)
        if not table:
            raise ApiError(404, 'not_found')
        spec = table.get(method)
        if not spec:
            raise ApiError(405, 'method_not_allowed')
        access, fn = spec
        user = None
        if access != 'public' or route == '/api/auth/logout':
            tok = self._cookie_token()
            user = auth.session_user(tok)
        if access in ('user', 'admin') and not user:
            if route.startswith('/api/upload/'):
                self.close_connection = True
            raise ApiError(401, 'auth', 'Please sign in.')
        if access == 'admin' and user['role'] != 'admin':
            raise ApiError(403, 'forbidden', 'Admin only.')
        getattr(self, fn)(user)

    # ---- auth routes ----
    def _auth_error(self, e):
        if e.code == 'locked':
            err = ApiError(429, 'locked', e.message, retry_after=e.retry_after)
        elif e.code in ('bad', 'bad_invite', 'bad_setup_code'):
            err = ApiError(403, 'bad_credentials' if e.code == 'bad' else e.code, e.message)
        elif e.code == 'exists':
            err = ApiError(409, 'exists', e.message)
        elif e.code == 'not_found':
            err = ApiError(404, 'not_found', e.message)
        elif e.code == 'forbidden':
            err = ApiError(403, 'forbidden', e.message)
        else:
            err = ApiError(400, 'invalid', e.message)
        return err

    def _login_reply(self, u, extra=None):
        token = auth.new_session(u['uid'])
        body = {'ok': True, 'user': _me(u)}
        body.update(extra or {})
        self._json(200, body, self._set_cookie(token))

    def r_state(self, user):
        self._json(200, {'setup_needed': not auth.has_users()})

    def r_setup(self, user):
        b = self._json_body()
        try:
            u = auth.create_admin(b.get('setup_code'), b.get('username'), b.get('password'))
        except auth.AuthError as e:
            raise self._auth_error(e)
        extra = {}
        if b.get('import_existing'):
            extra['imported'] = profiles.import_legacy(u['uid'])
            _forget(u['uid'])
            u = auth.get_user(u['uid'])
        self._login_reply(u, extra)

    def r_login(self, user):
        b = self._json_body()
        try:
            u = auth.verify(b.get('username'), b.get('password'), self.client_address[0])
        except auth.AuthError as e:
            raise self._auth_error(e)
        self._login_reply(u)

    def r_register(self, user):
        b = self._json_body()
        try:
            u = auth.register(b.get('code'), b.get('username'), b.get('password'))
        except auth.AuthError as e:
            raise self._auth_error(e)
        self._login_reply(u)

    def r_logout(self, user):
        auth.logout(self._cookie_token())
        self._json(200, {'ok': True}, self._set_cookie('', 0))

    def r_me(self, user):
        self._json(200, {'ok': True, 'user': _me(user)})

    def r_password(self, user):
        b = self._json_body()
        try:
            auth.change_password(user['uid'], b.get('old'), b.get('new'))
        except auth.AuthError as e:
            raise self._auth_error(e)
        self._login_reply(auth.get_user(user['uid']))        # all sessions were ended; this device gets a fresh one

    def r_account_delete(self, user):
        b = self._json_body()
        uid = user['uid']
        try:
            if user['role'] == 'admin':
                if not auth.verify_password(uid, b.get('password')):
                    raise auth.AuthError('bad', message='Password is wrong.')
                profiles.delete_profile(uid)
                _forget(uid)
                return self._json(200, {'ok': True, 'deleted': 'files'})
            auth.delete_self(uid, b.get('password'))
        except auth.AuthError as e:
            raise self._auth_error(e)
        profiles.delete_profile(uid)
        _forget(uid)
        self._json(200, {'ok': True, 'deleted': 'account'}, self._set_cookie('', 0))

    def r_account_status(self, user):
        self._json(200, {'ok': True, **profiles.status(user['uid'])})

    # ---- uploads (raw body, one file per request) ----
    def _upload(self, user, kind):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        if n <= 0:
            raise ApiError(400, 'invalid', 'The file is empty.')
        if n > profiles.MAX_UPLOAD:
            left = min(n, 32 * 1024 * 1024)            # drain a little so the browser can read our answer
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
            self.close_connection = True
            raise ApiError(413, 'too_large', f'The file is larger than {profiles.MAX_UPLOAD // (1024 * 1024)} MB.')
        data = self.rfile.read(n)
        name = os.path.basename(urllib.parse.unquote(self.headers.get('X-Filename') or ''))[:200]
        confirm = (self.headers.get('X-Confirm') or '') == 'replace'      # the user saw the comparison and accepts a smaller ledger
        r = profiles.save_upload(user['uid'], kind, data, name, confirm=confirm)
        if r.get('ok'):
            _forget(user['uid'])                       # files changed: drop this user's cached advice
        if not r.get('ok'):
            extra = {k: x for k, x in r.items() if k not in ('ok', 'error', 'message')}
            raise ApiError(409 if r['error'] in ('accno_mismatch', 'accno_taken', 'confirm_needed') else 400, r['error'], r.get('message'), **extra)
        self._json(200, r)

    def r_upload_holdings(self, user):
        self._upload(user, 'holdings')

    def r_upload_ledger(self, user):
        self._upload(user, 'ledger')

    # ---- admin ----
    def r_admin_users(self, user):
        us = auth.list_users()
        for u in us:
            u['has_files'] = profiles.has_files(u['uid'])
            u['sid'] = auth.sid_of(u['uid'])
        self._json(200, {'ok': True, 'users': us})

    def r_admin_invite_new(self, user):
        code, exp = auth.create_invite(user['uid'])
        self._json(200, {'ok': True, 'code': code, 'expires': exp})

    def r_admin_invites(self, user):
        self._json(200, {'ok': True, 'invites': auth.list_invites()})

    def r_admin_reset(self, user):
        b = self._json_body()
        try:
            auth.reset_password(user['uid'], b.get('uid'), b.get('new'))
        except auth.AuthError as e:
            raise self._auth_error(e)
        self._json(200, {'ok': True})

    def r_admin_delete(self, user):
        b = self._json_body()
        target = b.get('uid')
        try:
            auth.delete_user(user['uid'], target)
        except auth.AuthError as e:
            raise self._auth_error(e)
        profiles.delete_profile(target)
        _forget(target)
        self._json(200, {'ok': True})

    # ---- data routes (always the caller's own profile) ----
    def r_holdings(self, user):
        files = profiles._holdings_files(profiles.profile_dir(user['uid']))
        if not files:
            raise ApiError(409, 'no_files', 'Upload your two Nordnet files first.')
        path = files[-1]
        data = Path(path).read_bytes()
        self._send(200, data, 'text/csv', {'X-Source-File': urllib.parse.quote(os.path.basename(path))})

    def r_baseline(self, user):
        self._json(200, profiles.baseline(user['uid']))

    def r_status(self, user):
        if not _supports(trade_analytics.signature, 'base_dir'):
            raise ApiError(503, 'backend_not_ready')
        self._json(200, trade_analytics.signature(profiles.profile_dir(user['uid'])))

    def r_trades(self, user):
        self._json(200, _payload(user['uid']))

    def r_assets(self, user):
        p = _payload(user['uid'])
        self._json(200, {'generated': p['generated'], 'sources': p['sources'], 'assets': p['assets']})

    def r_live(self, user):
        p = _payload(user['uid'])
        self._json(200, {'ok': True, 'asof': datetime.now().isoformat(timespec='seconds'), 'quotes': _live_quotes(_held(p))})

    def r_advice(self, user):
        p = _payload(user['uid'])
        prof = (self.query.get('profile') or [advisor.DEFAULT_PROFILE])[0]
        self._json(200, _advice(user['uid'], p, _live_quotes(_held(p)), prof if prof in advisor.PROFILES else advisor.DEFAULT_PROFILE))

    def r_reports(self, user):
        self._json(200, reports.upcoming(_payload(user['uid'])))

    def r_sectors(self, user):
        p = _payload(user['uid'])
        held = [{'isin': a['isin'], 'name': a['name'], 'ccy': a.get('ccy')} for a in p['assets'] if (a.get('held') or a.get('value')) and a.get('isin')]
        info, pending = sectors.batch(held)
        self._json(200, {'ok': True, 'pending': pending, 'sectors': info})

    def r_benchmark(self, user):
        p = _payload(user['uid'])
        flows = [{'date': c['date'], 'amount': c['amount']} for c in p.get('cashflows', [])]
        self._json(200, benchmark.compute(flows, p['insights']['overview']['total_value']))

    def r_overlay(self, user):
        p = _payload(user['uid'])
        ser = p['insights']['deposit_behavior']['series']
        flows = [{'date': c['date'], 'amount': c['amount']} for c in p.get('cashflows', [])]
        self._json(200, benchmark.overlay(flows, ser[0]['date'], ser[-1]['date']))

    def r_symbol(self, user):
        q = lambda k: (self.query.get(k) or [''])[0]
        self._json(200, symbols.get(q('isin'), q('name'), q('ccy')))

    def r_ask(self, user):
        b = self._json_body()
        q = str(b.get('q') or '').strip()[:500]
        if not q:
            raise ApiError(400, 'invalid', 'Ask a question.')
        now = time.time()
        with _ASK_LOCK:
            dq = _ASK[user['uid']]
            while dq and dq[0] < now - 60:
                dq.popleft()
            if len(dq) >= ASK_PER_MINUTE:
                raise ApiError(429, 'rate_limited', 'Too many questions, wait a moment.')
            dq.append(now)
        try:
            import assistant                      # optional module (another worker); the question is never logged
        except ImportError:
            raise ApiError(503, 'unavailable', 'The assistant is not installed.')
        p = _payload(user['uid'])
        try:
            adv = _advice(user['uid'], p, None, advisor.DEFAULT_PROFILE)
        except Exception:
            adv = None
        try:
            try:
                p = dict(p, reports=reports.upcoming(p, fetch=False))     # cached dates only: asking never waits for Yahoo
            except Exception:
                pass
            self._json(200, {'ok': True, **assistant.answer(q, p, adv)})
        except Exception as e:
            sys.stdout.write(f'[error] assistant {type(e).__name__}\n')
            raise ApiError(503, 'unavailable', 'The assistant could not answer that.')

    ROUTES = {
        '/api/auth/state':      {'GET':  ('public', 'r_state')},
        '/api/auth/setup':      {'POST': ('public', 'r_setup')},
        '/api/auth/login':      {'POST': ('public', 'r_login')},
        '/api/auth/register':   {'POST': ('public', 'r_register')},
        '/api/auth/logout':     {'POST': ('public', 'r_logout')},
        '/api/auth/me':         {'GET':  ('user', 'r_me')},
        '/api/auth/password':   {'POST': ('user', 'r_password')},
        '/api/account/delete':  {'POST': ('user', 'r_account_delete')},
        '/api/account/status':  {'GET':  ('user', 'r_account_status')},
        '/api/upload/holdings': {'POST': ('user', 'r_upload_holdings')},
        '/api/upload/ledger':   {'POST': ('user', 'r_upload_ledger')},
        '/api/admin/users':     {'GET':  ('admin', 'r_admin_users')},
        '/api/admin/invites':   {'GET':  ('admin', 'r_admin_invites'), 'POST': ('admin', 'r_admin_invite_new')},
        '/api/admin/users/reset':  {'POST': ('admin', 'r_admin_reset')},
        '/api/admin/users/delete': {'POST': ('admin', 'r_admin_delete')},
        '/api/holdings':        {'GET':  ('user', 'r_holdings')},
        '/api/baseline':        {'GET':  ('user', 'r_baseline')},
        '/api/trades':          {'GET':  ('user', 'r_trades')},
        '/api/trades/status':   {'GET':  ('user', 'r_status')},
        '/api/assets':          {'GET':  ('user', 'r_assets')},
        '/api/live':            {'GET':  ('user', 'r_live')},
        '/api/advice':          {'GET':  ('user', 'r_advice')},
        '/api/reports':         {'GET':  ('user', 'r_reports')},
        '/api/sectors':         {'GET':  ('user', 'r_sectors')},
        '/api/benchmark':       {'GET':  ('user', 'r_benchmark')},
        '/api/overlay':         {'GET':  ('user', 'r_overlay')},
        '/api/symbol':          {'GET':  ('user', 'r_symbol')},
        '/api/ask':             {'POST': ('user', 'r_ask')},
    }

    # ---- Yahoo proxy (session required: it is otherwise an open proxy) ----
    def _proxy_yahoo(self, method):
        if method != 'GET':
            raise ApiError(405, 'method_not_allowed')
        if not auth.session_user(self._cookie_token()):
            raise ApiError(401, 'auth', 'Please sign in.')
        raw_path = self.path[7:]   # strip '/yahoo/'
        path_part, _, qs = raw_path.partition('?')
        try:
            if path_part.startswith('v7/finance/quote'):          # translate to v8 chart (no auth needed)
                data = _handle_v7_quote(qs)
            else:                                                # v8/chart, v8/spark, ... pass through
                data = _fetch_yahoo(raw_path)
            self._send(200, data, 'application/json')
        except Exception:
            self._json(502, {'error': 'proxy'})


class DashboardServer(http.server.ThreadingHTTPServer):
    """One thread per request, so several browsers (and slow Yahoo calls) never block each other."""
    daemon_threads = True                      # threads never keep the process alive
    request_queue_size = 64
    allow_reuse_address = os.name != 'nt'      # on Windows SO_REUSEADDR lets a SECOND server share the port silently (the old one then answers)

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    parser = argparse.ArgumentParser(description='Trading Dashboard server')
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args()

    os.chdir(Path(__file__).parent)
    try:
        sys.stdout.reconfigure(line_buffering=True)      # the setup code must show up at once, also when output is redirected
    except Exception:
        pass
    auth.init()
    try:
        httpd_cm = DashboardServer(('', args.port), DashboardHandler)
    except OSError as e:
        sys.exit(f'\n  Port {args.port} is already in use (another dashboard server running?). Run stop-dashboard.bat first.\n  ({e})\n')
    with httpd_cm as httpd:
        print(f'\n  Dashboard  ->  http://localhost:{args.port}')
        print(f'  Analytics   ->  http://localhost:{args.port}/analytics.html')
        print(f'  Data folder ->  {auth.data_dir()}')
        code = auth.setup_code()
        if code:
            print('\n  FIRST START: there are no users yet.')
            print(f'  Open http://localhost:{args.port}/login.html and create the admin account.')
            print(f'  Setup code (needed once): {code}')
        print('\n  Press Ctrl+C to stop\n')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nStopped.')


if __name__ == '__main__':
    main()
