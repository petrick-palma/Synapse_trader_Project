# --- synapse_trader/strategies/stochastic_rsi_scalp.py ---

import logging
import pandas as pd
from finta import TA 

from synapse_trader.strategies.base_strategy import BaseStrategy, SignalType

logger = logging.getLogger(__name__)

class StochasticRsiScalpStrategy(BaseStrategy):
    """
    Estratégia de Scalping baseada no Stochastic RSI (StochRSI).
    """

    def __init__(self, k_period: int = 14, oversold: float = 20.0, overbought: float = 80.0):
        
        super().__init__(name=f"StochRSI_Scalp_{k_period}")
        self.k_period = k_period
        self.oversold = oversold
        self.overbought = overbought
        self.parameters = {'k_period': k_period, 'oversold': oversold, 'overbought': overbought}

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula e adiciona a coluna 'STOCHRSI_K' ao DataFrame.
        """
        try:
            # CORREÇÃO: Usar fillna com método moderno
            stoch_rsi = TA.STOCHRSI(data, rsi_period=self.k_period)
            if stoch_rsi is not None:
                data['STOCHRSI_K'] = (stoch_rsi * 100.0).ffill()
            else:
                # Fallback manual se a Finta falhar
                delta = data['close'].diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                avg_gain = gain.rolling(window=self.k_period).mean()
                avg_loss = loss.rolling(window=self.k_period).mean()
                rs = avg_gain / avg_loss.replace(0, 1e-9)
                rsi = 100 - (100 / (1 + rs))
                
                stoch_rsi_manual = (rsi - rsi.rolling(window=self.k_period).min()) / \
                                 (rsi.rolling(window=self.k_period).max() - rsi.rolling(window=self.k_period).min())
                data['STOCHRSI_K'] = (stoch_rsi_manual * 100.0).ffill()
                
        except Exception as e:
            logger.error(f"[{self.name}] Erro ao calcular indicadores StochRSI: {e}", exc_info=True)
            # Fallback para evitar quebrar o pipeline
            data['STOCHRSI_K'] = 50.0  # Valor neutro
        
        return data

    def check_signal(self, data_with_indicators: pd.DataFrame) -> SignalType:
        """
        Verifica se ocorreu um cruzamento de threshold (20 ou 80) na última vela.
        """
        if len(data_with_indicators) < 2 or 'STOCHRSI_K' not in data_with_indicators.columns:
            return SignalType.HOLD

        last_row = data_with_indicators.iloc[-1]
        prev_row = data_with_indicators.iloc[-2]

        if pd.isna(last_row['STOCHRSI_K']) or pd.isna(prev_row['STOCHRSI_K']):
            return SignalType.HOLD

        # BUY: StochRSI cruza de baixo para cima do oversold
        is_buy_signal = (last_row['STOCHRSI_K'] > self.oversold and 
                         prev_row['STOCHRSI_K'] <= self.oversold)

        # SELL: StochRSI cruza de cima para baixo do overbought
        is_sell_signal = (last_row['STOCHRSI_K'] < self.overbought and 
                          prev_row['STOCHRSI_K'] >= self.overbought)

        if is_buy_signal:
            return SignalType.BUY
        elif is_sell_signal:
            return SignalType.SELL
        else:
            return SignalType.HOLD