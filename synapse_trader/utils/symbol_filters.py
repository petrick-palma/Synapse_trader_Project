# --- synapse_trader/utils/symbol_filters.py ---

import logging
import math
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP # <-- Importar ROUND_HALF_UP
from synapse_trader.connectors.binance_client import BinanceClient

logger = logging.getLogger(__name__)

class SymbolFilters:
    """
    Singleton para armazenar e aceder aos filtros de símbolos (regras de trading)
    da Binance (ex: stepSize, minNotional).
    """
    _instance = None
    _loaded = False
    _filters = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SymbolFilters, cls).__new__(cls)
        return cls._instance

    async def load_filters(self, binance_client: BinanceClient):
        """
        Carrega todos os filtros da exchange. Deve ser chamado no arranque.
        """
        if self._loaded:
            logger.info("[SymbolFilters] Filtros já carregados.")
            return

        try:
            logger.info("[SymbolFilters] A carregar filtros da Binance (exchangeInfo)...")
            exchange_info = await binance_client.get_exchange_info()
            
            for symbol_data in exchange_info.get("symbols", []):
                symbol = symbol_data.get("symbol")
                if not symbol: continue
                
                self._filters[symbol] = {
                    "status": symbol_data.get("status"),
                    "baseAsset": symbol_data.get("baseAsset"),
                    "quoteAsset": symbol_data.get("quoteAsset"),
                    "filters": {f["filterType"]: f for f in symbol_data.get("filters", [])}
                }
            
            self._loaded = True
            logger.info(f"[SymbolFilters] {len(self._filters)} filtros de símbolos carregados.")
            
        except Exception as e:
            logger.critical(f"[SymbolFilters] FALHA CRÍTICA ao carregar filtros: {e}", exc_info=True)
            raise RuntimeError(f"Falha ao carregar filtros da exchange: {e}")

    def _get_filter(self, symbol: str, filter_type: str) -> dict | None:
        """Helper para obter um filtro específico."""
        if not self._loaded:
            logger.error("[SymbolFilters] Tentativa de aceder a filtros antes de carregar.")
            return None
        return self._filters.get(symbol, {}).get("filters", {}).get(filter_type)

    def is_symbol_trading(self, symbol: str) -> bool:
        """Verifica se o símbolo está com o status 'TRADING'."""
        return self._filters.get(symbol, {}).get("status") == "TRADING"

    def adjust_quantity_to_step(self, symbol: str, quantity: float) -> float:
        """Ajusta a quantidade para o 'stepSize' (lote). Arredonda PARA BAIXO."""
        lot_size_filter = self._get_filter(symbol, "LOT_SIZE")
        if not lot_size_filter:
            logger.warning(f"[SymbolFilters] Sem filtro LOT_SIZE para {symbol}.")
            return quantity

        step_size_str = lot_size_filter.get("stepSize")
        if not step_size_str:
             logger.warning(f"[SymbolFilters] stepSize não encontrado para {symbol}.")
             return quantity
        
        try:
            quantity_d = Decimal(str(quantity))
            step_size_d = Decimal(step_size_str)
            if step_size_d == Decimal(0): return 0.0
            
            adjusted_qty = (quantity_d / step_size_d).to_integral_value(rounding=ROUND_DOWN) * step_size_d
            
            return float(adjusted_qty)
        except Exception as e:
            logger.error(f"Erro ao ajustar stepSize para {symbol}: {e}")
            return 0.0

    def adjust_price_to_tick(self, symbol: str, price: float) -> float:
        """Ajusta o preço para o 'tickSize'. Arredonda PARA O TICK MAIS PRÓXIMO."""
        price_filter = self._get_filter(symbol, "PRICE_FILTER")
        if not price_filter:
            logger.warning(f"[SymbolFilters] Sem filtro PRICE_FILTER para {symbol}.")
            return price
            
        tick_size_str = price_filter.get("tickSize")
        if not tick_size_str:
            logger.warning(f"[SymbolFilters] tickSize não encontrado para {symbol}.")
            return price
            
        try:
            price_d = Decimal(str(price))
            tick_size_d = Decimal(tick_size_str)
            if tick_size_d == Decimal(0): return price
            
            # --- CORREÇÃO: Lógica de arredondamento ao tick ---
            # (price / tick_size).round() * tick_size
            ticks_count = (price_d / tick_size_d).to_integral_value(rounding=ROUND_HALF_UP) # <-- Usa ROUND_HALF_UP
            adjusted_price = ticks_count * tick_size_d
            # ------------------------------------------------
            
            return float(adjusted_price)
            
        except Exception as e:
            logger.error(f"Erro ao ajustar tickSize para {symbol}: {e}")
            return price

    def validate_min_notional(self, symbol: str, quantity: float, price: float) -> bool:
        """Verifica se a ordem (qtd * preço) cumpre o valor 'minNotional'."""
        min_notional_filter = self._get_filter(symbol, "MIN_NOTIONAL")
        if not min_notional_filter:
            logger.warning(f"[SymbolFilters] Sem filtro MIN_NOTIONAL para {symbol}.")
            return True 

        min_notional_str = min_notional_filter.get("minNotional")
        if not min_notional_str:
            logger.warning(f"[SymbolFilters] minNotional não encontrado para {symbol}.")
            return True
            
        try:
            min_notional = Decimal(min_notional_str)
            order_value = Decimal(str(quantity)) * Decimal(str(price))
            
            if order_value < min_notional:
                logger.warning(f"[SymbolFilters] Ordem {symbol} REJEITADA (minNotional). "
                               f"Valor: {order_value:.4f} < Mínimo: {min_notional}")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Erro ao validar minNotional para {symbol}: {e}")
            return False 

# Instância Singleton
symbol_filters = SymbolFilters()