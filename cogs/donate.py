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
        # Optional: Add checks to prevent donating to self or bots
        if receiver.id == ctx.author.id:
            await ctx.send("You cannot donate to yourself.", ephemeral=True)
            return

        if (balance := await self.bot.currency_db.get_balance(ctx.author.id)) < amount:
            await ctx.send(f"Insufficient funds! You have ${balance}")
            return

        await ctx.defer()

        success = await self.bot.currency_db.transfer_money(
            sender_id=ctx.author.id,
            receiver_id=receiver.id,
            amount=amount,
        )

        if success:
            await ctx.send(
                f"{ctx.author.mention} donated ${amount} to {receiver.mention}.",
            )
        else:
            balance = await self.bot.currency_db.get_balance(ctx.author.id)
            await ctx.send(f"Insufficient funds! You only have ${balance}.")

        print(f"Donate command executed by {ctx.author.display_name}.\n")


async def setup(bot: CurrencyBot) -> None:
    await bot.add_cog(Donate(bot))
