import pathlib
import random
import re
from typing import ClassVar

import discord
from discord import Forbidden, HTTPException, Message, MissingApplicationID
from discord.app_commands import CommandSyncFailure, TranslationError
from discord.ext import commands
from discord.ext.commands import ExtensionAlreadyLoaded, ExtensionFailed, ExtensionNotFound, NoEntryPointError

from modules.ActivityDB import ActivityDB
from modules.CurrencyDB import CurrencyDB
from modules.Database import Database

PRUNE_GUILD_ID = 1328629578096316427


class CurrencyBot(commands.Bot):
    loaded_extensions: ClassVar[list[str]] = []

    def __init__(self) -> None:
        # Define the bot and its command prefix
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    # Event to notify when the bot has connected
    async def on_ready(self) -> None:
        # Initialize the database
        self.database: Database = Database()
        self.currency_db = CurrencyDB(self.database)
        self.activity_db = ActivityDB(self.database)

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

        await self._prune_inactive_members()

    # Check if Fibo thanked for bumping and track user activity
    async def on_message(self, message: Message, /) -> None:
        # Ignore all bots for activity tracking, but check for Fibo bump message
        if message.author.bot:
            bump_channel_id = 1328629578683383879
            fibo_bot_id = 735147814878969968
            bumped_regex = re.compile("Thx for bumping our Server! We will remind you in 2 hours!\r\n<@(\\d{18})>")

            if (
                message.channel.id == bump_channel_id
                and message.author.id == fibo_bot_id
                and (match := bumped_regex.match(message.content.strip()))
            ):
                bumper = await self.fetch_user(int(match.group(1)))
                reward = random.randint(50, 100)
                await self.currency_db.add_money(bumper.id, reward)
                await message.reply(f"{bumper.mention}\r\nAs a reward for bumping, you received ${reward}!")
            return  # End processing for bot messages here

        # Update user activity on every message from a non-bot user
        if message.guild:
            await self.activity_db.update_last_message(message.author.id)

        # IMPORTANT: This line is required to process any commands
        await self.process_commands(message)

    async def _prune_inactive_members(self) -> None:
        """Task to prune a configured role from inactive members across all guilds."""
        INACTIVITY_DAYS = 14
        # Dummy values to test
        ROLES_TO_PRUNE: list[int] = [123456789012345678, 987654321098765432]
        print("Running automatic prune check for inactive members...")

        try:
            guild = self.get_guild(PRUNE_GUILD_ID)
            if not guild:
                print(f"Pruning failed: Guild with ID {PRUNE_GUILD_ID} not found.")
                return

            inactive_user_ids = set(await self.activity_db.get_inactive_users(INACTIVITY_DAYS))
            if not inactive_user_ids:
                print("No inactive users found in the database to prune.")
                return

            # Pre-fetch the role objects that exist in the target guild
            prunable_roles = {guild.get_role(role_id) for role_id in ROLES_TO_PRUNE}
            prunable_roles.discard(None)  # Remove None if a role ID wasn't found
            if not prunable_roles:
                print(f"Pruning skipped: None of the configured roles were found in guild '{guild.name}'.")
                return

            total_members_pruned = 0
            # More efficient: Iterate through inactive users and check if they are in the guild
            for user_id in inactive_user_ids:
                member = guild.get_member(user_id)
                if not member:
                    continue  # User is inactive but not in the target guild

                # Find which of the prunable roles the member actually has
                roles_to_remove = [role for role in member.roles if role in prunable_roles]

                if roles_to_remove:
                    try:
                        # Remove all applicable roles at once
                        await member.remove_roles(*roles_to_remove, reason=f"Pruned for {INACTIVITY_DAYS}+ days of inactivity.")
                        role_names = ", ".join(f"'{r.name}'" for r in roles_to_remove)
                        print(f"Pruned {role_names} from {member.display_name}.")
                        total_members_pruned += 1
                    except Forbidden:
                        print(f"Failed to prune {member.display_name}: Missing Permissions.")
                    except HTTPException as e:
                        print(f"Failed to prune {member.display_name}: {e}")

            print(f"Pruning complete. Roles removed from {total_members_pruned} member(s).")

        except Exception as e:  # noqa: BLE001
            print(f"An error occurred during the automatic prune check: {e}")
