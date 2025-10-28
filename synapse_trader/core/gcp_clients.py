# --- synapse_trader/core/gcp_clients.py ---

import logging
from synapse_trader.utils.config import settings

# Importações de tipos (são lazy-loaded)
pubsub_v1 = None
firestore = None
exceptions = None

logger = logging.getLogger(__name__)

# Inicializa os clientes como None
pubsub_publisher_client = None
pubsub_subscriber_client = None
firestore_client = None

if settings.EXECUTION_ENVIRONMENT.upper() == "GCP":
    logger.info("Modo GCP: A inicializar clientes Google Cloud...")
    try:
        from google.cloud import pubsub_v1
        from google.cloud import firestore
        from google.cloud import exceptions as gcp_exceptions
        
        exceptions = gcp_exceptions 
        
        pubsub_publisher_client = pubsub_v1.PublisherClient()
        
        pubsub_subscriber_client = pubsub_v1.SubscriberClient()
        
        firestore_client = firestore.AsyncClient(
            project=settings.GCP_PROJECT_ID,
            database="(default)" 
        )
        logger.info("Clientes GCP (Pub/Sub, Firestore) inicializados.")
        
    except ImportError:
         logger.critical("Falha ao importar 'google.cloud'. O modo GCP não funcionará. Verifique 'google-cloud-pubsub' e 'google-cloud-firestore'.")
    except Exception as e:
        logger.critical(f"Falha fatal ao inicializar clientes GCP: {e}", exc_info=True)
        raise RuntimeError(f"Erro ao inicializar clientes GCP: {e}")

async def check_firestore_connection():
    """
    Verifica se a ligação ao Firestore está ativa.
    """
    if firestore_client:
        try:
            await firestore_client.collection("health_check").document("ping").get()
            logger.info("Conexão com Firestore (Modo GCP) verificada com sucesso.")
            return True
        except Exception as e:
            logger.error(f"Falha ao conectar com Firestore (Modo GCP): {e}")
            return False
    return False