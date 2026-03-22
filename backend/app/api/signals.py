"""
Signal history endpoints:
- GET /api/signals        — paginated signal history
- GET /api/signals/latest — latest N signals
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.auth import get_current_user
from ..database import get_db
from ..models.signal import Signal
from ..models.user import User

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
async def list_signals(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Signal).order_by(desc(Signal.created_at)).limit(limit).offset(offset)
    )
    signals = result.scalars().all()
    return [
        {
            "id": s.id,
            "symbol": s.symbol,
            "strategy": s.strategy,
            "direction": s.direction,
            "confidence": s.confidence,
            "price": s.price,
            "acted_on": s.acted_on,
            "created_at": s.created_at.isoformat(),
        }
        for s in signals
    ]


@router.get("/latest")
async def latest_signals(
    n: int = 10,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Signal).order_by(desc(Signal.created_at)).limit(n)
    )
    return result.scalars().all()
