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

    DEFAULT_PARAMS = {
        "grid_spacing_pips": 200.0,    # $200 spacing — covers round-trip commission + profit
        "take_profit_pips": 200.0,     # TP = 1 grid level above entry
        "max_orders": 6,               # Max 6 open grid orders
        "pip_value": 1.0,              # BTCUSDT: 1 pip = $1 USDT
        "max_adverse_levels": 4,       # Close all if price moves 4 levels against grid
    }

    def __init__(
        self,
        symbol: str,
        base_lot: float = 0.001,
        grid_spacing_pips: float = 200.0,
        take_profit_pips: float = 200.0,
        max_orders: int = 6,
        pip_value: float = 1.0,
        max_adverse_levels: int = 4,   # Safety: stop adding if too many adverse levels
    ) -> None:
        super().__init__(symbol, base_lot)
        self.grid_spacing_pips = grid_spacing_pips
        self.take_profit_pips = take_profit_pips
        self.max_orders = max_orders
        self.pip_value = pip_value
        self.max_adverse_levels = max_adverse_levels
        self.grid_spacing = grid_spacing_pips * pip_value
        self.take_profit = take_profit_pips * pip_value

        self._grid_center: float | None = None
        self._placed_levels: Set[int] = set()

    def update_params(self, params: dict) -> None:
        """Override to recalculate derived attributes after param update."""
        super().update_params(params)
        self.grid_spacing = self.grid_spacing_pips * self.pip_value
        self.take_profit = self.take_profit_pips * self.pip_value

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

        # Store indicators for direction logic
        self._last_indicators = indicators

        # Initialize grid center on first run
        if self._grid_center is None:
            self._grid_center = current_price

        level = self._price_to_level(current_price)

        # Safety: stop adding adverse levels beyond max_adverse_levels
        # (prevents runaway losses in strong trends)
        adverse = sum(1 for lvl in self._placed_levels
                      if (lvl < 0))   # BUY levels below center = adverse if price keeps falling
        if abs(level) > self.max_adverse_levels:
            return signals

        # Check if we've exceeded max orders
        if len(self._placed_levels) >= self.max_orders:
            return signals

        # Only place a new order if this level hasn't been used
        if level not in self._placed_levels:
            # Check trading session using bar timestamp (London/NY: 07:00-22:00 UTC)
            try:
                bar_hour = int(df.index[-1].hour)
            except Exception:
                from datetime import datetime, timezone
                bar_hour = datetime.now(timezone.utc).hour
            if not (7 <= bar_hour < 22):
                return signals

            # Grid direction: lean WITH trend
            # In uptrend (ST=1): only BUY (buy dips), in downtrend (ST=-1): only SELL (sell bounces)
            # In neutral/ranging: original symmetric behavior
            _ind = indicators.get("last", {})
            st_dir = _ind.get("st_direction", 0)
            if st_dir == 1:
                side = "BUY"   # only buy the dips in uptrend
            elif st_dir == -1:
                side = "SELL"  # only sell the bounces in downtrend
            else:
                side = "BUY" if level <= 0 else "SELL"  # symmetric in ranging

            tp_price = (
                current_price + self.take_profit if side == "BUY" else current_price - self.take_profit
            )
            # SL = same distance as TP → 1:1 R:R minimum
            # Break-even WR = 50%. Grid in ranging should exceed this.
            sl_price = (
                current_price - self.take_profit if side == "BUY"
                else current_price + self.take_profit
            )

            self._placed_levels.add(level)
            signals.append(
                OrderSignal(
                    strategy=self.name,
                    side=side,
                    quantity=self.base_lot,
                    entry_price=current_price,
                    stop_loss=sl_price,
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

    def dump_state(self) -> dict:
        return {
            "grid_center": self._grid_center,
            "placed_levels": list(self._placed_levels),
        }

    def load_state(self, state: dict) -> None:
        self._grid_center = state.get("grid_center")
        self._placed_levels = set(state.get("placed_levels", []))
