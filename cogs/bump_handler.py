# cogs/bump_handler.py
import logging
import os
import random
import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from modules.CurrencyBot import CurrencyBot

if TYPE_CHECKING:
    from modules.CurrencyDB import CurrencyDB

log = logging.getLogger(__name__)

# Configuration constants loaded from environment variables
BUMP_CHANNEL_ID = int(os.getenv("BUMP_CHANNEL_ID"))
FIBO_BOT_ID = int(os.getenv("FIBO_BOT_ID"))
BUMPED_REGEX = re.compile("Thx for bumping our Server! We will remind you in 2 hours!\\r\\n<@(\\d{18})>")


class BumpHandlerCog(commands.Cog):
    def __init__(self, bot: CurrencyBot) -> None:
        self.bot = bot
        # The cog needs access to the currency database to give rewards
        self.currency_db: CurrencyDB = bot.currency_db

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore messages that are not from the Fibo bot in the specific bump channel
        if not (message.channel.id == BUMP_CHANNEL_ID and message.author.id == FIBO_BOT_ID):
            return

        # Check if the message content matches the bump confirmation
        if match := BUMPED_REGEX.match(message.content.strip()):
            try:
                bumper_id = int(match.group(1))
                bumper = await self.bot.fetch_user(bumper_id)
                reward = random.randint(50, 100)

                await self.currency_db.add_money(bumper.id, reward)
                await message.reply(f"{bumper.mention}\\r\\nAs a reward for bumping, you received ${reward}!")
                log.info("Rewarded %s with $%d for bumping.", bumper.display_name, reward)
            except (discord.HTTPException, ValueError):
                log.exception("Error processing bump reward")


async def setup(bot: CurrencyBot) -> None:
    await bot.add_cog(BumpHandlerCog(bot))
