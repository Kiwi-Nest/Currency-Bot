import discord
from discord.ext import commands
import sqlite3

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
        synced = await bot.tree.sync()  # Sync slash commands with Discord
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Error syncing commands: {e}')

# Slash command definition
@bot.tree.command(name="ping", description="Responds with Pong!")
async def ping(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    # Check if the user exists in the database
    cursor.execute("SELECT * FROM currencies WHERE discord_id = ?", (user_id,))
    result = cursor.fetchone()
    if result is None:
        # If the user does not exist, insert them with a default balance
        cursor.execute("INSERT INTO currencies (discord_id, balance) VALUES (?, ?)", (user_id, 0.0))
        conn.commit()
        print(f'New user added: {user_id}')
    await interaction.response.send_message("Pong!")
    print('Slash ping command executed.')

@bot.tree.command(name="bal", description="Displays your balance")
async def bal(interaction: discord.Interaction):
    cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (str(interaction.user.id),))
    result = cursor.fetchone()
    if result:
        balance = result[0]
        user_id = str(interaction.user.id)
        member = await interaction.guild.fetch_member(int(user_id))
        print(f'User {interaction.user.id} has a balance of {balance}')
        await interaction.response.send_message(f'{member.mention}, your balance is {balance}')
    else:
        print(f'User {interaction.user.id} not found in the database.')
        await interaction.response.send_message("User not found in the database.")
    print('Slash bal command executed.')



# Run the bot with your token
bot.run('TOKEN')