"""
Momentum / Breakout Strategy
Ported from python-trade/pro_scalping_system.py lines 4135-4250
EMA crossover + RSI confirmation + ATR-based TP/SL
"""
from __future__ import annotations
from typing import List
import pandas as pd

from .base import BaseStrategy, OrderSignal
from ..core.smc import SMCResult


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    DEFAULT_PARAMS = {
        "fast_ema": 8,
        "slow_ema": 21,
        "rsi_bull": 55.0,
        "rsi_bear": 45.0,
        "atr_tp_mult": 2.0,
        "atr_sl_mult": 1.5,
        "cooldown_bars": 5,
    }

    def __init__(
        self,
        symbol: str,
        base_lot: float = 0.001,
        fast_ema: int = 8,
        slow_ema: int = 21,
        rsi_bull: float = 55.0,
        rsi_bear: float = 45.0,
        atr_tp_mult: float = 2.0,
        atr_sl_mult: float = 1.5,
        cooldown_bars: int = 5,
    ) -> None:
        super().__init__(symbol, base_lot)
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.rsi_bull = rsi_bull
        self.rsi_bear = rsi_bear
        self.atr_tp_mult = atr_tp_mult
        self.atr_sl_mult = atr_sl_mult
        self.cooldown_bars = cooldown_bars

        self._last_signal_bar: int = -cooldown_bars
        self._bar_count: int = 0

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

        # Cooldown check
        if self._bar_count - self._last_signal_bar < self.cooldown_bars:
            return signals

        ind = indicators.get("last", {})
        ema8 = ind.get("ema8", current_price)
        ema21 = ind.get("ema21", current_price)
        rsi = ind.get("rsi", 50.0)
        atr = ind.get("atr", current_price * 0.001)

        # Check for EMA crossover using last 2 candles
        ema8_arr = indicators.get("ema8")
        ema21_arr = indicators.get("ema21")

        if ema8_arr is None or ema21_arr is None or len(ema8_arr) < 2:
            return signals

        prev_diff = ema8_arr[-2] - ema21_arr[-2]
        curr_diff = ema8_arr[-1] - ema21_arr[-1]

        bullish_cross = prev_diff <= 0 < curr_diff
        bearish_cross = prev_diff >= 0 > curr_diff

        # Bullish: EMA crossover + RSI > rsi_bull + SMC bias bullish
        if bullish_cross and rsi >= self.rsi_bull and smc.bias != "BEARISH":
            tp = current_price + atr * self.atr_tp_mult
            sl = current_price - atr * self.atr_sl_mult
            self._last_signal_bar = self._bar_count
            signals.append(
                OrderSignal(
                    strategy=self.name,
                    side="BUY",
                    quantity=self.base_lot,
                    entry_price=current_price,
                    stop_loss=sl,
                    take_profit=tp,
                    reason=f"Bullish EMA cross RSI={rsi:.0f}",
                )
            )

        # Bearish: EMA crossover + RSI < rsi_bear + SMC bias bearish
        elif bearish_cross and rsi <= self.rsi_bear and smc.bias != "BULLISH":
            tp = current_price - atr * self.atr_tp_mult
            sl = current_price + atr * self.atr_sl_mult
            self._last_signal_bar = self._bar_count
            signals.append(
                OrderSignal(
                    strategy=self.name,
                    side="SELL",
                    quantity=self.base_lot,
                    entry_price=current_price,
                    stop_loss=sl,
                    take_profit=tp,
                    reason=f"Bearish EMA cross RSI={rsi:.0f}",
                )
            )

        return signals

    def dump_state(self) -> dict:
        return {
            "last_signal_bar": self._last_signal_bar,
            "bar_count": self._bar_count,
        }

    def load_state(self, state: dict) -> None:
        self._last_signal_bar = state.get("last_signal_bar", -self.cooldown_bars)
        self._bar_count = state.get("bar_count", 0)
