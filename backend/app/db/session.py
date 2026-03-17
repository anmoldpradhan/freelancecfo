from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# Engine manages the connection pool
engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",  # log SQL in dev, not prod
    pool_pre_ping=True,  # test connections before use (handles DB restarts)
)

# Factory that creates new sessions
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # objects stay usable after commit
)