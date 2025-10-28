# --- synapse_trader/strategies/ema_crossover.py ---

import logging
import pandas as pd
from finta import TA # Usamos finta (conforme requirements.txt)

from synapse_trader.strategies.base_strategy import BaseStrategy, SignalType

logger = logging.getLogger(__name__)

class EmaCrossoverStrategy(BaseStrategy):
    """
    Estratégia de Cruzamento de Médias Móveis Exponenciais (EMA).
    Golden Cross -> BUY | Death Cross -> SELL
    """

    def __init__(self, fast_period: int = 9, slow_period: int = 21):
        super().__init__(name=f"EMA_Crossover_{fast_period}_{slow_period}")
        if fast_period >= slow_period:
            raise ValueError("O período rápido (fast_period) deve ser menor que o período lento (slow_period).")
        self.fast_period = fast_period
        self.slow_period = slow_period


    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula e adiciona as colunas 'EMA_fast' e 'EMA_slow' ao DataFrame.
        """
        try:
            # finta espera que as colunas 'open', 'high', 'low', 'close' existam
            data["EMA_fast"] = data["close"].ewm(span=self.fast_period, min_periods=1).mean()
            data["EMA_slow"] = data["close"].ewm(span=self.slow_period, min_periods=1).mean()
        except Exception as e:
            logger.error(f"[{self.name}] Erro ao calcular indicadores EMA: {e}", exc_info=True)
        
        return data
        
    def check_signal(self, data_with_indicators: pd.DataFrame) -> SignalType:
        """
        Verifica se ocorreu um cruzamento na última vela.
        """
        # Verifica se temos dados suficientes (pelo menos 2 velas e os indicadores)
        if len(data_with_indicators) < 2 or 'EMA_fast' not in data_with_indicators.columns or 'EMA_slow' not in data_with_indicators.columns:
            return SignalType.HOLD

        # Pega nas duas últimas velas
        last_row = data_with_indicators.iloc[-1]
        prev_row = data_with_indicators.iloc[-2]

        # Verifica se os indicadores não são nulos (NaN)
        if pd.isna(last_row['EMA_fast']) or pd.isna(last_row['EMA_slow']) or \
           pd.isna(prev_row['EMA_fast']) or pd.isna(prev_row['EMA_slow']):
            logger.debug(f"[{self.name}] Indicadores ainda a aquecer (NaN). A aguardar...")
            return SignalType.HOLD

        # --- Lógica do Cruzamento ---

        # Golden Cross (Sinal de Compra)
        if (last_row['EMA_fast'] > last_row['EMA_slow'] and 
            prev_row['EMA_fast'] <= prev_row['EMA_slow']):
            return SignalType.BUY

        # Death Cross (Sinal de Venda)
        if (last_row['EMA_fast'] < last_row['EMA_slow'] and 
            prev_row['EMA_fast'] >= prev_row['EMA_slow']):
            return SignalType.SELL

        # Sem sinal
        return SignalType.HOLD