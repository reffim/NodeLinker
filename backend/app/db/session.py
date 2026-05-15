import sys
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool

from app.core.config import settings

# Celery runs tasks via asyncio.run() which creates a new event loop each time.
# We must use NullPool in Celery to avoid sharing connections across different event loops.
is_celery = "celery" in sys.argv[0]

engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=settings.DEBUG,
    poolclass=NullPool if is_celery else AsyncAdaptedQueuePool
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
# Alias used by Celery worker tasks
async_session_factory = AsyncSessionLocal


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        yield session
