# --- synapse_trader/ml/model.py ---

import logging
from tensorflow.keras.models import Model # CORRIGIDO: Importação do submódulo
from tensorflow.keras.layers import ( # CORRIGIDO
    Input, LSTM, Dense, Lambda, Add
)
from tensorflow.keras.optimizers import Adam # CORRIGIDO
import tensorflow.keras.backend as K # CORRIGIDO

logger = logging.getLogger(__name__)

def build_model(input_shape: tuple, n_actions: int, learning_rate: float = 0.001) -> Model:
    """
    Constrói o modelo Dueling DDQN + LSTM.
    
    Args:
        input_shape (tuple): O formato da entrada (window_size, n_features).
                             Ex: (10, 7)
        n_actions (int): O número de ações possíveis (ex: 3 para HOLD, BUY, SELL).
        learning_rate (float): A taxa de aprendizagem para o otimizador Adam.
        
    Returns:
        Model: O modelo Keras compilado.
    """
    
    logger.info(f"A construir modelo com input_shape={input_shape}, n_actions={n_actions}")
    
    # Camada de Entrada
    inputs = Input(shape=input_shape)
    
    # Camada LSTM para processar a sequência de tempo (as 'window_size' velas)
    # return_sequences=False pois só queremos a saída após a sequência toda
    lstm_out = LSTM(64, return_sequences=False)(inputs)
    
    # --- Arquitetura Dueling ---
    
    # Braço 1: Value Stream (Estima o valor do estado V(s))
    # Uma camada Densa que leva a 1 único nó de saída.
    value_stream = Dense(32, activation="relu")(lstm_out)
    value_stream = Dense(1, name="value")(value_stream)

    # Braço 2: Advantage Stream (Estima a vantagem de cada ação A(s,a))
    # Uma camada Densa que leva a 'n_actions' nós de saída.
    advantage_stream = Dense(32, activation="relu")(lstm_out)
    advantage_stream = Dense(n_actions, name="advantage")(advantage_stream)

    # --- Agregação ---
    # Combina os braços V(s) e A(s,a)
    # Q(s,a) = V(s) + (A(s,a) - mean(A(s,a)))
    
    def aggregate_streams(streams):
        v, a = streams
        # K.expand_dims(v, axis=1) -> Transforma V de (batch_size, 1) para (batch_size, 1)
        # K.mean(a, axis=1, keepdims=True) -> Calcula a média das vantagens
        q_values = K.expand_dims(v, axis=1) + (a - K.mean(a, axis=1, keepdims=True))
        # O 'squeeze' remove a dimensão extra, retornando (batch_size, n_actions)
        return K.squeeze(q_values, axis=1)

    # Usamos uma camada Lambda para aplicar a nossa função de agregação
    # Nota: A implementação alternativa com 'Add' e 'Lambda' simples é mais comum:
    
    # V(s)
    value_stream_expanded = Lambda(lambda v: K.expand_dims(v, axis=1))(value_stream)
    
    # A(s,a) - mean(A(s,a))
    advantage_stream_mean_subtracted = Lambda(
        lambda a: a - K.mean(a, axis=1, keepdims=True)
    )(advantage_stream)
    
    # Q(s,a) = V(s) + (A(s,a) - mean(A(s,a)))
    q_values = Add(name="q_values")([value_stream_expanded, advantage_stream_mean_subtracted])
    
    # Remove a dimensão 1 (se existir) para garantir (batch_size, n_actions)
    output = Lambda(lambda q: K.squeeze(q, axis=1))(q_values)
    
    # Cria o modelo final
    model = Model(inputs=inputs, outputs=output)
    
    # Compila o modelo
    model.compile(
        optimizer=Adam(learning_rate=learning_rate),
        loss="mse"  # Mean Squared Error (padrão para Q-Learning)
    )
    
    logger.info("Modelo Keras (LSTM + Dueling DQN) construído e compilado com sucesso.")
    
    return model