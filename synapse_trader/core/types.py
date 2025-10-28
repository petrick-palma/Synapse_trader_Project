# --- synapse_trader/core/types.py ---

from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

# --- Constantes de Tópicos do Event Bus ---
EVENT_KLINE_CLOSED = "kline_closed"
EVENT_HOT_LIST_UPDATED = "hot_list_updated"
EVENT_TRADE_SIGNAL = "trade_signal"
EVENT_ORDER_REQUEST = "order_request"
EVENT_ORDER_TIMEOUT = "order_timeout"
EVENT_POSITION_OPENED = "position_opened"
EVENT_POSITION_CLOSED = "position_closed"
EVENT_PNL_UPDATE = "pnl_update"
EVENT_NOTIFICATION = "notification"
EVENT_TRAINER_DONE = "trainer_done"
EVENT_OPTIMIZER_DONE = "EVENT_OPTIMIZER_DONE"

# --- Constantes do StateManager (NOVAS) ---
POSITIONS_COLLECTION = "positions"
PENDING_ORDERS_COLLECTION = "pending_orders"
MARKET_STATE_COLLECTION = "market_state"

# Chaves de Tendência (usadas pelo Analyst e Optimizer)
TREND_STATE_KEY = "current_trend" 
BTC_TREND_KEY = "PROPHET_BTC_TREND"
ETH_TREND_KEY = "PROPHET_ETH_TREND"

# --- Enums (Tipos Constantes) ---

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

# --- Estruturas de Dados (Pydantic Models) ---

class KlineClosed(BaseModel):
    """Evento publicado pelo DataFeed quando uma vela fecha."""
    symbol: str
    timeframe: str
    kline: dict 

class TickData(BaseModel):
    """Evento de atualização de preço em tempo real (do MonitorBot)."""
    symbol: str
    price: float

class TradeSignal(BaseModel):
    """Evento publicado pelo StrategistBot."""
    symbol: str
    side: OrderSide
    strategy: str

class OrderRequest(BaseModel):
    """Evento publicado pelo RiskManagerBot (ou MonitorBot) para o ExecutorBot."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    client_order_id: str 
    
    price: float | None = None 
    sl_price: float | None = None 
    tp_price: float | None = None 
    timeout_seconds: int | None = None
    strategy: str | None = None 

class Position(BaseModel):
    """Representa uma posição aberta, guardada no StateManager."""
    symbol: str
    strategy: str
    side: OrderSide
    quantity: float
    entry_price: float
    entry_timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    sl_price: float 
    tp_price: float | None 
    
    tsl_active_at_price: float | None = None 
    tsl_trail_percent: float | None = None 
    tsl_current_stop: float | None = None 
    tsl_highest_price: float = 0.0