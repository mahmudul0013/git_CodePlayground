import config


class RiskManager:
    """
    Controls position sizing, Stop Loss / Take Profit levels,
    and enforces the daily loss limit.
    """

    def __init__(self):
        self.daily_loss_usd = 0.0
        self.in_trade       = False
        self.entry_price    = None
        self.trade_side     = None   # "BUY" or "SELL"

    # ── Position sizing ───────────────────────────────────────────────────────

    def position_size_usd(self) -> float:
        """Returns the dollar amount to put into a single trade."""
        return round(config.CAPITAL_USDT * config.POSITION_SIZE_PCT, 2)

    # ── SL / TP prices ────────────────────────────────────────────────────────

    def levels(self, entry: float, side: str) -> dict:
        """Returns stop_loss and take_profit price for a given entry."""
        if side == "BUY":
            return {
                "take_profit": round(entry * (1 + config.TAKE_PROFIT_PCT), 4),
                "stop_loss":   round(entry * (1 - config.STOP_LOSS_PCT),   4),
            }
        else:  # SELL / SHORT
            return {
                "take_profit": round(entry * (1 - config.TAKE_PROFIT_PCT), 4),
                "stop_loss":   round(entry * (1 + config.STOP_LOSS_PCT),   4),
            }

    # ── Daily loss gate ───────────────────────────────────────────────────────

    def is_daily_limit_hit(self) -> bool:
        return self.daily_loss_usd >= config.MAX_DAILY_LOSS_USD

    def record_trade_result(self, pnl_usd: float):
        if pnl_usd < 0:
            self.daily_loss_usd += abs(pnl_usd)

    def reset_daily(self):
        self.daily_loss_usd = 0.0

    # ── Trade state ───────────────────────────────────────────────────────────

    def open_trade(self, price: float, side: str):
        self.in_trade    = True
        self.entry_price = price
        self.trade_side  = side

    def close_trade(self):
        self.in_trade    = False
        self.entry_price = None
        self.trade_side  = None

    def should_exit(self, current_price: float) -> str | None:
        """Returns 'take_profit', 'stop_loss', or None."""
        if not self.in_trade:
            return None

        lvl = self.levels(self.entry_price, self.trade_side)

        if self.trade_side == "BUY":
            if current_price >= lvl["take_profit"]:
                return "take_profit"
            if current_price <= lvl["stop_loss"]:
                return "stop_loss"
        else:
            if current_price <= lvl["take_profit"]:
                return "take_profit"
            if current_price >= lvl["stop_loss"]:
                return "stop_loss"

        return None
