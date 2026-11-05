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
Existing Portfolio page (`index.html`, `app.js`, `style.css`) got an "Analytics" link and a **Heat map** nav tab (NOT part of Analytics): `heatmap.js`/`heatmap.css` (squarified treemap of current holdings grouped by Yahoo sector / type / country, coloured by day change or unrealised %, plus doughnut, breakdown table, concentration notes). Data: `/api/assets` (assets from the payload) and `/api/sectors` (`sectors.py`, cache `sector_cache.json`; ETFs/funds have no Yahoo sector so they group as ETFs/Funds, unknown = Unclassified). Portfolio page is ONE continuous page (no separate Stocks/Funds tabs): summary, signals, stocks, funds, then `#heatmap-section`; the nav buttons Portfolio / Heat map just scroll (`app.js`), `Heat.show()` runs at page load. Live: while the tab is open it polls `/api/trades/status` every 10 s (new/changed CSV -> reload assets, sectors, live) and `/api/live` every 30 s (`server.py` `_live_quotes`: Yahoo v8 chart per holding via `symbols.resolve`, 25 s cache). Live price replaces the day change; value/unrealised are rescaled by live/export price only when currencies match. Pitfalls learned: never use Yahoo `meta.chartPreviousClose` for the day change (with range=5d it is the close before the whole window -> Micron showed +9% instead of -5%); `_live_quote` takes the last daily close dated before the current session (EU listings have a null close for the open session). Nordnet funds (Yahoo `0P...` symbols) keep the export day%/value; same-currency quotes whose price is >2x/<0.5x the export price are a wrong symbol and ignored; fix the symbol by hand in `symbol_cache.json` (source `manual`) and `TICKER_MAP` in app.js (fixed: XRS2.DE, IUSL.DE, XACT-OMXS30.ST, STMPA.PA, SPYL.DE). Verify with the live-vs-Nordnet-day% comparison (72 of 84 within 0.15 pt; the rest are other-currency listings or funds). Layout rules: `#app`/`#main-content` use `overflow: clip` so nothing (scrollIntoView, focus) can scroll the header under the fixed ticker; the header wraps (`flex-wrap`) so no control is ever cut off at narrow widths; nav buttons scroll `#scroll-body` manually (never `scrollIntoView`). Portfolio page Today's P&L: the export's `Idag %` is ~0 on weekends/outside trading hours, so the card shows a placeholder until the first live fetch (`S.liveLoaded`); names missing in `TICKER_MAP` get a Yahoo symbol from the server (`loadAutoTickers()` -> /api/assets + /api/live, same-currency listings only, funds `0P...` skipped), so day P&L covers ~99% of the portfolio. Keep the Portfolio page working.

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
- Tax (ISK) view; dividend forecast / yield per holding.

## Dividends tab
`dividend_analysis()` in trade_analytics.py (from the ledger: UTDELNING = dividend, KÄLLSKATT / TYSK SOL SKATT UTD = tax; kr, booking date) -> `insights.dividends` {series per day, payers, summary}. Dividends were always inside the account value / all-time result (they land in cash); the tab only makes them visible: KPI row, per day/week/month stacked net+tax columns, cumulative line, per-calendar-month seasonality, top payers (green held / grey sold), payer table, insight cards. Privacy CSS masks `#div-kpis`. Result at 2026-11-01: 2 444 kr net (2 833 gross, 389 tax) from 79 companies; all-time result -1 076 kr incl., -3 521 kr without.

