import os
import sqlite3

import discord
from discord.ext import commands


class CurrencyBot(commands.Bot):
    loadedExtensions: list[str] = []
    conn: sqlite3.Connection
    cursor: sqlite3.Cursor

    def __init__(this):
        # Initialize the database connection
        this.conn = sqlite3.connect('currency.db')
        this.cursor = this.conn.cursor()
        # Create a table for currencies if it doesn't exist
        this.cursor.execute('''
                       CREATE TABLE IF NOT EXISTS currencies
                       (
                           id         INTEGER PRIMARY KEY AUTOINCREMENT,
                           discord_id TEXT   NOT NULL,
                           balance    NUMBER NOT NULL,
                           tsw        NUMBER,
                           tsd        NUMBER
                       )
                       ''')

        # Define the bot and its command prefix
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    # Event to notify when the bot has connected
    async def on_ready(this):
        print(f'Logged in as {this.user}')
        try:
            for filename in os.listdir('./cogs'):
                if filename.endswith('.py'):
                    await this.load_extension(f'cogs.{filename[:-3]}')
            synced = await this.tree.sync()  # Sync slash commands with Discord
            print(f'Synced {len(synced)} command(s)')
        except Exception as e:
            print(f'Error syncing commands: {e}')