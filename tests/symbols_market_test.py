"""Market-aware symbol resolution (symbols.py), no network: Yahoo search and chart are replaced by made-up answers.
Run   python tests/symbols_market_test.py
Proves: the Nordnet market picks the Yahoo suffix; the listing on that venue in the export currency wins (ASML.AS, not the US
ASML; VVSM.DE, not SMH; IS3N.DE, not EIMI.L; the NYSE Celestica, not CLS.TO); a sister share class with another long name is
never taken; cached entries that conflict with the market are looked up again once and keep the market used; manual entries,
consistent entries and calls without a market are never re-checked; a Yahoo failure keeps the old entry; the parser keeps the
Market column."""
import json
import os
import shutil
import sys
import tempfile
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the project folder
sys.path.insert(0, PROJ)
sys.dont_write_bytecode = True
import symbols            # noqa: E402
import trade_analytics    # noqa: E402

res = []


def ok(n, c, d=''):
    res.append(bool(c))
    print(('PASS ' if c else 'FAIL ') + n + ('  ' + str(d)[:160] if d else ''))


tmp = tempfile.mkdtemp(prefix='symtest_')
symbols.CACHE_FILE = os.path.join(tmp, 'symbol_cache.json')               # never the project's cache
symbols.APP_JS = os.path.join(tmp, 'app.js')
with open(symbols.APP_JS, 'w', encoding='utf-8') as f:                     # the seed map, with the old wrong entries
    f.write("const TICKER_MAP = {\n  'ASML HOLDING': 'ASML',\n  'VanEck Semiconductor ETF': 'SMH',\n  'Siemens AG': 'SIE.DE',\n};\n")


def q(sym, exch, name, kind='EQUITY'):
    return {'symbol': sym, 'exchange': exch, 'quoteType': kind, 'longname': name, 'shortname': name[:30]}


VV, EM, VA, VD = ('VanEck Semiconductor UCITS ETF', 'iShares Core MSCI EM IMI UCITS ETF USD (Acc)',
                  'Vanguard FTSE All-World High Dividend Yield UCITS ETF USD Accumulation',
                  'Vanguard FTSE All-World High Dividend Yield UCITS ETF USD Distributing')
SEARCH = {
    'NL0010273215': [q('ASML', 'NMS', 'ASML Holding N.V.'), q('ASML.AS', 'AMS', 'ASML Holding N.V.')],
    'IE00BMC38736': [q('SMH.L', 'LSE', VV, 'ETF'), {'symbol': 'IE00BMC38736.SG', 'exchange': 'STU', 'quoteType': 'MUTUALFUND'}],
    VV: [q('SMH', 'NMS', 'VanEck Semiconductor ETF', 'ETF'), q('SMH.L', 'LSE', VV, 'ETF'), q('VVSM.DE', 'GER', VV, 'ETF'),
         q('SMH.MI', 'MIL', VV, 'ETF')],
    'IE00BKM4GZ66': [q('EIMI.L', 'LSE', EM, 'ETF')],
    EM: [q('EIMI.L', 'LSE', EM, 'ETF'), q('EIMU.DE', 'GER', 'iShares Core MSCI EM IMI UCITS ETF USD (Dist)', 'ETF'),
         q('IS3N.DE', 'GER', EM, 'ETF'), q('EMIM.AS', 'AMS', EM, 'ETF'), q('EMIM.L', 'LSE', EM, 'ETF')],
    'IE00BK5BR626': [q('VHYA.L', 'LSE', VA, 'ETF')],
    VA: [], 'Vanguard FTSE All-World High Dividend Yield UCITS ETF': [q('VGWD.DE', 'GER', VD, 'ETF'), q('VGWE.DE', 'GER', VA, 'ETF')],
    'CA15101Q2071': [q('CLS.TO', 'TOR', 'Celestica Inc.')],
    'Celestica Inc.': [q('CLSF', 'PNK', 'Celestica Inc.'), q('CLS.TO', 'TOR', 'Celestica Inc.'), q('CLS', 'NYQ', 'Celestica Inc.')],
    'FI0009000681': [q('NOKIA.HE', 'HEL', 'Nokia Oyj')],
    'Nokia Oyj': [q('NOK', 'NYQ', 'Nokia Oyj'), q('NOKIA.HE', 'HEL', 'Nokia Oyj'), q('NOA3.DE', 'GER', 'Nokia Oyj'),
                  q('NOKIA-SEK.ST', 'STO', 'Nokia Oyj')],
    'LU1829221024': [q('NASD.L', 'LSE', 'Amundi Core Nasdaq-100 Swap UCITS ETF Acc', 'ETF')],
    'Amundi Core Nasdaq-100 Swap UCITS ETF Acc': [q('UST.PA', 'PAR', 'Amundi Core Nasdaq-100 Swap UCITS ETF Acc', 'ETF'),
                                                  q('NASD.L', 'LSE', 'Amundi Core Nasdaq-100 Swap UCITS ETF Acc', 'ETF')],
}
CHART = {'EIMI.L': 'USD', 'EMIM.L': 'GBp', 'SMH.L': 'USD', 'NASD.L': 'USD', 'VHYA.L': 'USD'}
calls = []
DOWN = [False]


