# --- synapse_trader/backtester/adapters_vectorbt.py ---

import logging
import pandas as pd
import numpy as np
import vectorbt as vbt
from typing import Tuple, Dict, Any

from synapse_trader.strategies.ema_crossover import EmaCrossoverStrategy
from synapse_trader.strategies.stochastic_rsi_scalp import StochasticRsiScalpStrategy

logger = logging.getLogger(__name__)

# --- Configuração Base do VectorBT ---
vbt.settings.returns['freq'] = '15m' # Frequência base para o PnL
vbt.settings.metrics['metrics'] = ['total_return', 'sharpe_ratio', 'max_drawdown']

def _get_signals_from_strategy(df: pd.DataFrame, strategy_name: str, params: Dict[str, Any]) -> Tuple[pd.Series, pd.Series]:
    """
    Executa a estratégia Python e converte os sinais em Séries 'Entradas' e 'Saídas'.
    """
    if strategy_name == EmaCrossoverStrategy.__name__:
        strategy = EmaCrossoverStrategy(**params)
    elif strategy_name == StochasticRsiScalpStrategy.__name__:
        strategy = StochasticRsiScalpStrategy(**params)
    else:
        raise ValueError(f"Estratégia desconhecida: {strategy_name}")

    # 1. Calcula indicadores
    df_with_indicators = strategy.calculate_indicators(df.copy())
    
    entries = pd.Series(False, index=df.index)
    exits = pd.Series(False, index=df.index)

    # 2. Verifica o sinal para cada vela
    for i in range(1, len(df_with_indicators)):
        signal = strategy.check_signal(df_with_indicators.iloc[:i+1])
        if signal.value == "BUY":
            entries.iloc[i] = True
        elif signal.value == "SELL":
            exits.iloc[i] = True
    
    return entries, exits

def run_vectorbt_backtest(df: pd.DataFrame, strategy_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executa um backtest simples e retorna as métricas de performance.
    """
    try:
        # Exemplo Simples (usando EMA nativa do vbt para demonstração rápida)
        fast_period = params.get('fast_period', 9)
        slow_period = params.get('slow_period', 21)
        
        fast_ma = df.vbt.ma(window=fast_period)
        slow_ma = df.vbt.ma(window=slow_period)
        
        entries = fast_ma.vbt.crossed_above(slow_ma)
        exits = fast_ma.vbt.crossed_below(slow_ma)

        pf = vbt.Portfolio.from_signals(
            df.vbt.ohlcv, 
            entries, 
            exits, 
            init_cash=1000, 
            fees=0.001, 
            freq='15m'
        )
        
        metrics = pf.get_metrics()
        
        return {
            "total_return": metrics["total_return"],
            "sharpe_ratio": metrics["sharpe_ratio"],
            "max_drawdown": metrics["max_drawdown"]
        }

    except Exception as e:
        logger.error(f"[VectorBT] Erro no backtest: {e}", exc_info=True)
        return {"total_return": np.nan, "sharpe_ratio": np.nan, "max_drawdown": np.nan}


def run_vectorbt_optimization(df: pd.DataFrame, strategy_name: str, param_ranges: Dict[str, np.ndarray]) -> Dict[str, Any]:
    """
    Executa uma otimização de grelha de parâmetros e encontra os melhores.
    """
    logger.info(f"[VectorBT] A iniciar otimização de grelha para {strategy_name}...")
    
    try:
        if strategy_name == EmaCrossoverStrategy.__name__:
            fast_periods = param_ranges['fast_period']
            slow_periods = param_ranges['slow_period']
            
            fast_ma = df['close'].vbt.ma(window=fast_periods)
            slow_ma = df['close'].vbt.ma(window=slow_periods)
            
            entries = fast_ma.vbt.crossed_above(slow_ma)
            exits = fast_ma.vbt.crossed_below(slow_ma)
            
        elif strategy_name == StochasticRsiScalpStrategy.__name__:
            k_periods = param_ranges['k_period']
            
            rsi = df['close'].vbt.rsi(window=k_periods) 
            
            # Sinais simples: Oversold/Overbought (Aplica o mesmo limite a todos)
            entries = rsi.vbt.crossed_above(30) # Hardcoded
            exits = rsi.vbt.crossed_below(70) # Hardcoded
            
        else:
            raise ValueError(f"Estratégia de otimização desconhecida: {strategy_name}")

        pf = vbt.Portfolio.from_signals(
            df['close'], 
            entries, 
            exits, 
            init_cash=1000, 
            fees=0.001, 
            freq='15m'
        )
        
        optimization_result = pf.deep_getattr('sharpe_ratio').vbt.max()
        best_params_index = optimization_result.index
        best_sharpe = optimization_result.values[0]

        best_params = {}
        if strategy_name == EmaCrossoverStrategy.__name__:
            best_params['fast_period'] = best_params_index[0]
            best_params['slow_period'] = best_params_index[1]
        elif strategy_name == StochasticRsiScalpStrategy.__name__:
             best_params['k_period'] = best_params_index[0]

        logger.info(f"[VectorBT] Otimização concluída. Melhor Sharpe Ratio: {best_sharpe:.4f}")
        
        return {
            "strategy_name": strategy_name,
            "best_metric_value": best_sharpe,
            "metric_type": "sharpe_ratio",
            "best_params": best_params
        }

    except Exception as e:
        logger.error(f"[VectorBT] Erro CRÍTICO durante otimização: {e}", exc_info=True)
        return {"status": "Error", "message": str(e)}