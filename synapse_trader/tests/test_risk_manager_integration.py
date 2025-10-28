# --- tests/test_risk_manager_integration.py ---

import pytest
import pandas as pd 
import numpy as np
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal

from synapse_trader.bots.risk_manager import RiskManagerBot

from synapse_trader.core.types import (
    EVENT_TRADE_SIGNAL, EVENT_ORDER_REQUEST, OrderSide, OrderType, 
    TradeSignal, OrderRequest, POSITIONS_COLLECTION
)
from synapse_trader.bots.strategist import KLINE_COLUMNS, DATA_FRAME_COLUMNS 

@pytest.mark.asyncio
async def test_risk_manager_calculates_position_size_correctly(mock_event_bus, 
                                                            mock_state_manager, 
                                                            mock_binance_client, 
                                                            mock_symbol_filters, 
                                                            sample_trade_signal):
    """
    Testa se o RiskManager calcula corretamente o tamanho da posição
    baseado no Risco (0.5% do Saldo) e na Distância do SL (1.5x ATR).
    """

    # --- Configurações de Mock ---
    
    # 1. Mock do get_klines para retornar dados estruturados
    async def get_klines_side_effect(symbol, interval, limit):
        # Criar dados mais realistas com variação de preços
        base_timestamp = 1609459200000  # Timestamp base
        klines = []
        for i in range(limit):
            base_price = 20000.0 + (i * 10)  # Pequena tendência de alta
            kline = [
                base_timestamp + (i * 900000),  # +15min por kline
                str(base_price - 50),  # open
                str(base_price + 50),  # high  
                str(base_price - 50),  # low
                str(base_price),       # close
                "1000", "0", "0", "0", "0", "0", "0"
            ]
            klines.append(kline)
        return klines
    
    mock_binance_client.get_klines.side_effect = get_klines_side_effect

    # 2. Mock do StateManager - 0 posições abertas
    mock_state_manager.get_collection.return_value = {}

    # --- Inicialização do Bot ---
    risk_manager = RiskManagerBot(
        mock_event_bus, mock_state_manager, mock_binance_client, mock_symbol_filters
    )

    # --- Mock do ATR diretamente no método _fetch_data_for_atr ---
    async def mock_fetch_data_for_atr(symbol: str):
        # Criar um DataFrame mock completo com ATR já calculado
        # CORREÇÃO: Usar 50 períodos para corresponder ao ATR_WARMUP_PERIOD
        index = pd.date_range(start='2024-01-01', periods=50, freq='15min')
        
        # CORREÇÃO: Último preço será 20490.0 (20000 + 49*10)
        mock_df = pd.DataFrame({
            'open': [19950.0 + (i * 10) for i in range(50)],
            'high': [20050.0 + (i * 10) for i in range(50)],
            'low': [19950.0 + (i * 10) for i in range(50)],
            'close': [20000.0 + (i * 10) for i in range(50)],  # 20000 + 49*10 = 20490
            'volume': [1000.0] * 50,
            'ATR': [100.0] * 50  # ATR constante de 100
        }, index=index)

        return mock_df

    # Substituir o método original pelo mock
    risk_manager._fetch_data_for_atr = mock_fetch_data_for_atr

    # --- Execução ---
    await risk_manager._on_trade_signal(sample_trade_signal.model_dump())

    # --- Assertions ---
    # Risco Máximo = 1000 * 0.005 = 5.00 USDT
    # Distância SL = 1.5 * ATR (100) = 150 USD
    # Quantidade Ajustada = 5.00 / 150 ≈ 0.0333 BTC

    mock_event_bus.publish.assert_called_once()
    
    published_message = mock_event_bus.publish.call_args[0][1]
    order_req = OrderRequest(**published_message)
    
    assert order_req.symbol == "BTCUSDT"
    assert order_req.side == OrderSide.BUY
    assert order_req.order_type == OrderType.MARKET
    assert order_req.quantity == pytest.approx(0.0333, abs=1e-4) 
    
    # CORREÇÃO: Último preço será 20490.0 (20000 + 49*10), então:
    # SL = 20490 - 150 = 20340.0, TP = 20490 + 300 = 20790.0
    assert order_req.sl_price == pytest.approx(20340.0, abs=0.01)
    assert order_req.tp_price == pytest.approx(20790.0, abs=0.01)


