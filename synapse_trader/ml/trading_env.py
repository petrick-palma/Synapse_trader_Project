# --- synapse_trader/ml/trading_env.py ---

import logging
import numpy as np
import pandas as pd
import random
from typing import Tuple

logger = logging.getLogger(__name__)

class TradingEnv:
    """
    Ambiente de simulação de trading (estilo OpenAI Gym) para o
    agente DRL treinar.
    
    Opera num DataFrame *já pré-processado (normalizado)*.
    """
    
    # --- Ações ---
    ACTION_HOLD = 0
    ACTION_BUY = 1
    ACTION_SELL_CLOSE = 2 # Vende (se 'short' for permitido) ou Fecha Posição

    def __init__(self, 
                 data: pd.DataFrame, 
                 window_size: int = 10, 
                 fee_percent: float = 0.001): # 0.1% de taxa (Binance)
        """
        Inicializa o ambiente.
        
        Args:
            data (pd.DataFrame): DataFrame já normalizado com colunas
                                 ['open', 'high', 'low', 'close', 'volume', ...indicadores]
            window_size (int): Quantas velas (passos) a IA "vê" de uma vez (para o LSTM).
            fee_percent (float): Taxa de transação por operação.
        """
        self.data = data
        self.window_size = window_size
        self.fee_percent = fee_percent
        
        # O estado do ambiente (Ação, Observação, Recompensa)
        self.action_space = 3 # 0: Hold, 1: Buy, 2: Sell/Close
        self.features = self.data.columns
        self.n_features = len(self.features)
        
        # Observação: (janela, n_features) ex: (10 velas, 7 features)
        self.observation_space_shape = (self.window_size, self.n_features)
        
        # Estado interno do trade
        self._position = 0.0     # 0.0 (sem posição), 1.0 (comprado)
        self._entry_price = 0.0
        
        # Iterador
        self._start_step = self.window_size
        self._end_step = len(self.data) - 1
        self._current_step = self._start_step

        logger.info(
            f"TradingEnv inicializado. Ações: {self.action_space}, "
            f"Espaço de Observação: {self.observation_space_shape}"
        )

    def _get_state(self) -> np.ndarray:
        """
        Retorna a "janela" de observação atual (dados normalizados).
        """
        # (do passo - 10) até (passo)
        window = self.data.iloc[self._current_step - self.window_size : self._current_step]
        return window.values # Retorna um array NumPy

    def _calculate_reward(self, current_price: float) -> float:
        """
        Calcula a recompensa para o passo atual, ANTES da ação ser tomada.
        """
        reward = 0.0
        
        if self._position == 1.0: # Se estiver comprado
            # Recompensa é o P/L não realizado (variação de preço)
            prev_price = self.data.iloc[self._current_step - 1]['close']
            reward = (current_price - prev_price) / prev_price
        
        return reward

    def reset(self) -> Tuple[np.ndarray, dict]:
        """
        Reinicia o ambiente para um novo episódio de treino.
        Salta para um ponto aleatório nos dados.
        """
        # Salta para um ponto aleatório (excluindo a última parte
        # para que o episódio possa correr por algum tempo)
        safe_end = self._end_step - (self.window_size * 2) # Garante algum espaço
        if safe_end <= self._start_step:
            safe_end = self._start_step + 1

        self._current_step = random.randint(self._start_step, safe_end)
        
        # Reseta o estado do trade
        self._position = 0.0
        self._entry_price = 0.0
        
        # Retorna o primeiro estado
        state = self._get_state()
        info = {'step': self._current_step} # Informação de debug
        return state, info

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, dict]:
        """
        Executa um passo no ambiente (toma uma ação).
        
        Returns:
            state (np.ndarray): O próximo estado (janela de observação).
            reward (float): A recompensa ganha neste passo.
            terminated (bool): Se o episódio terminou (fim dos dados).
            truncated (bool): (Não usado aqui, mas parte da API Gym).
            info (dict): Informação de debug.
        """
        
        # Obtém o preço de fecho atual (não normalizado)
        # Nota: Estamos a usar 'close' normalizado, o que pode ser um problema.
        # Idealmente, o 'self.data' deve ter os preços normalizados,
        # mas precisamos dos preços reais para P/L.
        # Vamos assumir que 'close' no DF é o preço normalizado.
        # Para um ambiente real, precisaríamos de DOIS DataFrames.
        
        # --- Simplificação ---
        # Vamos assumir que o 'data' contém os preços REAIS, e o
        # _get_state() normaliza-os (ou que o 'data' já está normalizado
        # e o cálculo de recompensa também é feito sobre dados normalizados)
        # Assumiremos que o 'data' está NORMALIZADO.
        
        current_price = self.data.iloc[self._current_step]['close']
        
        # 1. Calcular a recompensa do estado anterior
        reward = self._calculate_reward(current_price)
        
        # 2. Executar a ação
        if action == self.ACTION_BUY:
            if self._position == 0.0: # Se não estiver comprado, compra
                self._position = 1.0
                self._entry_price = current_price
                reward -= self.fee_percent # Penaliza pela taxa de entrada
                
        elif action == self.ACTION_SELL_CLOSE:
            if self._position == 1.0: # Se estiver comprado, fecha a posição
                # Recompensa final (P/L realizado)
                # (A recompensa do passo já foi calculada,
                # mas adicionamos a penalidade da taxa)
                reward -= self.fee_percent # Penaliza pela taxa de saída
                self._position = 0.0
                self._entry_price = 0.0

        # (Se a ação for HOLD, não faz nada)

        # 3. Avançar no tempo
        self._current_step += 1
        
        # 4. Verificar se o episódio terminou
        terminated = self._current_step >= self._end_step
        truncated = False # Não usamos truncamento
        
        # 5. Obter o novo estado
        next_state = self._get_state()
        
        info = {'step': self._current_step, 'position': self._position}
        
        return next_state, reward, terminated, truncated, info