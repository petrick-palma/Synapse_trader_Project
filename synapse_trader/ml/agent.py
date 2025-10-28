# --- synapse_trader/ml/agent.py ---

import logging
import numpy as np # <-- CORREÇÃO: np
import random
from tensorflow.keras.models import Model # <-- CORREÇÃO

from synapse_trader.ml.model import build_model

logger = logging.getLogger(__name__)


class DDQNAgent:
    """
    Agente Dueling Double Deep Q-Network (DDQN).
    Gere os dois modelos (online e target), a política de
    ação (epsilon-greedy) e a lógica de aprendizagem (DDQN).
    """

    def __init__(self, 
                 state_shape: tuple, 
                 n_actions: int, 
                 learning_rate: float = 0.001,
                 gamma: float = 0.95, 
                 epsilon: float = 1.0, 
                 epsilon_decay: float = 0.995, 
                 epsilon_min: float = 0.01):
        
        self.state_shape = state_shape
        self.n_actions = n_actions
        self.learning_rate = learning_rate
        self.gamma = gamma                # Fator de desconto
        self.epsilon = epsilon            # Taxa de exploração
        self.epsilon_decay = epsilon_decay
        self.epsilon_min = epsilon_min
        
        # Constrói os dois modelos (online e target)
        self.model = self._build_model()
        self.target_model = self._build_model()
        
        # Inicializa o target model com os mesmos pesos
        self.update_target_model()
        
        logger.info("Agente DDQN inicializado (modelos online e target criados).")

    def _build_model(self) -> Model:
        """Constrói um modelo Keras usando a função importada."""
        return build_model(
            input_shape=self.state_shape,
            n_actions=self.n_actions,
            learning_rate=self.learning_rate
        )

    def update_target_model(self):
        """Copia os pesos do modelo online para o modelo target."""
        logger.info("A atualizar o Target Model...")
        self.target_model.set_weights(self.model.get_weights())

    def act(self, state: np.ndarray) -> int:
        """
        Toma uma decisão (ação) usando a política Epsilon-Greedy.
        
        Args:
            state (np.ndarray): O estado atual (window_size, n_features).
            
        Returns:
            int: A ação a ser tomada (0, 1, ou 2).
        """
        # Exploração (ação aleatória)
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.n_actions)
            
        # Exploitation (melhor ação prevista)
        
        # Adiciona uma dimensão de 'batch' (lote) ao estado
        # Transforma (window_size, n_features) em (1, window_size, n_features)
        state_batch = np.expand_dims(state, axis=0)
        
        # Prevê os Q-values para o estado
        q_values = self.model.predict(state_batch, verbose=0)
        
        # Retorna a ação com o maior Q-value
        return np.argmax(q_values[0])

    def learn(self, batch: list[tuple]):
        """
        Treina o modelo 'online' usando um 'batch' (lote) de
        experiências da Replay Buffer.
        
        Args:
            batch (list[tuple]): Uma lista de (state, action, reward, next_state, done).
        """
        batch_size = len(batch)
        
        # Descompacta o batch
        states, actions, rewards, next_states, dones = zip(*batch)
        
        # Converte para arrays NumPy
        states = np.array(states)
        actions = np.array(actions)
        rewards = np.array(rewards)
        next_states = np.array(next_states)
        dones = np.array(dones).astype(int) # (0 ou 1)

        # --- Lógica Dueling Double DQN (DDQN) ---
        
        # 1. Prever os Q-values para os *próximos estados* (next_states)
        #    usando o modelo *online* (self.model)
        q_online_next = self.model.predict(next_states, verbose=0)
        
        # 2. Escolher as *melhores ações* com base nesses Q-values
        best_actions_next = np.argmax(q_online_next, axis=1)

        # 3. Prever os Q-values para os *próximos estados* (next_states)
        #    usando o modelo *target* (self.target_model)
        q_target_next = self.target_model.predict(next_states, verbose=0)
        
        # 4. Selecionar o Q-value da 'melhor ação' (passo 2)
        #    a partir dos Q-values do 'target' (passo 3).
        #    Este é o "Double" do DDQN.
        target_q_for_best_action = q_target_next[range(batch_size), best_actions_next]

        # 5. Calcular o target Q-value final (Fórmula de Bellman)
        #    Se 'done' for True (1), a recompensa futura é 0.
        target_q = rewards + (self.gamma * target_q_for_best_action * (1 - dones))

        # --- Treino ---
        
        # 6. Obter os Q-values atuais para os 'states' originais
        current_q_values = self.model.predict(states, verbose=0)
        
        # 7. Atualizar *apenas* o Q-value da 'action' que foi tomada
        #    para o 'target_q' que acabámos de calcular
        current_q_values[range(batch_size), actions] = target_q
        
        # 8. Treinar o modelo 'online' para mapear 'states' para os 'current_q_values'
        self.model.fit(states, current_q_values, epochs=1, verbose=0)

    def decay_epsilon(self):
        """Reduz a taxa de exploração (epsilon)."""
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
            self.epsilon = max(self.epsilon_min, self.epsilon)

    def save(self, filepath: str):
        """Salva os pesos do modelo online."""
        try:
            self.model.save_weights(filepath)
            logger.info(f"Pesos do Agente (modelo online) salvos em: {filepath}")
        except Exception as e:
            logger.error(f"Falha ao salvar pesos do agente: {e}", exc_info=True)

    def load(self, filepath: str):
        """Carrega os pesos para o modelo online e target."""
        try:
            self.model.load_weights(filepath)
            self.target_model.load_weights(filepath)
            logger.info(f"Pesos do Agente carregados de: {filepath} (para online e target)")
        except Exception as e:
            logger.error(f"Falha ao carregar pesos do agente: {e}", exc_info=True)