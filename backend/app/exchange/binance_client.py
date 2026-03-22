"""
Binance Futures wrapper using ccxt (async).
Supports testnet and mainnet.
"""
from __future__ import annotations
import asyncio
from typing import Any, List
import pandas as pd
import ccxt.async_support as ccxt


class BinanceClient:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        testnet: bool = True,
    ) -> None:
        options: dict[str, Any] = {
            "defaultType": "future",
            "adjustForTimeDifference": True,
        }
        if testnet:
            options["urls"] = {
                "api": {
                    "public": "https://testnet.binancefuture.com/fapi/v1",
                    "private": "https://testnet.binancefuture.com/fapi/v1",
                }
            }

        self._exchange = ccxt.binance(
            {
                "apiKey": api_key,
                "secret": secret_key,
                "options": options,
                "enableRateLimit": True,
            }
        )

    async def close(self) -> None:
        await self._exchange.close()

    # ─────────────────── Market Data ───────────────────

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 200,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles and return as DataFrame with lowercase columns."""
        raw = await self._exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df

    async def fetch_ticker(self, symbol: str) -> dict:
        return await self._exchange.fetch_ticker(symbol)

    async def fetch_balance(self) -> dict:
        balance = await self._exchange.fetch_balance()
        usdt = balance.get("USDT", {})
        return {
            "total": float(usdt.get("total", 0)),
            "free": float(usdt.get("free", 0)),
            "used": float(usdt.get("used", 0)),
        }

    async def fetch_positions(self, symbol: str | None = None) -> List[dict]:
        positions = await self._exchange.fetch_positions(symbol=[symbol] if symbol else None)
        return [
            {
                "symbol": p["symbol"],
                "side": p["side"],
                "size": float(p["contracts"] or 0),
                "entry_price": float(p["entryPrice"] or 0),
                "unrealized_pnl": float(p["unrealizedPnl"] or 0),
                "leverage": int(p.get("leverage", 1)),
            }
            for p in positions
            if float(p.get("contracts") or 0) != 0
        ]

    # ─────────────────── Order Execution ───────────────────

    async def create_market_order(
        self,
        symbol: str,
        side: str,  # "buy" | "sell"
        quantity: float,
        params: dict | None = None,
    ) -> dict:
        return await self._exchange.create_market_order(
            symbol, side.lower(), quantity, params=params or {}
        )

    async def create_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        params: dict | None = None,
    ) -> dict:
        return await self._exchange.create_limit_order(
            symbol, side.lower(), quantity, price, params=params or {}
        )

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        return await self._exchange.cancel_order(order_id, symbol)

    async def close_position(self, symbol: str, side: str, quantity: float) -> dict:
        """Close a position by placing an opposite market order."""
        close_side = "sell" if side.upper() == "BUY" else "buy"
        return await self.create_market_order(
            symbol, close_side, quantity, {"reduceOnly": True}
        )


class PaperBinanceClient(BinanceClient):
    """
    Paper trading client — fetches real market data but simulates orders.
    No real API key required for read-only data if keys are empty.
    """

    def __init__(self, api_key: str = "", secret_key: str = "", testnet: bool = True) -> None:
        self._paper_orders: List[dict] = []
        self._paper_balance = {"total": 10000.0, "free": 10000.0, "used": 0.0}
        self._paper_positions: List[dict] = []

        # Public-only exchange (no API keys) — used only for market data (OHLCV, ticker)
        # Binance rejects requests with invalid API keys even on public endpoints
        self._exchange = ccxt.binance(
            {
                "options": {"defaultType": "future"},
                "enableRateLimit": True,
            }
        )

    async def fetch_balance(self) -> dict:
        return self._paper_balance.copy()

    async def fetch_positions(self, symbol: str | None = None) -> List[dict]:
        if symbol:
            return [p for p in self._paper_positions if p["symbol"] == symbol]
        return self._paper_positions.copy()

    async def create_market_order(self, symbol: str, side: str, quantity: float, params=None) -> dict:
        order_id = f"paper_{len(self._paper_orders) + 1}"
        order = {
            "id": order_id,
            "symbol": symbol,
            "side": side.upper(),
            "quantity": quantity,
            "status": "filled",
            "paper": True,
        }
        self._paper_orders.append(order)
        return order

    async def create_limit_order(self, symbol: str, side: str, quantity: float, price: float, params=None) -> dict:
        return await self.create_market_order(symbol, side, quantity, params)

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        return {"id": order_id, "status": "cancelled", "paper": True}

    async def close_position(self, symbol: str, side: str, quantity: float) -> dict:
        return await self.create_market_order(symbol, "sell" if side == "BUY" else "buy", quantity)
