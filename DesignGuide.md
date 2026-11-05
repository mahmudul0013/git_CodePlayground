# Trading Dashboard — Design Guide

## Inspiration
TradingView.com — professional dark-themed trading interface.

---

## Color Palette

| Token          | Hex       | Usage                        |
|----------------|-----------|------------------------------|
| Background     | #131722   | Main page background         |
| Surface        | #1E2130   | Cards, panels, tables        |
| Border         | #2A2E39   | Dividers, table borders      |
| Text Primary   | #D1D4DC   | Main text                    |
| Text Secondary | #787B86   | Labels, secondary info       |
| Accent Blue    | #2962FF   | Links, buttons, highlights   |
| Green          | #26A69A   | Positive returns, up arrows  |
| Red            | #EF5350   | Negative returns, down arrows|
| Gold/Yellow    | #F7C948   | Watchlist star, alerts       |
| White          | #FFFFFF   | Active/selected text         |

---

## Typography

- **Font Family**: `'Inter'`, `'Trebuchet MS'`, sans-serif
- **Base size**: 13px (compact, data-dense like TradingView)
- **Headings**: 16px–22px, weight 600
- **Table cells**: 13px, weight 400–500
- **Ticker bar**: 12px, monospace feel

---

## Layout
```
┌─────────────────────────────────────────────────────────┐
│  TICKER BAR (top, full-width, scrolling)                │
├──────────┬──────────────────────────────────────────────┤
│          │  HEADER: Logo + Nav Tabs + Currency Toggle   │
│ SIDE     ├──────────────────────────────────────────────┤
│ WATCH-   │  SUMMARY CARDS ROW                           │
│ LIST     │  [Total Value] [Day P&L] [Total Return] [FX] │
│          ├──────────────────────────────────────────────┤
│          │  STOCKS TABLE (SEK | USD tabs)               │
│          │  ─────────────────────────────               │
│          │  FUNDS TABLE                                 │
│          │  ─────────────────────────────               │
│          │  HEAT MAP (same page, below the tables)      │
└──────────┴──────────────────────────────────────────────┘
```

---

## Component Specs

### Ticker Bar
- Fixed top, black background `#0F1117`
- Scrolling marquee animation (CSS)
- Each item: `NAME ▲+1.20% VALUE`

### Summary Cards
- Dark surface `#1E2130`
- Rounded corners `8px`
- Border `1px solid #2A2E39`
- Value: large bold white
- Label: small gray text below

### Tables
- Header row: `#2A2E39` background, `#787B86` text, uppercase
- Alternating rows: `#131722` and `#1A1D2E`
- Hover: `#2A2E39` highlight
- Return % column: color-coded (green/red)
- Sticky header on scroll

### Buttons (Buy/Sell style)
- Buy: `#26A69A` text on dark background, border
- Sell: `#EF5350` text on dark background, border
- Rounded: `4px`

### Currency Filter Tabs
- Active tab: Blue `#2962FF` underline or pill
- Inactive: `#787B86`

### Sparklines
- Library: Lightweight Charts or Chart.js mini
- Color: green line if return positive, red if negative

---

## Analytics Page

Same dark tokens as the Portfolio page. Five tabs: **Assets**, **Trading habits & costs**, **Deposit behaviour**, **Dividends**, **Advice**.

### Chart colours
- Categorical series use a fixed order, never cycled: `#3987e5` `#d95926` `#199e70` `#c98500` `#d55181` `#008300` `#9085e9` `#e66767`. After seven slots the rest folds into a grey "Other" (`#5d6170`).
- Colour follows the entity, not its rank: deposits blue, portfolio purple, positions green, S&P 500 gold, OMXS30 orange, Nasdaq 100 futures pink.
- Green / red are reserved for gain / loss.
- One axis per chart. Different units get separate charts that share an x axis (Deposit behaviour: deposits, portfolio and positions stacked, with a linked crosshair and tooltips).
- Thin marks (2 px lines, rounded bar ends), recessive grid, a legend for two or more series, a tooltip on every chart.

