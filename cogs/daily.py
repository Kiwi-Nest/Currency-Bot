import asyncio
import datetime
import json
import pathlib
import random
from types import SimpleNamespace

import aiofiles
import discord
from discord.ext import commands

from CurrencyBot import CurrencyBot

# cooldown = 86400
cooldown = 60  # For testing purposes, set to 60 seconds


class DailyView(discord.ui.View):
    def __init__(self, bot: CurrencyBot, ownerId: int) -> None:
        super().__init__(timeout=None)
        self.channel: discord.abc.Messageable = None
        self.owner = ownerId
        self.bot = bot
        # There's no other way to achieve persistent view
        asyncio.create_task(self.appendOwner())  # noqa: RUF006

    @discord.ui.button(
        label="Remind me",
        style=discord.ButtonStyle.primary,
        custom_id="REMIND",
    )
    async def refresh(
        self,
        ctx: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if ctx.user.id != self.owner:
            await ctx.response.send_message(
                "You can't mess with this UI.",
                ephemeral=True,
            )
            return

        button.disabled = True
        self.stop()
        await self.removeOwner()

        self.channel = ctx.channel

        # Faking message till I make it
        fake_message = SimpleNamespace()
        fake_message.id = ctx.message.id
        fake_message.author = ctx.user
        fake_message.guild = ctx.guild
        fake_message.channel = ctx.channel

        command = self.bot.get_command("daily")
        # Evil undocumented API abuse
        bucket = command._buckets.get_bucket(fake_message)  # noqa: SLF001
        retry_after = bucket.get_retry_after()

        # Like running a new thread, we don't care about if it fails
        asyncio.create_task(self.remind(int(retry_after)))  # noqa: RUF006

        await ctx.message.edit(view=self)
        await ctx.response.send_message(
            "You will be pinged when you can claim next",
            ephemeral=True,
        )

    async def remind(self, time: int) -> None:
        await asyncio.sleep(time + 1)
        owner = await self.bot.fetch_user(self.owner)
        await self.channel.send(f"{owner.mention}, it's time to claim your daily!")

    async def appendOwner(self) -> None:
        async with aiofiles.open("uis.json", "w+") as f:
            if not (content := (await f.read()).strip()):
                await f.write("[]")
                owners = set()
            else:
                try:
                    owners = set[int](json.loads(content))
                    if self.owner in owners:
                        return

                except json.decoder.JSONDecodeError:
                    owners = set()

            owners.add(self.owner)
            await f.write(json.dumps(list(owners)))

    async def removeOwner(self) -> None:
        if not pathlib.Path("uis.json").is_file():
            return
        async with aiofiles.open("uis.json", "w+") as f:
            owners = set[int](json.loads(await f.read()))
            owners.remove(self.owner)

            await f.write(json.dumps(list(owners)))

    @staticmethod
    async def getOwners() -> set[int]:
        if not pathlib.Path("uis.json").is_file():
            return set()
        try:
            async with aiofiles.open("uis.json") as f:
                return set[int](json.loads(await f.read()))
        except json.JSONDecodeError:
            return set()


class Daily(commands.Cog):
    def __init__(self, bot: CurrencyBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="daily", description="Claim your daily monies")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    async def daily(self, ctx: commands.Context) -> None:
        await ctx.defer()

        async with self.bot.get_cursor() as cursor:
            await cursor.execute(
                "SELECT balance FROM currencies WHERE discord_id = ?",
                (ctx.author.id,),
            )

            result = await cursor.fetchone()
            balance = int(result[0]) if result else 0
            daily_mon = random.randint(101, 10000) if random.randint(1, 100) == 1 else random.randint(50, 100)
            new_balance = balance + daily_mon

            await cursor.execute(
                "INSERT INTO currencies (discord_id, balance) VALUES (?, ?) ON CONFLICT(discord_id) DO UPDATE SET balance = ?",
                (ctx.author.id, new_balance, new_balance),
            )

        print(f"User {ctx.author.display_name} has a balance of {new_balance}")

        # Create and send the embed
        embed = discord.Embed(
            title="Daily Claim",
            description=f"{ctx.author.mention}\n Balance: {new_balance}",
            color=discord.Color.green(),
        )

        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        embed.set_footer(
            text=f"{ctx.author.name} | Balance",
            icon_url=ctx.author.avatar.url,
        )
        embed.timestamp = datetime.datetime.now()

        view = DailyView(self.bot, ctx.author.id)
        await ctx.send(
            f"{ctx.author.mention} claimed their daily, +${daily_mon}",
            embed=embed,
            view=view,
        )

        print(f"Daily command executed by {ctx.author.display_name}.\n")

    @daily.error
    async def daily_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            time_left = error.retry_after

            hours = int(time_left // 3600)
            minutes = int((time_left % 3600) // 60)
            seconds = int(time_left % 60)

            embed = discord.Embed(
                title="Daily Claim",
                description=f"Claim next in {hours}h, {minutes}m, {seconds}s",
                color=discord.Color.red(),
            )

            embed.set_author(
                name=ctx.author.name,
                icon_url=ctx.author.display_avatar.url,
            )
            embed.set_footer(
                text=f"{ctx.author.display_name} | Daily Claim",
                icon_url=ctx.author.display_avatar.url,
            )
            embed.timestamp = datetime.datetime.now()
            await ctx.send(
                f"You have already claimed this within the last 24 hours, please wait {hours}h {minutes}m {seconds}s",
                embed=embed,
            )

        print(f"Daily command executed by {ctx.author.display_name}.\n")


async def setup(bot: CurrencyBot) -> None:
    # Persistent view
    for ownerId in await DailyView.getOwners():
        bot.add_view(DailyView(bot, ownerId))

    await bot.add_cog(Daily(bot))
