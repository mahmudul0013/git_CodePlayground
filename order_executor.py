from binance.client import Client
from binance.exceptions import BinanceAPIException
import config


class OrderExecutor:
    """
    Places orders on Binance.
    MODE = "paper" → simulates trades with zero real orders.
    MODE = "live"  → places real market orders.
    """

    def __init__(self, client: Client):
        self.client = client

    # ── Entry order ───────────────────────────────────────────────────────────

    def enter(self, side: str, price: float, size_usd: float) -> dict:
        """
        side      : "BUY" or "SELL"
        price     : current market price
        size_usd  : dollar amount to trade
        Returns a trade dict with fill details.
        """
        quantity = round(size_usd / price, 4)

        if config.MODE == "paper":
            print(f"  [PAPER] {side} {quantity} {config.PAIR} @ {price:.4f}  (${size_usd})")
            return {
                "status":   "PAPER_FILLED",
                "side":     side,
                "quantity": quantity,
                "price":    price,
                "cost_usd": size_usd,
            }

        # Live order
        try:
            order = self.client.create_order(
                symbol=config.PAIR,
                side=Client.SIDE_BUY if side == "BUY" else Client.SIDE_SELL,
                type=Client.ORDER_TYPE_MARKET,
                quoteOrderQty=size_usd,   # buy $X worth — Binance handles qty
            )
            filled_price = float(order["fills"][0]["price"]) if order.get("fills") else price
            filled_qty   = float(order["executedQty"])
            print(f"  [LIVE] {side} {filled_qty} {config.PAIR} @ {filled_price:.4f}")
            return {
                "status":   "FILLED",
                "side":     side,
                "quantity": filled_qty,
                "price":    filled_price,
                "cost_usd": size_usd,
                "order_id": order["orderId"],
            }
        except BinanceAPIException as e:
            print(f"  [ERROR] Order failed: {e}")
            return {"status": "FAILED", "reason": str(e)}

    # ── Exit order ────────────────────────────────────────────────────────────

    def exit(self, side: str, quantity: float, price: float) -> dict:
        """
        side     : original entry side ("BUY" → exit is SELL, and vice versa)
        quantity : quantity held
        price    : current market price
        """
        exit_side = "SELL" if side == "BUY" else "BUY"

        if config.MODE == "paper":
            print(f"  [PAPER] EXIT {exit_side} {quantity} {config.PAIR} @ {price:.4f}")
            return {
                "status":   "PAPER_FILLED",
                "side":     exit_side,
                "quantity": quantity,
                "price":    price,
            }

        try:
            order = self.client.create_order(
                symbol=config.PAIR,
                side=Client.SIDE_SELL if exit_side == "SELL" else Client.SIDE_BUY,
                type=Client.ORDER_TYPE_MARKET,
                quantity=quantity,
            )
            filled_price = float(order["fills"][0]["price"]) if order.get("fills") else price
            print(f"  [LIVE] EXIT {exit_side} {quantity} {config.PAIR} @ {filled_price:.4f}")
            return {
                "status":   "FILLED",
                "side":     exit_side,
                "quantity": quantity,
                "price":    filled_price,
                "order_id": order["orderId"],
            }
        except BinanceAPIException as e:
            print(f"  [ERROR] Exit order failed: {e}")
            return {"status": "FAILED", "reason": str(e)}
