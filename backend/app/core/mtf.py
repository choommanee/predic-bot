"""
Multi-timeframe analysis: 4H bias → 15m structure → 1m entry trigger.
Only trade when higher timeframes align (top-down confirmation).
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MTFContext:
    bias_4h: str = "NEUTRAL"
    structure_15m: str = "NEUTRAL"
    smc_4h: Any = None
    smc_15m: Any = None
    ind_4h: dict = field(default_factory=dict)
    aligned: bool = False


async def get_mtf_context(exchange, symbol: str, smc_module, ind_module) -> MTFContext:
    try:
        df_4h, df_15m = await asyncio.gather(
            exchange.fetch_ohlcv(symbol, "4h", 100),
            exchange.fetch_ohlcv(symbol, "15m", 200),
        )
        smc_4h = smc_module.analyze(df_4h)
        smc_15m = smc_module.analyze(df_15m)
        ind_4h = ind_module.compute_all(df_4h)
        bias_4h = getattr(smc_4h, "bias", "NEUTRAL") or "NEUTRAL"
        structure_15m = getattr(smc_15m, "bias", "NEUTRAL") or "NEUTRAL"
        aligned = bias_4h == structure_15m and bias_4h != "NEUTRAL"
        return MTFContext(
            bias_4h=bias_4h,
            structure_15m=structure_15m,
            smc_4h=smc_4h,
            smc_15m=smc_15m,
            ind_4h=ind_4h,
            aligned=aligned,
        )
    except Exception as exc:
        logger.warning("MTF fetch failed: %s", exc)
        return MTFContext()
