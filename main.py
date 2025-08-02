import discord
from discord.ext import commands
import sqlite3
import os
from dotenv import load_dotenv

# Loads environment variables
load_dotenv()

# Initialize the database connection
conn = sqlite3.connect('currency.db')
cursor = conn.cursor()
# Create a table for currencies if it doesn't exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS currencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id TEXT NOT NULL,
    balance REAL NOT NULL
)
''')
# Define the bot and its command prefix
intents = discord.Intents.default()
intents.message_content = True  # This is required to read messages
bot = commands.Bot(command_prefix="!", intents=intents)

# Event to notify when the bot has connected
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    try:
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                await bot.load_extension(f'cogs.{filename[:-3]}')
        synced = await bot.tree.sync()  # Sync slash commands with Discord
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Error syncing commands: {e}')

# Run the bot with your token
bot.run(os.getenv('TOKEN'))