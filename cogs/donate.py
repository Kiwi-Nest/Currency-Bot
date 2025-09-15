import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Range

from modules.CurrencyBot import CurrencyBot


class Donate(commands.Cog):
    def __init__(self, bot: CurrencyBot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="donate",
        description="Donate to the poor",
        aliases=["give"],
    )
    @app_commands.describe(receiver="User you want to donate to")
    @app_commands.describe(amount="Amount to donate")
    async def donate(
        self,
        ctx: commands.Context,
        receiver: discord.Member,
        amount: Range[int, 1],
    ) -> None:
        await ctx.defer()

        if balance := await self.bot.currency_db.get_balance(ctx.author.id) < amount:
            await ctx.send(f"Insufficient funds! You have ${balance}")
            return

        await self.bot.currency_db.remove_money(ctx.author.id, amount)
        await self.bot.currency_db.add_money(receiver.id, amount)

        await ctx.send(
            f"{ctx.author.mention} donated ${amount} to {receiver.name}.",
        )

        print(f"Donate command executed by {ctx.author.display_name}.\n")


async def setup(bot: CurrencyBot) -> None:
    await bot.add_cog(Donate(bot))
