# --- run_worker.py ---

import logging
import asyncio
import pandas as pd
import time

from synapse_trader.utils.config import settings
from synapse_trader.utils.logging_config import setup_logging
from synapse_trader.core.event_bus import get_event_bus
from synapse_trader.core.state_manager import get_state_manager
from synapse_trader.utils import database
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.connectors.gemini_client import GeminiClient

from synapse_trader.bots.notification_bot import NotificationBot
from synapse_trader.bots.optimizer import OptimizerBot 
from synapse_trader.backtester.run_optimization import run_full_optimization_cycle 
from synapse_trader.core.types import EVENT_OPTIMIZER_DONE # Importar o nome do evento

logger = logging.getLogger("synapse_trader.worker")


async def main():
    """Função principal assíncrona para o serviço 'worker'."""
    logger.info(f"A iniciar o serviço 'worker' (Ambiente: {settings.EXECUTION_ENVIRONMENT})...")
    
    binance_client = None

    try:
        event_bus = get_event_bus()
        state_manager = get_state_manager()
        await database.init_db()
        
        binance_client = BinanceClient()
        gemini_client = GeminiClient()
        
        await binance_client.connect()
        await binance_client.health_check()
        
        notification_bot = NotificationBot(event_bus, state_manager)
        optimizer_bot = OptimizerBot(event_bus, state_manager, binance_client)
        
        # --- CORREÇÃO: Orquestração do Ciclo de Otimização ---
        async def run_full_optimization_loop():
             """Ciclo principal do worker: Otimiza (VectorBT), depois Treina (DRL/Prophet)."""
             while True:
                try:
                    start_time = time.time()
                    logger.info("[WORKER] A iniciar ciclo de OTIMIZAÇÃO DE PARÂMETROS (VectorBT)...")
                    
                    # 1. Executa a otimização de grelha
                    optimization_results = await run_full_optimization_cycle()
                    
                    # 2. Publica os melhores parâmetros (para o StrategistBot)
                    if optimization_results:
                        logger.info(f"[WORKER] Otimização (VectorBT) concluída. {len(optimization_results)} resultados encontrados.")
                        for result in optimization_results:
                             await event_bus.publish(EVENT_OPTIMIZER_DONE, result)
                             logger.info(f"[WORKER] Parâmetros publicados para {result['strategy_name']}")
                    
                    logger.info("[WORKER] A iniciar ciclo de TREINO DE IA (DRL + Prophet)...")
                    # 3. Executa o ciclo DRL e Prophet do OptimizerBot
                    await optimizer_bot.run_optimization_cycle()
                    
                    end_time = time.time()
                    logger.info(f"[WORKER] Ciclo de Otimização/Treino concluído em {end_time - start_time:.2f}s.")
                    
                    # 4. Aguarda o intervalo
                    interval = optimizer_bot.OPTIMIZE_INTERVAL_SECONDS
                    logger.info(f"[WORKER] Próximo ciclo em {interval / 3600:.1f} horas.")
                    await asyncio.sleep(interval)

                except Exception as e:
                    logger.critical(f"[WORKER] Erro CRÍTICO no ciclo de OTIMIZAÇÃO: {e}", exc_info=True)
                    logger.info("A aguardar 60s antes de tentar novamente...")
                    await asyncio.sleep(60)
        # --- FIM DA CORREÇÃO ---
        
        tasks = [
            asyncio.create_task(notification_bot.run()), # Ouve por alertas
            asyncio.create_task(run_full_optimization_loop()), # Executa o ciclo de otimização/treino
        ]

        await asyncio.gather(*tasks)
            
    except Exception as e:
        logger.critical(f"Erro fatal no 'worker': {e}", exc_info=True)
    finally:
        if binance_client:
            await binance_client.close()
        logger.info("Serviço 'worker' a desligar.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Serviço 'worker' interrompido manualmente.")