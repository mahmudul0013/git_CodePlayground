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
│ LIST     │  [Account value] [Today's P&L] [All-time result] [FX] │
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
- A one-line note (rule-based, not a forecast, not advice) sits at the top; the entry-profile chips (Conservative / Balanced / Aggressive) follow, then risk cards, a theme bar (red above the 40% cap) and the action tables.
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

## Net Asset Value Curve (Portfolio page)

One chart space above Add / Trim Ideas. Controls: single-choice **range** chips (1W 1M 3M YTD 1Y 3Y Max) and a **view** switch (Value kr / Growth %) in `.nav-seg` radio groups; **category** checkboxes (`.nav-cat` pills, a colour dot doubles as the legend, share of holdings in grey) with a fixed Total NAV pill; four KPI tiles above the chart.
- Data-visualisation rules: line chart, no smoothing; value axis starts at 0 or just under the lowest point, growth axis has a 0 % reference line; the whole account is a thick near-white line, categories use the fixed categorical palette in selection order so no two selected curves share a colour (max 8 at once); net deposits are a thin dashed grey step line; shared tooltip with the date and every selected curve, sorted high to low; crosshair; compact axis labels (`330k kr`); `aria-label` on the canvas summarises the range.
- Colours: whole account = white (3 px), money deposited = gold dashed step line, area between them green (gain) / red (loss); categories use 8 bright, well separated hues on the dark background in selection order (blue, orange, green, violet, pink, cyan, lime, red; the 6th to 8th also get dashed styles); white and gold are never used for categories. Every line is labelled at its right end (skipped below 520 px wide, where the pills are the legend).
- Smoothing: Off / Light (radius 2) / Strong (radius 5) triangular moving average, drawing only, end points exact, monotone curve, tooltip shows the exact value and the gain versus deposited.
- Fluid: chart height `clamp(240px, 34vw, 420px)` (`clamp(220px, 62vw, 300px)` on phones), KPI tiles 4 / 2 columns, chips wrap, tap targets 40 px on small or touch screens, privacy mode hides the kr axis, tooltip and kr tiles.

## Accounts, Help and Responsive Rules

- **Login / account pages** (`login.html`, `account.html`): centred card on the dark background, same tokens as the dashboard; errors in plain language under the field; the invite code is shown once with a copy button. The header shows a round user button (initial) with a menu: Upload / replace files, Account, Admin (admin only), Log out.
- **Chat button** (`#as-fab`, bottom right) opens a 336x440 px panel (`#as-panel`) that never covers the header; answers are one or two lines with an optional link chip. `/` focuses it, Esc closes it.
- **Tile help**: an 18 px vector ⓘ (`.tv-help`, 40 px hit area) on tiles, chart titles and table headers; tap opens a popover (`.tv-pop`, max 280 px, clamped to the viewport, flips above/below).
- **Responsive**: fluid text with `clamp()`, no sideways page scroll at 320 px and wider, tables in a scroll box with the name column sticky and low-priority columns hidden by width, chart heights `clamp(220px, 40vw, 360px)`, tap targets of at least 40 px at 900 px and below, charts and the heat map refit after resize and rotation (`responsive.js`).

## Privacy Toggle

Eye icon button in the header of both pages (gold border when values are hidden). Hidden values are blurred (`color: transparent` plus a soft `text-shadow`), labels stay visible, and the state is kept in `localStorage` (`tv_privacy`) and shared by both pages. Mark any new private number with `<span class="pv">`. Chart kr axes and tooltips are switched off while hidden.

---

## Icons & Logos
- Use company logos where possible (via Clearbit API: `logo.clearbit.com/domain.com`)
- Fallback: colored initials avatar

---

## File Structure

See the *Project structure* section of [README.md](README.md) for the current file list (Portfolio page, Analytics page, heat map, privacy toggle, `server.py`, `trade_analytics.py`, `advisor.py`, launchers and the Nordnet CSVs).

---

## Phase 3 — Nordnet Integration & Last Buy Tracking

### Data Flow (current)
```
Nordnet website -> export CSVs -> dropped into the project folder by hand
  start-dashboard.bat runs nordnet_sync.py once (portfolio_baseline.json from the 2 newest holdings exports)

Newest Innehav file -> server.py /api/holdings -> app.js (loadHoldings, split by isFundName)
  -> detectAndSaveBuys()  -> localStorage snapshot
  -> /yahoo/* proxy       -> live prices (60 s refresh, works on any host name)
  -> 5-min CSV auto-reload (setInterval csvRefreshMs)
Ledger + holdings -> trade_analytics.py -> /api/trades, /api/assets (Analytics, heat map)
Live Yahoo quotes -> /api/live (25 s) ; price history -> advisor.py -> /api/advice (10 min)
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

## Tech stack

| Layer | Choice | Reason |
|---|---|---|
| UI | Plain HTML + CSS + vanilla JS | No build step |
| Charts | Chart.js 4.4.0 (CDN) | Sparklines, doughnuts, bars, lines |
| Data | Nordnet CSV exports (ledger + holdings) | Ground truth for positions, cost and trades |
| Live data | Yahoo Finance via the local `/yahoo/*` proxy and `server.py` endpoints | Free, no API key |
| Server | Python standard library (`ThreadingHTTPServer`), started by `start-dashboard.bat` or `python server.py` | No dependencies |