### Dividends tab
KPI row (privacy-masked), a Day / Week / Month chip row, a stacked column chart (net green, tax grey) over a running-total area chart with a linked crosshair, insight cards, a top-payers horizontal bar (green = still held, grey = sold), a per-calendar-month bar and a payer table.

### Advice tab and the Add / trim column
- Action badges (`.adv`): ADD green, BUY BACK blue, TRIM gold, CONSOLIDATE purple, REVIEW red, HOLD grey. The kr amount sits under the badge (`.adv-amt`, masked by privacy). The tooltip holds the reasons.
- A gold-edged "What this is (and is not)" panel with the back-test table sits at the top; the entry-profile chips (Conservative / Balanced / Aggressive) follow, then risk cards, a theme bar (red above the 40% cap) and the action tables.
- Assets table: no horizontal scrolling at 1100-1440 px with 13 px text. Type and Ccy share one column, Last buy / Last sell are gone, and below 1360 px the Bought / Sold columns hide (CSS `nth-child` 7 and 8; keep those positions if columns change).

### Cards
- `.vcard` verdict cards (left border: red = act, gold = watch, green = ok) and `.finding` insight cards with an ACT / WATCH / NOTE badge, a big number, a sentence and a grey tip.

## Portfolio Page Layout (continuous)

Summary cards, Add / Trim Ideas (two panels: add or buy back, trim / consolidate / review), Stocks & ETFs, Funds, then the Heat map section. The header nav has only **Portfolio** and **Heat map**; they scroll to the top / to the heat map and highlight by scroll position.

## Heat Map

```
[Group by: Category | Type | Country]  [Colour: Today | Unrealised]  [Refresh]
+-----------------------------------------------------------+
| TECHNOLOGY 43%          | INDUSTRIALS 14%   | HEALTHCARE  |   group blocks, uppercase 11px title
| +---------+----------+  | +------+--------+ | ...         |   tile = one holding, area = market value
| | Micron  | ASML     |  | | GE   | Siemens| |             |
| +---------+----------+  | +------+--------+ |             |
+-----------------------------------------------------------+
        -3% [red ... grey ... green] +3%        (colour scale)
[ distribution doughnut ]   [ breakdown table ]   concentration notes
```
- Squarified treemap, two levels (category, then holding), group background `#0d1017`, 1 px gaps.
- Diverging colour: red `rgb(192,64,62)` to neutral `rgb(58,63,80)` to green `rgb(27,138,127)`; saturates at +-3 % (today) or +-25 % (unrealised). Missing data is neutral grey. Tile text is white; names truncate, and the % is shown only when the tile is large enough.
- Hover tooltip: name, value, weight, today, unrealised, sector / industry / type / country.
- Status line with a live dot (green = live Yahoo prices, grey = export values only).

## Privacy Toggle

Eye icon button in the header of both pages (gold border when values are hidden). Hidden values are blurred (`color: transparent` plus a soft `text-shadow`), labels stay visible, and the state is kept in `localStorage` (`tv_privacy`) and shared by both pages. Mark any new private number with `<span class="pv">`. Chart kr axes and tooltips are switched off while hidden.

---

## Icons & Logos
- Use company logos where possible (via Clearbit API: `logo.clearbit.com/domain.com`)
- Fallback: colored initials avatar

---

## File Structure (Recommended)
```
/trading-dashboard/
├── index.html
├── style.css
├── app.js
├── data/
│   ├── stocks.csv
│   └── funds.csv
├── components/
│   ├── ticker.js
│   ├── table.js
│   ├── cards.js
│   └── sparkline.js
└── api/
    └── prices.js
```
```

---

## Phase 3 — Nordnet Integration & Last Buy Tracking

### Data Flow (updated)
```
Nordnet Website → Export CSV → nordnet_sync.py
  --watch mode  → auto-copy from Downloads → "Innehav Tabell Export, accno N, DATE.csv" (stocks + ETFs + funds)
  --api mode    → Nordnet REST API (session token) → same file format

