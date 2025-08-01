import discord
from discord.ext import commands
import sqlite3

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('currency.db')
        self.cursor = self.conn.cursor()

    @commands.hybrid_command(name="ping", description="Responds with Pong!")
    async def ping(self, ctx: commands.Context):
        await ctx.defer()
        user_id = str(ctx.author.id)
        # Check if the user exists in the database
        self.cursor.execute("SELECT * FROM currencies WHERE discord_id = ?", (user_id,))
        result = self.cursor.fetchone()
        if result is None:
            # If the user does not exist, insert them with a default balance
            self.cursor.execute("INSERT INTO currencies (discord_id, balance) VALUES (?, ?)", (user_id, 0.0))
            self.conn.commit()
            print(f'New user added: {user_id}')
        await ctx.send("Pong!")
        print(f'Ping command executed by {user_id}.\n')

async def setup(bot):
    await bot.add_cog(Ping(bot))