## Advice engine (replaces "Tomorrow's Signals")
`advisor.py` -> `/api/advice` (cached per payload + hour; Yahoo 2y adjusted closes in `history_cache.json`, gitignored, 6 h TTL). Position management, NOT a forecast. A back-test on the 77 held assets (5y daily, ~70k samples; scripts were in the session scratchpad, numbers are shown in the Advice tab) found: the old 8-indicator next-day score had no edge (Strong Buy: -0.25% next day, 43% up; rank IC ~ -0.02..-0.05), "trim when overbought" would have sold winners (+15% vs +9.6% next 63d), broken-trend has no sell edge, pullback-in-uptrend add is only a small tilt (+12.8% vs +10.5%). Caveats: survivorship (stocks you chose) and a 2021-26 bull market. So actions: TRIM = weight > 4% or theme (Yahoo sector) > 40% and weight >= 2.5% (give back a fifth); ADD = weight < 1.5%, close > 200d and 50d > 200d, 12-1 momentum > 0, 5-25% below 52w high, RSI < 68, theme not over cap (fill to 2%, min order 1 500 kr, score = momentum rank + pullback + low vol); BUYBACK = the same trend / pullback test on CLOSED positions (>= 7 days after the last sell, sector not over cap, 1.5% sized, shows sold price vs now when currencies match; history + sector lookups for ~110 closed assets make the first call slow, so a partial answer is cached only 90 s); CONSOLIDATE = < 1 500 kr; REVIEW = downtrend + negative momentum + > 15% under cost. Cards: fragmentation, theme concentration, portfolio vol / 1y max drawdown / avg correlation of top 30 (effective bets), trend health, size of changes. Constants at the top of advisor.py. UI: Analytics tab "Advice", column "Add / trim" in the Assets table (sortable, tooltip = reasons), Portfolio page "Add / Trim Ideas" panel (`loadPredictions()` in app.js now calls /api/advice; the old client-side scoring was deleted). Assets table layout: Type and Ccy are one column, Last buy / Last sell columns were removed, and below 1360 px the Bought / Sold columns hide (CSS nth-child 7 and 8 of `#asset-table`; keep them at those positions if columns change); it fits at 1100-1440 px with 13 px text. Known gap: the Assets table "Value kr" column still shows the export snapshot (KPI row and Portfolio page are live).

## Live headline values
Portfolio page and Analytics KPI "Account value / All-time result / Unrealised" are rescaled by live Yahoo price vs export price (same-currency, 0.5-2x guard, funds keep export). Export values are only a snapshot from the day it was made.
- Let the user override asset type/country (`asset_overrides.json`).

## Privacy toggle
Eye button (`#privacy-btn`) in the header of BOTH pages -> `privacy.js` + `privacy.css`: adds `html.privacy`, which blurs the Portfolio summary cards and the Analytics KPI row (labels stay). State in localStorage `tv_privacy`, shared between pages/tabs. Visual only (numbers stay in the DOM). `privacy.js` also auto-masks: table columns whose header is kr/SEK/Value/Return/Realised/Unrealised/Total/Net/Qty/Units/Position after (cells get class `pv`), `... kr` amounts inside sentences in cards/notes (MutationObserver, so re-renders are covered), and kr chart axes/tooltips (Chart.js plugin `tvPrivacy`, detects money callbacks by `fmt(`/`kr` in their source; it edits raw `chart.config.options`, never the resolved proxy). privacy.js must load AFTER the Chart.js script. Anything else private: wrap in `<span class="pv">`. Not covered: percentages, prices per share, chart shapes.

## Server launchers
`start-dashboard.bat` (runs `nordnet_sync.py` ONCE to rebuild portfolio_baseline.json from the 2 newest exports, then the auto-restart server loop; the user drops ALL CSVs into the project folder by hand - no Downloads watching, no `--watch`), `stop-dashboard.bat`, `install-autostart.bat` / `uninstall-autostart.bat` (optional login start via the Startup folder). Server still listens on all interfaces on purpose (Tailscale).

## Conventions
- Keep Portfolio page untouched except bug fixes; new work goes in the analytics files.
- Match existing style (compact, comments only for non-obvious "why"). Charts: categorical colours `--s1..--s8` fixed order, green/red only for gain/loss, no dual-axis charts, tooltips on every chart.
- Test with headless Chrome (puppeteer-core in a scratchpad dir, never in the project) after UI changes.
- At the end of a session: update this file's "Current results / Ideas", commit, push to `TestTrading`.
