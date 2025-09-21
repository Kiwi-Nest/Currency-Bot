import pathlib
import random
import re
from typing import ClassVar

import discord
from discord import Forbidden, HTTPException, Message, MissingApplicationID
from discord.app_commands import CommandSyncFailure, TranslationError
from discord.ext import commands
from discord.ext.commands import ExtensionAlreadyLoaded, ExtensionFailed, ExtensionNotFound, NoEntryPointError

from modules.CurrencyDB import CurrencyDB
from modules.Database import Database


class CurrencyBot(commands.Bot):
    loaded_extensions: ClassVar[list[str]] = []

    def __init__(self) -> None:
        # Define the bot and its command prefix
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    # Event to notify when the bot has connected
    async def on_ready(self) -> None:
        # Initialize the database
        self.database: Database = Database()
        self.currency_db: CurrencyDB = CurrencyDB(self.database)
        print(f"Logged in as {self.user}")
        try:
            for file in pathlib.Path("cogs/").glob("*.py"):
                if file.is_file():
                    await self.load_extension(f"cogs.{file.stem}")
            synced = await self.tree.sync()  # Sync slash commands with Discord
            print(f"Synced {len(synced)} command(s)")
        except (
            HTTPException,
            CommandSyncFailure,
            Forbidden,
            MissingApplicationID,
            TranslationError,
            ExtensionNotFound,
            ExtensionAlreadyLoaded,
            NoEntryPointError,
            ExtensionFailed,
        ) as e:
            print(f"Error syncing commands: {e}")

    # Check if Fibo thanked for bumping
    async def on_message(self, message: Message, /) -> None:
        bump_channel_id = 1328629578683383879
        fibo_bot_id = 735147814878969968
        bumped_regex = re.compile("Thx for bumping our Server! We will remind you in 2 hours!\r\n<@(\\d{18})>")

        if (
            message.channel.id == bump_channel_id
            and message.author.id == fibo_bot_id
            and (match := bumped_regex.match(message.content.strip()))
        ):
            bumper = await self.fetch_user(int(match.group(1)))
            reward = random.randint(50, 100)  # TODO(m3z0id): Change actual amount

            await self.currency_db.add_money(bumper.id, reward)
            await message.reply(f"{bumper.mention}\r\nAs a reward for bumping, you received ${reward}!")
