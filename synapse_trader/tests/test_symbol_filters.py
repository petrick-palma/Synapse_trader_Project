# --- tests/test_symbol_filters.py ---

import pytest
from decimal import Decimal
import math

from synapse_trader.utils.symbol_filters import SymbolFilters
from synapse_trader.connectors.binance_client import BinanceClient
from unittest.mock import AsyncMock

# O SymbolFilters é um Singleton

@pytest.mark.asyncio
async def test_symbol_filters_load(mock_binance_client: AsyncMock):
    """Testa se os filtros podem ser carregados da Binance."""
    
    # Resetar o singleton para o teste
    SymbolFilters._instance = None
    filters_instance = SymbolFilters()
    filters_instance._loaded = False
    filters_instance._filters = {}
    
    mock_binance_client.get_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "TESTUSDT",
                "status": "TRADING",
                "baseAsset": "TEST",
                "quoteAsset": "USDT",
                "filters": [
                    {"filterType": "LOT_SIZE", "stepSize": "0.01000000", "minQty": "0.01000000"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.00010000"},
                    {"filterType": "MIN_NOTIONAL", "minNotional": "5.00000000"}
                ]
            }
        ]
    }
    
    await filters_instance.load_filters(mock_binance_client)
    
    assert filters_instance._loaded is True
    assert "TESTUSDT" in filters_instance._filters
    assert filters_instance.is_symbol_trading("TESTUSDT") is True
    assert filters_instance._get_filter("TESTUSDT", "LOT_SIZE") is not None


def test_adjust_quantity_to_step(mock_symbol_filters: SymbolFilters):
    """Testa o ajuste de quantidade ao stepSize (arredondamento para baixo)."""
    filters_instance = mock_symbol_filters
    
    # O mock_symbol_filters usa "BTCUSDT" com stepSize "0.00010000"
    
    qty_in = 0.12345678
    qty_expected = 0.1234
    qty_out = filters_instance.adjust_quantity_to_step("BTCUSDT", qty_in)
    assert qty_out == pytest.approx(qty_expected, abs=1e-6)
    
    qty_in_small = 0.000001
    qty_out_small = filters_instance.adjust_quantity_to_step("BTCUSDT", qty_in_small)
    assert qty_out_small == 0.0

    qty_in_exact = 1.5001
    qty_out_exact = filters_instance.adjust_quantity_to_step("BTCUSDT", qty_in_exact)
    assert qty_out_exact == 1.5001


def test_adjust_price_to_tick(mock_symbol_filters: SymbolFilters):
    """Testa o ajuste de preço ao tickSize (arredondamento para o tick mais próximo)."""
    filters_instance = mock_symbol_filters
    
    # O mock_symbol_filters usa "BTCUSDT" com tickSize "0.01000000"
    
    # Teste 1: Arredondamento para cima (para 0.13)
    price_in = 0.128
    price_expected = 0.13
    price_out = filters_instance.adjust_price_to_tick("BTCUSDT", price_in)
    assert price_out == pytest.approx(price_expected, abs=1e-3)

    # Teste 2: Arredondamento para baixo (para 1.00)
    price_in_down = 1.002
    price_expected_down = 1.00
    price_out_down = filters_instance.adjust_price_to_tick("BTCUSDT", price_in_down)
    assert price_out_down == pytest.approx(price_expected_down, abs=1e-3)
    
    # Teste 3: Metade (para 0.13)
    price_in_half = 0.125
    price_expected_half = 0.13
    price_out_half = filters_instance.adjust_price_to_tick("BTCUSDT", price_in_half)
    assert price_out_half == pytest.approx(price_expected_half, abs=1e-3)


def test_validate_min_notional(mock_symbol_filters: SymbolFilters):
    """Testa a validação de Min Notional."""
    filters_instance = mock_symbol_filters
    
    # O mock_symbol_filters usa "BTCUSDT" com minNotional "10.0"
    
    assert filters_instance.validate_min_notional("BTCUSDT", quantity=1.5, price=10.0) is True
    assert filters_instance.validate_min_notional("BTCUSDT", quantity=1.5, price=5.0) is False
    assert filters_instance.validate_min_notional("BTCUSDT", quantity=1.0, price=10.0) is True