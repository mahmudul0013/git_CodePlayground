"""HTTPS check:  python tests/https_test.py   (needs the openssl command; Git for Windows has one).

Two scratch servers with a self-signed certificate:
  A) default with a certificate: plain http on one port (your LAN address keeps working) AND https on a second port (the Tailscale name)
  B) --https-only: https on the main port, a plain http:// visit is redirected to https://
Checks: trusted connection, Secure cookie only over https, redirect, a stalled handshake that must not block others, junk bytes,
no tracebacks in the log."""
import http.client
import http.cookiejar
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENSSL = shutil.which('openssl') or r'C:\Program Files\Git\usr\bin\openssl.exe'      # Git for Windows ships one
res = []


def ok(n, c, d=''):
    res.append(bool(c))
    print(('PASS ' if c else 'FAIL ') + n + (('  ' + str(d)[:140]) if d else ''))


class Server:
    def __init__(self, tag, args):
        self.dir = tempfile.mkdtemp(prefix='tv_https_' + tag)
        os.makedirs(os.path.join(self.dir, 'tls'))
        self.cert, self.key = os.path.join(self.dir, 'tls', 'cert.pem'), os.path.join(self.dir, 'tls', 'key.pem')
        subprocess.run([OPENSSL, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', self.key, '-out', self.cert, '-days', '3', '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'], check=True, capture_output=True)
        self.log = os.path.join(self.dir, 'server.log')
        self.proc = subprocess.Popen([sys.executable, 'server.py'] + args, cwd=PROJ, env=dict(os.environ, TV_DATA_DIR=self.dir, PYTHONUNBUFFERED='1'),
                                     stdout=open(self.log, 'w'), stderr=subprocess.STDOUT)
        time.sleep(4)
        self.out = open(self.log, encoding='utf-8', errors='replace').read()
        m = re.search(r'Setup code[^A-Z0-9]*([A-Z0-9-]{6,})', self.out)
        self.code = m.group(1) if m else None

    def client(self, base):
        ctx = ssl.create_default_context(cafile=self.cert)
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.HTTPCookieProcessor(cj))

        def call(path, body=None):
            hd = {'X-TV': '1', 'Origin': base}
            d = None
            if body is not None:
                d = json.dumps(body).encode()
                hd['Content-Type'] = 'application/json'
            r = op.open(urllib.request.Request(base + path, data=d, headers=hd, method='POST' if d else 'GET'), timeout=30)
            return r.status, dict(r.headers), json.loads(r.read() or b'{}')
        return call

    def stop(self):
        self.proc.terminate()
        time.sleep(0.5)
        tb = open(self.log, encoding='utf-8', errors='replace').read()
        ok('no tracebacks in the server log', 'Traceback' not in tb, tb[-160:] if 'Traceback' in tb else '')
        shutil.rmtree(self.dir, ignore_errors=True)


# ───── A) plain http + https beside it ─────
print('A) certificate found: plain http on 8125 and https on 8445')
A = Server('A', ['--port', '8125', '--https-port', '8445'])
try:
    ok('banner shows both addresses', 'http://localhost:8125' in A.out and 'https://' in A.out and '8445' in A.out, A.out.strip().splitlines()[0][:80])
    plain, secure = A.client('http://127.0.0.1:8125'), A.client('https://127.0.0.1:8445')
    s, h, j = plain('/api/auth/state')
    ok('plain http on the main port still works (the LAN address keeps working)', s == 200 and j.get('setup_needed') is True)
    s, h, j = secure('/api/auth/state')
    ok('https on the second port works with a trusting client', s == 200)
    plain('/api/auth/setup', {'setup_code': A.code, 'username': 'tlsuser', 'password': 'tls-pass-12345', 'import_existing': False})
    s, h, j = plain('/api/auth/login', {'username': 'tlsuser', 'password': 'tls-pass-12345'})
    ok('cookie over plain http has NO Secure flag (it could not be sent back otherwise)', 'Secure' not in h.get('Set-Cookie', '') and 'HttpOnly' in h.get('Set-Cookie', ''))
    s, h, j = secure('/api/auth/login', {'username': 'tlsuser', 'password': 'tls-pass-12345'})
    ck = h.get('Set-Cookie', '')
    ok('cookie over https is HttpOnly + SameSite + Secure', all(x in ck for x in ('HttpOnly', 'SameSite=Lax', 'Secure')))
    s, h, j = secure('/api/auth/me')
    ok('Secure cookie is sent back over https', s == 200 and j['user']['username'] == 'tlsuser')
    try:
        urllib.request.urlopen('https://127.0.0.1:8445/api/auth/state', timeout=10, context=ssl.create_default_context())
        untrusted = False
    except Exception as e:
        untrusted = 'certificate' in str(e).lower()
    ok('a client that does not trust the certificate gets a certificate error', untrusted)
    stalled = socket.create_connection(('127.0.0.1', 8445))
    stalled.sendall(b'\x16\x03')
    t0 = time.time()
    s, h, j = secure('/api/auth/me')
    ok('a stalled handshake does not block other users', s == 200 and time.time() - t0 < 3, f'{time.time() - t0:.2f}s')
    junk = socket.create_connection(('127.0.0.1', 8445))
    junk.sendall(b'\x16\x03\x01' + os.urandom(200))
    time.sleep(0.5)
    junk.close()
    stalled.close()
    s, h, j = secure('/api/auth/me')
    ok('junk bytes on the https port do not crash the server', s == 200)
    s, h, j = plain('/api/auth/me')
    ok('the plain port is unaffected', s in (200, 401))
finally:
    A.stop()

# ───── B) https only ─────
print('B) --https-only: https on the main port, plain http redirected')
B = Server('B', ['--port', '8126', '--https-only'])
try:
    ok('banner says HTTPS only', 'HTTPS only' in B.out, B.out.strip().splitlines()[0][:80])
    secure = B.client('https://127.0.0.1:8126')
    s, h, j = secure('/api/auth/state')
    ok('https on the main port works', s == 200)
    c = http.client.HTTPConnection('127.0.0.1', 8126, timeout=10)
    c.request('GET', '/login.html')
    r = c.getresponse()
    ok('plain http:// on that port is redirected to https://', r.status == 301 and r.getheader('Location') == 'https://127.0.0.1:8126/login.html', f'{r.status} {r.getheader("Location")}')
    secure('/api/auth/setup', {'setup_code': B.code, 'username': 'tlsuser', 'password': 'tls-pass-12345', 'import_existing': False})
    s, h, j = secure('/api/auth/login', {'username': 'tlsuser', 'password': 'tls-pass-12345'})
    ok('Secure cookie over https', 'Secure' in h.get('Set-Cookie', ''))
finally:
    B.stop()

print(f'{sum(res)}/{len(res)} passed')
sys.exit(0 if all(res) else 1)
