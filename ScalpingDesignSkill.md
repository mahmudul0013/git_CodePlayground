# Crypto Bot Master Document
> Platform: Binance | Capital: ~$250 | Three bots, three strategies
> Last updated: 2026-07-09 | For: resuming work with Claude from this point

---

## Quick Start — How to Run

```bash
# Terminal 1 — Scalping Bot (spike detection, trending days)
python bot_engine.py

# Terminal 2 — Grid Bot (oscillation profits, sideways days)
python grid_bot.py

# Terminal 3 — Moon Bot (pump detection) ← TO BUILD NEXT
python moon_engine.py

# Stop any bot
Ctrl+C    ← prints summary, saves trades.csv cleanly

# Switch paper vs live (edit config.py)
MODE = "paper"   ← simulate only, no real money
MODE = "live"    ← real orders on Binance
```

Each bot needs its own terminal. They run in parallel independently.

---

## Account Snapshot

| Asset | Amount | Role |
|-------|--------|------|
| BTC | 0.00273 | Scalp target |
| ETH | 0.00892 | Scalp target |
| SOL | 0.09654 | Primary target (most volatile) |
| USDC | 10.15 | Trading capital |
| BNB | 0.01121 | Keep — pays fees at 25% discount |
| EURI | 4.01 | Convert to USDT |
| PEPE | 1.19M | Convert to USDT |

Primary pair: **SOL/USDT**

---

## Trading Concepts Learned

These concepts were taught from scratch. Future Claude sessions do not need to re-explain them.

### Volume Spike
Sudden burst of buy/sell activity in one candle (3x the average of last 20 candles).
Means a crowd rushed in. Bot rides the same direction as the spike.
- Price UP + volume spike = BUY (momentum continues upward)
- Price DOWN + volume spike = SELL (momentum continues downward)
You are NOT buying at the peak — you buy during the surge and exit fast (+0.5%).

### Bollinger Bands
A rubber band around the price chart:
- Middle line = 20-candle average price
- Upper band = average + 2 standard deviations (price stretched too high)
- Lower band = average - 2 standard deviations (price stretched too low)
Price almost always stays inside. When it breaks outside, it snaps back:
- Price breaks BELOW lower band → bounce UP → BUY
- Price breaks ABOVE upper band → drop DOWN → SELL

### RSI (Relative Strength Index)
A number 0–100 measuring how hard price has been running in one direction.
Like exhaustion — when a runner sprints too long, they must slow down.
- RSI above 75 = overbought = price ran too fast UP → expect drop → SELL
- RSI below 25 = oversold = price ran too fast DOWN → expect bounce → BUY
Uses last 14 candles to calculate. Written as RSI(14).

### Order Book Imbalance
Live list of all pending buy/sell orders people have placed but not executed.
Top 10 levels = 10 prices closest to current price on both sides.
- 70%+ are BUY orders → demand crushes supply → price going UP → BUY signal
- 70%+ are SELL orders → supply crushes demand → price going DOWN → SELL signal
Fastest signal — fires BEFORE price moves (shows intention, not action).

### Short Selling
Selling something you do not own yet, then buying it back cheaper later.
Works backwards from normal trading:
- Normal trade: BUY low → SELL high = profit
- Short trade:  SELL high (borrowed) → BUY low (return) = profit
On SPOT trading (own money only): can only SHORT what you already hold.
On MARGIN/FUTURES: exchange lends you the asset instantly (milliseconds), automated.
For now: SPOT only. Futures/margin = Phase 2 after 1–2 months profitable.

### Grid Bot Concept (Your Own Idea, Validated)
User's insight: sell 1 unit in morning, buy back cheaper in evening = profit both ways.
This is Grid Trading — automated and systematic:
- Divide a price range into levels ($135, $137, $139... $155)
- BUY orders sit below current price, SELL orders sit above
- Every time price bounces between levels → buy low, sell high automatically
- Each completed BUY→SELL pair = one profit unit (grid spacing minus fees)
Works best in sideways/oscillating markets. Fails if price breaks out of the range.

### Moon Bot Concept
"Mooning" = a coin's price shoots up fast and dramatically.
Moon Bot scans hundreds of crypto pairs looking for coins that are starting to pump,
buys in early, and sells before the price crashes back down.
Different from scalping: targets 5–50% gains on random coins, not 0.5% on SOL.
Trailing stop exit: follows price up, only sells when price drops X% from its peak.

---

## Bot 1 — Scalping Bot (COMPLETE)

**Status:** Built and working. Run on Testnet (paper mode).
**File:** `bot_engine.py`
**Best for:** Trending / volatile days, sudden price spikes
**Target:** +0.5% profit per trade | Stop loss: -0.3%

### Architecture

