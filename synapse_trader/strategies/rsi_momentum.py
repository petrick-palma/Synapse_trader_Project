# --- synapse_trader/strategies/rsi_momentum.py ---
import pandas as pd
from .base_strategy import BaseStrategy, SignalType

class RsiMomentumStrategy(BaseStrategy):
    def __init__(self, period: int = 14, oversold: int = 30, overbought: int = 70):
        super().__init__(name=f"RSI_Momentum_{period}_{oversold}_{overbought}")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def _rsi(self, series: pd.Series) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.rolling(window=self.period, min_periods=1).mean()
        avg_loss = loss.rolling(window=self.period, min_periods=1).mean()
        rs = avg_gain / (avg_loss.replace(0, 1e-9))
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["rsi"] = self._rsi(out["close"])
        # CORREÇÃO: Usar ffill() em vez de fillna(method='bfill')
        out = out.ffill()
        return out

    def check_signal(self, df: pd.DataFrame) -> SignalType:
        if len(df) < 2:
            return SignalType.HOLD

        prev = float(df.iloc[-2]["rsi"])
        curr = float(df.iloc[-1]["rsi"])

        # Cross down from overbought -> SELL
        if prev >= self.overbought and curr < self.overbought:
            return SignalType.SELL

        # Cross up from oversold -> BUY
        if prev <= self.oversold and curr > self.oversold:
            return SignalType.BUY

        return SignalType.HOLD