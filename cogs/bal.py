import datetime

import discord
from discord import app_commands
from discord.ext import commands

from modules.CurrencyBot import CurrencyBot


class Bal(commands.Cog):
    bot: CurrencyBot

    def __init__(self, bot: CurrencyBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="bal", description="Displays a user's balance")
    @app_commands.describe(member="User whose balance to show")
    async def bal(self, ctx: commands.Context, member: discord.Member = None) -> None:
        await ctx.defer()
        if member is None:
            member = ctx.author

        balance = await self.bot.currency_db.get_balance(member.id)

        embed = discord.Embed(
            title="Balance",
            description=f"{member.mention}\n Wallet: {balance}",
            color=discord.Color.green(),
        )
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.set_footer(text=f"{ctx.author.display_name} | Balance")
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)
        print(f"User {member.display_name} has a balance of ${balance}")

        print(f"Bal command executed by {member.display_name}.\n")


async def setup(bot: CurrencyBot) -> None:
    await bot.add_cog(Bal(bot))
