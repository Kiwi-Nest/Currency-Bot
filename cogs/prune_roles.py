# cogs/pruner.py
import logging
from discord.ext import commands, tasks
from discord import Forbidden, HTTPException

# It's better to depend on the abstract class/module, not the specific bot type
from modules.ActivityDB import ActivityDB

# Use Python's logging module for better diagnostics in a reusable component
log = logging.getLogger(__name__)


class PrunerCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        activity_db: ActivityDB,
        guild_id: int,
        role_ids_to_prune: list[int],
        inactivity_days: int = 14,
    ):
        self.bot = bot
        self.activity_db = activity_db
        self.guild_id = guild_id
        self.role_ids_to_prune = role_ids_to_prune
        self.inactivity_days = inactivity_days

    # This is a special event that runs when the cog is loaded
    async def cog_load(self) -> None:
        self.prune_loop.start()

    @tasks.loop(hours=24)
    async def prune_loop(self) -> None:
        """The background task that checks for and prunes inactive members."""
        log.info("Running automatic prune check for inactive members...")

        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            log.error(f"Pruning failed: Guild with ID {self.guild_id} not found.")
            return

        # Fetch roles from the guild that are configured for pruning
        prunable_roles = {guild.get_role(role_id) for role_id in self.role_ids_to_prune}
        prunable_roles.discard(None)  # Remove None if a role ID wasn't found
        if not prunable_roles:
            log.warning(f"Pruning skipped: None of the configured roles found in guild '{guild.name}'.")
            return

        # Get inactive user IDs from the database
        inactive_user_ids = await self.activity_db.get_inactive_users(self.inactivity_days)
        if not inactive_user_ids:
            log.info("No inactive users found in the database to prune.")
            return

        total_members_pruned = 0
        for user_id in inactive_user_ids:
            member = guild.get_member(user_id)
            if not member:
                continue  # User is not in the target guild

            # Find which of the prunable roles the member actually has
            roles_to_remove = [role for role in member.roles if role in prunable_roles]

            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason=f"Pruned for {self.inactivity_days}+ days of inactivity.")
                    role_names = ", ".join(f"'{r.name}'" for r in roles_to_remove)
                    log.info(f"Pruned {role_names} from {member.display_name}.")
                    total_members_pruned += 1
                except Forbidden:
                    log.error(f"Failed to prune {member.display_name}: Missing Permissions.")
                except HTTPException as e:
                    log.error(f"Failed to prune {member.display_name}: {e}")

        log.info(f"Pruning complete. Roles removed from {total_members_pruned} member(s).")

    @prune_loop.before_loop
    async def before_prune_loop(self) -> None:
        """Waits until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()


# The setup function that discord.py calls when loading the extension
async def setup(bot: commands.Bot) -> None:
    # This is where another user would configure the cog for their bot.
    # For your specific bot, it would look like this:

    # You should move these into a config file, but for demonstration:
    GUILD_ID = 1328629578096316427
    ROLES_TO_PRUNE = [123456789012345678, 987654321098765432]
    INACTIVITY_DAYS = 14

    pruner_cog = PrunerCog(
        bot=bot,
        activity_db=activity_db,
        guild_id=GUILD_ID,
        role_ids_to_prune=ROLES_TO_PRUNE,
        inactivity_days=INACTIVITY_DAYS,
    )
    await bot.add_cog(pruner_cog)
