"""Alembic migration environment for ZERO API."""

import asyncio
import os
import platform
import sys
from logging.config import fileConfig
from pathlib import Path

# Ensure the backend root (/app) is on sys.path for module resolution
backend_root = str(Path(__file__).resolve().parents[2])
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.infrastructure.database import Base

# Import all models so they're registered with Base.metadata
import app.db.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Honor the runtime DSN (ZERO_POSTGRES_URL or DATABASE_URL) over alembic.ini.
# alembic.ini was written for the legacy Docker `zero-postgres` host; the live
# stack now points at the host Postgres install via host.docker.internal.
runtime_url = os.environ.get("ZERO_POSTGRES_URL") or os.environ.get("DATABASE_URL")
if runtime_url:
    # Alembic uses sync drivers via the SQLAlchemy engine config; ensure we
    # land on a driver alembic's async runner can use.
    if runtime_url.startswith("postgresql://") and "+psycopg" not in runtime_url:
        runtime_url = runtime_url.replace("postgresql://", "postgresql+psycopg://", 1)
    config.set_main_option("sqlalchemy.url", runtime_url)

target_metadata = Base.metadata

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
