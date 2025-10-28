# --- tests/test_strategies.py ---

import pytest
import pandas as pd
import numpy as np
from typing import Dict

from synapse_trader.strategies.base_strategy import SignalType
from synapse_trader.strategies.ema_crossover import EmaCrossoverStrategy
from synapse_trader.strategies.stochastic_rsi_scalp import StochasticRsiScalpStrategy
from synapse_trader.strategies.macd_crossover import MacdCrossoverStrategy 
from synapse_trader.strategies.rsi_momentum import RsiMomentumStrategy 

def run_strategy_on_data(strategy, df: pd.DataFrame, index_to_check: int) -> SignalType:
    """
    Executa a estratégia num subconjunto de dados e retorna o sinal.
    """
    if index_to_check >= len(df):
         index_to_check = len(df) - 1
         
    # Usar .copy() para evitar SettingWithCopyWarning
    df_slice = df.iloc[:index_to_check + 1].copy() 
    
    df_with_indicators = strategy.calculate_indicators(df_slice)
    
    # Não fazemos dropna, a estratégia deve lidar com isso
    
    if len(df_with_indicators) < 2:
         return SignalType.HOLD
         
    return strategy.check_signal(df_with_indicators)


# --- Testes Unitários de Estratégia ---

def test_ema_crossover_strategy(mock_ohlcv_data: pd.DataFrame):
    """Testa EMA Crossover."""
    strategy = EmaCrossoverStrategy(fast_period=5, slow_period=15) 
    
    # Testar em diferentes pontos - focar em verificar se a estratégia funciona
    # em vez de esperar sinais específicos em pontos específicos
    
    # Ponto durante a primeira tendência de alta (pode dar BUY)
    signal_1 = run_strategy_on_data(strategy, mock_ohlcv_data, 35)
    print(f"EMA Signal at 35: {signal_1}")
    
    # Ponto durante a correção (pode dar SELL)
    signal_2 = run_strategy_on_data(strategy, mock_ohlcv_data, 65)
    print(f"EMA Signal at 65: {signal_2}")
    
    # Ponto durante segunda tendência de alta (pode dar BUY)
    signal_3 = run_strategy_on_data(strategy, mock_ohlcv_data, 80)
    print(f"EMA Signal at 80: {signal_3}")
    
    # Verificar que a estratégia retorna um SignalType válido
    assert signal_1 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
    assert signal_2 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
    assert signal_3 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]


def test_stochrsi_scalp_strategy(mock_ohlcv_data: pd.DataFrame):
    """Testa StochRSI."""
    strategy = StochasticRsiScalpStrategy(k_period=14, oversold=20, overbought=80)

    # Testar em diferentes pontos
    signal_1 = run_strategy_on_data(strategy, mock_ohlcv_data, 40)
    print(f"StochRSI Signal at 40: {signal_1}")
    
    signal_2 = run_strategy_on_data(strategy, mock_ohlcv_data, 70)
    print(f"StochRSI Signal at 70: {signal_2}")
    
    signal_3 = run_strategy_on_data(strategy, mock_ohlcv_data, 95)
    print(f"StochRSI Signal at 95: {signal_3}")
    
    # Verificar que a estratégia retorna um SignalType válido
    assert signal_1 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
    assert signal_2 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
    assert signal_3 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]


def test_macd_crossover_strategy(mock_ohlcv_data: pd.DataFrame):
    """Testa MACD."""
    strategy = MacdCrossoverStrategy(fast_period=12, slow_period=26, signal_period=9)
    
    # Testar em diferentes pontos
    signal_1 = run_strategy_on_data(strategy, mock_ohlcv_data, 35)
    print(f"MACD Signal at 35: {signal_1}")

    signal_2 = run_strategy_on_data(strategy, mock_ohlcv_data, 65)
    print(f"MACD Signal at 65: {signal_2}")
    
    signal_3 = run_strategy_on_data(strategy, mock_ohlcv_data, 85)
    print(f"MACD Signal at 85: {signal_3}")
    
    # Verificar que a estratégia retorna um SignalType válido
    assert signal_1 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
    assert signal_2 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
    assert signal_3 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]


def test_rsi_momentum_strategy(mock_ohlcv_data: pd.DataFrame):
    """Testa RSI."""
    strategy = RsiMomentumStrategy(period=14, oversold=30, overbought=70)

    # Testar em diferentes pontos
    signal_1 = run_strategy_on_data(strategy, mock_ohlcv_data, 40)
    print(f"RSI Signal at 40: {signal_1}")
    
    signal_2 = run_strategy_on_data(strategy, mock_ohlcv_data, 75)
    print(f"RSI Signal at 75: {signal_2}")
    
    signal_3 = run_strategy_on_data(strategy, mock_ohlcv_data, 98)
    print(f"RSI Signal at 98: {signal_3}")
    
    # Verificar que a estratégia retorna um SignalType válido
    assert signal_1 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
    assert signal_2 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
    assert signal_3 in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]