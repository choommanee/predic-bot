"""
Risk Management
Ported concepts from python-trade/vtmarkets_settings.py and pro_scalping_system.py
"""
from __future__ import annotations
from datetime import datetime, timezone
from dataclasses import dataclass, field


@dataclass
class RiskState:
    daily_pnl: float = 0.0
    peak_equity: float = 0.0
    daily_trades: int = 0
    circuit_breaker_hit: bool = False
    reset_date: str = ""

    def reset_if_new_day(self, current_equity: float) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.reset_date != today:
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.circuit_breaker_hit = False
            self.reset_date = today
            if current_equity > self.peak_equity:
                self.peak_equity = current_equity

    def record_trade_pnl(self, pnl: float) -> None:
        self.daily_pnl += pnl

    def drawdown_pct(self, current_equity: float) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - current_equity) / self.peak_equity * 100


class RiskManager:
    def __init__(
        self,
        max_daily_loss_usd: float = 100.0,
        max_drawdown_pct: float = 15.0,
        base_lot_size: float = 0.001,
        mart_multiplier: float = 1.5,
        mart_max_levels: int = 7,
    ) -> None:
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_drawdown_pct = max_drawdown_pct
        self.base_lot_size = base_lot_size
        self.mart_multiplier = mart_multiplier
        self.mart_max_levels = mart_max_levels
        self.state = RiskState()

    def can_trade(self, current_equity: float) -> tuple[bool, str]:
        """Return (allowed, reason) before placing any order."""
        self.state.reset_if_new_day(current_equity)

        if self.state.circuit_breaker_hit:
            return False, "Circuit breaker active — daily loss limit hit"

        if self.state.daily_pnl <= -self.max_daily_loss_usd:
            self.state.circuit_breaker_hit = True
            return False, f"Daily loss limit reached (${self.state.daily_pnl:.2f})"

        dd = self.state.drawdown_pct(current_equity)
        if dd >= self.max_drawdown_pct:
            self.state.circuit_breaker_hit = True
            return False, f"Max drawdown reached ({dd:.1f}%)"

        return True, "ok"

    def martingale_lot(self, level: int) -> float:
        """Calculate lot size for martingale level (0-indexed)."""
        level = min(level, self.mart_max_levels - 1)
        return round(self.base_lot_size * (self.mart_multiplier ** level), 6)

    def update_equity_peak(self, equity: float) -> None:
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    def record_pnl(self, pnl: float) -> None:
        self.state.record_trade_pnl(pnl)

    def risk_to_qty(self, equity: float, risk_pct: float, entry: float, stoploss: float) -> float:
        """Jesse-style: size so that SL hit = lose risk_pct% of equity."""
        if entry <= 0 or stoploss <= 0 or abs(entry - stoploss) < 0.01:
            return self.base_lot_size
        risk_dollars = equity * (risk_pct / 100.0)
        qty = risk_dollars / abs(entry - stoploss)
        return max(qty, self.base_lot_size)
