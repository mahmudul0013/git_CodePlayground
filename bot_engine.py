"""
Scalping Bot — Main Engine
Run:  python bot_engine.py
"""

from binance.client import Client
from colorama import Fore, Style, init

import config
from data_stream   import DataStream
from spike_detector import SpikeDetector
from risk_manager   import RiskManager
from order_executor import OrderExecutor
from trade_logger   import TradeLogger

init(autoreset=True)   # colorama

# ── State ─────────────────────────────────────────────────────────────────────
active_trade  = None   # holds entry details while in a trade
entry_signals = ""


def on_candle(df):
    """Called by DataStream every time a 1-min candle closes."""
    global active_trade, entry_signals

    current_price = df["close"].iloc[-1]

    # ── Check exit if in trade ────────────────────────────────────────────────
    if active_trade and risk.in_trade:
        exit_reason = risk.should_exit(current_price)
        if exit_reason:
            result = executor.exit(
                side=active_trade["side"],
                quantity=active_trade["quantity"],
                price=current_price,
            )
            pnl = logger.log(
                pair=config.PAIR,
                mode=config.MODE,
                side=active_trade["side"],
                entry_price=active_trade["price"],
                exit_price=current_price,
                quantity=active_trade["quantity"],
                exit_reason=exit_reason,
                signals=entry_signals,
            )
            risk.record_trade_result(pnl)
            risk.close_trade()
            active_trade = None

            colour = Fore.GREEN if pnl >= 0 else Fore.RED
            print(
                f"{colour}  [EXIT] [{exit_reason.upper()}]  "
                f"PnL: {'+'if pnl>=0 else ''}{pnl:.4f} USD  "
                f"Daily loss: ${risk.daily_loss_usd:.2f}{Style.RESET_ALL}"
            )

            if risk.is_daily_limit_hit():
                print(Fore.RED + "  [!!] Daily loss limit hit - bot paused for today.")
            return

    # ── Skip new entry if already in trade or daily limit hit ────────────────
    if active_trade or risk.is_daily_limit_hit():
        _status_line(current_price, df)
        return

    # ── Run spike detector ────────────────────────────────────────────────────
    detection = detector.analyse(df)
    _status_line(current_price, df, detection)

    if detection["signal"] is None:
        return

    # ── Enter trade ───────────────────────────────────────────────────────────
    size_usd = risk.position_size_usd()
    result   = executor.enter(
        side=detection["signal"],
        price=current_price,
        size_usd=size_usd,
    )

    if result["status"] in ("PAPER_FILLED", "FILLED"):
        active_trade  = result
        entry_signals = detection["reason"]
        risk.open_trade(current_price, detection["signal"])
        lvl = risk.levels(current_price, detection["signal"])

        colour = Fore.CYAN if detection["signal"] == "BUY" else Fore.YELLOW
        print(
            f"\n{colour}  [ENTRY] {detection['signal']} @ {current_price:.4f}"
            f"  TP: {lvl['take_profit']}  SL: {lvl['stop_loss']}"
            f"\n    Signals: {detection['reason']}{Style.RESET_ALL}\n"
        )


def _status_line(price, df, detection=None):
    rsi = detection["rsi"] if detection else "-"
    vol = detection["volume_ratio"] if detection else "-"
    sig = (detection.get("signal") or "none") if detection else "in_trade"
    print(
        f"[{config.PAIR}]  Price: {price:.4f}  "
        f"RSI: {rsi}  Vol*: {vol}  "
        f"Signal: {sig}  "
        f"Mode: {config.MODE.upper()}",
        end="\r",
    )


# ── Boot ──────────────────────────────────────────────────────────────────────

def main():
    print(Fore.YELLOW + f"\n{'='*55}")
    print(f"  Scalping Bot  |  {config.PAIR}  |  Mode: {config.MODE.upper()}")
    print(f"  Capital: ${config.CAPITAL_USDT}  |  Per trade: ${config.CAPITAL_USDT * config.POSITION_SIZE_PCT}")
    print(f"  TP: +{config.TAKE_PROFIT_PCT*100}%   SL: -{config.STOP_LOSS_PCT*100}%")
    print(f"{'='*55}\n" + Style.RESET_ALL)

    global risk, executor, detector, logger
    client   = Client(config.API_KEY, config.API_SECRET)
    risk     = RiskManager()
    executor = OrderExecutor(client)
    detector = SpikeDetector()
    logger   = TradeLogger()
    stream   = DataStream(client, on_candle)

    try:
        stream.start()
    except KeyboardInterrupt:
        stream.stop()
        print(Fore.YELLOW + "\n  Bot stopped by user. Check trades.csv for results.")


if __name__ == "__main__":
    main()
