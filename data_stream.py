import pandas as pd
from binance.client import Client
from binance import ThreadedWebsocketManager
import config


class DataStream:
    """
    Loads historical candles on startup then streams live 1-min klines via WebSocket.
    Calls `on_candle(df)` every time a candle closes.
    """

    def __init__(self, client: Client, on_candle):
        self.client    = client
        self.on_candle = on_candle
        self.df        = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        self.twm       = ThreadedWebsocketManager(
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
        )
        self._load_history()

    # ── Bootstrap with recent history ────────────────────────────────────────

    def _load_history(self):
        raw = self.client.get_klines(
            symbol=config.PAIR,
            interval=config.INTERVAL,
            limit=config.HISTORY_LIMIT,
        )
        rows = [
            {
                "open":   float(k[1]),
                "high":   float(k[2]),
                "low":    float(k[3]),
                "close":  float(k[4]),
                "volume": float(k[5]),
            }
            for k in raw
        ]
        self.df = pd.DataFrame(rows)
        print(f"[DataStream] Loaded {len(self.df)} historical candles for {config.PAIR}")

    # ── WebSocket handler ─────────────────────────────────────────────────────

    def _handle_message(self, msg):
        if msg.get("e") == "error":
            print(f"[DataStream] WebSocket error: {msg.get('m')}")
            return

        k = msg["k"]
        if not k["x"]:          # ignore open (unclosed) candles
            return

        new_row = {
            "open":   float(k["o"]),
            "high":   float(k["h"]),
            "low":    float(k["l"]),
            "close":  float(k["c"]),
            "volume": float(k["v"]),
        }

        self.df = pd.concat(
            [self.df, pd.DataFrame([new_row])],
            ignore_index=True,
        ).tail(config.HISTORY_LIMIT).reset_index(drop=True)

        self.on_candle(self.df.copy())

    # ── Start streaming ───────────────────────────────────────────────────────

    def start(self):
        print(f"[DataStream] Starting live stream -> {config.PAIR} {config.INTERVAL}")
        self.twm.start()
        self.twm.start_kline_socket(
            callback=self._handle_message,
            symbol=config.PAIR,
            interval=config.INTERVAL,
        )
        self.twm.join()

    def stop(self):
        self.twm.stop()
