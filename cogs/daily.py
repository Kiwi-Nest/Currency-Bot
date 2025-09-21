import datetime
import logging
import random
from datetime import timedelta

import discord
from discord.ext import commands

from modules.CurrencyBot import CurrencyBot

log = logging.getLogger(__name__)

# cooldown = 86400
cooldown = 60  # For testing purposes, set to 60 seconds


class DailyView(discord.ui.View):
    def __init__(self, bot: CurrencyBot, owner_id: int) -> None:
        super().__init__(timeout=None)
        self.channel: discord.abc.Messageable = None
        self.owner = owner_id
        self.bot = bot

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

        # Calculate when the cooldown ends using the known cooldown duration
        cooldown_ends = datetime.datetime.now() + timedelta(seconds=cooldown)
        cooldown_ends_str = cooldown_ends.isoformat()

        # Store the cooldown end time and enable reminder in database
        await self.bot.user_db.set_daily_cooldown(self.owner, cooldown_ends_str)
        await self.bot.user_db.set_daily_reminder(self.owner, True)

        await ctx.message.edit(view=self)
        await ctx.response.send_message(
            "You will be pinged when you can claim next",
            ephemeral=True,
        )


class Daily(commands.Cog):
    def __init__(self, bot: CurrencyBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="daily", description="Claim your daily monies")
    @commands.cooldown(1, cooldown, commands.BucketType.user)
    async def daily(self, ctx: commands.Context) -> None:
        await ctx.defer()

        # scalable daily reward logic
        rewards = [(50, 100), (101, 10000)]  # (min, max) ranges
        weights = [99, 1]  # 99% chance for standard, 1% for jackpot
        chosen_range = random.choices(rewards, weights=weights, k=1)[0]
        daily_mon = random.randint(*chosen_range)

        await self.bot.currency_db.add_money(ctx.author.id, daily_mon)

        new_balance = await self.bot.currency_db.get_balance(ctx.author.id)

        log.info("User %s has a balance of %d", ctx.author.display_name, new_balance)

        # Store the cooldown end time for this user
        cooldown_ends = datetime.datetime.now() + timedelta(seconds=cooldown)
        cooldown_ends_str = cooldown_ends.isoformat()
        await self.bot.user_db.set_daily_cooldown(ctx.author.id, cooldown_ends_str)

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

        log.info("Daily command executed by %s.", ctx.author.display_name)

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


async def setup(bot: CurrencyBot) -> None:
    # Get users with reminders from the database and add persistent views
    users_with_reminders = await bot.user_db.get_users_with_reminders()
    for owner_id in users_with_reminders:
        bot.add_view(DailyView(bot, owner_id))

    await bot.add_cog(Daily(bot))
