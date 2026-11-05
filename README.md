# Trading Dashboard

A personal, browser-based portfolio dashboard inspired by TradingView's dark theme. It tracks a Nordnet brokerage account (Swedish and US holdings) using plain HTML, CSS and vanilla JS. A small Python server serves the files and proxies Yahoo Finance for live prices.

## Features

- Portfolio summary: total value, day P&L, total return, SEK/USD allocation
- Stocks and funds tables with SEK/USD filters, sorting, search and sparklines
- Scrolling market ticker (OMXS30, DAX, S&P futures, Gold, USD/SEK, EUR/USD)
- Watchlist sidebar and SEK/USD currency toggle
- Last-buy tracking: new shares and buy price shown in gold under Qty and Price
- Tomorrow's Signals: top 5 buy and top 5 sell from an 8-factor technical model
- Live price refresh every 60 s; portfolio CSV reload every 5 min
- **One continuous Portfolio page**: summary, signals, stocks, funds, then the **Heat map** (the nav buttons *Portfolio* / *Heat map* just scroll)
- **Portfolio heat map**: treemap of the current holdings, size = market value, colour = today's change or unrealised return, grouped by Yahoo Finance sector (or type / country), with distribution doughnut, breakdown table and concentration notes. It syncs by itself: a new or changed Nordnet CSV is picked up within 10 s and live Yahoo prices refresh every 30 s
- **Add / Trim ideas** (Portfolio page, Analytics → Advice, and the *Add / trim* column of the Assets table): rule-based position management from position size, Yahoo sector concentration, tiny positions and trend health (50/200-day averages, 12-1 month momentum, pullback). It is not a price forecast; the Advice tab shows the back-test that led to dropping the old next-day signals. Price history is cached in `history_cache.json`
- **Privacy toggle** (eye button in the header of both pages): blurs summary rows, headline numbers, money/size table columns, "... kr" amounts in text and kr chart axes/tooltips. Remembered between pages and reloads (visual masking only)

- **Analytics page** (`/analytics.html`), three tabs:
  - **Assets**: asset explorer (all ever held / current / closed / bought or sold in the last 1 week or 1 month, with type, currency and country filters and charts)
  - **Trading habits & costs**: habit score, broker costs, benchmark against OMXS30 / S&P 500 / Nasdaq 100 futures, good-practice tips, fee and holding-time analysis
  - **Deposit behaviour**: deposits per day / week / month as columns, estimated portfolio value (or deposit-free return) and positions held as lines on one shared axis, optional index overlays (OMXS30, S&P 500, Nasdaq 100 futures `NQ=F`), insight cards (return vs market, risk, idle cash, deposit timing, why you are ahead or behind the index, money per position)

  It is built from `transactions-and-notes-export*.csv` and `Innehav*Export*.csv` in the project folder; the newest matching file wins and the page re-syncs by itself when a file changes.

## Requirements

- Python 3.8 or newer (standard library only, no `pip install` needed)
- A modern browser
- Internet access (Yahoo Finance, Chart.js CDN, Clearbit logos)

## Running the project

### 1. Open the project folder

```powershell
cd "c:\Users\Administrator\Documents\Agentic World\testTrading"
```

### 2. Get your holdings data (Nordnet CSVs)

Nordnet now exports **all holdings (stocks, ETFs and funds) in one file**, named like `Innehav Tabell Export, accno 66262387, YYYY-MM-DD.csv`. Both the Portfolio page and the Analytics page use only the **newest** such file in the project folder (the date in the file name wins, file modified time breaks ties). Older exports are ignored for all calculations; the second-newest one is only used as the "previous state" for last-buy tracking.

1. Log in at nordnet.se and export your holdings table (**Innehav → Exportera**).
2. Drop the file (and the ledger `transactions-and-notes-export.csv`) into the project folder by hand, then refresh the last-buy baseline (`start-dashboard.bat` does this at every start):

