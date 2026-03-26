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

### 5. Watchlist Sidebar
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
- Allocation heatmap
- News feed widget per stock
- Target price / alerts

## Phase 2 — Implemented Features

### Tomorrow's Signals Widget
Displays Top 5 stocks with the strongest bullish setup and Top 5 with the
strongest bearish setup from your portfolio, ranked by composite signal score.

**8-factor technical model (scored independently, then summed):**

| Factor | Max Weight | Signal Logic |
|---|---|---|
| MACD (12,26,9) | ±3 | Crossover = strongest signal; trend confirmation = ±1–2 |
| RSI (14-period, Wilder) | ±2 | <30 oversold bullish; >70 overbought bearish |
| Bollinger Bands (20, 2σ) | ±2 | Price at/below lower band = buy; at/above upper = sell |
| Stochastic %K (14-period) | ±2 | <20 oversold; >80 overbought |
| SMA5 vs SMA20 crossover | ±2.5 | Golden cross = +2.5; death cross = −2.5; trend = ±1 |
| Volume confirmation | ±1.5 | High vol on up/down day validates the move |
| Classic Pivot Points | ±1 | Price near S1/S2 support = bullish; near R1/R2 = bearish |
| Rate of Change (5-day) | ±1 | >3% strong momentum; <−3% strong downswing |

**Total max score ≈ ±15.**
Confidence% = |score| / 15 × 100, capped at 92%.

**Labels:** Strong Buy/Sell (score ≥ 7) · Buy/Sell (≥ 4) · Weak Buy/Sell (< 4)

**Data source:** Yahoo Finance v8 chart API (~60 trading days OHLCV, 3mo range)
Fetched automatically in background after page load (200ms gap between requests).

