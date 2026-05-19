from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from zero.database.base import engine

# Create a session factory for async operations
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Dependency to get a new session for each async operation
async def get_async_session():
    async with AsyncSessionLocal() as session:
        yield session