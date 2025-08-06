import os

import aiosqlite
import discord
from discord.ext import commands


class CurrencyBot(commands.Bot):
    loadedExtensions: list[str] = []
    conn: aiosqlite.Connection
    cursor: aiosqlite.Cursor

    def __init__(self) -> None:
        # Define the bot and its command prefix
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def _postInit(self) -> None:
        # Initialize the database connection
        self.conn = aiosqlite.connect("currency.db")
        self.cursor = await self.conn.cursor()
        # Create a table for currencies if it doesn't exist
        await self.cursor.execute(
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
            for filename in os.listdir("./cogs"):
                if filename.endswith(".py"):
                    await self.load_extension(f"cogs.{filename[:-3]}")
            synced = await self.tree.sync()  # Sync slash commands with Discord
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Error syncing commands: {e}")
