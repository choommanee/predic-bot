"""Base Strategy interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Any
import pandas as pd

from ..core.smc import SMCResult


@dataclass
class PartialTPLevel:
    """Define one take-profit level: exit `pct`% of position at RR `rr` (multiples of ATR or SL distance)."""
    rr: float        # risk:reward ratio trigger (e.g. 1.0 = 1R, 2.0 = 2R)
    pct: float       # % of remaining position to close (e.g. 50 = 50%)
    hit: bool = False


@dataclass
class OrderSignal:
    strategy: str
    side: str                       # BUY | SELL
    quantity: float
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    level: int = 0                  # Martingale/Grid level
    reason: str = ""
    # Partial TP levels — overrides take_profit if set
    partial_tps: List[PartialTPLevel] = field(default_factory=list)
    # ATR at signal time — used by trailing stop + sizing
    atr: float = 0.0


@dataclass
class StrategyState:
    active: bool = False
    open_orders: List[dict] = field(default_factory=list)
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    win_count: int = 0
    loss_count: int = 0

    @property
    def win_rate(self) -> float:
        total = self.win_count + self.loss_count
        return round(self.win_count / total * 100, 1) if total else 0.0


class BaseStrategy(ABC):
    name: str = "base"

    # Default configurable params — subclasses override
    DEFAULT_PARAMS: dict = {}

    def __init__(self, symbol: str, base_lot: float = 0.001) -> None:
        self.symbol = symbol
        self.base_lot = base_lot
        self.state = StrategyState()

    @abstractmethod
    async def evaluate(
        self,
        df: pd.DataFrame,
        smc: SMCResult,
        indicators: dict,
        current_price: float,
    ) -> List[OrderSignal]:
        """Evaluate market data and return list of order signals (may be empty)."""

    # ─────────────────── Config hot-reload ───────────────────

    def update_params(self, params: dict) -> None:
        """Apply a dict of param overrides without restarting the engine."""
        for key, val in params.items():
            if hasattr(self, key):
                try:
                    existing = getattr(self, key)
                    setattr(self, key, type(existing)(val))
                except (TypeError, ValueError):
                    setattr(self, key, val)

    def get_params(self) -> dict:
        """Return current configurable params as a plain dict."""
        return {k: getattr(self, k, self.DEFAULT_PARAMS[k]) for k in self.DEFAULT_PARAMS}

    # ─────────────────── Partial TP helpers ───────────────────

    @staticmethod
    def build_partial_tps(
        side: str,
        entry: float,
        sl: float | None,
        atr: float,
        levels: list[tuple[float, float]] | None = None,
    ) -> List[PartialTPLevel]:
        """
        Build PartialTPLevel list from RR levels.
        Default: [(1.0, 50%), (2.0, 50%)] — half at 1R, rest at 2R.
        sl_distance used as 1R unit; falls back to 1×ATR if no SL.
        """
        if levels is None:
            levels = [(1.0, 50.0), (2.0, 50.0)]

        if sl and entry:
            one_r = abs(entry - sl)
        elif atr:
            one_r = atr
        else:
            return []

        result = []
        for rr, pct in levels:
            price = entry + rr * one_r if side == "BUY" else entry - rr * one_r
            result.append(PartialTPLevel(rr=rr, pct=pct))
        return result

    @staticmethod
    def partial_tp_prices(
        side: str,
        entry: float,
        sl: float | None,
        atr: float,
        levels: list[tuple[float, float]] | None = None,
    ) -> list[float]:
        """Return a list of price targets for each partial TP level."""
        if levels is None:
            levels = [(1.0, 50.0), (2.0, 50.0)]
        one_r = abs(entry - sl) if sl and entry else atr
        if not one_r:
            return []
        prices = []
        for rr, _ in levels:
            prices.append(entry + rr * one_r if side == "BUY" else entry - rr * one_r)
        return prices

    # ─────────────────── State persistence ───────────────────

    def dump_state(self) -> dict:
        return {}

    def load_state(self, state: dict) -> None:
        pass

    # ─────────────────── Position callbacks ───────────────────

    def on_fill(self, signal: OrderSignal, fill_price: float) -> None:
        self.state.open_orders.append({
            "side": signal.side,
            "quantity": signal.quantity,
            "entry": fill_price,
            "level": signal.level,
        })

    def on_close(self, pnl: float) -> None:
        self.state.daily_pnl += pnl
        self.state.total_pnl += pnl
        if pnl >= 0:
            self.state.win_count += 1
        else:
            self.state.loss_count += 1
        if self.state.open_orders:
            self.state.open_orders.pop(0)
