"""
Technical Indicators - ported from python-trade/pro_scalping_system.py
Pure NumPy functions, no class dependencies.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Tuple


def calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average (ported from pro_scalping_system.py:2441)"""
    ema = np.zeros_like(prices, dtype=float)
    multiplier = 2 / (period + 1)
    ema[0] = prices[0]
    for i in range(1, len(prices)):
        ema[i] = (prices[i] - ema[i - 1]) * multiplier + ema[i - 1]
    return ema


def _smooth(data: np.ndarray, period: int) -> np.ndarray:
    """Wilder smoothing used by ADX (ported from pro_scalping_system.py:2566)"""
    result = np.zeros_like(data, dtype=float)
    if len(data) < period:
        return result
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = (result[i - 1] * (period - 1) + data[i]) / period
    return result


def calculate_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index (ported from pro_scalping_system.py:2507)"""
    n = len(prices)
    rsi = np.full(n, 50.0)

    if n < period + 1:
        return rsi

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.zeros(n)
    avg_loss = np.zeros(n)

    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])

    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

    for i in range(period, n):
        if avg_loss[i] == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def calculate_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range (ported from pro_scalping_system.py:2576)"""
    n = len(high)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    atr = np.zeros(n)
    if n >= period:
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


def calculate_adx(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ADX, +DI, -DI (ported from pro_scalping_system.py:2538)"""
    n = len(high)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        h_diff = high[i] - high[i - 1]
        l_diff = low[i - 1] - low[i]
        plus_dm[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
        minus_dm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    smoothed_tr = _smooth(tr, period)
    plus_di = 100 * _smooth(plus_dm, period) / np.where(smoothed_tr == 0, 1, smoothed_tr)
    minus_di = 100 * _smooth(minus_dm, period) / np.where(smoothed_tr == 0, 1, smoothed_tr)

    dx = 100 * np.abs(plus_di - minus_di) / np.where(
        (plus_di + minus_di) == 0, 1, plus_di + minus_di
    )
    adx = _smooth(dx, period)

    return adx, plus_di, minus_di


def calculate_supertrend(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 10,
    multiplier: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """SuperTrend (ported from pro_scalping_system.py:2450). Returns (supertrend, direction)."""
    n = len(high)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    atr = np.zeros(n)
    if n >= period:
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    hl2 = (high + low) / 2
    up_lev = hl2 - (multiplier * atr)
    dn_lev = hl2 + (multiplier * atr)

    up_trend = np.zeros(n)
    down_trend = np.zeros(n)
    supertrend = np.zeros(n)
    direction = np.ones(n)

    for i in range(1, n):
        up_trend[i] = max(up_lev[i], up_trend[i - 1]) if close[i - 1] > up_trend[i - 1] else up_lev[i]
        down_trend[i] = min(dn_lev[i], down_trend[i - 1]) if close[i - 1] < down_trend[i - 1] else dn_lev[i]

        if close[i] > down_trend[i - 1]:
            direction[i] = 1
        elif close[i] < up_trend[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

        supertrend[i] = up_trend[i] if direction[i] == 1 else down_trend[i]

    return supertrend, direction


def compute_all(df: pd.DataFrame, bar_minutes: int = 15) -> dict:
    """Compute all indicators at once and return as dict of latest values + arrays."""
    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)

    ema8 = calculate_ema(close, 8)
    ema21 = calculate_ema(close, 21)
    ema55 = calculate_ema(close, 55)
    ema200 = calculate_ema(close, 200)
    rsi14 = calculate_rsi(close, 14)
    atr14 = calculate_atr(high, low, close, 14)
    adx14, plus_di, minus_di = calculate_adx(high, low, close, 14)
    st, st_dir = calculate_supertrend(high, low, close)

    # Volume array (raw from df if available)
    volume = df["volume"].values.astype(float) if "volume" in df.columns else np.ones(len(close))

    # Dynamic macro trend — adapts to bar_minutes (5m, 15m, 1h etc.)
    bars_per_day = int(24 * 60 / bar_minutes)
    lookback_7d  = bars_per_day * 7   # e.g. 2016 for 5m, 672 for 15m
    lookback_3d  = bars_per_day * 3   # e.g. 864 for 5m,  288 for 15m

    macro_close_7d_ago = float(close[-lookback_7d]) if len(close) >= lookback_7d else float(close[0])
    macro_trend_7d     = int(np.sign(float(close[-1]) - macro_close_7d_ago))

    macro_close_3d_ago = float(close[-lookback_3d]) if len(close) >= lookback_3d else float(close[0])
    macro_trend_3d     = int(np.sign(float(close[-1]) - macro_close_3d_ago))

    return {
        "ema8": ema8,
        "ema21": ema21,
        "ema55": ema55,
        "ema200": ema200,
        "rsi": rsi14,
        "atr": atr14,
        "adx": adx14,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "supertrend": st,
        "st_direction": st_dir,
        "volume": volume,
        # Latest scalar values
        "last": {
            "ema8": float(ema8[-1]),
            "ema21": float(ema21[-1]),
            "ema55": float(ema55[-1]),
            "ema200": float(ema200[-1]),
            "rsi": float(rsi14[-1]),
            "atr": float(atr14[-1]),
            "adx": float(adx14[-1]),
            "plus_di": float(plus_di[-1]),
            "minus_di": float(minus_di[-1]),
            "st_direction": int(st_dir[-1]),
            "macro_trend_7d": macro_trend_7d,   # +1 = uptrend (7d), -1 = downtrend
            "macro_trend_3d": macro_trend_3d,   # +1 = uptrend (3d), -1 = downtrend
        },
    }
