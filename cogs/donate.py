import discord
from discord.ext import commands
import sqlite3

class Donate(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('currency.db')
        self.cursor = self.conn.cursor()

    @commands.hybrid_command(name="donate", description="Donate to the poor", aliases=["give"])
    async def Donate(self, ctx: commands.Context, member: discord.Member, amount: int):
        await ctx.defer()
        sender_id = str(ctx.author.id)
        receiver_id = str(member.id)
        self.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (sender_id,))
        sender = self.cursor.fetchone()
        self.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (receiver_id,))
        receiver = self.cursor.fetchone()
        if sender and sender[0] >= amount:
            self.cursor.execute("UPDATE currencies SET balance = balance - ? WHERE discord_id = ?", (amount, sender_id))
            if receiver:
                self.cursor.execute("UPDATE currencies SET balance = balance + ? WHERE discord_id = ?", (amount, receiver_id))
            else:
                self.cursor.execute("INSERT INTO currencies (discord_id, balance) VALUES (?, ?)", (receiver_id, amount))
            self.conn.commit()
            await ctx.send(f"{ctx.author.mention} donated ${amount} to {member.name}.")
        else:
            await ctx.send("Insufficient funds or account not found.")

async def setup(bot):
    await bot.add_cog(Donate(bot))