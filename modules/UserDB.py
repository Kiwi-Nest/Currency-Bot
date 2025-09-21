from typing import ClassVar

from modules.Database import Database


# False S608: CURRENCY_TABLE is a constant, not user input
class UserDB:
    USERS_TABLE: ClassVar[str] = "users"

    def __init__(self, database: Database) -> None:
        self.database = database

    async def post_init(self) -> None:
        """Initialize the database table for users."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.USERS_TABLE} (
                    discord_id TEXT UNIQUE NOT NULL,
                    last_message_timestamp TEXT NOT NULL,
                    daily_reminder INTEGER NOT NULL DEFAULT 0,
                    daily_cooldown_ends TEXT
                )
                """,
            )
            await conn.commit()

    async def update_last_message(self, discord_id: int) -> None:
        """Update the timestamp of the last message for a user."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.USERS_TABLE} (discord_id, last_message_timestamp)
                VALUES (?, datetime('now'))
                ON CONFLICT(discord_id) DO UPDATE SET
                last_message_timestamp = datetime('now')
                """,  # noqa: S608
                (discord_id,),
            )
            await conn.commit()

    async def set_daily_reminder(self, discord_id: int, wants_reminder: bool) -> None:
        """Set the daily reminder preference for a user."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.USERS_TABLE} (discord_id, last_message_timestamp, daily_reminder)
                VALUES (?, datetime('now'), ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                daily_reminder = ?
                """,  # noqa: S608
                (discord_id, 1 if wants_reminder else 0, 1 if wants_reminder else 0),
            )
            await conn.commit()

    async def get_users_with_reminders(self) -> list[int]:
        """Get a list of user IDs who have daily reminders enabled."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"SELECT discord_id FROM {self.USERS_TABLE} WHERE daily_reminder = 1",  # noqa: S608
            )
            users = await cursor.fetchall()
        return [int(row[0]) for row in users]

    async def get_inactive_users(self, days: int) -> list[int]:
        """Get a list of user IDs that have been inactive for more than a specified number of days."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT discord_id FROM {self.USERS_TABLE}
                WHERE julianday('now') - julianday(last_message_timestamp) > ?
                """,  # noqa: S608
                (days,),
            )
            inactive_users = await cursor.fetchall()
        return [int(row[0]) for row in inactive_users]

    async def bulk_update_last_message(self, activity_cache: dict[int, str]) -> None:
        """Bulk update last message timestamps from the activity cache."""
        if not activity_cache:
            return

        async with self.database.get_conn() as conn:
            # Prepare data for bulk insert/update
            data = [(str(discord_id), timestamp) for discord_id, timestamp in activity_cache.items()]

            await conn.executemany(
                f"""
                INSERT INTO {self.USERS_TABLE} (discord_id, last_message_timestamp)
                VALUES (?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                last_message_timestamp = ?
                """,  # noqa: S608
                [(discord_id, timestamp, timestamp) for discord_id, timestamp in data],
            )
            await conn.commit()

    async def set_daily_cooldown(self, discord_id: int, cooldown_ends: str) -> None:
        """Set the daily cooldown end time for a user."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.USERS_TABLE} (discord_id, last_message_timestamp, daily_cooldown_ends)
                VALUES (?, datetime('now'), ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                daily_cooldown_ends = ?
                """,  # noqa: S608
                (discord_id, cooldown_ends, cooldown_ends),
            )
            await conn.commit()

    async def get_users_ready_for_reminder(self) -> list[int]:
        """Get users who have reminders enabled and whose cooldown has expired."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT discord_id FROM {self.USERS_TABLE}
                WHERE daily_reminder = 1
                AND daily_cooldown_ends IS NOT NULL
                AND datetime(daily_cooldown_ends) <= datetime('now')
                """,  # noqa: S608
            )
            users = await cursor.fetchall()
        return [int(row[0]) for row in users]

    async def clear_daily_reminder(self, discord_id: int) -> None:
        """Clear the daily reminder flag and cooldown timestamp for a user."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                f"""
                UPDATE {self.USERS_TABLE}
                SET daily_reminder = 0, daily_cooldown_ends = NULL
                WHERE discord_id = ?
                """,  # noqa: S608
                (discord_id,),
            )
            await conn.commit()
