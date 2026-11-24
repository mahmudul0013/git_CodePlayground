# Trading Dashboard

A personal, browser-based portfolio dashboard inspired by TradingView's dark theme. It tracks a Nordnet brokerage account (Swedish and US holdings) using plain HTML, CSS and vanilla JS. A small Python server serves the files and proxies Yahoo Finance for live prices.

## Features

- Portfolio summary: account value, today's P&L, all-time result, SEK/USD allocation (every number comes from the one valuation, see *One source of truth*)
- Stocks and funds tables with SEK/USD filters, sorting, search and a **Vol 3M** column: the daily volatility of every holding over the last 3 months (the typical size of a one-day price move in %, the standard deviation of daily changes from Yahoo daily closes; funds use their Yahoo NAV history; red from 5% a day, gold from 3%; hover for the yearly figure). It sits directly in front of **Day %**, so you can see at a glance whether today's move is normal for that holding (Day % turns bold when it is at least twice the usual daily move). It replaced the 7-day sparkline
- Scrolling market ticker (OMXS30, DAX, S&P 500 futures, Nasdaq 100 futures, US 10-year yield in %, Gold, BTC/USD, USD/SEK, EUR/USD)
- Reports Calendar sidebar (replaced the old fixed watchlist) and SEK/USD currency toggle
- Last-buy tracking: new shares and buy price shown in gold under Qty and Price
- Buy / Sell this month: the top 5 buy ideas (deposit plan, pullbacks in an uptrend, buy-backs) and the top 5 sales due (size cap, trend exit, regime exit, tiny positions); see the portfolio plan below
- **Light refresh, correct numbers first** (`pulse.js`, one scheduler per page): nothing is fetched while the tab is hidden, and every job that is due runs once when you come back. In market hours (Mon-Fri 08:00-22:30 Stockholm time) the valuation refreshes every 30 s, the ticker every minute, the plan and trend signals every 10 min, the growth curve every 30 min and the uploaded files are checked by a small signature request every 2 min (Analytics 1 min); outside market hours prices do not move, so the valuation refreshes every 15 min. The heat map and the growth curve reuse the page's valuation instead of asking again, and the growth curve reloads at once when its last point differs from the account value (so the two never disagree on one page). The server gzips JSON and pages above 1 KB, and the browser keeps the JS / CSS / HTML files and only asks whether they changed (ETag, answered with 304), so a `git pull` is picked up on the next view. Measured with the page left open for 90 s: Portfolio 3 requests / 17 KB (was 16 / 211 KB), Analytics 3 / 17 KB (was 21 / 887 KB); one page view 124 KB (was 683) and 220 KB (was 1 652). Server memory with every page loaded about 62 MB (the 10-year prices are freed after the evidence test).
- **One continuous Portfolio page**: summary, signals, stocks, funds, then the **Heat map** (the nav buttons *Portfolio* / *Heat map* just scroll)
- **Portfolio heat map**: treemap of the current holdings, size = market value, colour = today's change or unrealised return, grouped by Yahoo Finance sector (or type / country), with distribution doughnut, breakdown table and concentration notes. It syncs by itself: a new or changed Nordnet CSV is picked up within 10 s and live Yahoo prices refresh every 30 s
- **Net Asset Value growth curve** (Portfolio page, directly above Add / Trim Ideas): the account value on every weekday since your first transaction, rebuilt from your ledger and Yahoo daily closes (not dividend-adjusted, converted to kr with that day's FX rate, cash included; funds and unmatched symbols use your own trade prices). Pick the **time range** (1W, 1M, 3M, YTD, 1Y, 3Y, Max; a range longer than your history shows everything), the **view** (*Value (kr)* with a dashed "net deposited" line, or *Growth (%)*, which is time-weighted so a deposit is never shown as growth), and any **categories** (the same Yahoo sectors as the heat map, up to 8 curves at once in one chart; the axes rescale to the selection). A **Smooth** switch (Off / Light / Strong; Light by default) calms the line for readability only: it is a short moving average with exact end points drawn as a monotone curve, while the tooltip and the tiles always show the exact daily numbers. The whole account is a white line, the money you deposited a gold dashed line, and the area between them is green for a gain and red for a loss; every line also carries a label at its right end. Four tiles show the account value, the change in the range with the deposits inside it, the time-weighted growth and the largest drop. The chat answers "how much has my portfolio grown this year".
- **Reports calendar** (left sidebar of the Portfolio page; a slide-in drawer on phones): earnings reports and ex-dividend dates of your stocks from Yahoo Finance as one scrollable list, Today, then Tomorrow, then This week (next 7 days), each with the holding's weight and an "(est.)" mark while the date is not confirmed; hover for the analysts' EPS estimate. A date that has already passed means the company just reported and Yahoo has not published the next one yet. Funds and ETFs have no earnings. The chat answers "which of my stocks report this week", "when does ASML report" and "ex-dividend date for Apple".
- **Portfolio plan: one strategy per category** (Analytics → *Plan & advice*, the Portfolio page *Buy / Sell this month* panels, the *Add / trim* column of the Assets table). Every holding is put in a category (fund name rules, Yahoo sector and industry; you can move any holding to another category in the Plan tab). Each category has a target share of the whole account (cash included) and its own rule, chosen from a 10-year test of your own holdings per category (2017-2026, 0.3% cost per switch):
  - **Broad index funds** (target 50%, Balanced): buy and hold with monthly saving, never timed (every timing rule lost: buy and hold 12.3% a year against 4.9-8.6%).
  - **AI and semiconductor chain** (15%): the theme ETFs and the 5 largest stocks are the *hold half*; the other stocks are the *trend half* and follow the **weekly close vs SMA(200)** rule. Best return per unit of volatility in the test and a smaller worst fall (-36% against -43%).
  - **Big tech, Healthcare and consumer, Financials** (7 / 7 / 3%): quality, buy and hold; new money only in an uptrend with RSI(14) below 40 (Balanced), and only while the category is under its target. REVIEW when SMA(50) falls below SMA(200) with a loss above 15%.
  - **Industrials and defence** (5%): half held, half on the weekly SMA(200) rule. **Energy and materials** (3%): hold while SMA(50) is above SMA(200). **Gold, bonds and real estate** (5%) and **Opportunity cash** (5%): fixed weights, no timing.
  - **Size cap** 4% per stock; tiny positions (under 1 500 kr) are CONSOLIDATE. **No RSI take-profit**: RSI above 75 was followed by more gains in the tests, so profits are taken by the size and category caps. A category more than 5 points over target gets no new money and is reduced by at most the monthly reduction budget (default 15 000 kr), smallest names first; planned sales go on a day the RSI(14) is above 45. RSI only times new money, never a sale.
  - **"200-day average"** everywhere = SMA(200), the simple average of the last 200 daily closes (dividend adjusted), checked at the **last close of each week**: one weekly close below takes the trend half out, one weekly close above brings it back. A separate check of SMA(50), EMA(100) (daily and weekly), half + EMA(100) and an EMA(100) warning for new money found none that beat the current rules in both 2017-2022 and 2023-2026.
  - The **Plan & advice** tab shows: **the short verdict** (your result on deposits and its causes in a few sentences: the group that lost most, fees against trading profit, deposits made after the best day, what worked, how many independent bets the portfolio really is), five tiles, **Where the money was lost** (lifetime result per category) next to **How well you follow each popular strategy** (0-10) with the measures behind it, this month (**each deposit goes to**: the split in % of every deposit, so it holds for any amount, with the funds inside each group; and the sales due in their own scroll box, each with an "OK today / wait for a bounce" note), every category against its target, all holdings by category with the weekly trend (group rows in one neutral style with a status pill, the holdings indented under them; the reason behind an action sits behind an **(i)** button), the evidence (the 10-year test, computed in the background for your own holdings), the transition (months to target) and a stress test. Buy ideas are on the Portfolio page only (a deposit-plan buy there shows its share, "41% of deposit"). The **profile** buttons (Conservative: index funds 60%, AI at most 10%; Balanced 50 / 15; Aggressive 40 / 22; they also set the RSI level for new money, 35 / 40 / 45) apply at once and are saved for the account, like a holding's **category** chosen in the holdings table, in `data/profiles/<id>/plan_settings.json`; the Portfolio page, the Plan tab, the assistant and every device use the same plan. The plan assumes 10 000 kr deposited a month, a reduction budget of 15 000 kr a month for an over-target group and 5% opportunity cash (`DEFAULT_SETTINGS` in strategy.py; there is no form for them).
- **Trend Signals sidebar** (Portfolio page, above the reports calendar; folds away; a drawer on phones): how many holdings closed last week above / below SMA(200) and how much money that is, then *Changed this week*, *May change on Friday* (today's price is on the other side of SMA(200) than the last weekly close) and *Changed in 2-4 weeks*, each with the 8-week history, "choppy" when a holding crossed 3 or more times in 12 weeks, and what the plan does about it (sell the trend half, keep the hold half, stop new money, new money OK).
- **Light and dark mode**: the sun / moon button in every page header (remembered per browser); every chart repaints in place
- **Long lists scroll inside their own box** (no Show all buttons): Portfolio holdings and the Analytics assets table at most about 70% of the screen high, an asset's trade list 320 px, the heat-map breakdown 440 px, Sell this month 420 px, holdings by category and the evidence about 72% of the screen; the column headers stay visible while the rows scroll, and a scroll box never scrolls sideways.
- **No sideways scrolling in any table** on desktop, tablet or phone: text wraps between words only (a word is never broken in the middle), and when a table's box is narrow (CSS container query) every row becomes a small labelled card; wide tables (holdings by category, the evidence) become cards with their values in columns on tablets too. The Portfolio and Assets tables hide their least important columns step by step (logo, currency and average cost first) and the Assets table turns into cards on phones. In *Currently held* every row stays one line high: the status column is hidden (all rows are held), Bought / Sold hide below 1500 px, type / first buy / last trade below 1250 px, and the name keeps at least 200 px. On phones amounts are shown in whole kronor and percentages with one decimal.
- **Compact headers**: on every screen wider than a phone both headers are ONE 50 px row: the status shows only the time ("Live · 20:42", "Synced 20:42"; the file names are in its tooltip), and button labels, the user name and the logo text drop step by step as the window narrows. The Portfolio header sits flush under the ticker. On phones the Portfolio header and ticker take about 130 px (two rows) and the Analytics header is a single 48 px bar with short tab names (Assets, Habits, Deposits, Dividends, Plan).
- **Data notes** (export rows that could not be matched, ...) are one folded line at the bottom of the Analytics page; click to open (remembered).
- Table boxes hug their rows (no empty space under a short table), and dates and numbers never break across lines. The *All dividend payers* list scrolls in its own box; the *Data range* tile shows the span ("17 months") with the dates under it.
- **Privacy toggle** (eye button in the header of both pages): blurs summary rows, headline numbers, money/size table columns, "... kr" amounts in text and kr chart axes/tooltips. Remembered between pages and reloads (visual masking only)

- **Analytics page** (`/analytics.html`), five tabs:
  - **Assets**: asset explorer (all ever held / current / closed / bought or sold in the last 1 week or 1 month, with type, currency and country filters and charts)
  - **Trading habits & costs**: habit score, broker costs, benchmark against OMXS30 / S&P 500 / Nasdaq 100 futures, good-practice tips, fee and holding-time analysis
  - **Deposit behaviour**: deposits per day / week / month as columns, estimated portfolio value (or deposit-free return) and positions held as lines on one shared axis, optional index overlays (OMXS30, S&P 500, Nasdaq 100 futures `NQ=F`), insight cards (return vs market, risk, idle cash, deposit timing, why you are ahead or behind the index, money per position)

  - **Dividends**: dividends received (net of withholding tax) per day / week / month, running total, per-calendar-month pattern, top payers, payer table and insight cards. Dividends were always inside the account value; this tab makes them visible
  - **Plan & advice**: the per-category portfolio plan described above, with your plan settings

  Headline values (Account value, All-time result, Unrealised and the Portfolio page totals) are rescaled by live Yahoo prices; the holdings export is only a snapshot from the day it was made.

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

### 2. Start the server and create your account

```powershell
python server.py                  # http://localhost:8000
python server.py --port 9000      # custom port
```

Use `server.py`, not `python -m http.server`. Only `server.py` has the login, the profiles and the `/yahoo/*` proxy.

**First start:** while there are no users, the server window prints a one-time **setup code**. Open `http://localhost:8000/login.html`, enter the code and choose a username and password. That first account is the **admin**. Tick *import the existing files in the project folder* to move your current Nordnet CSVs into that account (the originals stay where they are).

### 3. Upload your two Nordnet files (per account)

Every account has its own private profile. After signing in, an empty profile lands on the upload screen:

1. Log in at nordnet.se and export the holdings table (**Innehav → Exportera**). Three Nordnet names work: `Innehav Tabell Export, accno N, YYYY-MM-DD.csv` (stocks, ETFs and funds in one file), or the older pair `aktier_kontonummer-N_YYYY-MM-DD.csv` (stocks and ETFs) and `fonder_kontonummer-N_YYYY-MM-DD.csv` (funds). Upload both old files with the **same date**: the server converts them to the standard layout (`GAV` / `Snittkurs` → `GAV/snittkurs`, `1 dag %` → `Idag %`, `Senaste NAV` → `Senaste kurs`, extra `Värde` / `Inköpsv. SEK` columns dropped) and combines them into one holdings file; after the first of the two it tells you the other part is still missing. A full Innehav export of the same date replaces the parts.
2. Export the transactions ledger (`transactions-and-notes-export.csv`, no account number in its name).
3. Use the two **Browse** buttons (or drag the files in). The server reads the account number from inside the ledger (`Depå` column) and from the holdings file name, and refuses files from different accounts, files that do not parse, and an account number that already belongs to another user. One Nordnet account per profile.

Upload newer exports any time from **user menu → Upload / replace files**; the pages pick them up by themselves. Every upload is **compared with the file that is running now** and the result is shown: for holdings, positions added / removed / with a changed quantity and the change in total value; an export **older** than the running one is kept as history only (the dashboard keeps using the newer one) and the page says so; for the transactions ledger, a file with **fewer rows or an earlier end** than the running one is *not* stored until you press **Replace anyway**, so a partial export cannot silently overwrite your full history. The previous holdings file becomes the baseline for the gold last-buy tags (built automatically on upload; `nordnet_sync.py` is no longer needed).

The export has no instrument type, so the Portfolio page puts Nordnet mutual funds (names containing index/indeks/allemansfond/AuAg...) in the **Funds** table and everything else in **Stocks** (`isFundName()` in `app.js`, matching `classify_type()` in `trade_analytics.py`).

### 3b. Run it without VS Code (Windows)

Double-click **`start-dashboard.bat`**. It starts `server.py` in its own window (minimised is fine) and restarts it automatically if it ever stops. Close that window, or double-click **`stop-dashboard.bat`**, to stop the server (it only touches this project's processes). A second server on the same port refuses to start with a clear message (Windows would otherwise let two servers share a port silently).

Optional: **`install-autostart.bat`** makes the server start by itself, minimised, at every Windows login (puts a launcher in your Startup folder, no admin rights needed); **`uninstall-autostart.bat`** removes it. Stop any server you started from VS Code first, otherwise port 8000 is taken.

### 4. Other people (multi-user)

- **Invites:** as admin open **user menu → Admin** and create a single-use **invite code** (valid 7 days). Open codes stay visible in the admin table (with **Copy** and **Revoke**) until the person registers; then the code is erased and the row reads "used by <name>" (**Remove** clears it). Revoking a code deletes the whole invite (hash and code) at once, so it stops working and leaves nothing behind. The list cleans itself: unused invites disappear when they expire, and used ones a week later. As admin you can also **Delete** any other user: the account and all their files are removed and their sessions end (you cannot delete your own account). The new person opens `/login.html`, chooses *I have an invite code*, picks a username and password, then uploads their own two files. They only ever see their own portfolio.
- **One port for everybody.** All users share port 8000 and one server process; the market-data caches (prices, history, sectors) are shared because they are public data, everything derived from a portfolio is per user.
- **Reaching the server from other devices (Tailscale).** The server listens on all interfaces. Your own phone works because it uses the same Tailscale account as the PC. Do not give anyone your login. Use **node sharing** instead: in the Tailscale admin console open *Machines*, choose the server PC, **Share**, send the link. The other person installs Tailscale with their own account, accepts the share and then opens `http://<the PC's 100.x.y.z address>:8000`. They can reach only that PC. Tailscale decides who can reach the server, the dashboard login decides which portfolio they see. Plain Wi-Fi addresses (`http://192.168.x.x:8000`) are not encrypted, so passwords can be read on that network; prefer Tailscale.
- **"Not secure" in the browser** only means the page is served over plain `http://`. Over Tailscale the traffic is encrypted anyway; the label is the browser's. You do **not** need a domain: Tailscale gives every machine a free name (`<pc-name>.<tailnet>.ts.net`) and a free certificate for it. A certificate is issued for a NAME, never for a bare IP address, so `http://192.168.x.x:8000` will always say "Not secure".
  - **How it runs:** when the server finds `data/tls/cert.pem` and `data/tls/key.pem` (or `--cert FILE --key FILE`) it serves **plain http on 8000 as before** (so your LAN address keeps working) **and https on 8443** (for the Tailscale name). The login cookie gets the `Secure` flag only over https. `--https-port N` changes 8443; `--https-only` serves https on the main port and redirects plain `http://` to it. Without a certificate nothing changes.
  - **Step by step with Tailscale (on the SERVER PC):**
    1. In the Tailscale admin console (https://login.tailscale.com/admin/dns) make sure *MagicDNS* is on and press **Enable HTTPS** under *HTTPS Certificates*.
    2. Find the PC's full name in the Tailscale app or in *Machines*, for example `server-pc.tail1234.ts.net`.
    3. Open PowerShell in the project folder and run:
       `New-Item -ItemType Directory -Force data\tls; cd data\tls; tailscale cert server-pc.tail1234.ts.net; ren server-pc.tail1234.ts.net.crt cert.pem; ren server-pc.tail1234.ts.net.key key.pem` (use your own name).
    4. Allow the new port through the Windows firewall once (PowerShell as administrator): `netsh advfirewall firewall add rule name="TradeView https" dir=in action=allow protocol=TCP localport=8443`.
    5. `stop-dashboard.bat`, then `start-dashboard.bat`. The window now shows a *Secure* line.
    6. On any device with Tailscale switched on open `https://server-pc.tail1234.ts.net:8443`. No warning.
    7. The certificate lasts 90 days: repeat step 3 and restart before it expires (put a reminder in your calendar).
  - **Home Wi-Fi without Tailscale:** keep using `http://192.168.x.x:8000` (works, shows "Not secure"). A local certificate authority such as `mkcert` can remove the label there, but its root certificate must be installed on every device; not worth it for a private network.

### 5. Security model

Passwords are hashed with scrypt; sessions use random tokens in an HttpOnly cookie (only hashes are stored); five wrong logins lock the username and IP for a growing time; every changing request needs the `X-TV` header and a matching Origin; every data route reads only the signed-in user's folder (`data/profiles/<random id>/`, git-ignored) and never a path or id from the browser; only html/js/css/image files are served as static files, never `data/`, `.py`, `.csv`, `.json`, `.env`; `/yahoo/*` needs a login. The admin can create invites, reset passwords and delete users, but has no screen showing another user's portfolio. The person who owns the PC can of course read the files on disk (no encryption at rest).

### 6. Stop the server

Press `Ctrl + C` in the terminal, or run `stop-dashboard.bat`.

## Typical daily workflow

1. Export new CSVs from Nordnet.
2. Sign in, **user menu → Upload / replace files**, Browse the two files.
3. The pages pick up the new data by themselves; the server only needs to be running.

## One source of truth: how every number is defined

All prices are applied in ONE place on the server (`valuation.py`); the Portfolio page, Analytics, the heat map, the Add / Trim weights, the growth curve, the reports calendar and the chat only read its result (`/api/snapshot`, and `/api/trades`, `/api/assets`, `/api/advice`, `/api/nav` built from it). The browser does no pricing, so the same thing can never show two values.

| Term | Meaning |
|---|---|
| **Holdings value** | shares x price of what you hold today, in kr |
| **Account value** (net asset value) | holdings value + cash balance |
| **Unrealised** | holdings value minus what the current holdings cost (Nordnet export value minus Nordnet export return) |
| **All-time result** | account value minus net deposits: includes realised, unrealised, dividends and all costs |
| **Growth (time-weighted)** | return of the account where a deposit is never growth (growth curve) |
| **Today's P&L** | change of the holdings today, measured on yesterday's value |

Price used per holding: the live Yahoo price if it is in the same currency as the Nordnet export and within 0.5x-2x of the export price (otherwise the symbol is another instrument and is ignored); funds and unmatched symbols keep the Nordnet export value. Every page shows the basis ("valued 10:20 with live prices for 80 of 86 holdings; the others at the Nordnet export of 2026-11-22").

Which Yahoo listing a holding is priced from (`symbols.py`) follows the **Market** column of the holdings export: the listing on that venue (Xetra `.DE`, Euronext Amsterdam `.AS`, Paris `.PA`, Nasdaq Stockholm `.ST`, Oslo `.OL`, Copenhagen `.CO`, Helsinki `.HE`, London `.L`, Toronto `.TO`, SIX `.SW`, New York / Nasdaq no suffix, ...) in the export's currency is chosen, so ASML on Euronext Amsterdam is `ASML.AS` (EUR), not the US `ASML` (USD) that could never value it, the VanEck Semiconductor ETF on Xetra is `VVSM.DE`, not the US `SMH`, and Celestica on the NYSE is `CLS`, not `CLS.TO`. A listing found by name must have the same Yahoo long name as the ISIN's own listing, so a sister share class (Dist / Acc) is never taken. Cached symbols that contradict the market are looked up again once and keep the market used; hand edits (`"source": "manual"` in `symbol_cache.json`) always win. Only public ISINs, names and tickers are sent to Yahoo. Funds (Yahoo `0P...`) keep the Nordnet value. The last day of the growth curve and the end of the Deposit-behaviour tab are anchored to the same live valuation; earlier days are rebuilt from Yahoo daily closes.

**Accepted differences:** numbers from the same snapshot are identical. Rounding and currency conversion may move a figure that is reached by a different route (for example the growth curve rebuilt from daily closes) by at most **max(5 kr, 0.05% of the figure)**. `python tests/consistency_test.py` reads every source of every number and fails when two differ by more; run it after any change that touches numbers (`python tests/consistency_test.py URL USER PASSWORD` checks a running server).

## Ask and help

- A round **chat button** (bottom right, shortcut `/`) answers questions about your own portfolio in one or two lines, for example "what does split orders mean" (definition plus your own number), "how much did I pay in fees", "why is ASML flagged". It is rule-based and runs on the server: no AI service sees your data, and every number comes from the same calculations as the pages. If it is not sure it says so and suggests questions.
- A small **ⓘ icon** on tiles, charts and table headers explains that item with the same engine (tap on touch screens).
- The layout is fluid: phones, tablets and desktops, portrait and landscape; long tables scroll up and down inside their own box (never sideways), narrow boxes turn rows into cards, and charts refit after rotating.

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
| Port already in use | Another dashboard server is running: run `stop-dashboard.bat`, or start this one with `python server.py --port 9000`. |
| A stock shows `—` for price | Add its name to `TICKER_MAP` in `app.js` with the Yahoo Finance symbol. |
| Last-buy tags missing or stale | Upload the newest holdings export again; the previous one becomes the baseline (needs at least two uploads). |
| Heat map "Today" differs from Yahoo or Nordnet | Live day change comes from Yahoo daily bars (last close before the current session). Nordnet funds (`0P...` symbols) keep the export values. A same-currency quote priced 2x off the export is ignored as a wrong symbol. |
| A holding is "Unclassified" or shows no live price | Add or fix its Yahoo symbol in `symbol_cache.json` (set `"source": "manual"`) and in `TICKER_MAP` in `app.js`. ETFs and funds have no Yahoo sector, so they are grouped as ETFs / Funds. |
| Dashboard shows old holdings | Upload the new `Innehav ... Export` file (user menu → Upload / replace files) and click **Refresh Portfolio**. |
| Forgot the setup code | It is printed in the server window at start while no users exist. If users exist, the admin creates invites and resets passwords. |
| Locked out after wrong passwords | Wait for the countdown shown on the login page (60 s, growing to 15 min). |

Yahoo symbol suffixes: `.ST` Sweden, `.OL` Norway, `.HE` Finland, `.CO` Denmark, `.L` London, `.DE` Germany, `.PA` Paris. US stocks use the plain ticker.

## Project structure

```
testTrading/
├── index.html               Portfolio page (summary, tables, heat map section)
├── style.css                TradingView styles, dark and light tokens
├── theme.js                 Light / dark toggle (TVTheme, tvthemechange event, Chart.js defaults)
├── pulse.js                 One refresh scheduler per page: paused while hidden, market-hours aware
├── app.js                   Portfolio logic (data, live prices, Add / Trim ideas, nav scroll)
├── heatmap.js / heatmap.css Portfolio heat map (treemap, doughnut, live sync)
├── analytics.html/css/js    Analytics page (Assets, Trading habits, Deposit behaviour, Dividends, Plan & advice)
├── plan.js / plan.css       The Plan & advice tab
├── asset_chart.js           Per-asset price chart with BUY/SELL markers
├── privacy.js / privacy.css Master privacy toggle (eye button)
├── server.py                Local HTTP server + Yahoo proxy + JSON API (see below)
├── trade_analytics.py       Ledger + holdings -> positions, trades, insights, deposit behaviour
├── benchmark.py             Index comparison and overlay series (OMXS30, S&P 500, NQ=F)
├── symbols.py / symbol_cache.json   ISIN -> Yahoo symbol (hand edits kept)
├── sectors.py / sector_cache.json   Sector / fund category per holding from Yahoo
├── valuation.py             The one valuation (snapshot + apply) every page reads; tolerance for the consistency test
├── tests/                   consistency_test.py (same number everywhere), nav_math_test.py (growth-curve logic), advisor_rules_test.py (plan rules), assistant_test.py (chat answers), symbols_market_test.py (listing per market), https_test.py
├── nav.py                   Net asset value history (total + per category) from the ledger and Yahoo daily closes
├── nav.js / nav.css         The growth curve on the Portfolio page
├── reports.py               Earnings / ex-dividend calendar of the holdings (Yahoo calendarEvents, report_cache.json)
├── advisor.py               The plan turned into actions per holding, cards, portfolio risk (history_cache.json)
├── strategy.py              Categories, targets, weekly SMA(200) trend, deposit plan, transition, stress test, plan settings
├── strategy_bt.py           10-year test of the rules per category on your holdings (background, history10_cache.json)
├── nordnet_sync.py          Legacy: baseline builder and optional API mode (uploads now build the baseline)
├── start-dashboard.bat      Run the server without VS Code (auto-restart)
├── auth.py / profiles.py    Accounts, sessions, invites, per-user profile folders and uploads
├── assistant.py / assistant.js / assistant.css   Local rule-based chat and search
├── help.js / help.css       Tile help (i) icons
├── responsive.js / responsive.css   Fluid layout and chart refit for phones and tablets
├── login.html / account.html (+ .js, auth.js, auth.css)   Sign in, upload, account and admin pages
├── data/                    Users and profiles (created at first start, git-ignored)
├── stop-dashboard.bat       Stop it
├── install-autostart.bat / uninstall-autostart.bat   Optional start at Windows login
├── transactions-and-notes-export.csv / Innehav ... .csv   Legacy single-user files (only used by 'import existing files' at setup)
├── WishList.md              Feature requirements
├── DesignGuide.md           Visual design spec
└── .claude/skill.md         Detailed project design knowledge
```

## Server API

| Route | Purpose |
|---|---|
| `/api/auth/*`, `/api/account/*`, `/api/upload/*`, `/api/admin/*` | Login, sessions, invites, uploads, account and admin actions |
| `/api/ask` (POST) | Assistant answer for a question, from the signed-in user's data |
| `/api/baseline` | Previous-state snapshot for the last-buy tags |
| `/api/holdings` | Newest holdings CSV of the signed-in user (Portfolio page) |
| `/api/trades`, `/api/trades/status` | Full analytics payload; file signature used for auto-sync |
| `/api/assets` | Assets only (used by the heat map) |
| `/api/live` | Live Yahoo quotes for current holdings (25 s cache; a failed request reuses that symbol's last good quote for up to 20 min, marked `stale`) |
| `/api/sectors` | Yahoo sector / fund category per holding (30-day cache) |
| `/api/snapshot` | THE valuation: per holding price used, value, cost, unrealised, today's change and weight, plus the totals (holdings, cash, account value, unrealised, all-time result, today's P&L); live quotes shared 25 s, and one failed Yahoo request reuses the symbol's last good quote (at most 20 min old) instead of dropping the holding to its export price |
| `/api/nav` | Daily net asset value history: total (NAV, cash, net deposits, growth index) and per Yahoo category (value, growth index); built by `nav.py`, price history shared in `nav_price_cache.json` (6 h), curve cached per user for 10 min |
| `/api/reports` | Upcoming earnings / ex-dividend dates of the signed-in user's holdings (Yahoo `calendarEvents`, 12 h shared cache in `report_cache.json`) |
| `/api/advice?profile=` | The portfolio plan (`conservative`, `balanced`, `aggressive`): actions per holding with the weekly trend, cards, and `plan` (categories, deposit plan, sales due, transition, stress test, strategy fit, lifetime result per category); cached 60 s |
| `/api/plan/settings` (GET, POST) | The user's plan settings: profile and category overrides (validated; deposit, reduction and cash % keep their defaults). `/api/advice` without `?profile=` uses the saved profile |
| `/api/plan/evidence` | The 10-year test of the rules per category on the user's holdings (`pending` while it runs in the background; kept 24 h in memory) |
| `/api/benchmark`, `/api/overlay` | Index comparison and daily index curves |
| `/api/symbol` | ISIN / name -> Yahoo symbol |
| `/yahoo/*` | Yahoo Finance proxy |

Every route except the public auth routes needs a session and reads only that user's profile. Memory: per-user caches keep at most 6 profiles (least recently used is dropped); the other caches hold one entry that is replaced, not grown (measured about 40 MB after loading every endpoint, flat over hundreds of polls).

## Further reading

- [WishList.md](WishList.md): feature requirements and implemented phases
- [DesignGuide.md](DesignGuide.md): colors, typography and component specs
- [.claude/skill.md](.claude/skill.md): architecture, last-buy logic, the (old) signal model and ticker map
- [.claude/skills/trading-analytics/SKILL.md](.claude/skills/trading-analytics/SKILL.md): analytics, heat map, live-price and privacy notes
