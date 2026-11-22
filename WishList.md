# Trading Dashboard — Wishlist & Feature Requirements

## Overview
A personal, browser-based trading dashboard inspired by TradingView.
Shows all holdings (stocks & funds) categorized by currency domain: SEK (EU) and USD (US).

---

## Core Features

### 1. Portfolio Overview Panel
- Account value (holdings + cash) in SEK and USD
- Daily P&L (today's return in % and absolute value)
- All-time result (account value minus deposits) in % and SEK, with the unrealised part
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

### 6. Volatility instead of sparklines *(replaced in 2026-11)*
- The 7-day sparkline column did not add information; the table now has a **Vol 3M** column (daily volatility over the last 3 months)

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

### Portfolio plan: one strategy per category (replaced Add / Trim Ideas and "Tomorrow's Signals")
The old 8-indicator next-day score had no predictive power and the RSI take-profit was dropped (RSI above 75 was followed by more gains).
`strategy.py` puts every holding in a category with a target share and its own rule, chosen from a 10-year test of the user's own holdings
(`strategy_bt.py`): index funds buy and hold with monthly saving; AI and semiconductor chain half held + half on the weekly SMA(200) rule;
quality groups buy and hold with new money only on pullbacks in an uptrend; industrials half + weekly SMA(200); energy and materials SMA(50) > SMA(200);
gold / bonds and opportunity cash at fixed weights. `advisor.py` turns it into ADD / BUY BACK / WATCH / TRIM / CONSOLIDATE / REVIEW per holding,
a deposit plan, sales due this month, the transition, a stress test and the fit to five popular strategies. Shown in Analytics → Plan & advice,
on the Portfolio page (Buy / Sell this month, Trend Signals sidebar) and in the Assets table (*Add / trim* column). Plan settings per user.
Verified against SMA(50), EMA(100) (daily and weekly), half + EMA(100) and an EMA(100) new-money warning: none beat the current rules in both 2017-2022 and 2023-2026.

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

- **Net asset value growth curve** (Portfolio page): ranges 1W-Max, value or time-weighted growth, per Yahoo-sector curves in one chart.

## Ideas not done yet
- Benchmark line (OMXS30 / S&P 500) on the growth curve; ISK / currency-split views of the curve.
- Optional HTTPS mode; several Nordnet accounts per profile; encryption at rest; Swedish answers in the assistant; follow-up context in the chat.
- Exact portfolio value history from Yahoo closes per holding (the current history is an estimate).
- Assets table "Value kr" column rescaled by live prices.
- Look-through sector exposure of ETFs and funds.
- Tax (ISK) view; dividend forecast.
