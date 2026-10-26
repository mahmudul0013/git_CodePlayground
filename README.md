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

- **Analytics page** (`/analytics.html`): asset explorer (all ever held / current / closed / bought or sold in the last 1 week or 1 month, with type, currency and country filters and charts) plus a trading-habits and broker-cost report. It is built from `transactions-and-notes-export*.csv` and `Innehav*Export*.csv` in the project folder; the newest matching file wins and the page re-syncs by itself when a file changes.

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
2. Put the file in the project folder (or let the watcher copy it from Downloads):

```powershell
python nordnet_sync.py            # rebuild portfolio_baseline.json from the 2 newest exports in the folder
python nordnet_sync.py --watch    # keep running, auto-copy new exports from Downloads
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

### 4. Open the dashboard

Go to **http://localhost:8000** in your browser. Click **Refresh Portfolio** in the header to reload the CSVs and prices immediately.

### 5. Stop the server

Press `Ctrl + C` in the terminal. If it is running in the background:

```powershell
taskkill /IM python.exe /F
```

This kills every Python process, so close other Python programs first.

## Typical daily workflow

1. Export new CSVs from Nordnet.
2. Run `python nordnet_sync.py` (or leave `--watch` running in a second terminal).
3. Run `python server.py` and open http://localhost:8000.

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
| Dashboard shows old holdings | Drop the new `Innehav ... Export` file in the folder (or run `nordnet_sync.py --watch`) and click **Refresh Portfolio**. Restart `server.py` once if you updated from an older version (it needs the `/api/holdings` route). |

Yahoo symbol suffixes: `.ST` Sweden, `.OL` Norway, `.HE` Finland, `.CO` Denmark, `.L` London, `.DE` Germany, `.PA` Paris. US stocks use the plain ticker.

## Project structure

```
testTrading/
├── index.html               Dashboard UI
├── style.css                TradingView dark theme styles
├── app.js                   Dashboard logic (data, live prices, signals)
├── server.py                Local HTTP server + Yahoo Finance proxy
├── nordnet_sync.py          Nordnet export sync (baseline, watch, API)
├── Innehav Tabell Export, accno N, DATE.csv   Holdings export (newest one is used)
├── portfolio_baseline.json  Previous-state snapshot for last-buy tracking
├── WishList.md              Feature requirements
├── DesignGuide.md           Visual design spec
└── .claude/skill.md         Detailed project design knowledge
```

## Further reading

- [WishList.md](WishList.md): feature requirements and implemented phases
- [DesignGuide.md](DesignGuide.md): colors, typography and component specs
- [.claude/skill.md](.claude/skill.md): architecture, last-buy logic, signal model and ticker map
