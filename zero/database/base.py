from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Database URL configuration
DATABASE_URL = "postgresql+asyncpg://user:password@localhost/dbname"

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# Base class for models
Base = declarative_base()