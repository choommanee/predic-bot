from sqlalchemy import String, Float, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime, timezone
from ..database import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20))
    strategy: Mapped[str] = mapped_column(String(50))
    direction: Mapped[str] = mapped_column(String(10))  # BUY | SELL | NEUTRAL
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 - 1.0
    price: Mapped[float] = mapped_column(Float)
    smc_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    ai_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    acted_on: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
