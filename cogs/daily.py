import discord
from discord.ext import commands
import sqlite3
import random
import datetime

cooldown = 86400

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('currency.db')
        self.cursor = self.conn.cursor()

    @commands.hybrid_command(name="daily", description="Claim your daily monies")
    async def Daily(self, ctx: commands.Context, member: discord.Member = None):
        await ctx.defer()
        if member is None:
            member = ctx.author
        user_id = str(member.id)
        self.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (user_id,))
        result = self.cursor.fetchone()
        self.cursor.execute("SELECT tsd FROM currencies WHERE discord_id = ?", (user_id))
        tsd = self.cursor.fetchone()
        if result:
            balance = int(result[0])
            time = 
            time_dif = time - tsd
            if time_dif > cooldown:
                if random.randint(1, 100) == 1:
                    daily_mon = random.randint(101, 100000000000000000)
                else:
                    daily_mon = random.randint(1, 100)
                print(f'User {user_id} has a balance of {balance}')
                await ctx.send(f"{member.name} claimed their daily, +${daily_mon}")
                self.cu
            else:
                time_left = int(time_dif - cooldown)
                await ctx.send(f"You have already claimed this within the last 24 hours, please wait {time_left}")

        else:
            print(f'User {user_id} not found in the database.')
            await ctx.send("User not found in the database.")
        print(f'Bal command executed by {user_id}.\n')

async def setup(bot):
    await bot.add_cog(Daily(bot))