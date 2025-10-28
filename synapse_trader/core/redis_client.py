# --- synapse_trader/core/redis_client.py ---

import logging
import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool
from contextlib import asynccontextmanager
from synapse_trader.utils.config import settings

logger = logging.getLogger(__name__)

# Pool de ligações global, inicializado como None
redis_pool: ConnectionPool | None = None

def get_redis_pool() -> ConnectionPool:
    """
    Inicializa e/ou retorna o pool de ligações Redis assíncrono.
    Usa um padrão singleton para garantir que o pool seja criado apenas uma vez.
    """
    global redis_pool
    if redis_pool is None:
        try:
            logger.info(f"A criar pool de ligações Redis para: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
            redis_pool = redis.ConnectionPool(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=0, # Usamos a base de dados 0 por defeito
                decode_responses=True # Descodifica respostas de bytes para utf-8
            )
        except Exception as e:
            logger.critical(f"Falha ao criar pool de ligações Redis: {e}", exc_info=True)
            raise
    return redis_pool

@asynccontextmanager
async def get_redis_connection():
    """
    Fornece uma ligação Redis a partir do pool usando um context manager.
    Garante que a ligação é devolvida ao pool.
    """
    pool = get_redis_pool()
    client = None
    try:
        client = redis.Redis(connection_pool=pool)
        yield client
    except Exception as e:
        logger.error(f"Erro durante a operação com Redis: {e}", exc_info=True)
        raise
    finally:
        if client:
            # Com 'redis.asyncio' e pools, fechar a ligação
            # na verdade devolve-a ao pool.
            await client.aclose()

async def check_redis_connection():
    """
    Verifica se a ligação ao Redis está ativa.
    """
    try:
        async with get_redis_connection() as r:
            await r.ping()
        logger.info("Conexão com Redis (Modo Local) verificada com sucesso.")
        return True
    except Exception as e:
        logger.error(f"Falha ao conectar com Redis (Modo Local): {e}")
        return False