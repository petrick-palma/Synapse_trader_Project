# --- synapse_trader/utils/database.py ---

import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, DateTime
from contextlib import asynccontextmanager
import datetime

logger = logging.getLogger(__name__)

# Define o caminho para o ficheiro da base de dados SQLite
# Ficará em /app/data/trades.db dentro do contentor
DATABASE_URL = "sqlite+aiosqlite:///./data/trades.db"

# Cria o 'engine' assíncrono
engine = create_async_engine(DATABASE_URL, echo=False)

# Cria um 'sessionmaker' assíncrono
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    """Classe base para os modelos SQLAlchemy."""
    pass

# --- Modelo de Tabela ---

class TradeLog(Base):
    """
    Modelo (tabela) para registar trades concluídos.
    """
    __tablename__ = "trade_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    strategy: Mapped[str] = mapped_column(String(50))
    side: Mapped[str] = mapped_column(String(10)) # BUY ou SELL (lado da entrada)
    
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    
    pnl: Mapped[float] = mapped_column(Float) # Lucro ou Perda (P/L)
    pnl_percent: Mapped[float] = mapped_column(Float)
    
    timestamp_entry: Mapped[datetime.datetime] = mapped_column(DateTime)
    timestamp_exit: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

# --- Funções de Gestão ---

@asynccontextmanager
async def get_session() -> AsyncSession:
    """Fornece uma sessão AsyncSession com gestão de contexto."""
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        logger.error("Erro na sessão da base de dados. A reverter (rollback)...", exc_info=True)
        raise
    finally:
        await session.close()

async def init_db():
    """
    Inicializa a base de dados e cria as tabelas se não existirem.
    Deve ser chamado uma vez no arranque de cada serviço.
    """
    async with engine.begin() as conn:
        try:
            logger.info("A inicializar base de dados (SQLite)...")
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Base de dados (SQLite) inicializada com sucesso.")
        except Exception as e:
            logger.critical(f"Falha ao inicializar a base de dados (SQLite): {e}", exc_info=True)
            raise

async def log_trade_to_db(trade_data: dict):
    """
    Grava um trade concluído na base de dados.
    Espera um dicionário com os dados do trade.
    """
    try:
        async with get_session() as session:
            # Cria a entrada do log
            new_log = TradeLog(
                symbol=trade_data.get("symbol"),
                strategy=trade_data.get("strategy"),
                side=trade_data.get("side"),
                quantity=trade_data.get("quantity"),
                entry_price=trade_data.get("entry_price"),
                exit_price=trade_data.get("exit_price"),
                pnl=trade_data.get("pnl"),
                pnl_percent=trade_data.get("pnl_percent"),
                timestamp_entry=trade_data.get("timestamp_entry"),
                timestamp_exit=trade_data.get("timestamp_exit", datetime.datetime.utcnow())
            )
            session.add(new_log)
        logger.info(f"Trade registado na BD (SQLite): {trade_data.get('symbol')} P/L: {trade_data.get('pnl')}")
    except Exception as e:
        logger.error(f"Falha ao registar trade na BD (SQLite): {e}", exc_info=True)