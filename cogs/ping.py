from discord.ext import commands


# Ping command adds the user to the database; it acts as a /start command
class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="ping", description="Responds with Pong!")
    async def ping(self, ctx: commands.Context):
        await ctx.defer()

        # Check if the user exists in the database
        self.bot.cursor.execute("SELECT * FROM currencies WHERE discord_id = ?", (ctx.author.id,))
        result = self.bot.cursor.fetchone()
        if result is None:
            # If the user does not exist, insert them with a default balance
            self.bot.cursor.execute("INSERT INTO currencies (discord_id, balance) VALUES (?, ?)", (ctx.author.id, 0))
            self.bot.conn.commit()
            print(f'New user added: {ctx.author.id}')
        await ctx.send("Pong!")
        print(f'Ping command executed by {ctx.author.display_name}.\n')

async def setup(bot):
    await bot.add_cog(Ping(bot))