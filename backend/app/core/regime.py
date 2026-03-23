"""
Market regime classifier — which strategy fits current conditions.
Pattern: Freqtrade + Jesse meta-controller.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketRegime:
    regime: str = "UNKNOWN"
    active_strategies: list[str] = field(default_factory=lambda: ["smc", "martingale", "grid", "momentum"])
    description: str = ""


def classify(smc_4h: Any, indicators: dict) -> MarketRegime:
    ind = indicators.get("last", {}) if indicators else {}
    # Use 4H bias if available; fall back to the SMCResult passed as smc_4h
    # (in backtest, the 1-minute SMCResult is passed when no 4H data exists)
    bias = (getattr(smc_4h, "bias", "NEUTRAL") if smc_4h else "NEUTRAL") or "NEUTRAL"
    adx = float(ind.get("adx") or 0)
    # NOTE: key is "st_direction" (not "supertrend_direction")
    st = int(ind.get("st_direction") or 0)

    # Strong trend — Donchian breakout + SMC structure trades
    if bias == "BULLISH" and adx > 20 and st >= 0:
        return MarketRegime("TRENDING_UP",   ["smc", "donchian", "martingale"], f"Uptrend — ADX {adx:.0f}")
    elif bias == "BEARISH" and adx > 20 and st <= 0:
        return MarketRegime("TRENDING_DOWN", ["smc", "donchian", "martingale"], f"Downtrend — ADX {adx:.0f}")
    elif adx < 18:
        # Ranging: grid ONLY — martingale gets direction wrong in choppy sideways market
        # Grid captures both bounces up and down without directional bias
        return MarketRegime("RANGING", ["grid"], f"Ranging — ADX {adx:.0f}")
    else:
        # Transitioning: martingale always active, donchian for momentum
        return MarketRegime("TRANSITIONING", ["smc", "donchian", "martingale", "grid"], f"Transitioning — ADX {adx:.0f}")
