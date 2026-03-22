"""
Smart Martingale Strategy with Zone Recovery
Ported from python-trade/pro_scalping_system.py lines 4432-4700
"""
from __future__ import annotations
from typing import List
import pandas as pd

from .base import BaseStrategy, OrderSignal, StrategyState
from ..core.smc import SMCResult, check_entry_near_ob
from ..core.indicators import calculate_ema


class MartingaleStrategy(BaseStrategy):
    name = "martingale"

    def __init__(
        self,
        symbol: str,
        base_lot: float = 0.001,
        multiplier: float = 1.5,
        max_levels: int = 7,
        pip_distance: float = 30.0,   # pip distance between levels
        take_profit_pips: float = 35.0,
        pip_value: float = 0.01,      # BTCUSDT: 1 pip = $1
    ) -> None:
        super().__init__(symbol, base_lot)
        self.multiplier = multiplier
        self.max_levels = max_levels
        self.pip_distance = pip_distance
        self.take_profit_pips = take_profit_pips
        self.pip_value = pip_value

        self._direction: str | None = None
        self._entry_prices: List[float] = []
        self._levels: int = 0

    def _determine_direction(self, smc: SMCResult, indicators: dict) -> str | None:
        """Use SMC bias + EMA alignment to choose BUY/SELL."""
        ind = indicators.get("last", {})
        ema8 = ind.get("ema8", 0)
        ema21 = ind.get("ema21", 0)
        rsi = ind.get("rsi", 50)

        bull_score = 0
        bear_score = 0

        if smc.bias == "BULLISH":
            bull_score += 3
        elif smc.bias == "BEARISH":
            bear_score += 3

        if ema8 > ema21:
            bull_score += 2
        else:
            bear_score += 2

        if rsi > 55:
            bull_score += 1
        elif rsi < 45:
            bear_score += 1

        if bull_score > bear_score:
            return "BUY"
        elif bear_score > bull_score:
            return "SELL"
        return None

    def _lot_for_level(self, level: int) -> float:
        return round(self.base_lot * (self.multiplier ** min(level, self.max_levels - 1)), 6)

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

        # No open positions — look for initial entry
        if not self._entry_prices:
            direction = self._determine_direction(smc, indicators)
            if direction is None:
                return signals

            # Require near Order Block for entry
            if not check_entry_near_ob(current_price, smc.order_blocks, direction, self.pip_value):
                return signals

            self._direction = direction
            self._levels = 0
            tp = (
                current_price + self.take_profit_pips * self.pip_value
                if direction == "BUY"
                else current_price - self.take_profit_pips * self.pip_value
            )
            signals.append(
                OrderSignal(
                    strategy=self.name,
                    side=direction,
                    quantity=self._lot_for_level(0),
                    entry_price=current_price,
                    take_profit=tp,
                    level=0,
                    reason="SMC+OB initial entry",
                )
            )
            self._entry_prices.append(current_price)
            return signals

        # Already have open positions — check if need to add (martingale)
        if not self._direction or self._levels >= self.max_levels - 1:
            return signals

        last_price = self._entry_prices[-1]
        distance = (
            (last_price - current_price) / self.pip_value
            if self._direction == "BUY"
            else (current_price - last_price) / self.pip_value
        )

        if distance >= self.pip_distance:
            self._levels += 1
            lot = self._lot_for_level(self._levels)
            tp = (
                current_price + self.take_profit_pips * self.pip_value
                if self._direction == "BUY"
                else current_price - self.take_profit_pips * self.pip_value
            )
            signals.append(
                OrderSignal(
                    strategy=self.name,
                    side=self._direction,
                    quantity=lot,
                    entry_price=current_price,
                    take_profit=tp,
                    level=self._levels,
                    reason=f"Martingale level {self._levels}",
                )
            )
            self._entry_prices.append(current_price)

        return signals

    def reset(self) -> None:
        self._direction = None
        self._entry_prices = []
        self._levels = 0
