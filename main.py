import discord
from discord.ext import commands

# Define the bot and its command prefix
intents = discord.Intents.default()
intents.message_content = True  # This is required to read messages
bot = commands.Bot(command_prefix="!", intents=intents)

# Event to notify when the bot has connected
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

# Run the bot with your token
bot.run('YOUR_BOT_TOKEN')