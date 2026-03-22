"""
Trading API endpoints:
- GET  /api/trading/status       — engine status + indicators
- GET  /api/trading/positions    — current open positions
- GET  /api/trading/balance      — account balance
- POST /api/trading/strategy     — enable/disable strategy
- POST /api/trading/mode         — change trading mode
- GET  /api/trading/ohlcv        — latest OHLCV data for chart
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..api.auth import get_current_user
from ..models.user import User

router = APIRouter(prefix="/api/trading", tags=["trading"])

# Engine is injected via app state (set in main.py)
def get_engine(user: User = Depends(get_current_user)):
    from ..main import engine
    if engine is None:
        raise HTTPException(status_code=503, detail="Trading engine not running")
    return engine


class StrategyControl(BaseModel):
    name: str
    active: bool


class ModeControl(BaseModel):
    mode: str  # paper | signal | auto | both


@router.get("/status")
async def get_status(engine=Depends(get_engine)):
    return engine.get_status()


@router.get("/positions")
async def get_positions(engine=Depends(get_engine)):
    return await engine.exchange.fetch_positions(engine.symbol)


@router.get("/balance")
async def get_balance(engine=Depends(get_engine)):
    return await engine.exchange.fetch_balance()


@router.get("/ohlcv")
async def get_ohlcv(timeframe: str = "1m", limit: int = 100, engine=Depends(get_engine)):
    # Use cached 1m data when possible, otherwise fetch from Binance
    if timeframe == "1m" and engine._cached_df is not None:
        df = engine._cached_df.tail(limit).copy()
    else:
        df = await engine.exchange.fetch_ohlcv(engine.symbol, timeframe, limit)
    df = df.reset_index()
    # Ensure timestamp is serializable
    if "timestamp" in df.columns:
        df["timestamp"] = df["timestamp"].astype(str)
    return df.to_dict(orient="records")


@router.post("/strategy")
async def control_strategy(body: StrategyControl, engine=Depends(get_engine)):
    ok = engine.set_strategy_active(body.name, body.active)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Strategy '{body.name}' not found")
    return {"strategy": body.name, "active": body.active}


@router.post("/mode")
async def set_mode(body: ModeControl, engine=Depends(get_engine)):
    valid = {"paper", "signal", "auto", "both"}
    if body.mode not in valid:
        raise HTTPException(status_code=400, detail=f"Mode must be one of {valid}")
    engine.mode = body.mode
    return {"mode": body.mode}
