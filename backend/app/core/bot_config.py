"""
Bot configuration loader — reads settings from DB, falls back to env vars.
Sensitive values (API keys, tokens) are encrypted with Fernet using SECRET_KEY.
"""
from __future__ import annotations
import base64
import hashlib
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.setting import BotSetting

logger = logging.getLogger(__name__)

# Keys that are masked in API responses and encrypted at rest
SENSITIVE_KEYS = {
    "binance_api_key",
    "binance_secret_key",
    "telegram_bot_token",
    "anthropic_api_key",
}

# All configurable keys with their defaults (from env/config)
SETTING_KEYS = [
    "binance_api_key",
    "binance_secret_key",
    "binance_testnet",
    "telegram_bot_token",
    "telegram_chat_id",
    "anthropic_api_key",
    "trading_symbol",
    "trading_mode",
    "max_daily_loss_usd",
    "max_drawdown_pct",
    "base_lot_size",
]


def _make_fernet(secret_key: str) -> Fernet:
    """Derive a 32-byte Fernet key from SECRET_KEY."""
    digest = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_value(value: str, secret_key: str) -> str:
    return _make_fernet(secret_key).encrypt(value.encode()).decode()


def decrypt_value(token: str, secret_key: str) -> str:
    try:
        return _make_fernet(secret_key).decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


async def load_bot_config(db: AsyncSession) -> dict[str, Any]:
    """
    Return merged config: DB values override env defaults.
    Sensitive values are decrypted automatically.
    """
    env = get_settings()
    secret = env.secret_key

    # Env defaults
    defaults: dict[str, Any] = {
        "binance_api_key": env.binance_api_key,
        "binance_secret_key": env.binance_secret_key,
        "binance_testnet": env.binance_testnet,
        "telegram_bot_token": env.telegram_bot_token,
        "telegram_chat_id": env.telegram_chat_id,
        "anthropic_api_key": env.anthropic_api_key,
        "trading_symbol": env.trading_symbol,
        "trading_mode": env.trading_mode,
        "max_daily_loss_usd": env.max_daily_loss_usd,
        "max_drawdown_pct": env.max_drawdown_pct,
        "base_lot_size": env.base_lot_size,
    }

    try:
        result = await db.execute(select(BotSetting))
        rows = result.scalars().all()
        for row in rows:
            val = row.value or ""
            if row.is_encrypted and val:
                val = decrypt_value(val, secret)
            # Cast to correct type
            if row.key in ("binance_testnet",):
                defaults[row.key] = val.lower() in ("true", "1", "yes")
            elif row.key in ("max_daily_loss_usd", "max_drawdown_pct", "base_lot_size"):
                try:
                    defaults[row.key] = float(val)
                except ValueError:
                    pass
            else:
                defaults[row.key] = val
    except Exception as exc:
        logger.warning("Could not load bot_settings from DB: %s", exc)

    return defaults


async def save_bot_setting(db: AsyncSession, key: str, value: str) -> None:
    """Upsert a single setting. Sensitive keys are encrypted."""
    env = get_settings()
    is_sensitive = key in SENSITIVE_KEYS
    stored_value = encrypt_value(value, env.secret_key) if is_sensitive else value

    result = await db.execute(select(BotSetting).where(BotSetting.key == key))
    row = result.scalar_one_or_none()

    if row:
        row.value = stored_value
        row.is_encrypted = is_sensitive
    else:
        db.add(BotSetting(key=key, value=stored_value, is_encrypted=is_sensitive))

    await db.commit()
