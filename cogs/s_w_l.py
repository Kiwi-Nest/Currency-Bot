import random
import string
from typing import ClassVar

from discord import app_commands
from discord.ext import commands

from modules.CurrencyBot import CurrencyBot

cooldown = 300


class Sell(commands.Cog):
    LIMBS: ClassVar[list[str]] = ["Left Arm", "Right Arm", "Left Hand", "Right Hand", "Head", "Torso"]
    ORGANS: ClassVar[list[str]] = [
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
        limb=[app_commands.Choice(name=limb, value=limb.lower()) for limb in LIMBS],
    )
    async def sell(self, ctx: commands.Context, limb: str | None = None) -> None:
        await ctx.defer()

        if limb is None:
            limb = random.choice(self.LIMBS)

        if (limb := string.capwords(limb.replace("_", " "))) not in self.LIMBS:
            await ctx.send("Invalid limb", ephemeral=True)
            ctx.command.reset_cooldown(ctx)
            return

        random_num = random.randint(1, 100)
        await self.bot.currency_db.add_money(ctx.author.id, random_num)

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
        organ=[app_commands.Choice(name=organ, value=organ.lower()) for organ in ORGANS],
    )
    async def harvest(self, ctx: commands.Context, organ: str | None = None) -> None:
        await ctx.defer()

        if organ is None:
            organ = random.choice(self.ORGANS)

        if (organ := string.capwords(organ.replace("_", " "))) not in self.ORGANS:
            await ctx.send("Invalid organ", ephemeral=True)
            ctx.command.reset_cooldown(ctx)
            return

        random_num = random.randint(1, 100)
        await self.bot.currency_db.add_money(ctx.author.id, random_num)

        print(
            f"User {ctx.author.display_name} has sold wndx2's {organ.lower()} for {random_num}.",
        )
        await ctx.send(
            f"{ctx.author.mention}, you sold wndx2's {organ.lower()} for ${random_num}.",
        )

        print(f"Harvest command executed by {ctx.author.display_name}.\n")

    @sell.error
    @harvest.error
    async def sell_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            time_left = error.retry_after
            minutes = int(time_left // 60)
            seconds = int(time_left % 60)
            await ctx.send(
                f"Please wait {minutes}m {seconds}s before repeating this command.",
            )


async def setup(bot: CurrencyBot) -> None:
    await bot.add_cog(Sell(bot))
