"""
Momentum / Breakout Strategy
Ported from python-trade/pro_scalping_system.py lines 4135-4250
EMA crossover + RSI confirmation + ATR-based TP/SL
"""
from __future__ import annotations
from typing import List
import pandas as pd

from .base import BaseStrategy, OrderSignal, PartialTPLevel
from ..core.smc import SMCResult


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    DEFAULT_PARAMS = {
        "fast_ema": 8,
        "slow_ema": 21,
        "trend_ema": 200,        # EMA200 as trend filter — only trade WITH trend
        "rsi_bull": 55.0,
        "rsi_bear": 45.0,
        "atr_tp_mult": 2.5,
        "atr_sl_mult": 1.2,
        "cooldown_bars": 10,     # longer cooldown to avoid noise
        "use_partial_tp": True,
        "trailing_stop": True,
        "require_volume": True,  # require above-average volume for entry
        "volume_mult": 1.2,      # volume must be > 1.2x 20-bar average
    }

    def __init__(
        self,
        symbol: str,
        base_lot: float = 0.001,
        fast_ema: int = 8,
        slow_ema: int = 21,
        trend_ema: int = 200,
        rsi_bull: float = 55.0,
        rsi_bear: float = 45.0,
        atr_tp_mult: float = 2.5,
        atr_sl_mult: float = 1.2,
        cooldown_bars: int = 10,
        use_partial_tp: bool = True,
        trailing_stop: bool = True,
        require_volume: bool = True,
        volume_mult: float = 1.2,
    ) -> None:
        super().__init__(symbol, base_lot)
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.trend_ema = trend_ema
        self.rsi_bull = rsi_bull
        self.rsi_bear = rsi_bear
        self.atr_tp_mult = atr_tp_mult
        self.atr_sl_mult = atr_sl_mult
        self.cooldown_bars = cooldown_bars
        self.use_partial_tp = use_partial_tp
        self.trailing_stop = trailing_stop
        self.require_volume = require_volume
        self.volume_mult = volume_mult

        self._last_signal_bar: int = -cooldown_bars
        self._bar_count: int = 0

    async def evaluate(
        self,
        df: pd.DataFrame,
        smc: SMCResult,
        indicators: dict,
        current_price: float,
    ) -> List[OrderSignal]:
        signals: List[OrderSignal] = []

        if not self.state.active:
            return signals

        self._bar_count += 1

        # Cooldown check
        if self._bar_count - self._last_signal_bar < self.cooldown_bars:
            return signals

        ind = indicators.get("last", {})
        ema8 = ind.get("ema8", current_price)
        ema21 = ind.get("ema21", current_price)
        ema200 = ind.get("ema200", current_price)  # trend filter
        rsi = ind.get("rsi", 50.0)
        atr = ind.get("atr", current_price * 0.001)

        # SIGNAL: SuperTrend direction FLIP (more reliable than EMA cross)
        # SuperTrend flip = trend change confirmed by volatility-adjusted price
        st_dir_arr = indicators.get("st_direction")
        if st_dir_arr is None or len(st_dir_arr) < 3:
            return signals

        prev_st = int(st_dir_arr[-2])
        curr_st = int(st_dir_arr[-1])

        bullish_flip = prev_st == -1 and curr_st == 1   # bearish→bullish flip
        bearish_flip = prev_st == 1  and curr_st == -1  # bullish→bearish flip

        # Volume confirmation
        vol_ok = True
        if self.require_volume:
            vol_arr = indicators.get("volume")
            if vol_arr is not None and len(vol_arr) >= 20:
                vol_avg = float(vol_arr[-20:].mean())
                vol_ok = vol_avg > 0 and float(vol_arr[-1]) >= vol_avg * self.volume_mult

        # TREND FILTER: only trade WITH EMA200 direction
        in_uptrend   = current_price > ema200
        in_downtrend = current_price < ema200

        # ADX FILTER: only trade in trending market
        adx = ind.get("adx", 0.0)
        is_trending = adx >= 20.0

        # RSI confirmation (not extreme)
        rsi_ok_bull = 45 <= rsi <= 70
        rsi_ok_bear = 30 <= rsi <= 55

        # Bullish: SuperTrend flips UP + in uptrend + volume + trending + RSI OK
        if bullish_flip and in_uptrend and vol_ok and is_trending and rsi_ok_bull and smc.bias != "BEARISH":
            sl = current_price - atr * self.atr_sl_mult
            sl_dist = max(current_price - sl, atr * 0.5)
            tp = current_price + sl_dist * self.atr_tp_mult if not self.use_partial_tp else None
            partial_tps = self.build_partial_tps("BUY", current_price, sl, atr) if self.use_partial_tp else []
            self._last_signal_bar = self._bar_count
            signals.append(
                OrderSignal(
                    strategy=self.name,
                    side="BUY",
                    quantity=self.base_lot,
                    entry_price=current_price,
                    stop_loss=sl,
                    take_profit=tp,
                    reason=f"ST flip BUY RSI={rsi:.0f} ADX={adx:.0f}",
                    partial_tps=partial_tps,
                    atr=atr,
                )
            )

        # Bearish: SuperTrend flips DOWN + in downtrend + volume + trending + RSI OK
        elif bearish_flip and in_downtrend and vol_ok and is_trending and rsi_ok_bear and smc.bias != "BULLISH":
            sl = current_price + atr * self.atr_sl_mult
            sl_dist = max(sl - current_price, atr * 0.5)
            tp = current_price - sl_dist * self.atr_tp_mult if not self.use_partial_tp else None
            partial_tps = self.build_partial_tps("SELL", current_price, sl, atr) if self.use_partial_tp else []
            self._last_signal_bar = self._bar_count
            signals.append(
                OrderSignal(
                    strategy=self.name,
                    side="SELL",
                    quantity=self.base_lot,
                    entry_price=current_price,
                    stop_loss=sl,
                    take_profit=tp,
                    reason=f"ST flip SELL RSI={rsi:.0f} ADX={adx:.0f}",
                    partial_tps=partial_tps,
                    atr=atr,
                )
            )

        return signals

    def dump_state(self) -> dict:
        return {
            "last_signal_bar": self._last_signal_bar,
            "bar_count": self._bar_count,
        }

    def load_state(self, state: dict) -> None:
        self._last_signal_bar = state.get("last_signal_bar", -self.cooldown_bars)
        self._bar_count = state.get("bar_count", 0)
