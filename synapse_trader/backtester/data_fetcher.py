# --- synapse_trader/backtester/data_fetcher.py ---

import logging
import asyncio
import pandas as pd
import os
from binance import AsyncClient

# Não usamos o nosso BinanceClient.py aqui, pois este script pode ser
# executado standalone para gerar os dados.
from synapse_trader.utils.config import settings

logger = logging.getLogger(__name__)

# Onde os dados serão salvos (dentro da pasta 'data' na raiz do projeto)
SAVE_DIR = "data" 
os.makedirs(SAVE_DIR, exist_ok=True)

# Colunas (deve corresponder ao StrategistBot/OptimizerBot)
KLINE_COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume", 
    "close_time", "quote_asset_volume", "number_of_trades", 
    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
]

async def fetch_data_for_backtesting(symbol: str, interval: str, start_str: str, end_str: str | None = None) -> pd.DataFrame | None:
    """
    Busca dados de velas da Binance e guarda-os como um DataFrame formatado.
    
    Args:
        symbol (str): O par de trading (ex: 'BTCUSDT').
        interval (str): O intervalo das velas (ex: '1h', '1m').
        start_str (str): Data de início (ex: '1 Jan, 2024').
        end_str (str, optional): Data de fim (ex: '1 Sep, 2024').
        
    Returns:
        pd.DataFrame | None: O DataFrame formatado ou None em caso de falha.
    """
    filename = os.path.join(SAVE_DIR, f"{symbol}_{interval}_{start_str.replace(' ', '_')}_{end_str.replace(' ', '_')}.csv")

    if os.path.exists(filename):
        logger.info(f"[Fetcher] Dados existentes para {symbol} {interval} encontrados em {filename}. A carregar...")
        try:
            df = pd.read_csv(filename, index_col='timestamp', parse_dates=True)
            return df
        except Exception as e:
            logger.warning(f"[Fetcher] Falha ao carregar o CSV: {e}. A tentar buscar novamente.")

    try:
        # Cria um cliente temporário (não o nosso BinanceClient persistente)
        client = await AsyncClient.create(
            api_key=settings.BINANCE_API_KEY, 
            api_secret=settings.BINANCE_API_SECRET,
            testnet=settings.BINANCE_TESTNET # Usa a configuração do ambiente
        )
        
        logger.info(f"[Fetcher] A baixar dados de {symbol} {interval} de {start_str} até {end_str or 'agora'}...")
        
        # Usa get_historical_klines para lidar com limites de 1000 velas
        klines = await client.get_historical_klines(
            symbol=symbol, 
            interval=interval, 
            start_str=start_str, 
            end_str=end_str
        )
        
        await client.close_connection()
        
        if not klines:
            logger.warning(f"[Fetcher] Nenhuma vela devolvida para {symbol} {interval}.")
            return None

        df = pd.DataFrame(klines, columns=KLINE_COLUMNS)
        
        # Formatação
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        # Seleciona as colunas essenciais e renomeia
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        
        # Salva para uso futuro
        df.to_csv(filename)
        logger.info(f"[Fetcher] Dados baixados e salvos em: {filename} ({len(df)} velas)")
        
        return df

    except Exception as e:
        logger.error(f"[Fetcher] Erro ao baixar dados: {e}", exc_info=True)
        return None

# --- Script de execução direta (para o docker-compose exec worker) ---
async def main_fetcher():
    """Função de entrada para download manual."""
    # Garante que as configurações estão carregadas
    from synapse_trader.utils.config import settings 
    from synapse_trader.utils.logging_config import setup_logging
    setup_logging(settings.LOG_LEVEL)

    # Exemplo de uso (os parâmetros reais podem ser passados via linha de comando no futuro)
    # Baixar 6 meses de dados de 15m para o BTC
    await fetch_data_for_backtesting("BTCUSDT", "15m", "1 May, 2025")
    await fetch_data_for_backtesting("ETHUSDT", "1h", "1 Jan, 2025")

if __name__ == "__main__":
    import sys
    # Se chamado como módulo (ex: python -m synapse_trader.backtester.data_fetcher)
    if not sys.stdin.isatty():
        print("A iniciar o downloader de dados...")
        try:
            asyncio.run(main_fetcher())
        except KeyboardInterrupt:
            print("Download interrompido.")
    else:
         print("Este script deve ser executado no modo assíncrono (ex: via run_worker.py ou asyncio.run(main_fetcher())).")