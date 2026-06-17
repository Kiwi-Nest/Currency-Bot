from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from modules.Database import snowflake
from modules.dtypes import DISCORD_EPOCH_MS, ChannelId, GuildId, MemberEvent, MessageId, ReconcileResult, UserId

if TYPE_CHECKING:
    from collections.abc import Sequence

    from modules.Database import Database

log = logging.getLogger(__name__)

# Reserved synthetic source ids - satisfy CHECK(> 1_000_000) but are not real Discord snowflakes.
SYNTHETIC_JOIN_SOURCE = UserId(1_000_001)
SYNTHETIC_JOIN_CHANNEL = ChannelId(1_000_002)

# 10 seconds expressed as snowflake delta (ms * 2^22)
_DEDUP_WINDOW = 10_000 << 22


def _dedup_events(
    rows: Sequence[tuple[int, int, int, int | None]],  # (msg_id, bot_id, delta, anchor_count)
    own_bot_id: int | None,
) -> list[tuple[int, int, int | None]]:
    """Collapse same-direction events from multiple bots within a 10s window into one.

    Multiple bots logging the same join/leave produce near-simultaneous rows with
    identical delta. Keep the best: own bot > has anchor_count > earliest snowflake.
    Losing rows get delta=0 and anchor_count=None so they don't skew running counts.

    Edge case - bulk purges: rapid sequential kicks from the same event source also
    produce many events in quick succession. Multiple kicks within 10s of the
    cluster's first snowflake into one instantaneous drop rather than the exact step count.
    This is not noticebale on a graph.
    """
    result: list[tuple[int, int, int | None]] = []
    n = len(rows)
    i = 0
    while i < n:
        msg_id, _, delta, anchor = rows[i]
        cluster = [i]
        j = i + 1
        while j < n:
            nxt_id, _, nxt_delta, _ = rows[j]
            if nxt_delta == delta and (nxt_id - msg_id) <= _DEDUP_WINDOW:
                cluster.append(j)
                j += 1
            else:
                break
        if len(cluster) == 1:
            result.append((msg_id, delta, anchor))
        else:
            winner = min(
                cluster,
                key=lambda idx: (rows[idx][1] != own_bot_id, rows[idx][3] is None, rows[idx][0]),
            )
            for idx in cluster:
                m, _, d, ac = rows[idx]
                result.append((m, d if idx == winner else 0, ac if idx == winner else None))
        i = j
    return result


def _compute_counts(rows: Sequence[tuple[int, int, int | None]]) -> tuple[list[int], int]:
    """Return (member_count per row, max_drift) from (message_id, delta, anchor_count) rows."""
    counts = [0] * len(rows)
    running = 0
    max_drift = 0
    first_anchor: int | None = None
    first_anchor_count: int = 0

    for i, (_, delta, anchor_count) in enumerate(rows):
        if anchor_count is not None:
            if first_anchor is not None:
                max_drift = max(max_drift, abs(anchor_count - running))
            else:
                first_anchor = i
                first_anchor_count = anchor_count
            running = anchor_count
        running += delta
        counts[i] = running

    if first_anchor is not None and first_anchor > 0:
        prev_before = first_anchor_count
        for i in range(first_anchor - 1, -1, -1):
            counts[i] = prev_before
            prev_before -= rows[i][1]

    return counts, max_drift


