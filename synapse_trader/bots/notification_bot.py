# --- synapse_trader/bots/notification_bot.py ---

import logging
import asyncio
import telegram
from telegram.constants import ParseMode

from synapse_trader.bots.base_bot import BaseBot
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager
from synapse_trader.core.types import EVENT_POSITION_OPENED, EVENT_POSITION_CLOSED
from synapse_trader.utils.config import settings

logger = logging.getLogger(__name__)

class NotificationBot(BaseBot):
    """
    Ouve eventos do Event Bus (executado no 'worker')
    e envia notificações via Telegram.
    """

    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager):
        
        super().__init__(event_bus, state_manager)
        self.chat_id = settings.TELEGRAM_CHAT_ID
        
        if not settings.TELEGRAM_BOT_TOKEN or "TOKEN" in settings.TELEGRAM_BOT_TOKEN:
            logger.warning("[NotificationBot] Token do Telegram não configurado. Bot ficará inativo.")
            self.bot = None
        else:
            try:
                self.bot = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)
                logger.info("[NotificationBot] Cliente Telegram inicializado.")
            except Exception as e:
                logger.error(f"[NotificationBot] Falha ao inicializar cliente Telegram: {e}")
                self.bot = None

    async def _send_telegram_message(self, text: str):
        """Envia uma mensagem formatada (HTML) para o Telegram."""
        if not self.bot:
            logger.debug(f"[NotificationBot] (Inativo) Mensagem: {text}")
            return
            
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"[NotificationBot] Erro ao enviar mensagem Telegram: {e}", exc_info=True)

    async def _on_position_opened(self, message: dict):
        """Callback para EVENT_POSITION_OPENED."""
        symbol = message.get("symbol", "N/A")
        side = message.get("side", "N/A")
        price = message.get("entry_price", 0.0)
        qty = message.get("quantity", 0.0)
        sl = message.get("sl_price", 0.0)
        
        text = (
            f"<b>✅ POSIÇÃO ABERTA</b>\n\n"
            f"<b>Símbolo:</b> {symbol}\n"
            f"<b>Lado:</b> {side}\n"
            f"<b>Quantidade:</b> {qty}\n"
            f"<b>Preço Entrada:</b> ${price:,.4f}\n"
            f"<b>Stop Loss:</b> ${sl:,.4f}"
        )
        await self._send_telegram_message(text)

    async def _on_position_closed(self, message: dict):
        """Callback para EVENT_POSITION_CLOSED."""
        symbol = message.get("symbol", "N/A")
        pnl = message.get("pnl", 0.0)
        pnl_percent = message.get("pnl_percent", 0.0)
        exit_price = message.get("exit_price", 0.0)
        
        # Emoji de lucro ou perda
        emoji = "💰" if pnl >= 0 else "🔻"
        
        text = (
            f"<b>{emoji} POSIÇÃO FECHADA</b>\n\n"
            f"<b>Símbolo:</b> {symbol}\n"
            f"<b>Preço Saída:</b> ${exit_price:,.4f}\n"
            f"<b>P/L:</b> ${pnl:,.2f} ({pnl_percent:,.2f}%)"
        )
        await self._send_telegram_message(text)

    async def run(self):
        """Inicia o bot e subscreve aos eventos."""
        if not self.bot:
            logger.warning("[NotificationBot] Bot inativo. A encerrar.")
            return

        # Envia mensagem de arranque
        await self._send_telegram_message("🤖 <b>Synapse Trader (Worker)</b> iniciou e está online.")

        logger.info("[NotificationBot] A subscrever aos tópicos de Posição...")
        await self._subscribe(EVENT_POSITION_OPENED, self._on_position_opened)
        await self._subscribe(EVENT_POSITION_CLOSED, self._on_position_closed)
        
        while True:
            await asyncio.sleep(3600) # Mantém-se vivo