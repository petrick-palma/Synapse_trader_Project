# --- synapse_trader/bots/risk_manager.py ---

import logging
import asyncio
import pandas as pd
import time
from finta import TA
from typing import Dict, Any

from synapse_trader.bots.base_bot import BaseBot
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.utils.symbol_filters import SymbolFilters
from synapse_trader.core.types import (
    EVENT_TRADE_SIGNAL, EVENT_ORDER_REQUEST, TradeSignal, OrderRequest,
    OrderSide, OrderType, POSITIONS_COLLECTION
)
from synapse_trader.utils.config import settings
from synapse_trader.bots.strategist import KLINE_COLUMNS, DATA_FRAME_COLUMNS 

logger = logging.getLogger(__name__)

ATR_TIMEFRAME = "15m" 
ATR_PERIOD = 14
ATR_WARMUP_PERIOD = 50

SL_ATR_MULTIPLIER = 1.5 
TP_ATR_MULTIPLIER = 3.0 

class RiskManagerBot(BaseBot):
    """
    Ouve Sinais de Trade, aplica gestão de risco,
    calcula o tamanho da posição e os níveis de SL/TP.
    """

    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager,
                 binance_client: BinanceClient,
                 symbol_filters: SymbolFilters):
        
        super().__init__(event_bus, state_manager)
        self.binance_client = binance_client
        self.symbol_filters = symbol_filters

    async def _fetch_data_for_atr(self, symbol: str) -> pd.DataFrame:
        """Busca klines (15m) para calcular o ATR."""
        try:
            klines_list = await self.binance_client.get_klines(
                symbol=symbol, 
                interval=ATR_TIMEFRAME, 
                limit=ATR_WARMUP_PERIOD
            )
            
            logger.debug(f"[RiskManager] Klines recebidos: {len(klines_list)} para {symbol}")
            
            if not klines_list:
                 logger.warning(f"[RiskManager] _fetch_data_for_atr: Nenhum kline retornado para {symbol}.")
                 return pd.DataFrame()

            df = pd.DataFrame(klines_list, columns=KLINE_COLUMNS)
            
            # --- CORREÇÃO: A formatação deve ocorrer ANTES do astype ---
            # 1. Seleciona as colunas corretas
            df = df[DATA_FRAME_COLUMNS].copy()
            # 2. Converte o timestamp (necessário para o mock de teste)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            # 3. Converte os dados para float *depois* de selecionar
            df = df.astype(float)
            # -------------------------------------------------------------
            
            logger.debug(f"[RiskManager] DataFrame shape após processamento: {df.shape}")
            logger.debug(f"[RiskManager] Colunas do DataFrame: {df.columns.tolist()}")
            
            # Calcular ATR
            df['ATR'] = TA.ATR(df, period=ATR_PERIOD)
            
            # CORREÇÃO: Usar métodos modernos para preencher NaN
            if df['ATR'].isna().all():
                logger.warning(f"[RiskManager] ATR calculado com todos os valores NaN.")
                # Tentar preencher com valor padrão se todos forem NaN
                df['ATR'] = 100.0  # Valor padrão conservador
            else:
                # Preencher valores NaN restantes
                df['ATR'] = df['ATR'].bfill().ffill()
            
            logger.debug(f"[RiskManager] ATR calculado. Valores não-NaN: {df['ATR'].notna().sum()}")
            logger.debug(f"[RiskManager] Último ATR: {df['ATR'].iloc[-1] if not df.empty else 'N/A'}")
            
            return df
            
        except Exception as e:
            logger.error(f"[RiskManager] Erro ao buscar dados para ATR ({symbol}): {e}", exc_info=True)
            return pd.DataFrame()

    async def _get_available_balance(self) -> float:
        """Busca o saldo 'free' da moeda de cotação (ex: USDT)."""
        try:
            account_info = await self.binance_client.get_account_info()
            balances = account_info.get("balances", [])
            for balance in balances:
                if balance.get("asset") == settings.QUOTE_ASSET:
                    free_balance = float(balance.get("free", 0.0))
                    logger.debug(f"[RiskManager] Saldo disponível: {free_balance} {settings.QUOTE_ASSET}")
                    return free_balance
            
            logger.warning(f"[RiskManager] Saldo para {settings.QUOTE_ASSET} não encontrado.")
            return 0.0
        except Exception as e:
            logger.error(f"[RiskManager] Erro ao buscar saldo da conta: {e}", exc_info=True)
            return 0.0

    async def _on_trade_signal(self, message: dict):
        """Callback para o evento EVENT_TRADE_SIGNAL."""
        try:
            signal = TradeSignal(**message)
            symbol = signal.symbol
            side = signal.side
            
            logger.info(f"[RiskManager] Sinal de trade recebido: {side.value} {symbol} (Estratégia: {signal.strategy})")

            open_positions = await self.state_manager.get_collection(POSITIONS_COLLECTION)
            if len(open_positions) >= settings.MAX_CONCURRENT_TRADES:
                logger.warning(
                    f"[RiskManager] REJEITADO (Regra): Máximo de trades concorrentes "
                    f"({settings.MAX_CONCURRENT_TRADES}) atingido."
                )
                return

            if symbol in open_positions:
                logger.warning(
                    f"[RiskManager] REJEITADO (Regra): Posição para {symbol} já está aberta."
                )
                return

            df_atr = await self._fetch_data_for_atr(symbol)
            
            # DEBUG: Verificar o estado do DataFrame
            logger.debug(f"[RiskManager] DataFrame ATR vazio: {df_atr.empty}")
            if not df_atr.empty:
                logger.debug(f"[RiskManager] Colunas no DataFrame ATR: {df_atr.columns.tolist()}")
                logger.debug(f"[RiskManager] 'ATR' nas colunas: {'ATR' in df_atr.columns}")
                if 'ATR' in df_atr.columns:
                    logger.debug(f"[RiskManager] ATR tem valores NaN: {df_atr['ATR'].isna().all()}")
                    logger.debug(f"[RiskManager] Últimos valores ATR: {df_atr['ATR'].tail().tolist()}")
            
            if df_atr.empty or 'ATR' not in df_atr.columns or df_atr['ATR'].isna().all():
                logger.error(f"[RiskManager] REJEITADO (Dados): Não foi possível calcular o ATR para {symbol}.")
                logger.error(f"[RiskManager] DataFrame vazio: {df_atr.empty}, 'ATR' nas colunas: {'ATR' in df_atr.columns if not df_atr.empty else 'N/A'}")
                return
                
            current_price = df_atr.iloc[-1]['close']
            atr_value = df_atr.iloc[-1]['ATR']
            
            logger.debug(f"[RiskManager] Preço atual: {current_price}, ATR: {atr_value}")
            
            if atr_value == 0 or pd.isna(atr_value):
                logger.error(f"[RiskManager] REJEITADO (Dados): Valor do ATR é zero ou NaN para {symbol}.")
                return

            distance_to_sl = atr_value * SL_ATR_MULTIPLIER
            distance_to_tp = atr_value * TP_ATR_MULTIPLIER
            
            if side == OrderSide.BUY:
                sl_price = current_price - distance_to_sl
                tp_price = current_price + distance_to_tp
            else: # OrderSide.SELL
                sl_price = current_price + distance_to_sl
                tp_price = current_price - distance_to_tp
                
            sl_price = self.symbol_filters.adjust_price_to_tick(symbol, sl_price)
            tp_price = self.symbol_filters.adjust_price_to_tick(symbol, tp_price)

            total_balance = await self._get_available_balance()
            if total_balance <= 0:
                 logger.error(f"[RiskManager] REJEITADO (Saldo): Saldo 0 em {settings.QUOTE_ASSET}.")
                 return
            
            risk_per_trade_usd = total_balance * settings.RISK_PER_TRADE_PERCENT
            risk_per_unit_usd = abs(current_price - sl_price)
            
            logger.debug(f"[RiskManager] Saldo total: {total_balance}, Risco por trade: {risk_per_trade_usd}")
            logger.debug(f"[RiskManager] Risco por unidade: {risk_per_unit_usd}")
            
            if risk_per_unit_usd == 0:
                logger.error(f"[RiskManager] REJEITADO (Cálculo): Risco por unidade é zero (SL muito próximo).")
                return

            quantity = risk_per_trade_usd / risk_per_unit_usd
            
            logger.debug(f"[RiskManager] Quantidade calculada: {quantity}")
            
            quantity_adjusted = self.symbol_filters.adjust_quantity_to_step(symbol, quantity)
            
            logger.debug(f"[RiskManager] Quantidade ajustada: {quantity_adjusted}")
            
            if quantity_adjusted == 0:
                logger.warning(
                    f"[RiskManager] REJEITADO (Tamanho): Quantidade calculada ({quantity}) "
                    f"foi ajustada para 0 (stepSize)."
                )
                return

            if not self.symbol_filters.validate_min_notional(symbol, quantity_adjusted, current_price):
                logger.warning(
                    f"[RiskManager] REJEITADO (Regra): Ordem (Qtd: {quantity_adjusted}) "
                    f"não cumpre o valor 'MIN_NOTIONAL'."
                )
                return

            order_type = OrderType.MARKET
            client_order_id = f"syn_{side.value}_{symbol}_{int(time.time() * 1000)}"

            order_request = OrderRequest(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity_adjusted,
                client_order_id=client_order_id,
                price=None,
                sl_price=sl_price, 
                tp_price=tp_price, 
                timeout_seconds=None,
                strategy=signal.strategy 
            )
            
            logger.info(
                f"[RiskManager] APROVADO. A publicar EVENT_ORDER_REQUEST:\n"
                f"Símbolo: {symbol}, Lado: {side.value}, Qtd: {quantity_adjusted}\n"
                f"Preço Entrada (Aprox): {current_price:.4f}, SL: {sl_price:.4f}, TP: {tp_price:.4f}\n"
                f"Risco (USD): {risk_per_trade_usd:.2f}"
            )

            await self._publish(EVENT_ORDER_REQUEST, order_request.model_dump())

        except Exception as e:
            logger.error(f"[RiskManager] Erro fatal ao processar sinal de trade: {e}", exc_info=True)

    async def run(self):
        """Inicia o bot e subscreve aos eventos."""
        logger.info("[RiskManager] A subscrever ao tópico TRADE_SIGNAL.")
        await self._subscribe(EVENT_TRADE_SIGNAL, self._on_trade_signal)
        
        while True:
            await asyncio.sleep(3600)