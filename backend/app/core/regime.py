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
    active_strategies: list[str] = field(default_factory=lambda: ["martingale", "grid", "momentum"])
    description: str = ""


def classify(smc_4h: Any, indicators: dict) -> MarketRegime:
    ind = indicators.get("last", {}) if indicators else {}
    bias = (getattr(smc_4h, "bias", "NEUTRAL") if smc_4h else "NEUTRAL") or "NEUTRAL"
    adx = float(ind.get("adx") or 0)
    st = int(ind.get("supertrend_direction") or 0)

    if bias == "BULLISH" and adx > 25 and st == 1:
        return MarketRegime("TRENDING_UP", ["momentum"], f"Strong uptrend — ADX {adx:.0f}")
    elif bias == "BEARISH" and adx > 25 and st == -1:
        return MarketRegime("TRENDING_DOWN", ["momentum"], f"Strong downtrend — ADX {adx:.0f}")
    elif adx < 20:
        return MarketRegime("RANGING", ["grid", "martingale"], f"Ranging — ADX {adx:.0f}")
    else:
        return MarketRegime("TRANSITIONING", ["martingale"], f"Transitioning — ADX {adx:.0f}")
