# --- synapse_trader/strategies/macd_crossover.py ---

import logging
import pandas as pd
from finta import TA 

from synapse_trader.strategies.base_strategy import BaseStrategy, SignalType

logger = logging.getLogger(__name__)

class MacdCrossoverStrategy(BaseStrategy):
    """
    Estratégia de Cruzamento MACD.
    """

    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        name = f"MACD_{fast_period}_{slow_period}_{signal_period}"
        super().__init__(name=name)
        
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.parameters = {
            'fast_period': fast_period, 
            'slow_period': slow_period, 
            'signal_period': signal_period
        }

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula e adiciona as colunas 'MACD' e 'Signal' ao DataFrame.
        """
        try:
            # CORREÇÃO: A Finta retorna um DataFrame com colunas específicas
            macd_df = TA.MACD(data, 
                              period_fast=self.fast_period, 
                              period_slow=self.slow_period, 
                              signal=self.signal_period)
            
            # CORREÇÃO: Verificar se as colunas existem antes de atribuir
            if 'MACD' in macd_df.columns:
                data['MACD'] = macd_df['MACD'].ffill()
            else:
                # Fallback: calcular manualmente se a Finta não retornar a coluna esperada
                data['MACD'] = data['close'].ewm(span=self.fast_period).mean() - data['close'].ewm(span=self.slow_period).mean()
            
            if 'SIGNAL' in macd_df.columns:
                data['Signal'] = macd_df['SIGNAL'].ffill()
            elif 'Signal' in macd_df.columns:
                data['Signal'] = macd_df['Signal'].ffill()
            else:
                # Fallback: calcular manualmente
                data['Signal'] = data['MACD'].ewm(span=self.signal_period).mean()
                
        except Exception as e:
            logger.error(f"[{self.name}] Erro ao calcular indicadores MACD: {e}", exc_info=True)
            # Fallback para cálculo manual em caso de erro
            data['MACD'] = data['close'].ewm(span=self.fast_period).mean() - data['close'].ewm(span=self.slow_period).mean()
            data['Signal'] = data['MACD'].ewm(span=self.signal_period).mean()
        
        return data

    def check_signal(self, data_with_indicators: pd.DataFrame) -> SignalType:
        """
        Verifica se ocorreu um cruzamento MACD na última vela disponível.
        """
        required_columns = ['MACD', 'Signal']
        if len(data_with_indicators) < 2 or not all(col in data_with_indicators.columns for col in required_columns):
            return SignalType.HOLD

        last_row = data_with_indicators.iloc[-1]
        prev_row = data_with_indicators.iloc[-2]

        if pd.isna(last_row['MACD']) or pd.isna(last_row['Signal']) or \
           pd.isna(prev_row['MACD']) or pd.isna(prev_row['Signal']):
            return SignalType.HOLD

        is_buy_signal = (last_row['MACD'] > last_row['Signal'] and 
                         prev_row['MACD'] <= prev_row['Signal'])

        is_sell_signal = (last_row['MACD'] < last_row['Signal'] and 
                          prev_row['MACD'] >= prev_row['Signal'])

        if is_buy_signal:
            return SignalType.BUY
        elif is_sell_signal:
            return SignalType.SELL
        else:
            return SignalType.HOLD