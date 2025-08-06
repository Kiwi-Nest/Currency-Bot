from discord.ext import commands

from CurrencyBot import CurrencyBot


# Ping command adds the user to the database; it acts as a /start command
class Ping(commands.Cog):
    def __init__(self, bot: CurrencyBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="ping", description="Responds with Pong!")
    async def ping(self, ctx: commands.Context) -> None:
        await ctx.defer()
        await ctx.send("Pong!")
        print(f"Ping command executed by {ctx.author.display_name}.\n")


async def setup(bot: CurrencyBot) -> None:
    await bot.add_cog(Ping(bot))
