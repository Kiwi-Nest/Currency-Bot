import discord
from discord.ext import commands
import sqlite3
import random
import time

cooldown = 300

class Sell(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="sell", description="Sell one of wndx2's limbs")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    async def sell(self, ctx: commands.Context):
        await ctx.defer()

        self.bot.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (ctx.author.id,))
        result = self.bot.cursor.fetchone()
        if result:
            balance = int(result[0])

            random_num = random.randint(1, 100)
            new_balance = balance + random_num

            limb = random.choice(["left arm", "right arm", "left leg", "right leg", "head", "torso"])
            self.bot.cursor.execute("UPDATE currencies SET balance = ? WHERE discord_id = ?", (new_balance, ctx.author.id))
            self.bot.conn.commit()
            print(f"User {ctx.author.display_name} has sold wndx2's {limb} for {random_num}.")
            await ctx.send(f"{ctx.author.mention}, you sold wndx2's {limb} for ${random_num}.")


        else:
            print(f'User {ctx.author.id} not found in the database.')
            await ctx.send("User not found in the database.")
        print(f'Sell command executed by {ctx.author.display_name}.\n')

    @sell.error
    async def sell_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            time_left = error.retry_after
            minutes = time_left // 60
            seconds = time_left % 60
            await ctx.send(f"Please wait {minutes}m {seconds}s before selling again.")

async def setup(bot):
    await bot.add_cog(Sell(bot))