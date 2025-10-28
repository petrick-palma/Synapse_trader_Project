# --- synapse_trader/core/data_feed.py ---

import logging
import asyncio
from binance import BinanceSocketManager
from typing import Any, List, Set # CORRIGIDO: Importação de List e Set

from synapse_trader.bots.base_bot import BaseBot
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.core.types import (
    KlineClosed, EVENT_KLINE_CLOSED, EVENT_HOT_LIST_UPDATED
)
from synapse_trader.utils.config import settings

logger = logging.getLogger(__name__)

class DataFeed(BaseBot):
    """
    Gere os streams de dados (WebSocket) da Binance e publica
    eventos de 'Klines Fechados' no event bus.
    
    Ouve por EVENT_HOT_LIST_UPDATED para subscrever/cancelar streams dinamicamente.
    """

    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager,
                 binance_client: BinanceClient):
        
        super().__init__(event_bus, state_manager)
        self.binance_client = binance_client
        self.bsm: BinanceSocketManager = self.binance_client.get_socket_manager()
        
        self.timeframes: list[str] = [
            tf.strip() for tf in settings.STRATEGY_TIMEFRAMES.split(',') if tf.strip()
        ]
        
        if not self.timeframes:
            logger.critical("[DataFeed] Nenhum STRATEGY_TIMEFRAMES definido!")
            raise ValueError("STRATEGY_TIMEFRAMES não pode estar vazio.")

        self.watched_symbols: Set[str] = set()
        self.active_streams: Set[str] = set()
        self.socket_task: asyncio.Task | None = None

        logger.info(f"[DataFeed] A monitorizar timeframes: {self.timeframes}")
        
    def _build_streams(self) -> List[str]:
        """Constrói a lista de streams para o multiplex socket."""
        streams = []
        for symbol in self.watched_symbols:
            for tf in self.timeframes:
                stream_name = f"{symbol.lower()}@kline_{tf}"
                streams.append(stream_name)
        return streams

    async def _handle_kline_message(self, msg: dict[str, Any]):
        """Callback para processar mensagens do WebSocket de klines."""
        try:
            if msg.get('e') == 'kline':
                kline_data = msg.get('k', {})
                if kline_data.get('x', False): # Vela fechada
                    kline_event = KlineClosed(
                        symbol=kline_data.get('s'),
                        timeframe=kline_data.get('i'),
                        kline=kline_data
                    )
                    asyncio.create_task(
                        self._publish(EVENT_KLINE_CLOSED, kline_event.model_dump())
                    )
            elif msg.get('e') == 'error':
                logger.error(f"[DataFeed] Erro no WebSocket: {msg.get('m')}")
        except Exception as e:
            logger.error(f"[DataFeed] Erro ao processar mensagem kline: {e}", exc_info=True)

    async def _run_socket(self):
        """(Re)Inicia o multiplex socket com os streams atuais."""
        streams = self._build_streams()
        if not streams:
            logger.warning("[DataFeed] Nenhuma stream para ouvir. O socket não será iniciado.")
            self.active_streams = set()
            return

        logger.info(f"[DataFeed] A iniciar/reiniciar multiplex socket para {len(streams)} streams...")
        self.active_streams = set(streams)
        
        async with self.bsm.start_multiplex_socket(
            streams=streams, 
            callback=self._handle_kline_message
        ) as socket:
            try:
                while True:
                    await socket.recv()
            except asyncio.CancelledError:
                logger.info("[DataFeed] Tarefa do socket cancelada (para reinício).")
            except Exception as e:
                logger.error(f"[DataFeed] Erro no socket: {e}. A reiniciar...", exc_info=True)

    async def _on_hot_list_updated(self, message: dict):
        """Callback para EVENT_HOT_LIST_UPDATED (do AnalystBot)."""
        new_symbols = set(message.get("symbols", []))
        
        if new_symbols == self.watched_symbols:
            logger.info("[DataFeed] Hot list recebida, mas é idêntica à lista atual. A ignorar.")
            return

        logger.info(f"[DataFeed] Nova 'hot list' recebida: {new_symbols}")
        self.watched_symbols = new_symbols
        
        # Verifica se o socket precisa ser reiniciado
        new_streams = set(self._build_streams())
        if new_streams == self.active_streams:
            logger.info("[DataFeed] Nenhuma alteração nos streams necessária.")
            return

        # 1. Cancela a tarefa do socket antigo (se estiver a correr)
        if self.socket_task and not self.socket_task.done():
            logger.info("[DataFeed] A parar socket antigo...")
            self.socket_task.cancel()
            try:
                await self.socket_task # Espera o cancelamento
            except asyncio.CancelledError:
                pass # Esperado

        # 2. Inicia a nova tarefa do socket
        self.socket_task = asyncio.create_task(self._run_socket())

    async def run(self):
        """Inicia o DataFeed e subscreve aos eventos."""
        
        logger.info("[DataFeed] A subscrever ao tópico HOT_LIST_UPDATED.")
        await self._subscribe(EVENT_HOT_LIST_UPDATED, self._on_hot_list_updated)
        
        logger.info("[DataFeed] DataFeed pronto. A aguardar pela primeira 'hot list' do AnalystBot...")
        
        # Mantém o bot vivo (a tarefa do socket e o _subscribe já fazem isto)
        while True:
            await asyncio.sleep(3600)