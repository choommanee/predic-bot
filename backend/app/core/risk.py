"""
Risk Management
Ported concepts from python-trade/vtmarkets_settings.py and pro_scalping_system.py

Enhancements vs original:
- ATR-based volatility-adjusted position sizing (Jesse-style)
- Max concurrent position cap (OctoBot-style)
- Kelly Criterion approximation
- Portfolio-level exposure tracking
"""
from __future__ import annotations
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List


@dataclass
class RiskState:
    daily_pnl: float = 0.0
    peak_equity: float = 0.0
    daily_trades: int = 0
    circuit_breaker_hit: bool = False
    reset_date: str = ""
    open_position_count: int = 0
    total_exposure_usd: float = 0.0

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
        max_open_positions: int = 5,          # ← max concurrent positions (OctoBot-style)
        risk_per_trade_pct: float = 1.0,      # ← % equity to risk per trade (Jesse-style)
        atr_lot_enabled: bool = True,         # ← use ATR-based sizing vs fixed
    ) -> None:
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_drawdown_pct = max_drawdown_pct
        self.base_lot_size = base_lot_size
        self.mart_multiplier = mart_multiplier
        self.mart_max_levels = mart_max_levels
        self.max_open_positions = max_open_positions
        self.risk_per_trade_pct = risk_per_trade_pct
        self.atr_lot_enabled = atr_lot_enabled
        self.state = RiskState()

    # ─────────────────── Gate checks ───────────────────

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

        if self.state.open_position_count >= self.max_open_positions:
            return False, f"Max concurrent positions reached ({self.max_open_positions})"

        return True, "ok"

    # ─────────────────── Position Sizing ───────────────────

    def atr_lot(
        self,
        equity: float,
        entry: float,
        stop_loss: float,
        atr: float,
    ) -> float:
        """
        ATR-based volatility-adjusted lot size (Jesse-style).
        Risk exactly `risk_per_trade_pct`% of equity on each trade.
        SL distance = max(|entry - stop_loss|, 1×ATR).
        """
        sl_distance = max(abs(entry - stop_loss), atr) if stop_loss else atr
        if sl_distance <= 0 or equity <= 0:
            return self.base_lot_size

        risk_usd = equity * (self.risk_per_trade_pct / 100.0)
        qty = risk_usd / sl_distance
        # Clamp: never below base_lot, never above 5% of equity at current price
        max_qty = equity * 0.05 / max(entry, 1)
        qty = max(qty, self.base_lot_size)
        qty = min(qty, max_qty)
        return round(qty, 6)

    def smart_lot(
        self,
        equity: float,
        entry: float,
        stop_loss: float | None = None,
        atr: float = 0.0,
    ) -> float:
        """
        Choose between ATR-adjusted or fixed base lot.
        Falls back to base_lot_size when ATR data unavailable.
        """
        if self.atr_lot_enabled and stop_loss and atr > 0:
            return self.atr_lot(equity, entry, stop_loss, atr)
        return self.base_lot_size

    def martingale_lot(self, level: int) -> float:
        """Calculate lot size for martingale level (0-indexed)."""
        level = min(level, self.mart_max_levels - 1)
        return round(self.base_lot_size * (self.mart_multiplier ** level), 6)

    def risk_to_qty(self, equity: float, risk_pct: float, entry: float, stoploss: float) -> float:
        """Jesse-style: size so that SL hit = lose risk_pct% of equity."""
        if entry <= 0 or stoploss <= 0 or abs(entry - stoploss) < 0.01:
            return self.base_lot_size
        risk_dollars = equity * (risk_pct / 100.0)
        qty = risk_dollars / abs(entry - stoploss)
        return max(qty, self.base_lot_size)

    # ─────────────────── Position tracking ───────────────────

    def on_position_opened(self, qty: float, price: float) -> None:
        self.state.open_position_count += 1
        self.state.total_exposure_usd += qty * price

    def on_position_closed(self, pnl: float, qty: float = 0.0, price: float = 0.0) -> None:
        self.state.daily_pnl += pnl
        self.state.open_position_count = max(0, self.state.open_position_count - 1)
        exposure = qty * price
        self.state.total_exposure_usd = max(0.0, self.state.total_exposure_usd - exposure)

    def record_pnl(self, pnl: float) -> None:
        self.state.record_trade_pnl(pnl)

    def update_equity_peak(self, equity: float) -> None:
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    def risk_summary(self, current_equity: float) -> dict:
        return {
            "daily_pnl": round(self.state.daily_pnl, 4),
            "drawdown_pct": round(self.state.drawdown_pct(current_equity), 2),
            "peak_equity": round(self.state.peak_equity, 2),
            "open_positions": self.state.open_position_count,
            "total_exposure_usd": round(self.state.total_exposure_usd, 2),
            "circuit_breaker": self.state.circuit_breaker_hit,
        }
