# --- synapse_trader/bots/arbitrage.py ---

import logging
import asyncio
import time
from typing import Dict, Tuple, List, Optional, Any
from decimal import Decimal, ROUND_DOWN 

from synapse_trader.bots.base_bot import BaseBot
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.utils.symbol_filters import SymbolFilters
from synapse_trader.utils.config import settings

logger = logging.getLogger(__name__)

FEE_PERCENT = Decimal(settings.BINANCE_FEE_PERCENT)
ONE_MINUS_FEE = Decimal('1.0') - FEE_PERCENT

# Quantidade base inicial para a arbitragem (em USDT ou equivalente)
INITIAL_TRADE_AMOUNT_USDT = Decimal("11.0") 

class ArbitrageBot(BaseBot):
    """
    Monitoriza triângulos de pares para oportunidades de arbitragem
    e executa as 3 ordens atomicamente.
    """

    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager,
                 binance_client: BinanceClient,
                 symbol_filters: SymbolFilters):
        
        super().__init__(event_bus, state_manager)
        self.binance_client = binance_client
        self.symbol_filters = symbol_filters
        
        self.triangles: List[Tuple[str, str, str]] = self._parse_triangles(settings.ARBITRAGE_TRIANGLES)
        self.min_profit_percent = Decimal(settings.ARBITRAGE_MIN_PROFIT)
        
        self.tickers: Dict[str, Dict[str, Decimal]] = {}
        self.symbol_to_triangles: Dict[str, List[Tuple[str, str, str]]] = {}
        
        self.streams: List[str] = self._build_streams_and_map()
        
        self.executing: bool = False 
        self.cooldown_until: float = 0.0
        
        if not self.triangles:
            logger.warning("[ArbitrageBot] Nenhum triângulo configurado.")
        else:
            logger.info(f"[ArbitrageBot] A monitorizar {len(self.triangles)} triângulos.")

    def _parse_triangles(self, triangles_str: str) -> List[Tuple[str, str, str]]:
        triangles = []
        if not triangles_str: return triangles
        try:
            groups = triangles_str.split(';')
            for group in groups:
                assets = [asset.strip().upper() for asset in group.split(',')]
                if len(assets) == 3:
                    triangles.append(tuple(assets))
                else:
                    logger.warning(f"[ArbitrageBot] Grupo de triângulo inválido ignorado: {group}")
            return triangles
        except Exception as e:
            logger.error(f"[ArbitrageBot] Erro ao parsear ARBITRAGE_TRIANGLES: {e}")
            return []

    def _get_pair(self, asset1: str, asset2: str) -> Optional[str]:
        pair1 = f"{asset1}{asset2}"
        pair2 = f"{asset2}{asset1}"
        
        # Acessa diretamente o dict de filtros (assumindo que já foi carregado)
        if hasattr(self.symbol_filters, '_filters'):
             if pair1 in self.symbol_filters._filters: return pair1
             if pair2 in self.symbol_filters._filters: return pair2
        else:
             logger.error("[ArbitrageBot] Tentativa de _get_pair antes do SymbolFilters ser carregado!")
             return None
        
        logger.debug(f"[ArbitrageBot] Par não encontrado na Binance: {asset1}/{asset2}")
        return None

    def _build_streams_and_map(self) -> List[str]:
        streams = set()
        self.symbol_to_triangles = {}
        valid_triangles_count = 0
        
        for triangle in self.triangles:
            a, b, c = triangle
            pair_ab = self._get_pair(a, b)
            pair_bc = self._get_pair(b, c)
            pair_ac = self._get_pair(a, c)
            pairs = [pair_ab, pair_bc, pair_ac]
            
            if None in pairs:
                logger.warning(f"[ArbitrageBot] Triângulo {triangle} inválido (par não encontrado). A ignorar.")
                continue

            valid_triangles_count += 1
            logger.info(f"[ArbitrageBot] Triângulo válido encontrado: {pairs}")
            
            for pair in pairs:
                streams.add(f"{pair.lower()}@bookTicker")
                if pair not in self.symbol_to_triangles:
                    self.symbol_to_triangles[pair] = []
                if triangle not in self.symbol_to_triangles[pair]:
                    self.symbol_to_triangles[pair].append(triangle)
                         
        logger.info(f"[ArbitrageBot] Monitorizando {len(streams)} streams para {valid_triangles_count} triângulos.")
        return list(streams)


    async def _handle_ticker_message(self, msg: dict):
        """Callback para o stream @bookTicker."""
        try:
            data = msg.get('data', {})
            symbol = data.get('s')
            
            if symbol and symbol in self.symbol_to_triangles:
                bid = data.get('b')
                ask = data.get('a')
                if bid is None or ask is None: return 
                
                self.tickers[symbol] = {
                    "bid": Decimal(bid), 
                    "ask": Decimal(ask) 
                }
                
                tasks = [self._check_arbitrage_opportunity(triangle) 
                         for triangle in self.symbol_to_triangles[symbol]]
                if tasks:
                    await asyncio.gather(*tasks)
                    
        except Exception as e:
            logger.error(f"[ArbitrageBot] Erro ao processar bookTicker: {e}", exc_info=True)


    async def _check_arbitrage_opportunity(self, triangle: Tuple[str, str, str]):
        """Verifica se existe uma oportunidade de arbitragem."""
        if self.executing or time.time() < self.cooldown_until: return
            
        a, b, c = triangle
        pair_ab = self._get_pair(a, b)
        pair_bc = self._get_pair(b, c)
        pair_ac = self._get_pair(a, c)
        
        if not all([pair_ab, pair_bc, pair_ac]): return 
        
        ticker_ab = self.tickers.get(pair_ab)
        ticker_bc = self.tickers.get(pair_bc)
        ticker_ac = self.tickers.get(pair_ac)
        
        if not all([ticker_ab, ticker_bc, ticker_ac]): return
        
        start_amount = Decimal('1.0')
        
        # --- Rota 1: A -> B -> C -> A ---
        try:
            if pair_ab.endswith(a): 
                amount_b = start_amount / ticker_ab['ask'] * ONE_MINUS_FEE
            else: 
                amount_b = start_amount * ticker_ab['bid'] * ONE_MINUS_FEE
            if pair_bc.endswith(b): 
                amount_c = amount_b / ticker_bc['ask'] * ONE_MINUS_FEE
            else: 
                amount_c = amount_b * ticker_bc['bid'] * ONE_MINUS_FEE
            if pair_ac.endswith(c): 
                end_amount_a_r1 = amount_c / ticker_ac['ask'] * ONE_MINUS_FEE
            else: 
                end_amount_a_r1 = amount_c * ticker_ac['bid'] * ONE_MINUS_FEE
            
            profit_r1 = ((end_amount_a_r1 - start_amount) / start_amount) * Decimal('100.0')
        except Exception: profit_r1 = Decimal('-100.0')

        # --- Rota 2: A -> C -> B -> A ---
        try:
            if pair_ac.endswith(a): 
                amount_c = start_amount / ticker_ac['ask'] * ONE_MINUS_FEE
            else: 
                amount_c = start_amount * ticker_ac['bid'] * ONE_MINUS_FEE
            if pair_bc.endswith(c): 
                amount_b = amount_c / ticker_bc['ask'] * ONE_MINUS_FEE
            else: 
                amount_b = amount_c * ticker_bc['bid'] * ONE_MINUS_FEE
            if pair_ab.endswith(b): 
                end_amount_a_r2 = amount_b / ticker_ab['ask'] * ONE_MINUS_FEE
            else: 
                end_amount_a_r2 = amount_b * ticker_ab['bid'] * ONE_MINUS_FEE

            profit_r2 = ((end_amount_a_r2 - start_amount) / start_amount) * Decimal('100.0')
        except Exception: profit_r2 = Decimal('-100.0')
        
        # --- Verificação e Execução ---
        if profit_r1 > self.min_profit_percent:
            logger.info(f"[ArbitrageBot] OPORTUNIDADE R1 {triangle}: Lucro: {profit_r1:.4f}%")
            asyncio.create_task(self._execute_arbitrage(triangle, "R1", 
                                                         (pair_ab, pair_bc, pair_ac), 
                                                         (ticker_ab, ticker_bc, ticker_ac)))
        elif profit_r2 > self.min_profit_percent:
            logger.info(f"[ArbitrageBot] OPORTUNIDADE R2 {triangle}: Lucro: {profit_r2:.4f}%")
            asyncio.create_task(self._execute_arbitrage(triangle, "R2", 
                                                         (pair_ac, pair_bc, pair_ab), 
                                                         (ticker_ac, ticker_bc, ticker_ab)))

    def _calculate_order_params(self, 
                                pair: str, 
                                input_asset: str, 
                                input_amount: Decimal, 
                                ticker: Dict[str, Decimal]
                                ) -> Tuple[Optional[Dict[str, Any]], Optional[Decimal], Optional[str], Optional[Decimal]]:
        """
        Calcula os parâmetros (side, quantity) para uma perna da arbitragem,
        aplica stepSize e retorna os params, o output_amount (líquido de taxa)
        e o output_asset, juntamente com o preço de execução.
        """
        try:
            symbol_info = self.symbol_filters._filters.get(pair)
            if not symbol_info: return None, None, None, None
            
            base_asset = symbol_info.get('baseAsset')
            quote_asset = symbol_info.get('quoteAsset')

            # 1. Determina Lado, Preço e Qtd não ajustada
            if input_asset == quote_asset: # Ex: Temos USDT, par é BTCUSDT -> BUY BTC
                side = "BUY"
                price = ticker['ask']
                if price == 0: return None, None, None, None
                order_qty_unadjusted = input_amount / price
                output_asset = base_asset
            elif input_asset == base_asset: # Ex: Temos ETH, par é ETHBTC -> SELL ETH
                side = "SELL"
                price = ticker['bid']
                order_qty_unadjusted = input_amount
                output_asset = quote_asset
            else:
                logger.error(f"[ArbitrageBot] Asset de input {input_asset} inválido para par {pair}")
                return None, None, None, None

            # 2. Aplica stepSize (arredonda PARA BAIXO)
            adjusted_qty = self.symbol_filters.adjust_quantity_to_step(pair, float(order_qty_unadjusted))
            adjusted_qty_decimal = Decimal(str(adjusted_qty))

            if adjusted_qty_decimal <= 0:
                logger.debug(f"[ArbitrageBot] Quantidade ajustada é zero para {pair} (Qty: {order_qty_unadjusted})")
                return None, None, None, None

            # 3. Calcula o output_amount LÍQUIDO (após taxa) com a quantidade AJUSTADA
            if side == "BUY":
                final_output_amount = adjusted_qty_decimal * price * ONE_MINUS_FEE
            else: # SELL
                final_output_amount = adjusted_qty_decimal * price * ONE_MINUS_FEE

            params = {
                "symbol": pair,
                "side": side,
                "type": "MARKET",
                "quantity": float(adjusted_qty), 
                "newClientOrderId": f"arb_{pair}_{int(time.time() * 1000)}_{side}" 
            }
            
            return params, final_output_amount, output_asset, price

        except Exception as e:
            logger.error(f"[ArbitrageBot] Erro em _calculate_order_params para {pair}: {e}", exc_info=True)
            return None, None, None, None

    async def _execute_arbitrage(self, 
                                 triangle: Tuple[str, str, str], 
                                 route_name: str, 
                                 pairs: Tuple[str, str, str], 
                                 tickers: Tuple[Dict[str, Decimal], Dict[str, Decimal], Dict[str, Decimal]]):
        """Tenta calcular e executar as 3 ordens MARKET."""
        
        if self.executing or time.time() < self.cooldown_until: return
            
        self.executing = True
        logger.warning(f"[ArbitrageBot] >> TENTANDO EXECUTAR {route_name} {triangle} <<")
        
        start_asset = triangle[0]
        pair1, pair2, pair3 = pairs
        ticker1, ticker2, ticker3 = tickers
        
        current_amount = INITIAL_TRADE_AMOUNT_USDT # Começa com a quantidade fixa
        current_asset = start_asset 
        
        # --- Cálculo das 3 Pernas (Sequencial) ---
        
        # Perna 1
        params1, amount2, asset2, price1 = self._calculate_order_params(pair1, current_asset, current_amount, ticker1)
        if params1 is None: 
            logger.warning(f"[ArbitrageBot] {route_name} {triangle}: Falha no cálculo da Perna 1.")
            self.executing = False; self.cooldown_until = time.time() + 1; return
            
        # Perna 2
        params2, amount3, asset3, price2 = self._calculate_order_params(pair2, asset2, amount2, ticker2)
        if params2 is None: 
            logger.warning(f"[ArbitrageBot] {route_name} {triangle}: Falha no cálculo da Perna 2.")
            self.executing = False; self.cooldown_until = time.time() + 1; return

        # Perna 3
        params3, final_amount, final_asset, price3 = self._calculate_order_params(pair3, asset3, amount3, ticker3)
        if params3 is None: 
            logger.warning(f"[ArbitrageBot] {route_name} {triangle}: Falha no cálculo da Perna 3.")
            self.executing = False; self.cooldown_until = time.time() + 1; return

        if final_asset != start_asset:
            logger.error(f"[ArbitrageBot] {route_name} {triangle}: Erro de lógica! Asset final ({final_asset}) diferente do inicial ({start_asset}). Abortando.")
            self.executing = False; self.cooldown_until = time.time() + settings.ARBITRAGE_COOLDOWN_SEC; return

        # Validação MIN_NOTIONAL
        valid1 = self.symbol_filters.validate_min_notional(pair1, params1['quantity'], float(price1))
        valid2 = self.symbol_filters.validate_min_notional(pair2, params2['quantity'], float(price2))
        valid3 = self.symbol_filters.validate_min_notional(pair3, params3['quantity'], float(price3))

        if not (valid1 and valid2 and valid3):
             logger.warning(f"[ArbitrageBot] {route_name} {triangle}: Falha na validação minNotional. Abortando.")
             self.executing = False; self.cooldown_until = time.time() + 1; return

        # --- Execução Concorrente ---
        logger.warning(f"[ArbitrageBot] {route_name} {triangle}: Cálculos OK, VALIDAÇÃO OK. A ENVIAR 3 ORDENS!")
        
        orders_ok = True
        try:
            tasks = [
                self.binance_client.create_order(**params1),
                self.binance_client.create_order(**params2),
                self.binance_client.create_order(**params3),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    orders_ok = False
                    logger.error(f"[ArbitrageBot] Erro na ordem {i+1} ({[pair1, pair2, pair3][i]}): {res}")
                else:
                    logger.info(f"[ArbitrageBot] Ordem {i+1} ({res.get('symbol')}) enviada. Status: {res.get('status')}")
            
        except Exception as e:
            logger.critical(f"[ArbitrageBot] Erro INESPERADO durante envio de ordens: {e}", exc_info=True)
            orders_ok = False
        finally:
            if orders_ok:
                logger.warning(f"[ArbitrageBot] Execução de {route_name} {triangle} CONCLUÍDA. Lucro Estimado (Líquido): {(final_amount - current_amount):.8f} {start_asset}")
            else:
                 logger.error(f"[ArbitrageBot] Execução de {route_name} {triangle} FALHOU. É NECESSÁRIO VERIFICAR SALDOS!")
                 
            self.cooldown_until = time.time() + settings.ARBITRAGE_COOLDOWN_SEC
            self.executing = False

    async def run(self):
        """Inicia o bot e o stream de bookTicker."""
        if not self.triangles or not self.streams:
            logger.warning("[ArbitrageBot] Inativo (sem triângulos ou streams válidos).")
            return

        logger.info(f"[ArbitrageBot] A iniciar stream @bookTicker para {len(self.streams)} pares...")
        bsm = self.binance_client.get_socket_manager()
        
        try:
             async with bsm.start_multiplex_socket(self.streams, self._handle_ticker_message) as socket:
                while True:
                    await socket.recv()
        except Exception as e:
             logger.critical(f"[ArbitrageBot] Stream @bookTicker FALHOU: {e}. Sem arbitragem!", exc_info=True)
             await asyncio.sleep(10)
             asyncio.create_task(self.run())
        logger.warning("[ArbitrageBot] Stream @bookTicker encerrado.")