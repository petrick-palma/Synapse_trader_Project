# --- synapse_trader/bots/base_bot.py ---

import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Any
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager

logger = logging.getLogger(__name__)

class BaseBot(ABC):
    """
    Classe base abstrata para todos os Bots.
    
    Fornece uma interface comum e acesso ao Event Bus e State Manager.
    """

    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager):
        """
        Inicializa o bot base.
        
        Args:
            event_bus: A instância do barramento de eventos (Redis ou GCP Pub/Sub).
            state_manager: A instância do gestor de estado (Redis ou Firestore).
        """
        self.event_bus = event_bus
        self.state_manager = state_manager
        self.bot_name = self.__class__.__name__ # Ex: "DataFeed"
        logger.info(f"Bot '{self.bot_name}' inicializado.")

    @abstractmethod
    async def run(self):
        """
        O método principal de execução do bot.
        Classes filhas DEVEM implementar este método.
        """
        pass

    async def _publish(self, topic: str, message: dict):
        """
        Método auxiliar para publicar uma mensagem no event bus.
        """
        logger.debug(f"[{self.bot_name}] A publicar no tópico '{topic}': {message}")
        await self.event_bus.publish(topic, message)

    async def _subscribe(self, topic: str, callback: Callable[[dict], Any]):
        """
        Método auxiliar para subscrever a um tópico no event bus.
        
        Nota: Isto cria uma 'task' de escuta que corre indefinidamente.
        """
        logger.info(f"[{self.bot_name}] A subscrever ao tópico '{topic}'")
        # Cria uma task de subscrição que corre em segundo plano
        asyncio.create_task(self.event_bus.subscribe(topic, callback))