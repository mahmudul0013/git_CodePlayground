# Trading Dashboard — Wishlist & Feature Requirements

## Overview
A personal, browser-based trading dashboard inspired by TradingView.
Shows all holdings (stocks & funds) categorized by currency domain: SEK (EU) and USD (US).

---

## Core Features

### 1. Portfolio Overview Panel
- Total portfolio value in SEK and USD
- Daily P&L (today's return in % and absolute value)
- Total return (all-time) in % and SEK
- Currency breakdown widget: EU (SEK) vs US (USD) allocation pie chart

### 2. Holdings Table — Stocks
Columns:
- Logo / Icon
- Name
- Ticker
- Currency (SEK / USD)
- Quantity (Number of shares)
- Average Buy Price (GAVE)
- Latest Price
- Today's Change %
- Total Value (in native currency)
- Total Value in SEK
- Return % (all-time)
- Return in SEK

Filters:
- Filter by Currency: All | SEK (EU) | USD (US)
- Sort by any column
- Search by name or ticker

### 3. Holdings Table — Funds
Same columns as stocks table but labeled separately.
Funds section below stocks section.

### 4. Market Ticker Bar (Top)
- Live-style scrolling ticker showing: OMXS30, DAX, SP500, Gold, USD/SEK
- Color coded: green for up, red for down

### 5. Watchlist Sidebar *(replaced in 2026-11 by the Reports Calendar sidebar: earnings and ex-dividend dates of the holdings, Today / Tomorrow / This week)*
- Add/remove stocks manually
- Shows current price and daily change %

### 6. Mini Sparkline Charts
- Small 7-day price trend chart for each holding in the table

### 7. Currency Toggle
- Switch entire dashboard view between SEK and USD equivalent values

### 8. Dark Mode (default, TradingView-style)
- Dark background with high-contrast text and colored indicators

### 9. Data Source
- CSV files for holdings data (stocks.csv and funds.csv)
- Prices fetched from a free API (Yahoo Finance via yfinance proxy or Alpha Vantage free tier)

### 10. Responsive Layout
- Desktop first, but usable on tablet

## 11. Real time market visualization
- use this site to see the real time stock market data https://finance.yahoo.com/


---

## Nice-to-Have (Phase 2)
- Candlestick chart on row click (mini modal)
- Export portfolio to PDF
- Allocation heatmap *(done: Portfolio page, see below)*
- News feed widget per stock
- Target price / alerts

## Phase 3 — Implemented Features (2026-03-30)

### Nordnet Portfolio Sync (`nordnet_sync.py`)
- **Manual drop (current workflow)**: export `Innehav Tabell Export, accno N, DATE.csv` (stocks, ETFs and funds in one file)
  and `transactions-and-notes-export.csv` from Nordnet and put them in the project folder. The server always uses the newest of each.
- **One-shot baseline**: `start-dashboard.bat` runs `python nordnet_sync.py` once, which builds `portfolio_baseline.json`
  (previous state for last-buy tracking) from the second-newest `Innehav` export.
- *(Not used any more: `--watch` auto-copy from Downloads was dropped on purpose; `--api` mode with a session token still exists but is optional.)*

### Auto Portfolio Reload
- Dashboard re-reads CSVs every **5 minutes** automatically (no browser refresh needed).
- **Refresh Portfolio** button in the header triggers an immediate reload + price update.
- Always reads the single newest `Innehav ... Export` file (served by `server.py` at `/api/holdings`).

### Last Buy Tracking
- After each CSV reload the dashboard compares the new holdings against the previous
  snapshot stored in `localStorage`.
- If the quantity of any position increased, the number of new shares and the implied
  buy price are calculated from the shift in weighted-average price:
  `buyPrice = (newQty × newGAV − oldQty × oldGAV) / addedShares`
- The result is shown **inline** in the Qty and Price columns in gold text:
  - Qty column: `5 (+2)` — current total with new shares in brackets
  - Price column: `252.00 (248.50)` — current price with last-buy price in brackets
- Data persists across page loads (stored in `localStorage['portfolio_lastbuy']`).

---

## Phase 2 — Implemented Features

### Add / Trim Ideas (replaced "Tomorrow's Signals")
The old 8-indicator next-day score was back-tested on 77 holdings over 5 years (~70 000 samples) and had no predictive power, so it was removed.
Ideas now come from `advisor.py` (`/api/advice`): TRIM (position over 4% or sector over 40%), ADD (under-weight, uptrend, pulled back),
BUY BACK (the same test on closed positions), CONSOLIDATE (under 1 500 kr) and REVIEW (downtrend and over 15% under cost).
Three entry profiles (Conservative / Balanced / Aggressive). Shown on the Portfolio page, in the Assets table (*Add / trim* column) and in Analytics → Advice.

---

## Phase 4 — Implemented Features (2026-10 / 11)

- **Portfolio heat map** (Portfolio page, below the tables): Yahoo sectors, live prices, auto-sync with the CSV.
- **Analytics page** (Assets, Trading habits & costs, Deposit behaviour, Dividends, Advice) built from the ledger and the holdings export,
  with index overlays (OMXS30, S&P 500, Nasdaq 100 futures).
- **Live headline values**: Portfolio and Analytics totals are rescaled by live Yahoo prices (the export is only a snapshot).
- **Privacy toggle** (eye button) hides money values on both pages.
- **Run without VS Code**: `start-dashboard.bat` / `stop-dashboard.bat` (optional autostart); threaded server for several browsers; reachable over LAN / Tailscale.

## Phase 5 - Multi-user (2026-11)
- Accounts with login (username + password), single-use invite codes from the admin, one private profile per user (own two Nordnet CSVs uploaded in the browser, account number checked inside the files), all on port 8000.
- Local rule-based chat and search, tile help icons, fluid layout for phones, tablets and desktops.

## Ideas not done yet
- Optional HTTPS mode; several Nordnet accounts per profile; encryption at rest; Swedish answers in the assistant; follow-up context in the chat.
- Exact portfolio value history from Yahoo closes per holding (the current history is an estimate).
- Assets table "Value kr" column rescaled by live prices.
- Look-through sector exposure of ETFs and funds.
- Tax (ISK) view; dividend forecast.
