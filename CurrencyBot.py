import pathlib
import random
import re
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

    # Check if Fibo thanked for bumping
    async def on_message(self, message: Message, /) -> None:
        bump_channel_id = 1328629578683383879
        fibo_bot_id = 735147814878969968
        bumped_regex = re.compile("Thx for bumping our Server! We will remind you in 2 hours!\r\n<@(\\d{18})>")

        if (
            message.channel.id == bump_channel_id
            and message.author.id == fibo_bot_id
            and (match := bumped_regex.match(message.content.strip()))
        ):
            bumper = await self.fetch_user(int(match.group(1)))
            reward = random.randint(50, 100)  # TODO(m3z0id): Change actual amount

            async with self.get_cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO currencies (discord_id, balance) VALUES (?, ?) \
                    ON CONFLICT(discord_id) DO UPDATE SET balance = ?",
                    (bumper.id, reward, reward),
                )

            await message.reply(f"{bumper.mention}\r\nAs a reward for bumping, you received {reward} coins!")
