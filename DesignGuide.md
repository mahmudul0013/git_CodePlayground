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

### Volatility column
The 7-day sparkline column was replaced by **Vol 3M** (daily volatility over 3 months, `col-vol`): right-aligned `%` with two decimals, plain below 3%, gold from 3%, red from 5%; the tooltip gives the number of days, the yearly figure and the average absolute daily move. It sits directly in front of **Day %** (the usual daily move next to today's move); a Day % that is at least twice the volatility is bold with a tooltip ("2.3x its usual daily move"). It is sortable and hidden on phones (below 700 px), like the return-in-kr column. Idea badges: ADD green, BUY BACK blue, WATCH dashed grey (close to a signal), TRIM gold, CONSOLIDATE purple, REVIEW red.

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

### Plan & advice tab and the Add / trim column
- Action badges (`.adv`): ADD green, BUY BACK blue, TRIM (shown as SELL on the Portfolio page) gold, CONSOLIDATE purple, REVIEW red, WATCH dashed grey, HOLD grey; a queued sale carries a grey "· later" tag (`.adv-later`, tooltip: sold after this month's sales). The kr amount sits on the same line as the badge (`.adv-amt`, inline, masked by privacy) so a row stays one line high. The tooltip holds the reason.
- The tab (plan.js / plan.css) reads top to bottom: profile chips (they apply at once; no settings form), the status line, **The short verdict** (a panel with a red left border, one paragraph with bold lead-ins: One bet / One habit / One timing problem / What worked), five tiles, then *Where the money was lost* (red / green bars) beside *How well you follow each popular strategy* (blue 0-10 bars) and the measures table; *This month* (two panels: *Each deposit goes to* with the share of every deposit in % (from `deposit_plan[].pct`, whole numbers adding up to 100, the funds inside a group as their part of it; no kr: the split holds for any amount), sales due with a pill "RSI nn: OK today" in green or "wait for a bounce" in gold, in a 420 px scroll box; an (i) button opens the reason under a row); no cards that repeat a tile; *One strategy per category* (today against target bars, lifetime result per category in green / red, a category table with an inline bar and a white target tick, status pills over / under / on target); *Holdings by category* (collapsible group rows in one neutral style: --surface2 background, bold name, a status pill over / under / on target, no colour per category; holdings indented under their group; weekly trend pill above / below with weeks, a category select per holding); *Evidence* (CAGR and worst-fall bars, buy and hold in grey against the rule used in blue, findings, a details table with the used rule tinted); strategy-fit bars and table; transition lines (plan blue, deposits only aqua, as now orange, dashed target) and stress-test bars (today grey, target blue); the SMA(200) explainer and the rules.
- Colours come only from the CSS tokens and are read at render time; every chart redraws on `tvthemechange`. Categories get no colour of their own in tables (it read as a rainbow unrelated to the rest of the page): headings are neutral, meaning is carried by the status pill and the bar (accent blue, red when over target). Charts use --s1 for the plan / rule used, --text-dim for buy and hold or today.
- Assets table: no horizontal scrolling at any width, one line per row. Type and Ccy share one dim text column (never a pill), Last buy / Last sell are gone; columns hide by `nth-child` (keep those positions if columns change): <= 1500 px 7, 8 (Bought / Sold), <= 1250 px 2, 9, 10, <= 1000 px 3, 5, 11; column 3 (status) is always hidden in *Currently held* (`#asset-table.view-held`). The name keeps min-width 200 px (150 px <= 1000 px) and headers never wrap.

### Cards
- `.vcard` verdict cards (left border: red = act, gold = watch, green = ok) and `.finding` insight cards with an ACT / WATCH / NOTE badge, a big number, a sentence and a grey tip.

## Portfolio Page Layout (continuous)

Summary cards, Buy / Sell this month (two panels: buy this month, sell this month), Stocks & ETFs, Funds, then the Heat map section. The left sidebar holds two foldable panels: Trend Signals (summary bar of money above / below SMA(200), then Changed this week / May change on Friday / Changed in 2-4 weeks, each item with a green ▲ or red ▼, distance to SMA(200), an 8-week strip and an action chip: red sell, green buy, grey keep, gold dashed for a pending Friday decision) and the Reports Calendar. The header nav has only **Portfolio** and **Heat map**; they scroll to the top / to the heat map and highlight by scroll position.

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
| Charts | Chart.js 4.4.0 (CDN) | Doughnuts, bars, lines |
| Data | Nordnet CSV exports (ledger + holdings) | Ground truth for positions, cost and trades |
| Live data | Yahoo Finance via the local `/yahoo/*` proxy and `server.py` endpoints | Free, no API key |
| Server | Python standard library (`ThreadingHTTPServer`), started by `start-dashboard.bat` or `python server.py` | No dependencies |


## Light and dark mode
`theme.js` (first script in every page head) sets `data-theme` on `<html>` before first paint, stores the choice in `tv_theme`, injects the sun / moon `.theme-btn` before `#user-menu`, and fires `tvthemechange`. Dark keeps the original TradingView tokens; light uses white / #F7F8FA surfaces, #131722 text and darker green / red / gold so small text keeps 4.5:1 contrast. Charts read colours from tokens at render time and repaint on the event.

## Tables: no sideways scrolling
Every data table wraps to its box. `table.stack` (responsive.css): when the box (`.tbl-wrap` / `.table-wrap`, `container-type: inline-size`) is 460 px or narrower each row becomes a bordered card, the first cell is the title and every other cell shows its `data-label` on the left and the value on the right; `table.stack.wide` does the same below 900 px and lays the values out in columns (`repeat(auto-fill, minmax(130px, 1fr))`, two columns on a 390 px phone), with the name, full-width notes and `.span2` cells across the card. Group rows (`tr.grp`) and sub-rows (`tr.sub`) have no card border. Reasons never get a column: an (i) button (`.why-btn`, 20 px, 28 px on touch) opens a `tr.why-row` under the row. The Portfolio tables hide columns by viewport (<= 1250 px logo / currency / GAV, <= 1050 px quantity / price, <= 760 px return kr, <= 560 px volatility) and let the name wrap. Text wraps only between words (`overflow-wrap: break-word`, never `anywhere`, no hyphen breaks inside a word).

### Long lists: scroll boxes
Long tables scroll vertically inside their own box; there are no Show all / Show fewer buttons. `.table-wrap` (Portfolio, Analytics) has `max-height: min(70vh, 640px)` (Analytics `min(72vh, 660px)`, `.short` 340 px, filling its grid panel), `.tbl-wrap.scroll` 420 px (`.tall` `min(72vh, 680px)`), the heat-map breakdown 440 px and an asset's trade list (`.detail-inner`) 320 px. Inside a scroll box the `thead` is sticky, `overflow-x: hidden` with `scrollbar-gutter: stable` (the scrollbar never makes the table wider than its box) and `overscroll-behavior: contain`.

### Headers at every width
Above 700 px both headers are one row (`flex-wrap: nowrap`), 50 px. The status text is short ("Live · 20:42" / "Synced 20:42", gold "ledger older than holdings" when stale); file names live in the `title` of the text and the dot. Steps: <= 1180 px `.btn-label` and `.um-name` hide; <= 1000 px the Portfolio status text and `.um-caret` hide and tab padding shrinks; the Portfolio logo text hides at 901-1000 px (the 230 px sidebar is still there) and <= 820 px. `main` padding applies to the Analytics page only (`main:not(#main-content)`): on the Portfolio page it put a 16 px frame round the header.

### Table boxes and data notes
A `.table-wrap.short` inside a grid panel hugs its rows (`flex: 0 1 auto`, max 340 px, then scrolls); a chart in the same panel takes any extra height. Cells without letters and at most 24 characters (dates, numbers, %, "+1 234 kr") get `td.nw` (no wrap) from `table()` in analytics.js. Data notes are a folded `<details>` (`#data-notes`, last child of `main`, gold left border, count pill), open state in `localStorage` `tv_notes_open`; the top banner is only for load errors.

### Phone header
At <= 700 px the Portfolio header is two rows (logo, short tab labels, icon-only buttons: `.btn-label`, `.um-name`, `.um-caret`, `#last-updated-time` hidden; the update time is the status dot's `title`); header plus ticker stay under 16% of a 900 px screen. The Analytics `#top` is one bar <= 60 px with short tab names (`.tl-long` / `.tl-short` spans); `#sync-text` hides below 1100 px and the logo below 440 px. Below 560 px the ⓘ icons in table headers hide, numbers in the Portfolio tables use whole kronor and one-decimal percentages (`NARROW` in app.js), KPI tiles compact below 600 px.
