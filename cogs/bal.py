import discord
from discord.ext import commands
import sqlite3

class Bal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('currency.db')
        self.cursor = self.conn.cursor()

    @commands.hybrid_command(name="bal", description="Displays your balance")
    async def bal(self, ctx: commands.Context):
        await ctx.defer()
        self.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (str(ctx.author.id),))
        result = self.cursor.fetchone()
        if result:
            balance = result[0]
            user_id = str(ctx.author.id)
            member = await ctx.guild.fetch_member(int(user_id))
            print(f'User {ctx.author.id} has a balance of {balance}')
            await ctx.send(f'{member.mention}, your balance is {balance}')
        else:
            print(f'User {ctx.author.id} not found in the database.')
            await ctx.send("User not found in the database.")
        print(f'Bal command executed by {user_id}.\n')

async def setup(bot):
    await bot.add_cog(Bal(bot))