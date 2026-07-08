import csv
import os
from datetime import datetime

LOG_FILE = os.path.join(os.path.dirname(__file__), "trades.csv")

HEADERS = [
    "timestamp", "pair", "mode", "side",
    "entry_price", "exit_price", "quantity",
    "pnl_usd", "pnl_pct", "exit_reason", "signals",
]


class TradeLogger:

    def __init__(self):
        if not os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=HEADERS).writeheader()

    def log(
        self,
        pair: str,
        mode: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        exit_reason: str,
        signals: str,
    ):
        if side == "BUY":
            pnl_usd = (exit_price - entry_price) * quantity
        else:
            pnl_usd = (entry_price - exit_price) * quantity

        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        if side == "SELL":
            pnl_pct = -pnl_pct

        row = {
            "timestamp":   datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "pair":        pair,
            "mode":        mode,
            "side":        side,
            "entry_price": entry_price,
            "exit_price":  exit_price,
            "quantity":    quantity,
            "pnl_usd":     round(pnl_usd, 4),
            "pnl_pct":     round(pnl_pct, 3),
            "exit_reason": exit_reason,
            "signals":     signals,
        }

        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=HEADERS).writerow(row)

        return pnl_usd
