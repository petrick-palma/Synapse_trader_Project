# --- synapse_trader/core/state_manager.py ---

import logging
import json
from abc import ABC, abstractmethod
from typing import Any, Dict
from datetime import datetime 

from synapse_trader.utils.config import settings
from synapse_trader.core import redis_client
# --- CORREÇÃO: Importar o módulo gcp_clients ---
import synapse_trader.core.gcp_clients as gcp_clients
# -----------------------------------------------

logger = logging.getLogger(__name__)

class AbstractStateManager(ABC):
    """Define a interface para o gestor de estado."""

    @abstractmethod
    async def set_state(self, collection: str, key: str, data: Any):
        pass
    @abstractmethod
    async def get_state(self, collection: str, key: str) -> Any | None:
        pass
    @abstractmethod
    async def delete_state(self, collection: str, key: str):
        pass
    @abstractmethod
    async def get_collection(self, collection: str) -> Dict[str, Any]:
        pass

# --- Implementação Local (Redis Hashes) ---

class RedisStateManager(AbstractStateManager):
    """Implementação do Gestor de Estado usando Redis Hashes."""
    
    async def set_state(self, collection: str, key: str, data: Any):
        try:
            if isinstance(data, (dict, list, str, int, float, bool)):
                 data_str = json.dumps(data)
            elif hasattr(data, 'model_dump_json'): 
                 data_str = data.model_dump_json()
            else:
                 data_str = str(data) 

            async with redis_client.get_redis_connection() as r:
                await r.hset(collection, key, data_str)
            logger.debug(f"Estado definido no Redis (Col: {collection}, Key: {key})")
        except Exception as e:
            logger.error(f"Erro ao definir estado no Redis ({collection}/{key}): {e}", exc_info=True)

    async def get_state(self, collection: str, key: str) -> Any | None:
        try:
            async with redis_client.get_redis_connection() as r:
                data_str = await r.hget(collection, key)
            
            if data_str:
                logger.debug(f"Estado obtido do Redis (Col: {collection}, Key: {key})")
                try:
                    return json.loads(data_str)
                except json.JSONDecodeError:
                     return data_str 
            
            logger.debug(f"Estado não encontrado no Redis (Col: {collection}, Key: {key})")
            return None
        except Exception as e:
            logger.error(f"Erro ao obter estado do Redis ({collection}/{key}): {e}", exc_info=True)
            return None

    async def delete_state(self, collection: str, key: str):
        try:
            async with redis_client.get_redis_connection() as r:
                await r.hdel(collection, key)
            logger.debug(f"Estado apagado do Redis (Col: {collection}, Key: {key})")
        except Exception as e:
            logger.error(f"Erro ao apagar estado no Redis ({collection}/{key}): {e}", exc_info=True)

    async def get_collection(self, collection: str) -> Dict[str, Any]:
        all_data: Dict[str, Any] = {}
        try:
            async with redis_client.get_redis_connection() as r:
                all_data_str = await r.hgetall(collection)
            
            for key, data_str in all_data_str.items():
                try:
                    all_data[key] = json.loads(data_str)
                except json.JSONDecodeError:
                    all_data[key] = data_str 
            
            logger.debug(f"Coleção obtida do Redis (Col: {collection}), {len(all_data)} items.")
            return all_data
        except Exception as e:
            logger.error(f"Erro ao obter coleção do Redis ({collection}): {e}", exc_info=True)
            return {}

# --- Implementação de Produção (GCP Firestore) ---

class GCPStateManager(AbstractStateManager):
    """Implementação do Gestor de Estado usando GCP Firestore."""
    
    def __init__(self):
        # --- CORREÇÃO: Usar o cliente importado do módulo gcp_clients ---
        self.db = gcp_clients.firestore_client
        # -------------------------------------------------------------
        if not self.db:
             logger.warning("Cliente GCP Firestore não inicializado (provavelmente modo local).")

    async def set_state(self, collection: str, key: str, data: Any):
        if not self.db: return 
        try:
            doc_ref = self.db.collection(collection).document(key)
            
            if hasattr(data, 'model_dump'): 
                data_to_set = data.model_dump()
            elif isinstance(data, (dict, list, str, int, float, bool, type(None))):
                 data_to_set = data
            elif isinstance(data, datetime):
                 data_to_set = data
            else:
                 data_to_set = str(data) 

            await doc_ref.set(data_to_set)
            logger.debug(f"Estado definido no Firestore (Col: {collection}, Doc: {key})")
        except Exception as e:
            logger.error(f"Erro ao definir estado no Firestore ({collection}/{key}): {e}", exc_info=True)

    async def get_state(self, collection: str, key: str) -> Any | None:
        if not self.db: return None
        try:
            doc_ref = self.db.collection(collection).document(key)
            doc = await doc_ref.get()
            
            if doc.exists:
                data = doc.to_dict()
                logger.debug(f"Estado obtido do Firestore (Col: {collection}, Doc: {key})")
                return data 
            
            logger.debug(f"Estado não encontrado no Firestore (Col: {collection}, Doc: {key})")
            return None
        except Exception as e:
            logger.error(f"Erro ao obter estado do Firestore ({collection}/{key}): {e}", exc_info=True)
            return None

    async def delete_state(self, collection: str, key: str):
        if not self.db: return
        try:
            doc_ref = self.db.collection(collection).document(key)
            await doc_ref.delete()
            logger.debug(f"Estado apagado do Firestore (Col: {collection}, Doc: {key})")
        except Exception as e:
            logger.error(f"Erro ao apagar estado no Firestore ({collection}/{key}): {e}", exc_info=True)

    async def get_collection(self, collection: str) -> Dict[str, Any]:
        if not self.db: return {}
        all_data: Dict[str, Any] = {}
        try:
            collection_ref = self.db.collection(collection)
            async for doc in collection_ref.stream():
                all_data[doc.id] = doc.to_dict()
                
            logger.debug(f"Coleção obtida do Firestore (Col: {collection}), {len(all_data)} items.")
            return all_data
        except Exception as e:
            logger.error(f"Erro ao obter coleção do Firestore ({collection}): {e}", exc_info=True)
            return {}

# --- Fábrica (Factory) ---

_state_manager_instance: AbstractStateManager | None = None

def get_state_manager() -> AbstractStateManager:
    """
    Fábrica que retorna a implementação correta do State Manager.
    """
    global _state_manager_instance
    if _state_manager_instance is None:
        if settings.EXECUTION_ENVIRONMENT.upper() == "GCP":
            logger.info("A usar GCPStateManager (Firestore).")
            _state_manager_instance = GCPStateManager()
        else:
            logger.info("A usar RedisStateManager.")
            try:
                import redis.exceptions
                redis_client.exceptions = redis.exceptions
            except ImportError:
                 logger.warning("Biblioteca 'redis' não encontrada. Modo Local falhará.")
            _state_manager_instance = RedisStateManager()
    return _state_manager_instance