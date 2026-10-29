---
name: trading-analytics
description: Project knowledge for the testTrading dashboard's Analytics page (Nordnet CSV ledger -> asset explorer, habit/cost report, benchmark score, per-asset buy/sell charts). Load before continuing any work on analytics.html/js, trade_analytics.py, benchmark.py, symbols.py or server.py API routes.
---

# Trading Analytics — project state & how to continue

Owner's account: Nordnet 66262387 (SEK). Branch: `TestTrading` (commit + push after every working session — user rule).
Stack: plain HTML/CSS/vanilla JS, Chart.js 4.4.0 (CDN), Python stdlib only (no pip). Dark TradingView theme tokens in `style.css` / `analytics.css`.

## Run
```powershell
cd "c:\Users\Administrator\Documents\Agentic World\testTrading"
python server.py            # http://localhost:8000  (Portfolio)   /analytics.html  (Analytics)
python trade_analytics.py   # prints the analytics JSON summary (quick engine check)
python benchmark.py         # prints the index buy-and-hold comparison
```
Restarting on Windows: `pkill` does not work; use PowerShell `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ? CommandLine -match server.py | % { Stop-Process -Id $_.ProcessId -Force }`.

## Ground-truth data (the heart of everything)
Newest match wins (ledger: newest mtime; holdings: date in the file name, then mtime), so the user just drops fresh exports there:
- `transactions-and-notes-export*.csv` — full ledger (UTF-16, tab separated, Swedish headers).
- `Innehav*Export*.csv` — current holdings for ALL instruments (stocks, ETFs, funds in ONE file, `Innehav Tabell Export, accno N, YYYY-MM-DD.csv`; prices, GAV, value). No ISIN column -> matched to ledger assets by name. Only the newest file is used. Headers have non-breaking spaces.
The Portfolio page (`app.js`) reads the same file through `server.py` `/api/holdings` and splits funds/stocks with `isFundName()`. `nordnet_sync.py` only copies exports and writes `portfolio_baseline.json` (previous export). The legacy `aktier_*/fonder_*/portfolio_*.csv` files are no longer read by any code (kept in git as history).
**Data in git:** user confirmed (personal repo) the ledger and holdings CSVs are committed.

## Architecture
| File | Role |
|---|---|
| `trade_analytics.py` | Parse ledger+holdings, rebuild positions, trades/assets/insights/scorecard JSON. `BENCHMARKS` list = scoring targets (rule-of-thumb, editable). Cache key = path+mtime+size. |
| `benchmark.py` | "Every deposit into OMXS30 / S&P500 (via USDSEK)" vs account value, Yahoo daily closes, 6 h memory cache + `benchmark_cache.json` offline fallback. |
| `symbols.py` | ISIN/name -> Yahoo symbol; seeds from `TICKER_MAP` in app.js, then Yahoo search; `symbol_cache.json` (hand edits are kept, negatives retried after 7 days). |
| `server.py` | Original file server + Yahoo proxy, plus `/api/trades`, `/api/trades/status`, `/api/benchmark`, `/api/symbol`. |
| `analytics.html/css/js` | The page. Tabs: **Assets** (view chips, filters, 4 charts, sortable table, expandable rows), **Trading habits & costs** (verdict, benchmark score, good practice, findings, charts, tables) and **Deposit behaviour** (`#deposits`: deposits as columns per day/week/month + estimated portfolio value / deposit-free return + positions held, three stacked charts with a linked crosshair; deposit-vs-market-move stats from `deposit_behavior()` in trade_analytics.py). Polls `/api/trades/status` every 10 s and reloads when a CSV changes. |
| `asset_chart.js` | `AssetChart.render(el, asset)`: Yahoo daily-close line + BUY/SELL markers; falls back to the user's own trade prices when no symbol / currency mismatch. |
Existing Portfolio page (`index.html`, `app.js`, `style.css`) got an "Analytics" link and a **Heat map** nav tab (NOT part of Analytics): `heatmap.js`/`heatmap.css` (squarified treemap of current holdings grouped by Yahoo sector / type / country, coloured by day change or unrealised %, plus doughnut, breakdown table, concentration notes). Data: `/api/assets` (assets from the payload) and `/api/sectors` (`sectors.py`, cache `sector_cache.json`; ETFs/funds have no Yahoo sector so they group as ETFs/Funds, unknown = Unclassified). Portfolio page is ONE continuous page (no separate Stocks/Funds tabs): summary, signals, stocks, funds, then `#heatmap-section`; the nav buttons Portfolio / Heat map just scroll (`app.js`), `Heat.show()` runs at page load. Live: while the tab is open it polls `/api/trades/status` every 10 s (new/changed CSV -> reload assets, sectors, live) and `/api/live` every 30 s (`server.py` `_live_quotes`: Yahoo v8 chart per holding via `symbols.resolve`, 25 s cache). Live price replaces the day change; value/unrealised are rescaled by live/export price only when currencies match. Pitfalls learned: never use Yahoo `meta.chartPreviousClose` for the day change (with range=5d it is the close before the whole window -> Micron showed +9% instead of -5%); `_live_quote` takes the last daily close dated before the current session (EU listings have a null close for the open session). Nordnet funds (Yahoo `0P...` symbols) keep the export day%/value; same-currency quotes whose price is >2x/<0.5x the export price are a wrong symbol and ignored; fix the symbol by hand in `symbol_cache.json` (source `manual`) and `TICKER_MAP` in app.js (fixed: XRS2.DE, IUSL.DE, XACT-OMXS30.ST, STMPA.PA, SPYL.DE). Verify with the live-vs-Nordnet-day% comparison (72 of 84 within 0.15 pt; the rest are other-currency listings or funds). Keep the Portfolio page working.

