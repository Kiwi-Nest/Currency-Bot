import asyncio
import contextlib
import pathlib
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import ClassVar

import aiosqlite

type Migration = tuple[int, Callable[[aiosqlite.Connection], Awaitable[None]]]


async def _noop(_: aiosqlite.Connection) -> None: ...


MIGRATIONS: list[Migration] = [
    (3, _noop),
]


def snowflake(col: str) -> str:
    return f"CHECK({col} > 1000000)"


def scalar_or[T](row: aiosqlite.Row | None, col: str, default: T) -> T:
    return row[col] if row is not None else default  # type: ignore[index]


class WriteTx:
    """Opaque handle to an active write transaction. Only constructible by Database.transaction()."""

    __slots__ = ("_conn",)

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, parameters: Sequence[object] = ()) -> aiosqlite.Cursor:
        return await self._conn.execute(sql, parameters)

    async def executemany(self, sql: str, seq_of_parameters: Sequence[Sequence[object]]) -> aiosqlite.Cursor:
        return await self._conn.executemany(sql, seq_of_parameters)

    async def rollback(self) -> None:
        await self._conn.rollback()


class Database:
    DB_FILENAME: ClassVar[str] = "database.db"

    def __init__(self) -> None:
        self.db_path = pathlib.Path(self.DB_FILENAME).resolve()
        self._writer: aiosqlite.Connection | None = None
        self._reader: aiosqlite.Connection | None = None
        self._write_lock: asyncio.Lock | None = None

    async def connect(self) -> None:
        self._write_lock = asyncio.Lock()
        self._writer = await aiosqlite.connect(self.db_path)
        self._writer.row_factory = aiosqlite.Row
        await self._writer.execute("PRAGMA journal_mode = WAL;")
        await self._writer.execute("PRAGMA foreign_keys = ON;")
        await self._writer.execute("PRAGMA busy_timeout = 5000;")
        await self._writer.execute("PRAGMA synchronous = NORMAL;")
        await self._writer.execute("PRAGMA temp_store = MEMORY;")
        await self._writer.execute("PRAGMA mmap_size = 268435456;")

        self._reader = await aiosqlite.connect(self.db_path)
        self._reader.row_factory = aiosqlite.Row
        await self._reader.execute("PRAGMA busy_timeout = 5000;")
        await self._reader.execute("PRAGMA temp_store = MEMORY;")
        await self._reader.execute("PRAGMA mmap_size = 268435456;")

        await self.migrate()

    async def close(self) -> None:
        if self._writer:
            # Persist query-planner statistics so future runs start optimized.
            with contextlib.suppress(Exception):
                await self._writer.execute("PRAGMA analysis_limit = 400;")
                await self._writer.execute("PRAGMA optimize;")
        for conn in (self._writer, self._reader):
            if conn:
                await conn.close()
        self._writer = self._reader = self._write_lock = None

    @asynccontextmanager
    async def get_cursor(self) -> AsyncGenerator[aiosqlite.Cursor]:
        if self._reader is None:
            msg = "Database not connected."
            raise RuntimeError(msg)
        async with self._reader.cursor() as cursor:
            yield cursor

    @asynccontextmanager
    async def get_conn(self) -> AsyncGenerator[aiosqlite.Connection]:
        if self._writer is None or self._write_lock is None:
            msg = "Database not connected."
            raise RuntimeError(msg)
        async with self._write_lock:
            yield self._writer

    async def migrate(self) -> None:
        async with self.transaction() as tx:
            await tx.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY)")
            row = await (await tx.execute("SELECT version FROM schema_version")).fetchone()
            current = row[0] if row else 0
            for version, fn in MIGRATIONS:
                if version > current:
                    await fn(tx._conn)
                    await tx.execute("INSERT OR REPLACE INTO schema_version(version) VALUES (?)", (version,))

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[WriteTx]:
        """Run a block inside a single write transaction.

        Acquires the write lock, commits on clean exit, and rolls back on any
        exception. A ``return`` inside the block commits - callers that need an
        early-out without committing must call ``tx.rollback()`` explicitly first.

        Relies on sqlite's implicit (deferred) transaction: the first write
        statement opens it. Every write goes through this one serialized writer
        connection, so there is no second writer to race - an eager
        ``BEGIN IMMEDIATE`` would buy nothing here.
        """
        if self._writer is None or self._write_lock is None:
            msg = "Database not connected."
            raise RuntimeError(msg)
        async with self._write_lock:
            conn = self._writer
            try:
                yield WriteTx(conn)
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
