# --- run_trading.py ---
# Ponto de entrada para o serviço Trading Bot (24/7)

import logging
import asyncio

from synapse_trader.utils.config import settings
from synapse_trader.utils.logging_config import setup_logging
from synapse_trader.core.event_bus import get_event_bus
from synapse_trader.core.state_manager import get_state_manager
from synapse_trader.utils import database
from synapse_trader.utils.symbol_filters import symbol_filters
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.connectors.gemini_client import GeminiClient

# --- IMPORTAÇÕES DOS BOTS ---
from synapse_trader.core.data_feed import DataFeed
from synapse_trader.bots.strategist import StrategistBot
from synapse_trader.bots.risk_manager import RiskManagerBot
from synapse_trader.bots.executor import ExecutorBot
from synapse_trader.bots.monitor import MonitorBot
from synapse_trader.bots.analyst import AnalystBot
from synapse_trader.bots.arbitrage import ArbitrageBot # <-- NOVO

# 1. Configurar o logging
setup_logging(settings.LOG_LEVEL)
logger = logging.getLogger("synapse_trader.trading_bot")


async def main():
    """
    Função principal assíncrona para o serviço de trading.
    """
    logger.info(f"A iniciar o serviço 'trading_bot' (Ambiente: {settings.EXECUTION_ENVIRONMENT})...")
    
    binance_client = None 

    try:
        # 2. Inicializar os serviços core
        event_bus = get_event_bus()
        state_manager = get_state_manager()
        await database.init_db()
        logger.info("Event Bus, State Manager e Base de Dados (SQLite) inicializados.")

        # 3. Inicializar os conectores
        binance_client = BinanceClient()
        gemini_client = GeminiClient()
        
        await binance_client.connect()
        await binance_client.health_check()
        logger.info("Conexão Binance REST OK.")
        
        await symbol_filters.load_filters(binance_client)
        logger.info("Filtros de símbolos carregados.")
        
        logger.info("Conectores (Binance, Gemini) inicializados.")
        
        # 5. Inicializar os bots deste serviço
        logger.info("A inicializar bots do serviço de trading...")
        
        data_feed = DataFeed(event_bus, state_manager, binance_client)
        strategist_bot = StrategistBot(event_bus, state_manager, binance_client, symbol_filters)
        risk_manager_bot = RiskManagerBot(event_bus, state_manager, binance_client, symbol_filters)
        executor_bot = ExecutorBot(event_bus, state_manager, binance_client, symbol_filters)
        monitor_bot = MonitorBot(event_bus, state_manager, binance_client)
        analyst_bot = AnalystBot(event_bus, state_manager, binance_client, gemini_client)
        
        arbitrage_bot = ArbitrageBot( # <-- NOVO
            event_bus, state_manager, binance_client, symbol_filters
        )
        
        # 6. Criar 'tasks' para cada bot
        tasks = [
            asyncio.create_task(data_feed.run()),
            asyncio.create_task(strategist_bot.run()),
            asyncio.create_task(risk_manager_bot.run()),
            asyncio.create_task(executor_bot.run()),
            asyncio.create_task(monitor_bot.run()),
            asyncio.create_task(analyst_bot.run()),
            asyncio.create_task(arbitrage_bot.run()), # <-- NOVO
        ]
        
        logger.info(f"{len(tasks)} bots iniciados. O sistema está totalmente operacional.")
        await asyncio.gather(*tasks)

    except Exception as e:
        logger.critical(f"Erro fatal no 'trading_bot': {e}", exc_info=True)
    finally:
        if binance_client:
            await binance_client.close()
        logger.warning("O serviço 'trading_bot' está a ser encerrado. Isto não é esperado.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Serviço 'trading_bot' interrompido manualmente.")