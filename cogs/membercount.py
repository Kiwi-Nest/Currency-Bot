from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands

from modules import membercount_graph
from modules.dtypes import DISCORD_EPOCH_MS, ChannelId, GuildId, GuildInteraction, MemberEvent, MessageId, UserId
from modules.exceptions import UserError
from modules.guild_cog import GuildOnlyHybridCog
from modules.membercount_parsers import parse_embed

if TYPE_CHECKING:
    from modules.BotCore import BotCore
    from modules.ConfigDB import ConfigDB
    from modules.MemberCountDB import MemberCountDB

log = logging.getLogger(__name__)

_LOOKBACK_BUDGET = 500


def _snowflake_to_dt(message_id: int) -> datetime:
    ms = (message_id >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _date_to_snowflake(d: date, tz: ZoneInfo) -> MessageId:
    dt = datetime(d.year, d.month, d.day, tzinfo=tz)
    ms = int(dt.timestamp() * 1000) - DISCORD_EPOCH_MS
    return MessageId(max(ms, 0) << 22)


def _parse_message(msg: discord.Message, guild_id: GuildId, channel_id: ChannelId) -> MemberEvent | None:
    if msg.type is not discord.MessageType.default or not msg.author.bot or not msg.embeds:
        return None

    for embed in msg.embeds:
        # TODO: latent bug multiple embeds can exist
        parsed = parse_embed(embed.title or "", embed.description or "", embed.footer.text if embed.footer else "")
        if parsed is None:
            continue
        delta, anchor_count = parsed
        return MemberEvent(
            message_id=MessageId(msg.id),
            guild_id=guild_id,
            channel_id=channel_id,
            bot_id=UserId(msg.author.id),
            delta=delta,
            anchor_count=anchor_count,
        )

    return None


def _quantize(rows: list[tuple[int, int]], tz: ZoneInfo) -> list[tuple[datetime, int]]:
    times = [_snowflake_to_dt(mid).astimezone(tz) for mid, _ in rows]
    counts = [c for _, c in rows]
    if len(rows) == 1:
        return [(times[0], counts[0])] * 10
    t0, t1 = times[0], times[-1]
    bin_s = (t1 - t0).total_seconds() / 10
    bins: list[int | None] = [None] * 10
    for t, c in zip(times, counts, strict=False):
        bins[min(int((t - t0).total_seconds() / bin_s), 9)] = c
    carry = counts[0]
    result: list[tuple[datetime, int]] = []
    for i, v in enumerate(bins):
        carry = v if v is not None else carry
        result.append((t0 + timedelta(seconds=bin_s * i), carry))
    return result


class MemberCount(GuildOnlyHybridCog):
    membercount_group = app_commands.Group(
        name="membercount",
        description="Member count history tools",
    )

    def __init__(self, bot: BotCore, *, member_count_db: MemberCountDB, config_db: ConfigDB) -> None:
        self.bot = bot
        self.member_count_db = member_count_db
        self.config_db = config_db

    async def _guild_tz(self, guild_id: GuildId) -> ZoneInfo:
        config = await self.config_db.get_guild_config(guild_id)
        if config.guild_timezone:
            try:
                return ZoneInfo(config.guild_timezone)
            except ZoneInfoNotFoundError:
                log.warning("Unrecognised guild_timezone %r for guild %s", config.guild_timezone, guild_id)
        return self.bot.config.daily_timezone

    @membercount_group.command(name="sync", description="Sync member count events from a log channel.")  # ty: ignore[invalid-argument-type]
    @app_commands.describe(
        channel="The join/leave log channel (defaults to current channel)",
        full="Backfill all history instead of only fetching new messages",
    )
    async def sync(
        self,
        interaction: GuildInteraction,
        channel: discord.TextChannel | None = None,
        full: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            msg = "This command must be used in or targeted at a text channel."
            raise UserError(msg)

        guild_id = GuildId(interaction.guild.id)
        channel_id = ChannelId(target.id)

        events: list[MemberEvent] = []
        scanned = 0
        lookback_scanned = 0

        if full or (id_range := await self.member_count_db.synced_id_range(guild_id, channel_id)) is None:
            async for msg in target.history(limit=None, after=None, oldest_first=True):
                scanned += 1
                if event := _parse_message(msg, guild_id, channel_id):
                    events.append(event)
        else:
            min_id, max_id = id_range
            async for msg in target.history(limit=None, after=discord.Object(max_id), oldest_first=True):
                scanned += 1
                if event := _parse_message(msg, guild_id, channel_id):
                    events.append(event)
            budget = _LOOKBACK_BUDGET
            async for msg in target.history(limit=None, before=discord.Object(min_id), oldest_first=False):
                lookback_scanned += 1
                if event := _parse_message(msg, guild_id, channel_id):
                    events.append(event)
                else:
                    budget -= 1
                    if budget <= 0:
                        break

        inserted = await self.member_count_db.upsert_events(events)
        own_bot_id = UserId(self.bot.user.id) if self.bot.user else None
        result = await self.member_count_db.reconcile(guild_id, own_bot_id)

        embed = discord.Embed(
            title="Member Count Sync",
            colour=discord.Colour.green() if result.max_drift == 0 else discord.Colour.orange(),
            timestamp=datetime.now(UTC),
        )
        embed.add_field(name="Messages scanned", value=str(scanned), inline=True)
        if lookback_scanned:
            embed.add_field(name="Lookback scanned", value=str(lookback_scanned), inline=True)
        embed.add_field(name="Events upserted", value=str(inserted), inline=True)
        embed.add_field(name="Current count", value=str(result.current_count), inline=True)
        if result.max_drift > 0:
            embed.add_field(
                name="⚠ Max drift",
                value=f"{result.max_drift} (missed log messages detected)",
                inline=False,
            )
        embed.set_footer(text=f"Channel: #{target.name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @membercount_group.command(name="history", description="Show member count history as a chart.")  # ty: ignore[invalid-argument-type]
    @app_commands.describe(
        channel="Filter to a specific channel",
        start="Start date (YYYY-MM-DD)",
        end="End date (YYYY-MM-DD)",
    )
    async def history(
        self,
        interaction: GuildInteraction,
        channel: discord.TextChannel | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=False)

        guild_id = GuildId(interaction.guild.id)
        channel_id = ChannelId(channel.id) if channel else None
        tz = await self._guild_tz(guild_id)

        start_id: MessageId | None = None
        end_id: MessageId | None = None

        if start:
            try:
                start_id = _date_to_snowflake(date.fromisoformat(start), tz)
            except ValueError as exc:
                msg = f"Invalid start date {start!r}. Use YYYY-MM-DD."
                raise UserError(msg) from exc

        if end:
            try:
                end_id = MessageId(_date_to_snowflake(date.fromisoformat(end) + timedelta(days=1), tz) - 1)
            except ValueError as exc:
                msg = f"Invalid end date {end!r}. Use YYYY-MM-DD."
                raise UserError(msg) from exc

        rows = await self.member_count_db.history(guild_id, channel_id, start_id, end_id)

        if not rows:
            await interaction.followup.send("No history found for the given filters.", ephemeral=False)
            return

        title = "Member Count - " + (f"#{channel.name}" if channel else interaction.guild.name)

        if membercount_graph.AVAILABLE:
            points = [(_snowflake_to_dt(mid).astimezone(tz), count) for mid, count in rows]
            buf = membercount_graph.create_member_count_graph(points, title)
            await interaction.followup.send(file=discord.File(buf, filename="membercount.png"), ephemeral=False)
        else:
            lines = [f"`{dt.strftime('%Y-%m-%d %H:%M')}` → **{count}**" for dt, count in _quantize(rows, tz)]
            embed = discord.Embed(title=title, description="\n".join(lines), colour=discord.Colour.blurple())
            await interaction.followup.send(embed=embed, ephemeral=False)

    @membercount_group.command(name="channels", description="List channels with synced member count data.")  # ty: ignore[invalid-argument-type]
    async def channels(self, interaction: GuildInteraction) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id = GuildId(interaction.guild.id)
        synced = await self.member_count_db.synced_channels(guild_id)

        if not synced:
            await interaction.followup.send("No channels have been synced yet. Use `/membercount sync`.", ephemeral=True)
            return

        tz = await self._guild_tz(guild_id)
        lines = []
        for ch_id, last_msg_id in synced:
            ch = interaction.guild.get_channel(int(ch_id))
            ch_name = f"#{ch.name}" if ch else f"<#{ch_id}>"
            last_dt = _snowflake_to_dt(last_msg_id).astimezone(tz)
            lines.append(f"{ch_name} - last synced `{last_dt.strftime('%Y-%m-%d %H:%M')}`")

        embed = discord.Embed(
            title="Synced Channels",
            description="\n".join(lines),
            colour=discord.Colour.blurple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: BotCore) -> None:
    await bot.add_cog(MemberCount(bot, member_count_db=bot.member_count_db, config_db=bot.config_db))
