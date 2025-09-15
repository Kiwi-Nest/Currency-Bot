from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import ClassVar

import aiosqlite


class Database:
    DB_FILENAME: ClassVar[str] = "database.db"

    def __init__(self) -> None:
        pass

    @asynccontextmanager
    async def get_cursor(self) -> AsyncGenerator[aiosqlite.Cursor]:
        async with aiosqlite.connect(self.DB_FILENAME) as conn, conn.cursor() as cursor:
            yield cursor

    @asynccontextmanager
    async def get_conn(self) -> AsyncGenerator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.DB_FILENAME) as conn:
            yield conn
