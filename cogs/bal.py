import discord
from discord.ext import commands
import sqlite3

class Bal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('currency.db')
        self.cursor = self.conn.cursor()

    @commands.hybrid_command(name="bal", description="Displays a user's balance")
    async def bal(self, ctx: commands.Context, member: discord.Member = None):
        await ctx.defer()
        if member is None:
            member = ctx.author
        user_id = str(member.id)
        self.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (user_id,))
        result = self.cursor.fetchone()
        if result:
            balance = int(result[0])
            print(f'User {user_id} has a balance of {balance}')
            await ctx.send(f"{member.name}'s, balance is ${balance}")
        else:
            print(f'User {user_id} not found in the database.')
            await ctx.send("User not found in the database.")
        print(f'Bal command executed by {user_id}.\n')

async def setup(bot):
    await bot.add_cog(Bal(bot))