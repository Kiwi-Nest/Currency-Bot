import discord
from discord.ext import commands
import sqlite3
import random
import datetime

class Sell(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('currency.db')
        self.cursor = self.conn.cursor()

    @commands.hybrid_command(name="sell", description="Sell one of wndx2's limbs")
    async def Sell(self, ctx: commands.Context):
        await ctx.defer()
        self.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (str(ctx.author.id),))
        result = self.cursor.fetchone()
        if result:
            balance = result[0]
            random_num = random.randint(1, 100)
            new_balance = balance + random_num
            limb = random.choice(["left arm", "right arm", "left leg", "right leg", "head", "torso"])
            user_id = str(ctx.author.id)
            member = await ctx.guild.fetch_member(int(user_id))
            print(f"User {ctx.author.id} has sold wndx2's {limb} for {random_num}.")
            self.cursor.execute("UPDATE currencies SET balance = ? WHERE discord_id = ?", (new_balance, user_id))
            self.conn.commit()
            await ctx.send(f"{member.mention}, you sold wndx2's {limb} for ${random_num}.")
        else:
            print(f'User {ctx.author.id} not found in the database.')
            await ctx.send("User not found in the database.")
        print(f'Sell command executed by {user_id}.\n')

async def setup(bot):
    await bot.add_cog(Sell(bot))