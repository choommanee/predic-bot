"""
Telegram Bot notifications using aiogram 3.x
"""
from __future__ import annotations
import logging
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self.chat_id = chat_id
        self._bot: Bot | None = None
        if token:
            self._bot = Bot(
                token=token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )

    async def send(self, text: str) -> None:
        if not self._bot or not self.chat_id:
            return
        try:
            await self._bot.send_message(chat_id=self.chat_id, text=text)
        except Exception as exc:
            logger.error("Telegram send error: %s", exc)

    async def send_signal(self, event: dict) -> None:
        """Format and send a trading signal."""
        signals = event.get("signals", [])
        if not signals:
            return

        smc = event.get("smc", {})
        ind = event.get("indicators", {})
        price = event.get("price", 0)
        symbol = event.get("symbol", "")

        lines = [f"🤖 <b>predic-bot Signal</b>"]
        lines.append(f"📍 {symbol} @ <code>{price:.4f}</code>")
        lines.append(f"📊 SMC: {smc.get('bias', 'NEUTRAL')}")
        lines.append(f"📈 RSI: {ind.get('rsi', 0):.1f} | ADX: {ind.get('adx', 0):.1f}")
        lines.append("")

        for sig in signals:
            emoji = "🟢" if sig["side"] == "BUY" else "🔴"
            lines.append(
                f"{emoji} <b>{sig['strategy'].upper()}</b> {sig['side']} "
                f"{sig['quantity']} @ {sig['price']:.4f}"
            )
            lines.append(f"   📝 {sig['reason']}")

        ai = event.get("ai")
        if ai and ai.get("success"):
            lines.append("")
            lines.append(f"🧠 <b>AI:</b> {ai.get('direction', 'NEUTRAL')} "
                         f"({ai.get('confidence', 0)}% confidence)")

        await self.send("\n".join(lines))

    async def send_risk_alert(self, message: str) -> None:
        await self.send(f"⚠️ <b>Risk Alert</b>\n{message}")

    async def close(self) -> None:
        if self._bot:
            await self._bot.session.close()
