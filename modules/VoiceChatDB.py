from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from modules.Database import snowflake
from modules.dtypes import UserVoiceStats

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    import aiosqlite

    from modules.Database import Database
    from modules.dtypes import GuildId, UserId

log = logging.getLogger(__name__)


class VoiceChatDB:
    TABLE_SLOTS = "vc_slots"
    TABLE_SESSIONS = "vc_sessions"

    def __init__(self, database: Database) -> None:
        self.database = database

    async def post_init(self) -> None:
        async with self.database.get_conn() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_SLOTS} (
                    guildID   INTEGER NOT NULL {snowflake("guildID")},
                    bucket_ts INTEGER NOT NULL CHECK(bucket_ts > 0 AND bucket_ts % 300 = 0),
                    sum_count INTEGER NOT NULL DEFAULT 0 CHECK(sum_count >= 0),
                    n_samples INTEGER NOT NULL DEFAULT 0 CHECK(n_samples >= 0),
                    max_count INTEGER NOT NULL DEFAULT 0 CHECK(max_count >= 0),
                    PRIMARY KEY (guildID, bucket_ts)
                ) STRICT, WITHOUT ROWID
            """)
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_SESSIONS} (
                    guildID   INTEGER NOT NULL {snowflake("guildID")},
                    userID    INTEGER NOT NULL {snowflake("userID")},
                    joined_at INTEGER NOT NULL CHECK(joined_at > 0),
                    left_at   INTEGER CHECK(left_at IS NULL OR left_at >= joined_at),
                    PRIMARY KEY (guildID, userID, joined_at)
                ) STRICT, WITHOUT ROWID
            """)
            await conn.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_vc_open
                ON {self.TABLE_SESSIONS}(guildID, userID) WHERE left_at IS NULL
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_vc_user
                ON {self.TABLE_SESSIONS}(userID, joined_at)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_vc_guild_time
                ON {self.TABLE_SESSIONS}(guildID, joined_at)
            """)
            await conn.commit()

    async def write_slot_snapshot(self, guild_id: GuildId, count: int) -> None:
        try:
            async with self.database.get_conn() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {self.TABLE_SLOTS} (guildID, bucket_ts, sum_count, n_samples, max_count)
                    VALUES (?, (unixepoch() / 300) * 300, ?, 1, ?)
                    ON CONFLICT(guildID, bucket_ts) DO UPDATE SET
                        sum_count = sum_count + excluded.sum_count,
                        n_samples = n_samples + 1,
                        max_count = MAX(max_count, excluded.max_count)
                    """,  # noqa: S608
                    (guild_id, count, count),
                )
                await conn.commit()
        except Exception:
            log.exception("Failed to write VC slot snapshot for guild %s", guild_id)

    async def record_join(self, guild_id: GuildId, user_id: UserId) -> None:
        try:
            async with self.database.get_conn() as conn:
                await conn.execute(
                    f"INSERT OR IGNORE INTO {self.TABLE_SESSIONS} (guildID, userID, joined_at) VALUES (?, ?, unixepoch())",  # noqa: S608
                    (guild_id, user_id),
                )
                await conn.commit()
        except Exception:
            log.exception("Failed to record VC join for user %s guild %s", user_id, guild_id)

    async def record_leave(self, guild_id: GuildId, user_id: UserId) -> None:
        try:
            async with self.database.get_conn() as conn:
                await conn.execute(
                    f"UPDATE {self.TABLE_SESSIONS} SET left_at = unixepoch() WHERE guildID = ? AND userID = ? AND left_at IS NULL",  # noqa: S608, E501
                    (guild_id, user_id),
                )
                await conn.commit()
        except Exception:
            log.exception("Failed to record VC leave for user %s guild %s", user_id, guild_id)

    async def reconcile_sessions(self, guild_id: GuildId, current_user_ids: set[int]) -> None:
        """Close stale open sessions and open sessions for users already in VC."""
        try:
            async with self.database.get_conn() as conn:
                cursor = await conn.execute(
                    f"SELECT userID FROM {self.TABLE_SESSIONS} WHERE guildID = ? AND left_at IS NULL",  # noqa: S608
                    (guild_id,),
                )
                open_rows = await cursor.fetchall()
                open_ids = {row[0] for row in open_rows}

                stale = open_ids - current_user_ids
                if stale:
                    await conn.executemany(
                        f"UPDATE {self.TABLE_SESSIONS} SET left_at = unixepoch() WHERE guildID = ? AND userID = ? AND left_at IS NULL",  # noqa: S608, E501
                        [(guild_id, uid) for uid in stale],
                    )

                new_members = current_user_ids - open_ids
                if new_members:
                    await conn.executemany(
                        f"INSERT OR IGNORE INTO {self.TABLE_SESSIONS} (guildID, userID, joined_at) VALUES (?, ?, unixepoch())",  # noqa: S608
                        [(guild_id, uid) for uid in new_members],
                    )

                await conn.commit()
        except Exception:
            log.exception("Failed to reconcile VC sessions for guild %s", guild_id)

    async def guild_peak_today(self, guild_id: GuildId, local_midnight_ts: int, next_midnight_ts: int) -> tuple[int, int] | None:
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""SELECT max_count, (bucket_ts - ?) / 300
                    FROM {self.TABLE_SLOTS}
                    WHERE guildID = ? AND bucket_ts >= ? AND bucket_ts < ?
                    ORDER BY max_count DESC LIMIT 1""",  # noqa: S608
                (local_midnight_ts, guild_id, local_midnight_ts, next_midnight_ts),
            )
            row = await cursor.fetchone()
            if row:
                return (row[0], row[1])
            return None

    async def user_stats_today(
        self,
        guild_id: GuildId,
        user_id: UserId,
        day_start_unix: int,
    ) -> tuple[int, int | None]:
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT
                    SUM(
                        MIN(COALESCE(left_at, unixepoch()), ? + 86400)
                        - MAX(joined_at, ?)
                    ) / 60,
                    MAX(COALESCE(left_at, joined_at))
                FROM {self.TABLE_SESSIONS}
                WHERE guildID = ? AND userID = ?
                  AND joined_at < ? + 86400
                  AND COALESCE(left_at, unixepoch()) >= ?
                """,  # noqa: S608
                (day_start_unix, day_start_unix, guild_id, user_id, day_start_unix, day_start_unix),
            )
            row = await cursor.fetchone()
            if row and row[0] is not None:
                return (int(row[0]), int(row[1]) if row[1] is not None else None)
            return (0, None)

    async def user_stats_period(
        self,
        guild_id: GuildId,
        user_id: UserId,
        days: int,
    ) -> tuple[int, int | None]:
        """Return (minutes, last_seen_unix) for the past `days` days in this guild."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT
                    SUM(
                        MIN(COALESCE(left_at, unixepoch()), unixepoch())
                        - MAX(joined_at, unixepoch('now', ?))
                    ) / 60,
                    MAX(COALESCE(left_at, joined_at))
                FROM {self.TABLE_SESSIONS}
                WHERE guildID = ? AND userID = ?
                  AND joined_at < unixepoch()
                  AND COALESCE(left_at, unixepoch()) >= unixepoch('now', ?)
                """,  # noqa: S608
                (f"-{days} days", guild_id, user_id, f"-{days} days"),
            )
            row = await cursor.fetchone()
            if row and row[0] is not None:
                return (int(row[0]), int(row[1]) if row[1] is not None else None)
            return (0, None)

    async def get_user_voice_stats(self, user_id: UserId) -> UserVoiceStats:
        async with self.database.get_cursor() as cursor:
            totals_row = await (
                await cursor.execute(
                    f"""
                    SELECT
                        SUM(COALESCE(left_at, unixepoch()) - joined_at) / 60,
                        datetime(MAX(COALESCE(left_at, joined_at)), 'unixepoch')
                    FROM {self.TABLE_SESSIONS} WHERE userID = ?
                    """,  # noqa: S608
                    (user_id,),
                )
            ).fetchone()
            total_minutes: int = int(totals_row[0]) if totals_row and totals_row[0] else 0
            last_seen: str | None = totals_row[1] if totals_row else None

            peak_row = await (
                await cursor.execute(
                    f"""
                    SELECT date(joined_at, 'unixepoch') AS day,
                           SUM(COALESCE(left_at, unixepoch()) - joined_at) AS secs
                    FROM {self.TABLE_SESSIONS} WHERE userID = ?
                    GROUP BY day ORDER BY secs DESC LIMIT 1
                    """,  # noqa: S608
                    (user_id,),
                )
            ).fetchone()
            peak_day: str | None = peak_row[0] if peak_row else None

        return UserVoiceStats(total_minutes=total_minutes, peak_day=peak_day, last_seen=last_seen)

    async def erase_on_conn(self, conn: aiosqlite.Connection, user_id: UserId) -> int:
        cursor = await conn.execute(
            f"DELETE FROM {self.TABLE_SESSIONS} WHERE userID = ?",  # noqa: S608
            (user_id,),
        )
        return cursor.rowcount

    async def delete_old_sessions(self, days: int = 90) -> int:
        async with self.database.get_conn() as conn:
            cursor = await conn.execute(
                f"DELETE FROM {self.TABLE_SESSIONS} WHERE left_at IS NOT NULL AND left_at < unixepoch('now', ?)",  # noqa: S608
                (f"-{days} days",),
            )
            await conn.commit()
            deleted = cursor.rowcount
        log.info("Deleted %d VC sessions older than %d days", deleted, days)
        return deleted

    async def infer_streak(self, guild_id: GuildId) -> tuple[int, int] | None:
        """Return (started_at_unix, peak_concurrent) for the current streak, or None if no open sessions.

        Single sweep-line pass: finds the last gap (concurrent → 0), then the first join after it,
        and computes peak concurrent from that point. Handles bot downtime gaps correctly.
        """
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""
                WITH horizon AS (
                    SELECT MIN(joined_at) AS t
                    FROM {self.TABLE_SESSIONS} WHERE guildID = ? AND left_at IS NULL
                ),
                events AS (
                    SELECT joined_at AS ts, 1 AS d FROM {self.TABLE_SESSIONS}
                    WHERE guildID = ? AND joined_at >= (SELECT t FROM horizon)
                    UNION ALL
                    SELECT left_at AS ts, -1 AS d FROM {self.TABLE_SESSIONS}
                    WHERE guildID = ? AND left_at IS NOT NULL
                      AND left_at >= (SELECT t FROM horizon)
                ),
                sweep AS (
                    SELECT ts, d,
                           SUM(d) OVER (ORDER BY ts ROWS UNBOUNDED PRECEDING) AS n
                    FROM events
                ),
                last_empty AS (SELECT MAX(ts) AS t FROM sweep WHERE n = 0),
                streak_start AS (
                    SELECT CASE
                        WHEN (SELECT t FROM last_empty) IS NOT NULL
                        THEN (SELECT MIN(ts) FROM sweep
                              WHERE ts > (SELECT t FROM last_empty) AND d = 1)
                        ELSE (SELECT MIN(ts) FROM sweep WHERE d = 1)
                    END AS t
                )
                SELECT
                    (SELECT t FROM streak_start) AS started_at,
                    MAX(CASE WHEN ts >= (SELECT t FROM streak_start) THEN n ELSE 0 END) AS peak
                FROM sweep
                """,  # noqa: S608
                (guild_id, guild_id, guild_id),
            )
            row = await cursor.fetchone()
            if row and row[0] is not None:
                return (int(row[0]), int(row[1]) if row[1] is not None else 0)
            return None

    async def get_streak_participants(self, guild_id: GuildId, started_at: int) -> set[int]:
        """All user IDs who were in VC at any point since started_at. Used on restart reconstruction."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT userID FROM {self.TABLE_SESSIONS}
                WHERE guildID = ? AND joined_at >= ?
                  AND (left_at IS NULL OR left_at > ?)
                """,  # noqa: S608
                (guild_id, started_at, started_at),
            )
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    async def read_heatmap_data(
        self,
        guild_id: GuildId,
        tz: ZoneInfo,
        start: str | None = None,
        end: str | None = None,
    ) -> list[tuple[str, int, float]]:
        clauses = ["guildID = ?"]
        params: list[object] = [guild_id]
        if start is not None:
            clauses.append("bucket_ts >= ?")
            params.append(int(datetime.combine(date.fromisoformat(start), time.min, tz).timestamp()))
        if end is not None:
            clauses.append("bucket_ts < ?")
            params.append(int(datetime.combine(date.fromisoformat(end) + timedelta(days=1), time.min, tz).timestamp()))
        where = " AND ".join(clauses)
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"SELECT bucket_ts, CAST(sum_count AS REAL) / n_samples FROM {self.TABLE_SLOTS} WHERE {where} ORDER BY bucket_ts",  # noqa: S608
                params,
            )
            raw = await cursor.fetchall()
        return [
            (
                (local_dt := datetime.fromtimestamp(ts, tz)).date().isoformat(),
                (local_dt.hour * 60 + local_dt.minute) // 5,
                avg,
            )
            for ts, avg in raw
        ]
