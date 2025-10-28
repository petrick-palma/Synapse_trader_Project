# --- synapse_trader/ml/replay_buffer.py ---

import logging
import random
from collections import deque
from typing import Tuple, Any

logger = logging.getLogger(__name__)

# O tipo de uma experiência
Experience = Tuple[Any, Any, Any, Any, Any] # (state, action, reward, next_state, done)

class ReplayBuffer:
    """
    Memória de Experiência (Replay Buffer) de tamanho fixo.
    Armazena 'tuplas' de experiência (s, a, r, s', done).
    """

    def __init__(self, buffer_size: int = 10000):
        """
        Inicializa o Replay Buffer.
        
        Args:
            buffer_size (int): O número máximo de experiências
                               a serem guardadas na memória.
        """
        self.buffer_size = buffer_size
        self.memory = deque(maxlen=self.buffer_size)
        logger.info(f"Replay Buffer inicializado com tamanho máximo de {buffer_size}.")

    def add(self, state, action, reward, next_state, done):
        """
        Adiciona uma nova experiência (transição) à memória.
        """
        experience = (state, action, reward, next_state, done)
        self.memory.append(experience)
        logger.debug(f"Experiência adicionada ao buffer (Tamanho atual: {len(self.memory)})")

    def sample(self, batch_size: int) -> list[Experience]:
        """
        Retorna uma amostra aleatória (batch) de experiências da memória.
        
        Args:
            batch_size (int): O número de experiências a amostrar.
            
        Returns:
            list[Experience]: Uma lista de tuplas de experiência.
        """
        if batch_size > len(self.memory):
            logger.warning(
                f"A tentar amostrar {batch_size} experiências, "
                f"mas o buffer só tem {len(self.memory)}. "
                f"A retornar {len(self.memory)}."
            )
            return random.sample(self.memory, len(self.memory))
        
        return random.sample(self.memory, batch_size)

    def __len__(self) -> int:
        """Retorna o número atual de experiências no buffer."""
        return len(self.memory)