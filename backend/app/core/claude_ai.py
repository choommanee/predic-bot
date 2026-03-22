"""
Claude AI Market Analysis
Ported from python-trade/pro_scalping_system.py lines 452-610
"""
from __future__ import annotations
import re
from typing import TYPE_CHECKING

import anthropic
import pandas as pd

if TYPE_CHECKING:
    from .smc import SMCResult


def build_prompt(df: pd.DataFrame, smc: "SMCResult", indicators: dict, symbol: str) -> str:
    """Build the market analysis prompt for Claude."""
    close = df["close"].values
    current_price = float(close[-1])
    ind = indicators.get("last", {})

    pct_1h = 0.0
    pct_4h = 0.0
    if len(close) > 12:
        pct_1h = (current_price - close[-12]) / close[-12] * 100
    if len(close) > 48:
        pct_4h = (current_price - close[-48]) / close[-48] * 100

    last_5 = df.tail(5)[["open", "high", "low", "close"]].to_string()
    high_20 = df["high"].tail(20).max()
    low_20 = df["low"].tail(20).min()

    price_vs_ema8 = "above" if current_price > ind.get("ema8", current_price) else "below"
    price_vs_ema21 = "above" if current_price > ind.get("ema21", current_price) else "below"
    price_vs_ema55 = "above" if current_price > ind.get("ema55", current_price) else "below"

    return f"""You are an expert crypto trader using Smart Money Concepts (SMC).
Analyze the following market data and provide a trading recommendation.

📊 Current Data:
- Symbol: {symbol}
- Price: {current_price:.4f}
- Change 1H: {pct_1h:.2f}%
- Change 4H: {pct_4h:.2f}%

📈 Technical Indicators:
- EMA 8: {ind.get('ema8', 0):.4f} (price {price_vs_ema8})
- EMA 21: {ind.get('ema21', 0):.4f} (price {price_vs_ema21})
- EMA 55: {ind.get('ema55', 0):.4f} (price {price_vs_ema55})
- RSI(14): {ind.get('rsi', 50):.1f}
- ATR(14): {ind.get('atr', 0):.4f}
- ADX(14): {ind.get('adx', 0):.1f}
- SuperTrend Direction: {"UP" if ind.get('st_direction', 1) == 1 else "DOWN"}
- 20-bar High: {high_20:.4f}
- 20-bar Low: {low_20:.4f}

🔍 SMC Analysis:
- Bullish BOS/CHoCH (last 10 bars): {smc.bullish_bos}
- Bearish BOS/CHoCH (last 10 bars): {smc.bearish_bos}
- Bullish Order Blocks: {smc.bullish_obs}
- Bearish Order Blocks: {smc.bearish_obs}
- SMC Bias: {smc.bias}

📉 Last 5 Candles:
{last_5}

Reply in this exact JSON format:
{{
  "market_condition": "UPTREND|DOWNTREND|SIDEWAY|VOLATILE",
  "confidence": <0-100>,
  "direction": "BUY|SELL|NEUTRAL",
  "risk_level": "LOW|MEDIUM|HIGH",
  "analysis": "<2-3 sentence summary>",
  "warnings": "<key risks to watch>"
}}"""


async def analyze_market(
    df: pd.DataFrame,
    smc: "SMCResult",
    indicators: dict,
    symbol: str,
    api_key: str,
    model: str = "claude-sonnet-4-6",
) -> dict:
    """
    Call Claude API for market analysis.
    Returns structured dict with direction, confidence, etc.
    """
    client = anthropic.AsyncAnthropic(api_key=api_key)
    prompt = build_prompt(df, smc, indicators, symbol)

    try:
        message = await client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text
        return _parse_response(raw)
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "direction": "NEUTRAL",
            "confidence": 0,
            "market_condition": "unknown",
            "risk_level": "HIGH",
            "analysis": "",
            "warnings": "",
        }


def _parse_response(text: str) -> dict:
    """Extract JSON from Claude response."""
    import json

    # Try to extract JSON block
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            data = json.loads(match.group())
            data["success"] = True
            data["raw_response"] = text
            return data
        except json.JSONDecodeError:
            pass

    # Fallback parsing
    result = {
        "success": True,
        "raw_response": text,
        "market_condition": "unknown",
        "confidence": 50,
        "direction": "NEUTRAL",
        "risk_level": "MEDIUM",
        "analysis": text[:300],
        "warnings": "",
    }

    text_lower = text.lower()
    if "uptrend" in text_lower:
        result["market_condition"] = "UPTREND"
    elif "downtrend" in text_lower:
        result["market_condition"] = "DOWNTREND"
    elif "sideway" in text_lower or "ranging" in text_lower:
        result["market_condition"] = "SIDEWAY"

    if "buy" in text_lower and "sell" not in text_lower:
        result["direction"] = "BUY"
    elif "sell" in text_lower and "buy" not in text_lower:
        result["direction"] = "SELL"

    conf_match = re.search(r"confidence[:\s]+(\d+)", text_lower)
    if conf_match:
        result["confidence"] = int(conf_match.group(1))

    return result
