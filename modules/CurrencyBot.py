import logging
import pathlib
from datetime import datetime
from typing import ClassVar

import discord
from discord import Forbidden, HTTPException, Message, MissingApplicationID
from discord.app_commands import CommandSyncFailure, TranslationError
from discord.ext import commands, tasks
from discord.ext.commands import ExtensionAlreadyLoaded, ExtensionFailed, ExtensionNotFound, NoEntryPointError

from modules.CurrencyDB import CurrencyDB
from modules.Database import Database
from modules.UserDB import UserDB

log = logging.getLogger(__name__)


class CurrencyBot(commands.Bot):
    loaded_extensions: ClassVar[list[str]] = []

    def __init__(self) -> None:
        # Define the bot and its command prefix
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

        # Initialize activity cache for efficient database writes
        self.activity_cache: dict[int, str] = {}

    # Event to notify when the bot has connected
    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)

        # Initialize the database first
        self.database: Database = Database()
        self.currency_db = CurrencyDB(self.database)
        self.user_db = UserDB(self.database)

        # AWAIT the post-initialization tasks to ensure tables are created
        await self.currency_db.post_init()
        await self.user_db.post_init()
        log.info("Database tables initialized.")

        # Now it's safe to load cogs
        try:
            for file in pathlib.Path("cogs/").glob("*.py"):
                if file.is_file():
                    await self.load_extension(f"cogs.{file.stem}")
            synced = await self.tree.sync()  # Sync slash commands with Discord
            log.info("Synced %d command(s)", len(synced))
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
        ):
            log.exception("Error syncing commands")

        # Start the unified background task
        self.unified_background_task.start()
        log.info("Unified background task started.")

    async def on_message(self, message: Message, /) -> None:
        # Ignore all messages from any bot
        if message.author.bot:
            return

        # Cache user activity instead of writing to database immediately
        if message.guild:  # Only check if active in a server
            self.activity_cache[message.author.id] = datetime.now().isoformat()

        # IMPORTANT: This line is required to process any commands
        await self.process_commands(message)

    @tasks.loop(seconds=60)
    async def unified_background_task(self) -> None:
        """Unified background task that handles database writes and reminder checks."""
        try:
            # First, flush the activity cache to database
            if self.activity_cache:
                await self.user_db.bulk_update_last_message(self.activity_cache)
                log.info("Flushed %d user activities to database", len(self.activity_cache))
                self.activity_cache.clear()

            # Second, check for users ready for reminders
            users_ready = await self.user_db.get_users_ready_for_reminder()
            for user_id in users_ready:
                try:
                    user = await self.fetch_user(user_id)
                    if user:
                        # Find a channel to send the reminder (try to get from cache or use DM)
                        try:
                            await user.send("⏰ Your daily reward is ready to claim! Use `/daily` to get your reward.")
                            # Only clear the reminder on successful send
                            await self.user_db.clear_daily_reminder(user_id)
                            log.info("Sent daily reminder to user %d", user_id)
                        except (discord.Forbidden, discord.HTTPException):
                            # If DM fails, we could try to find a mutual guild channel
                            # For now, just log the failure
                            log.warning("Failed to send reminder to user %d", user_id)
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    log.exception("Error sending reminder to user %d", user_id)

        except (discord.HTTPException, ConnectionError, OSError):
            log.exception("Error in unified background task")

    @unified_background_task.before_loop
    async def before_unified_background_task(self) -> None:
        """Wait until the bot is ready before starting the background task."""
        await self.wait_until_ready()
