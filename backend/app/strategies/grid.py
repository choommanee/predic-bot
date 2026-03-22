"""
Grid Bot Strategy
Ported from python-trade/pro_scalping_system.py lines 4000-4130
"""
from __future__ import annotations
from typing import List, Set
import pandas as pd

from .base import BaseStrategy, OrderSignal
from ..core.smc import SMCResult


class GridStrategy(BaseStrategy):
    name = "grid"

    def __init__(
        self,
        symbol: str,
        base_lot: float = 0.001,
        grid_spacing_pips: float = 50.0,
        take_profit_pips: float = 50.0,
        max_orders: int = 8,
        pip_value: float = 1.0,  # BTCUSDT: ~$1 per pip (1 pip = $1 USDT)
    ) -> None:
        super().__init__(symbol, base_lot)
        self.grid_spacing = grid_spacing_pips * pip_value
        self.take_profit = take_profit_pips * pip_value
        self.max_orders = max_orders

        self._grid_center: float | None = None
        self._placed_levels: Set[int] = set()

    def _price_to_level(self, price: float) -> int:
        if self._grid_center is None:
            return 0
        return round((price - self._grid_center) / self.grid_spacing)

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

        # Initialize grid center on first run
        if self._grid_center is None:
            self._grid_center = current_price

        level = self._price_to_level(current_price)

        # Check if we've exceeded max orders
        if len(self._placed_levels) >= self.max_orders:
            return signals

        # Only place a new order if this level hasn't been used
        if level not in self._placed_levels:
            # Check trading session (London/NY: 08:00-22:00 UTC)
            from datetime import datetime, timezone
            hour = datetime.now(timezone.utc).hour
            if not (8 <= hour < 22):
                return signals

            # Grid: place BUY below center, SELL above center
            side = "BUY" if level <= 0 else "SELL"

            tp_price = (
                current_price + self.take_profit if side == "BUY" else current_price - self.take_profit
            )

            self._placed_levels.add(level)
            signals.append(
                OrderSignal(
                    strategy=self.name,
                    side=side,
                    quantity=self.base_lot,
                    entry_price=current_price,
                    take_profit=tp_price,
                    level=abs(level),
                    reason=f"Grid level {level}",
                )
            )

        return signals

    def on_close(self, pnl: float) -> None:
        super().on_close(pnl)
        # When a grid order closes (TP hit), mark level as available again
        if self._placed_levels:
            self._placed_levels.discard(min(self._placed_levels))

    def reset(self) -> None:
        self._grid_center = None
        self._placed_levels = set()
