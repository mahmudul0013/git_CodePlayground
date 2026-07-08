"""
Grid Bot — profits from price oscillating between fixed levels.
Run: python grid_bot.py

How it works:
  - Fetches current SOL price from Binance at startup automatically
  - Centers a grid of ±GRID_RANGE around that live price
  - Places BUY orders at levels BELOW current price
  - Places SELL orders at levels ABOVE current price
  - When a BUY fills  → places SELL one level above (locks in profit)
  - When a SELL fills → reloads BUY one level below (ready for next cycle)
  - Each completed BUY→SELL cycle = grid spacing profit minus fees
"""

import signal
import sys
from binance.client import Client
from colorama import Fore, Style, init

import config
from data_stream import DataStream
from trade_logger import TradeLogger

init(autoreset=True)

# ── Grid Parameters (LOWER/UPPER set at runtime from live price) ──────────────
LOWER    = None
UPPER    = None
LEVELS   = config.GRID_LEVELS
CAPITAL  = config.GRID_CAPITAL
FEE_RATE = 0.001   # 0.1% per trade (Binance spot fee with BNB discount)

# ── State ─────────────────────────────────────────────────────────────────────
pending      = {}    # {price_level: {"side": "BUY"/"SELL", "buy_at": float|None}}
total_profit = 0.0
total_cycles = 0
initialized  = False
_logger      = None


def _spacing():
    return (UPPER - LOWER) / LEVELS


def _qty(level):
    return round((CAPITAL / LEVELS) / level, 4)


def _build_orders(current_price):
    """BUY orders below current price, SELL orders above."""
    step   = _spacing()
    levels = [round(LOWER + i * step, 4) for i in range(LEVELS + 1)]
    orders = {}
    for lv in levels:
        if lv < current_price:
            orders[lv] = {"side": "BUY", "buy_at": None}
        elif lv > current_price:
            orders[lv] = {"side": "SELL", "buy_at": round(lv - step, 4)}
    return orders


def on_candle(df):
    global pending, total_profit, total_cycles, initialized

    candle_close = df["close"].iloc[-1]
    candle_low   = df["low"].iloc[-1]
    candle_high  = df["high"].iloc[-1]
    step         = _spacing()

    if not initialized:
        pending     = _build_orders(candle_close)
        initialized = True
        n_buys  = sum(1 for o in pending.values() if o["side"] == "BUY")
        n_sells = sum(1 for o in pending.values() if o["side"] == "SELL")
        print(f"  Grid initialised @ {candle_close:.4f}")
        print(f"  BUY  levels: {n_buys}  |  SELL levels: {n_sells}\n")

    filled = []

    for level, order in sorted(pending.items()):
        side = order["side"]

        # ── BUY triggered: candle dipped to or below this level ──────────────
        if side == "BUY" and candle_low <= level:
            sell_level = round(level + step, 4)
            if sell_level <= UPPER:
                pending[sell_level] = {"side": "SELL", "buy_at": level}

            qty    = _qty(level)
            gross  = (sell_level - level) * qty
            fees   = (level + sell_level) * qty * FEE_RATE
            profit = round(gross - fees, 6)

            total_profit += profit
            total_cycles += 1
            filled.append(level)

            _logger.log(
                pair=config.PAIR, mode=config.MODE,
                side="BUY",
                entry_price=level, exit_price=sell_level,
                quantity=qty,
                exit_reason="GRID_CYCLE",
                signals=f"Grid BUY@{level}->SELL@{sell_level}",
            )
            print(
                Fore.CYAN +
                f"\n  [BUY  FILLED] @ {level:.2f}  "
                f"→  SELL set @ {sell_level:.2f}  "
                f"Profit/cycle: ${profit:.4f}  "
                f"Total: ${total_profit:.4f}"
                + Style.RESET_ALL
            )

        # ── SELL triggered: candle rose to or above this level ───────────────
        elif side == "SELL" and candle_high >= level:
            buy_level = round(level - step, 4)
            if buy_level >= LOWER:
                pending[buy_level] = {"side": "BUY", "buy_at": None}
            filled.append(level)

            print(
                Fore.GREEN +
                f"\n  [SELL FILLED] @ {level:.2f}  "
                f"→  BUY  reload @ {buy_level:.2f}"
                + Style.RESET_ALL
            )

    for lv in filled:
        pending.pop(lv, None)

    n_buys  = sum(1 for o in pending.values() if o["side"] == "BUY")
    n_sells = sum(1 for o in pending.values() if o["side"] == "SELL")
    print(
        f"[GRID] Price: {candle_close:.4f}  "
        f"BUY: {n_buys}  SELL: {n_sells}  "
        f"Cycles: {total_cycles}  Profit: ${total_profit:.4f}  "
        f"Mode: {config.MODE.upper()}",
        end="\r",
    )


def _graceful_exit(sig, frame):
    n_buys  = sum(1 for o in pending.values() if o["side"] == "BUY")
    n_sells = sum(1 for o in pending.values() if o["side"] == "SELL")
    print(Fore.YELLOW + f"\n\n  Grid Bot stopped.")
    print(f"  Completed cycles : {total_cycles}")
    print(f"  Total profit     : ${total_profit:.4f}")
    print(f"  Open BUY orders  : {n_buys}")
    print(f"  Open SELL orders : {n_sells}")
    print(f"  Results saved    : trades.csv" + Style.RESET_ALL)
    sys.exit(0)


def main():
    global LOWER, UPPER, _logger
    signal.signal(signal.SIGINT, _graceful_exit)

    client = Client(config.API_KEY, config.API_SECRET)

    # ── Auto-fetch live SOL price and center grid around it ───────────────────
    ticker      = client.get_symbol_ticker(symbol=config.PAIR)
    spot_price  = float(ticker["price"])
    LOWER       = round(spot_price - config.GRID_RANGE, 2)
    UPPER       = round(spot_price + config.GRID_RANGE, 2)
    step        = (UPPER - LOWER) / LEVELS

    print(Fore.YELLOW + f"\n{'='*55}")
    print(f"  Grid Bot  |  {config.PAIR}  |  Mode: {config.MODE.upper()}")
    print(f"  Live price : ${spot_price:.4f}  (fetched from Binance)")
    print(f"  Grid range : ${LOWER:.2f} – ${UPPER:.2f}  (±${config.GRID_RANGE})")
    print(f"  Levels     : {LEVELS}  |  Spacing: ${step:.4f}")
    print(f"  Capital    : ${CAPITAL}  |  Per level: ${CAPITAL / LEVELS:.2f}")
    print(f"{'='*55}\n" + Style.RESET_ALL)

    _logger = TradeLogger()
    stream  = DataStream(client, on_candle)
    stream.start()


if __name__ == "__main__":
    main()