```powershell
python nordnet_sync.py            # rebuild portfolio_baseline.json from the 2 newest exports in the folder
python nordnet_sync.py --watch    # optional, not used by start-dashboard.bat: auto-copy new exports from Downloads
python nordnet_sync.py --api      # fetch live from the Nordnet API (needs .env, see below)
```

The export has no instrument type, so the Portfolio page puts Nordnet mutual funds (names containing index/indeks/allemansfond/AuAg...) in the **Funds** table and everything else (stocks, ETFs, ETCs) in **Stocks**. The rule is `isFundName()` in `app.js`, matching `classify_type()` in `trade_analytics.py`.

Skip this step if an `Innehav ... Export` file already exists and is current.

### 3. Start the server

```powershell
python server.py                  # http://localhost:8000
python server.py --port 9000      # custom port
```

Use `server.py`, not `python -m http.server`. Only `server.py` includes the `/yahoo/*` proxy that live prices and the ticker bar depend on.

### 3b. Run it without VS Code (Windows)

Double-click **`start-dashboard.bat`**. It first runs `nordnet_sync.py` once (rebuilds `portfolio_baseline.json`, the previous-state snapshot behind the gold last-buy tags, from the two newest `Innehav…` exports in the folder), then starts `server.py` in its own window (minimised is fine) and restarts it automatically if it ever stops. You drop all Nordnet CSVs (holdings exports and the ledger) into the project folder by hand; nothing is copied from Downloads. The dashboard, Analytics and heat map pick up a new CSV by themselves; to refresh the last-buy baseline after dropping a new holdings export, run `python nordnet_sync.py` or restart `start-dashboard.bat`. Close that window, or double-click **`stop-dashboard.bat`**, to stop the server (it only touches this project's processes).

Optional: **`install-autostart.bat`** makes the server start by itself, minimised, at every Windows login (puts a launcher in your Startup folder, no admin rights needed); **`uninstall-autostart.bat`** removes it. Stop any server you started from VS Code first, otherwise port 8000 is taken.

The server listens on **all network interfaces** on purpose (so you can open it through Tailscale from another device). Anyone who can reach port 8000 can read the dashboard, so only expose it on networks you trust.

### 4. Open the dashboard

Go to **http://localhost:8000** in your browser (Analytics: **/analytics.html**). Click **Refresh Portfolio** in the header to reload the CSVs and prices immediately.

### 5. Stop the server

Press `Ctrl + C` in the terminal. If it is running in the background:

```powershell
taskkill /IM python.exe /F
```

This kills every Python process, so close other Python programs first.

## Typical daily workflow

1. Export new CSVs from Nordnet and drop them into the project folder.
2. Run `python nordnet_sync.py` once to refresh the last-buy baseline (or just restart `start-dashboard.bat`, which runs it before starting the server).
3. Open http://localhost:8000. The server only needs to be running; the pages pick up the new CSVs by themselves.

## Nordnet API mode (optional)

1. Log in to nordnet.se with BankID.
2. Open DevTools → Network, filter for `api/2`, click a request and copy the `SESSION` cookie value.
3. Create a `.env` file in the project root:

   ```
   NORDNET_SESSION_TOKEN=<paste here>
   NORDNET_ACCOUNT=66262387
   ```

4. Run `python nordnet_sync.py --api`.

The session token expires, so repeat these steps when it does.

## Troubleshooting

| Problem | Fix |
|---|---|
| Live prices or ticker bar are empty | You are not using `server.py`. Stop any other server and run `python server.py`. |
| Port already in use | Run `python server.py --port 9000`, or stop the old process with `taskkill /IM python.exe /F`. |
| A stock shows `—` for price | Add its name to `TICKER_MAP` in `app.js` with the Yahoo Finance symbol. |
| Last-buy tags missing or stale | Run `python nordnet_sync.py` after a new export (needs at least two `Innehav` files in the folder) so `portfolio_baseline.json` is refreshed. |
| Heat map "Today" differs from Yahoo or Nordnet | Live day change comes from Yahoo daily bars (last close before the current session). Nordnet funds (`0P...` symbols) keep the export values. A same-currency quote priced 2x off the export is ignored as a wrong symbol. |
| A holding is "Unclassified" or shows no live price | Add or fix its Yahoo symbol in `symbol_cache.json` (set `"source": "manual"`) and in `TICKER_MAP` in `app.js`. ETFs and funds have no Yahoo sector, so they are grouped as ETFs / Funds. |
| Dashboard shows old holdings | Drop the new `Innehav ... Export` file in the folder and click **Refresh Portfolio**. Restart `server.py` once if you updated from an older version (it needs the `/api/holdings` route). |

Yahoo symbol suffixes: `.ST` Sweden, `.OL` Norway, `.HE` Finland, `.CO` Denmark, `.L` London, `.DE` Germany, `.PA` Paris. US stocks use the plain ticker.

## Project structure

```
testTrading/
├── index.html               Portfolio page (summary, tables, heat map section)
├── style.css                TradingView dark theme styles
├── app.js                   Portfolio logic (data, live prices, signals, nav scroll)
├── heatmap.js / heatmap.css Portfolio heat map (treemap, doughnut, live sync)
├── analytics.html/css/js    Analytics page (Assets, Trading habits, Deposit behaviour)
├── asset_chart.js           Per-asset price chart with BUY/SELL markers
├── privacy.js / privacy.css Master privacy toggle (eye button)
├── server.py                Local HTTP server + Yahoo proxy + JSON API (see below)
├── trade_analytics.py       Ledger + holdings -> positions, trades, insights, deposit behaviour
├── benchmark.py             Index comparison and overlay series (OMXS30, S&P 500, NQ=F)
├── symbols.py / symbol_cache.json   ISIN -> Yahoo symbol (hand edits kept)
├── sectors.py / sector_cache.json   Sector / fund category per holding from Yahoo
├── nordnet_sync.py          Nordnet export sync (baseline, watch, API)
├── start-dashboard.bat      Run nordnet_sync.py once, then the server without VS Code (auto-restart)
├── stop-dashboard.bat       Stop it
├── install-autostart.bat / uninstall-autostart.bat   Optional start at Windows login
├── transactions-and-notes-export.csv   Full ledger (newest used)
├── Innehav Tabell Export, accno N, DATE.csv   Holdings export (newest one is used)
├── portfolio_baseline.json  Previous-state snapshot for last-buy tracking
├── WishList.md              Feature requirements
├── DesignGuide.md           Visual design spec
└── .claude/skill.md         Detailed project design knowledge
```

## Server API

| Route | Purpose |
|---|---|
| `/api/holdings` | Newest holdings CSV (Portfolio page) |
| `/api/trades`, `/api/trades/status` | Full analytics payload; file signature used for auto-sync |
| `/api/assets` | Assets only (used by the heat map) |
| `/api/live` | Live Yahoo quotes for current holdings (25 s cache) |
| `/api/sectors` | Yahoo sector / fund category per holding (30-day cache) |
| `/api/benchmark`, `/api/overlay` | Index comparison and daily index curves |
| `/api/symbol` | ISIN / name -> Yahoo symbol |
| `/yahoo/*` | Yahoo Finance proxy |

Memory: every server cache holds one entry that is replaced, not grown (measured about 40 MB after loading every endpoint, flat over hundreds of polls).

## Further reading

- [WishList.md](WishList.md): feature requirements and implemented phases
- [DesignGuide.md](DesignGuide.md): colors, typography and component specs
- [.claude/skill.md](.claude/skill.md): architecture, last-buy logic, signal model and ticker map
- [.claude/skills/trading-analytics/SKILL.md](.claude/skills/trading-analytics/SKILL.md): analytics, heat map, live-price and privacy notes