```
data_stream.py     → WebSocket live candle feed (1-min)
spike_detector.py  → 4 signals detect spike entry
risk_manager.py    → position size + SL/TP rules
order_executor.py  → places market orders on Binance
trade_logger.py    → saves every trade to trades.csv
bot_engine.py      → main loop tying everything together
```

### 4 Signals (need 2 of 4 to agree)

```
Signal 1 — Volume Spike
  Current volume > 3x 20-candle average AND price moved > 0.3%
  BUY if price up, SELL if price down

Signal 2 — Bollinger Band Breakout
  Price closes outside upper or lower band (Period:20, StdDev:2.0)
  BUY on lower break (bounce), SELL on upper break (reversal)

Signal 3 — RSI Extreme
  RSI(14) < 25 → oversold → BUY
  RSI(14) > 75 → overbought → SELL
  Wait next candle to confirm reversal

Signal 4 — Order Book Imbalance
  Buy orders > 70% of top 10 levels → BUY
  Sell orders > 70% of top 10 levels → SELL
  Fastest signal — fires before price moves
```

### Risk Rules

```
Per trade capital    : 20% of CAPITAL_USDT ($5 on $25)
Stop Loss            : -0.3% from entry
Take Profit          : +0.5% from entry
Risk/Reward          : 1 : 1.67
Max daily loss       : -$10 (bot pauses for the day)
Max open positions   : 1 at a time
Fee buffer           : 0.2% round-trip (0.1% buy + 0.1% sell)
```

### Expected Performance

| Metric | Estimate |
|--------|---------|
| Trades per day | 8–15 |
| Win rate target | 55–60% |
| Avg profit/win | +0.5% |
| Avg loss/loss | -0.3% |
| Daily PnL ($50 position) | $1.50–$3.00 |
| Monthly estimate | $45–$90 |

---

## Bot 2 — Grid Bot (COMPLETE)

**Status:** Built and working. Run on Testnet (paper mode).
**File:** `grid_bot.py`
**Best for:** Sideways / oscillating markets
**Target:** Grid spacing profit per cycle

### How It Works

Fetches live SOL price from Binance automatically on every startup.
Centers the grid ±GRID_RANGE around that live price. No manual price updates needed.

```
Startup auto-fetch example:
  Live SOL price  : $145.00 (fetched from Binance API)
  Grid range      : $135.00 – $155.00 (±$10)
  Levels          : 10  →  spacing = $2.00 per level
  Capital/level   : $25 / 10 = $2.50 per level

Grid layout:
  $155 ─── SELL
  $153 ─── SELL
  $151 ─── SELL
  $149 ─── SELL
  $147 ─── SELL
  ───── current price ~$145 ─────
  $143 ─── BUY
  $141 ─── BUY
  $139 ─── BUY
  $137 ─── BUY
  $135 ─── BUY

When price hits BUY level  → fill BUY → place SELL one level up → profit locked
When price hits SELL level → fill SELL → reload BUY one level down → ready again
```

### Architecture

```
grid_bot.py startup:
  client.get_symbol_ticker("SOLUSDT") → live price
  LOWER = price - GRID_RANGE
  UPPER = price + GRID_RANGE
  build_orders() → dict of {level: "BUY"/"SELL"}

data_stream.py → 1-min candles
on_candle():
  candle_low  <= BUY level  → BUY filled → set SELL above
  candle_high >= SELL level → SELL filled → reload BUY below
  profit per cycle = spacing * qty - fees

trade_logger.py → saves each cycle to trades.csv
```

### Config

```python
GRID_RANGE   = 10.0    # ±$10 around live price (auto-centered each startup)
GRID_LEVELS  = 10      # intervals (more = smaller spacing, more trades)
GRID_CAPITAL = 25.0    # USDT for grid bot
```

Tune: widen GRID_RANGE on volatile days, narrow on calm days.

### Expected Performance

| Metric | Estimate |
|--------|---------|
| Spacing (±$10, 10 levels) | $2.00 |
| Qty per level | ~0.017 SOL |
| Profit per cycle | ~$0.029 after fees |
| Cycles/day (active) | 10–30 |
| Daily estimate | $0.30–$0.90 |
| Monthly estimate | $9–$27 |

---

## Bot 3 — Moon Bot (DESIGN READY — TO BUILD NEXT)

**Status:** Design complete. Files not yet created.
**File to build:** `moon_engine.py` + supporting modules
**Best for:** Any day a random coin suddenly pumps 5–50%
**Target:** Catch coins early in a pump, ride momentum, exit before crash

### What Makes It Different

```
                 Scalping Bot    Grid Bot    Moon Bot
Pairs watched  : 1–2            1           200–500
Target profit  : 0.4–0.8%       spacing     5–50%
Trade speed    : seconds-min    cycles      minutes-hours
Risk level     : Low            Low         Higher
Signal type    : Volume/RSI/BB  Price lvl   Pump % detection
```

