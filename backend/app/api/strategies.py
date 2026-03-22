"""
Strategy configuration API
- GET  /api/strategies              — list all strategies with current config
- GET  /api/strategies/{name}       — get a single strategy config
- PUT  /api/strategies/{name}       — update params + active flag (hot-reload)
- POST /api/strategies/{name}/reset — reset internal runtime state
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.auth import get_current_user
from ..database import get_db
from ..models.strategy_config import StrategyConfig
from ..models.user import User

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def get_engine(user: User = Depends(get_current_user)):
    from ..main import engine
    if engine is None:
        raise HTTPException(status_code=503, detail="Trading engine not running")
    return engine


class StrategyUpdate(BaseModel):
    active: bool | None = None
    params: dict | None = None


@router.get("")
async def list_strategies(engine=Depends(get_engine)):
    result = []
    for name, strategy in engine.strategies.items():
        result.append({
            "name": name,
            "active": strategy.state.active,
            "params": strategy.get_params(),
            "pnl": {
                "daily": round(strategy.state.daily_pnl, 4),
                "total": round(strategy.state.total_pnl, 4),
            },
            "open_orders": len(strategy.state.open_orders),
        })
    return result


@router.get("/{name}")
async def get_strategy(name: str, engine=Depends(get_engine)):
    if name not in engine.strategies:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
    strategy = engine.strategies[name]
    return {
        "name": name,
        "active": strategy.state.active,
        "params": strategy.get_params(),
        "state": strategy.dump_state(),
        "pnl": {
            "daily": round(strategy.state.daily_pnl, 4),
            "total": round(strategy.state.total_pnl, 4),
        },
        "open_orders": strategy.state.open_orders,
    }


@router.put("/{name}")
async def update_strategy(
    name: str,
    body: StrategyUpdate,
    db: AsyncSession = Depends(get_db),
    engine=Depends(get_engine),
):
    if name not in engine.strategies:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")

    strategy = engine.strategies[name]

    # Apply active flag
    if body.active is not None:
        strategy.state.active = body.active

    # Apply params hot-reload
    if body.params:
        strategy.update_params(body.params)

    # Persist to DB
    result = await db.execute(select(StrategyConfig).where(StrategyConfig.name == name))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = StrategyConfig(name=name)
        db.add(cfg)

    cfg.active = strategy.state.active
    cfg.params = strategy.get_params()
    await db.commit()

    # Broadcast strategy_update event
    await engine._broadcast({
        "type": "strategy_update",
        "strategy": name,
        "active": strategy.state.active,
        "params": strategy.get_params(),
    })

    return {"name": name, "active": strategy.state.active, "params": strategy.get_params()}


@router.post("/{name}/reset")
async def reset_strategy(name: str, engine=Depends(get_engine)):
    if name not in engine.strategies:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
    strategy = engine.strategies[name]
    if hasattr(strategy, "reset"):
        strategy.reset()
    return {"name": name, "reset": True}
