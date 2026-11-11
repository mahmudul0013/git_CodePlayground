"""
volatility.py - daily volatility of every holding over the last 3 months. Python stdlib only.

Definition (the usual one): the sample standard deviation of the daily price changes (close to close) over the last 63 trading days,
in %. A stock with 2.0% daily volatility typically moves about 2% on an ordinary day (two out of three days it stays within +-2%).
Also given: the same figure per year (daily x sqrt(252)) and the average absolute daily move.

Data: Yahoo daily closes from the shared price history of advisor.py (history_cache.json). Funds use the daily NAV of their Yahoo
fund page (0P... symbols): fine for volatility, even though those NAVs are not used to value anything. Nothing here touches the
network on a page request; missing or old history is fetched in the background and shows up on the next refresh.
"""
import math
import threading
import time

import advisor
import symbols

WINDOW = 63                 # trading days, about 3 months
MIN_RETURNS = 40            # fewer daily changes than this is not enough for a meaningful figure
REFRESH_AFTER = 12 * 3600   # history older than this is refreshed in the background (still used meanwhile)

_LOCK = threading.Lock()
_bg = {'busy': False}


def stats(closes):
    """Volatility figures from a list of daily closes (oldest first), or None when there are too few."""
    c = closes[-(WINDOW + 1):]
    rets = [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1] and c[i] and c[i - 1] > 0]
    if len(rets) < MIN_RETURNS:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    return {'daily': round(sd * 100, 3), 'annual': round(sd * math.sqrt(252) * 100, 1),
            'avg_abs': round(sum(abs(r) for r in rets) / len(rets) * 100, 3), 'days': len(rets)}


def _fetch_in_background(syms):
    with _LOCK:
        if _bg['busy'] or not syms:
            return
        _bg['busy'] = True

    def work():
        try:
            advisor._histories(sorted(set(syms)), 60)         # shared 2-year daily history, also used by the Add / Trim review
        except Exception:
            pass
        finally:
            with _LOCK:
                _bg['busy'] = False
    threading.Thread(target=work, daemon=True).start()


def for_assets(assets):
    """{isin: {daily, annual, avg_abs, days}} for the assets (dicts with isin / name / ccy) that have enough Yahoo history."""
    hist = advisor._load()
    out, need = {}, []
    now = time.time()
    for a in assets:
        r = symbols.resolve(a['isin'], a['name'], a.get('ccy'))
        sym = (r or {}).get('symbol')
        if not sym:
            continue
        h = hist.get(sym)
        if not h:
            need.append(sym)
            continue
        if now - h.get('at', 0) > REFRESH_AFTER:
            need.append(sym)                                    # stale: refresh later, use what we have now
        s = stats(h['c'])
        if s:
            out[a['isin']] = s
    if need:
        _fetch_in_background(need)
    return out
