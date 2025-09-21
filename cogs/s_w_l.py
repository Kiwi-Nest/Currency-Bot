import logging
import random
import string
from typing import ClassVar

from discord import app_commands
from discord.ext import commands

from modules.CurrencyBot import CurrencyBot

log = logging.getLogger(__name__)

cooldown = 300


class Sell(commands.Cog):
    LIMBS: ClassVar[tuple[str, ...]] = ("Left Arm", "Right Arm", "Left Hand", "Right Hand", "Head", "Torso")
    ORGANS: ClassVar[tuple[str, ...]] = (
        "Brain",
        "Heart",
        "Left Kidney",
        "Right Kidney",
        "Left Lung",
        "Right Lung",
        "Liver",
        "Bone Marrow",
    )

    def __init__(self, bot: CurrencyBot) -> None:
        self.bot = bot

    async def _process_sale(self, ctx: commands.Context, item: str | None, item_list: tuple[str, ...], action_name: str) -> None:
        """Handle the sale/harvest logic."""
        if item is None:
            item = random.choice(item_list)

        item = string.capwords(item.replace("_", " "))
        if item not in item_list:
            item_type = "limb" if item_list == self.LIMBS else "organ"
            await ctx.send(f"Invalid {item_type}", ephemeral=True)
            ctx.command.reset_cooldown(ctx)
            return

        random_num = random.randint(1, 100)
        await self.bot.currency_db.add_money(ctx.author.id, random_num)

        log.info(
            "User %s has sold wndx2's %s for %d.",
            ctx.author.display_name,
            item.lower(),
            random_num,
        )
        await ctx.send(
            f"{ctx.author.mention}, you sold wndx2's {item.lower()} for ${random_num}.",
        )

        log.info("%s command executed by %s.", action_name.capitalize(), ctx.author.display_name)

    @commands.hybrid_command(name="sell", description="Sell one of wndx2's limbs")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    @app_commands.describe(limb="Limb to sell")
    @app_commands.choices(
        limb=[app_commands.Choice(name=limb, value=limb.lower()) for limb in LIMBS],
    )
    async def sell(self, ctx: commands.Context, limb: str | None = None) -> None:
        await ctx.defer()
        await self._process_sale(ctx, limb, self.LIMBS, "sell")

    @commands.hybrid_command(name="harvest", description="Harvest one of wndx2's organs")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    @app_commands.describe(organ="Organ to harvest")
    @app_commands.choices(
        organ=[app_commands.Choice(name=organ, value=organ.lower()) for organ in ORGANS],
    )
    async def harvest(self, ctx: commands.Context, organ: str | None = None) -> None:
        await ctx.defer()
        await self._process_sale(ctx, organ, self.ORGANS, "harvest")

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
