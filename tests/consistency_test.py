"""
Consistency test: the same quantity must have the same value wherever the dashboard shows it.

  python tests/consistency_test.py                      starts a scratch server on a spare port with a scratch data folder, creates a
                                                        profile from the Nordnet files in the project folder, and checks every route
  python tests/consistency_test.py URL USER PASSWORD    checks a server that is already running (read-only)

It reads the one valuation (/api/snapshot) and every other source of the same numbers (overview, assets, advice, growth curve,
deposit analysis, reports, chat) and fails when two differ by more than valuation.allowed(): max(5 kr, 0.05% of the figure).
Numbers that come from the same snapshot are expected to be identical; the tolerance covers rounding and currency conversion.
The Portfolio page, Analytics and the heat map read the same routes; their on-screen numbers are checked in the browser tests.
"""
import http.cookiejar
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, PROJ)
import valuation   # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (('  ' + str(detail)) if detail else ''))


def same(name, a, b):
    ok = valuation.agree(a, b)
    check(name, ok, f'{a} vs {b}' + ('' if ok else f'  (allowed {valuation.allowed(max(abs(a or 0), abs(b or 0))):.1f})'))


class Client:
    def __init__(self, base):
        self.base = base
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path, body=None):
        hd = {'X-TV': '1', 'Origin': self.base}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hd['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base + path, data=data, headers=hd, method='POST' if data is not None else 'GET')
        try:
            with self.op.open(req, timeout=180) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')


def run(c):
    s, snap = c.call('/api/snapshot')
    check('snapshot available', s == 200 and snap.get('ok'), s)
    if s != 200:
        return
    T, A = snap['totals'], snap['assets']
    print(f"  valued {snap['asof']} with live prices for {T['live_positions']} of {T['positions']} holdings; export {snap['export_date']}")

    # 1. the snapshot is internally consistent
    same('holdings + cash = account value', T['holdings'] + T['cash'], T['account'])
    same('account value - net deposits = all-time result', T['account'] - T['net_deposits'], T['all_time'])
    same('sum of holding values = holdings value', sum(a['value'] for a in A.values()), T['holdings'])
    same('sum of unrealised = unrealised total', sum(a['unrealized'] for a in A.values()), T['unrealized'])
    same("sum of today's P&L = today's P&L total", sum(a['day_pnl'] for a in A.values()), T['day_pnl'])
    check('position count = number of holdings', T['positions'] == len(A), f"{T['positions']} vs {len(A)}")
    check('weights sum to 100%', abs(sum(a['weight'] for a in A.values()) - 100) < 0.05, round(sum(a['weight'] for a in A.values()), 3))

    # 2. analytics payload (Analytics page, habit scores)
    s, tr = c.call('/api/trades')
    ov = tr['insights']['overview']
    same('analytics: holdings value', ov['holdings_value'], T['holdings'])
    same('analytics: account value', ov['total_value'], T['account'])
    same('analytics: unrealised', ov['unrealized'], T['unrealized'])
    same('analytics: all-time result', ov['all_time_pnl'], T['all_time'])
    held = [a for a in tr['assets'] if a.get('held') and a.get('value')]
    same('analytics: sum of asset values', sum(a['value'] for a in held), T['holdings'])
    same('analytics: sum of asset unrealised', sum(a['unrealized'] for a in held), T['unrealized'])
    top = [i['value'] for i in tr['insights']['scorecard']['items'] if i['key'] == 'top_weight'][0]
    check('analytics: largest position share = snapshot', abs(top - max(a['weight'] for a in A.values())) < 0.05, f"{top} vs {max(a['weight'] for a in A.values()):.2f}")
    db = tr['insights']['deposit_behavior']
    same('deposit tab: end value = account value', db['series'][-1]['value'], T['account'])
    check('analytics payload carries no private fields', '_cash_events' not in tr)

    # 3. assets route (heat map metadata)
    s, ax = c.call('/api/assets')
    ah = [a for a in ax['assets'] if a.get('held') and a.get('value')]
    same('assets route: holdings value', sum(a['value'] for a in ah), T['holdings'])
    mism = [a['name'] for a in ah if a['isin'] in A and not valuation.agree(a['value'], A[a['isin']]['value'])]
    check('assets route: every holding equals the snapshot', not mism, mism[:3])

    # 4. growth curve
    s, nv = c.call('/api/nav')
    check('growth curve available', s == 200 and nv.get('ok'), nv.get('message') or s)
    if nv.get('ok'):
        n = len(nv['dates']) - 1
        same('growth curve: last account value', nv['total']['nav'][n], T['account'])
        same('growth curve: last cash', nv['total']['cash'][n], T['cash'])
        same('growth curve: categories add up to holdings', sum(cv['value'][n] for cv in nv['categories'].values()), T['holdings'])
        check('growth curve = deposit tab growth index', abs(nv['total']['twr'][n] - db['series'][-1]['index']) < 0.01, f"{nv['total']['twr'][n]} vs {db['series'][-1]['index']}")
        same('growth curve: net deposits', nv['total']['net_deposits'][n], T['net_deposits'])
        check('growth curve summary uses the same last value', abs(nv['summary']['nav'] - T['account']) <= valuation.allowed(T['account']), nv['summary']['nav'])

    # 5. advice
    s, adv = c.call('/api/advice')
    same('advice: holdings value', adv['summary']['total'], T['holdings'])
    check('advice: position count', adv['summary']['positions'] == T['positions'], f"{adv['summary']['positions']} vs {T['positions']}")

    # 6. reports calendar weights
    s, rp = c.call('/api/reports')
    bad = []
    for g in rp.get('groups', {}).values():
        for it in g:
            a = A.get(it['isin'])
            if a and abs(it['weight'] - a['weight']) > 0.06:
                bad.append((it['name'], it['weight'], a['weight']))
    check('reports calendar: weights = snapshot weights', not bad, bad[:3])

    # 7. chat
    s, an = c.call('/api/ask', {'q': 'what is my net asset value'})
    m = re.search(r'Net asset value ([\d\s ]+) kr', an.get('answer', ''))
    if m:
        v = float(re.sub(r'\D', '', m.group(1)))
        same('chat: net asset value', v, T['account'])
    else:
        check('chat: net asset value answer', False, an.get('answer'))
    s, an = c.call('/api/ask', {'q': 'how much is my total fees'})
    check('chat answers a second question', an.get('ok'), an.get('answer', '')[:60])


def main():
    if len(sys.argv) >= 4:
        c = Client(sys.argv[1].rstrip('/'))
        s, r = c.call('/api/auth/login', {'username': sys.argv[2], 'password': sys.argv[3]})
        if s != 200:
            sys.exit(f'login failed ({s})')
        run(c)
    else:
        data = tempfile.mkdtemp(prefix='tv_consistency_')
        port = 8190
        env = dict(os.environ, TV_DATA_DIR=data, PYTHONUNBUFFERED='1')
        log = open(os.path.join(data, 'server.log'), 'w')
        srv = subprocess.Popen([sys.executable, 'server.py', '--port', str(port)], cwd=PROJ, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            time.sleep(4)
            code = re.search(r'Setup code[^A-Z0-9]*([A-Z0-9-]{6,})', open(os.path.join(data, 'server.log'), encoding='utf-8', errors='replace').read())
            if not code:
                sys.exit('could not start the scratch server (is port 8190 free?)')
            c = Client(f'http://127.0.0.1:{port}')
            s, r = c.call('/api/auth/setup', {'setup_code': code.group(1), 'username': 'tester', 'password': 'tester-pass-123', 'import_existing': True})
            if s != 200 or not (r.get('imported') or {}).get('ledger'):
                sys.exit('no Nordnet files in the project folder to build a test profile from; pass URL USER PASSWORD of a running server instead')
            c.call('/api/auth/login', {'username': 'tester', 'password': 'tester-pass-123'})
            run(c)
        finally:
            srv.terminate()
            shutil.rmtree(data, ignore_errors=True)
    bad = results.count(False)
    print(f'\n{len(results) - bad}/{len(results)} passed  (tolerance: max({valuation.TOLERANCE_KR:g} kr, {valuation.TOLERANCE_REL * 100:g}% of the figure))')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