Newest Innehav file → server.py /api/holdings → app.js (loadHoldings, split by isFundName)
  → detectAndSaveBuys()  → localStorage snapshot
  → Yahoo Finance API    → live prices (60s refresh)
  → 5-min CSV auto-reload (setInterval csvRefreshMs)
```

### Last Buy Display
Columns that show last-buy data (gold `.lb-tag` text below main value):

| Column | Normal | With last buy |
|--------|--------|---------------|
| Qty    | `5`    | `5` + `(+2)` in gold |
| Price  | `252.00` | `252.00` + `(248.50)` in gold |

- Gold color token: `#F7C948`
- Font size: 10px, block-level under main value
- CSS class: `.lb-tag`

### Files Added / Modified
| File | Change |
|------|--------|
| `nordnet_sync.py` | New — Nordnet sync script (watch + API modes) |
| `Innehav Tabell Export, accno N, DATE.csv` | Single holdings export (newest used); replaces `portfolio_stocks/funds.csv` |
| `app.js` | `CFG.holdingsUrl`, `loadHoldings()`, `lastBuy` state, snapshot functions, CSV reload |
| `index.html` | Refresh Portfolio button in header |
| `style.css` | `.refresh-btn`, `.lb-tag` styles |

### Nordnet API Session Token (for --api mode)
1. Open `nordnet.se` → log in with BankID
2. DevTools → Network tab → filter `api/2`
3. Click any request → Headers → copy `SESSION` cookie value
4. Create `.env` in project root:
   ```
   NORDNET_SESSION_TOKEN=<paste here>
   NORDNET_ACCOUNT=66262387
   ```
5. Run: `python nordnet_sync.py --api`

---

## STEP 2 — Project Architecture Plan

Here's the full tech stack decision (simple, no framework needed):

| Layer | Choice | Reason |
|---|---|---|
| UI | Plain HTML + CSS + Vanilla JS | No build step, fast, Claude Code handles it easily |
| Charts | Chart.js (CDN) | Simple sparklines + pie chart |
| Data | Your CSV files | Already have them |
| Live Prices | Yahoo Finance via `https://query1.finance.yahoo.com` | Free, no API key needed |
| Server | Python `http.server` or Node `live-server` | Just to serve files locally |

---

## STEP 3 — Where YOU Engage Claude Code (in VS Code)

Here's exactly what to do, step by step in **VS Code with Claude Code**:

### 🔵 Open Claude Code terminal in VS Code:
Press `Ctrl + ~` to open terminal, then type `claude` to start Claude Code.

---

### Task 1 — Give Claude Code this prompt:
```
Read the WishList.md and DesignGuide.md files in this project. Then read stocks.csv and funds.csv to understand the data structure. Create a complete trading dashboard as a single-page web app (index.html, style.css, app.js) that matches the design guide. Use the color palette, layout, and component specs exactly. Load data from the CSV files. Show stocks and funds in separate tables with SEK and USD currency tabs. Include summary cards at the top. Make it look like TradingView dark theme. No frameworks — plain HTML/CSS/JS only.
```

### Task 2 — After Claude Code generates files, ask:
```
Now add live price fetching from Yahoo Finance API for each ticker symbol found in the CSV files. Update the "Latest Price" and "Today's Change %" columns dynamically when the page loads. Handle CORS using a proxy if needed.
```

### Task 3 — For the ticker bar:
```
Add a scrolling top ticker bar showing OMXS30, DAX, SP500F, Gold, and USD/SEK with live data from Yahoo Finance. Color code each: green if positive, red if negative.
```

### Task 4 — Final polish:
```
Add sparkline mini-charts to each row in the tables using Chart.js. Use green color for positive total return, red for negative. Also add company logo images using Clearbit API (logo.clearbit.com). Add a currency toggle button to switch all values between SEK and USD.
```

### Task 5 — Start local server:
start server>python -m http.server 8000
kill server> taskkill /IM python.exe /F
```
Start a local development server so I can view the dashboard in my browser. Tell me the URL.