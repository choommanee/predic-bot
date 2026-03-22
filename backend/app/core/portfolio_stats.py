"""
Portfolio-level performance statistics.
Tracks rolling metrics across all strategies:
  - Win rate (rolling 20 trades)
  - Sharpe ratio (rolling daily PnL)
  - Max drawdown (running peak-to-trough)
  - Profit factor (gross profit / gross loss)
  - Average RR (avg winner / avg loser)
  - Best/worst trade
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, List
import math


@dataclass
class TradeRecord:
    strategy: str
    side: str
    pnl: float
    entry_price: float
    exit_price: float
    quantity: float
    opened_at: datetime
    closed_at: datetime


@dataclass
class PortfolioMetrics:
    total_trades: int = 0
    win_rate: float = 0.0           # % of profitable trades
    sharpe_ratio: float = 0.0       # annualized (252-day basis)
    profit_factor: float = 0.0      # gross profit / gross loss
    max_drawdown_pct: float = 0.0   # peak-to-trough %
    avg_rr: float = 0.0             # avg winner / avg loser
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    by_strategy: dict = field(default_factory=dict)


class PortfolioStats:
    """Maintains rolling portfolio statistics across all closed trades."""

    ROLLING_WINDOW = 50   # last N trades for rolling metrics

    def __init__(self) -> None:
        self._trades: Deque[TradeRecord] = deque(maxlen=500)
        self._daily_pnl: Deque[float] = deque(maxlen=365)   # daily returns
        self._equity_curve: List[float] = []
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._today: str = ""
        self._today_pnl: float = 0.0

    def record(self, record: TradeRecord) -> None:
        """Record a closed trade and update equity curve."""
        self._trades.append(record)
        self._current_equity += record.pnl
        self._equity_curve.append(self._current_equity)
        self._peak_equity = max(self._peak_equity, self._current_equity)

        # Daily PnL accumulation
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._today:
            if self._today:
                self._daily_pnl.append(self._today_pnl)
            self._today = today
            self._today_pnl = record.pnl
        else:
            self._today_pnl += record.pnl

    def record_from_dict(
        self,
        strategy: str,
        side: str,
        pnl: float,
        entry_price: float,
        exit_price: float,
        quantity: float,
        opened_at: datetime | None = None,
        closed_at: datetime | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.record(TradeRecord(
            strategy=strategy,
            side=side,
            pnl=pnl,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            opened_at=opened_at or now,
            closed_at=closed_at or now,
        ))

    def compute(self) -> PortfolioMetrics:
        if not self._trades:
            return PortfolioMetrics()

        trades = list(self._trades)
        recent = trades[-self.ROLLING_WINDOW:]

        winners = [t.pnl for t in recent if t.pnl > 0]
        losers  = [t.pnl for t in recent if t.pnl <= 0]

        win_rate = len(winners) / len(recent) * 100 if recent else 0.0

        gross_profit = sum(winners) or 0.0
        gross_loss   = abs(sum(losers)) or 0.0
        profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

        avg_winner = sum(winners) / len(winners) if winners else 0.0
        avg_loser  = abs(sum(losers) / len(losers)) if losers else 0.0
        avg_rr = avg_winner / avg_loser if avg_loser else 0.0

        total_pnl = sum(t.pnl for t in trades)
        best  = max((t.pnl for t in trades), default=0.0)
        worst = min((t.pnl for t in trades), default=0.0)

        # Max drawdown from equity curve
        max_dd = self._max_drawdown_pct()

        # Sharpe ratio from daily PnL
        sharpe = self._sharpe()

        # Per-strategy breakdown (last 50)
        by_strategy: dict = {}
        for t in recent:
            s = by_strategy.setdefault(t.strategy, {"trades": 0, "pnl": 0.0, "wins": 0})
            s["trades"] += 1
            s["pnl"] = round(s["pnl"] + t.pnl, 4)
            if t.pnl > 0:
                s["wins"] += 1
        for s in by_strategy.values():
            s["win_rate"] = round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0.0

        return PortfolioMetrics(
            total_trades=len(trades),
            win_rate=round(win_rate, 1),
            sharpe_ratio=round(sharpe, 3),
            profit_factor=round(profit_factor, 2),
            max_drawdown_pct=round(max_dd, 2),
            avg_rr=round(avg_rr, 2),
            total_pnl=round(total_pnl, 4),
            daily_pnl=round(self._today_pnl, 4),
            best_trade=round(best, 4),
            worst_trade=round(worst, 4),
            by_strategy=by_strategy,
        )

    def _max_drawdown_pct(self) -> float:
        if len(self._equity_curve) < 2:
            return 0.0
        peak = self._equity_curve[0]
        max_dd = 0.0
        for val in self._equity_curve:
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak * 100
                max_dd = max(max_dd, dd)
        return max_dd

    def _sharpe(self, risk_free: float = 0.0) -> float:
        """Annualized Sharpe ratio from daily PnL series."""
        if len(self._daily_pnl) < 5:
            return 0.0
        returns = list(self._daily_pnl)
        n = len(returns)
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / max(n - 1, 1)
        std = math.sqrt(variance)
        if std == 0:
            return 0.0
        daily_sharpe = (mean - risk_free) / std
        return daily_sharpe * math.sqrt(252)   # annualized
