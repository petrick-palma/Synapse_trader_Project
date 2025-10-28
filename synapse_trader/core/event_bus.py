# --- synapse_trader/core/event_bus.py ---

import logging
import json
import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Any
from google.cloud import pubsub_v1 

from synapse_trader.utils.config import settings
from synapse_trader.core import redis_client
# --- CORREÇÃO: Importar o módulo gcp_clients ---
import synapse_trader.core.gcp_clients as gcp_clients 
# --------------------------------------------------------------------

logger = logging.getLogger(__name__)

class AbstractEventBus(ABC):
    """Define a interface para o barramento de eventos."""
    
    @abstractmethod
    async def publish(self, topic: str, message: dict):
        pass

    @abstractmethod
    async def subscribe(self, topic: str, callback: Callable[[dict], Any]):
        pass

# --- Implementação Local (Redis Pub/Sub) ---

class RedisEventBus(AbstractEventBus):
    """Implementação do Event Bus usando Redis Pub/Sub."""
    
    async def publish(self, topic: str, message: dict):
        try:
            message_str = json.dumps(message)
            async with redis_client.get_redis_connection() as r:
                await r.publish(topic, message_str)
            logger.debug(f"Mensagem publicada no Redis (Tópico {topic}): {message_str[:100]}...")
        except Exception as e:
            logger.error(f"Erro ao publicar no Redis (Tópico {topic}): {e}", exc_info=True)

    async def subscribe(self, topic: str, callback: Callable[[dict], Any]):
        logger.info(f"Subscrevendo ao tópico Redis: {topic}")
        while True:
            try:
                async with redis_client.get_redis_connection() as r:
                    pubsub = r.pubsub(ignore_subscribe_messages=True) 
                    await pubsub.subscribe(topic)
                    
                    logger.info(f"Conectado e ouvindo o tópico Redis: {topic}")
                    async for message in pubsub.listen():
                        if message['type'] == 'message':
                            data_str = message['data']
                            logger.debug(f"Mensagem recebida do Redis (Tópico {topic}): {data_str[:100]}...")
                            try:
                                data_dict = json.loads(data_str)
                                asyncio.create_task(callback(data_dict)) 
                            except json.JSONDecodeError:
                                logger.warning(f"Ignorando mensagem mal formada no tópico {topic}: {data_str}")
                            except Exception as cb_err:
                                 logger.error(f"Erro no callback do Redis para {topic}: {cb_err}", exc_info=True)
                                 
            except Exception as e:
                logger.error(f"Erro inesperado na subscrição Redis (Tópico {topic}): {e}. A tentar reconectar em 5s...", exc_info=True)
            
            await asyncio.sleep(5) 


# --- Implementação de Produção (GCP Pub/Sub) ---

class GCPEventBus(AbstractEventBus):
    """Implementação do Event Bus usando GCP Pub/Sub."""
    
    def __init__(self):
        # --- CORREÇÃO: Usar os clientes importados do módulo gcp_clients ---
        self.publisher = gcp_clients.pubsub_publisher_client
        self.subscriber = gcp_clients.pubsub_subscriber_client
        # ------------------------------------------------------------------
        self.project_id = settings.GCP_PROJECT_ID
        if not all([self.publisher, self.subscriber, self.project_id]):
             logger.info("Clientes GCP Pub/Sub não inicializados (provavelmente modo local).")

    async def publish(self, topic_id: str, message: dict):
        if not self.publisher: 
            logger.debug(f"GCPEventBus (local): Ignorando publicação em {topic_id}")
            return
            
        topic_path = self.publisher.topic_path(self.project_id, topic_id)
        try:
            message_str = json.dumps(message)
            message_bytes = message_str.encode("utf-8")
            
            future = self.publisher.publish(topic_path, message_bytes)
            future.add_done_callback(lambda fut: logger.debug(f"GCP Pub/Sub: Mensagem publicada (ID: {fut.result()}) em {topic_id}"))

            logger.debug(f"Mensagem enviada para GCP Pub/Sub (Tópico {topic_id}): {message_str[:100]}...")
        except Exception as e: 
            logger.error(f"Erro ao publicar no GCP Pub/Sub (Tópico {topic_id}): {e}", exc_info=True)

    async def subscribe(self, topic_id: str, callback: Callable[[dict], Any]):
        if not self.subscriber:
             logger.warning(f"GCPEventBus (local): Ignorando subscrição em {topic_id}")
             return 

        subscription_id = f"{topic_id}-main-subscription"
        topic_path = self.publisher.topic_path(self.project_id, topic_id)
        subscription_path = self.subscriber.subscription_path(self.project_id, subscription_id)

        try:
            self.subscriber.create_subscription(
                request={"name": subscription_path, "topic": topic_path}
            )
            logger.info(f"Subscrição GCP '{subscription_id}' criada para o tópico '{topic_id}'.")
        except gcp_clients.exceptions.AlreadyExists: 
            logger.info(f"Subscrição GCP '{subscription_id}' já existe. A usar a existente.")
        except Exception as e:
            logger.error(f"Erro ao criar/verificar subscrição GCP '{subscription_id}': {e}", exc_info=True)
            return 

        def _gcp_callback_wrapper(message: pubsub_v1.subscriber.message.Message):
            """Wrapper síncrono que o cliente GCP usa."""
            data_str = ""
            try:
                data_str = message.data.decode("utf-8")
                logger.debug(f"Mensagem recebida do GCP Pub/Sub (Tópico {topic_id}): {data_str[:100]}...")
                data_dict = json.loads(data_str)
                
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                loop.create_task(callback(data_dict)) 
                message.ack()
            except json.JSONDecodeError:
                logger.warning(f"Ignorando mensagem mal formada no tópico {topic_id}: {data_str}")
                message.nack() 
            except Exception as e:
                logger.error(f"Erro ao processar callback GCP para {topic_id}: {e}", exc_info=True)
                message.nack()

        logger.info(f"A ouvir mensagens no GCP Pub/Sub (Subscrição {subscription_id})...")
        streaming_pull_future = self.subscriber.subscribe(
            subscription_path, 
            callback=_gcp_callback_wrapper
        )
        
        try:
             logger.info(f"Streaming pull para {subscription_id} iniciado em background.")
        except Exception as e:
            logger.error(f"Erro ao iniciar/monitorar subscrição GCP ({topic_id}): {e}", exc_info=True)
            streaming_pull_future.cancel()


# --- Fábrica (Factory) ---

_event_bus_instance: AbstractEventBus | None = None

def get_event_bus() -> AbstractEventBus:
    """
    Fábrica que retorna a implementação correta do Event Bus.
    """
    global _event_bus_instance
    if _event_bus_instance is None:
        if settings.EXECUTION_ENVIRONMENT.upper() == "GCP":
            logger.info("A usar GCPEventBus.")
            try:
                from google.cloud import exceptions as gcp_exceptions 
                gcp_clients.exceptions = gcp_exceptions 
            except ImportError:
                 logger.warning("Biblioteca 'google.cloud' não encontrada. Modo GCP falhará.")
            _event_bus_instance = GCPEventBus()
        else:
            logger.info("A usar RedisEventBus.")
            try:
                import redis.exceptions
                redis_client.exceptions = redis.exceptions
            except ImportError:
                 logger.warning("Biblioteca 'redis' não encontrada. Modo Local falhará.")
            _event_bus_instance = RedisEventBus()
    return _event_bus_instance