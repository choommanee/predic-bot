"""
Weighted signal aggregation (OctoBot-inspired).
Each evaluator scores in [-1, +1]. Trade fires when weighted sum >= THRESHOLD.

Evaluators:
  1. 4H SMC bias         weight 0.25
  2. 15m structure       weight 0.15
  3. OB proximity        weight 0.15
  4. EMA alignment       weight 0.15
  5. SuperTrend          weight 0.10
  6. RSI extremes        weight 0.05
  7. Volume spike        weight 0.08  ← NEW
  8. Claude AI signal    weight 0.07  ← NEW
     Total               1.00
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
    ai_signal: dict | None = None,   # {"direction": "BUY"|"SELL"|"NEUTRAL", "confidence": 0-100}
) -> AggregatedSignal:
    bull = 0.0
    bear = 0.0
    reasons: list[str] = []
    ind = indicators.get("last", {}) if indicators else {}

    # ── 1. 4H HTF bias — weight 0.25 ──────────────────────
    bias_4h = getattr(smc_4h, "bias", "NEUTRAL") if smc_4h else "NEUTRAL"
    if bias_4h == "BULLISH":
        bull += 0.25; reasons.append("4H SMC Bullish")
    elif bias_4h == "BEARISH":
        bear += 0.25; reasons.append("4H SMC Bearish")

    # ── 2. 15m structure — weight 0.15 ───────────────────
    bias_15m = getattr(smc_15m, "bias", "NEUTRAL") if smc_15m else "NEUTRAL"
    if bias_15m == "BULLISH":
        bull += 0.15; reasons.append("15m Structure Bullish")
    elif bias_15m == "BEARISH":
        bear += 0.15; reasons.append("15m Structure Bearish")

    # ── 3. Order Block proximity — weight 0.15 ───────────
    obs = getattr(smc_1m, "order_blocks", []) if smc_1m else []
    for ob in (obs or [])[-3:]:
        ob_type = getattr(ob, "ob_type", "")
        ob_low  = getattr(ob, "low", 0)
        ob_high = getattr(ob, "high", 0)
        if ob_type == "bullish" and ob_low and ob_high and ob_low <= current_price <= ob_high * 1.003:
            bull += 0.15; reasons.append("Near Bullish OB"); break
        elif ob_type == "bearish" and ob_low and ob_high and ob_low * 0.997 <= current_price <= ob_high:
            bear += 0.15; reasons.append("Near Bearish OB"); break

    # ── 4. EMA alignment — weight 0.15 ───────────────────
    ema8  = ind.get("ema8")  or 0
    ema21 = ind.get("ema21") or 0
    ema55 = ind.get("ema55") or 0
    if ema8 and ema21 and ema55:
        if ema8 > ema21 > ema55:
            bull += 0.15; reasons.append("EMA8>21>55 bullish stack")
        elif ema8 < ema21 < ema55:
            bear += 0.15; reasons.append("EMA8<21<55 bearish stack")

    # ── 5. SuperTrend — weight 0.10 ──────────────────────
    st = int(ind.get("supertrend_direction") or 0)
    if st == 1:
        bull += 0.10; reasons.append("SuperTrend Up")
    elif st == -1:
        bear += 0.10; reasons.append("SuperTrend Down")

    # ── 6. RSI extremes — weight 0.05 ────────────────────
    rsi = ind.get("rsi") or 50
    if rsi > 55:
        bull += 0.05; reasons.append(f"RSI {rsi:.0f} bullish")
    elif rsi < 45:
        bear += 0.05; reasons.append(f"RSI {rsi:.0f} bearish")

    # ── 7. Volume spike confirmation — weight 0.08 ────── NEW
    # Volume spike = current volume > 1.5× 20-bar average volume
    volume_arr = indicators.get("volume") if indicators else None
    if volume_arr is not None and len(volume_arr) >= 20:
        import numpy as np
        avg_vol = float(np.mean(volume_arr[-20:-1]))
        cur_vol = float(volume_arr[-1])
        if avg_vol > 0 and cur_vol > avg_vol * 1.5:
            # Volume spike confirms whichever direction is leading
            if bull >= bear:
                bull += 0.08; reasons.append(f"Volume spike ×{cur_vol/avg_vol:.1f} bull confirm")
            else:
                bear += 0.08; reasons.append(f"Volume spike ×{cur_vol/avg_vol:.1f} bear confirm")

    # ── 8. Claude AI signal — weight 0.07 ─────────────── NEW
    if ai_signal:
        ai_dir = ai_signal.get("direction", "NEUTRAL")
        ai_conf = float(ai_signal.get("confidence", 0)) / 100.0  # normalize 0-1
        contribution = 0.07 * min(ai_conf, 1.0)
        if ai_dir == "BUY" and contribution > 0:
            bull += contribution; reasons.append(f"Claude AI BUY conf={ai_conf*100:.0f}%")
        elif ai_dir == "SELL" and contribution > 0:
            bear += contribution; reasons.append(f"Claude AI SELL conf={ai_conf*100:.0f}%")

    net = round(bull - bear, 4)
    if net >= THRESHOLD:
        return AggregatedSignal("BUY", net, min(100.0, net * 100), reasons)
    elif net <= -THRESHOLD:
        return AggregatedSignal("SELL", net, min(100.0, abs(net) * 100), reasons)
    return AggregatedSignal("NEUTRAL", net, 0.0, reasons)
