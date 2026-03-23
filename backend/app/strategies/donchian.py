"""
Donchian Channel Breakout Strategy
Classic Turtle Trader breakout — proven profitable across all liquid markets.

Entry:  price CLOSES above N-bar high (BUY) or below N-bar low (SELL)
SL:     opposite Donchian band + ATR buffer
TP:     SL-distance × tp_mult (default 2:1 R:R)
Filters:
  - ADX > 20 (confirms trend strength, not choppy range)
  - EMA200 direction (only BUY above, SELL below)
  - 7-day macro trend (no BUY in sustained downtrend)
  - Volume > 1.1× 20-bar avg (confirms genuine breakout)
"""
from __future__ import annotations
from typing import List
import numpy as np
import pandas as pd

from .base import BaseStrategy, OrderSignal
from ..core.smc import SMCResult


class DonchianStrategy(BaseStrategy):
    name = "donchian"

    DEFAULT_PARAMS = {
        "channel_period": 96,       # 96 × 15m = 24-hour channel (classic Turtle Traders use daily)
        "atr_tp_mult": 2.0,         # TP = 2× SL distance
        "atr_sl_mult": 0.5,         # Extra ATR buffer beyond channel edge
        "min_break_atr": 0.25,      # Close must exceed channel by at least 0.25 ATR (filters noise)
        "cooldown_bars": 10,        # 10 × 15m = 2.5h cooldown (one entry per breakout)
        "adx_min": 22.0,            # Only trade in trending conditions
        "require_volume": True,
        "volume_mult": 1.1,         # Volume must be > 1.1× 20-bar avg
        "use_partial_tp": True,     # 50% at 1R, 50% at 2R
        "trailing_stop": True,
    }

    def __init__(
        self,
        symbol: str,
        base_lot: float = 0.001,
        channel_period: int = 96,
        atr_tp_mult: float = 2.0,
        atr_sl_mult: float = 0.5,
        min_break_atr: float = 0.25,
        cooldown_bars: int = 10,
        adx_min: float = 22.0,
        require_volume: bool = True,
        volume_mult: float = 1.1,
        use_partial_tp: bool = True,
        trailing_stop: bool = True,
    ) -> None:
        super().__init__(symbol, base_lot)
        self.channel_period = channel_period
        self.atr_tp_mult    = atr_tp_mult
        self.atr_sl_mult    = atr_sl_mult
        self.min_break_atr  = min_break_atr
        self.cooldown_bars  = cooldown_bars
        self.adx_min        = adx_min
        self.require_volume = require_volume
        self.volume_mult    = volume_mult
        self.use_partial_tp = use_partial_tp
        self.trailing_stop  = trailing_stop

        self._bar_count: int = 0
        self._last_signal_bar: int = -cooldown_bars

    async def evaluate(
        self,
        df: pd.DataFrame,
        smc: SMCResult,
        indicators: dict,
        current_price: float,
    ) -> List[OrderSignal]:
        signals: List[OrderSignal] = []

        if not self.state.active:
            return signals

        self._bar_count += 1

        # Cooldown — one entry per breakout move
        if self._bar_count - self._last_signal_bar < self.cooldown_bars:
            return signals

        # Need channel_period + 2 bars to avoid look-ahead
        if len(df) < self.channel_period + 3:
            return signals

        ind  = indicators.get("last", {})
        atr  = ind.get("atr", current_price * 0.001)
        adx  = ind.get("adx", 0.0)
        ema200 = ind.get("ema200", current_price)

        # ── ADX filter ───────────────────────────────────────────
        if adx < self.adx_min:
            return signals

        # ── Volume confirmation ───────────────────────────────────
        if self.require_volume:
            vol_arr = indicators.get("volume")
            if vol_arr is not None and len(vol_arr) >= 20:
                vol_avg = float(np.mean(vol_arr[-20:]))
                if vol_avg > 0 and float(vol_arr[-1]) < vol_avg * self.volume_mult:
                    return signals

        # ── Donchian channel (no look-ahead: use bars[-channel_period-1:-1]) ─
        high_arr = df["high"].values.astype(float)
        low_arr  = df["low"].values.astype(float)

        channel_highs = high_arr[-self.channel_period - 1:-1]
        channel_lows  = low_arr[-self.channel_period - 1:-1]
        chan_high = float(np.max(channel_highs))
        chan_low  = float(np.min(channel_lows))

        # Breakout: current close crossed the channel boundary
        # AND must exceed it by at least min_break_atr to filter noise
        prev_close = float(df["close"].iloc[-2])
        curr_close = float(df["close"].iloc[-1])
        min_break  = atr * self.min_break_atr

        bullish_break = prev_close <= chan_high and curr_close > chan_high + min_break
        bearish_break = prev_close >= chan_low  and curr_close < chan_low  - min_break

        if not bullish_break and not bearish_break:
            return signals

        # ── Macro + SMC bias confluence ──────────────────────────────
        macro_7d   = ind.get("macro_trend_7d", 0)
        macro_3d   = ind.get("macro_trend_3d", 0)
        smc_bias   = getattr(smc, "bias", "NEUTRAL")

        # ── EMA200 trend filter + signal construction ─────────────
        if bullish_break and current_price > ema200:
            if macro_7d == -1 and macro_3d == -1:
                return signals  # sustained downtrend — skip BUY
            if smc_bias == "BEARISH":
                return signals  # structure is bearish — skip BUY breakout

            # SL = channel low − ATR buffer, CAPPED at 1.5 ATR from entry
            # Without cap: SL could be $6K away on 24hr channel → catastrophic loss on reversals
            sl_structure = chan_low - atr * self.atr_sl_mult
            sl_atr_cap   = current_price - atr * 1.5
            sl = max(sl_structure, sl_atr_cap)   # use the CLOSER (less risky) one
            sl_dist = max(current_price - sl, atr * 0.5)
            tp = current_price + sl_dist * self.atr_tp_mult

            partial_tps = (
                self.build_partial_tps("BUY", current_price, sl, atr)
                if self.use_partial_tp else []
            )
            full_tp = None if self.use_partial_tp else tp

            self._last_signal_bar = self._bar_count
            signals.append(OrderSignal(
                strategy=self.name,
                side="BUY",
                quantity=self.base_lot,
                entry_price=current_price,
                stop_loss=sl,
                take_profit=full_tp,
                reason=f"Donchian BUY break ch={chan_high:.0f} ADX={adx:.0f}",
                partial_tps=partial_tps,
                atr=atr,
            ))

        elif bearish_break and current_price < ema200:
            if macro_7d == 1 and macro_3d == 1:
                return signals  # sustained uptrend — skip SELL
            if smc_bias == "BULLISH":
                return signals  # structure is bullish — skip SELL breakout

            # SL = channel high + ATR buffer, CAPPED at 1.5 ATR from entry
            sl_structure = chan_high + atr * self.atr_sl_mult
            sl_atr_cap   = current_price + atr * 1.5
            sl = min(sl_structure, sl_atr_cap)   # use the CLOSER (less risky) one
            sl_dist = max(sl - current_price, atr * 0.5)
            tp = current_price - sl_dist * self.atr_tp_mult

            partial_tps = (
                self.build_partial_tps("SELL", current_price, sl, atr)
                if self.use_partial_tp else []
            )
            full_tp = None if self.use_partial_tp else tp

            self._last_signal_bar = self._bar_count
            signals.append(OrderSignal(
                strategy=self.name,
                side="SELL",
                quantity=self.base_lot,
                entry_price=current_price,
                stop_loss=sl,
                take_profit=full_tp,
                reason=f"Donchian SELL break ch={chan_low:.0f} ADX={adx:.0f}",
                partial_tps=partial_tps,
                atr=atr,
            ))

        return signals

    def reset(self) -> None:
        self._bar_count = 0
        self._last_signal_bar = -self.cooldown_bars

    def dump_state(self) -> dict:
        return {
            "bar_count": self._bar_count,
            "last_signal_bar": self._last_signal_bar,
        }

    def load_state(self, state: dict) -> None:
        self._bar_count      = state.get("bar_count", 0)
        self._last_signal_bar = state.get("last_signal_bar", -self.cooldown_bars)
