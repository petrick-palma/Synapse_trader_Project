# --- synapse_trader/bots/strategist.py ---

import logging
import asyncio
import pandas as pd
from typing import Dict, Tuple, Set, Any

from synapse_trader.bots.base_bot import BaseBot
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager
from synapse_trader.connectors.binance_client import BinanceClient
from synapse_trader.utils.symbol_filters import SymbolFilters
from synapse_trader.core.types import (
    EVENT_KLINE_CLOSED, EVENT_TRADE_SIGNAL, EVENT_HOT_LIST_UPDATED, 
    EVENT_TRAINER_DONE, EVENT_OPTIMIZER_DONE, EVENT_ORDER_REQUEST,
    KlineClosed, TradeSignal, OrderSide,
    MARKET_STATE_COLLECTION, TREND_STATE_KEY 
)
# --- CORREÇÃO: Importar BaseStrategy aqui ---
from synapse_trader.strategies.base_strategy import BaseStrategy, SignalType
# -----------------------------------------
from synapse_trader.strategies.ema_crossover import EmaCrossoverStrategy
from synapse_trader.strategies.stochastic_rsi_scalp import StochasticRsiScalpStrategy
from synapse_trader.strategies.macd_crossover import MacdCrossoverStrategy 
from synapse_trader.strategies.rsi_momentum import RsiMomentumStrategy 
from synapse_trader.utils.config import settings

from synapse_trader.ml.preprocessing import DataPreprocessor, FEATURES_TO_NORMALIZE
from synapse_trader.ml.agent import DDQNAgent
from synapse_trader.ml.trading_env import TradingEnv
from synapse_trader.bots.optimizer import SCALER_PATH, AGENT_PATH, WINDOW_SIZE

logger = logging.getLogger(__name__)

KLINE_COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume", 
    "close_time", "quote_asset_volume", "number_of_trades", 
    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
]
DATA_FRAME_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

