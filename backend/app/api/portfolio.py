"""
Portfolio statistics API
- GET /api/portfolio/stats    — rolling metrics (win rate, Sharpe, max DD, etc.)
- GET /api/portfolio/risk     — current risk state (exposure, drawdown, circuit breaker)
- GET /api/portfolio/trailing — active trailing stops
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from ..api.auth import get_current_user
from ..models.user import User

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def get_engine(user: User = Depends(get_current_user)):
    from ..main import engine
    from fastapi import HTTPException
    if engine is None:
        raise HTTPException(status_code=503, detail="Trading engine not running")
    return engine


@router.get("/stats")
async def get_stats(engine=Depends(get_engine)):
    metrics = engine.portfolio.compute()
    return {
        "total_trades":     metrics.total_trades,
        "win_rate":         metrics.win_rate,
        "sharpe_ratio":     metrics.sharpe_ratio,
        "profit_factor":    metrics.profit_factor,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "avg_rr":           metrics.avg_rr,
        "total_pnl":        metrics.total_pnl,
        "daily_pnl":        metrics.daily_pnl,
        "best_trade":       metrics.best_trade,
        "worst_trade":      metrics.worst_trade,
        "by_strategy":      metrics.by_strategy,
    }


@router.get("/risk")
async def get_risk(engine=Depends(get_engine)):
    return engine.risk.risk_summary(engine._last_price or 1.0)


@router.get("/trailing")
async def get_trailing(engine=Depends(get_engine)):
    return engine.trailing.get_all()
