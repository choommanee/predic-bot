"""
Bot settings endpoints — read/write config stored in DB.
All endpoints require authentication.
"""
from __future__ import annotations
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..api.auth import get_current_user
from ..core.bot_config import (
    SETTING_KEYS,
    SENSITIVE_KEYS,
    load_bot_config,
    save_bot_setting,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingItem(BaseModel):
    key: str
    value: str


class SettingsResponse(BaseModel):
    settings: dict[str, Any]


def _mask(key: str, value: Any) -> Any:
    """Replace sensitive values with asterisks in API responses."""
    if key in SENSITIVE_KEYS and value:
        v = str(value)
        return v[:4] + "****" if len(v) > 4 else "****"
    return value


@router.get("", response_model=SettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    config = await load_bot_config(db)
    masked = {k: _mask(k, v) for k, v in config.items() if k in SETTING_KEYS}
    return {"settings": masked}


@router.put("")
async def update_settings(
    items: list[SettingItem],
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    for item in items:
        if item.key not in SETTING_KEYS:
            raise HTTPException(status_code=400, detail=f"Unknown setting: {item.key}")
        await save_bot_setting(db, item.key, item.value)

    return {"status": "saved", "count": len(items)}


@router.post("/reload")
async def reload_engine(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Reload TradingEngine with latest settings from DB."""
    from ..main import engine as _engine

    if _engine is None:
        raise HTTPException(status_code=503, detail="Engine not running")

    config = await load_bot_config(db)
    await _engine.stop()

    # Restart with new config
    from ..core.engine import TradingEngine
    from ..main import engine as _eng_ref
    import backend.app.main as _main_module

    new_engine = TradingEngine(override_config=config)

    from ..api.websocket import manager

    async def _ws_cb(event: dict):
        await manager.broadcast(event)

    new_engine.add_broadcast_callback(_ws_cb)
    await new_engine.start()
    _main_module.engine = new_engine

    return {"status": "reloaded"}
