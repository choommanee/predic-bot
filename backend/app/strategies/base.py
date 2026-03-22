"""Base Strategy interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Any
import pandas as pd

from ..core.smc import SMCResult


@dataclass
class OrderSignal:
    strategy: str
    side: str           # BUY | SELL
    quantity: float
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    level: int = 0      # Martingale/Grid level
    reason: str = ""


@dataclass
class StrategyState:
    active: bool = False
    open_orders: List[dict] = field(default_factory=list)
    total_pnl: float = 0.0
    daily_pnl: float = 0.0


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
                    # Cast to the type of the existing attribute
                    existing = getattr(self, key)
                    setattr(self, key, type(existing)(val))
                except (TypeError, ValueError):
                    setattr(self, key, val)

    def get_params(self) -> dict:
        """Return current configurable params as a plain dict."""
        result = {}
        for key in self.DEFAULT_PARAMS:
            result[key] = getattr(self, key, self.DEFAULT_PARAMS[key])
        return result

    # ─────────────────── State persistence ───────────────────

    def dump_state(self) -> dict:
        """Serialize internal runtime state for DB storage."""
        return {}

    def load_state(self, state: dict) -> None:
        """Restore internal runtime state from DB dict."""

    # ─────────────────── Position callbacks ───────────────────

    def on_fill(self, signal: OrderSignal, fill_price: float) -> None:
        """Called when an order signal is filled."""
        self.state.open_orders.append({
            "side": signal.side,
            "quantity": signal.quantity,
            "entry": fill_price,
            "level": signal.level,
        })

    def on_close(self, pnl: float) -> None:
        """Called when a position is closed."""
        self.state.daily_pnl += pnl
        self.state.total_pnl += pnl
        if self.state.open_orders:
            self.state.open_orders.pop(0)
