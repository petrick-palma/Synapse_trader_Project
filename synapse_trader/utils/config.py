# --- synapse_trader/utils/config.py ---

import os
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from google.cloud import secretmanager
from dotenv import load_dotenv
import sys

# Configura um logger específico para este módulo
logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    EXECUTION_ENVIRONMENT: str = "local"
    GCP_PROJECT_ID: str | None = None
    LOG_LEVEL: str = "INFO"

    # --- Chaves API Binance ---
    BINANCE_API_KEY: str = "SUA_API_KEY_BINANCE"
    BINANCE_API_SECRET: str = "SEU_API_SECRET_BINANCE"
    BINANCE_TESTNET: bool = True
    BINANCE_FEE_PERCENT: str = "0.001"

    # --- Chave API Google Gemini ---
    GEMINI_API_KEY: str = "SUA_API_KEY_GEMINI"

    # --- Configuração Telegram ---
    TELEGRAM_BOT_TOKEN: str = "TOKEN_DO_SEU_BOT_TELEGRAM"
    TELEGRAM_CHAT_ID: str = "SEU_CHAT_ID_NUMERICO"

    # --- Configuração de Risco ---
    QUOTE_ASSET: str = "USDT" 
    RISK_PER_TRADE_PERCENT: float = 0.005
    MAX_CONCURRENT_TRADES: int = 10
    MAX_PER_SECTOR: int = 3

    # --- Configuração de Estratégia ---
    STRATEGY_TIMEFRAMES: str = "1m,5m,15m"

    # --- Configuração de Arbitragem ---
    ARBITRAGE_TRIANGLES: str = "ETH,BTC,USDT" 
    ARBITRAGE_MIN_PROFIT: str = "0.001" 
    ARBITRAGE_COOLDOWN_SEC: int = 5 

    # --- Configuração Local ---
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )


def _fetch_gcp_secrets(project_id: str, settings_obj: Settings) -> Settings:
    """Busca segredos do Google Secret Manager."""
    try:
        client = secretmanager.SecretManagerServiceClient()
    except Exception as e:
        logger.warning(f"Não foi possível inicializar o cliente do Secret Manager: {e}")
        logger.info("Continuando sem segredos do GCP - usando valores padrão/variáveis de ambiente")
        return settings_obj

    secrets_to_fetch = [
        "BINANCE_API_KEY", "BINANCE_API_SECRET", "GEMINI_API_KEY",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    ]
    
    def _fetch_gcp_secrets(project_id: str, settings_obj: Settings) -> Settings:
        """Busca segredos do Google Secret Manager."""
    try:
        client = secretmanager.SecretManagerServiceClient()
    except Exception as e:
        logger.error(f"Falha ao inicializar cliente do Secret Manager: {e}")
        if settings_obj.EXECUTION_ENVIRONMENT.upper() == "GCP":
            raise
        return settings_obj

    secrets_to_fetch = [
        "BINANCE_API_KEY", "BINANCE_API_SECRET", "GEMINI_API_KEY",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    ]
    
    logger.info(f"Buscando {len(secrets_to_fetch)} segredos do projeto {project_id}...")
    
    for secret_name in secrets_to_fetch:
        try:
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            payload = response.payload.data.decode("UTF-8")
            
            if hasattr(settings_obj, secret_name):
                setattr(settings_obj, secret_name, payload)
                logger.info(f"✓ Segredo '{secret_name}' carregado")
                
        except Exception as e:
            error_msg = str(e)
            if "NOT_FOUND" in error_msg:
                logger.warning(f"Secret '{secret_name}' não encontrado no Secret Manager")
            elif "PERMISSION_DENIED" in error_msg:
                logger.error(f"Sem permissão para acessar secret '{secret_name}'")
            else:
                logger.error(f"Erro ao acessar secret '{secret_name}': {e}")
            
            # Em ambiente GCP, falhamos apenas para segredos obrigatórios
            if settings_obj.EXECUTION_ENVIRONMENT.upper() == "GCP":
                if secret_name in ["BINANCE_API_KEY", "BINANCE_API_SECRET"]:
                    raise ValueError(f"Secret obrigatório '{secret_name}' não disponível") from e

    return settings_obj


def _is_gcp_environment() -> bool:
    """Verifica se estamos executando em um ambiente GCP."""
    # No Cloud Run, estas variáveis estão presentes
    gcp_indicators = [
        'K_SERVICE',  # Cloud Run
        'GAE_APPLICATION',  # App Engine
        'FUNCTION_TARGET',  # Cloud Functions
        'GCP_PROJECT'  # GCP Project
    ]
    return any(os.getenv(indicator) for indicator in gcp_indicators)


def load_config() -> Settings:
    """Orquestra o carregamento de configurações."""
    load_dotenv()
    
    # Detecta automaticamente o ambiente se não especificado
    env_type = os.getenv("EXECUTION_ENVIRONMENT")
    if not env_type and _is_gcp_environment():
        env_type = "GCP"
        os.environ["EXECUTION_ENVIRONMENT"] = "GCP"
    elif not env_type:
        env_type = "local"
    
    settings_obj = Settings()

    if env_type.upper() == "GCP":
        logger.info("Modo 'GCP' detectado. Inicializando configurações GCP...")
        project_id = settings_obj.GCP_PROJECT_ID or os.getenv("GOOGLE_CLOUD_PROJECT")
        
        if not project_id:
            logger.warning("GCP_PROJECT_ID não definido. Tentando detectar automaticamente...")
            # Tenta detectar o project ID do ambiente
            project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
            
        if not project_id:
            logger.error("Não foi possível determinar o GCP_PROJECT_ID")
            # Em ambiente GCP, isso é crítico; localmente, podemos continuar
            if _is_gcp_environment():
                raise ValueError("GCP_PROJECT_ID é obrigatório no ambiente GCP")
            else:
                logger.info("Continuando em modo local (sem segredos GCP)")
                env_type = "local"
        else:
            settings_obj = _fetch_gcp_secrets(project_id, settings_obj)
    else:
        logger.info("Modo 'local' detectado. Usando .env e variáveis de ambiente.")

    # Validação das chaves da Binance (mais flexível)
    binance_key_missing = (
        not settings_obj.BINANCE_API_KEY or 
        "SUA_API_KEY" in settings_obj.BINANCE_API_KEY
    )
    binance_secret_missing = (
        not settings_obj.BINANCE_API_SECRET or 
        "SEU_API_SECRET" in settings_obj.BINANCE_API_SECRET
    )

    if binance_key_missing or binance_secret_missing:
        if env_type.upper() == "GCP":
            # Em GCP, isso é crítico
            msg = "Chaves API da Binance não carregadas no ambiente GCP!"
            logger.critical(msg)
            raise ValueError(msg)
        else:
            # Localmente, apenas avisamos
            logger.warning("Chaves API da Binance não configuradas - algumas funcionalidades podem não funcionar")

    logger.info(f"Configuração carregada com sucesso. Modo: {env_type}")
    return settings_obj


try:
    settings = load_config()
except ValueError as e:
    logging.critical(f"Erro fatal ao inicializar a configuração: {e}")
    sys.exit(1)