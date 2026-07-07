from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands, tasks

from modules import heatmap as _heatmap
from modules.dtypes import GuildId, GuildInteraction, Member, UserId
from modules.guild_cog import GuildOnlyHybridCog
from modules.vc_color import streak_color

if TYPE_CHECKING:
    from modules.BotCore import BotCore
    from modules.ConfigDB import ConfigDB
    from modules.UserDB import UserDB
    from modules.VoiceChatDB import VoiceChatDB

log = logging.getLogger(__name__)


def _parse_date(value: str) -> date | None:
    try:
        d = date.fromisoformat(value)
    except ValueError:
        return None
    return d if d.isoformat() == value else None


@dataclass
class GuildStreak:
    started_at: datetime
    peak: int
    participants: set[UserId] = field(default_factory=set)


def _fmt_duration(d: timedelta) -> str:
    total = int(d.total_seconds())
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h} {'hour' if h == 1 else 'hours'}")
    if m:
        parts.append(f"{m} {'minute' if m == 1 else 'minutes'}")
    if s or not parts:
        parts.append(f"{s} {'second' if s == 1 else 'seconds'}")
    return ", ".join(parts)


def _build_activity_embed(duration: timedelta, peak: int, unique_count: int, started_at: datetime) -> discord.Embed:
    r, g, b = streak_color(duration)
    colour_hex = f"#{r:02X}{g:02X}{b:02X}"
    started_unix = int(started_at.timestamp())
    embed = discord.Embed(
        title=f"Ended at {_fmt_duration(duration)}",
        description=f"Streak started on <t:{started_unix}:F>.",
        colour=discord.Colour.from_rgb(r, g, b),
        timestamp=datetime.now(UTC),
    )
    embed.add_field(name="Peak Count", value=f"`{peak} user(s)`", inline=True)
    embed.add_field(name="Unique Users", value=f"`{unique_count} user(s)`", inline=True)
    embed.add_field(name="Final Colour", value=f"`{colour_hex}`", inline=True)
    embed.set_footer(text="Voice Activity")
    return embed


