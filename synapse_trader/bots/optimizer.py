# --- synapse_trader/bots/optimizer.py ---

import logging
import asyncio
import pandas as pd
import os
from prophet import Prophet 

from synapse_trader.bots.base_bot import BaseBot
from synapse_trader.core.event_bus import AbstractEventBus
from synapse_trader.core.state_manager import AbstractStateManager
from synapse_trader.connectors.binance_client import BinanceClient

# --- CORREÇÃO: Importar constantes de types.py ---
from synapse_trader.core.types import (
    EVENT_TRAINER_DONE, 
    MARKET_STATE_COLLECTION, 
    BTC_TREND_KEY, 
    ETH_TREND_KEY
)
# --------------------------------------------------

from synapse_trader.ml.preprocessing import DataPreprocessor, FEATURES_TO_NORMALIZE
from synapse_trader.ml.trading_env import TradingEnv
from synapse_trader.ml.agent import DDQNAgent
from synapse_trader.ml.replay_buffer import ReplayBuffer
from synapse_trader.ml.trainer import OfflineTrainer

from synapse_trader.strategies.base_strategy import BaseStrategy
from synapse_trader.strategies.ema_crossover import EmaCrossoverStrategy
from synapse_trader.strategies.stochastic_rsi_scalp import StochasticRsiScalpStrategy
from synapse_trader.strategies.macd_crossover import MacdCrossoverStrategy 
from synapse_trader.strategies.rsi_momentum import RsiMomentumStrategy 

logger = logging.getLogger(__name__)

# --- Configurações de Treino (DRL) ---
TRAIN_SYMBOL_DRL = "BTCUSDT"
TRAIN_TIMEFRAME_DRL = "15m"
TRAIN_KLINES_LIMIT_DRL = 3000
WINDOW_SIZE = 10
N_EPISODES = 50
BATCH_SIZE = 64
BUFFER_SIZE = 10000
TARGET_UPDATE_FREQ = 5
OPTIMIZE_INTERVAL_SECONDS = 60 * 60 * 24 # 1x/dia

# --- Configurações de Treino (Prophet) ---
PROPHET_KLINES_LIMIT = 1500
PROPHET_TIMEFRAME = "4h"
PROPHET_FORECAST_PERIODS = 8 
PROPHET_CONFIDENCE_THRESHOLD = 0.005 

# Caminhos dos modelos
MODEL_DIR = "./models"
SCALER_PATH = os.path.join(MODEL_DIR, "scaler.joblib")
AGENT_PATH = os.path.join(MODEL_DIR, "agent_weights.h5")

KLINE_COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume", 
    "close_time", "quote_asset_volume", "number_of_trades", 
    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
]
DATA_FRAME_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

