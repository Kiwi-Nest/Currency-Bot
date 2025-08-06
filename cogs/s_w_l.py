import random
import string

from discord import app_commands
from discord.ext import commands

from CurrencyBot import CurrencyBot

cooldown = 300


class Sell(commands.Cog):
    limbs = ["Left Arm", "Right Arm", "Left Hand", "Right Hand", "Head", "Torso"]
    organs = [
        "Brain",
        "Heart",
        "Left Kidney",
        "Right Kidney",
        "Left Lung",
        "Right Lung",
        "Liver",
        "Bone Marrow",
    ]

    def __init__(self, bot: CurrencyBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="sell", description="Sell one of wndx2's limbs")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    @app_commands.describe(limb="Limb to sell")
    @app_commands.choices(
        limb=[app_commands.Choice(name=limb, value=limb.lower()) for limb in limbs],
    )
    async def sell(self, ctx: commands.Context, limb: str | None = None) -> None:
        await ctx.defer()

        if limb is None:
            limb = random.choice(self.limbs)

        if (limb := string.capwords(limb.replace("_", " "))) not in self.limbs:
            await ctx.send("Invalid limb", ephemeral=True)
            ctx.command.reset_cooldown(ctx)
            return

        await self.bot.cursor.execute(
            "SELECT balance FROM currencies WHERE discord_id = ?",
            (ctx.author.id,),
        )
        balance = await self.bot.cursor.fetchone()
        balance = int(balance[0]) if balance else 0

        random_num = random.randint(1, 100)
        balance += random_num

        await self.bot.cursor.execute(
            "INSERT INTO currencies (discord_id, balance) VALUES (?, ?) ON CONFLICT(discord_id) DO UPDATE SET balance = ?",
            (ctx.author.id, balance, balance),
        )
        await self.bot.conn.commit()

        print(
            f"User {ctx.author.display_name} has sold wndx2's {limb.lower()} for {random_num}.",
        )
        await ctx.send(
            f"{ctx.author.mention}, you sold wndx2's {limb.lower()} for ${random_num}.",
        )

        print(f"Sell command executed by {ctx.author.display_name}.\n")

    @commands.hybrid_command(name="harvest", description="Harvest one of wndx2's limbs")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    @app_commands.describe(organ="Organ to harvest")
    @app_commands.choices(
        organ=[
            app_commands.Choice(name=organ, value=organ.lower()) for organ in organs
        ],
    )
    async def harvest(self, ctx: commands.Context, organ: str | None = None) -> None:
        await ctx.defer()

        if organ is None:
            organ = random.choice(self.organs)

        if (organ := string.capwords(organ.replace("_", " "))) not in self.organs:
            await ctx.send("Invalid organ", ephemeral=True)
            ctx.command.reset_cooldown(ctx)
            return

        await self.bot.cursor.execute(
            "SELECT balance FROM currencies WHERE discord_id = ?",
            (ctx.author.id,),
        )
        balance = await self.bot.cursor.fetchone()
        balance = int(balance[0]) if balance else 0

        random_num = random.randint(1, 100)
        balance += random_num

        await self.bot.cursor.execute(
            "INSERT INTO currencies (discord_id, balance) VALUES (?, ?) ON CONFLICT(discord_id) DO UPDATE SET balance = ?",
            (ctx.author.id, balance, balance),
        )
        await self.bot.conn.commit()

        print(
            f"User {ctx.author.display_name} has sold wndx2's {organ.lower()} for {random_num}.",
        )
        await ctx.send(
            f"{ctx.author.mention}, you sold wndx2's {organ.lower()} for ${random_num}.",
        )

        print(f"Harvest command executed by {ctx.author.display_name}.\n")

    @sell.error
    @harvest.error
    async def sell_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            time_left = error.retry_after
            minutes = int(time_left // 60)
            seconds = int(time_left % 60)
            await ctx.send(
                f"Please wait {minutes}m {seconds}s before repeating this command.",
            )


async def setup(bot) -> None:
    await bot.add_cog(Sell(bot))
