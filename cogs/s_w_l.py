import random

from discord import app_commands
from discord.ext import commands

from CurrencyBot import CurrencyBot

cooldown = 300

class Sell(commands.Cog):
    def __init__(self, bot: CurrencyBot):
        self.bot = bot

    @commands.hybrid_command(name="sell", description="Sell one of wndx2's limbs")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    @app_commands.describe(limb="Limb to sell")
    @app_commands.choices(limb=[
        app_commands.Choice(name="Left Arm", value="left arm"),
        app_commands.Choice(name="Right Arm", value="right arm"),
        app_commands.Choice(name="Left Leg", value="left leg"),
        app_commands.Choice(name="Right Leg", value="right leg"),
        app_commands.Choice(name="Head", value="head"),
        app_commands.Choice(name="Torso", value="torso"),
    ])
    async def sell(self, ctx: commands.Context, limb: str):
        await ctx.defer()

        self.bot.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (ctx.author.id,))
        balance = self.bot.cursor.fetchone()
        balance = int(balance[0]) if balance else 0

        random_num = random.randint(1, 100)
        balance += random_num

        self.bot.cursor.execute("INSERT INTO currencies (discord_id, balance) VALUES (?, ?) ON CONFLICT(discord_id) DO UPDATE SET balance = ?", (ctx.author.id, balance, balance))
        self.bot.conn.commit()

        print(f"User {ctx.author.display_name} has sold wndx2's {limb} for {random_num}.")
        await ctx.send(f"{ctx.author.mention}, you sold wndx2's {limb} for ${random_num}.")

        print(f'Sell command executed by {ctx.author.display_name}.\n')

    @sell.error
    async def sell_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            time_left = error.retry_after
            minutes = int(time_left // 60)
            seconds = int(time_left % 60)
            await ctx.send(f"Please wait {minutes}m {seconds}s before selling again.")

async def setup(bot):
    await bot.add_cog(Sell(bot))