### How Moon Bot Works

```
Step 1 — Scanner
  Every 60 seconds, fetch price of all 200+ Binance USDT pairs
  Flag any coin where: price_change > +5% in last 5 min
                  AND: volume > 3x its 20-candle average

Step 2 — Filter (is the pump real?)
  Is this early in the pump? (not already 80% in)
  Is volume actually rising alongside price?
  Is the coin NOT on the blacklist?
  Is market cap not too tiny? (scam risk)

Step 3 — Entry
  Market BUY a fixed dollar amount ($15–25)
  Log entry price

Step 4 — Trailing Stop Exit
  Do NOT use fixed take profit — follow the price up
  Track highest price seen since entry (peak)
  Exit when: current price drops X% below peak

  Example:
    Buy  : $1.00
    Peak : $1.60  (price rose 60%)
    Drop : $1.52  (dropped 5% from peak)
    SELL : $1.52  → profit +52%

Step 5 — Blacklist
  After selling, ignore this coin for 4 hours
  Prevents re-buying a dead pump that bounces slightly
```

### Architecture (Files to Build)

```
moon_engine.py      ← main loop (like bot_engine.py but for moon bot)
pair_scanner.py     ← scans all USDT pairs every 60s for pumps
pump_filter.py      ← validates pump is real and early
trailing_stop.py    ← tracks peak price, fires exit signal
blacklist.py        ← 4-hour ignore list after selling
```

### Detection Logic (pair_scanner.py)

```python
# Concept — not final code
pairs = client.get_ticker()          # all USDT pairs, last 24h stats
for pair in pairs:
    price_change = pair["priceChangePercent"]   # % change last 24h
    # also check 5-min candle specifically for fresh pumps
    if float(price_change) > 5.0:
        candles   = get_last_candles(pair["symbol"], limit=5)
        vol_ratio = candles[-1]["volume"] / avg_volume(candles)
        if vol_ratio > 3.0:
            fire_entry_signal(pair["symbol"])
```

### Trailing Stop Logic (trailing_stop.py)

```python
# Concept
peak_price   = entry_price
trail_pct    = 0.05      # exit if price drops 5% from peak

def check_exit(current_price):
    global peak_price
    if current_price > peak_price:
        peak_price = current_price      # update peak
    drop_from_peak = (peak_price - current_price) / peak_price
    if drop_from_peak >= trail_pct:
        return "TRAILING_STOP"          # exit signal
    return None
```

### Risks to Know

| Risk | What happens | Mitigation |
|------|-------------|-----------|
| Pump and dump | Scammers pump bait bots, then dump | Only enter if volume is real AND pump is early |
| Buy too late | Enter after 80% of pump done — crash comes | Check: is pump < 3 min old? |
| Slippage | Tiny coins — your own buy order moves price | Only trade coins with decent volume |
| API rate limits | Scanning 500 pairs hits Binance limits | Add rate limiting + sleep between calls |
| Crash speed | Price can drop 30% in 10 seconds | Trailing stop must run every tick, not every candle |

### Expected Performance

| Metric | Estimate |
|--------|---------|
| Pumps detected per day | 3–10 |
| Win rate | 40–55% (higher risk) |
| Avg profit per win | 8–20% |
| Avg loss per loss | -5% (trailing stop) |
| Capital per trade | $15–25 |
| Daily estimate | $2–$8 on good days |

### Build Order

Build Moon Bot AFTER Scalping Bot and Grid Bot are profitable for 2+ weeks.
Reason: Moon Bot has higher risk. Need trading discipline first.

```
Phase 1: pair_scanner.py    — scan all pairs, print pumps to terminal (no trades)
Phase 2: pump_filter.py     — add filters, reduce false positives
Phase 3: trailing_stop.py   — add trailing exit logic
Phase 4: blacklist.py       — prevent re-entry on dead pumps
Phase 5: moon_engine.py     — tie everything together, paper trade
Phase 6: backtest           — test on 30 days historical data
Phase 7: go live            — $15 per trade, max 2 open at a time
```

---

## Bot Comparison

| Feature | Scalping Bot | Grid Bot | Moon Bot |
|---------|-------------|---------|---------|
| File | `bot_engine.py` | `grid_bot.py` | `moon_engine.py` |
| Status | Complete | Complete | To build |
| Strategy | Spike detection | Price levels | Pump detection |
| Best market | Trending/volatile | Sideways | Any (random coins) |
| Pairs | SOL/USDT | SOL/USDT | All USDT pairs |
| Profit target | +0.5%/trade | spacing/cycle | +5–50%/trade |
| Exit method | Fixed TP/SL | Grid level | Trailing stop |
| Risk level | Low | Low | Medium-High |
| Capital | $25 | $25 | $15–25/trade |
| Run together | Yes | Yes | Yes (own terminal) |

