# Trading Dashboard — Project Design Knowledge

## Project Overview

A personal, browser-based portfolio dashboard inspired by TradingView.
Tracks a Nordnet brokerage account (account `66262387`) with Swedish and US holdings.
No frameworks — plain HTML + CSS + Vanilla JS, served locally via Python.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| UI | Plain HTML + CSS + Vanilla JS | No build step, fast |
| Charts | Chart.js (CDN) | Sparklines + pie chart |
| Data (holdings) | CSV files from Nordnet | Auto-synced via `nordnet_sync.py` |
| Live Prices | Yahoo Finance v8 chart API | Free, no API key |
| Server | `server.py` (Python) | File server + Yahoo Finance proxy |

---

## File Structure

```
/testTrading/
├── index.html            ← Dashboard UI
├── style.css             ← TradingView dark theme styles
├── app.js                ← All dashboard logic (data, live prices, signals)
├── server.py             ← Local HTTP server + Yahoo Finance CORS proxy
├── nordnet_sync.py       ← Nordnet CSV sync (watch/API mode)
├── portfolio_stocks.csv  ← Active stocks holdings (auto-generated)
├── portfolio_funds.csv   ← Active funds holdings (auto-generated)
├── portfolio_baseline.json ← Last-buy snapshot (persisted to disk)
├── WishList.md           ← Feature requirements
├── DesignGuide.md        ← Visual design spec
└── .claude/
    └── skill.md          ← This file
```

---

## Design System (TradingView Dark Theme)

### Color Palette

| Token | Hex | Usage |
|---|---|---|
| Background | `#131722` | Main page background |
| Surface | `#1E2130` | Cards, panels, tables |
| Border | `#2A2E39` | Dividers, table borders |
| Text Primary | `#D1D4DC` | Main text |
| Text Secondary | `#787B86` | Labels, secondary info |
| Accent Blue | `#2962FF` | Links, buttons, highlights |
| Green | `#26A69A` | Positive returns, up arrows |
| Red | `#EF5350` | Negative returns, down arrows |
| Gold | `#F7C948` | Last-buy tags, watchlist star |
| White | `#FFFFFF` | Active/selected text |

### Typography
- Font: `'Inter'`, `'Trebuchet MS'`, sans-serif
- Base: 13px (compact, data-dense)
- Headings: 16–22px, weight 600
- Ticker bar: 12px, monospace

### Layout
```
┌──────────────────────────────────────────────────────────┐
│  TICKER BAR (top, full-width, scrolling)                 │
├──────────┬───────────────────────────────────────────────┤
│          │  HEADER: Logo + Nav Tabs + Currency Toggle    │
│ SIDE     ├───────────────────────────────────────────────┤
│ WATCH-   │  SUMMARY CARDS ROW                            │
│ LIST     │  [Total Value] [Day P&L] [Return] [FX]        │
│          ├───────────────────────────────────────────────┤
│          │  STOCKS TABLE (currency tabs)                 │
│          │  ─────────────────────────────               │
│          │  FUNDS TABLE                                  │
│          ├───────────────────────────────────────────────┤
│          │  TOMORROW'S SIGNALS WIDGET (Top 5 Buy/Sell)   │
└──────────┴───────────────────────────────────────────────┘
```

---

## Component Specs

### Ticker Bar
- Fixed top, `#0F1117` background
- CSS marquee animation
- Format: `NAME ▲+1.20% VALUE`
- Symbols: `^OMX`, `^GDAXI`, `ES=F`, `GC=F`, `USDSEK=X`, `EURUSD=X`

### Summary Cards
- Surface `#1E2130`, rounded `8px`, border `1px solid #2A2E39`
- Large bold white value, small gray label below

### Holdings Tables (Stocks + Funds)
- Columns: Logo | Name | Ticker | Currency | Qty | GAV | Last Price | Today% | Value | Value SEK | Return% | Return SEK
- Header: `#2A2E39` bg, `#787B86` text, uppercase
- Alternating rows: `#131722` / `#1A1D2E`
- Hover: `#2A2E39`
- Return % is color-coded green/red
- Sticky header on scroll
- Filter tabs: All | SEK (EU) | USD (US)

### Last-Buy Tags (`.lb-tag`)
- Gold `#F7C948`, 10px, shown below main value in Qty and Price columns
- Qty column: `5 (+2)` — shows new shares added
- Price column: `252.00 (248.50)` — shows implied buy price

### Company Logos
- Source: Clearbit API `logo.clearbit.com/{domain}`
- Fallback: colored initials avatar

### Sparklines
- Library: Chart.js (mini, inline per table row)
- Green line = positive return, Red = negative
- Limited to 25 per load (`CFG.sparkLimit`)

---

## Source of Truth

**The latest CSV is always the source of truth for the stock list and quantities.**
`portfolio_stocks.csv` and `portfolio_funds.csv` are the files the dashboard reads.
They are always the latest Nordnet export, maintained by `nordnet_sync.py`.

## Data Flow

```
Nordnet Website
  → Export CSV  (aktier_kontonummer-{account}_YYYY-MM-DD.csv)
                (fonder_kontonummer-{account}_YYYY-MM-DD.csv)
  → nordnet_sync.py
      (default) → saves 2nd-newest as portfolio_baseline.json
                → promotes newest to portfolio_stocks.csv / portfolio_funds.csv
      --watch   → monitors ~/Downloads, auto-copies on new export
      --api     → Nordnet REST API (session token) → same fixed files

portfolio_stocks.csv / portfolio_funds.csv   ← source of truth
  → app.js loadCSVWithFallback()
      → detectAndSaveBuys()   → localStorage + portfolio_baseline.json
      → Yahoo Finance proxy   → live prices (60s refresh)
      → CSV auto-reload       → every 5 minutes (csvRefreshMs)
```

