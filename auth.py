"""
auth.py - accounts, invites, sessions and login throttling for the multi-user dashboard.
Python stdlib only. Everything lives under the data root (env TV_DATA_DIR, default <project>/data):

    users.json     users (scrypt password hashes, accno) and invites (only hashes of the codes)
    sessions.json  session records keyed by the SHA-256 of the token (the token itself is never stored)

Nothing here knows about portfolio data; profiles.py owns the per-user folders.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

SCRYPT = {'n': 2 ** 14, 'r': 8, 'p': 1}
SESSION_IDLE = 12 * 3600
SESSION_MAX = 30 * 86400
INVITE_TTL = 7 * 86400
MAX_FAILS = 5                     # per (ip, username) before the first lock
LOCK_BASE, LOCK_MAX = 60, 900     # seconds: 60, 120, 240 ... 900
IP_WINDOW, IP_MAX_FAILS, IP_LOCK = 600, 20, 300
B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'   # Crockford base32 (no I, L, O, U)
USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,32}$')

_LOCK = threading.RLock()
_loaded = False
_users = []
_invites = []
_sessions = {}
_setup_code = None
_fails = {}        # (ip, username_lower) -> {'n': count, 'until': ts}
_ip_fails = {}     # ip -> {'times': [ts...], 'until': ts}
_sessions_saved = 0.0
_DUMMY = None


class AuthError(Exception):
    def __init__(self, code, retry_after=0, message=''):
        super().__init__(message or code)
        self.code = code
        self.retry_after = retry_after
        self.message = message or code


def data_dir():
    return os.path.abspath(os.environ.get('TV_DATA_DIR') or os.path.join(HERE, 'data'))


def _p(name):
    return os.path.join(data_dir(), name)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_users():
    _write_json(_p('users.json'), {'users': _users, 'invites': _invites})


def _save_sessions(force=True):
    global _sessions_saved
    if not force and time.time() - _sessions_saved < 300:
        return
    _write_json(_p('sessions.json'), _sessions)
    _sessions_saved = time.time()


def init():
    """Load users and sessions (idempotent). Creates the setup code while there are no users."""
    global _loaded, _users, _invites, _sessions, _setup_code
    with _LOCK:
        d = _read_json(_p('users.json'), {})
        _users = list(d.get('users') or [])
        _invites = list(d.get('invites') or [])
        _sessions = dict(_read_json(_p('sessions.json'), {}))
        _loaded = True
        _prune_sessions()
        _setup_code = None if _users else _new_code(8)


def _ensure():
    if not _loaded:
        init()


def _new_code(n):
    return ''.join(secrets.choice(B32) for _ in range(n))


def _sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def sid_of(uid):
    """Short stable id derived from the uid; the frontend appends it to localStorage keys."""
    return _sha(uid)[:8]


# ───────── passwords ─────────
def _scrypt(password, salt, n=SCRYPT['n'], r=SCRYPT['r'], p=SCRYPT['p']):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=n, r=r, p=p, dklen=32)


def _hash_pw(password):
    salt = secrets.token_bytes(16)
    return {'salt': salt.hex(), 'hash': _scrypt(password, salt).hex(), **SCRYPT}


def _check_pw(password, rec):
    try:
        h = _scrypt(password, bytes.fromhex(rec['salt']), rec['n'], rec['r'], rec['p'])
        return hmac.compare_digest(h, bytes.fromhex(rec['hash']))
    except Exception:
        return False


def _check_username(username):
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        raise AuthError('invalid', message='Username must be 3-32 characters: letters, digits, dot, dash, underscore.')


def _check_password(password, username=''):
    if not isinstance(password, str) or len(password) < 8:
        raise AuthError('invalid', message='Password must be at least 8 characters.')
    if len(password) > 200:
        raise AuthError('invalid', message='Password is too long.')
    if username and password.lower() == username.lower():
        raise AuthError('invalid', message='Password must not equal the username.')


def _find(uid):
    for u in _users:
        if u['uid'] == uid:
            return u
    return None


def _find_name(username):
    low = (username or '').lower()
    for u in _users:
        if u['username'].lower() == low:
            return u
    return None


def _public(u):
    return {'uid': u['uid'], 'username': u['username'], 'role': u['role'], 'accno': u.get('accno'),
            'created': u['created'], 'last_login': u.get('last_login')}


def _new_user(username, password, role):
    _check_username(username)
    _check_password(password, username)
    if _find_name(username):
        raise AuthError('exists', message='That username is taken.')
    u = {'uid': secrets.token_hex(8), 'username': username, 'role': role, 'pw': _hash_pw(password),
         'accno': None, 'created': time.time(), 'last_login': None}
    _users.append(u)
    _save_users()
    return u


# ───────── setup, invites, registration ─────────
def has_users():
    _ensure()
    return bool(_users)


def setup_code():
    _ensure()
    return _setup_code if not _users else None


def create_admin(code, username, password):
    global _setup_code
    _ensure()
    with _LOCK:
        if _users:
            raise AuthError('forbidden', message='Setup is already done.')
        if not _setup_code or not hmac.compare_digest(str(code or '').strip().upper().encode(), _setup_code.encode()):
            raise AuthError('bad_setup_code', message='Wrong setup code (see the server console).')
        u = _new_user(username, password, 'admin')
        _setup_code = None
        return _public(u)


def _norm_code(code):
    c = re.sub(r'[\s-]', '', str(code or '').upper())
    return c.translate(str.maketrans({'O': '0', 'I': '1', 'L': '1'}))


def create_invite(admin_uid):
    _ensure()
    with _LOCK:
        a = _find(admin_uid)
        if not a or a['role'] != 'admin':
            raise AuthError('forbidden')
        raw = _new_code(12)
        now = time.time()
        _invites.append({'code_hash': _sha(raw), 'created_by': admin_uid, 'created': now, 'expires': now + INVITE_TTL, 'used_by': None})
        _save_users()
        return f'{raw[:4]}-{raw[4:8]}-{raw[8:]}', now + INVITE_TTL


def register(code, username, password):
    _ensure()
    with _LOCK:
        h = _sha(_norm_code(code))
        now = time.time()
        inv = next((i for i in _invites if hmac.compare_digest(i['code_hash'], h)), None)
        if not inv or inv['used_by'] or inv['expires'] < now:
            raise AuthError('bad_invite', message='That invite code is invalid, used or expired.')
        u = _new_user(username, password, 'user')      # raises before the invite is consumed
        inv['used_by'] = u['uid']
        _save_users()
        return _public(u)


def list_invites():
    _ensure()
    now = time.time()
    with _LOCK:
        names = {u['uid']: u['username'] for u in _users}
        return [{'id': i['code_hash'][:8], 'created': i['created'], 'expires': i['expires'],
                 'status': 'used' if i['used_by'] else ('expired' if i['expires'] < now else 'open'),
                 'used_by': names.get(i['used_by'])} for i in _invites]


# ───────── login (throttled) ─────────
def _dummy_verify(password):
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = _hash_pw('x' * 12)
    _check_pw(password, _DUMMY)


def verify(username, password, ip):
    """Return the user (public dict) or raise AuthError('locked', retry_after) / AuthError('bad')."""
    _ensure()
    key = ((ip or '?'), str(username or '').lower())
    now = time.time()
    with _LOCK:
        f = _fails.get(key)
        ipf = _ip_fails.get(key[0])
        until = max((f or {}).get('until', 0), (ipf or {}).get('until', 0))
        if until > now:
            raise AuthError('locked', retry_after=int(until - now) + 1, message='Too many attempts. Try again later.')
        u = _find_name(username) if isinstance(username, str) else None
        rec = dict(u['pw']) if u else None
    ok = _check_pw(password, rec) if rec and isinstance(password, str) else (_dummy_verify(str(password)[:200]) or False)
    with _LOCK:
        if ok:
            _fails.pop(key, None)
            u = _find_name(username)
            u['last_login'] = time.time()
            _save_users()
            return _public(u)
        f = _fails.setdefault(key, {'n': 0, 'until': 0})
        f['n'] += 1
        if f['n'] >= MAX_FAILS:
            f['until'] = time.time() + min(LOCK_BASE * 2 ** (f['n'] - MAX_FAILS), LOCK_MAX)
        ipf = _ip_fails.setdefault(key[0], {'times': [], 'until': 0})
        ipf['times'] = [t for t in ipf['times'] if t > now - IP_WINDOW] + [now]
        if len(ipf['times']) >= IP_MAX_FAILS:
            ipf['until'] = now + IP_LOCK
        if len(_fails) > 5000:            # bound memory: forget the oldest records
            for k in list(_fails)[:2500]:
                _fails.pop(k, None)
    raise AuthError('bad', message='Wrong username or password.')


# ───────── sessions ─────────
def _prune_sessions():
    now = time.time()
    dead = [h for h, s in _sessions.items() if now - s['last_seen'] > SESSION_IDLE or now - s['created'] > SESSION_MAX or not _find(s['uid'])]
    for h in dead:
        _sessions.pop(h, None)


def new_session(uid):
    _ensure()
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _LOCK:
        _prune_sessions()
        _sessions[_sha(token)] = {'uid': uid, 'created': now, 'last_seen': now}
        _save_sessions()
    return token


def session_user(token):
    _ensure()
    if not token or not isinstance(token, str) or len(token) > 200:
        return None
    h = _sha(token)
    now = time.time()
    with _LOCK:
        s = _sessions.get(h)
        if not s:
            return None
        if now - s['last_seen'] > SESSION_IDLE or now - s['created'] > SESSION_MAX:
            _sessions.pop(h, None)
            _save_sessions()
            return None
        u = _find(s['uid'])
        if not u:
            _sessions.pop(h, None)
            return None
        s['last_seen'] = now
        _save_sessions(force=False)
        return _public(u)


def logout(token):
    _ensure()
    with _LOCK:
        if _sessions.pop(_sha(token or ''), None) is not None:
            _save_sessions()


def logout_all(uid):
    _ensure()
    with _LOCK:
        for h in [h for h, s in _sessions.items() if s['uid'] == uid]:
            _sessions.pop(h, None)
        _save_sessions()


# ───────── account management ─────────
def get_user(uid):
    _ensure()
    with _LOCK:
        u = _find(uid)
        return _public(u) if u else None


def change_password(uid, old, new):
    _ensure()
    with _LOCK:
        u = _find(uid)
        if not u or not _check_pw(str(old or ''), u['pw']):
            raise AuthError('bad', message='Current password is wrong.')
        _check_password(new, u['username'])
        u['pw'] = _hash_pw(new)
        _save_users()
    logout_all(uid)


def verify_password(uid, password):
    """Plain password check for an already signed-in user (no throttling needed: a session is required to get here)."""
    _ensure()
    with _LOCK:
        u = _find(uid)
        return bool(u) and _check_pw(str(password or ''), u['pw'])


def reset_password(admin_uid, target_uid, new):
    _ensure()
    with _LOCK:
        a, u = _find(admin_uid), _find(target_uid)
        if not a or a['role'] != 'admin':
            raise AuthError('forbidden')
        if not u:
            raise AuthError('not_found', message='No such user.')
        _check_password(new, u['username'])
        u['pw'] = _hash_pw(new)
        _save_users()
    logout_all(target_uid)


def delete_user(admin_uid, target_uid):
    _ensure()
    with _LOCK:
        a, u = _find(admin_uid), _find(target_uid)
        if not a or a['role'] != 'admin':
            raise AuthError('forbidden')
        if not u:
            raise AuthError('not_found', message='No such user.')
        if u['uid'] == admin_uid:
            raise AuthError('forbidden', message='The admin cannot delete their own account.')
        _users.remove(u)
        _save_users()
    logout_all(target_uid)


def delete_self(uid, password):
    """Remove the caller's own (non-admin) account after a password check. Files are removed by the caller."""
    _ensure()
    with _LOCK:
        u = _find(uid)
        if not u or not _check_pw(str(password or ''), u['pw']):
            raise AuthError('bad', message='Password is wrong.')
        if u['role'] == 'admin':
            raise AuthError('forbidden', message='The admin account cannot be deleted; delete only the files.')
        _users.remove(u)
        _save_users()
    logout_all(uid)


def list_users():
    _ensure()
    with _LOCK:
        return [_public(u) for u in _users]


# ───────── account number binding (one Nordnet accno per profile, unique across profiles) ─────────
def accno_owner(accno):
    _ensure()
    with _LOCK:
        u = next((u for u in _users if u.get('accno') and u['accno'] == str(accno)), None)
        return u['uid'] if u else None


def bind_accno(uid, accno):
    """Atomic check-and-set. True if the profile now carries this accno (new or already), False if another user owns it
    or the profile is bound to a different accno."""
    _ensure()
    accno = str(accno)
    with _LOCK:
        u = _find(uid)
        if not u:
            return False
        owner = accno_owner(accno)
        if owner and owner != uid:
            return False
        if u.get('accno') and u['accno'] != accno:
            return False
        u['accno'] = accno
        _save_users()
        return True


def unbind_accno(uid):
    _ensure()
    with _LOCK:
        u = _find(uid)
        if u:
            u['accno'] = None
            _save_users()
