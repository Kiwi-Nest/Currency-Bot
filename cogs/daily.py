import discord
from discord.ext import commands
import sqlite3
import random
import time

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
        self.cursor.execute("SELECT balance, tsd FROM currencies WHERE discord_id = ?", (user_id,))
        result = self.cursor.fetchone()
        if result:
            balance = int(result[0])
            last_claim = int(result[1]) if result[1] else 0
            now = int(time.time())
            time_dif = now - last_claim
            if time_dif > cooldown:
                if random.randint(1, 100) == 1:
                    daily_mon = random.randint(101, 10000)
                else:
                    daily_mon = random.randint(50, 100)
                new_balance = balance + daily_mon
                self.cursor.execute("UPDATE currencies SET balance = ?, tsd = ? WHERE discord_id = ?", (new_balance, now, user_id))
                self.conn.commit()
                print(f'User {user_id} has a balance of {new_balance}')
                # Create and send the embed
                embed = discord.Embed(
                    title="Daily Claim",
                    description=f"{member.mention}\n Balance: {new_balance}",
                    color=discord.Color.green()
                )
                embed.set_author(name=member.name, icon_url=member.display_avatar.url)
                embed.set_footer(text=f"{ctx.author.name} | {discord.utils.utcnow().strftime('%H:%M:%S')} | balance")

                class DailyView(discord.ui.View):
                    @discord.ui.button(label="Remind me", style=discord.ButtonStyle.primary)
                    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
                        await interaction.response.send_message("You will be pinged when you can claim next", ephemeral=True)

                view = DailyView()
                await ctx.send(f"{member.mention} claimed their daily, +${daily_mon}", embed=embed, view=view)
            else:
                time_left = cooldown - time_dif
                hours = time_left // 3600
                minutes = (time_left % 3600) // 60
                seconds = time_left % 60
                embed = discord.Embed(
                    title="Daily Claim",
                    description=f"{hours}h, {minutes}m, {seconds}s",
                    color=discord.Color.green()
                )
                embed.set_author(name=member.name, icon_url=member.display_avatar.url)
                embed.set_footer(text=f"{ctx.author.name} | {discord.utils.utcnow().strftime('%H:%M:%S')} | daily claim")
                await ctx.send(f"You have already claimed this within the last 24 hours, please wait {hours}h {minutes}m {seconds}s",embed=embed)
        else:
            print(f'User {user_id} not found in the database.')
            await ctx.send("User not found in the database.")
        print(f'Daily command executed by {user_id}.\n')

async def setup(bot):
    await bot.add_cog(Daily(bot))