def fake_quotes(query, n=10):
    calls.append(('search', query))
    if DOWN[0]:
        return None
    return [x for x in SEARCH.get(query, []) if (x.get('quoteType') or '').upper() in symbols._GOOD_TYPES]


def fake_chart(sym):
    calls.append(('chart', sym))
    return None if DOWN[0] else CHART.get(sym)


symbols._quotes = fake_quotes
symbols._chart_ccy = fake_chart


def cache():
    try:
        with open(symbols.CACHE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except OSError:
        return {}


def put(key, ent):
    c = cache()
    c[key] = ent
    with open(symbols.CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(c, f)


def sym(isin, name, ccy, market=None):
    return (symbols.resolve(isin, name, ccy, market) or {}).get('symbol')


try:
    # --- market name -> Yahoo suffix
    want = {'Euronext Amsterdam': '.AS', 'Xetra': '.DE', 'ETFs/Xetra': '.DE', 'Euronext Paris': '.PA', 'Euronext Brussels': '.BR',
            'Euronext Milan': '.MI', 'Borsa Italiana': '.MI', 'Nasdaq Stockholm AB': '.ST', 'First North Stockholm': '.ST',
            'Oslo Børs': '.OL', 'Nasdaq Helsinki Oy': '.HE', 'Nasdaq Copenhagen A/S': '.CO', 'London Stock Exchange': '.L',
            'Toronto Stock Exchange': '.TO', 'SIX Swiss Exchange': '.SW', 'New York Stock Exchange': '', 'Nasdaq': '', 'NYSE Arca': '',
            '': None, None: None, 'Some Other Exchange': None}
    got = {m: symbols.market_suffix(m) for m in want}
    ok('market -> suffix for every Nordnet market name', got == want, {m: g for m, g in got.items() if g != want[m]})

    # --- the listing on the holding's venue, in its currency
    ok('ASML (Euronext Amsterdam, EUR): ASML.AS, not the US ASML from the seed map', sym('NL0010273215', 'ASML HOLDING', 'EUR', 'Euronext Amsterdam') == 'ASML.AS')
    ok('VanEck Semiconductor (Xetra, EUR): VVSM.DE, not SMH / SMH.L', sym('IE00BMC38736', 'VanEck Semiconductor ETF', 'EUR', 'Xetra') == 'VVSM.DE')
    ok('iShares EM IMI (Xetra, EUR): IS3N.DE (the Dist class with the same index is not taken)',
       sym('IE00BKM4GZ66', 'iShares Core MSCI EM IMI UCITS ETF USD (Acc)', 'EUR', 'Xetra') == 'IS3N.DE')
    ok('Vanguard High Dividend Acc (Xetra): VGWE.DE, not the Distributing VGWD.DE listed first',
       sym('IE00BK5BR626', 'Vanguard FTSE All-World High Dividend Yield UCITS ETF - (USD) Acc', 'EUR', 'Xetra') == 'VGWE.DE')
    n = len(calls)
    ok('Celestica (New York Stock Exchange, USD): CLS, not CLS.TO nor the OTC line', sym('CA15101Q2071', 'Celestica', 'USD', 'New York Stock Exchange') == 'CLS')
    ok('Nokia in SEK on Nasdaq Stockholm: NOKIA-SEK.ST', sym('FI0009000681', 'Nokia', 'SEK', 'Nasdaq Stockholm AB') == 'NOKIA-SEK.ST')
    ok('Siemens (Xetra) from the seed map without asking Yahoo', sym('DE0007236101', 'Siemens AG', 'EUR', 'Xetra') == 'SIE.DE'
       and not any(c[1] == 'DE0007236101' for c in calls))
    e = cache()['CA15101Q2071']
    ok('the market and currency used are stored in the cache entry', e.get('market') == 'New York Stock Exchange' and e.get('ccy') == 'USD', e)

    # --- currency preference on a venue with several currencies (chart answers)
    calls.clear()
    SEARCH['IE00BKM4GZ67'] = SEARCH['IE00BKM4GZ68'] = [q('EMIM.L', 'LSE', EM, 'ETF'), q('EIMI.L', 'LSE', EM, 'ETF')]
    ok('London, USD: the chart currency decides between two .L lines (EIMI.L in USD, not EMIM.L in GBp)',
       sym('IE00BKM4GZ67', 'iShares EM IMI', 'USD', 'London Stock Exchange') == 'EIMI.L' and ('chart', 'EMIM.L') in calls,
       [c for c in calls if c[0] == 'chart'])
    ok('London, GBP: the GBp line for a GBP holding', sym('IE00BKM4GZ68', 'iShares EM IMI', 'GBP', 'London Stock Exchange') == 'EMIM.L')

    # --- cached entries
    now = time.time()
    put('CA15101Q2071', {'symbol': 'CLS.TO', 'currency': 'CAD', 'exchange': 'TOR', 'source': 'yahoo_search', 'checked': now})
    calls.clear()
    r1 = sym('CA15101Q2071', 'Celestica', 'USD', 'New York Stock Exchange')
    e = cache()['CA15101Q2071']
    ok('a cached listing on another market is looked up again and replaced', r1 == 'CLS' and e.get('was') == 'CLS.TO' and calls, e)
    calls.clear()
    ok('... and then served from the cache with no Yahoo call', sym('CA15101Q2071', 'Celestica', 'USD', 'New York Stock Exchange') == 'CLS' and not calls, calls)

    put('IE00BJZ2DD79', {'symbol': 'XRS2.DE', 'source': 'manual', 'checked': 0})
    calls.clear()
    ok('a manual entry is kept even when it contradicts the market', sym('IE00BJZ2DD79', 'Xtrackers Russell 2000', 'EUR', 'Euronext Paris') == 'XRS2.DE' and not calls)
    put('NL0000226223', {'symbol': 'STMPA.PA', 'source': 'yahoo_search', 'currency': 'EUR', 'exchange': 'PAR', 'checked': 0})
    ok('a consistent entry (Paris listing, Euronext Paris, EUR) is used as is', sym('NL0000226223', 'STMicroelectronics NV', 'EUR', 'Euronext Paris') == 'STMPA.PA' and not calls)
    put('XX0000000001', {'symbol': 'CLS.TO', 'source': 'yahoo_search', 'currency': 'CAD', 'checked': now})
    ok('without a market the cache is used as before (no re-check)', sym('XX0000000001', 'Celestica', 'USD') == 'CLS.TO' and not calls)
    put('SE0002756973', {'symbol': '0P0000J24W.ST', 'source': 'yahoo_search', 'checked': 0})
    ok('a Nordnet fund (0P symbol) is never re-checked', sym('SE0002756973', 'Nordnet Sverige Index', 'SEK', 'Xetra') == '0P0000J24W.ST' and not calls)

    put('LU1829221024', {'symbol': 'UST.PA', 'source': 'yahoo_search', 'currency': 'EUR', 'exchange': 'PAR', 'checked': now})
    r1 = sym('LU1829221024', 'Amundi Nasdaq-100 II UCITS ETF Acc', 'EUR', 'Xetra')
    e = cache()['LU1829221024']
    calls.clear()
    r2 = sym('LU1829221024', 'Amundi Nasdaq-100 II UCITS ETF Acc', 'EUR', 'Xetra')
    ok('no listing on the venue: the same-currency listing is kept, the market stored, no further Yahoo calls',
       r1 == r2 == 'UST.PA' and e.get('market') == 'Xetra' and not e.get('was') and not calls, (r1, r2, e, calls))

    put('NL0010273215', {'symbol': 'ASML', 'source': 'ticker_map', 'checked': now})
    DOWN[0] = True
    calls.clear()
    r1 = sym('NL0010273215', 'ASML HOLDING', 'EUR', 'Euronext Amsterdam')
    n1 = len(calls)
    r2 = sym('NL0010273215', 'ASML HOLDING', 'EUR', 'Euronext Amsterdam')
    ok('Yahoo down: the old entry is kept, nothing cached, no new attempt within the hour',
       r1 == r2 == 'ASML' and cache()['NL0010273215'].get('market') is None and n1 > 0 and len(calls) == n1, (r1, r2, calls))
    DOWN[0] = False
    symbols._RECHECKED.clear()
    ok('... and fixed on the next attempt', sym('NL0010273215', 'ASML HOLDING', 'EUR', 'Euronext Amsterdam') == 'ASML.AS')

    put('NAME:celestica', {'symbol': None, 'name': 'Celestica', 'checked': now})
    SEARCH['Celestica'] = [q('CLS.TO', 'TOR', 'Celestica Inc.'), q('CLS', 'NYQ', 'Celestica Inc.'), q('CLHI.TO', 'TOR', 'Ninepoint Celestica HighShares ETF', 'ETF')]
    calls.clear()
    ok('a recent miss (no ISIN) is retried once a market is known: name search, every word of the name must match',
       sym('', 'Celestica', 'USD', 'New York Stock Exchange') == 'CLS' and ('search', 'Celestica') in calls, calls)
    put('NAME:unknown thing ab', {'symbol': None, 'name': 'Unknown Thing AB', 'checked': now})
    calls.clear()
    ok('a recent miss without a market stays a miss with no Yahoo call (old behaviour)', sym('', 'Unknown Thing AB', 'SEK') is None and not calls)

    # --- of(): the market is passed only when the export gave one (a test's 3-argument stand-in keeps working)
    real = symbols.resolve
    symbols.resolve = lambda isin, name, ccy: {'symbol': 'OLD'}
    try:
        a = symbols.of({'isin': 'X', 'name': 'x', 'ccy': 'SEK'})
        b = symbols.of({'isin': 'X', 'name': 'x', 'ccy': 'SEK', 'market': ''})
    finally:
        symbols.resolve = real
    ok('of() without a market calls resolve(isin, name, ccy)', a == b == {'symbol': 'OLD'})
    ok('get() takes the optional market', symbols.get('NL0010273215', 'ASML HOLDING', 'EUR', 'Euronext Amsterdam').get('symbol') == 'ASML.AS')

    # --- parser: the Market column is kept; older layouts without it give ''
    hdr = ['Namn', 'Valuta', 'Antal', 'GAV/snittkurs', 'Idag %', 'Senaste kurs', 'Värde\xa0SEK', 'Avkast. %', 'Avkast.\xa0SEK', 'ISIN', 'Market']
    h = trade_analytics._parse_holdings_table(hdr, [['ASML HOLDING', 'EUR', '1', '600', '1,0', '700', '7700', '10', '700', 'NL0010273215', 'Euronext Amsterdam'],
                                                    ['Nordnet Sverige Index', 'SEK', '2', '100', '0', '110', '220', '10', '20', 'SE0002756973', '']])
    ok('parse keeps the Market column', h['ASML HOLDING']['market'] == 'Euronext Amsterdam' and h['Nordnet Sverige Index']['market'] == '', h['ASML HOLDING'])
    h = trade_analytics._parse_holdings_table(hdr[:9], [['ABB', 'SEK', '1', '500', '0', '550', '550', '10', '50']])
    ok('an old layout without Market parses with market ""', h['ABB']['market'] == '' and h['ABB']['value_sek'] == 550, h['ABB'])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('%d/%d passed' % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
