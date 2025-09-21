import logging
import os

import discord
from discord import Forbidden, HTTPException
from discord.ext import commands, tasks

from modules.UserDB import UserDB

# Use Python's logging module for better diagnostics in a reusable component
log = logging.getLogger(__name__)


class PrunerCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        user_db: UserDB,
        guild_id: int,
        role_ids_to_prune: list[int],
        inactivity_days: int = 14,
    ) -> None:
        self.bot = bot
        self.user_db = user_db
        self.guild_id = guild_id
        self.role_ids_to_prune = role_ids_to_prune
        self.inactivity_days = inactivity_days

    # This is a special event that runs when the cog is loaded
    async def cog_load(self) -> None:
        self.prune_loop.start()

    async def cog_unload(self) -> None:
        """Clean up when the cog is unloaded."""
        self.prune_loop.cancel()

    @tasks.loop(hours=1)
    async def prune_loop(self) -> None:
        """Check for and prune inactive members."""
        log.info("Running automatic prune check for inactive members...")

        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            log.error("Pruning failed: Guild with ID %s not found.", self.guild_id)
            return

        # Fetch roles from the guild that are configured for pruning
        prunable_roles = {guild.get_role(role_id) for role_id in self.role_ids_to_prune}
        prunable_roles.discard(None)  # Remove None if a role ID wasn't found
        if not prunable_roles:
            log.warning("Pruning skipped: None of the configured roles found in guild '%s'.", guild.name)
            return

        # Get inactive user IDs from the database
        inactive_user_ids = await self.user_db.get_inactive_users(self.inactivity_days)
        if not inactive_user_ids:
            log.info("No inactive users found in the database to prune.")
            return

        total_members_pruned = 0
        for user_id in inactive_user_ids:
            try:
                # Use fetch_member instead of get_member to ensure we get the member
                # even if they're not in the bot's cache
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                continue  # User is no longer in the guild, skip them
            except discord.HTTPException:
                log.exception("Failed to fetch member %s", user_id)
                continue

            if not member:
                continue  # User is not in the target guild

            # Find which of the prunable roles the member actually has
            roles_to_remove = [role for role in member.roles if role in prunable_roles]

            # Also add any roles that start with "Gradient: " prefix
            gradient_roles = [role for role in member.roles if role.name.startswith("Gradient: ")]
            roles_to_remove.extend(gradient_roles)

            # Remove duplicates in case a gradient role was already in prunable_roles
            roles_to_remove = list(set(roles_to_remove))

            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason=f"Pruned for {self.inactivity_days}+ days of inactivity.")
                    role_names = ", ".join(f"'{r.name}'" for r in roles_to_remove)
                    log.info("Pruned %s from %s.", role_names, member.display_name)
                    total_members_pruned += 1
                except Forbidden:
                    log.exception("Failed to prune %s: Missing Permissions.", member.display_name)
                except HTTPException:
                    log.exception("Failed to prune %s", member.display_name)

        log.info("Pruning complete. Roles removed from %s member(s).", total_members_pruned)

    @prune_loop.before_loop
    async def before_prune_loop(self) -> None:
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()


# The setup function that discord.py calls when loading the extension
async def setup(bot: commands.Bot) -> None:
    GUILD_ID = int(os.getenv("GUILD_ID"))
    ROLES_TO_PRUNE = [int(role_id) for role_id in os.getenv("ROLES_TO_PRUNE").split(",")]
    INACTIVITY_DAYS = int(os.getenv("INACTIVITY_DAYS", "14"))

    # The cog needs the UserDB instance from the bot
    user_db = getattr(bot, "user_db", None)
    if not user_db:
        msg = "Bot is missing the 'user_db' attribute."
        raise RuntimeError(msg)

    pruner_cog = PrunerCog(
        bot=bot,
        user_db=user_db,
        guild_id=GUILD_ID,
        role_ids_to_prune=ROLES_TO_PRUNE,
        inactivity_days=INACTIVITY_DAYS,
    )
    await bot.add_cog(pruner_cog)
