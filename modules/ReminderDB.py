from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

from modules.Database import snowflake

if TYPE_CHECKING:
    from modules.Database import Database
    from modules.dtypes import ChannelId, GuildId, UserId

log = logging.getLogger(__name__)


class ReminderDB:
    TABLE_NAME: ClassVar[str] = "reminders"

    def __init__(self, database: Database) -> None:
        self.database = database

    async def post_init(self) -> None:
        """Initialize the reminders table."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    message_id   INTEGER PRIMARY KEY,
                    user_id      INTEGER NOT NULL REFERENCES users(discord_id)
                                     ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
                    guild_id     INTEGER NOT NULL {snowflake("guild_id")},
                    channel_id   INTEGER NOT NULL {snowflake("channel_id")},
                    message      TEXT NOT NULL,
                    remind_at    INTEGER NOT NULL,
                    failures     INTEGER NOT NULL DEFAULT 0,
                    last_attempt INTEGER DEFAULT NULL,
                    created_at   INTEGER NOT NULL DEFAULT (unixepoch())
                ) STRICT
                """,
            )
            await conn.execute(f"CREATE INDEX IF NOT EXISTS idx_reminders_due ON {self.TABLE_NAME}(remind_at)")
            await conn.commit()

    async def add_reminder(
        self,
        user_id: UserId,
        guild_id: GuildId,
        channel_id: ChannelId,
        message_id: int,
        message: str,
        remind_at: datetime,
    ) -> int:
        """Add a reminder (UPSERT). remind_at must be timezone-aware (UTC)."""
        sql = f"""
            INSERT INTO {self.TABLE_NAME} (message_id, user_id, guild_id, channel_id, message, remind_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                remind_at = excluded.remind_at,
                message = excluded.message,
                failures = 0,
                last_attempt = NULL
        """  # noqa: S608
        remind_epoch = int(remind_at.astimezone(UTC).timestamp())
        async with self.database.get_conn() as conn:
            await conn.execute(sql, (message_id, user_id, guild_id, channel_id, message, remind_epoch))
            await conn.commit()
            return message_id

    async def get_due_reminders(self) -> list[tuple]:
        """Fetch reminders that are due (PEEK). Does NOT delete."""
        now_epoch = int(datetime.now(UTC).timestamp())
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT message_id, user_id, guild_id, channel_id, message, failures
                FROM {self.TABLE_NAME}
                WHERE remind_at <= ?
                ORDER BY remind_at ASC
                """,  # noqa: S608
                (now_epoch,),
            )
            return await cursor.fetchall()

    async def get_next_reminder(self) -> tuple | None:
        """Fetch the single earliest reminder (future or past due)."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT message_id, user_id, guild_id, channel_id, message, remind_at
                FROM {self.TABLE_NAME}
                ORDER BY remind_at ASC
                LIMIT 1
                """,  # noqa: S608
            )
            return await cursor.fetchone()

    async def get_active_reminders(self, user_id: UserId) -> list[tuple]:
        """Get all pending reminders for a user."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"SELECT message_id, message, remind_at FROM {self.TABLE_NAME} WHERE user_id = ? ORDER BY remind_at ASC",  # noqa: S608
                (user_id,),
            )
            return await cursor.fetchall()

    async def delete_reminder(self, reminder_id: int, user_id: UserId) -> bool:
        """Delete a specific reminder if it belongs to the user."""
        async with self.database.get_conn() as conn:
            cursor = await conn.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE message_id = ? AND user_id = ?",  # noqa: S608
                (reminder_id, user_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def delete_reminder_by_message_id(self, message_id: int) -> None:
        """Delete a reminder solely by its message ID (used by system cleanup)."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE message_id = ?",  # noqa: S608
                (message_id,),
            )
            await conn.commit()

    async def purge_stale(self, days: int = 90) -> int:
        """Delete reminders older than N days."""
        cutoff = int(datetime.now(UTC).timestamp()) - days * 86400
        async with self.database.get_conn() as conn:
            cursor = await conn.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE remind_at < ?",  # noqa: S608
                (cutoff,),
            )
            await conn.commit()
        deleted = cursor.rowcount
        log.info("Purged %d stale reminders (older than %d days)", deleted, days)
        return deleted

    async def handle_failure(self, message_id: int, current_failures: int) -> None:
        """Increment failure count and apply exponential backoff."""
        new_failures = current_failures + 1
        if new_failures > 3:
            await self.delete_reminder_by_message_id(message_id)
            return

        minutes = 10**new_failures
        now_epoch = int(datetime.now(UTC).timestamp())
        next_attempt = now_epoch + minutes * 60

        async with self.database.get_conn() as conn:
            await conn.execute(
                f"""
                UPDATE {self.TABLE_NAME}
                SET failures = ?, remind_at = ?, last_attempt = ?
                WHERE message_id = ?
                """,  # noqa: S608
                (new_failures, next_attempt, now_epoch, message_id),
            )
            await conn.commit()
