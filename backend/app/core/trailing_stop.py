"""
Trailing Stop Manager
Tracks open trades and updates SL as price moves in favor.

Modes:
  - ATR-based : trail by N × ATR (adapts to volatility)
  - Fixed pips: trail by fixed pip distance
  - Percentage: trail by % of price

Works with both paper and live modes.
Activated after price moves min_activation_r × ATR from entry.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class TrailingState:
    trade_id: str
    strategy: str
    side: str               # BUY | SELL
    entry_price: float
    quantity: float
    current_sl: float       # current stop loss price
    best_price: float       # highest (BUY) or lowest (SELL) seen
    activated: bool = False
    atr_at_entry: float = 0.0

    def should_activate(self, current_price: float, activation_atr_mult: float) -> bool:
        """Trail activates after price moves `activation_atr_mult × ATR` in favor."""
        if self.activated or self.atr_at_entry <= 0:
            return self.activated
        if self.side == "BUY":
            return current_price >= self.entry_price + activation_atr_mult * self.atr_at_entry
        else:
            return current_price <= self.entry_price - activation_atr_mult * self.atr_at_entry

    def update_best(self, current_price: float) -> None:
        if self.side == "BUY":
            self.best_price = max(self.best_price, current_price)
        else:
            self.best_price = min(self.best_price, current_price)

    def new_sl(self, current_price: float, atr: float, atr_mult: float) -> float:
        """Calculate new SL position based on current best price."""
        trail_dist = atr * atr_mult
        if self.side == "BUY":
            return round(self.best_price - trail_dist, 6)
        else:
            return round(self.best_price + trail_dist, 6)

    def sl_hit(self, current_price: float) -> bool:
        if self.side == "BUY":
            return current_price <= self.current_sl
        else:
            return current_price >= self.current_sl


class TrailingStopManager:
    """
    Manages trailing stops for all open trades.
    Call `on_price_tick()` every time a new price arrives (5s ticker loop).
    """

    def __init__(
        self,
        atr_mult: float = 1.5,            # trail distance = N × ATR
        activation_atr_mult: float = 1.0,  # activate after N × ATR profit
    ) -> None:
        self.atr_mult = atr_mult
        self.activation_atr_mult = activation_atr_mult
        self._states: Dict[str, TrailingState] = {}   # trade_id → state

    def register(
        self,
        trade_id: str,
        strategy: str,
        side: str,
        entry_price: float,
        quantity: float,
        initial_sl: float,
        atr_at_entry: float,
    ) -> None:
        """Register a new open trade for trailing."""
        self._states[trade_id] = TrailingState(
            trade_id=trade_id,
            strategy=strategy,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            current_sl=initial_sl,
            best_price=entry_price,
            atr_at_entry=atr_at_entry,
        )
        logger.debug("TrailingStop registered: %s %s entry=%.4f sl=%.4f", strategy, side, entry_price, initial_sl)

    def unregister(self, trade_id: str) -> None:
        self._states.pop(trade_id, None)

    def on_price_tick(
        self,
        current_price: float,
        current_atr: float,
    ) -> List[dict]:
        """
        Process a price tick for all registered trades.
        Returns list of actions: {"trade_id", "action": "update_sl"|"close", "new_sl", "reason"}
        """
        actions = []
        for trade_id, state in list(self._states.items()):
            state.update_best(current_price)

            # Check activation
            if not state.activated:
                if state.should_activate(current_price, self.activation_atr_mult):
                    state.activated = True
                    logger.info("Trailing activated for %s @ %.4f", trade_id, current_price)
                else:
                    # Not yet activated — check hard SL only
                    if state.sl_hit(current_price):
                        actions.append({
                            "trade_id": trade_id,
                            "action": "close",
                            "exit_price": current_price,
                            "reason": "hard_sl_hit",
                            "state": state,
                        })
                        self.unregister(trade_id)
                    continue

            # Trailing is active — compute new SL
            atr = current_atr if current_atr > 0 else state.atr_at_entry
            new_sl = state.new_sl(current_price, atr, self.atr_mult)

            sl_improved = (
                new_sl > state.current_sl if state.side == "BUY"
                else new_sl < state.current_sl
            )

            if sl_improved:
                old_sl = state.current_sl
                state.current_sl = new_sl
                actions.append({
                    "trade_id": trade_id,
                    "action": "update_sl",
                    "old_sl": old_sl,
                    "new_sl": new_sl,
                    "state": state,
                })
                logger.debug("TrailingSL moved %s: %.4f → %.4f", trade_id, old_sl, new_sl)

            # Check if trailing SL hit
            if state.sl_hit(current_price):
                actions.append({
                    "trade_id": trade_id,
                    "action": "close",
                    "exit_price": state.current_sl,
                    "reason": "trailing_sl_hit",
                    "state": state,
                })
                self.unregister(trade_id)

        return actions

    def get_all(self) -> List[dict]:
        return [
            {
                "trade_id": s.trade_id,
                "strategy": s.strategy,
                "side": s.side,
                "entry_price": s.entry_price,
                "current_sl": s.current_sl,
                "best_price": s.best_price,
                "activated": s.activated,
            }
            for s in self._states.values()
        ]

    def __len__(self) -> int:
        return len(self._states)
