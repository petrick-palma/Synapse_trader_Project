# --- synapse_trader/ml/trainer.py ---

import logging
import numpy as np

from synapse_trader.ml.trading_env import TradingEnv
from synapse_trader.ml.agent import DDQNAgent
from synapse_trader.ml.replay_buffer import ReplayBuffer

logger = logging.getLogger(__name__)

class OfflineTrainer:
    """
    Orquestra o ciclo de treino offline.
    Junta o Ambiente, o Agente e o Replay Buffer.
    """

    def __init__(self, 
                 env: TradingEnv, 
                 agent: DDQNAgent, 
                 buffer: ReplayBuffer):
        """
        Inicializa o Treinador.
        
        Args:
            env (TradingEnv): O ambiente de simulação.
            agent (DDQNAgent): O agente que irá aprender.
            buffer (ReplayBuffer): A memória de experiência.
        """
        self.env = env
        self.agent = agent
        self.buffer = buffer
        logger.info("OfflineTrainer inicializado.")

    def run_training_loop(self, 
                          n_episodes: int = 100, 
                          batch_size: int = 64, 
                          target_update_freq: int = 5):
        """
        Executa o ciclo principal de treino.
        
        Args:
            n_episodes (int): O número de "jogos" (episódios) a simular.
            batch_size (int): O tamanho do lote (batch) a amostrar da memória.
            target_update_freq (int): A frequência (em episódios) para
                                      atualizar o target_model do agente.
        """
        logger.info(
            f"A iniciar ciclo de treino: {n_episodes} episódios, "
            f"batch_size={batch_size}, target_update_freq={target_update_freq}"
        )
        
        episode_rewards = [] # Para acompanhar o progresso

        for episode in range(1, n_episodes + 1):
            state, _ = self.env.reset() # (window_size, n_features)
            total_reward = 0.0
            done = False
            
            step = 0
            while not done:
                step += 1
                
                # 1. Agente escolhe a ação
                action = self.agent.act(state)
                
                # 2. Ambiente executa a ação
                next_state, reward, terminated, truncated, info = self.env.step(action)
                done = terminated or truncated
                
                # 3. Agente guarda a experiência na memória
                self.buffer.add(state, action, reward, next_state, done)
                
                total_reward += reward
                state = next_state
                
                # 4. Agente aprende (se a memória estiver cheia o suficiente)
                if len(self.buffer) > batch_size:
                    batch = self.buffer.sample(batch_size)
                    self.agent.learn(batch)
            
            # --- Fim do Episódio ---
            
            # 5. Reduz a taxa de exploração (epsilon)
            self.agent.decay_epsilon()
            
            episode_rewards.append(total_reward)
            logger.info(
                f"Episódio: {episode}/{n_episodes} | "
                f"Passos: {step} | "
                f"Recompensa Total: {total_reward:.4f} | "
                f"Epsilon: {self.agent.epsilon:.4f}"
            )

            # 6. Atualiza o modelo 'target' (Double DQN)
            if episode % target_update_freq == 0:
                self.agent.update_target_model()

        logger.info(f"Treino concluído. Recompensa média: {np.mean(episode_rewards):.4f}")