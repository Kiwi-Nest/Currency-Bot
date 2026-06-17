import asyncio
import contextlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from modules.discord_search import fetch_author_stats
from modules.dtypes import GuildId, GuildInteraction, Member, UserId
from modules.guild_cog import GuildOnlyHybridCog
from modules.result import Err, Ok

if TYPE_CHECKING:
    from modules.BotCore import BotCore
    from modules.UserDB import UserDB


log = logging.getLogger(__name__)


@commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.cooldown(2, 60.0, key=lambda i: i.guild_id)
class AdminActivity(
    GuildOnlyHybridCog,
    commands.GroupCog,
    group_name="activity",
    group_description="Admin activity management",
):
    def __init__(self, bot: BotCore, *, user_db: UserDB) -> None:
        self.bot = bot
        self.user_db = user_db
        super().__init__()
        self.startup_backfill.start()

    async def cog_unload(self) -> None:
        self.startup_backfill.cancel()

    async def _backfill_guild(self, guild: discord.Guild) -> tuple[int, int, int, int]:
        """Backfill untracked members in a guild. Returns (known, updated, skipped, failed)."""
        guild_id = GuildId(guild.id)
        known_ids = set(await self.user_db.get_all_users(guild_id))
        missing = [m for m in guild.members if not m.bot and UserId(m.id) not in known_ids]

        updated = 0
        failed = 0

        for member in missing:
            user_id = UserId(member.id)
            match await fetch_author_stats(self.bot.http_session, guild_id, user_id):
                case Ok((_, ts)):
                    resolved_epoch: int | None = None
                    if ts:
                        with contextlib.suppress(ValueError):
                            resolved_epoch = int(datetime.fromisoformat(ts).timestamp())
                    elif member.joined_at:
                        resolved_epoch = int(member.joined_at.timestamp())
                    if resolved_epoch is not None:
                        await self.user_db.set_last_active(Member(user_id, guild_id), resolved_epoch)
                        updated += 1
                case Err(e):
                    log.warning("Backfill fetch failed for %s in %s: %s", user_id, guild_id, e)
                    failed += 1

        skipped = len(missing) - updated - failed
        return len(known_ids), updated, skipped, failed

    @tasks.loop(count=1)
    async def startup_backfill(self) -> None:
        log.info("Starting startup backfill across %d guild(s)", len(self.bot.guilds))
        for guild in self.bot.guilds:
            known, updated, skipped, failed = await self._backfill_guild(guild)
            log.info(
                "Startup backfill guild %s: known=%d updated=%d skipped=%d failed=%d",
                guild.id,
                known,
                updated,
                skipped,
                failed,
            )

    @startup_backfill.before_loop
    async def before_startup_backfill(self) -> None:
        await self.bot.wait_until_ready()
        await asyncio.sleep(600)

    @app_commands.command(  # ty: ignore[invalid-argument-type]
        name="backfill",
        description="Backfill last-activity timestamps for guild members not yet in the database.",
    )
    async def backfill(self, interaction: GuildInteraction) -> None:
        await interaction.response.defer(ephemeral=True)

        known, updated, skipped, failed = await self._backfill_guild(interaction.guild)

        await interaction.followup.send(
            f"Backfill complete. {known} already tracked. "
            f"Of {updated + skipped + failed} untracked: updated {updated}, no data {skipped}, errors {failed}.",
            ephemeral=True,
        )

    @app_commands.command(  # ty: ignore[invalid-argument-type]
        name="status",
        description="Show how many members need backfilling and how many are prunable.",
    )
    @app_commands.describe(days="Inactivity threshold for the prunable count (default: 90).")
    async def status(
        self,
        interaction: GuildInteraction,
        days: app_commands.Range[int, 1, 3650] = 90,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id = GuildId(interaction.guild.id)
        human_ids = {UserId(m.id) for m in interaction.guild.members if not m.bot}

        known_ids = set(await self.user_db.get_all_users(guild_id))
        untracked_ids = human_ids - known_ids
        untracked = len(untracked_ids)
        if untracked_ids:
            member_map = {UserId(m.id): m for m in interaction.guild.members if not m.bot}
            for uid in untracked_ids:
                m = member_map.get(uid)
                log.info(
                    "Untracked member: id=%s name=%s joined=%s",
                    uid,
                    m.name if m else "?",
                    m.joined_at.isoformat() if m and m.joined_at else "unknown",
                )

        inactive = set(await self.user_db.get_inactive_users(guild_id, days))
        departed = inactive - human_ids
        prunable = len(departed)

        if departed:
            timestamps = await self.user_db.get_users_last_active(guild_id, departed)
            for uid, last_active in timestamps:
                log.info(
                    "Departed member: id=%s last_active=%s",
                    uid,
                    last_active,
                )

        await interaction.followup.send(
            f"{untracked} member(s) have no activity record (backfill candidates). "
            f"{prunable} departed member(s) inactive for >{days} days (prunable).",
            ephemeral=True,
        )

    @app_commands.command(  # ty: ignore[invalid-argument-type]
        name="prune",
        description="Delete DB records for users inactive longer than N days who have left the server.",
    )
    @app_commands.describe(days="Inactivity threshold in days (e.g. 90).")
    async def prune(
        self,
        interaction: GuildInteraction,
        days: app_commands.Range[int, 1, 3650],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id = GuildId(interaction.guild.id)

        inactive = set(await self.user_db.get_inactive_users(guild_id, days))
        member_ids = {UserId(m.id) for m in interaction.guild.members if not m.bot}
        to_delete = list(inactive - member_ids)

        if not to_delete:
            await interaction.followup.send(
                f"No departed users inactive for more than {days} days.",
                ephemeral=True,
            )
            return

        deleted = await self.user_db.delete_users(guild_id, to_delete)
        await interaction.followup.send(
            f"Pruned {deleted} user(s) inactive for >{days} days who are no longer in the server.",
            ephemeral=True,
        )


async def setup(bot: BotCore) -> None:
    await bot.add_cog(AdminActivity(bot, user_db=bot.user_db))
