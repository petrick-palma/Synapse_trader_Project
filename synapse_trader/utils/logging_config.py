# --- synapse_trader/utils/logging_config.py ---

import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_logging(log_level: str = "INFO"):
    """
    Configura o logging raiz para emitir logs em formato JSON estruturado,
    compatível com o Google Cloud Logging.
    """
    # Converte o nível de log de string para o formato logging (ex: "INFO" -> 20)
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Obtém o logger raiz
    logger = logging.getLogger()
    
    # Define o nível de log no logger raiz
    logger.setLevel(numeric_level)
    
    # Remove handlers existentes para evitar duplicação (especialmente em Cloud Run)
    if logger.hasHandlers():
        logger.handlers.clear()

    # Cria um handler que escreve para a saída padrão (stdout)
    handler = logging.StreamHandler(sys.stdout)
    
    # Define o formatador JSON
    # O Google Cloud Logging reconhece campos padrão como 'message', 'levelname'
    # e adiciona 'severity' e 'timestamp' automaticamente.
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s'
    )
    
    handler.setFormatter(formatter)
    
    # Adiciona o handler configurado ao logger raiz
    logger.addHandler(handler)

    # Silencia loggers muito "barulhentos" de bibliotecas de terceiros
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google.api_core").setLevel(logging.WARNING)
    logging.getLogger("google.cloud").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.INFO)

    logging.info(f"Configuração de logging concluída. Nível de log definido para: {log_level}")