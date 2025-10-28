# --- synapse_trader/bots/executor.py ---

import logging
import asyncio
from binance.exceptions import BinanceAPIException

from synapse_trader.bots.base_bot import BaseBot
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.utils.symbol_filters import SymbolFilters
from synapse_trader.core.types import (
    EVENT_ORDER_REQUEST, OrderRequest, OrderType
)

logger = logging.getLogger(__name__)

PENDING_ORDERS_COLLECTION = "pending_orders"

class ExecutorBot(BaseBot):
    """
    Ouve por Pedidos de Ordem (Order Requests) e envia-os
    para a exchange (Binance), com tratamento de erros robusto.
    """

    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager,
                 binance_client: BinanceClient,
                 symbol_filters: SymbolFilters): 
        
        super().__init__(event_bus, state_manager)
        self.binance_client = binance_client
        self.symbol_filters = symbol_filters

    async def _on_order_request(self, message: dict):
        """Callback para o evento EVENT_ORDER_REQUEST."""
        order_req: OrderRequest | None = None
        client_order_id: str | None = None
        
        try:
            order_req = OrderRequest(**message)
            client_order_id = order_req.client_order_id
            
            logger.info(f"[ExecutorBot] Pedido de Ordem recebido: {client_order_id} ({order_req.side.value} {order_req.symbol} Qtd:{order_req.quantity})")

            # 1. Armazenar o cache PRIMEIRO
            try:
                await self.state_manager.set_state(
                    collection=PENDING_ORDERS_COLLECTION,
                    key=client_order_id,
                    data=order_req.model_dump_json() 
                )
                logger.debug(f"[ExecutorBot] Metadados da ordem {client_order_id} salvos no cache.")
            except Exception as cache_err:
                logger.critical(
                    f"[ExecutorBot] FALHA CRÍTICA ao salvar cache para ordem {client_order_id}: {cache_err}. "
                    f"A ordem NÃO será enviada.",
                    exc_info=True
                )
                return 

            # 2. Construir e enviar a ordem para a Binance
            order_params = {
                "symbol": order_req.symbol,
                "side": order_req.side.value,
                "type": order_req.order_type.value,
                "quantity": order_req.quantity,
                "newClientOrderId": client_order_id,
            }

            if order_req.order_type == OrderType.LIMIT: 
                if order_req.price is None:
                    logger.error(f"[ExecutorBot] Ordem LIMIT {client_order_id} sem preço! A cancelar envio.")
                    await self.state_manager.delete_state(PENDING_ORDERS_COLLECTION, client_order_id)
                    return 
                order_params["price"] = order_req.price
                order_params["timeInForce"] = "GTC" 
            
            logger.debug(f"[ExecutorBot] A enviar ordem para Binance: {order_params}")
            
            order_response = await self.binance_client.create_order(**order_params)
            
            logger.info(f"[ExecutorBot] Ordem {client_order_id} enviada com sucesso para Binance. Status inicial: {order_response.get('status')}")

        except BinanceAPIException as api_err:
            logger.error(
                f"[ExecutorBot] Erro da API Binance ao enviar ordem {client_order_id or 'UNKNOWN'}: "
                f"Status={api_err.status_code}, Code={api_err.code}, Msg='{api_err.message}'",
                exc_info=False 
            )
            if client_order_id:
                await self.state_manager.delete_state(PENDING_ORDERS_COLLECTION, client_order_id)
        
        except Exception as e:
            logger.critical(
                f"[ExecutorBot] Erro INESPERADO ao processar/enviar ordem {client_order_id or 'UNKNOWN'}: {e}",
                exc_info=True 
            )
            if client_order_id:
                await self.state_manager.delete_state(PENDING_ORDERS_COLLECTION, client_order_id)


    async def run(self):
        """Inicia o bot e subscreve aos eventos."""
        logger.info("[ExecutorBot] A subscrever ao tópico ORDER_REQUEST.")
        await self._subscribe(EVENT_ORDER_REQUEST, self._on_order_request)
        
        while True:
            await asyncio.sleep(3600)