# --- run_api.py ---
# Ponto de entrada para o serviço API (FastAPI)

import uvicorn
import logging

# Importa a 'app' FastAPI principal do nosso módulo 'api.main'
# A 'app' já foi configurada com logging, lifespan, rotas e templates
try:
    from synapse_trader.api.main import app, settings
except ImportError:
    print("Erro: Não foi possível importar 'app' de 'synapse_trader.api.main'.")
    print("Certifique-se que o PYTHONPATH está correto e que 'synapse_trader/__init__.py' existe.")
    exit(1)

logger = logging.getLogger("synapse_trader.run_api")

if __name__ == "__main__":
    logger.info("A executar 'run_api.py' diretamente...")
    
    # Nota: uvicorn espera que o objeto 'app' esteja definido aqui.
    # O objeto 'app' é carregado na importação de 'synapse_trader.api.main'.
    uvicorn.run(
        "run_api:app", 
        host="0.0.0.0", 
        port=8080, 
        reload=True 
    )