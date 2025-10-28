# --- synapse_trader/backtester/run_optimization.py ---

import logging
import asyncio
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List

# Importar as ferramentas
from synapse_trader.backtester.data_fetcher import fetch_data_for_backtesting
from synapse_trader.backtester.adapters_vectorbt import run_vectorbt_optimization
from synapse_trader.strategies.ema_crossover import EmaCrossoverStrategy
from synapse_trader.strategies.stochastic_rsi_scalp import StochasticRsiScalpStrategy

logger = logging.getLogger(__name__)

# --- Configurações de Otimização ---
OPTIMIZATION_SYMBOL = "BTCUSDT"
OPTIMIZATION_TIMEFRAME = "15m"
OPTIMIZATION_START_DATE = "1 Jan, 2025" # Data de início do backtest

# Definição das Grelhas de Parâmetros
PARAM_RANGES: Dict[str, Dict[str, Any]] = {
    EmaCrossoverStrategy.__name__: {
        'fast_period': np.arange(5, 15, 1), # 5 a 14
        'slow_period': np.arange(20, 40, 5), # 20, 25, 30, 35
    },
    StochasticRsiScalpStrategy.__name__: {
        'k_period': np.arange(7, 21, 2), # 7, 9, 11... 19
    }
}

async def run_full_optimization_cycle() -> List[Dict[str, Any]]:
    """
    Executa o ciclo completo de otimização de parâmetros para todas as estratégias.
    """
    logger.info("A iniciar ciclo de otimização de parâmetros (VectorBT)...")
    
    # 1. Download de Dados
    df = await fetch_data_for_backtesting(
        OPTIMIZATION_SYMBOL, 
        OPTIMIZATION_TIMEFRAME, 
        OPTIMIZATION_START_DATE
    )
    
    if df is None or df.empty:
        logger.error("Otimização cancelada: Falha ao obter dados de backtest.")
        return []

    # 2. Executar Otimizações
    optimization_results = []
    
    # Otimização EMA Crossover
    ema_params = PARAM_RANGES[EmaCrossoverStrategy.__name__]
    ema_result = await asyncio.to_thread(
        run_vectorbt_optimization,
        df, EmaCrossoverStrategy.__name__, ema_params
    )
    optimization_results.append(ema_result)
    
    # Otimização StochRSI Scalp
    stoch_params = PARAM_RANGES[StochasticRsiScalpStrategy.__name__]
    stoch_result = await asyncio.to_thread(
        run_vectorbt_optimization,
        df, StochasticRsiScalpStrategy.__name__, stoch_params
    )
    optimization_results.append(stoch_result)
    
    # 3. Retornar os melhores resultados
    logger.info("Ciclo de otimização concluído. Resultados salvos.")
    return optimization_results