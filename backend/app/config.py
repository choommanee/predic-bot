from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Binance
    binance_api_key: str = ""
    binance_secret_key: str = ""
    binance_testnet: bool = True

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/predicbot"

    # Auth
    secret_key: str = "change_me_to_32_random_chars_minimum"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    google_client_id: str = ""
    google_client_secret: str = ""

    # Claude AI
    anthropic_api_key: str = ""

    # Trading
    trading_symbol: str = "BTCUSDT"
    trading_mode: str = "paper"  # paper | signal | auto | both
    max_daily_loss_usd: float = 100.0
    max_drawdown_pct: float = 15.0
    base_lot_size: float = 0.001

    # App
    app_env: str = "development"
    frontend_url: str = "http://localhost:5173"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
