# --- synapse_trader/ml/preprocessing.py ---

import logging
import pandas as pd
from sklearn.preprocessing import StandardScaler
import joblib
from typing import List

logger = logging.getLogger(__name__)

# As features (colunas) que a IA irá 'ver'
FEATURES_TO_NORMALIZE = [
    'open', 
    'high', 
    'low', 
    'close', 
    'volume',
    'EMA_fast', 
    'EMA_slow', 
    'STOCHRSI_K', 
    'MACD',       # <-- NOVO
    'Signal',     # <-- NOVO
    'RSI',        # <-- NOVO
]

class DataPreprocessor:
    """
    Gere o pré-processamento (normalização) dos dados para a IA.
    Usa StandardScaler do scikit-learn.
    """
    
    def __init__(self, features: List[str] = FEATURES_TO_NORMALIZE):
        self.scaler = StandardScaler()
        self.features = features
        self._fitted = False

    def fit(self, data: pd.DataFrame):
        """
        'Treina' o StandardScaler com os dados fornecidos.
        """
        try:
            missing_cols = [col for col in self.features if col not in data.columns]
            if missing_cols:
                logger.error(
                    f"Falha ao treinar o scaler: Features em falta no DataFrame: {missing_cols}"
                )
                raise KeyError(f"Features em falta: {missing_cols}")

            data_to_fit = data[self.features]
            
            self.scaler.fit(data_to_fit)
            self._fitted = True
            logger.info(f"DataPreprocessor (StandardScaler) treinado com {len(self.features)} features.")
            
        except KeyError:
            raise
        except Exception as e:
            logger.error(f"Erro ao treinar o scaler: {e}", exc_info=True)
            raise

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Aplica a normalização (transformação) aos dados.
        """
        if not self._fitted:
            raise RuntimeError("O Scaler deve ser 'treinado' (fit) antes de 'transformar' dados.")
            
        try:
            data_transformed = data.copy()
            data_transformed[self.features] = self.scaler.transform(data[self.features])
            return data_transformed
            
        except Exception as e:
            logger.error(f"Erro ao transformar dados: {e}", exc_info=True)
            return data 

    def save(self, filepath: str):
        """Salva o scaler treinado num ficheiro usando joblib."""
        if not self._fitted:
            logger.warning("A tentar salvar um scaler que não foi treinado.")
            return
            
        try:
            joblib.dump(self.scaler, filepath)
            logger.info(f"Scaler salvo em: {filepath}")
        except Exception as e:
            logger.error(f"Falha ao salvar o scaler: {e}", exc_info=True)

    def load(self, filepath: str):
        """Carrega um scaler pré-treinado do ficheiro."""
        try:
            self.scaler = joblib.load(filepath)
            self._fitted = True
            logger.info(f"Scaler carregado de: {filepath}")
        except FileNotFoundError:
            logger.error(f"Ficheiro do scaler não encontrado em: {filepath}")
            raise
        except Exception as e:
            logger.error(f"Falha ao carregar o scaler: {e}", exc_info=True)
            raise