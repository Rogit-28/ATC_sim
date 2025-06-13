"""Async PostgreSQL database layer using asyncpg.

Provides connection pool management, generic query helpers,
transaction support, and bulk COPY protocol writes.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional, Sequence

import asyncpg

from src.config import Settings

logger = logging.getLogger(__name__)


class Database:
    """asyncpg connection-pool wrapper.

    Usage::

        db = Database(settings)
        await db.initialize()
        row = await db.fetchrow("SELECT 1 AS n")
        await db.close()
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: Optional[asyncpg.Pool] = None

    # ── Lifecycle ─────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create the connection pool."""
        dsn = self._settings.database_url
        logger.info(
            "Connecting to database (pool %d–%d) …",
            self._settings.database_pool_min_size,
            self._settings.database_pool_max_size,
        )

        self._pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=self._settings.database_pool_min_size,
            max_size=self._settings.database_pool_max_size,
            command_timeout=self._settings.database_pool_timeout,
            init=self._init_connection,
        )
        logger.info("Database pool created.")

    async def close(self) -> None:
        """Gracefully close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Database pool closed.")

    async def health_check(self) -> bool:
        """Return True if the database is reachable."""
        try:
            val = await self.fetchval("SELECT 1")
            return val == 1
        except Exception:
            logger.exception("Database health-check failed")
            return False

    # ── Connection init callback ──────────────────────────────

    @staticmethod
    async def _init_connection(conn: asyncpg.Connection) -> None:
        """Per-connection setup: timezone and JIT."""
        await conn.execute("SET timezone = 'UTC'")
        await conn.execute("SET jit = 'off'")

    # ── Pool access helpers ───────────────────────────────────

    @property
    def pool(self) -> asyncpg.Pool:
        """Return the underlying pool, raising if not initialised."""
        if self._pool is None:
            raise RuntimeError("Database not initialised — call initialize() first")
        return self._pool

    # ── Generic query operations ──────────────────────────────

    async def execute(self, query: str, *args: Any, timeout: Optional[float] = None) -> str:
        """Execute a statement and return the status string."""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def executemany(self, query: str, args: Sequence[Sequence[Any]], *, timeout: Optional[float] = None) -> None:
        """Execute a statement for each set of args."""
        async with self.pool.acquire() as conn:
            await conn.executemany(query, args, timeout=timeout)

    async def fetchrow(self, query: str, *args: Any, timeout: Optional[float] = None) -> Optional[asyncpg.Record]:
        """Fetch a single row (or None)."""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args, timeout=timeout)

    async def fetch(self, query: str, *args: Any, timeout: Optional[float] = None) -> list[asyncpg.Record]:
        """Fetch multiple rows."""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args, timeout=timeout)

    async def fetchval(self, query: str, *args: Any, column: int = 0, timeout: Optional[float] = None) -> Any:
        """Fetch a single value from the first row."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args, column=column, timeout=timeout)

    # ── Bulk COPY ─────────────────────────────────────────────

    async def copy_records_to_table(
        self,
        table_name: str,
        *,
        records: Sequence[tuple[Any, ...]],
        columns: Sequence[str],
        timeout: Optional[float] = None,
    ) -> str:
        """Bulk-insert rows using the PostgreSQL COPY protocol.

        Returns the COPY status string (e.g. ``COPY 42``).
        """
        async with self.pool.acquire() as conn:
            return await conn.copy_records_to_table(
                table_name,
                records=records,
                columns=columns,
                timeout=timeout,
            )

    # ── Transactions ──────────────────────────────────────────

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """Provide a connection inside an explicit transaction.

        Usage::

            async with db.transaction() as conn:
                await conn.execute("INSERT …")
                await conn.execute("UPDATE …")
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn


# ── Module-level singleton ────────────────────────────────────

_db: Optional[Database] = None


async def init_db(settings: Settings) -> Database:
    """Initialise the global Database singleton and return it."""
    global _db
    if _db is not None:
        logger.warning("init_db called but Database already initialised — returning existing instance")
        return _db
    _db = Database(settings)
    await _db.initialize()
    return _db


def get_db() -> Database:
    """Return the global Database singleton (must be initialised first)."""
    if _db is None:
        raise RuntimeError("Database not initialised — call init_db(settings) first")
    return _db
