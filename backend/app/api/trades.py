"""
Trade execution history API
- GET /api/trades          — list trades (filter by status/strategy)
- GET /api/trades/open     — open trades only
- GET /api/trades/{id}     — single trade detail
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.auth import get_current_user
from ..database import get_db
from ..models.trade_execution import TradeExecution
from ..models.user import User

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("")
async def list_trades(
    strategy: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(TradeExecution).order_by(desc(TradeExecution.opened_at)).limit(limit)
    if strategy:
        stmt = stmt.where(TradeExecution.strategy == strategy)
    if status:
        stmt = stmt.where(TradeExecution.status == status)
    result = await db.execute(stmt)
    trades = result.scalars().all()
    return [_serialize(t) for t in trades]


@router.get("/open")
async def list_open_trades(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TradeExecution)
        .where(TradeExecution.status == "open")
        .order_by(desc(TradeExecution.opened_at))
    )
    trades = result.scalars().all()
    return [_serialize(t) for t in trades]


@router.get("/{trade_id}")
async def get_trade(
    trade_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TradeExecution).where(TradeExecution.id == trade_id)
    )
    trade = result.scalar_one_or_none()
    if trade is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trade not found")
    return _serialize(trade)


def _serialize(t: TradeExecution) -> dict:
    return {
        "id": t.id,
        "strategy": t.strategy,
        "symbol": t.symbol,
        "side": t.side,
        "quantity": t.quantity,
        "entry_price": t.entry_price,
        "stop_loss": t.stop_loss,
        "take_profit": t.take_profit,
        "level": t.level,
        "reason": t.reason,
        "sl_order_id": t.sl_order_id,
        "tp_order_id": t.tp_order_id,
        "status": t.status,
        "exit_price": t.exit_price,
        "pnl": t.pnl,
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
    }