class OptimizerBot(BaseBot):
    """
    Executa o treino DRL e a previsão Prophet periodicamente (no 'worker').
    """
    OPTIMIZE_INTERVAL_SECONDS = OPTIMIZE_INTERVAL_SECONDS 
    SCALER_PATH = SCALER_PATH
    AGENT_PATH = AGENT_PATH
    WINDOW_SIZE = WINDOW_SIZE
    
    def __init__(self, 
                 event_bus: AbstractEventBus, 
                 state_manager: AbstractStateManager,
                 binance_client: BinanceClient):
        
        super().__init__(event_bus, state_manager)
        self.binance_client = binance_client
        os.makedirs(MODEL_DIR, exist_ok=True)
        
        self.feature_strategies: list[BaseStrategy] = [
            EmaCrossoverStrategy(fast_period=9, slow_period=21),
            StochasticRsiScalpStrategy(k_period=14),
            MacdCrossoverStrategy(fast_period=12, slow_period=26, signal_period=9), 
            RsiMomentumStrategy(period=14, oversold=30, overbought=70) 
        ]
        logger.info(f"[OptimizerBot] A usar {len(self.feature_strategies)} estratégias para geração de features DRL.")

    async def _prepare_training_data_drl(self) -> pd.DataFrame | None:
        """Busca dados e calcula features para o treino DRL."""
        logger.info(f"[OptimizerBot-DRL] A buscar {TRAIN_KLINES_LIMIT_DRL} klines de {TRAIN_SYMBOL_DRL} {TRAIN_TIMEFRAME_DRL}...")
        try:
            klines = await self.binance_client.get_klines(
                symbol=TRAIN_SYMBOL_DRL, 
                interval=TRAIN_TIMEFRAME_DRL, 
                limit=TRAIN_KLINES_LIMIT_DRL
            )
            df = pd.DataFrame(klines, columns=KLINE_COLUMNS)
            df = df[DATA_FRAME_COLUMNS].copy()
            df = df.astype(float)
            
            for strategy in self.feature_strategies:
                df = strategy.calculate_indicators(df)
            
            df.dropna(inplace=True)
            df.reset_index(drop=True, inplace=True)
            
            for feature in FEATURES_TO_NORMALIZE:
                if feature not in df.columns:
                    logger.error(f"[OptimizerBot-DRL] Feature '{feature}' em falta! O treino DRL irá falhar.")
                    return None
            return df

        except Exception as e:
            logger.error(f"[OptimizerBot-DRL] Falha ao preparar dados: {e}", exc_info=True)
            return None

    async def _run_drl_training(self):
        """Executa o ciclo completo de treino DRL."""
        logger.info("[OptimizerBot-DRL] A iniciar ciclo de treino DRL...")
        
        training_data = await self._prepare_training_data_drl()
        if training_data is None or training_data.empty:
            logger.error("[OptimizerBot-DRL] Ciclo DRL falhou: Sem dados.")
            return False

        try:
            preprocessor = DataPreprocessor(features=FEATURES_TO_NORMALIZE)
            preprocessor.fit(training_data)
            preprocessor.save(SCALER_PATH)
        except Exception as e:
            logger.error(f"[OptimizerBot-DRL] Falha ao treinar o Scaler: {e}", exc_info=True)
            return False

        normalized_data = preprocessor.transform(training_data)
        
        env = TradingEnv(data=normalized_data[FEATURES_TO_NORMALIZE], window_size=WINDOW_SIZE)
        agent = DDQNAgent(state_shape=(WINDOW_SIZE, len(FEATURES_TO_NORMALIZE)), n_actions=env.action_space)
        buffer = ReplayBuffer(buffer_size=BUFFER_SIZE)
        trainer = OfflineTrainer(env, agent, buffer)
        
        await asyncio.to_thread(
            trainer.run_training_loop,
            n_episodes=N_EPISODES,
            batch_size=BATCH_SIZE,
            target_update_freq=TARGET_UPDATE_FREQ
        )
        
        agent.save(AGENT_PATH)
        logger.info("[OptimizerBot-DRL] Treino DRL concluído e modelos salvos.")
        return True # Sucesso

    async def _run_prophet_forecast(self, symbol: str, timeframe: str, state_key: str):
        """Executa a previsão (forecast) do Prophet para um símbolo."""
        logger.info(f"[OptimizerBot-Prophet] A iniciar previsão Prophet para {symbol} {timeframe}...")
        try:
            klines = await self.binance_client.get_klines(
                symbol=symbol, 
                interval=timeframe, 
                limit=PROPHET_KLINES_LIMIT
            )
            if not klines or len(klines) < 50: 
                 logger.warning(f"[OptimizerBot-Prophet] Dados insuficientes para previsão {symbol}.")
                 return
                 
            df = pd.DataFrame(klines, columns=KLINE_COLUMNS)
            
            df_prophet = df[['timestamp', 'close']].copy()
            df_prophet['ds'] = pd.to_datetime(df_prophet['timestamp'], unit='ms')
            df_prophet['y'] = df_prophet['close'].astype(float)
            df_prophet = df_prophet[['ds', 'y']]
            
            def train_prophet():
                logging.getLogger("prophet").setLevel(logging.WARNING)
                logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
                
                m = Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=False)
                m.fit(df_prophet)
                return m
            
            model = await asyncio.to_thread(train_prophet)
            
            future = model.make_future_dataframe(periods=PROPHET_FORECAST_PERIODS, freq=timeframe)
            forecast = await asyncio.to_thread(model.predict, future)
            
            current_price = df_prophet['y'].iloc[-1]
            predicted_price = forecast['yhat'].iloc[-1]
            
            trend = "SIDEWAYS"
            if predicted_price > (current_price * (1 + PROPHET_CONFIDENCE_THRESHOLD)):
                trend = "UPTREND"
            elif predicted_price < (current_price * (1 - PROPHET_CONFIDENCE_THRESHOLD)):
                trend = "DOWNTREND"
            
            logger.info(f"[OptimizerBot-Prophet] Previsão {symbol}: Atual ${current_price:.2f}, Previsto ${predicted_price:.2f} -> {trend}")
            
            await self.state_manager.set_state(
                MARKET_STATE_COLLECTION, 
                state_key, 
                {"trend": trend, "timestamp": pd.Timestamp.utcnow().isoformat()}
            )
            
        except Exception as e:
            logger.error(f"[OptimizerBot-Prophet] Falha ao prever {symbol}: {e}", exc_info=True)

    async def run_optimization_cycle(self):
        """Executa o ciclo completo de treino DRL e previsão Prophet."""
        drl_success = await self._run_drl_training()
        await self._run_prophet_forecast("BTCUSDT", PROPHET_TIMEFRAME, BTC_TREND_KEY)
        await self._run_prophet_forecast("ETHUSDT", PROPHET_TIMEFRAME, ETH_TREND_KEY)
        
        if drl_success:
            logger.info("[OptimizerBot] A publicar EVENT_TRAINER_DONE...")
            await self._publish(EVENT_TRAINER_DONE, {
                "scaler_path": SCALER_PATH,
                "agent_path": AGENT_PATH,
                "timestamp": pd.Timestamp.utcnow().isoformat()
            })
            
    async def run(self):
        """Loop principal do OptimizerBot."""
        logger.info("[OptimizerBot] A iniciar loop principal (orquestrado pelo run_worker)...")
        # A lógica principal agora está no run_worker
        pass