# --- tests/conftest.py ---

import pytest
import pandas as pd
import numpy as np
from unittest.mock import AsyncMock, MagicMock
from decimal import Decimal
import os
from typing import Optional, List, Any

# Informa a aplicação que estamos em modo de teste (corrige erro de API Key)
os.environ["PYTEST_RUNNING"] = "1" 

# Importa módulos do projeto
from synapse_trader.utils.symbol_filters import SymbolFilters
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.core.types import OrderRequest, TradeSignal, OrderSide, OrderType
from synapse_trader.utils.config import settings

# --- Mock de Dados OHLCV ---

@pytest.fixture
def mock_ohlcv_data():
    """
    Cria um DataFrame de klines simulado (100 velas) 
    para testes de estratégia com movimentos mais claros.
    """
    
    # CORREÇÃO: Criar dados com movimentos mais pronunciados para gerar sinais
    np.random.seed(42)  # Para resultados consistentes
    
    n_points = 100
    
    # Fase 1: Tendência lateral (índices 0-29)
    base_prices = 100 + np.cumsum(np.random.normal(0, 0.5, 30))
    
    # Fase 2: Tendência de alta forte (índices 30-59) - para gerar BUY
    uptrend = np.linspace(base_prices[-1], base_prices[-1] + 25, 30)
    
    # Fase 3: Correção (índices 60-69)
    correction = np.linspace(uptrend[-1], uptrend[-1] - 10, 10)
    
    # Fase 4: Segunda tendência de alta (índices 70-89)
    second_uptrend = np.linspace(correction[-1], correction[-1] + 20, 20)
    
    # Fase 5: Tendência de baixa final (índices 90-99)
    downtrend = np.linspace(second_uptrend[-1], second_uptrend[-1] - 15, 10)
    
    close_prices = np.concatenate([base_prices, uptrend, correction, second_uptrend, downtrend])
    
    # Garantir que temos exatamente n_points
    close_prices = close_prices[:n_points]
    
    # Criar OHLC realistas
    data = {
        'open': close_prices - np.random.uniform(0.1, 0.5, n_points),
        'high': close_prices + np.random.uniform(0.3, 1.0, n_points),
        'low': close_prices - np.random.uniform(0.3, 1.0, n_points),
        'close': close_prices,
        'volume': np.full(n_points, 1000.0) + np.random.normal(0, 100, n_points)
    }
    
    df = pd.DataFrame(data)
    index = pd.to_datetime(pd.date_range(start='2024-01-01', periods=len(df), freq='15min'))
    df.set_index(index, inplace=True)

    return df
# --- Mock de Clientes e Serviços ---

@pytest.fixture
def mock_event_bus():
    """Mock do EventBus (Pub/Sub ou Redis)."""
    mock = AsyncMock()
    mock.publish = AsyncMock()
    mock.subscribe = AsyncMock()
    return mock

@pytest.fixture
def mock_state_manager():
    """Mock do StateManager (Firestore ou Redis) para simular estado e posições."""
    mock = AsyncMock()
    
    # Default: 0 posições abertas
    mock.get_collection.return_value = {} 
    
    mock.get_state.return_value = None 
    mock.set_state = AsyncMock()
    mock.delete_state = AsyncMock()
    return mock

@pytest.fixture
def mock_binance_client():
    """Mock do BinanceClient para simular API REST e saldos."""
    mock = AsyncMock(spec=BinanceClient)

    async def get_account_side_effect():
        return {
            "balances": [
                {"asset": "USDT", "free": "1000.00"},
                {"asset": "BTC", "free": "0.5"},
            ]
        }
    
    async def get_klines_side_effect(symbol: str, interval: str, limit: int, 
                                     start_str: Optional[str] = None, 
                                     end_str: Optional[str] = None) -> List[List[Any]]:
        # Retorna dados mais realistas com timestamp crescente
        base_timestamp = 1609459200000
        klines = []
        for i in range(limit):
            base_price = 20000.0 + (i * 10)
            kline = [
                base_timestamp + (i * 900000),  # +15min
                str(base_price - 50), str(base_price + 50), str(base_price - 50), str(base_price),
                "1000", "0", "0", "0", "0", "0", "0"
            ]
            klines.append(kline)
        return klines

    mock.get_account_info.side_effect = get_account_side_effect
    mock.get_klines.side_effect = get_klines_side_effect
    mock.health_check.return_value = {"msg": "ok"}
    mock.create_order.return_value = {"status": "NEW", "orderId": 12345}
    
    return mock

@pytest.fixture
def mock_symbol_filters():
    """Mock do SymbolFilters (singleton) com dados de filtro pré-carregados."""
    
    btc_filters = {
        "LOT_SIZE": {"stepSize": "0.00010000", "minQty": "0.00010000"},
        "PRICE_FILTER": {"tickSize": "0.01000000"},
        "MIN_NOTIONAL": {"minNotional": "10.00000000"}
    }
    
    filters = {
        "BTCUSDT": {"filters": btc_filters, "status": "TRADING"},
        "ETHUSDT": {"filters": btc_filters, "status": "TRADING"},
        "ETHBTC": {"filters": btc_filters, "status": "TRADING"},
        "BNBUSDT": {"filters": btc_filters, "status": "TRADING"},
    }

    # Usamos uma instância REAL para testar, preenchendo os filtros
    filters_instance = SymbolFilters()
    filters_instance._filters = filters
    filters_instance._loaded = True
    
    return filters_instance

# --- Fixtures de Modelos ---

@pytest.fixture
def sample_trade_signal():
    """Retorna um TradeSignal de exemplo."""
    return TradeSignal(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        strategy="TestStrategy+DRL"
    )