class MemberCountDB:
    TABLE_EVENTS = "member_count_events"

    def __init__(self, database: Database) -> None:
        self.database = database

    async def post_init(self) -> None:
        async with self.database.get_conn() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_EVENTS} (
                    messageID    INTEGER NOT NULL {snowflake("messageID")},
                    guildID      INTEGER NOT NULL {snowflake("guildID")},
                    channelID    INTEGER NOT NULL {snowflake("channelID")},
                    botID        INTEGER NOT NULL {snowflake("botID")},
                    delta        INTEGER NOT NULL DEFAULT 0,
                    anchor_count INTEGER CHECK(anchor_count IS NULL OR anchor_count >= 0),
                    member_count INTEGER,
                    PRIMARY KEY (messageID)
                ) STRICT, WITHOUT ROWID
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_mce_guild_msg
                ON {self.TABLE_EVENTS}(guildID, messageID)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_mce_chan_msg
                ON {self.TABLE_EVENTS}(guildID, channelID, messageID)
            """)
            await conn.commit()
        log.info("Initialized %s table.", self.TABLE_EVENTS)

    async def upsert_events(self, events: list[MemberEvent]) -> int:
        if not events:
            return 0
        async with self.database.get_conn() as conn:
            cursor = await conn.executemany(
                f"""
                INSERT INTO {self.TABLE_EVENTS} (messageID, guildID, channelID, botID, delta, anchor_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(messageID) DO UPDATE SET
                    delta        = excluded.delta,
                    anchor_count = excluded.anchor_count
                """,  # noqa: S608
                [(e.message_id, e.guild_id, e.channel_id, e.bot_id, e.delta, e.anchor_count) for e in events],
            )
            await conn.commit()
        return cursor.rowcount

    async def synced_id_range(self, guild_id: GuildId, channel_id: ChannelId) -> tuple[MessageId, MessageId] | None:
        """Return (min, max) known message IDs for a channel, or None if unsynced."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"SELECT MIN(messageID), MAX(messageID) FROM {self.TABLE_EVENTS} WHERE guildID = ? AND channelID = ?",  # noqa: S608
                (guild_id, channel_id),
            )
            row = await cursor.fetchone()
        if not row or row[0] is None:
            return None
        return MessageId(row[0]), MessageId(row[1])

    async def reconcile(self, guild_id: GuildId, own_bot_id: UserId | None = None) -> ReconcileResult:
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"SELECT messageID, botID, delta, anchor_count FROM {self.TABLE_EVENTS} WHERE guildID = ? ORDER BY messageID",  # noqa: S608
                (guild_id,),
            )
            rows = await cursor.fetchall()

        deduped = _dedup_events(rows, own_bot_id)
        counts, max_drift = _compute_counts(deduped)
        updates = [(c, r[0]) for c, r in zip(counts, rows, strict=False)]

        if updates:
            async with self.database.get_conn() as conn:
                await conn.executemany(
                    f"UPDATE {self.TABLE_EVENTS} SET member_count = ? WHERE messageID = ?",  # noqa: S608
                    updates,
                )
                await conn.commit()

        return ReconcileResult(
            rows_updated=len(updates),
            max_drift=max_drift,
            current_count=counts[-1] if counts else 0,
        )

    async def history(
        self,
        guild_id: GuildId,
        channel_id: ChannelId | None = None,
        start: MessageId | None = None,
        end: MessageId | None = None,
    ) -> list[tuple[int, int]]:
        clauses = ["guildID = ?"]
        params: list[object] = [guild_id]
        if channel_id is not None:
            clauses.append("channelID = ?")
            params.append(channel_id)
        if start is not None:
            clauses.append("messageID >= ?")
            params.append(start)
        if end is not None:
            clauses.append("messageID <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"SELECT messageID, member_count FROM {self.TABLE_EVENTS} WHERE {where} AND member_count IS NOT NULL ORDER BY messageID",  # noqa: S608, E501
                params,
            )
            rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    async def sync_member_joins(self, guild_id: GuildId, members: list[tuple[UserId, int]]) -> int:
        """Upsert a +1 synthetic event per member. Idempotent; returns events written."""
        events = [
            MemberEvent(
                message_id=MessageId(((ts - DISCORD_EPOCH_MS) << 22) | (uid & 0x3FFFFF)),
                guild_id=guild_id,
                channel_id=SYNTHETIC_JOIN_CHANNEL,
                bot_id=SYNTHETIC_JOIN_SOURCE,
                delta=1,
                anchor_count=None,
            )
            for uid, ts in members
        ]
        return await self.upsert_events(events)

    async def synced_channels(self, guild_id: GuildId) -> list[tuple[ChannelId, MessageId]]:
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"SELECT channelID, MAX(messageID) FROM {self.TABLE_EVENTS}"  # noqa: S608
                " WHERE guildID = ? AND channelID != ? GROUP BY channelID",
                (guild_id, SYNTHETIC_JOIN_CHANNEL),
            )
            rows = await cursor.fetchall()
        return [(ChannelId(row[0]), MessageId(row[1])) for row in rows]
