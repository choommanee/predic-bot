"""TradeExecution — persistent record of every open/closed trade."""
from __future__ import annotations
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, Integer, DateTime, JSON

from ..database import Base


class TradeExecution(Base):
    __tablename__ = "trade_executions"

    id = Column(String(64), primary_key=True)          # exchange order ID (or paper_N)
    strategy = Column(String(32), nullable=False)
    symbol = Column(String(32), nullable=False)
    side = Column(String(8), nullable=False)            # BUY | SELL
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    level = Column(Integer, default=0)
    reason = Column(String(256), default="")

    # Bracket order IDs (set after placing SL/TP)
    sl_order_id = Column(String(64), nullable=True)
    tp_order_id = Column(String(64), nullable=True)

    # Lifecycle
    status = Column(String(16), default="open")        # open | closed | cancelled
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)

    extra = Column(JSON, default=dict)                  # any extra metadata

    opened_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    closed_at = Column(DateTime(timezone=True), nullable=True)
