# --- synapse_trader/connectors/binance_client.py ---
# REESCRITO para usar binance-sdk-spot (V3.0.0)

import logging
import backoff
import asyncio
from typing import Any, Dict, List, Callable, Optional
import pandas as pd 
import json 

# --- CORREÇÃO: Importação Final da Binance SDK ---
from binance.spot import Spot as SpotClient 
from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient 
from binance.error import ClientError 
# ----------------------------------------------------

from synapse_trader.utils.config import settings

logger = logging.getLogger(__name__)

# --- Configuração de Backoff ---
def _backoff_handler(details):
    exception = details.get('exception')
    error_code = getattr(exception, 'error_code', None)
    status_code = getattr(exception, 'status_code', None)
    logger.warning(
        f"Binance API: Retentativa {details['tries']} após falha ({details['target'].__name__}). "
        f"Próxima tentativa em {details['wait']:.1f}s. "
        f"Erro: (Status:{status_code}, Code:{error_code}) {exception}"
    )

backoff_binance_api = backoff.on_exception(
    backoff.expo, ClientError, max_tries=5, max_time=300, 
    on_backoff=_backoff_handler,
    giveup=lambda e: not (e.status_code >= 500 or e.status_code in [429, 418])
)

# --- Cliente Binance (Nova Versão) ---

