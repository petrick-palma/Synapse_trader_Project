# --- synapse_trader/api/main.py ---

import logging
import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from contextlib import asynccontextmanager

from synapse_trader.utils.config import settings
from synapse_trader.utils.logging_config import setup_logging
from synapse_trader.core.event_bus import get_event_bus
from synapse_trader.core.state_manager import get_state_manager
from synapse_trader.utils import database
from synapse_trader.api.endpoints import router as api_router
from synapse_trader.core.types import EVENT_PNL_UPDATE

setup_logging(settings.LOG_LEVEL)
logger = logging.getLogger("synapse_trader.api.main")


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Dashboard WebSocket conectado ({len(self.active_connections)} conexões)")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Dashboard WebSocket desconectado ({len(self.active_connections)} conexões)")

    async def broadcast(self, message: dict): 
        """Envia uma mensagem (JSON) para todos os dashboards conectados."""
        message_str = json.dumps(message) 
        disconnected_sockets = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message_str)
            except WebSocketDisconnect:
                disconnected_sockets.append(connection)
            except Exception as e:
                logger.warning(f"Erro ao transmitir para WebSocket: {e}")
        
        for socket in disconnected_sockets:
            self.disconnect(socket)


manager = ConnectionManager()

async def ws_event_listener():
    """Ouve o Event Bus (PNL_UPDATE) e transmite para o WebSocket."""
    logger.info("[API-WS] A iniciar ouvinte do Event Bus para WebSocket...")
    event_bus = get_event_bus()
    
    async def pnl_callback(message: dict):
        logger.debug(f"[API-WS] A transmitir PNL Update via WebSocket: {message}")
        await manager.broadcast(message)

    await event_bus.subscribe(EVENT_PNL_UPDATE, pnl_callback)
    logger.info("[API-WS] Subscrito ao EVENT_PNL_UPDATE.")
    
    while True:
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Função de 'lifespan' do FastAPI."""
    logger.info("Serviço API (FastAPI) a iniciar...")
    try:
        get_event_bus()
        get_state_manager()
        await database.init_db()
        logger.info("Event Bus, State Manager e DB (SQLite) inicializados.")
        
        asyncio.create_task(ws_event_listener())
        
    except Exception as e:
        logger.critical(f"Falha ao inicializar serviços core para a API: {e}", exc_info=True)
        raise
    
    yield
    logger.info("Serviço API (FastAPI) a desligar.")

# --- Criação da Aplicação FastAPI ---
app = FastAPI(
    title="Synapse Trader API",
    description="Dashboard e API para o Synapse Trader",
    version="0.1.0",
    lifespan=lifespan
)

app.mount("/static", StaticFiles(directory="synapse_trader/dashboard/static"), name="static")
templates = Jinja2Templates(directory="synapse_trader/dashboard/templates")

app.include_router(api_router)

@app.get("/", include_in_schema=False)
async def get_dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() 
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Erro no WebSocket /ws/dashboard: {e}")
        manager.disconnect(websocket)