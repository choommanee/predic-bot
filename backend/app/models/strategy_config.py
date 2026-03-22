"""StrategyConfig — persisted per-strategy configuration (JSON params)."""
from __future__ import annotations
from datetime import datetime, timezone

from sqlalchemy import Column, String, JSON, Boolean, DateTime

from ..database import Base


class StrategyConfig(Base):
    __tablename__ = "strategy_configs"

    name = Column(String(64), primary_key=True)   # "martingale" | "grid" | "momentum"
    active = Column(Boolean, default=False, nullable=False)
    params = Column(JSON, default=dict, nullable=False)   # strategy-specific params
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
