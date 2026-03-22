"""
SMC (Smart Money Concepts) Strategy
Trades directly on BOS/CHoCH breaks + Order Block test confluences.
Entry: price tests a fresh OB after a BOS in the same direction.
SL: behind the OB. TP: ATR-based RR of 2:1.
"""
from __future__ import annotations
from typing import List
import pandas as pd

from .base import BaseStrategy, OrderSignal, PartialTPLevel
from ..core.smc import SMCResult


class SMCStrategy(BaseStrategy):
    name = "smc"

    DEFAULT_PARAMS = {
        "min_bos_count": 1,
        "ob_proximity_pct": 0.3,
        "atr_tp_mult": 2.0,
        "atr_sl_mult": 1.0,
        "cooldown_bars": 10,
        "require_mtf_align": False,
        "use_partial_tp": True,     # ← partial TP: 50% at 1R, 50% at 2R
        "trailing_stop": True,      # ← hand off to TrailingStopManager
    }

    def __init__(
        self,
        symbol: str,
        base_lot: float = 0.001,
        min_bos_count: int = 1,
        ob_proximity_pct: float = 0.3,
        atr_tp_mult: float = 2.0,
        atr_sl_mult: float = 1.0,
        cooldown_bars: int = 10,
        require_mtf_align: bool = False,
        use_partial_tp: bool = True,
        trailing_stop: bool = True,
    ) -> None:
        super().__init__(symbol, base_lot)
        self.min_bos_count = min_bos_count
        self.ob_proximity_pct = ob_proximity_pct
        self.atr_tp_mult = atr_tp_mult
        self.atr_sl_mult = atr_sl_mult
        self.cooldown_bars = cooldown_bars
        self.require_mtf_align = require_mtf_align
        self.use_partial_tp = use_partial_tp
        self.trailing_stop = trailing_stop

        self._bar_count = 0
        self._last_signal_bar = -cooldown_bars
        self._last_ob_used: str | None = None   # avoid re-entering same OB

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

        # Cooldown
        if self._bar_count - self._last_signal_bar < self.cooldown_bars:
            return signals

        ind = indicators.get("last", {})
        atr = ind.get("atr", current_price * 0.001)

        # Require structural bias
        if smc.bias == "NEUTRAL":
            return signals

        direction = "BUY" if smc.bias == "BULLISH" else "SELL"

        # Need at least N BOS in direction
        if direction == "BUY" and smc.bullish_bos < self.min_bos_count:
            return signals
        if direction == "SELL" and smc.bearish_bos < self.min_bos_count:
            return signals

        # Find a fresh Order Block matching the direction to test
        obs = getattr(smc, "order_blocks", []) or []
        for ob in reversed(obs[-5:]):   # check last 5 OBs
            ob_type = getattr(ob, "ob_type", "")
            ob_low = getattr(ob, "low", 0)
            ob_high = getattr(ob, "high", 0)
            ob_id = f"{ob_type}_{ob_low}_{ob_high}"

            if ob_id == self._last_ob_used:
                continue  # skip already-used OB

            tolerance = (ob_high - ob_low) * (self.ob_proximity_pct / 100)

            in_zone = False
            if ob_type == "bullish" and direction == "BUY":
                in_zone = (ob_low - tolerance) <= current_price <= (ob_high + tolerance)
            elif ob_type == "bearish" and direction == "SELL":
                in_zone = (ob_low - tolerance) <= current_price <= (ob_high + tolerance)

            if in_zone:
                # Entry confirmed — build bracket
                if direction == "BUY":
                    sl = ob_low - atr * self.atr_sl_mult
                    tp = current_price + atr * self.atr_tp_mult
                else:
                    sl = ob_high + atr * self.atr_sl_mult
                    tp = current_price - atr * self.atr_tp_mult

                self._last_signal_bar = self._bar_count
                self._last_ob_used = ob_id

                # Build partial TP levels if enabled
                partial_tps = (
                    self.build_partial_tps(direction, current_price, sl, atr)
                    if self.use_partial_tp else []
                )
                # Full TP = 2R (fallback if partial TPs not used)
                full_tp = tp if not self.use_partial_tp else None

                signals.append(
                    OrderSignal(
                        strategy=self.name,
                        side=direction,
                        quantity=self.base_lot,
                        entry_price=current_price,
                        stop_loss=sl,
                        take_profit=full_tp,
                        reason=f"SMC {ob_type} OB test BOS={smc.bullish_bos if direction=='BUY' else smc.bearish_bos}",
                        partial_tps=partial_tps,
                        atr=atr,
                    )
                )
                break  # one signal per evaluation

        return signals

    def reset(self) -> None:
        self._bar_count = 0
        self._last_signal_bar = -self.cooldown_bars
        self._last_ob_used = None

    def dump_state(self) -> dict:
        return {
            "bar_count": self._bar_count,
            "last_signal_bar": self._last_signal_bar,
            "last_ob_used": self._last_ob_used,
        }

    def load_state(self, state: dict) -> None:
        self._bar_count = state.get("bar_count", 0)
        self._last_signal_bar = state.get("last_signal_bar", -self.cooldown_bars)
        self._last_ob_used = state.get("last_ob_used")
