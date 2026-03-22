"""
Weighted signal aggregation (OctoBot-inspired).
Each evaluator scores in [-1, +1]. Trade fires when weighted sum >= THRESHOLD.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

THRESHOLD = 0.55


@dataclass
class AggregatedSignal:
    direction: str = "NEUTRAL"
    score: float = 0.0
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


def aggregate(
    smc_1m: Any,
    smc_15m: Any,
    smc_4h: Any,
    indicators: dict,
    current_price: float,
) -> AggregatedSignal:
    bull = 0.0
    bear = 0.0
    reasons: list[str] = []
    ind = indicators.get("last", {}) if indicators else {}

    # 4H HTF bias — weight 0.30
    bias_4h = getattr(smc_4h, "bias", "NEUTRAL") if smc_4h else "NEUTRAL"
    if bias_4h == "BULLISH":
        bull += 0.30; reasons.append("4H SMC Bullish")
    elif bias_4h == "BEARISH":
        bear += 0.30; reasons.append("4H SMC Bearish")

    # 15m structure — weight 0.20
    bias_15m = getattr(smc_15m, "bias", "NEUTRAL") if smc_15m else "NEUTRAL"
    if bias_15m == "BULLISH":
        bull += 0.20; reasons.append("15m Structure Bullish")
    elif bias_15m == "BEARISH":
        bear += 0.20; reasons.append("15m Structure Bearish")

    # Order Block proximity — weight 0.20
    obs = getattr(smc_1m, "order_blocks", []) if smc_1m else []
    for ob in (obs or [])[-3:]:
        ob_type = getattr(ob, "ob_type", "")
        ob_low = getattr(ob, "low", 0)
        ob_high = getattr(ob, "high", 0)
        if ob_type == "bullish" and ob_low and ob_high and ob_low <= current_price <= ob_high * 1.003:
            bull += 0.20; reasons.append("Near Bullish OB"); break
        elif ob_type == "bearish" and ob_low and ob_high and ob_low * 0.997 <= current_price <= ob_high:
            bear += 0.20; reasons.append("Near Bearish OB"); break

    # EMA alignment — weight 0.15
    ema8 = ind.get("ema8") or 0
    ema21 = ind.get("ema21") or 0
    ema55 = ind.get("ema55") or 0
    if ema8 and ema21 and ema55:
        if ema8 > ema21 > ema55:
            bull += 0.15; reasons.append("EMA8>21>55")
        elif ema8 < ema21 < ema55:
            bear += 0.15; reasons.append("EMA8<21<55")

    # SuperTrend — weight 0.10
    st = ind.get("supertrend_direction") or 0
    if st == 1:
        bull += 0.10; reasons.append("SuperTrend Up")
    elif st == -1:
        bear += 0.10; reasons.append("SuperTrend Down")

    # RSI — weight 0.05
    rsi = ind.get("rsi") or 50
    if rsi > 55:
        bull += 0.05; reasons.append(f"RSI {rsi:.0f}")
    elif rsi < 45:
        bear += 0.05; reasons.append(f"RSI {rsi:.0f}")

    net = round(bull - bear, 4)
    if net >= THRESHOLD:
        return AggregatedSignal("BUY", net, min(100, net * 100), reasons)
    elif net <= -THRESHOLD:
        return AggregatedSignal("SELL", net, min(100, abs(net) * 100), reasons)
    return AggregatedSignal("NEUTRAL", net, 0.0, reasons)
