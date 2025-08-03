import discord
from discord.ext import commands

from CurrencyBot import CurrencyBot


class Donate(commands.Cog):
    def __init__(self, bot: CurrencyBot):
        self.bot = bot

    @commands.hybrid_command(name="donate", description="Donate to the poor", aliases=["give"])
    async def donate(self, ctx: commands.Context, member: discord.Member, amount: int):
        await ctx.defer()
        sender_id = str(ctx.author.id)
        receiver_id = str(member.id)
        self.bot.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (sender_id,))
        sender = self.bot.cursor.fetchone()
        self.bot.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (receiver_id,))
        receiver = self.bot.cursor.fetchone()
        if sender and sender[0] >= amount:
            self.bot.cursor.execute("UPDATE currencies SET balance = balance - ? WHERE discord_id = ?", (amount, sender_id))
            if receiver:
                self.bot.cursor.execute("UPDATE currencies SET balance = balance + ? WHERE discord_id = ?", (amount, receiver_id))
            else:
                self.bot.cursor.execute("INSERT INTO currencies (discord_id, balance) VALUES (?, ?)", (receiver_id, amount))
            self.bot.conn.commit()
            await ctx.send(f"{ctx.author.mention} donated ${amount} to {member.name}.")
        else:
            await ctx.send("Insufficient funds or account not found.")

        print(f'Donate command executed by {ctx.author.display_name}.\n')

async def setup(bot):
    await bot.add_cog(Donate(bot))