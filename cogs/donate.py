import discord
from discord import app_commands
from discord.ext import commands

from CurrencyBot import CurrencyBot


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
        amount: int,
    ) -> None:
        await ctx.defer()

        async with self.bot.get_cursor() as cursor:
            await cursor.execute(
                "SELECT balance FROM currencies WHERE discord_id = ?",
                (ctx.author.id,),
            )
            senderBal = await cursor.fetchone()
            senderBal = int(senderBal[0]) if senderBal else 0

            await cursor.execute(
                "SELECT balance FROM currencies WHERE discord_id = ?",
                (receiver.id,),
            )
            receiverBal = cursor.fetchone()
            receiverBal = int(receiverBal[0]) if receiverBal else 0

            if senderBal >= amount > 0:
                receiverBal += amount
                senderBal -= amount

                await cursor.execute(
                    "UPDATE currencies SET balance = ? WHERE discord_id = ?",
                    (senderBal, ctx.author.id),
                )
                await cursor.execute(
                    "INSERT INTO currencies (discord_id, balance) VALUES (?, ?) ON CONFLICT(discord_id) DO UPDATE SET balance = ?",
                    (receiver.id, receiverBal, receiverBal),
                )

                await ctx.send(
                    f"{ctx.author.mention} donated ${amount} to {receiver.name}.",
                )
            else:
                await ctx.send("Command error")

            print(f"Donate command executed by {ctx.author.display_name}.\n")


async def setup(bot) -> None:
    await bot.add_cog(Donate(bot))
