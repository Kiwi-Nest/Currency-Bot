import datetime
import json
import random
import os
import asyncio
from types import SimpleNamespace

import discord
from discord.ext import commands

from CurrencyBot import CurrencyBot

#cooldown = 86400
cooldown = 60  # For testing purposes, set to 60 seconds

class DailyView(discord.ui.View):
    def __init__(self, bot: CurrencyBot, ownerId: int):
        super().__init__(timeout=None)
        self.channel: discord.abc.Messageable = None
        self.owner = ownerId
        self.bot = bot
        asyncio.create_task(self.appendOwner())

    @discord.ui.button(label="Remind me", style=discord.ButtonStyle.primary, custom_id="REMIND")
    async def refresh(self, ctx: discord.Interaction, button: discord.ui.Button):
        if(ctx.user.id != self.owner):
            await ctx.response.send_message("You can't mess with this UI.", ephemeral=True)
            return

        button.disabled = True
        self.stop()
        asyncio.create_task(self.removeOwner())

        self.channel = ctx.channel

        # Faking message till I make it
        fake_message = SimpleNamespace()
        fake_message.id = ctx.message.id
        fake_message.author = ctx.user
        fake_message.guild = ctx.guild
        fake_message.channel = ctx.channel

        command = self.bot.get_command("daily")
        # Evil undocumented API abuse
        bucket = command._buckets.get_bucket(fake_message)
        retry_after = bucket.get_retry_after()

        asyncio.create_task(self.remind(int(retry_after)))

        await ctx.message.edit(view=self)
        await ctx.response.send_message("You will be pinged when you can claim next", ephemeral=True)

    async def appendOwner(self):
        if(not os.path.isfile("uis.json")):
            open("uis.json", "w").write("[]")
        with open("uis.json", "r") as f:
            try:
                owners = list[int](json.loads(f.read()))
                if (self.owner in owners):
                    return
            except json.decoder.JSONDecodeError:
                owners = []

            owners.append(self.owner)
            open("uis.json", "w").write(json.dumps(owners))

    async def removeOwner(self):
        if (not os.path.isfile("uis.json")):
            return
        with open("uis.json", "r") as f:
            try:
                owners = list[int](json.loads(f.read()))
                owners.remove(self.owner)

                open("uis.json", "w").write(json.dumps(owners))
            except Exception:
                return

    async def remind(self, time: int):
        await asyncio.sleep(time)
        owner = await self.bot.fetch_user(self.owner)
        await self.channel.send(f"{owner.mention}, it's time to claim your daily!")


    @staticmethod
    def getOwners():
        if (not os.path.isfile("uis.json")):
            return []
        try:
            with open("uis.json", "r") as f:
                return list[int](json.loads(f.read()))
        except Exception:
            return []

class Daily(commands.Cog):
    def __init__(self, bot: CurrencyBot):
        self.bot = bot

    @commands.hybrid_command(name="daily", description="Claim your daily monies")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    async def daily(self, ctx: commands.Context):
        await ctx.defer()

        self.bot.cursor.execute("SELECT balance FROM currencies WHERE discord_id = ?", (ctx.author.id,))
        result = self.bot.cursor.fetchone()
        balance = int(result[0]) if result else 0

        if random.randint(1, 100) == 1:
            daily_mon = random.randint(101, 10000)
        else:
            daily_mon = random.randint(50, 100)

        new_balance = balance + daily_mon

        self.bot.cursor.execute("INSERT INTO currencies (discord_id, balance) VALUES (?, ?) ON CONFLICT(discord_id) DO UPDATE SET balance = ?", (ctx.author.id, new_balance, new_balance))
        self.bot.conn.commit()
        print(f'User {ctx.author.display_name} has a balance of {new_balance}')

        # Create and send the embed
        embed = discord.Embed(
            title="Daily Claim",
            description=f"{ctx.author.mention}\n Balance: {new_balance}",
            color=discord.Color.green()
        )

        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        embed.set_footer(text=f"{ctx.author.name} | Balance", icon_url=ctx.author.avatar.url)
        embed.timestamp = datetime.datetime.now()

        view = DailyView(self.bot, ctx.author.id)
        await ctx.send(f"{ctx.author.mention} claimed their daily, +${daily_mon}", embed=embed, view=view)

        print(f'Daily command executed by {ctx.author.display_name}.\n')

    @daily.error
    async def daily_error(self, ctx: commands.Context, error):
        if(isinstance(error, commands.CommandOnCooldown)):
            time_left = error.retry_after

            hours = int(time_left // 3600)
            minutes = int((time_left % 3600) // 60)
            seconds = int(time_left % 60)

            embed = discord.Embed(
                title="Daily Claim",
                description=f"Claim next in {hours}h, {minutes}m, {seconds}s",
                color=discord.Color.red()
            )

            embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
            embed.set_footer(text=f"{ctx.author.display_name} | Daily Claim", icon_url=ctx.author.display_avatar.url)
            embed.timestamp = datetime.datetime.now()
            await ctx.send(f"You have already claimed this within the last 24 hours, please wait {hours}h {minutes}m {seconds}s", embed=embed)

        print(f'Daily command executed by {ctx.author.display_name}.\n')


async def setup(bot: CurrencyBot):
    # Persistent view
    for ownerId in DailyView.getOwners():
        bot.add_view(DailyView(bot, ownerId))

    await bot.add_cog(Daily(bot))