class StrategistBot(BaseBot):
    
    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager,
                 binance_client: BinanceClient,
                 symbol_filters: SymbolFilters):
        
        super().__init__(event_bus, state_manager)
        self.binance_client = binance_client
        self.symbol_filters = symbol_filters
        
        self.data_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
        self.watched_symbols: Set[str] = set()
        
        # --- Instanciação das Estratégias ---
        self.ema_strategy = EmaCrossoverStrategy(fast_period=9, slow_period=21)
        self.stochrsi_strategy = StochasticRsiScalpStrategy(k_period=14, overbought=80, oversold=20)
        self.macd_strategy = MacdCrossoverStrategy(fast_period=12, slow_period=26, signal_period=9) 
        self.rsi_strategy = RsiMomentumStrategy(period=14, oversold=30, overbought=70) 
        
        self.strategies: list[BaseStrategy] = [
            self.ema_strategy,
            self.stochrsi_strategy,
            self.macd_strategy,
            self.rsi_strategy
        ]
        
        self.timeframes: list[str] = [
            tf.strip() for tf in settings.STRATEGY_TIMEFRAMES.split(',') if tf.strip()
        ]
        
        # --- Estado da IA ---
        self.preprocessor = DataPreprocessor(features=FEATURES_TO_NORMALIZE)
        n_features = len(FEATURES_TO_NORMALIZE)
        
        df_cols = [col for col in FEATURES_TO_NORMALIZE if col in DATA_FRAME_COLUMNS]
        if not df_cols: df_cols = ['open', 'high', 'low', 'close', 'volume']
            
        n_actions = TradingEnv(data=pd.DataFrame(columns=df_cols), window_size=WINDOW_SIZE).action_space
        
        self.agent = DDQNAgent(
            state_shape=(WINDOW_SIZE, n_features),
            n_actions=n_actions,
            epsilon=0.0
        )
        self.ia_ready = False
        
        logger.info(f"[StrategistBot] {len(self.strategies)} estratégias (feature generators) carregadas.")

    async def _fetch_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        try:
            klines_list = await self.binance_client.get_klines(symbol=symbol, interval=timeframe, limit=limit)
            if not klines_list:
                logger.warning(f"Nenhum dado kline retornado para {symbol} {timeframe}.")
                return pd.DataFrame(columns=DATA_FRAME_COLUMNS[1:])
                
            df = pd.DataFrame(klines_list, columns=KLINE_COLUMNS)
            df = df[DATA_FRAME_COLUMNS].copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            df = df.astype(float)
            return df
        except Exception as e:
            logger.error(f"[StrategistBot] Erro ao buscar dados históricos para {symbol} {timeframe}: {e}", exc_info=True)
            return pd.DataFrame(columns=DATA_FRAME_COLUMNS[1:])

    async def _warmup_cache(self, symbols_to_warmup: Set[str]):
        if not symbols_to_warmup: return
        logger.info(f"[StrategistBot] A aquecer o cache para {len(symbols_to_warmup)} símbolos...")
        tasks = []
        for symbol in symbols_to_warmup:
            for tf in self.timeframes:
                tasks.append(self._fetch_historical_data(symbol, tf, limit=200))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        i = 0
        for symbol in symbols_to_warmup:
            for tf in self.timeframes:
                result = results[i]
                if isinstance(result, Exception) or result is None or result.empty:
                     logger.error(f"[StrategistBot] Falha ao aquecer cache para {symbol} {tf}: {result}")
                     self.data_cache[(symbol, tf)] = pd.DataFrame(columns=DATA_FRAME_COLUMNS[1:])
                else:
                    self.data_cache[(symbol, tf)] = result
                    logger.info(f"[StrategistBot] Cache para {symbol} {tf} aquecido com {len(result)} velas.")
                i += 1

    async def _on_hot_list_updated(self, message: dict):
        new_symbols = set(message.get("symbols", []))
        symbols_to_warmup = new_symbols - self.watched_symbols
        symbols_to_remove = self.watched_symbols - new_symbols
        for symbol in symbols_to_remove:
            for tf in self.timeframes:
                self.data_cache.pop((symbol, tf), None)
        self.watched_symbols = new_symbols
        logger.info(f"[StrategistBot] 'Hot list' atualizada para {len(self.watched_symbols)} símbolos.")
        if symbols_to_warmup:
            await self._warmup_cache(symbols_to_warmup)

    async def _load_ia_model(self, message: dict = None):
        if message:
            logger.info("[StrategistBot] EVENT_TRAINER_DONE recebido. A recarregar (hot-swap) modelos de IA...")
        else:
            logger.info("[StrategistBot] A carregar modelos de IA no arranque...")
        try:
            self.preprocessor.load(SCALER_PATH)
            self.agent.load(AGENT_PATH)
            self.ia_ready = True
            logger.info("[StrategistBot] Modelos de IA (Scaler e Agente) carregados com sucesso.")
        except FileNotFoundError:
            self.ia_ready = False
            logger.warning("[StrategistBot] Modelos de IA não encontrados. IA inativa.")
        except Exception as e:
            self.ia_ready = False
            logger.error(f"[StrategistBot] Falha fatal ao carregar modelos de IA: {e}", exc_info=True)

    def _get_strategy_by_name(self, name: str) -> BaseStrategy | None:
        """Helper para encontrar uma estratégia pelo nome da classe."""
        for strategy in self.strategies:
            if strategy.__class__.__name__ == name:
                return strategy
        return None

    async def _on_optimizer_done(self, message: dict):
        """Processa o evento do OptimizerBot e atualiza os parâmetros."""
        strategy_name = message.get("strategy_name")
        new_params = message.get("best_params")
        
        if not strategy_name or not new_params:
            logger.error("[StrategistBot] EVENT_OPTIMIZER_DONE inválido (missing name/params).")
            return

        target_strategy = self._get_strategy_by_name(strategy_name)
        
        if target_strategy:
            target_strategy.set_parameters(new_params)
            logger.info(f"[StrategistBot] Parâmetros de '{strategy_name}' atualizados via hot-swap.")
        else:
            logger.warning(f"[StrategistBot] Estratégia '{strategy_name}' não encontrada para hot-swap.")


    async def _on_kline(self, message: dict):
        try:
            kline_event = KlineClosed(**message)
            symbol = kline_event.symbol
            if symbol not in self.watched_symbols: return
            timeframe = kline_event.timeframe
            kline_data = kline_event.kline
            
            df = self.data_cache.get((symbol, timeframe))
            if df is None or df.empty:
                logger.debug(f"[StrategistBot] Cache vazio para {symbol} {timeframe}. A tentar buscar...")
                df = await self._fetch_historical_data(symbol, timeframe, limit=200)
                if df.empty: 
                    logger.warning(f"Não foi possível obter dados históricos para {symbol} {timeframe} no _on_kline.")
                    return
            
            new_kline_series = pd.Series(
                data=[float(kline_data['o']), float(kline_data['h']), float(kline_data['l']), float(kline_data['c']), float(kline_data['v'])],
                index=DATA_FRAME_COLUMNS[1:],
                name=pd.to_datetime(kline_data['t'], unit='ms')
            )
            
            if new_kline_series.name not in df.index:
                df = pd.concat([df, new_kline_series.to_frame().T])
            
            df = df.iloc[-200:]
            self.data_cache[(symbol, timeframe)] = df
            
            df_with_indicators = df.copy()
            for strategy in self.strategies:
                df_with_indicators = strategy.calculate_indicators(df_with_indicators)
                
            for strategy in self.strategies:
                signal = strategy.check_signal(df_with_indicators)
                
                if signal != SignalType.HOLD:
                    logger.info(f"[StrategistBot] SINAL {signal.value} da '{strategy.name}' para {symbol} ({timeframe}).")
                    await self._handle_signal(signal, symbol, strategy.name, df_with_indicators)
                    break 

        except Exception as e:
            logger.error(f"[StrategistBot] Erro ao processar kline: {e}", exc_info=True)

    async def _handle_signal(self, 
                             signal: SignalType, 
                             symbol: str, 
                             strategy_name: str, 
                             df_with_indicators: pd.DataFrame):
        
        # --- FILTRO DE TENDÊNCIA (PROPHET) ---
        trend_data = await self.state_manager.get_state(MARKET_STATE_COLLECTION, TREND_STATE_KEY)
        trend = trend_data.get("trend", "SIDEWAYS") if trend_data else "SIDEWAYS"
        
        if trend == "DOWNTREND" and signal == SignalType.BUY:
            logger.info(f"[StrategistBot] Sinal de COMPRA bloqueado pela Tendência Macro (Prophet): {trend}")
            return
        if trend == "UPTREND" and signal == SignalType.SELL:
             logger.info(f"[StrategistBot] Sinal de VENDA bloqueado pela Tendência Macro (Prophet): {trend}")
             return
        
        if not self.ia_ready:
            logger.warning(f"[StrategistBot] Sinal {signal.value} recebido, mas IA não está pronta. A ignorar.")
            return

        if len(df_with_indicators) < WINDOW_SIZE:
            logger.warning(f"[StrategistBot] Insuficientes velas ({len(df_with_indicators)}) para a IA ({WINDOW_SIZE}).")
            return
            
        state_df = df_with_indicators.iloc[-WINDOW_SIZE:]
        
        try:
            missing_features = [f for f in FEATURES_TO_NORMALIZE if f not in state_df.columns]
            if missing_features:
                 logger.error(f"[StrategistBot] Falha na IA: Features em falta no DataFrame: {missing_features}")
                 return
                 
            features_df = state_df[FEATURES_TO_NORMALIZE]
            if features_df.isnull().values.any():
                 logger.warning(f"[StrategistBot] Falha na IA: Dados de entrada contêm NaN. (Indicadores a aquecer)")
                 return
                 
            normalized_df = self.preprocessor.transform(features_df)
            state_array = normalized_df.values
        except Exception as e:
            logger.error(f"[StrategistBot] Falha ao normalizar o estado para a IA: {e}", exc_info=True)
            return
            
        action = self.agent.act(state_array)
        
        ia_approval = False
        if signal == SignalType.BUY and action == TradingEnv.ACTION_BUY:
            ia_approval = True
        elif signal == SignalType.SELL and action == TradingEnv.ACTION_SELL_CLOSE:
            ia_approval = True

        if ia_approval:
            logger.info(f"[StrategistBot] Agente IA (Ação: {action}) APROVOU o sinal {signal.value}. A publicar EVENT_TRADE_SIGNAL.")
            trade_signal = TradeSignal(
                symbol=symbol,
                side=OrderSide.BUY if signal == SignalType.BUY else OrderSide.SELL,
                strategy=f"{strategy_name}+DRL"
            )
            await self.event_bus.publish(EVENT_ORDER_REQUEST, trade_signal.model_dump())
        else:
            logger.info(f"[StrategistBot] Agente IA (Ação: {action}) REJEITOU o sinal {signal.value}.")


    async def run(self):
        """Inicia o bot e subscreve aos eventos."""
        await self._load_ia_model()
        
        await self._subscribe(EVENT_KLINE_CLOSED, self._on_kline)
        await self._subscribe(EVENT_HOT_LIST_UPDATED, self._on_hot_list_updated)
        await self._subscribe(EVENT_TRAINER_DONE, self._load_ia_model)
        await self._subscribe(EVENT_OPTIMIZER_DONE, self._on_optimizer_done)
        
        logger.info("[StrategistBot] Pronto.")
        while True:
            await asyncio.sleep(3600)