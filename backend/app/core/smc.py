"""
Smart Money Concepts (SMC) Analysis
Ported from python-trade/pro_scalping_system.py lines 2629-2978
Pure functions — no class, no GUI dependencies.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
import numpy as np
import pandas as pd


# ─────────────────────────── data classes ────────────────────────────

@dataclass
class SwingPoint:
    index: int
    price: float
    is_high: bool
    label: str  # HH | HL | LH | LL


@dataclass
class StructureBreak:
    index: int
    price: float
    is_bullish: bool
    label: str  # BOS | CHoCH
    origin_index: int


@dataclass
class OrderBlock:
    high: float
    low: float
    index: int
    is_bullish: bool
    mitigated: bool = False


@dataclass
class FVG:
    high: float
    low: float
    index: int
    is_bullish: bool


@dataclass
class LiquidityZone:
    price: float
    index: int
    is_high: bool
    swept: bool = False


@dataclass
class SMCResult:
    swings: List[SwingPoint] = field(default_factory=list)
    breaks: List[StructureBreak] = field(default_factory=list)
    order_blocks: List[OrderBlock] = field(default_factory=list)
    fvgs: List[FVG] = field(default_factory=list)
    liquidity: List[LiquidityZone] = field(default_factory=list)

    # Derived bias
    bullish_bos: int = 0
    bearish_bos: int = 0
    bullish_obs: int = 0
    bearish_obs: int = 0
    bias: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL


# ───────────────────────── core functions ──────────────────────────

def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> List[SwingPoint]:
    """
    Detect swing highs/lows with HH/HL/LH/LL labels.
    Ported from pro_scalping_system.py:2632
    """
    swings: List[SwingPoint] = []
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    last_swing_high: float | None = None
    last_swing_low: float | None = None

    for i in range(lookback, n - lookback):
        # Swing High
        is_swing_high = all(high[i] > high[i - j] and high[i] > high[i + j] for j in range(1, lookback + 1))
        if is_swing_high:
            label = "HH" if last_swing_high is None or high[i] > last_swing_high else "LH"
            last_swing_high = high[i]
            swings.append(SwingPoint(i, high[i], True, label))

        # Swing Low
        is_swing_low = all(low[i] < low[i - j] and low[i] < low[i + j] for j in range(1, lookback + 1))
        if is_swing_low:
            label = "LL" if last_swing_low is None or low[i] < last_swing_low else "HL"
            last_swing_low = low[i]
            swings.append(SwingPoint(i, low[i], False, label))

    return swings


def find_structure_breaks(df: pd.DataFrame, swings: List[SwingPoint]) -> List[StructureBreak]:
    """
    Detect BOS (Break of Structure) and CHoCH (Change of Character).
    Ported from pro_scalping_system.py:2853
    """
    breaks: List[StructureBreak] = []
    close = df["close"].values
    n = len(df)

    swing_highs = [s for s in swings if s.is_high]
    swing_lows = [s for s in swings if not s.is_high]

    current_bias = 0  # 0=neutral, 1=bullish, -1=bearish

    # Bullish BOS/CHoCH
    for sh in swing_highs:
        for i in range(sh.index + 1, min(sh.index + 50, n)):
            if close[i] > sh.price:
                label = "CHoCH" if current_bias == -1 else "BOS"
                breaks.append(StructureBreak(i, sh.price, True, label, sh.index))
                current_bias = 1
                break

    # Bearish BOS/CHoCH
    for sl in swing_lows:
        for i in range(sl.index + 1, min(sl.index + 50, n)):
            if close[i] < sl.price:
                label = "CHoCH" if current_bias == 1 else "BOS"
                breaks.append(StructureBreak(i, sl.price, False, label, sl.index))
                current_bias = -1
                break

    breaks.sort(key=lambda x: x.index)
    return breaks[-20:]


def find_order_blocks(df: pd.DataFrame, swings: List[SwingPoint]) -> List[OrderBlock]:
    """
    Detect Order Blocks (last candle before strong move).
    Ported from pro_scalping_system.py:2889
    """
    obs: List[OrderBlock] = []
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    open_p = df["open"].values
    n = len(df)

    for swing in swings:
        if swing.index < 1 or swing.index >= n - 1:
            continue

        if not swing.is_high:  # Bullish OB near swing low
            for j in range(swing.index, max(0, swing.index - 10), -1):
                if close[j] < open_p[j]:  # bearish candle
                    obs.append(OrderBlock(high[j], low[j], j, True))
                    break
        else:  # Bearish OB near swing high
            for j in range(swing.index, max(0, swing.index - 10), -1):
                if close[j] > open_p[j]:  # bullish candle
                    obs.append(OrderBlock(high[j], low[j], j, False))
                    break

    return obs[-10:]


def find_fair_value_gaps(df: pd.DataFrame) -> List[FVG]:
    """
    Detect Fair Value Gaps (3-bar imbalances).
    Ported from pro_scalping_system.py:2962
    """
    fvgs: List[FVG] = []
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    for i in range(2, n):
        # Bullish FVG
        if low[i] > high[i - 2]:
            fvgs.append(FVG(low[i], high[i - 2], i, True))
        # Bearish FVG
        if high[i] < low[i - 2]:
            fvgs.append(FVG(low[i - 2], high[i], i, False))

    return fvgs[-10:]


def find_liquidity_zones(df: pd.DataFrame, lookback: int = 10) -> List[LiquidityZone]:
    """
    Detect Equal Highs/Lows (liquidity pools) and whether they've been swept.
    Ported from pro_scalping_system.py:2918
    """
    liquidity: List[LiquidityZone] = []
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    for i in range(lookback, n - lookback):
        is_high = all(high[i] > high[i - j] and high[i] > high[i + j] for j in range(1, lookback + 1))
        if is_high:
            liquidity.append(LiquidityZone(high[i], i, True))

        is_low = all(low[i] < low[i - j] and low[i] < low[i + j] for j in range(1, lookback + 1))
        if is_low:
            liquidity.append(LiquidityZone(low[i], i, False))

    for liq in liquidity:
        if liq.is_high:
            for i in range(liq.index + 1, n):
                if high[i] > liq.price:
                    liq.swept = True
                    break
        else:
            for i in range(liq.index + 1, n):
                if low[i] < liq.price:
                    liq.swept = True
                    break

    return [liq for liq in liquidity if not liq.swept][-6:]


def analyze(df: pd.DataFrame, lookback: int = 5) -> SMCResult:
    """
    Run full SMC analysis and return SMCResult with bias.
    Entry point for trading engine.
    """
    swings = find_swing_points(df, lookback)
    breaks = find_structure_breaks(df, swings)
    obs = find_order_blocks(df, swings)
    fvgs = find_fair_value_gaps(df)
    liquidity = find_liquidity_zones(df)

    recent = breaks[-10:] if breaks else []
    bull_bos = sum(1 for b in recent if b.is_bullish)
    bear_bos = sum(1 for b in recent if not b.is_bullish)
    bull_obs = sum(1 for o in obs if o.is_bullish)
    bear_obs = sum(1 for o in obs if not o.is_bullish)

    if bull_bos > bear_bos:
        bias = "BULLISH"
    elif bear_bos > bull_bos:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return SMCResult(
        swings=swings,
        breaks=breaks,
        order_blocks=obs,
        fvgs=fvgs,
        liquidity=liquidity,
        bullish_bos=bull_bos,
        bearish_bos=bear_bos,
        bullish_obs=bull_obs,
        bearish_obs=bear_obs,
        bias=bias,
    )


def check_entry_near_ob(
    current_price: float,
    obs: List[OrderBlock],
    direction: str,
    pip_value: float = 0.01,
    tolerance_pips: int = 10,
) -> bool:
    """Return True if price is near/in a relevant Order Block."""
    tol = tolerance_pips * pip_value
    for ob in obs:
        if direction == "BUY" and ob.is_bullish:
            if ob.low <= current_price <= ob.high + tol:
                return True
        elif direction == "SELL" and not ob.is_bullish:
            if ob.low - tol <= current_price <= ob.high:
                return True
    return False
