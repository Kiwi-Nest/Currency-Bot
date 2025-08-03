import datetime

import discord
from discord.ext import commands
import sqlite3
import random

from CurrencyBot import CurrencyBot

cooldown = 86400

class DailyView(discord.ui.View):
    @discord.ui.button(label="Remind me", style=discord.ButtonStyle.primary, custom_id="REMIND")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("You will be pinged when you can claim next", ephemeral=True)

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = sqlite3.connect('currency.db')
        self.cursor = self.conn.cursor()

    @commands.hybrid_command(name="daily", description="Claim your daily monies")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    async def daily(self, ctx: commands.Context, member: discord.Member = None):
        await ctx.defer()
        if member is None:
            member = ctx.author

        self.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (member.id,))
        result = self.cursor.fetchone()
        if result:
            balance = int(result[0])

            if random.randint(1, 100) == 1:
                daily_mon = random.randint(101, 10000)
            else:
                daily_mon = random.randint(50, 100)

            new_balance = balance + daily_mon
            self.cursor.execute("UPDATE currencies SET balance = ? WHERE discord_id = ?", (new_balance, member.id))
            self.conn.commit()
            print(f'User {member.display_name} has a balance of {new_balance}')

            # Create and send the embed
            embed = discord.Embed(
                title="Daily Claim",
                description=f"{member.mention}\n Balance: {new_balance}",
                color=discord.Color.green()
            )

            embed.set_author(name=member.name, icon_url=member.display_avatar.url)
            embed.set_footer(text=f"{ctx.author.name} | Balance", icon_url=ctx.author.avatar.url)
            embed.timestamp = datetime.datetime.now()

            view = DailyView()
            await ctx.send(f"{member.mention} claimed their daily, +${daily_mon}", embed=embed, view=view)
        else:
            print(f'User {member.id} not found in the database.')
            await ctx.send("User not found in the database.")
        print(f'Daily command executed by {member.display_name}.\n')

    @daily.error
    async def daily_error(self, ctx: commands.Context, error):
        if(isinstance(error, commands.CommandOnCooldown)):
            time_left = error.retry_after

            hours = time_left // 3600
            minutes = (time_left % 3600) // 60
            seconds = time_left % 60

            embed = discord.Embed(
                title="Daily Claim",
                description=f"{hours}h, {minutes}m, {seconds}s",
                color=discord.Color.red()
            )

            embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
            embed.set_footer(text=f"{ctx.author.display_name} | Daily Claim", icon_url=ctx.author.display_avatar.url)
            embed.timestamp = datetime.datetime.now()
            await ctx.send(f"You have already claimed this within the last 24 hours, please wait {hours}h {minutes}m {seconds}s", embed=embed)

        else:
            print(f'User {ctx.author.id} not found in the database.')
            await ctx.send("User not found in the database.")
        print(f'Daily command executed by {ctx.author.id}.\n')


async def setup(bot: CurrencyBot):
    # Persistent view
    bot.add_view(DailyView())

    await bot.add_cog(Daily(bot))