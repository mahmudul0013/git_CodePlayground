# ── API Credentials ──────────────────────────────────────────────────────────
API_KEY    = "V98tAYa94kUuHX8UImHRklyLBNU6bbUaFVz59ReP7w6ssv1Emq7cyRikW0qOa67I"
API_SECRET = "pAz00h9AP9Ajz3S3eqNj7ycWbh59WwvPOEHE2RrJxrALrjKrsZvnfs72KpUD3nhb"

# ── Trading Settings ─────────────────────────────────────────────────────────
PAIR           = "SOLUSDT"   # trading pair
CAPITAL_USDT   = 25.0        # total capital allocated to this bot (USD)
MODE           = "paper"     # "paper" = simulate only | "live" = real orders

# ── Risk Rules ────────────────────────────────────────────────────────────────
TAKE_PROFIT_PCT    = 0.005   # exit trade at +0.5% profit
STOP_LOSS_PCT      = 0.003   # exit trade at -0.3% loss
POSITION_SIZE_PCT  = 0.20    # use 20% of capital per trade ($5 on $25 capital)
MAX_DAILY_LOSS_USD = 10.0    # bot stops for the day if loss exceeds this

# ── Signal Thresholds ─────────────────────────────────────────────────────────
MIN_SIGNALS        = 2       # need at least 2 of 4 signals to agree before trading
VOLUME_MULTIPLIER  = 3.0     # volume must be 3x the 20-candle average
RSI_OVERSOLD       = 25      # RSI below this → buy signal
RSI_OVERBOUGHT     = 75      # RSI above this → sell signal
BB_PERIOD          = 20      # Bollinger Bands period
BB_STD             = 2.0     # Bollinger Bands standard deviation
ORDER_BOOK_RATIO   = 0.70    # 70%+ buy or sell side → imbalance signal

# ── Candle Interval ───────────────────────────────────────────────────────────
INTERVAL      = "1m"         # 1-minute candles for scalping
HISTORY_LIMIT = 50           # how many past candles to load on startup

# ── Grid Bot Settings ─────────────────────────────────────────────────────────
# Grid auto-centers on live SOL price at startup — no manual price changes needed
GRID_RANGE   = 10.0    # grid spans ±$10 around current price (auto-fetched from Binance)
GRID_LEVELS  = 10      # number of grid intervals (more = smaller spacing, more trades)
GRID_CAPITAL = 25.0    # USDT capital dedicated to grid bot