@pytest.mark.asyncio
async def test_risk_manager_rejects_on_max_concurrent_trades(mock_event_bus, mock_state_manager, mock_binance_client, mock_symbol_filters, sample_trade_signal):
    """
    Testa se o bot rejeita o sinal se já houver muitas posições abertas.
    """
    
    # Mock com 11 posições abertas (MAX_CONCURRENT_TRADES é 10 por padrão)
    mock_state_manager.get_collection.return_value = {f"SYM{i}USDT": {} for i in range(11)}
    
    risk_manager = RiskManagerBot(
        mock_event_bus, mock_state_manager, mock_binance_client, mock_symbol_filters
    )
    
    await risk_manager._on_trade_signal(sample_trade_signal.model_dump())
    
    # O publish NÃO deve ter sido chamado
    mock_event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_risk_manager_handles_atr_calculation_failure(mock_event_bus, mock_state_manager, mock_binance_client, mock_symbol_filters, sample_trade_signal):
    """
    Testa se o RiskManager rejeita o sinal quando o ATR não pode ser calculado.
    """
    
    # Mock do get_klines para retornar dados válidos
    async def get_klines_side_effect(symbol, interval, limit):
        base_timestamp = 1609459200000
        klines = []
        for i in range(limit):
            base_price = 20000.0 + (i * 10)
            kline = [
                base_timestamp + (i * 900000),
                str(base_price - 50), str(base_price + 50), str(base_price - 50), str(base_price),
                "1000", "0", "0", "0", "0", "0", "0"
            ]
            klines.append(kline)
        return klines
    
    mock_binance_client.get_klines.side_effect = get_klines_side_effect

    # Mock do StateManager - 0 posições abertas
    mock_state_manager.get_collection.return_value = {}

    # --- Inicialização do Bot ---
    risk_manager = RiskManagerBot(
        mock_event_bus, mock_state_manager, mock_binance_client, mock_symbol_filters
    )

    # --- Mock do ATR para retornar DataFrame com ATR NaN ---
    async def mock_fetch_data_for_atr_nan(symbol: str):
        index = pd.date_range(start='2024-01-01', periods=50, freq='15min')
        
        mock_df = pd.DataFrame({
            'open': [19950.0 + (i * 10) for i in range(50)],
            'high': [20050.0 + (i * 10) for i in range(50)],
            'low': [19950.0 + (i * 10) for i in range(50)],
            'close': [20000.0 + (i * 10) for i in range(50)],
            'volume': [1000.0] * 50,
            'ATR': [np.nan] * 50  # ATR com valores NaN
        }, index=index)
        
        return mock_df

    # Substituir o método original pelo mock
    risk_manager._fetch_data_for_atr = mock_fetch_data_for_atr_nan

    # --- Execução ---
    await risk_manager._on_trade_signal(sample_trade_signal.model_dump())

    # --- Assertions ---
    # O publish NÃO deve ter sido chamado porque o ATR é NaN
    mock_event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_risk_manager_handles_insufficient_balance(mock_event_bus, mock_state_manager, mock_binance_client, mock_symbol_filters, sample_trade_signal):
    """
    Testa se o RiskManager rejeita o sinal quando o saldo é insuficiente.
    """
    
    # Mock do get_klines para retornar dados válidos
    async def get_klines_side_effect(symbol, interval, limit):
        base_timestamp = 1609459200000
        klines = []
        for i in range(limit):
            base_price = 20000.0 + (i * 10)
            kline = [
                base_timestamp + (i * 900000),
                str(base_price - 50), str(base_price + 50), str(base_price - 50), str(base_price),
                "1000", "0", "0", "0", "0", "0", "0"
            ]
            klines.append(kline)
        return klines
    
    mock_binance_client.get_klines.side_effect = get_klines_side_effect

    # Mock do StateManager - 0 posições abertas
    mock_state_manager.get_collection.return_value = {}

    # Mock do saldo da conta para retornar 0
    async def mock_get_account_info():
        return {
            "balances": [
                {"asset": "USDT", "free": "0.00"},  # Saldo zero
                {"asset": "BTC", "free": "0.5"},
            ]
        }
    
    mock_binance_client.get_account_info.side_effect = mock_get_account_info

    # --- Inicialização do Bot ---
    risk_manager = RiskManagerBot(
        mock_event_bus, mock_state_manager, mock_binance_client, mock_symbol_filters
    )

    # --- Mock do ATR ---
    async def mock_fetch_data_for_atr(symbol: str):
        index = pd.date_range(start='2024-01-01', periods=50, freq='15min')
        
        mock_df = pd.DataFrame({
            'open': [19950.0 + (i * 10) for i in range(50)],
            'high': [20050.0 + (i * 10) for i in range(50)],
            'low': [19950.0 + (i * 10) for i in range(50)],
            'close': [20000.0 + (i * 10) for i in range(50)],
            'volume': [1000.0] * 50,
            'ATR': [100.0] * 50
        }, index=index)
        
        return mock_df

    risk_manager._fetch_data_for_atr = mock_fetch_data_for_atr

    # --- Execução ---
    await risk_manager._on_trade_signal(sample_trade_signal.model_dump())

    # --- Assertions ---
    # O publish NÃO deve ter sido chamado porque o saldo é zero
    mock_event_bus.publish.assert_not_called()