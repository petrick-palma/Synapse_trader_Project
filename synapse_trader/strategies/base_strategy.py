# --- synapse_trader/strategies/base_strategy.py ---

import logging
import pandas as pd
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any

logger = logging.getLogger(__name__)

class SignalType(str, Enum):
    """Define os tipos de sinal que uma estratégia pode gerar."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class BaseStrategy(ABC):
    """
    Classe base abstrata para todas as estratégias de trading.
    """
    
    def __init__(self, name: str):
        self.name = name
        self.parameters: Dict[str, Any] = {} 
        logger.info(f"Estratégia '{self.name}' inicializada.")

    @abstractmethod
    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula indicadores.
        """
        pass

    @abstractmethod
    def check_signal(self, data_with_indicators: pd.DataFrame) -> SignalType:
        """
        Verifica a última vela (linha) do DataFrame para um sinal de trading.
        """
        pass

    def set_parameters(self, new_params: Dict[str, Any]): 
        """
        Atualiza os parâmetros da estratégia (hot-swap).
        """
        try:
            for key, value in new_params.items():
                if hasattr(self, key):
                    setattr(self, key, value)
                    self.parameters[key] = value
                else:
                    logger.warning(f"[{self.name}] Parâmetro desconhecido '{key}' ignorado durante o hot-swap.")
            
            # Atualiza o nome para refletir os novos parâmetros
            param_str = '_'.join(f'{k}:{v}' for k, v in self.parameters.items())
            self.name = f"{self.__class__.__name__}_{param_str}"
            
            logger.info(f"[{self.name}] Parâmetros atualizados via otimização: {new_params}")
        except Exception as e:
            logger.error(f"[{self.name}] Falha ao atualizar parâmetros: {e}", exc_info=True)