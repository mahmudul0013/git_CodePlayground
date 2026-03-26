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
```
Start a local development server so I can view the dashboard in my browser. Tell me the URL.