class BinanceClient:
    """
    Cliente (wrapper) para interagir com a API REST Spot e 
    WebSockets da Binance usando binance-sdk-spot.
    """

    def __init__(self):
        self.api_key: str = settings.BINANCE_API_KEY
        self.api_secret: str = settings.BINANCE_API_SECRET
        self.testnet: bool = settings.BINANCE_TESTNET
        
        self.base_url = "https://testnet.binance.vision" if self.testnet else "https://api.binance.com"
        self.ws_base_url = "wss://testnet.binance.ws/ws" if self.testnet else "wss://stream.binance.com:9443/ws"
        
        self.client: SpotClient | None = None
        self.ws_client: SpotWebsocketStreamClient | None = None # <-- CORREÇÃO: Nome da Classe
        
        self._ws_global_callback_map: Dict[str, Callable] = {} # Mapeia stream_name -> callback
        self._ws_stream_ids: Dict[str, str] = {} # Mapeia o nosso ID interno -> stream_name

    async def connect(self):
        """Inicializa os clientes REST e WebSocket."""
        if self.client:
            logger.warning("Cliente Binance já inicializado.")
            return
        
        try:
            logger.info("A inicializar clientes Binance (REST Spot e WebSocket Stream)...")
            self.client = SpotClient(
                key=self.api_key, 
                secret=self.api_secret, 
                base_url=self.base_url
            )
            # Usa a classe SpotWebsocketStreamClient importada com o callback GERAL
            self.ws_client = SpotWebsocketStreamClient(
                stream_url=self.ws_base_url, 
                on_message=self._handle_ws_message
            )
            logger.info("Clientes Binance (REST e WebSocket Stream) inicializados.")
            
            await self.health_check()
            logger.info("Binance REST API Health Check OK.")
            
        except Exception as e:
            logger.critical(f"Falha fatal ao inicializar clientes Binance: {e}", exc_info=True)
            raise
            
    def _handle_ws_message(self, _, message):
        """Callback GERAL que recebe TODAS as mensagens WS e as direciona."""
        try:
            msg_dict = json.loads(message)
            stream_name = msg_dict.get('stream')
            data = msg_dict.get('data')
            
            if not stream_name or data is None:
                logger.debug(f"[WS Global] Mensagem WS não-stream recebida: {message[:150]}")
                return

            target_callback = self._ws_global_callback_map.get(stream_name)
                 
            if target_callback:
                asyncio.run_coroutine_threadsafe(
                    target_callback(data), 
                    asyncio.get_event_loop()
                )
            else: 
                 logger.debug(f"Mensagem WS recebida para stream não mapeado: {stream_name}")
                    
        except json.JSONDecodeError:
            logger.warning(f"[WS Global] Mensagem WS não-JSON recebida: {message[:150]}")
        except Exception as e:
            logger.error(f"Erro ao processar mensagem WS GERAL: {e} | Mensagem: {message[:150]}", exc_info=True)


    async def close(self):
        """Para todos os streams WebSocket ativos."""
        logger.info("A parar todos os streams WebSocket da Binance...")
        if self.ws_client:
            try:
                 await asyncio.to_thread(self.ws_client.stop)
                 logger.info("Cliente WebSocket Stream parado.")
            except Exception as e:
                 logger.error(f"Erro ao parar o cliente WebSocket Stream: {e}")
                 
        self._ws_global_callback_map.clear()
        self._ws_stream_ids.clear()
        self.client = None
        self.ws_client = None
        logger.info("Conexões Binance fechadas.")

    # --- Métodos WebSocket (Adaptados para SpotWebsocketStreamClient) ---

    def _subscribe_stream(self, stream_name: str, internal_id: str, callback: Callable):
        """Inicia um stream (se não estiver ativo) e regista o callback."""
        if not self.ws_client:
            raise RuntimeError("Cliente WS não inicializado.")
            
        stream_name = stream_name.lower()
        
        if stream_name in self._ws_global_callback_map:
             logger.warning(f"Stream {stream_name} (ID: {internal_id}) já está subscrito. Apenas a atualizar o callback.")
        else:
             logger.info(f"A subscrever ao stream: {stream_name} (ID: {internal_id})")
             asyncio.get_event_loop().run_in_executor(
                 None, 
                 self.ws_client.subscribe, 
                 [stream_name] 
             )
        
        self._ws_global_callback_map[stream_name] = callback
        self._ws_stream_ids[internal_id] = stream_name
        logger.debug(f"Callback para {stream_name} (ID: {internal_id}) registado.")

    def _unsubscribe_stream(self, internal_id: str):
        """Para um stream pelo nosso ID interno."""
        if not self.ws_client: return
        
        stream_name = self._ws_stream_ids.pop(internal_id, None)
        if stream_name:
            logger.info(f"A cancelar subscrição do stream: {stream_name} (ID: {internal_id})")
            self._ws_global_callback_map.pop(stream_name, None)
            
            if stream_name not in self._ws_global_callback_map: 
                asyncio.get_event_loop().run_in_executor(
                     None, 
                     self.ws_client.unsubscribe, 
                     [stream_name]
                )
        else:
             logger.warning(f"Tentativa de parar stream ID '{internal_id}' inexistente.")

    # --- Interface Pública para os Bots ---

    def start_kline_stream(self, symbol: str, interval: str, callback: Callable):
        stream_id = f"kline_{symbol.lower()}_{interval}"
        stream_name = f"{symbol.lower()}@kline_{interval}"
        self._subscribe_stream(stream_name, stream_id, callback)
        return stream_id

    def start_user_data_stream(self, listen_key: str, callback: Callable):
        stream_id = f"user_data_{listen_key[:5]}"
        stream_name = listen_key 
        self._subscribe_stream(stream_name, stream_id, callback)
        return stream_id

    def start_book_ticker_stream(self, symbol: str | None, callback: Callable):
        if symbol:
            stream_id = f"book_ticker_{symbol.lower()}"
            stream_name = f"{symbol.lower()}@bookTicker"
        else:
            stream_id = "book_ticker_all"
            stream_name = "!bookTicker" # Stream de todos os símbolos
        self._subscribe_stream(stream_name, stream_id, callback)
        return stream_id
        
    def start_multiplex_stream(self, streams: List[str], callback: Callable):
        """Inicia um stream multiplex."""
        stream_id = f"multiplex_{hash(tuple(sorted(streams)))}" 
        logger.info(f"A subscrever a {len(streams)} streams multiplex (ID: {stream_id})...")
        
        streams_lower = [s.lower() for s in streams]
        
        for stream_name in streams_lower:
            internal_stream_id = f"{stream_id}_{stream_name}"
            self._subscribe_stream(stream_name, internal_stream_id, callback) 
            
        return stream_id

    async def stop_stream(self, stream_id: str):
        """Para um stream (ou grupo multiplex) pelo seu ID interno."""
        if "multiplex_" in stream_id:
             ids_to_remove = [internal_id for internal_id in self._ws_stream_ids if internal_id.startswith(stream_id)]
             logger.info(f"A parar {len(ids_to_remove)} streams multiplex (Grupo: {stream_id})...")
             for internal_id in ids_to_remove:
                  self._unsubscribe_stream(internal_id)
        else:
            self._unsubscribe_stream(stream_id)
        
    # --- Métodos REST (Usando asyncio.to_thread) ---
    @backoff_binance_api
    async def health_check(self) -> Dict[str, Any]:
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        return await asyncio.to_thread(self.client.ping)

    @backoff_binance_api
    async def get_exchange_info(self) -> Dict[str, Any]:
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        logger.info("A obter Exchange Info...")
        return await asyncio.to_thread(self.client.exchange_info)

    @backoff_binance_api
    async def get_account_info(self) -> Dict[str, Any]:
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        logger.debug("A obter informações da conta Binance...")
        return await asyncio.to_thread(self.client.account)

    @backoff_binance_api
    async def get_klines(self, symbol: str, interval: str, limit: int, 
                         start_str: Optional[str] = None, 
                         end_str: Optional[str] = None) -> List[List[Any]]:
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        logger.debug(f"A obter {limit} klines para {symbol} ({interval})...")
        params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
        if start_str: 
            try:
                start_ts = int(pd.Timestamp(start_str).timestamp() * 1000)
                params["startTime"] = start_ts
            except ValueError: logger.error(f"Formato de start_str inválido: {start_str}")
        if end_str:
             try:
                 end_ts = int(pd.Timestamp(end_str).timestamp() * 1000)
                 params["endTime"] = end_ts
             except ValueError: logger.error(f"Formato de end_str inválido: {end_str}")

        if limit > 1000:
             logger.warning(f"get_klines com limit > 1000. Buscando apenas 1000. (Paginação manual necessária para mais)")
             
        return await asyncio.to_thread(self.client.klines, **params)

    @backoff_binance_api
    async def create_order(self, **kwargs: Any) -> Dict[str, Any]:
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        logger.info(f"A criar ordem SPOT: {kwargs.get('symbol')} {kwargs.get('side')} {kwargs.get('type')} Qtd:{kwargs.get('quantity')}")
        if 'newClientOrderId' in kwargs:
             kwargs['newOrderRespType'] = 'RESULT' 
        return await asyncio.to_thread(self.client.new_order, **kwargs)

    @backoff_binance_api
    async def cancel_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str]=None) -> Dict[str, Any]:
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        if not orderId and not origClientOrderId: raise ValueError("orderId ou origClientOrderId necessário.")
        params = {"symbol": symbol}
        if orderId: params["orderId"] = orderId
        if origClientOrderId: params["origClientOrderId"] = origClientOrderId
        logger.info(f"A cancelar ordem: {symbol} (Params: {params})")
        return await asyncio.to_thread(self.client.cancel_order, **params)

    @backoff_binance_api
    async def get_order(self, symbol: str, orderId: Optional[str] = None, origClientOrderId: Optional[str]=None) -> Dict[str, Any]:
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        if not orderId and not origClientOrderId: raise ValueError("orderId ou origClientOrderId necessário.")
        params = {"symbol": symbol}
        if orderId: params["orderId"] = orderId
        if origClientOrderId: params["origClientOrderId"] = origClientOrderId
        logger.debug(f"A verificar ordem: {symbol} (Params: {params})")
        return await asyncio.to_thread(self.client.get_order, **params)

    @backoff_binance_api
    async def get_open_orders(self, symbol: str | None = None) -> List[Dict[str, Any]]:
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        logger.debug(f"A obter ordens abertas (Símbolo: {symbol or 'Todos'})...")
        params = {"symbol": symbol} if symbol else {}
        return await asyncio.to_thread(self.client.get_open_orders, **params)

    @backoff_binance_api
    async def get_listen_key(self) -> str:
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        logger.info("A obter Listen Key para User Data Stream...")
        response = await asyncio.to_thread(self.client.new_listen_key)
        return response['listenKey']

    @backoff_binance_api
    async def keep_alive_listen_key(self, listen_key: str):
        if not self.client: raise RuntimeError("Cliente REST não inicializado.")
        logger.debug(f"A fazer keep-alive no Listen Key {listen_key[:5]}...")
        await asyncio.to_thread(self.client.renew_listen_key, listenKey=listen_key)