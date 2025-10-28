# Copilot Instructions for Synapse Trader Project

## Project Overview
- **Purpose:** Algorithmic trading platform with modular bots, strategies, ML agents, and API/dashboard for monitoring and control.
- **Main Components:**
  - `synapse_trader/bots/`: Trading bots (analyst, arbitrage, executor, etc.)
  - `synapse_trader/strategies/`: Strategy implementations (EMA, MACD, RSI, etc.)
  - `synapse_trader/ml/`: ML agent, model, training, and environment code
  - `synapse_trader/core/`: Data feed, event bus, state management, Redis/GCP clients
  - `synapse_trader/api/`: FastAPI endpoints and main server logic
  - `synapse_trader/dashboard/`: Web dashboard (HTML/CSS/JS)
  - `synapse_trader/utils/`: Config, logging, database, symbol filters
  - `synapse_trader/backtester/`: Backtesting and optimization adapters
  - `synapse_trader/connectors/`: Exchange clients (Binance, Gemini)

## Developer Workflows
- **Run API server:** `python run_api.py` or `python synapse_trader/run_api.py`
- **Run trading bot:** `python run_trading.py`
- **Run worker:** `python run_worker.py`
- **Backtesting:** Use scripts in `synapse_trader/backtester/` (e.g., `run_optimization.py`)
- **Tests:**
  - Location: `synapse_trader/tests/`
  - Run: `pytest synapse_trader/tests/`
- **Dependencies:**
  - Python packages in `requirements.txt`
  - ML: TensorFlow/Keras
  - Web: FastAPI, Jinja2, JS/CSS static assets
  - Docker: Compose files for local/dev environments

## Key Patterns & Conventions
- **Bots/Strategies:**
  - Each bot/strategy is a class; inherit from `base_bot.py` or `base_strategy.py`
  - Strategies use `state`, `act`, and `learn` methods for RL/ML integration
- **ML Agents:**
  - DDQN agent in `ml/agent.py` uses Keras models built via `ml/model.py`
  - Replay buffer and training logic in `ml/replay_buffer.py` and `ml/trainer.py`
- **API:**
  - FastAPI endpoints in `api/endpoints.py`, main app in `api/main.py`
  - Use dependency injection for config/state
- **Config/Logging:**
  - Centralized in `utils/config.py` and `utils/logging_config.py`
- **Data Flow:**
  - Event-driven via `core/event_bus.py`
  - State managed in `core/state_manager.py`
  - Data feeds in `core/data_feed.py`
- **Backtesting:**
  - Adapters for Backtrader/VectorBT in `backtester/`
- **External Integration:**
  - Exchange connectors in `connectors/`
  - Redis/GCP clients in `core/`

## Examples
- To add a new bot: subclass `base_bot.py`, register in `run_trading.py`
- To create a new strategy: subclass `base_strategy.py`, implement `act` and `learn`
- To extend API: add endpoints in `api/endpoints.py`, update `main.py`

## Tips for AI Agents
- Always use existing base classes and utility modules
- Respect the modular structure: keep new code in the correct subdirectory
- Prefer event-driven and dependency-injected patterns for new features
- Reference existing tests for coverage and integration style

---
_If any section is unclear or missing, please provide feedback for improvement._
