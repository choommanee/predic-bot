"""
TradingEngine — asyncio orchestrator for all strategies.
Runs data loop, SMC analysis, strategy evaluation, order execution, and broadcasting.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
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
from ..strategies.smc import SMCStrategy
from ..strategies.martingale import MartingaleStrategy
from ..strategies.grid import GridStrategy
from ..strategies.momentum import MomentumStrategy
from ..core.mtf import get_mtf_context, MTFContext
from ..core.signal_aggregator import aggregate, AggregatedSignal
from ..core.regime import classify, MarketRegime

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
    6. Reconcile open trades (check SL/TP fills)
    """

    def __init__(self, override_config: dict | None = None) -> None:
        settings = get_settings()
        self.settings = settings

        # Merge override_config (from DB) on top of env settings
        cfg = override_config or {}
        self.symbol = cfg.get("trading_symbol", settings.trading_symbol)
        self.mode = cfg.get("trading_mode", settings.trading_mode)

        api_key = cfg.get("binance_api_key", settings.binance_api_key)
        secret_key = cfg.get("binance_secret_key", settings.binance_secret_key)
        testnet = cfg.get("binance_testnet", settings.binance_testnet)
        base_lot = float(cfg.get("base_lot_size", settings.base_lot_size))
        max_daily = float(cfg.get("max_daily_loss_usd", settings.max_daily_loss_usd))
        max_dd = float(cfg.get("max_drawdown_pct", settings.max_drawdown_pct))

        # Store for Claude AI key access
        self._anthropic_api_key = cfg.get("anthropic_api_key", settings.anthropic_api_key)

        # Exchange client
        if self.mode == "paper":
            self.exchange = PaperBinanceClient(api_key, secret_key, testnet)
        else:
            self.exchange = BinanceClient(api_key, secret_key, testnet)

        # Risk manager
        self.risk = RiskManager(
            max_daily_loss_usd=max_daily,
            max_drawdown_pct=max_dd,
            base_lot_size=base_lot,
        )

        # Strategies (all 4: SMC, Martingale, Grid, Momentum)
        self.strategies = {
            "smc": SMCStrategy(self.symbol, base_lot),
            "martingale": MartingaleStrategy(self.symbol, base_lot),
            "grid": GridStrategy(self.symbol, base_lot),
            "momentum": MomentumStrategy(self.symbol, base_lot),
        }

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._broadcast_callbacks: list[BroadcastCallback] = []
        self._cached_df: pd.DataFrame | None = None
        self._cached_indicators: dict = {}
        self._cached_smc: Any = None
        self._last_price: float = 0.0
        self._last_event: dict | None = None  # cached for immediate send on WS connect
        self._mtf_context: MTFContext | None = None
        self._regime: MarketRegime | None = None
        self._agg_signal: AggregatedSignal | None = None
        self._mtf_last_refresh: float = 0.0

        # DB factory — injected by main.py after engine creation
        self._db_factory = None

    # ─────────────────── Lifecycle ───────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("TradingEngine started (mode=%s symbol=%s)", self.mode, self.symbol)
        self._tasks = [
            asyncio.create_task(self._ticker_loop(), name="ticker_loop"),
            asyncio.create_task(self._data_loop(), name="data_loop"),
            asyncio.create_task(self._risk_monitor(), name="risk_monitor"),
            asyncio.create_task(self._reconciliation_loop(), name="reconciliation_loop"),
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

    def set_db_factory(self, factory) -> None:
        """Inject DB session factory for persistent storage."""
        self._db_factory = factory

    async def init_from_db(self, db) -> None:
        """Load strategy configs and open trades from DB on startup."""
        from sqlalchemy import select
        from ..models.strategy_config import StrategyConfig
        from ..models.trade_execution import TradeExecution

        # Load strategy configs
        try:
            result = await db.execute(select(StrategyConfig))
            configs = result.scalars().all()
            for cfg in configs:
                if cfg.name in self.strategies:
                    strategy = self.strategies[cfg.name]
                    strategy.state.active = cfg.active
                    if cfg.params:
                        strategy.update_params(cfg.params)
            logger.info("Loaded %d strategy configs from DB", len(configs))
        except Exception as exc:
            logger.warning("Could not load strategy configs: %s", exc)

        # Load open trades into strategy state
        try:
            result = await db.execute(
                select(TradeExecution).where(TradeExecution.status == "open")
            )
            open_trades = result.scalars().all()
            for trade in open_trades:
                strategy = self.strategies.get(trade.strategy)
                if strategy:
                    strategy.state.open_orders.append({
                        "id": trade.id,
                        "side": trade.side,
                        "quantity": trade.quantity,
                        "entry": trade.entry_price,
                        "level": trade.level,
                        "sl_order_id": trade.sl_order_id,
                        "tp_order_id": trade.tp_order_id,
                    })
            logger.info("Loaded %d open trades from DB", len(open_trades))
        except Exception as exc:
            logger.warning("Could not load open trades: %s", exc)

    # ─────────────────── Loops ───────────────────

    async def _ticker_loop(self) -> None:
        """Broadcast live price every 5 seconds for real-time dashboard updates."""
        while self._running:
            try:
                ticker = await self.exchange.fetch_ticker(self.symbol)
                price = float(ticker.get("last") or ticker.get("close") or 0)
                if price and price != self._last_price:
                    self._last_price = price
                    await self._broadcast({
                        "type": "price_update",
                        "symbol": self.symbol,
                        "price": price,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    # Check paper SL/TP on every price tick
                    if self.mode == "paper" and self._cached_smc:
                        await self._check_paper_sl_tp(price)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Ticker loop error: %s", exc)
            await asyncio.sleep(5)

    async def _data_loop(self) -> None:
        """Fetch OHLCV and run strategy every 30s — fires extra on new candle close."""
        _last_candle_ts: str = ""
        while self._running:
            try:
                df = await self.exchange.fetch_ohlcv(self.symbol, "1m", 200)

                # Detect new 1-minute candle close — triggers immediate analysis
                latest_ts = str(df.index[-2]) if len(df) >= 2 else ""
                new_candle = latest_ts != _last_candle_ts
                _last_candle_ts = latest_ts
                self._cached_df = df

                indicators = ind_module.compute_all(df)
                self._cached_indicators = indicators

                smc_result = smc_module.analyze(df)
                self._cached_smc = smc_result

                current_price = float(df["close"].iloc[-1])

                # Refresh MTF every 5 minutes
                now = time.time()
                if now - self._mtf_last_refresh > 300:
                    self._mtf_context = await get_mtf_context(
                        self.exchange, self.symbol, smc_module, ind_module
                    )
                    self._mtf_last_refresh = now

                # Classify market regime
                self._regime = classify(
                    getattr(self._mtf_context, "smc_4h", None),
                    self._cached_indicators,
                )

                # Aggregate signal
                self._agg_signal = aggregate(
                    smc_result,
                    getattr(self._mtf_context, "smc_15m", None),
                    getattr(self._mtf_context, "smc_4h", None),
                    indicators,
                    current_price,
                )

                # Run Claude AI if enabled and mode allows
                ai_result = None
                if self._anthropic_api_key and self.mode in ("auto", "both"):
                    try:
                        ai_result = await asyncio.wait_for(
                            analyze_market(
                                df, smc_result, indicators, self.symbol, self._anthropic_api_key
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

            await asyncio.sleep(30)

    async def _run_strategies(
        self,
        df: pd.DataFrame,
        smc: Any,
        indicators: dict,
        current_price: float,
    ) -> list[OrderSignal]:
        fired: list[OrderSignal] = []

        active = self._regime.active_strategies if self._regime else list(self.strategies.keys())
        for name, strategy in self.strategies.items():
            if not strategy.state.active:
                continue
            if name not in active:
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
        """Place order on exchange, persist TradeExecution, place bracket orders."""
        try:
            if self.mode == "signal":
                # Signal-only: don't place orders, just broadcast
                return

            order = await self.exchange.create_market_order(
                self.symbol, signal.side, signal.quantity
            )
            order_id = order.get("id", f"paper_{int(time.time() * 1000)}")

            logger.info(
                "Order placed: %s %s %.6f @ ~%.4f (%s)",
                signal.side, self.symbol, signal.quantity,
                signal.entry_price, signal.strategy,
            )

            # Place bracket orders (SL + TP)
            bracket = await self.exchange.place_bracket_orders(
                self.symbol,
                order_id,
                signal.side,
                signal.quantity,
                signal.stop_loss,
                signal.take_profit,
            )

            # Persist to DB
            if self._db_factory:
                await self._save_trade_execution(signal, order_id, bracket)

        except Exception as exc:
            logger.error("Order execution failed: %s", exc)

    async def _save_trade_execution(self, signal: OrderSignal, order_id: str, bracket: dict) -> None:
        """Save a new TradeExecution record to the database."""
        from ..models.trade_execution import TradeExecution
        try:
            async with self._db_factory() as db:
                trade = TradeExecution(
                    id=order_id,
                    strategy=signal.strategy,
                    symbol=self.symbol,
                    side=signal.side,
                    quantity=signal.quantity,
                    entry_price=signal.entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    level=signal.level,
                    reason=signal.reason,
                    sl_order_id=bracket.get("sl_order_id"),
                    tp_order_id=bracket.get("tp_order_id"),
                    status="open",
                )
                db.add(trade)
                await db.commit()
        except Exception as exc:
            logger.error("Failed to save trade execution: %s", exc)

    async def _check_paper_sl_tp(self, current_price: float) -> None:
        """Paper mode: check if SL or TP has been hit on any open trade."""
        if not self._db_factory:
            return
        from sqlalchemy import select
        from ..models.trade_execution import TradeExecution
        from datetime import datetime, timezone

        try:
            async with self._db_factory() as db:
                result = await db.execute(
                    select(TradeExecution).where(TradeExecution.status == "open")
                )
                open_trades = result.scalars().all()

                for trade in open_trades:
                    hit_tp = hit_sl = False
                    if trade.side == "BUY":
                        if trade.take_profit and current_price >= trade.take_profit:
                            hit_tp = True
                        elif trade.stop_loss and current_price <= trade.stop_loss:
                            hit_sl = True
                    else:  # SELL
                        if trade.take_profit and current_price <= trade.take_profit:
                            hit_tp = True
                        elif trade.stop_loss and current_price >= trade.stop_loss:
                            hit_sl = True

                    if hit_tp or hit_sl:
                        exit_price = trade.take_profit if hit_tp else trade.stop_loss
                        mult = 1 if trade.side == "BUY" else -1
                        pnl = (exit_price - trade.entry_price) * trade.quantity * mult

                        trade.status = "closed"
                        trade.exit_price = exit_price
                        trade.pnl = round(pnl, 4)
                        trade.closed_at = datetime.now(timezone.utc)
                        await db.commit()

                        strategy = self.strategies.get(trade.strategy)
                        if strategy:
                            strategy.on_close(pnl)

                        label = "TP" if hit_tp else "SL"
                        logger.info(
                            "Paper %s hit: %s %s pnl=%.4f", label, trade.strategy, trade.id, pnl
                        )
                        await self._broadcast({
                            "type": "trade_closed",
                            "trade_id": trade.id,
                            "strategy": trade.strategy,
                            "exit_price": exit_price,
                            "pnl": round(pnl, 4),
                            "reason": label,
                        })
        except Exception as exc:
            logger.debug("Paper SL/TP check error: %s", exc)

    async def _reconciliation_loop(self) -> None:
        """Every 30s: check if SL/TP orders on exchange have been filled."""
        while self._running:
            try:
                if self.mode != "paper" and self._db_factory:
                    await self._reconcile_open_trades()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Reconciliation error: %s", exc)
            await asyncio.sleep(30)

    async def _reconcile_open_trades(self) -> None:
        """Check exchange for filled SL/TP orders and close matching DB trades."""
        from sqlalchemy import select
        from ..models.trade_execution import TradeExecution
        from datetime import datetime, timezone

        try:
            open_orders_on_exchange = await self.exchange.fetch_open_orders(self.symbol)
            open_order_ids = {o["id"] for o in open_orders_on_exchange}
        except Exception as exc:
            logger.debug("fetch_open_orders failed: %s", exc)
            return

        async with self._db_factory() as db:
            result = await db.execute(
                select(TradeExecution).where(TradeExecution.status == "open")
            )
            open_trades = result.scalars().all()

            for trade in open_trades:
                # If both SL and TP orders are no longer open, the trade was closed
                sl_filled = trade.sl_order_id and trade.sl_order_id not in open_order_ids
                tp_filled = trade.tp_order_id and trade.tp_order_id not in open_order_ids

                if (trade.sl_order_id or trade.tp_order_id) and (sl_filled or tp_filled):
                    exit_price = self._last_price or trade.entry_price
                    mult = 1 if trade.side == "BUY" else -1
                    pnl = (exit_price - trade.entry_price) * trade.quantity * mult

                    trade.status = "closed"
                    trade.exit_price = exit_price
                    trade.pnl = round(pnl, 4)
                    trade.closed_at = datetime.now(timezone.utc)
                    await db.commit()

                    strategy = self.strategies.get(trade.strategy)
                    if strategy:
                        strategy.on_close(pnl)

                    logger.info("Trade reconciled as closed: %s pnl=%.4f", trade.id, pnl)
                    await self._broadcast({
                        "type": "trade_closed",
                        "trade_id": trade.id,
                        "strategy": trade.strategy,
                        "exit_price": exit_price,
                        "pnl": round(pnl, 4),
                    })

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
        if event.get("type") == "market_update":
            self._last_event = event
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
        base = {
            "mode": self.mode,
            "symbol": self.symbol,
            "running": self._running,
            "price": self._last_price,
            "strategies": {
                name: {
                    "active": s.state.active,
                    "open_orders": len(s.state.open_orders),
                    "daily_pnl": round(s.state.daily_pnl, 4),
                    "total_pnl": round(s.state.total_pnl, 4),
                    "params": s.get_params(),
                }
                for name, s in self.strategies.items()
            },
            "indicators": ind,
            "smc_bias": smc.bias if smc else "NEUTRAL",
            "regime": self._regime.regime if self._regime else "UNKNOWN",
            "agg_signal": {
                "direction": self._agg_signal.direction,
                "score": round(self._agg_signal.score, 3),
            } if self._agg_signal else None,
        }
        # Merge last market_update so reconnecting clients get full state
        if self._last_event:
            base = {**self._last_event, **base, "type": "status"}
        return base

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
            "regime": {
                "type": self._regime.regime,
                "active_strategies": self._regime.active_strategies,
                "description": self._regime.description,
            } if self._regime else None,
            "mtf": {
                "bias_4h": self._mtf_context.bias_4h,
                "structure_15m": self._mtf_context.structure_15m,
                "aligned": self._mtf_context.aligned,
            } if self._mtf_context else None,
            "agg_signal": {
                "direction": self._agg_signal.direction,
                "score": round(self._agg_signal.score, 3),
                "confidence": round(self._agg_signal.confidence, 1),
                "reasons": self._agg_signal.reasons,
            } if self._agg_signal else None,
            "strategy_stats": {
                name: {
                    "active": s.state.active,
                    "open_orders": len(s.state.open_orders),
                    "daily_pnl": round(s.state.daily_pnl, 4),
                }
                for name, s in self.strategies.items()
            },
        }
