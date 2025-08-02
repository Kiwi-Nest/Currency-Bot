import discord
from discord.ext import commands
import sqlite3
import random
import time

cooldown = 300

class Sell(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('currency.db')
        self.cursor = self.conn.cursor()

    @commands.hybrid_command(name="sell", description="Sell one of wndx2's limbs")
    async def Sell(self, ctx: commands.Context):
        await ctx.defer()
        member = ctx.author  # Always use the command author
        user_id = str(member.id)
        self.cursor.execute("SELECT balance, tsw FROM currencies WHERE discord_id = ?", (user_id,))
        result = self.cursor.fetchone()
        if result:
            balance = int(result[0])
            last_claim = int(result[1]) if result[1] else 0
            now = int(time.time())
            random_num = random.randint(1, 100)
            new_balance = balance + random_num
            time_dif = now - last_claim
            if time_dif > cooldown:
                limb = random.choice(["left arm", "right arm", "left leg", "right leg", "head", "torso"])
                self.cursor.execute("UPDATE currencies SET balance = ?, tsw = ? WHERE discord_id = ?", (new_balance, now, user_id))
                self.conn.commit()
                print(f"User {user_id} has sold wndx2's {limb} for {random_num}.")
                await ctx.send(f"{member.mention}, you sold wndx2's {limb} for ${random_num}.")
            else:
                time_left = cooldown - time_dif
                minutes = time_left // 60
                seconds = time_left % 60
                await ctx.send(f"Please wait {minutes}m {seconds}s before selling again.")
        else:
            print(f'User {user_id} not found in the database.')
            await ctx.send("User not found in the database.")
        print(f'Sell command executed by {user_id}.\n')

async def setup(bot):
    await bot.add_cog(Sell(bot))