---

## Yahoo Finance Integration

- **Proxy**: `server.py` intercepts `/yahoo/*` and forwards to `query1.finance.yahoo.com`
- **Auth bypass**: v7 quote batch API requires crumb/cookie; `server.py` translates v7 → v8 chart API (no auth needed) and reassembles v7 response format
- **Fallback**: `query2.finance.yahoo.com` if `query1` fails
- **Config in app.js**:
  - `CFG.yahooBase = IS_LOCAL ? '/yahoo' : 'https://query1.finance.yahoo.com'`
  - `CFG.refreshMs = 60_000` (live price refresh)
  - `CFG.csvRefreshMs = 300_000` (portfolio CSV re-check)

---

## Last-Buy Tracking Logic

The baseline (`portfolio_baseline.json`) stores the PREVIOUS portfolio state.
The app compares the current CSV against this baseline to detect changes.

### Detection rules (in `detectAndSaveBuys()`)
| Situation | Action |
|---|---|
| Fresh baseline (`__ts` > localStorage ts) | Reset `S.lastBuy = {}` so detection starts clean |
| Brand-new position (not in baseline, baseline non-empty) | Set `lastBuy` with full qty + GAV as buy price |
| Qty increased | Set `lastBuy` with added qty + derived buy price |
| Qty decreased (partial sale) | **Delete** `lastBuy` entry — stale annotation cleared |
| Qty unchanged | Preserve existing `lastBuy` (previous buy still shown) |
| Position no longer exists (sold) | **Delete** `lastBuy` entry |

### Key mechanism: `__ts`
`portfolio_baseline.json` carries a `__ts` (Unix ms) timestamp written by `nordnet_sync.py`.
`loadLastBuyData()` compares this against `portfolio_snapshot_ts` in localStorage.
If `baselineTs > localTs` → the sync produced a fresh baseline → app resets `S.lastBuy`
and seeds `S._snapshot` from the baseline, so the next `detectAndSaveBuys()` reflects
the true diff from the previous export to the current one.

### Display
- Gold `.lb-tag` below the main value in Qty and Price columns
- Qty: `4 (+1)` — current total with added shares in gold
- Price: `200.04 (188.50)` — live price with implied buy price in gold

---

## Tomorrow's Signals Widget (Top 5 Buy / Top 5 Sell)

Ranks all portfolio holdings by composite technical signal score.
Data: Yahoo Finance v8 chart API — ~60 trading days OHLCV, 3mo range.
Requests staggered 200ms apart to avoid rate limiting.

### 8-Factor Scoring Model (max score ≈ ±15)

| Factor | Weight | Bullish Logic | Bearish Logic |
|---|---|---|---|
| MACD (12,26,9) | ±3 | Crossover above signal | Crossover below signal |
| RSI 14 (Wilder) | ±2 | < 30 oversold | > 70 overbought |
| Bollinger Bands (20, 2σ) | ±2 | Price ≤ lower band | Price ≥ upper band |
| Stochastic %K 14 | ±2 | < 20 oversold | > 80 overbought |
| SMA5 vs SMA20 crossover | ±2.5 | Golden cross | Death cross |
| Volume confirmation | ±1.5 | High vol on up day | High vol on down day |
| Pivot Points (classic) | ±1 | Near S1/S2 support | Near R1/R2 resistance |
| Rate of Change 5-day | ±1 | > +3% momentum | < −3% downswing |

**Confidence%** = `|score| / 15 × 100`, capped at 92%

**Labels:**
- Score ≥ 7 → Strong Buy / Strong Sell
- Score ≥ 4 → Buy / Sell
- Score < 4 → Weak Buy / Weak Sell

---

## Nordnet Sync — nordnet_sync.py

```bash
python nordnet_sync.py            # copy newest existing CSVs from project folder
python nordnet_sync.py --watch    # monitor Downloads, auto-copy on new export
python nordnet_sync.py --api      # live fetch via Nordnet REST API
```

### API Mode Setup
1. Login to `nordnet.se` via BankID
2. DevTools → Network → filter `api/2` → copy `SESSION` cookie
3. Create `.env`:
   ```
   NORDNET_SESSION_TOKEN=<paste here>
   NORDNET_ACCOUNT=66262387
   ```
4. Run `python nordnet_sync.py --api`

---

## Server Commands

```bash
# Start dashboard
python server.py              # http://localhost:8000
python server.py --port 9000  # custom port

# Stop server
taskkill /IM python.exe /F
```

---

## Ticker Symbol Map (Yahoo Finance)

`TICKER_MAP` in `app.js` maps CSV stock names → Yahoo Finance ticker symbols.
**This map must be updated manually when new stocks appear in the CSV.**
Stocks without a TICKER_MAP entry show `—` for live price (graceful degradation).

Exchange suffix conventions:
- Swedish stocks → `.ST` (e.g. `ABB.ST`, `SAAB-B.ST`)
- Norwegian stocks → `.OL` (e.g. `KOG.OL`)
- Finnish stocks → `.HE` (e.g. `NOKIA.HE`)
- Danish stocks → `.CO` (e.g. `NOVO-B.CO`)
- London ETFs → `.L` (e.g. `EIMI.L`)
- German stocks/ETFs → `.DE` (e.g. `SIE.DE`, `IFX.DE`)
- Paris-listed → `.PA` (e.g. `SU.PA`, `STM.PA`)
- US stocks → plain ticker (e.g. `NVDA`, `AAPL`, `ARM`)
- SpaceX → no public ticker (private company)

---

## Planned / Backlog Features

- Candlestick chart on row click (mini modal)
- Export portfolio to PDF
- Allocation heatmap
- News feed widget per stock
- Target price / alerts
- Strategy update for "Top 5" signal model based on market conditions
