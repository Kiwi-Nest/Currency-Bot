import datetime

import discord
from discord import app_commands
from discord.ext import commands

from CurrencyBot import CurrencyBot


class Bal(commands.Cog):
    bot: CurrencyBot
    def __init__(self, bot: CurrencyBot):
        self.bot = bot

    @commands.hybrid_command(name="bal", description="Displays a user's balance")
    @app_commands.describe(member="User whose balance to show")
    async def bal(self, ctx: commands.Context, member: discord.Member = None):
        await ctx.defer()
        if member is None:
            member = ctx.author

        await self.bot.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (member.id,))
        result = await self.bot.cursor.fetchone()
        balance = int(result[0]) if result else 0

        embed = discord.Embed(
            title="Balance",
            description=f"{member.mention}\n Wallet: {balance}",
            color=discord.Color.green()
        )
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.set_footer(text=f"{ctx.author.display_name} | Balance")
        embed.timestamp = datetime.datetime.now()
        await ctx.send(embed=embed)
        print(f'User {member.display_name} has a balance of {balance}')

        print(f'Bal command executed by {member.display_name}.\n')

async def setup(bot):
    await bot.add_cog(Bal(bot))