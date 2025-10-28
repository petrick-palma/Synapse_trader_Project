# --- synapse_trader/bots/analyst.py ---

import logging
import asyncio
import pandas as pd
from finta import TA
from typing import Dict, Any, List
from datetime import datetime

from synapse_trader.bots.base_bot import BaseBot
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.connectors.gemini_client import GeminiClient
from synapse_trader.utils.config import settings 

# --- CORREÇÃO: Importar constantes de types.py ---
from synapse_trader.core.types import (
    EVENT_HOT_LIST_UPDATED, 
    MARKET_STATE_COLLECTION, 
    TREND_STATE_KEY, 
    BTC_TREND_KEY
)
# --------------------------------------------------
# Importar KLINE_COLUMNS e DATA_FRAME_COLUMNS
from synapse_trader.bots.strategist import KLINE_COLUMNS, DATA_FRAME_COLUMNS


logger = logging.getLogger(__name__)

TREND_SYMBOL = "BTCUSDT"
TREND_TIMEFRAME = "4h"
TREND_WARMUP_PERIOD = 50 
ANALYSIS_INTERVAL_SECONDS = 60 * 60 * 4 
FALLBACK_HOT_LIST = ["BTCUSDT", "ETHUSDT"]

class AnalystBot(BaseBot):
    """
    Analisa o mercado (tendência lida do Prophet/worker, hot list via Gemini)
    e publica os resultados para os outros bots.
    """

    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager,
                 binance_client: BinanceClient,
                 gemini_client: GeminiClient):
        
        super().__init__(event_bus, state_manager)
        self.binance_client = binance_client
        self.gemini_client = gemini_client

    async def _fetch_btc_data(self) -> pd.DataFrame:
        """Busca dados do BTCUSDT (4h) para análise de tendência (fallback)."""
        try:
            klines_list = await self.binance_client.get_klines(
                symbol=TREND_SYMBOL, 
                interval=TREND_TIMEFRAME, 
                limit=TREND_WARMUP_PERIOD
            )
            df = pd.DataFrame(klines_list, columns=KLINE_COLUMNS)
            df = df[DATA_FRAME_COLUMNS].copy()
            df = df.astype({'open': float, 'high': float, 'low': float, 'close': float, 'volume': float})
            return df
        except Exception as e:
            logger.error(f"[AnalystBot] Erro ao buscar dados do {TREND_SYMBOL}: {e}", exc_info=True)
            return pd.DataFrame()

    async def _check_market_trend(self):
        """
        Lê a tendência do Prophet (calculada pelo OptimizerBot)
        do StateManager e define-a como a tendência de mercado principal.
        """
        logger.info("[AnalystBot] A verificar tendência do Prophet (lida do StateManager)...")
        trend = "SIDEWAYS" # Default
        try:
            btc_trend_data = await self.state_manager.get_state(
                MARKET_STATE_COLLECTION, 
                BTC_TREND_KEY
            )
            
            if btc_trend_data and "trend" in btc_trend_data:
                trend = btc_trend_data["trend"]
                logger.info(f"[AnalystBot] Tendência de mercado (Prophet/BTC) definida: {trend}")
            else:
                logger.warning("[AnalystBot] Previsão do Prophet (BTC) não encontrada. A usar 'SIDEWAYS'.")
            
        except Exception as e:
            logger.error(f"[AnalystBot] Erro ao ler a tendência do Prophet: {e}", exc_info=True)
            logger.warning("[AnalystBot] A usar 'SIDEWAYS' como fallback de erro.")
            
        finally:
            await self.state_manager.set_state(
                MARKET_STATE_COLLECTION, 
                TREND_STATE_KEY, 
                {"trend": trend, "timestamp": datetime.utcnow().isoformat()}
            )


    async def _generate_hot_list(self) -> List[str]:
        """Gera a 'hot list' de símbolos para operar (via Gemini)."""
        logger.info("[AnalystBot] A gerar 'hot list' via Gemini...")
        
        prompt = (
            "Como um analista especialista em criptomoedas, execute as seguintes tarefas:\n"
            "1. Pesquise na web (notícias, blogs, Twitter) por quaisquer anúncios *oficiais* "
            "da exchange Binance sobre novas listagens de pares SPOT (não futuros ou margem) "
            "agendadas para os próximos 3 dias.\n"
            "2. Analise o sentimento de mercado e o 'hype' para encontrar 3 criptomoedas "
            "com 'potencial explosivo' a curto prazo (ex: narrativas de IA, RWA, DePIN) "
            "que já estejam listadas na Binance Spot.\n"
            "3. Inclua sempre 'BTC' e 'ETH' na sua análise.\n"
            "Combine todos os símbolos encontrados (BTC, ETH, Listagens Futuras, Potencial Explosivo) "
            "numa única lista. NÃO adicione 'USDT' ou 'FDUSD'.\n"
            "Formate a sua resposta *apenas* como uma lista de símbolos "
            "separados por vírgula, sem mais texto.\n"
            "Exemplo de resposta: BTC,ETH,ONDO,WIF,FET"
        )
        
        hot_list_symbols = []
        try:
            response = await self.gemini_client.prompt_async(prompt)
            if response:
                symbols = [s.strip().upper() for s in response.split(',')]
                hot_list_symbols = sorted(list(set(filter(None, symbols))))
                logger.info(f"[AnalystBot] Gemini retornou {len(hot_list_symbols)} símbolos: {hot_list_symbols}")
            else:
                logger.warning("[AnalystBot] Resposta do Gemini foi vazia.")

        except Exception as e:
            logger.error(f"[AnalystBot] Erro ao consultar o Gemini: {e}", exc_info=True)
            
        if not hot_list_symbols:
            logger.warning("[AnalystBot] A usar 'hot list' de fallback.")
            hot_list_symbols = [s.replace(settings.QUOTE_ASSET, "") for s in FALLBACK_HOT_LIST]

        hot_list_final = [f"{symbol}{settings.QUOTE_ASSET}" for symbol in hot_list_symbols]
        
        if TREND_SYMBOL not in hot_list_final:
            hot_list_final.append(TREND_SYMBOL)
            
        hot_list_final = sorted(list(set(hot_list_final)))
        return hot_list_final


    async def run(self):
        """Loop principal do AnalystBot."""
        logger.info("[AnalystBot] A iniciar ciclo de análise...")
        
        while True:
            try:
                await self._check_market_trend()
                hot_list = await self._generate_hot_list()
                
                logger.info(f"[AnalystBot] 'Hot list' final publicada: {hot_list}")
                await self._publish(EVENT_HOT_LIST_UPDATED, {"symbols": hot_list})
                
                logger.info(f"[AnalystBot] Ciclo de análise concluído. A aguardar {ANALYSIS_INTERVAL_SECONDS}s...")
                await asyncio.sleep(ANALYSIS_INTERVAL_SECONDS)
                
            except Exception as e:
                logger.error(f"[AnalystBot] Erro no ciclo de análise: {e}. A tentar novamente em 60s.", exc_info=True)
                await asyncio.sleep(60)