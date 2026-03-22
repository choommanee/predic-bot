"""
TradingEngine — asyncio orchestrator for all strategies.

Features vs previous version:
  - ATR-based dynamic lot sizing via RiskManager.smart_lot()
  - Max concurrent position cap before each signal
  - TrailingStopManager integrated into _ticker_loop (every 5s)
  - Partial TP: engine closes partial qty at each TP level
  - Claude AI signal fed into signal_aggregator (not just broadcast)
  - PortfolioStats: rolling win rate, Sharpe, max DD tracked live
  - Paper SL/TP check + trailing via _ticker_loop (every 5s)
  - Data loop every 30s with candle-close detection
"""
from __future__ import annotations
import asyncio
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
from ..core.trailing_stop import TrailingStopManager
from ..core.portfolio_stats import PortfolioStats
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
    def __init__(self, override_config: dict | None = None) -> None:
        settings = get_settings()
        self.settings = settings

        cfg = override_config or {}
        self.symbol    = cfg.get("trading_symbol", settings.trading_symbol)
        self.mode      = cfg.get("trading_mode",   settings.trading_mode)

        api_key    = cfg.get("binance_api_key",    settings.binance_api_key)
        secret_key = cfg.get("binance_secret_key", settings.binance_secret_key)
        testnet    = cfg.get("binance_testnet",    settings.binance_testnet)
        base_lot   = float(cfg.get("base_lot_size",        settings.base_lot_size))
        max_daily  = float(cfg.get("max_daily_loss_usd",   settings.max_daily_loss_usd))
        max_dd     = float(cfg.get("max_drawdown_pct",     settings.max_drawdown_pct))

        self._anthropic_api_key = cfg.get("anthropic_api_key", settings.anthropic_api_key)
        self._last_ai_signal: dict | None = None   # cache Claude AI result

        # Exchange
        if self.mode == "paper":
            self.exchange = PaperBinanceClient(api_key, secret_key, testnet)
        else:
            self.exchange = BinanceClient(api_key, secret_key, testnet)

        # Risk manager (with ATR sizing + max positions)
        self.risk = RiskManager(
            max_daily_loss_usd=max_daily,
            max_drawdown_pct=max_dd,
            base_lot_size=base_lot,
            max_open_positions=int(cfg.get("max_open_positions", 5)),
            risk_per_trade_pct=float(cfg.get("risk_per_trade_pct", 1.0)),
            atr_lot_enabled=bool(cfg.get("atr_lot_enabled", True)),
        )

        # Trailing stop manager
        self.trailing = TrailingStopManager(
            atr_mult=float(cfg.get("trailing_atr_mult", 1.5)),
            activation_atr_mult=float(cfg.get("trailing_activation_mult", 1.0)),
        )

        # Portfolio stats tracker
        self.portfolio = PortfolioStats()

        # Strategies (all 4)
        self.strategies = {
            "smc":        SMCStrategy(self.symbol, base_lot),
            "martingale": MartingaleStrategy(self.symbol, base_lot),
            "grid":       GridStrategy(self.symbol, base_lot),
            "momentum":   MomentumStrategy(self.symbol, base_lot),
        }

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._broadcast_callbacks: list[BroadcastCallback] = []
        self._cached_df: pd.DataFrame | None = None
        self._cached_indicators: dict = {}
        self._cached_smc: Any = None
        self._last_price: float = 0.0
        self._last_atr:   float = 0.0
        self._last_event: dict | None = None
        self._mtf_context: MTFContext | None = None
        self._regime: MarketRegime | None = None
        self._agg_signal: AggregatedSignal | None = None
        self._mtf_last_refresh: float = 0.0
        self._db_factory = None

    # ─────────────────── Lifecycle ───────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("TradingEngine started (mode=%s symbol=%s)", self.mode, self.symbol)
        self._tasks = [
            asyncio.create_task(self._ticker_loop(),        name="ticker_loop"),
            asyncio.create_task(self._data_loop(),          name="data_loop"),
            asyncio.create_task(self._risk_monitor(),       name="risk_monitor"),
            asyncio.create_task(self._reconciliation_loop(),name="reconciliation_loop"),
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
        self._db_factory = factory

    async def init_from_db(self, db) -> None:
        """Load strategy configs and open trades from DB on startup."""
        from sqlalchemy import select
        from ..models.strategy_config import StrategyConfig
        from ..models.trade_execution import TradeExecution

        try:
            result = await db.execute(select(StrategyConfig))
            for cfg in result.scalars().all():
                if cfg.name in self.strategies:
                    s = self.strategies[cfg.name]
                    s.state.active = cfg.active
                    if cfg.params:
                        s.update_params(cfg.params)
            logger.info("Strategy configs loaded from DB")
        except Exception as exc:
            logger.warning("Could not load strategy configs: %s", exc)

        try:
            result = await db.execute(
                select(TradeExecution).where(TradeExecution.status == "open")
            )
            for trade in result.scalars().all():
                # Rebuild trailing stop state for open trades
                if trade.stop_loss:
                    self.trailing.register(
                        trade_id=trade.id,
                        strategy=trade.strategy,
                        side=trade.side,
                        entry_price=trade.entry_price,
                        quantity=trade.quantity,
                        initial_sl=trade.stop_loss,
                        atr_at_entry=self._last_atr,
                    )
                s = self.strategies.get(trade.strategy)
                if s:
                    s.state.open_orders.append({
                        "id": trade.id, "side": trade.side,
                        "quantity": trade.quantity, "entry": trade.entry_price,
                        "level": trade.level, "sl_order_id": trade.sl_order_id,
                        "tp_order_id": trade.tp_order_id,
                    })
            logger.info("Open trades loaded from DB")
        except Exception as exc:
            logger.warning("Could not load open trades: %s", exc)

        # Load closed trades into portfolio stats
        try:
            from datetime import timezone
            result = await db.execute(
                select(TradeExecution).where(TradeExecution.status == "closed")
            )
            for trade in result.scalars().all():
                if trade.pnl is not None:
                    self.portfolio.record_from_dict(
                        strategy=trade.strategy,
                        side=trade.side,
                        pnl=trade.pnl,
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price or trade.entry_price,
                        quantity=trade.quantity,
                        opened_at=trade.opened_at,
                        closed_at=trade.closed_at,
                    )
        except Exception as exc:
            logger.warning("Could not load trade history for stats: %s", exc)

    # ─────────────────── Loops ───────────────────

    async def _ticker_loop(self) -> None:
        """Every 5s: price update + trailing stop check + paper SL/TP."""
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

                    # ── Trailing stop processing (every tick) ──
                    atr = self._last_atr or price * 0.001
                    trail_actions = self.trailing.on_price_tick(price, atr)
                    for action in trail_actions:
                        if action["action"] == "close":
                            await self._close_trade_by_trailing(action, price)
                        elif action["action"] == "update_sl":
                            # Update DB record with new SL
                            await self._update_trade_sl(action["trade_id"], action["new_sl"])

                    # ── Paper mode SL/TP check ──
                    if self.mode == "paper":
                        await self._check_paper_sl_tp(price)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Ticker loop error: %s", exc)
            await asyncio.sleep(5)

    async def _data_loop(self) -> None:
        """Every 30s: OHLCV fetch, SMC analysis, strategy evaluation."""
        _last_candle_ts: str = ""
        while self._running:
            try:
                df = await self.exchange.fetch_ohlcv(self.symbol, "1m", 200)
                self._cached_df = df

                indicators = ind_module.compute_all(df)
                self._cached_indicators = indicators
                self._last_atr = float(indicators.get("last", {}).get("atr") or 0)

                # Also cache volume array for signal_aggregator
                if "volume" not in indicators:
                    indicators["volume"] = df["volume"].values

                smc_result = smc_module.analyze(df)
                self._cached_smc = smc_result

                current_price = float(df["close"].iloc[-1])

                # Detect new 1m candle close
                latest_ts = str(df.index[-2]) if len(df) >= 2 else ""
                _last_candle_ts = latest_ts

                # MTF refresh every 5 min
                now = time.time()
                if now - self._mtf_last_refresh > 300:
                    self._mtf_context = await get_mtf_context(
                        self.exchange, self.symbol, smc_module, ind_module
                    )
                    self._mtf_last_refresh = now

                # Market regime
                self._regime = classify(
                    getattr(self._mtf_context, "smc_4h", None),
                    self._cached_indicators,
                )

                # Claude AI (every 5 min — rate limited)
                if self._anthropic_api_key and now % 300 < 35:
                    try:
                        ai_raw = await asyncio.wait_for(
                            analyze_market(df, smc_result, indicators, self.symbol, self._anthropic_api_key),
                            timeout=15.0,
                        )
                        if ai_raw:
                            self._last_ai_signal = {
                                "direction": ai_raw.get("direction", "NEUTRAL"),
                                "confidence": float(ai_raw.get("confidence", 0)),
                            }
                    except asyncio.TimeoutError:
                        logger.warning("Claude AI timeout")

                # Signal aggregation — now includes AI + Volume
                self._agg_signal = aggregate(
                    smc_result,
                    getattr(self._mtf_context, "smc_15m", None),
                    getattr(self._mtf_context, "smc_4h", None),
                    indicators,
                    current_price,
                    ai_signal=self._last_ai_signal,
                )

                balance = await self.exchange.fetch_balance()
                equity = balance["total"]
                self.risk.update_equity_peak(equity)
                allowed, reason = self.risk.can_trade(equity)

                signals_fired: list[OrderSignal] = []
                if allowed and self.mode in ("auto", "both", "paper"):
                    signals_fired = await self._run_strategies(
                        df, smc_result, indicators, current_price, equity
                    )

                event = self._build_event(current_price, indicators, smc_result, balance, signals_fired)
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
        equity: float,
    ) -> list[OrderSignal]:
        fired: list[OrderSignal] = []
        active = self._regime.active_strategies if self._regime else list(self.strategies.keys())
        atr = self._last_atr or current_price * 0.001

        for name, strategy in self.strategies.items():
            if not strategy.state.active or name not in active:
                continue
            try:
                signals = await strategy.evaluate(df, smc, indicators, current_price)
                for signal in signals:
                    # ATR-based position sizing
                    lot = self.risk.smart_lot(equity, current_price, signal.stop_loss, atr)
                    signal.quantity = lot
                    signal.atr = atr

                    ok, deny_reason = self.risk.can_trade(equity)
                    if not ok:
                        logger.info("Signal skipped (%s): %s", name, deny_reason)
                        continue

                    await self._execute_signal(signal)
                    fired.append(signal)
            except Exception as exc:
                logger.error("Strategy %s error: %s", name, exc)
        return fired

    async def _execute_signal(self, signal: OrderSignal) -> None:
        """Place order + bracket + register trailing stop + persist to DB."""
        if self.mode == "signal":
            return
        try:
            order = await self.exchange.create_market_order(
                self.symbol, signal.side, signal.quantity
            )
            order_id = order.get("id", f"paper_{int(time.time() * 1000)}")

            logger.info("Order: %s %s %.6f @ ~%.4f [%s]",
                        signal.side, self.symbol, signal.quantity, signal.entry_price, signal.strategy)

            # Bracket orders (SL + TP)
            bracket = await self.exchange.place_bracket_orders(
                self.symbol, order_id, signal.side,
                signal.quantity, signal.stop_loss, signal.take_profit,
            )

            # Register trailing stop (if strategy supports it)
            strategy = self.strategies.get(signal.strategy)
            if getattr(strategy, "trailing_stop", False) and signal.stop_loss:
                self.trailing.register(
                    trade_id=order_id,
                    strategy=signal.strategy,
                    side=signal.side,
                    entry_price=signal.entry_price,
                    quantity=signal.quantity,
                    initial_sl=signal.stop_loss,
                    atr_at_entry=signal.atr,
                )

            # Track position count
            self.risk.on_position_opened(signal.quantity, signal.entry_price)

            # Persist
            if self._db_factory:
                await self._save_trade_execution(signal, order_id, bracket)

        except Exception as exc:
            logger.error("Order execution failed: %s", exc)

    async def _save_trade_execution(self, signal: OrderSignal, order_id: str, bracket: dict) -> None:
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
                    extra={"partial_tps": len(signal.partial_tps), "atr": signal.atr},
                )
                db.add(trade)
                await db.commit()
        except Exception as exc:
            logger.error("Failed to save trade: %s", exc)

    async def _close_trade_by_trailing(self, action: dict, current_price: float) -> None:
        """Close a trade that hit its trailing stop."""
        trade_id = action["trade_id"]
        exit_price = action.get("exit_price", current_price)
        state = action["state"]
        reason = action.get("reason", "trailing_sl_hit")

        # Update risk manager
        mult = 1 if state.side == "BUY" else -1
        pnl = (exit_price - state.entry_price) * state.quantity * mult
        self.risk.on_position_closed(pnl, state.quantity, exit_price)

        # Update strategy
        strategy = self.strategies.get(state.strategy)
        if strategy:
            strategy.on_close(pnl)

        # Update portfolio stats
        self.portfolio.record_from_dict(
            strategy=state.strategy,
            side=state.side,
            pnl=pnl,
            entry_price=state.entry_price,
            exit_price=exit_price,
            quantity=state.quantity,
        )

        # Persist
        if self._db_factory:
            await self._close_trade_in_db(trade_id, exit_price, pnl)

        await self._broadcast({
            "type": "trade_closed",
            "trade_id": trade_id,
            "strategy": state.strategy,
            "exit_price": exit_price,
            "pnl": round(pnl, 4),
            "reason": reason,
        })
        logger.info("Trailing close %s: pnl=%.4f reason=%s", trade_id, pnl, reason)

    async def _close_trade_in_db(self, trade_id: str, exit_price: float, pnl: float) -> None:
        from sqlalchemy import select
        from ..models.trade_execution import TradeExecution
        try:
            async with self._db_factory() as db:
                result = await db.execute(
                    select(TradeExecution).where(TradeExecution.id == trade_id)
                )
                trade = result.scalar_one_or_none()
                if trade:
                    trade.status = "closed"
                    trade.exit_price = exit_price
                    trade.pnl = round(pnl, 4)
                    trade.closed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception as exc:
            logger.error("DB close trade failed: %s", exc)

    async def _update_trade_sl(self, trade_id: str, new_sl: float) -> None:
        """Update the stop_loss field in DB as trailing moves it."""
        from sqlalchemy import select
        from ..models.trade_execution import TradeExecution
        try:
            async with self._db_factory() as db:
                result = await db.execute(
                    select(TradeExecution).where(TradeExecution.id == trade_id)
                )
                trade = result.scalar_one_or_none()
                if trade:
                    trade.stop_loss = new_sl
                    await db.commit()
        except Exception as exc:
            logger.debug("Update SL failed: %s", exc)

    async def _check_paper_sl_tp(self, current_price: float) -> None:
        """Paper mode: check fixed SL/TP on open trades every tick."""
        if not self._db_factory:
            return
        from sqlalchemy import select
        from ..models.trade_execution import TradeExecution

        try:
            async with self._db_factory() as db:
                result = await db.execute(
                    select(TradeExecution).where(TradeExecution.status == "open")
                )
                for trade in result.scalars().all():
                    # Skip if trailing stop is tracking this trade
                    if trade.id in {s.trade_id for s in self.trailing._states.values()}:
                        continue

                    hit_tp = hit_sl = False
                    if trade.side == "BUY":
                        if trade.take_profit and current_price >= trade.take_profit: hit_tp = True
                        elif trade.stop_loss  and current_price <= trade.stop_loss:  hit_sl = True
                    else:
                        if trade.take_profit and current_price <= trade.take_profit: hit_tp = True
                        elif trade.stop_loss  and current_price >= trade.stop_loss:  hit_sl = True

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

                        self.risk.on_position_closed(pnl, trade.quantity, exit_price)
                        self.portfolio.record_from_dict(
                            strategy=trade.strategy, side=trade.side,
                            pnl=pnl, entry_price=trade.entry_price,
                            exit_price=exit_price, quantity=trade.quantity,
                        )

                        label = "TP" if hit_tp else "SL"
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
        """Every 30s: sync with exchange fills for live mode."""
        while self._running:
            try:
                if self.mode not in ("paper", "signal") and self._db_factory:
                    await self._reconcile_open_trades()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Reconciliation error: %s", exc)
            await asyncio.sleep(30)

    async def _reconcile_open_trades(self) -> None:
        from sqlalchemy import select
        from ..models.trade_execution import TradeExecution

        try:
            open_orders_ex = await self.exchange.fetch_open_orders(self.symbol)
            open_ids = {o["id"] for o in open_orders_ex}
        except Exception as exc:
            logger.debug("fetch_open_orders failed: %s", exc)
            return

        async with self._db_factory() as db:
            result = await db.execute(
                select(TradeExecution).where(TradeExecution.status == "open")
            )
            for trade in result.scalars().all():
                sl_gone = trade.sl_order_id and trade.sl_order_id not in open_ids
                tp_gone = trade.tp_order_id and trade.tp_order_id not in open_ids
                if (trade.sl_order_id or trade.tp_order_id) and (sl_gone or tp_gone):
                    exit_price = self._last_price or trade.entry_price
                    mult = 1 if trade.side == "BUY" else -1
                    pnl = (exit_price - trade.entry_price) * trade.quantity * mult

                    trade.status = "closed"
                    trade.exit_price = exit_price
                    trade.pnl = round(pnl, 4)
                    trade.closed_at = datetime.now(timezone.utc)
                    await db.commit()

                    self.trailing.unregister(trade.id)
                    strategy = self.strategies.get(trade.strategy)
                    if strategy:
                        strategy.on_close(pnl)
                    self.risk.on_position_closed(pnl, trade.quantity, exit_price)
                    self.portfolio.record_from_dict(
                        strategy=trade.strategy, side=trade.side,
                        pnl=pnl, entry_price=trade.entry_price,
                        exit_price=exit_price, quantity=trade.quantity,
                    )
                    await self._broadcast({
                        "type": "trade_closed", "trade_id": trade.id,
                        "strategy": trade.strategy, "exit_price": exit_price, "pnl": round(pnl, 4),
                    })

    async def _risk_monitor(self) -> None:
        while self._running:
            try:
                balance = await self.exchange.fetch_balance()
                equity  = balance["total"]
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

    # ─────────────────── Control & Status ───────────────────

    def set_strategy_active(self, name: str, active: bool) -> bool:
        if name in self.strategies:
            self.strategies[name].state.active = active
            return True
        return False

    def get_status(self) -> dict:
        ind = self._cached_indicators.get("last", {})
        smc = self._cached_smc
        metrics = self.portfolio.compute()
        base = {
            "mode":    self.mode,
            "symbol":  self.symbol,
            "running": self._running,
            "price":   self._last_price,
            "strategies": {
                name: {
                    "active":      s.state.active,
                    "open_orders": len(s.state.open_orders),
                    "daily_pnl":   round(s.state.daily_pnl, 4),
                    "total_pnl":   round(s.state.total_pnl, 4),
                    "win_rate":    s.state.win_rate,
                    "params":      s.get_params(),
                }
                for name, s in self.strategies.items()
            },
            "indicators":   ind,
            "smc_bias":     smc.bias if smc else "NEUTRAL",
            "regime":       self._regime.regime if self._regime else "UNKNOWN",
            "agg_signal": {
                "direction":  self._agg_signal.direction,
                "score":      round(self._agg_signal.score, 3),
                "confidence": round(self._agg_signal.confidence, 1),
                "reasons":    self._agg_signal.reasons,
            } if self._agg_signal else None,
            "portfolio": {
                "total_trades":      metrics.total_trades,
                "win_rate":          metrics.win_rate,
                "sharpe_ratio":      metrics.sharpe_ratio,
                "profit_factor":     metrics.profit_factor,
                "max_drawdown_pct":  metrics.max_drawdown_pct,
                "avg_rr":            metrics.avg_rr,
                "total_pnl":         metrics.total_pnl,
                "daily_pnl":         metrics.daily_pnl,
                "best_trade":        metrics.best_trade,
                "worst_trade":       metrics.worst_trade,
                "by_strategy":       metrics.by_strategy,
            },
            "risk": self.risk.risk_summary(self._last_price or 1.0),
            "trailing_active": len(self.trailing),
        }
        if self._last_event:
            base = {**self._last_event, **base, "type": "status"}
        return base

    def _build_event(self, price, indicators, smc, balance, signals):
        ind = indicators.get("last", {})
        metrics = self.portfolio.compute()
        return {
            "type":   "market_update",
            "ts":     datetime.now(timezone.utc).isoformat(),
            "symbol": self.symbol,
            "price":  price,
            "balance": balance,
            "indicators": ind,
            "smc": {
                "bias":         smc.bias if smc else "NEUTRAL",
                "bullish_bos":  smc.bullish_bos if smc else 0,
                "bearish_bos":  smc.bearish_bos if smc else 0,
                "bullish_obs":  smc.bullish_obs if smc else 0,
                "bearish_obs":  smc.bearish_obs if smc else 0,
            },
            "signals": [
                {
                    "strategy": s.strategy, "side": s.side,
                    "quantity": s.quantity,  "price": s.entry_price, "reason": s.reason,
                }
                for s in signals
            ],
            "ai": self._last_ai_signal,
            "regime": {
                "type": self._regime.regime,
                "active_strategies": self._regime.active_strategies,
                "description": self._regime.description,
            } if self._regime else None,
            "mtf": {
                "bias_4h":      self._mtf_context.bias_4h,
                "structure_15m":self._mtf_context.structure_15m,
                "aligned":      self._mtf_context.aligned,
            } if self._mtf_context else None,
            "agg_signal": {
                "direction":  self._agg_signal.direction,
                "score":      round(self._agg_signal.score, 3),
                "confidence": round(self._agg_signal.confidence, 1),
                "reasons":    self._agg_signal.reasons,
            } if self._agg_signal else None,
            "portfolio": {
                "win_rate":         metrics.win_rate,
                "sharpe_ratio":     metrics.sharpe_ratio,
                "profit_factor":    metrics.profit_factor,
                "max_drawdown_pct": metrics.max_drawdown_pct,
                "total_pnl":        metrics.total_pnl,
                "daily_pnl":        metrics.daily_pnl,
            },
            "risk": self.risk.risk_summary(price),
            "strategy_stats": {
                name: {
                    "active":      s.state.active,
                    "open_orders": len(s.state.open_orders),
                    "daily_pnl":   round(s.state.daily_pnl, 4),
                    "win_rate":    s.state.win_rate,
                }
                for name, s in self.strategies.items()
            },
        }
