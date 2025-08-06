import pathlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import ClassVar

import aiosqlite
import discord
from discord.ext import commands


class CurrencyBot(commands.Bot):
    loadedExtensions: ClassVar[list[str]] = []
    DATABASE = "currency.db"

    def __init__(self) -> None:
        # Define the bot and its command prefix
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    @asynccontextmanager
    async def get_cursor(self) -> AsyncGenerator[aiosqlite.Cursor]:
        async with aiosqlite.connect(self.DATABASE) as conn, conn.cursor() as cursor:
            yield cursor

    async def _postInit(self) -> None:
        # Initialize the database connection
        async with aiosqlite.connect(self.DATABASE) as conn:
            await conn.execute(
                """
            CREATE TABLE IF NOT EXISTS currencies
            (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT UNIQUE NOT NULL,
                balance    NUMBER      NOT NULL
            )
            """,
            )

    # Event to notify when the bot has connected
    async def on_ready(self) -> None:
        await self._postInit()
        print(f"Logged in as {self.user}")
        try:
            for file in pathlib.Path("./cogs").glob("*.py"):
                if file.is_file():
                    await self.load_extension(f"cogs.{file.stem}")
            synced = await self.tree.sync()  # Sync slash commands with Discord
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Error syncing commands: {e}")