class VoiceChatLogger(GuildOnlyHybridCog):
    def __init__(self, bot: BotCore, *, voicechat_db: VoiceChatDB, config_db: ConfigDB, user_db: UserDB) -> None:
        self.bot = bot
        self.voicechat_db = voicechat_db
        self.config_db = config_db
        self.user_db = user_db
        self._streaks: dict[GuildId, GuildStreak] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._flush.start()

    async def _guild_tz(self, guild_id: GuildId) -> ZoneInfo:
        config = await self.config_db.get_guild_config(guild_id)
        if config.guild_timezone:
            try:
                return ZoneInfo(config.guild_timezone)
            except ZoneInfoNotFoundError:
                log.warning("Unrecognised guild_timezone %r for guild %s, falling back", config.guild_timezone, guild_id)
        return self.bot.config.daily_timezone

    async def _resolve_tz(self, user_id: UserId, guild_id: GuildId) -> ZoneInfo:
        if tz := await self.user_db.get_timezone(Member(user_id, guild_id)):
            return tz
        return await self._guild_tz(guild_id)

    async def cog_unload(self) -> None:
        self._flush.cancel()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        was_in_vc = before.channel is not None
        is_in_vc = after.channel is not None
        if was_in_vc == is_in_vc:
            return

        guild_id = GuildId(member.guild.id)
        user_id = UserId(member.id)

        if is_in_vc:
            await self.voicechat_db.record_join(guild_id, user_id)
        else:
            await self.voicechat_db.record_leave(guild_id, user_id)

        live_count = sum(1 for vc in member.guild.voice_channels for m in vc.members if not m.bot)
        if live_count > 0:
            await self.voicechat_db.write_slot_snapshot(guild_id, live_count)

        now = datetime.now(UTC)

        if is_in_vc:
            if guild_id not in self._streaks:
                self._streaks[guild_id] = GuildStreak(started_at=now, peak=live_count, participants={user_id})
            else:
                streak = self._streaks[guild_id]
                streak.participants.add(user_id)
                streak.peak = max(streak.peak, live_count)
        elif live_count == 0 and guild_id in self._streaks:
            streak = self._streaks.pop(guild_id)
            task = asyncio.create_task(self._on_vc_death(member.guild, streak, now))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _on_vc_death(self, guild: discord.Guild, streak: GuildStreak, ended_at: datetime) -> None:
        duration = ended_at - streak.started_at
        if duration < timedelta(seconds=60):
            return
        config = await self.config_db.get_guild_config(GuildId(guild.id))
        if not config.vc_activity_channel_id:
            return
        channel = guild.get_channel(config.vc_activity_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        if streak.peak < 2:
            return
        unique = len(streak.participants)
        embed = _build_activity_embed(duration, streak.peak, unique, streak.started_at)
        files: list[discord.File] = []
        if _heatmap.AVAILABLE:
            guild_tz = await self._guild_tz(GuildId(guild.id))
            rows = await self.voicechat_db.read_heatmap_data(GuildId(guild.id), guild_tz)
            if rows:
                buf = await asyncio.to_thread(_heatmap.create_heatmap, rows, "VC Activity")
                files.append(discord.File(buf, filename="vcheatmap.png"))
                embed.set_image(url="attachment://vcheatmap.png")
        try:
            await channel.send(embed=embed, files=files)
        except discord.HTTPException:
            log.exception("Failed to post VC activity report for guild %s", guild.id)

    @tasks.loop(seconds=60)
    async def _flush(self) -> None:
        for guild in self.bot.guilds:
            guild_id = GuildId(guild.id)
            live_count = sum(1 for vc in guild.voice_channels for m in vc.members if not m.bot)
            streak = self._streaks.get(guild_id)
            if live_count == 0 and streak is None:
                continue
            if live_count > 0:
                await self.voicechat_db.write_slot_snapshot(guild_id, live_count)
            if streak is None:
                continue
            config = await self.config_db.get_guild_config(guild_id)
            if not config.vc_rgb_role_id:
                continue
            role = guild.get_role(config.vc_rgb_role_id)
            if role is None or not role.members:
                continue
            try:
                r, g, b = streak_color(datetime.now(UTC) - streak.started_at)
                if role.colour.to_rgb() == (r, g, b):
                    continue
                await role.edit(colour=discord.Colour.from_rgb(r, g, b))
            except Exception:
                log.exception("Failed to update RGB role for guild %s", guild_id)

    @_flush.before_loop
    async def _before_flush(self) -> None:
        await self.bot.wait_until_ready()

        now = datetime.now(UTC)

        for guild in self.bot.guilds:
            guild_id = GuildId(guild.id)
            current = {UserId(m.id) for vc in guild.voice_channels for m in vc.members if not m.bot}
            await self.voicechat_db.reconcile_sessions(guild_id, current)

            if not current:
                continue

            result = await self.voicechat_db.infer_streak(guild_id)
            if result is None:
                self._streaks[guild_id] = GuildStreak(
                    started_at=now,
                    peak=len(current),
                    participants=set(current),
                )
            else:
                started_ts, peak = result
                started_at = datetime.fromtimestamp(started_ts, UTC)
                raw_participants = await self.voicechat_db.get_streak_participants(guild_id, started_ts)
                self._streaks[guild_id] = GuildStreak(
                    started_at=started_at,
                    peak=max(peak, len(current)),
                    participants={UserId(uid) for uid in raw_participants} | current,
                )

    @app_commands.command(name="vcinfo", description="Voice channel activity for this guild or a specific user.")  # ty: ignore[invalid-argument-type]
    async def vcinfo(self, interaction: GuildInteraction, user: discord.Member | None = None) -> None:
        await interaction.response.defer(ephemeral=False)
        guild_id = GuildId(interaction.guild.id)

        if user is None:
            guild_tz = await self._guild_tz(guild_id)
            today = datetime.now(guild_tz).date()
            local_midnight_ts = int(datetime.combine(today, time.min, guild_tz).timestamp())
            next_midnight_ts = int(datetime.combine(today + timedelta(days=1), time.min, guild_tz).timestamp())
            peak = await self.voicechat_db.guild_peak_today(guild_id, local_midnight_ts, next_midnight_ts)
            live_count = sum(1 for vc in interaction.guild.voice_channels for m in vc.members if not m.bot)
            embed = discord.Embed(title="VC Activity", color=discord.Color.blurple())
            if peak:
                max_count, slot_offset = peak
                peak_unix = local_midnight_ts + slot_offset * 300
                embed.add_field(name="Peak today", value=f"{max_count} users at <t:{peak_unix}:t>", inline=False)
            else:
                embed.add_field(name="Peak today", value="No data yet", inline=False)
            embed.add_field(name="Currently live", value=str(live_count), inline=False)
            streak = self._streaks.get(guild_id)
            if streak:
                now = datetime.now(UTC)
                embed.add_field(name="Streak duration", value=_fmt_duration(now - streak.started_at), inline=True)
                embed.add_field(name="Peak count", value=f"{streak.peak} user(s)", inline=True)
                embed.add_field(name="Unique users", value=f"{len(streak.participants)} user(s)", inline=True)
        else:
            uid = UserId(user.id)
            user_tz = await self._resolve_tz(uid, guild_id)
            day_start_unix = int(datetime.combine(datetime.now(user_tz).date(), time.min, user_tz).timestamp())
            (minutes_today, _), (minutes_7d, _), (minutes_30d, last_seen_ts) = await asyncio.gather(
                self.voicechat_db.user_stats_today(guild_id, uid, day_start_unix),
                self.voicechat_db.user_stats_period(guild_id, uid, 7),
                self.voicechat_db.user_stats_period(guild_id, uid, 30),
            )
            last_seen = f"<t:{last_seen_ts}:f>" if last_seen_ts else "Never"
            embed = discord.Embed(title=f"VC Activity - {user.display_name}", color=discord.Color.blurple())
            embed.add_field(name="Today", value=f"{minutes_today} min", inline=True)
            embed.add_field(name="Last 7 days", value=f"{minutes_7d} min", inline=True)
            embed.add_field(name="Last 30 days", value=f"{minutes_30d} min", inline=True)
            embed.add_field(name="Last seen", value=last_seen, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(name="vcheatmap", description="VC activity heatmap for this guild.")  # ty: ignore[invalid-argument-type]
    @app_commands.describe(
        start="Start date (YYYY-MM-DD), inclusive. Defaults to all time.",
        end="End date (YYYY-MM-DD), inclusive. Defaults to today.",
    )
    async def vcheatmap(
        self,
        interaction: GuildInteraction,
        start: str | None = None,
        end: str | None = None,
    ) -> None:
        if not _heatmap.AVAILABLE:
            await interaction.response.send_message("Heatmap unavailable (matplotlib not installed).", ephemeral=True)
            return

        guild_id = GuildId(interaction.guild.id)
        guild_tz = await self._guild_tz(guild_id)
        today = datetime.now(guild_tz).date().isoformat()

        if start is not None and _parse_date(start) is None:
            await interaction.response.send_message(
                f"Invalid start date `{start}`. Use YYYY-MM-DD, e.g. `{today}`.",
                ephemeral=True,
            )
            return

        if end is not None:
            if _parse_date(end) is None:
                await interaction.response.send_message(
                    f"Invalid end date `{end}`. Use YYYY-MM-DD, e.g. `{today}`.",
                    ephemeral=True,
                )
                return
            end = min(end, today)

        if start is not None and end is not None and start > end:
            await interaction.response.send_message("Start date must be on or before end date.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        rows = await self.voicechat_db.read_heatmap_data(guild_id, guild_tz, start=start, end=end)
        if not rows:
            msg = "No data for that date range." if (start or end) else "No data yet."
            await interaction.followup.send(msg, ephemeral=True)
            return

        if start or end:
            lo = start or rows[0][0]
            hi = end or rows[-1][0]
            title = f"VC Activity ({lo} - {hi})"
        else:
            title = "VC Activity"

        buf = await asyncio.to_thread(_heatmap.create_heatmap, rows, title)
        await interaction.followup.send(file=discord.File(buf, filename="vcheatmap.png"), ephemeral=False)


async def setup(bot: BotCore) -> None:
    await bot.add_cog(VoiceChatLogger(bot, voicechat_db=bot.voicechat_db, config_db=bot.config_db, user_db=bot.user_db))