---

## Shared Infrastructure

```
data_stream.py    → WebSocket 1-min candle feed (Bot 1 + Bot 2 share this)
trade_logger.py   → CSV logger (all bots log to trades.csv)
config.py         → all settings for all bots
```

### Known Issue Fixed
**UnicodeEncodeError on Windows**: trade_logger.py was opening CSV without UTF-8 encoding.
Windows defaults to cp1252 which cannot handle arrow characters.
Fix applied: `open(LOG_FILE, "w", encoding="utf-8")` in trade_logger.py.
Do not revert this — it will break on any Windows machine.

---

## All Files

```
ScalpingBot/
├── ScalpingDesignSkill.md  ← this file (master knowledge doc)
├── config.py               ← all settings for all bots
├── data_stream.py          ← WebSocket live candle feed (shared)
├── spike_detector.py       ← 4-signal spike logic (Bot 1)
├── risk_manager.py         ← position size, SL/TP (Bot 1)
├── order_executor.py       ← place/cancel orders via API (Bot 1)
├── bot_engine.py           ← Scalping Bot main loop ✅ DONE
├── grid_bot.py             ← Grid Bot main loop ✅ DONE
├── trade_logger.py         ← logs all trades to CSV (shared) ✅ DONE
├── trades.csv              ← auto-generated trade log
│
├── moon_engine.py          ← Moon Bot main loop ← TO BUILD
├── pair_scanner.py         ← scan 200+ pairs for pumps ← TO BUILD
├── pump_filter.py          ← validate pump is real + early ← TO BUILD
├── trailing_stop.py        ← trail price up, exit on drop ← TO BUILD
├── blacklist.py            ← 4-hour ignore list ← TO BUILD
└── backtest.py             ← historical data testing ← TO BUILD
```

---

## Config Reference (config.py)

```python
# API
API_KEY / API_SECRET       ← Binance credentials

# Shared
PAIR           = "SOLUSDT"
MODE           = "paper"   # "paper" or "live"
INTERVAL       = "1m"
HISTORY_LIMIT  = 50

# Bot 1 — Scalping
CAPITAL_USDT       = 25.0
TAKE_PROFIT_PCT    = 0.005   # +0.5%
STOP_LOSS_PCT      = 0.003   # -0.3%
POSITION_SIZE_PCT  = 0.20    # 20% per trade
MAX_DAILY_LOSS_USD = 10.0
MIN_SIGNALS        = 2
VOLUME_MULTIPLIER  = 3.0
RSI_OVERSOLD       = 25
RSI_OVERBOUGHT     = 75
BB_PERIOD          = 20
BB_STD             = 2.0
ORDER_BOOK_RATIO   = 0.70

# Bot 2 — Grid
GRID_RANGE   = 10.0    # ±$10 auto-centered on live price
GRID_LEVELS  = 10
GRID_CAPITAL = 25.0

# Bot 3 — Moon (to add when building)
# MOON_PUMP_PCT     = 5.0    # minimum % pump to trigger scan
# MOON_VOL_MULT     = 3.0    # volume must be 3x average
# MOON_TRAIL_PCT    = 0.05   # exit on 5% drop from peak
# MOON_CAPITAL      = 20.0   # $ per moon trade
# MOON_BLACKLIST_HR = 4      # hours to ignore coin after selling
```

---

## API Key Setup

```
Binance → Profile → API Management → Create API
Label: "ScalpingBot"
Permissions:
  ✅ Enable Reading
  ✅ Enable Spot & Margin Trading
  ❌ Enable Withdrawals  ← NEVER enable this
IP restriction: add your PC's IP address
Keys stored in: config.py  (never commit to git)
```

---

## Build Phases (Current Status)

- [x] Phase 0 — Convert EURI + PEPE to USDT
- [x] Phase 1 — Install Python, libraries, API key
- [x] Phase 2 — data_stream.py (live WebSocket feed)
- [x] Phase 3 — spike_detector.py (4 signals)
- [x] Phase 4 — order_executor.py + risk_manager.py
- [x] Phase 5 — bot_engine.py (Scalping Bot complete)
- [x] Phase 6 — grid_bot.py (Grid Bot complete, auto price fetch)
- [ ] Phase 7 — Backtest both bots on 30 days historical data
- [ ] Phase 8 — Moon Bot: pair_scanner.py + pump_filter.py
- [ ] Phase 9 — Moon Bot: trailing_stop.py + blacklist.py + moon_engine.py
- [ ] Phase 10 — Go live with $25 (scalping) + $25 (grid) + $20 (moon)

---

*Created: 2026-06-28 | Updated: 2026-07-09*
*Status: Bot 1 + Bot 2 complete and tested. Bot 3 (Moon Bot) designed, ready to build.*
