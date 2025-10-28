# --- synapse_trader/bots/monitor.py ---

import logging
import asyncio
import time
from datetime import datetime
from decimal import Decimal
from binance.streams import BinanceSocketManager
# Adicionar importação corrigida

from synapse_trader.bots.base_bot import BaseBot
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.core.types import (
    OrderRequest, Position, OrderSide, OrderType,
    EVENT_POSITION_OPENED, EVENT_POSITION_CLOSED, EVENT_ORDER_REQUEST,
    EVENT_PNL_UPDATE
)
from synapse_trader.utils import database
from synapse_trader.bots.executor import PENDING_ORDERS_COLLECTION

logger = logging.getLogger(__name__)

POSITIONS_COLLECTION = "positions"

class MonitorBot(BaseBot):
    """
    Bot de baixa latência para monitorizar fills, verificar SL/TP/TSL
    e publicar PNL, com tratamento de erros robusto.
    """

    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager,
                 binance_client: BinanceClient):
        
        super().__init__(event_bus, state_manager)
        self.binance_client = binance_client
        self.watched_symbols: set[str] = set()

    async def _load_initial_positions(self):
        """Carrega posições existentes."""
        logger.info("[MonitorBot] A carregar posições abertas existentes...")
        try:
            positions = await self.state_manager.get_collection(POSITIONS_COLLECTION)
            for symbol, pos_data in positions.items():
                 try:
                     Position.model_validate_json(pos_data) 
                     self.watched_symbols.add(symbol)
                 except Exception as val_err:
                      logger.error(f"[MonitorBot] Posição inválida encontrada no StateManager para {symbol}: {val_err}. Ignorando.")
            logger.info(f"[MonitorBot] {len(self.watched_symbols)} posições válidas carregadas.")
        except Exception as e:
            logger.critical(f"[MonitorBot] FALHA CRÍTICA ao carregar posições iniciais: {e}", exc_info=True)

    async def _listen_user_data_stream(self):
        """Inicia o socket de dados do utilizador."""
        logger.info("[MonitorBot] A iniciar stream de dados do utilizador...")
        bsm = self.binance_client.get_socket_manager()
        try:
            async with bsm.start_user_socket(self._handle_user_data_message) as socket:
                while True:
                    await socket.recv()
        except Exception as e:
             logger.critical(f"[MonitorBot] Stream de dados do utilizador FALHOU: {e}. Sem confirmação de ordens!", exc_info=True)
             await asyncio.sleep(10)
             asyncio.create_task(self._listen_user_data_stream())
        logger.warning("[MonitorBot] Stream de dados do utilizador encerrado.")


    async def _handle_user_data_message(self, msg: dict):
        """Callback para o socket de dados do utilizador."""
        try:
            if msg.get('e') == 'executionReport':
                if msg.get('X') == 'FILLED':
                    asyncio.create_task(self._process_order_fill(msg))
                elif msg.get('X') in ['CANCELED', 'REJECTED', 'EXPIRED']:
                     logger.warning(f"[MonitorBot] Ordem {msg.get('X')}: {msg.get('s')} ID:{msg.get('c')} Razão:{msg.get('r')}")
                     client_order_id = msg.get('c')
                     if client_order_id:
                         try:
                             await self.state_manager.delete_state(PENDING_ORDERS_COLLECTION, client_order_id)
                         except Exception as del_err:
                              logger.error(f"[MonitorBot] Falha ao limpar cache para ordem {msg.get('X')} {client_order_id}: {del_err}")
                     
        except Exception as e:
            logger.error(f"[MonitorBot] Erro ao processar mensagem do utilizador: {e}", exc_info=True)

    async def _process_order_fill(self, fill_msg: dict):
        """Processa uma ordem 'FILLED'."""
        client_order_id = fill_msg.get('c')
        symbol = fill_msg.get('s')
        
        if not client_order_id or not symbol:
             logger.error(f"[MonitorBot] Mensagem FILL inválida recebida: {fill_msg}")
             return

        logger.info(f"[MonitorBot] ORDEM PREENCHIDA (FILLED): {client_order_id} ({symbol})")
        
        cached_order_str: str | None = None
        order_req: OrderRequest | None = None
        
        try:
            # 1. Buscar ordem no cache e apagar
            try:
                cached_order_str = await self.state_manager.get_state(PENDING_ORDERS_COLLECTION, client_order_id)
                if not cached_order_str:
                    logger.warning(f"[MonitorBot] Ordem {client_order_id} preenchida, mas não encontrada no cache.")
                    return
                order_req = OrderRequest.model_validate_json(cached_order_str)
            except Exception as get_err:
                logger.critical(f"[MonitorBot] FALHA CRÍTICA ao ler cache para ordem preenchida {client_order_id}: {get_err}.", exc_info=True)
                return

            try:
                await self.state_manager.delete_state(PENDING_ORDERS_COLLECTION, client_order_id)
            except Exception as del_err:
                logger.error(f"[MonitorBot] Falha ao apagar cache para ordem preenchida {client_order_id}: {del_err}.", exc_info=True)
            
            fill_price = float(fill_msg.get('L')) 
            fill_qty = float(fill_msg.get('q'))   
            order_side = OrderSide(fill_msg.get('S'))
            fill_timestamp = datetime.utcfromtimestamp(fill_msg.get('T') / 1000.0)

            # --- Cenário A: ENTRADA ---
            if order_req and order_side == order_req.side and order_req.sl_price is not None:
                logger.info(f"[MonitorBot] {symbol} (ENTRADA) preenchida @ {fill_price}")
                
                new_position = Position(
                    symbol=symbol, strategy=order_req.strategy or "Unknown", side=order_side,
                    quantity=fill_qty, entry_price=fill_price, entry_timestamp=fill_timestamp,
                    sl_price=order_req.sl_price, tp_price=order_req.tp_price,
                    tsl_highest_price=fill_price
                )
                
                try:
                    await self.state_manager.set_state(POSITIONS_COLLECTION, symbol, new_position.model_dump_json())
                    self.watched_symbols.add(symbol)
                    await self._publish(EVENT_POSITION_OPENED, new_position.model_dump())
                    logger.info(f"[MonitorBot] Posição {symbol} criada com sucesso no StateManager.")
                except Exception as set_pos_err:
                    logger.critical(f"[MonitorBot] FALHA CRÍTICA ao salvar nova posição {symbol} no StateManager após FILL: {set_pos_err}. A posição NÃO será monitorizada!", exc_info=True)
                    if symbol in self.watched_symbols: self.watched_symbols.remove(symbol)

            # --- Cenário B: SAÍDA ---
            else:
                logger.info(f"[MonitorBot] {symbol} (SAÍDA) preenchida @ {fill_price}")
                
                old_pos: Position | None = None
                try:
                    old_pos_data = await self.state_manager.get_state(POSITIONS_COLLECTION, symbol)
                    if not old_pos_data:
                        logger.error(f"[MonitorBot] Ordem de SAÍDA {client_order_id} preenchida, mas sem posição aberta encontrada no StateManager!")
                        return
                    old_pos = Position.model_validate_json(old_pos_data)
                except Exception as get_old_pos_err:
                     logger.critical(f"[MonitorBot] FALHA CRÍTICA ao ler posição antiga {symbol} do StateManager após FILL de SAÍDA: {get_old_pos_err}. Estado pode ficar inconsistente.", exc_info=True)
                     return
                
                try:
                    await self.state_manager.delete_state(POSITIONS_COLLECTION, symbol)
                    logger.info(f"[MonitorBot] Posição {symbol} removida do StateManager.")
                except Exception as del_old_pos_err:
                     logger.error(f"[MonitorBot] Falha ao apagar posição antiga {symbol} do StateManager: {del_old_pos_err}.")

                try:
                    d_fill_price = Decimal(str(fill_price))
                    d_entry_price = Decimal(str(old_pos.entry_price))
                    d_quantity = Decimal(str(old_pos.quantity))
                    pnl = (d_fill_price - d_entry_price) * d_quantity if old_pos.side == OrderSide.BUY else (d_entry_price - d_fill_price) * d_quantity
                    entry_value = d_entry_price * d_quantity
                    pnl_percent = (pnl / entry_value) * Decimal('100') if entry_value != 0 else Decimal('0')
                    
                    trade_log_data = {
                        "symbol": symbol, "strategy": old_pos.strategy, "side": old_pos.side.value,
                        "quantity": float(d_quantity), "entry_price": float(d_entry_price), "exit_price": float(d_fill_price),
                        "pnl": float(pnl), "pnl_percent": float(pnl_percent),
                        "timestamp_entry": old_pos.entry_timestamp, "timestamp_exit": fill_timestamp
                    }
                    
                    try:
                        await database.log_trade_to_db(trade_log_data)
                    except Exception as db_err:
                        logger.error(f"[MonitorBot] Falha ao salvar trade fechado {symbol} na BD (SQLite): {db_err}", exc_info=True)
                        
                    await self._publish(EVENT_POSITION_CLOSED, trade_log_data)
                    
                except Exception as pnl_err:
                     logger.error(f"[MonitorBot] Erro ao calcular P/L ou publicar evento para {symbol}: {pnl_err}", exc_info=True)

        except Exception as outer_err:
             logger.critical(f"[MonitorBot] Erro INESPERADO no processamento do FILL {client_order_id}: {outer_err}", exc_info=True)


    async def _listen_market_data_stream(self):
        """Inicia o stream de !miniTicker@arr."""
        logger.info("[MonitorBot] A iniciar stream de dados de mercado (!miniTicker@arr)...")
        bsm = self.binance_client.get_socket_manager()
        try:
            async with bsm.start_multiplex_socket(['!miniTicker@arr'], self._handle_market_data_message) as socket:
                while True:
                    await socket.recv()
        except Exception as e:
            logger.critical(f"[MonitorBot] Stream de dados de mercado FALHOU: {e}. Sem monitorização de SL/TP!", exc_info=True)
            await asyncio.sleep(10)
            asyncio.create_task(self._listen_market_data_stream())
        logger.warning("[MonitorBot] Stream de dados de mercado encerrado.")

    async def _handle_market_data_message(self, msg: dict):
        """Callback para o socket de !miniTicker@arr."""
        try:
            ticks = msg.get('data', [])
            tasks = []
            for tick in ticks:
                symbol = tick.get('s')
                if symbol in self.watched_symbols:
                    price = float(tick.get('c'))
                    tasks.append(self._check_position_sl_tp(symbol, price))
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for i, res in enumerate(results):
                     if isinstance(res, Exception):
                          failed_symbol = tasks[i].__coro__.cr_frame.f_locals.get('symbol', 'UNKNOWN')
                          logger.error(f"[MonitorBot] Erro durante _check_position_sl_tp para {failed_symbol}: {res}", exc_info=False)
                          
        except Exception as e:
            logger.error(f"[MonitorBot] Erro ao processar tick de mercado: {e}", exc_info=True)

    async def _check_position_sl_tp(self, symbol: str, current_price: float):
        """Verifica SL/TP e publica PNL."""
        pos: Position | None = None
        try:
            # 1. Obter a posição
            try:
                pos_data = await self.state_manager.get_state(POSITIONS_COLLECTION, symbol)
                if not pos_data:
                    if symbol in self.watched_symbols: self.watched_symbols.remove(symbol)
                    return
                pos = Position.model_validate_json(pos_data)
            except Exception as get_pos_err:
                 logger.error(f"[MonitorBot] Falha ao ler estado da posição {symbol} para check SL/TP: {get_pos_err}. Ignorando tick.", exc_info=False)
                 return

            # 2. Calcular e Publicar PNL
            try:
                d_current_price = Decimal(str(current_price))
                d_entry_price = Decimal(str(pos.entry_price))
                d_quantity = Decimal(str(pos.quantity))
                current_pnl = (d_current_price - d_entry_price) * d_quantity if pos.side == OrderSide.BUY else (d_entry_price - d_current_price) * d_quantity
                
                asyncio.create_task(self._publish(EVENT_PNL_UPDATE, {
                    "symbol": symbol, "pnl": float(current_pnl), "price": current_price
                }))
            except Exception as pnl_pub_err:
                 logger.warning(f"[MonitorBot] Falha ao calcular/publicar PNL para {symbol}: {pnl_pub_err}", exc_info=False)

            # 3. Verificar SL/TP
            trigger_exit = False
            exit_reason = "Unknown"
            if pos.side == OrderSide.BUY:
                if current_price <= pos.sl_price: trigger_exit, exit_reason = True, "Stop Loss"
                elif pos.tp_price and current_price >= pos.tp_price: trigger_exit, exit_reason = True, "Take Profit"
            elif pos.side == OrderSide.SELL:
                if current_price >= pos.sl_price: trigger_exit, exit_reason = True, "Stop Loss"
                elif pos.tp_price and current_price <= pos.tp_price: trigger_exit, exit_reason = True, "Take Profit"
            
            # TODO: Lógica TSL

            # 4. Se SL/TP atingido, tentar fechar
            if trigger_exit:
                logger.info(f"[MonitorBot] GATILHO DE SAÍDA: {symbol} atingiu {exit_reason} @ {current_price}")
                
                if symbol in self.watched_symbols:
                    self.watched_symbols.remove(symbol)
                else:
                    logger.debug(f"[MonitorBot] Gatilho de saída para {symbol}, mas já não estava a ser observado.")
                    return 
                
                client_order_id = f"syn_EXIT_{pos.side.value}_{symbol}_{int(time.time() * 1000)}"
                order_request = OrderRequest(
                    symbol=symbol,
                    side=OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=pos.quantity,
                    client_order_id=client_order_id,
                    sl_price=None, tp_price=None,
                    strategy=f"Exit ({exit_reason})"
                )
                
                try:
                    await self._publish(EVENT_ORDER_REQUEST, order_request.model_dump())
                    logger.info(f"[MonitorBot] Pedido de ordem de SAÍDA para {symbol} publicado com sucesso.")
                except Exception as pub_err:
                     logger.critical(
                         f"[MonitorBot] FALHA CRÍTICA ao publicar ordem de SAÍDA para {symbol} ({exit_reason}): {pub_err}. "
                         f"A posição PODE FICAR ABERTA sem monitorização!",
                         exc_info=True
                     )

        except Exception as outer_err:
            logger.error(f"[MonitorBot] Erro INESPERADO durante verificação SL/TP para {symbol or 'UNKNOWN'}: {outer_err}", exc_info=True)


    async def run(self):
        """Inicia as tarefas principais do MonitorBot."""
        await self._load_initial_positions()
        task_user_data = asyncio.create_task(self._listen_user_data_stream())
        task_market_data = asyncio.create_task(self._listen_market_data_stream())
        logger.info("[MonitorBot] Tasks de escuta iniciadas.")
        await asyncio.gather(task_user_data, task_market_data)