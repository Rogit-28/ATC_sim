"""Alembic environment configuration.

Reads DATABASE_URL from environment variable (or falls back to default).
Uses raw SQL migrations — no SQLAlchemy ORM metadata.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Alembic Config object — access to .ini values
config = context.config

# Set up Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Database URL: prefer env var, fall back to alembic.ini, then default
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    config.get_main_option("sqlalchemy.url") or "postgresql://postgres:changeme@localhost:5434/atc_simulator",
)

# No ORM target metadata — we use raw SQL migrations
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without requiring a live database connection.
    """
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an engine and associates a connection with the context.
    """
    connectable = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
