# --- run_api.py ---
# Ponto de entrada para o serviço API (FastAPI)

import logging
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

from synapse_trader.utils.config import settings
from synapse_trader.utils.logging_config import setup_logging
from synapse_trader.core.event_bus import get_event_bus
from synapse_trader.core.state_manager import get_state_manager
from synapse_trader.utils import database # <-- NOVO: Importar o módulo database

# 1. Configurar o logging ANTES de tudo
# (O 'settings' já foi carregado e validado em config.py)
setup_logging(settings.LOG_LEVEL)
logger = logging.getLogger("synapse_trader.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Função de 'lifespan' do FastAPI.
    Código aqui é executado ANTES do servidor iniciar.
    """
    logger.info("Serviço API a iniciar...")
    
    # Inicializa as abstrações (Event Bus e State Manager)
    # Isto também inicializa os clientes subjacentes (Redis ou GCP)
    try:
        get_event_bus()
        get_state_manager()
        logger.info("Event Bus e State Manager inicializados para a API.")
        
        # <-- NOVO: Inicializa a base de dados (cria tabelas se não existirem) ---
        await database.init_db()
        # -------------------------------------------------------------------
        
    except Exception as e:
        logger.critical(f"Falha ao inicializar serviços core para a API: {e}", exc_info=True)
        # Se falharmos aqui, o 'lifespan' falha e o FastAPI não arranca.
        raise
    
    yield
    
    # Código aqui é executado DEPOIS do servidor parar
    logger.info("Serviço API a desligar.")


# Cria a aplicação FastAPI
app = FastAPI(
    title="Synapse Trader API",
    description="Dashboard e API para o Synapse Trader",
    version="0.1.0",
    lifespan=lifespan
)

# --- Endpoints ---

@app.get("/", tags=["Health"])
async def get_root_health():
    """
    Endpoint de verificação de saúde (Health Check).
    """
    logger.info("Health check (/) solicitado.")
    return {
        "status": "ok",
        "service": "synapse-trader-api",
        "environment": settings.EXECUTION_ENVIRONMENT
    }

# TODO: Importar e incluir routers da pasta 'api'
# from synapse_trader.api import endpoints
# app.include_router(endpoints.router, prefix="/api/v1")


if __name__ == "__main__":
    # Este 'if' é usado se executarmos 'python run_api.py' diretamente
    # No Docker, o 'uvicorn' é chamado diretamente (ver docker-compose.local.yml)
    logger.info("A executar 'run_api.py' diretamente...")
    uvicorn.run(
        "run_api:app", 
        host="0.0.0.0", 
        port=8080, 
        reload=True # Ativa o reload (ótimo para dev local)
    )