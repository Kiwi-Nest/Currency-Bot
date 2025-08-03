import os
import sqlite3

import discord
from discord.ext import commands


class CurrencyBot(commands.Bot):
    loadedExtensions: list[str] = []
    conn: sqlite3.Connection
    cursor: sqlite3.Cursor

    def __init__(self):
        # Initialize the database connection
        self.conn = sqlite3.connect('currency.db')
        self.cursor = self.conn.cursor()
        # Create a table for currencies if it doesn't exist
        self.cursor.execute('''
                       CREATE TABLE IF NOT EXISTS currencies
                       (
                           id         INTEGER PRIMARY KEY AUTOINCREMENT,
                           discord_id TEXT   UNIQUE NOT NULL,
                           balance    NUMBER NOT NULL
                       )
                       ''')

        # Define the bot and its command prefix
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    # Event to notify when the bot has connected
    async def on_ready(self):
        print(f'Logged in as {self.user}')
        try:
            for filename in os.listdir('./cogs'):
                if filename.endswith('.py'):
                    await self.load_extension(f'cogs.{filename[:-3]}')
            synced = await self.tree.sync()  # Sync slash commands with Discord
            print(f'Synced {len(synced)} command(s)')
        except Exception as e:
            print(f'Error syncing commands: {e}')