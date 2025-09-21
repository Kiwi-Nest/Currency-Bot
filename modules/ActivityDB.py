import asyncio
from typing import ClassVar

from modules.Database import Database


class ActivityDB:
    ACTIVITY_TABLE: ClassVar[str] = "user_activity"

    def __init__(self, database: Database) -> None:
        self.database = database
        # No other way to do this
        asyncio.create_task(self._postInit())  # noqa: RUF006

    async def _postInit(self) -> None:
        """Initialize the database table for user activity."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.ACTIVITY_TABLE}
                (
                    discord_id TEXT UNIQUE NOT NULL,
                    last_message_timestamp TEXT NOT NULL
                )
                """,
            )
            await conn.commit()

    async def update_last_message(self, discord_id: int) -> None:
        """Update the timestamp of the last message for a given user."""
        async with self.database.get_conn() as conn:
            # False S608: ACTIVITY_TABLE is a constant, not user input
            await conn.execute(
                f"""
                INSERT INTO {self.ACTIVITY_TABLE} (discord_id, last_message_timestamp)
                VALUES (?, datetime('now'))
                ON CONFLICT(discord_id) DO UPDATE SET
                last_message_timestamp = datetime('now')
                """,  # noqa: S608
                (discord_id,),
            )
            await conn.commit()

    async def get_inactive_users(self, days: int) -> list[int]:
        """Get a list of user IDs that have been inactive for more than a specified number of days."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                # False S608: ACTIVITY_TABLE is a constant, not user input
                f"""
                SELECT discord_id FROM {self.ACTIVITY_TABLE}
                WHERE julianday('now') - julianday(last_message_timestamp) > ?
                """,  # noqa: S608
                (days,),
            )
            inactive_users = await cursor.fetchall()
        return [int(row[0]) for row in inactive_users]
