from sqlalchemy import String, Float, Integer, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime, timezone
from ..database import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20))
    strategy: Mapped[str] = mapped_column(String(50))  # martingale | grid | momentum
    side: Mapped[str] = mapped_column(String(10))  # BUY | SELL
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)
    binance_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=0)  # Martingale level
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
