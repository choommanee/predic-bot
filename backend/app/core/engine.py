"""
TradingEngine — asyncio orchestrator for all strategies.
Runs data loop, SMC analysis, strategy evaluation, order execution, and broadcasting.
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

import pandas as pd

from ..config import get_settings
from ..core import indicators as ind_module
from ..core import smc as smc_module
from ..core.claude_ai import analyze_market
from ..core.risk import RiskManager
from ..exchange.binance_client import BinanceClient, PaperBinanceClient
from ..strategies.base import OrderSignal
from ..strategies.martingale import MartingaleStrategy
from ..strategies.grid import GridStrategy
from ..strategies.momentum import MomentumStrategy

logger = logging.getLogger(__name__)

BroadcastCallback = Callable[[dict], Awaitable[None]]


class TradingEngine:
    """
    Manages the full trading lifecycle:
    1. Fetch OHLCV from Binance every candle
    2. Run SMC + indicator analysis
    3. Evaluate active strategies
    4. Execute orders (real or paper)
    5. Broadcast events to WebSocket + Telegram
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.symbol = settings.trading_symbol
        self.mode = settings.trading_mode  # paper | signal | auto | both

        # Exchange client
        if self.mode == "paper":
            self.exchange = PaperBinanceClient(
                settings.binance_api_key, settings.binance_secret_key, settings.binance_testnet
            )
        else:
            self.exchange = BinanceClient(
                settings.binance_api_key, settings.binance_secret_key, settings.binance_testnet
            )

        # Risk manager
        self.risk = RiskManager(
            max_daily_loss_usd=settings.max_daily_loss_usd,
            max_drawdown_pct=settings.max_drawdown_pct,
            base_lot_size=settings.base_lot_size,
        )

        # Strategies
        self.strategies = {
            "martingale": MartingaleStrategy(self.symbol, settings.base_lot_size),
            "grid": GridStrategy(self.symbol, settings.base_lot_size),
            "momentum": MomentumStrategy(self.symbol, settings.base_lot_size),
        }

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._broadcast_callbacks: list[BroadcastCallback] = []
        self._cached_df: pd.DataFrame | None = None
        self._cached_indicators: dict = {}
        self._cached_smc: Any = None

    # ─────────────────── Lifecycle ───────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("TradingEngine started (mode=%s symbol=%s)", self.mode, self.symbol)
        self._tasks = [
            asyncio.create_task(self._data_loop(), name="data_loop"),
            asyncio.create_task(self._risk_monitor(), name="risk_monitor"),
        ]

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.exchange.close()
        logger.info("TradingEngine stopped")

    def add_broadcast_callback(self, cb: BroadcastCallback) -> None:
        self._broadcast_callbacks.append(cb)

    # ─────────────────── Loops ───────────────────

    async def _data_loop(self) -> None:
        """Fetch OHLCV and run strategy every 60s (aligned to candle close)."""
        while self._running:
            try:
                df = await self.exchange.fetch_ohlcv(self.symbol, "1m", 200)
                self._cached_df = df

                indicators = ind_module.compute_all(df)
                self._cached_indicators = indicators

                smc_result = smc_module.analyze(df)
                self._cached_smc = smc_result

                current_price = float(df["close"].iloc[-1])

                # Run Claude AI if enabled and mode allows
                ai_result = None
                if self.settings.anthropic_api_key and self.mode in ("auto", "both"):
                    try:
                        ai_result = await asyncio.wait_for(
                            analyze_market(
                                df, smc_result, indicators, self.symbol, self.settings.anthropic_api_key
                            ),
                            timeout=15.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Claude AI timeout")

                # Get account balance for risk checks
                balance = await self.exchange.fetch_balance()
                equity = balance["total"]
                self.risk.update_equity_peak(equity)

                allowed, reason = self.risk.can_trade(equity)

                signals_fired = []
                if allowed and self.mode in ("auto", "both", "paper"):
                    signals_fired = await self._run_strategies(df, smc_result, indicators, current_price)

                # Build event for broadcast
                event = self._build_event(
                    current_price, indicators, smc_result, balance, signals_fired, ai_result
                )
                await self._broadcast(event)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Data loop error: %s", exc, exc_info=True)

            await asyncio.sleep(60)

    async def _run_strategies(
        self,
        df: pd.DataFrame,
        smc: Any,
        indicators: dict,
        current_price: float,
    ) -> list[OrderSignal]:
        fired: list[OrderSignal] = []

        for name, strategy in self.strategies.items():
            if not strategy.state.active:
                continue
            try:
                signals = await strategy.evaluate(df, smc, indicators, current_price)
                for signal in signals:
                    await self._execute_signal(signal)
                    fired.append(signal)
            except Exception as exc:
                logger.error("Strategy %s error: %s", name, exc)

        return fired

    async def _execute_signal(self, signal: OrderSignal) -> None:
        """Place order on exchange or simulate for paper trading."""
        try:
            if self.mode in ("signal",):
                # Signal-only: don't place orders, just broadcast
                return

            order = await self.exchange.create_market_order(
                self.symbol, signal.side, signal.quantity
            )
            logger.info(
                "Order placed: %s %s %.6f @ ~%.4f (%s)",
                signal.side, self.symbol, signal.quantity,
                signal.entry_price, signal.strategy,
            )
        except Exception as exc:
            logger.error("Order execution failed: %s", exc)

    async def _risk_monitor(self) -> None:
        """Monitor risk every 30s, emergency close if limits hit."""
        while self._running:
            try:
                balance = await self.exchange.fetch_balance()
                equity = balance["total"]
                allowed, reason = self.risk.can_trade(equity)
                if not allowed:
                    logger.warning("Risk limit: %s — disabling strategies", reason)
                    for s in self.strategies.values():
                        s.state.active = False
                    await self._broadcast({"type": "risk_alert", "message": reason})
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Risk monitor error: %s", exc)
            await asyncio.sleep(30)

    async def _broadcast(self, event: dict) -> None:
        for cb in self._broadcast_callbacks:
            try:
                await cb(event)
            except Exception as exc:
                logger.error("Broadcast error: %s", exc)

    # ─────────────────── Strategy Control ───────────────────

    def set_strategy_active(self, name: str, active: bool) -> bool:
        if name in self.strategies:
            self.strategies[name].state.active = active
            return True
        return False

    def get_status(self) -> dict:
        ind = self._cached_indicators.get("last", {})
        smc = self._cached_smc
        return {
            "mode": self.mode,
            "symbol": self.symbol,
            "running": self._running,
            "strategies": {
                name: s.state.active for name, s in self.strategies.items()
            },
            "indicators": ind,
            "smc_bias": smc.bias if smc else "NEUTRAL",
        }

    # ─────────────────── Event Builder ───────────────────

    def _build_event(
        self,
        price: float,
        indicators: dict,
        smc: Any,
        balance: dict,
        signals: list[OrderSignal],
        ai: dict | None,
    ) -> dict:
        ind = indicators.get("last", {})
        return {
            "type": "market_update",
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": self.symbol,
            "price": price,
            "balance": balance,
            "indicators": ind,
            "smc": {
                "bias": smc.bias if smc else "NEUTRAL",
                "bullish_bos": smc.bullish_bos if smc else 0,
                "bearish_bos": smc.bearish_bos if smc else 0,
                "bullish_obs": smc.bullish_obs if smc else 0,
                "bearish_obs": smc.bearish_obs if smc else 0,
            },
            "signals": [
                {
                    "strategy": s.strategy,
                    "side": s.side,
                    "quantity": s.quantity,
                    "price": s.entry_price,
                    "reason": s.reason,
                }
                for s in signals
            ],
            "ai": ai,
        }