## Domain rules learned the hard way
- The type string for sells is **`SÅLT`** (Å, not Ä); buys `KÖPT`. Use the `\u` escapes in `trade_analytics.py`.
- `Total Avgift` = all fees (SEK); `Courtage` = commission; FX/other = difference. `Belopp` is net of fees (buy negative).
- Ledger rebuild must equal holdings export; warnings list any mismatch (currently only a 0-value "Lunar Royalties Corp SDB TAX" row).
- Corporate actions: BYTE/SPLIT pairs share a verification number -> ISIN alias + cost carried; FISSION / dividend-in-kind get zero cost (so later sells of those look like pure gain).
- Realised P&L = average cost in SEK incl. fees (differs a little from Nordnet's `Resultat`); holding period = FIFO.
- Compare prices across listings in SEK (`price * fx`), never raw (AstraZeneca trades in both USD and SEK).
- Asset type/country are heuristics (name regex, ISIN prefix); the CSV has no sector data — never invent one.
- Windows 1W/1M count back from today's date, not from the last CSV date.

## Current results (as of ledger to 2026-10-22; re-run to refresh)
Account ~break-even (+97 kr on 347 400 deposited); broker costs 21 724 kr (6.3% of deposits); fees > gross profit from sells; 0-1 day flips lose; habit score ~22/100 (F); OMXS30 / S&P500 buy-and-hold would be ~+11% / ~+18%.

## Verified / not verified
Verified (headless Chrome, 2026-10-23): benchmark score + index chart + good-practice cards, per-asset charts (MU, ALFA.ST live; ETF currency mismatch falls back), ledger==holdings (0 mismatches), chips/filters/sort/expand in headless Chrome, 400px layout. Check `git log` for later sessions. Per-asset charts: symbol lookup tested live; currency-mismatch listings (e.g. SMH in USD vs EUR trades, VUSA.L in GBp) intentionally fall back to trade prices — fix by adding a same-currency symbol by hand in `symbol_cache.json`.

## Deposit behaviour notes
- Index overlay (checkboxes OMXS30 / S&P 500 / Nasdaq 100 futures NQ=F): `/api/overlay` -> `benchmark.overlay()` (Yahoo ^OMX ^GSPC NQ=F, US ones x USDSEK, cached 6 h + benchmark_overlay_cache.json, gitignored). Return view = price return since first deposit; value view = all deposits invested in the index. Add more indices in `OVERLAY_INDICES` + `OV_COLOR`/checkbox.
- Portfolio value history is an ESTIMATE (no price feed): positions priced from own trades, linearly interpolated to today's holdings price. Real Yahoo history per holding would make it exact (see Ideas).
- Return index removes deposits/withdrawals (time-weighted); deposit "5 days before" move uses it. Thresholds: drop <= -2%, rise >= +2%.
- Holdings export is live but the ledger lags by a day: holdings > ledger qty is shown as a 'bought today' note, not an error.

## Ideas not done yet
- Exact portfolio value history from Yahoo closes per holding (replace the estimate).
- Account-value-over-time chart (needs historical prices per holding).
- Monthly fee budget / "order too small" warning on the page.
- Dividend/yield analysis page; tax (ISK) view.
- Let the user override asset type/country (`asset_overrides.json`).

## Conventions
- Keep Portfolio page untouched except bug fixes; new work goes in the analytics files.
- Match existing style (compact, comments only for non-obvious "why"). Charts: categorical colours `--s1..--s8` fixed order, green/red only for gain/loss, no dual-axis charts, tooltips on every chart.
- Test with headless Chrome (puppeteer-core in a scratchpad dir, never in the project) after UI changes.
- At the end of a session: update this file's "Current results / Ideas", commit, push to `TestTrading`.
