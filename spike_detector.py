import pandas as pd
import ta
import config


class SpikeDetector:
    """
    Analyses a DataFrame of OHLCV candles and fires BUY / SELL signals.
    Requires at least MIN_SIGNALS of 4 signals to agree before returning a signal.

    Signals:
        1. Volume Spike      — volume 3x the 20-candle average
        2. Bollinger Bands   — price closes outside the bands
        3. RSI Extreme       — RSI drops below 25 or rises above 75
        4. Price Momentum    — strong 1-candle move confirms the direction
    """

    def analyse(self, df: pd.DataFrame) -> dict:
        if len(df) < config.BB_PERIOD + 2:
            return {"signal": None, "reason": "not enough candles"}

        df = df.copy()
        signals_buy  = []
        signals_sell = []

        # ── Signal 1: Volume Spike ────────────────────────────────────────────
        avg_volume    = df["volume"].iloc[:-1].rolling(20).mean().iloc[-1]
        last_volume   = df["volume"].iloc[-1]
        last_close    = df["close"].iloc[-1]
        prev_close    = df["close"].iloc[-2]
        price_change  = (last_close - prev_close) / prev_close

        volume_spiked = last_volume > avg_volume * config.VOLUME_MULTIPLIER
        if volume_spiked:
            if price_change > 0.003:
                signals_buy.append("volume_spike")
            elif price_change < -0.003:
                signals_sell.append("volume_spike")

        # ── Signal 2: Bollinger Band Breakout ────────────────────────────────
        bb = ta.volatility.BollingerBands(
            close=df["close"],
            window=config.BB_PERIOD,
            window_dev=config.BB_STD,
        )
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]

        if last_close < bb_lower:
            signals_buy.append("bb_lower_break")
        elif last_close > bb_upper:
            signals_sell.append("bb_upper_break")

        # ── Signal 3: RSI Extreme ─────────────────────────────────────────────
        rsi = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi()
        rsi_now  = rsi.iloc[-1]
        rsi_prev = rsi.iloc[-2]

        if rsi_now < config.RSI_OVERSOLD:
            signals_buy.append("rsi_oversold")
        elif rsi_now > config.RSI_OVERBOUGHT:
            signals_sell.append("rsi_overbought")

        # ── Signal 4: Price Momentum Confirmation ─────────────────────────────
        # Strong single-candle body (close vs open) as confirmation
        last_open  = df["open"].iloc[-1]
        candle_body = (last_close - last_open) / last_open

        if candle_body > 0.003:
            signals_buy.append("momentum_up")
        elif candle_body < -0.003:
            signals_sell.append("momentum_down")

        # ── Decision ──────────────────────────────────────────────────────────
        buy_count  = len(signals_buy)
        sell_count = len(signals_sell)

        result = {
            "signal":      None,
            "buy_signals":  signals_buy,
            "sell_signals": signals_sell,
            "rsi":          round(rsi_now, 2),
            "price":        last_close,
            "volume_ratio": round(last_volume / avg_volume, 2) if avg_volume > 0 else 0,
        }

        if buy_count >= config.MIN_SIGNALS and buy_count > sell_count:
            result["signal"] = "BUY"
            result["reason"] = " + ".join(signals_buy)
        elif sell_count >= config.MIN_SIGNALS and sell_count > buy_count:
            result["signal"] = "SELL"
            result["reason"] = " + ".join(signals_sell)
        else:
            result["reason"] = f"weak signal — buy:{buy_count} sell:{sell_count}"

        return result
