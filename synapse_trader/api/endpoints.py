# --- synapse_trader/api/endpoints.py ---

import logging
from fastapi import APIRouter
from sqlalchemy.future import select
from sqlalchemy import desc

from synapse_trader.core.state_manager import get_state_manager
from synapse_trader.utils.database import get_session, TradeLog
from synapse_trader.bots.analyst import MARKET_STATE_COLLECTION, TREND_STATE_KEY
from synapse_trader.bots.monitor import POSITIONS_COLLECTION

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

@router.get("/status")
async def get_status():
    """Retorna o estado operacional atual do bot."""
    state_manager = get_state_manager()
    
    try:
        # Busca a tendência atual definida pelo AnalystBot
        trend_data = await state_manager.get_state(
            MARKET_STATE_COLLECTION, 
            TREND_STATE_KEY
        )
        return {
            "service": "synapse-trader-api",
            "status": "online",
            "market_trend": trend_data.get("trend", "ANALYSING...") if trend_data else "UNKNOWN"
        }
    except Exception as e:
        logger.error(f"Erro ao obter estado da API: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

@router.get("/positions")
async def get_open_positions():
    """Retorna todas as posições atualmente abertas."""
    state_manager = get_state_manager()
    try:
        # Obtém a coleção inteira
        positions_dict = await state_manager.get_collection(POSITIONS_COLLECTION)
        # Converte o dicionário de posições em lista
        positions_list = list(positions_dict.values())
        return {"positions": positions_list}
    except Exception as e:
        logger.error(f"Erro ao obter posições: {e}", exc_info=True)
        return {"positions": [], "error": str(e)}

@router.get("/trade_history")
async def get_trade_history():
    """Retorna os últimos 50 trades fechados da BD (SQLite)."""
    try:
        async with get_session() as session:
            # Query para buscar os últimos 50 trades, ordenados por data de saída
            stmt = select(TradeLog).order_by(desc(TradeLog.timestamp_exit)).limit(50)
            result = await session.execute(stmt)
            trades = result.scalars().all()
            
            return {"history": trades}
    except Exception as e:
        logger.error(f"Erro ao obter histórico de trades: {e}", exc_info=True)
        return {"history": [], "error": str(e)}