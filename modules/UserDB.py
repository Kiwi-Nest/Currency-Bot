"""Manage user-specific data and preferences in the database.

The `users` table stores person-level prefs (timezone, native_language, autotranslate).
The `memberships` table stores per-guild state (currency, xp, bumps, level, etc.).
"""

from __future__ import annotations

import json
import logging
import math
from typing import TYPE_CHECKING, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.CurrencyLedgerDB import COLLATERAL_POOL_ID, SYSTEM_USER_ID
from modules.Database import scalar_or, snowflake
from modules.dtypes import (
    GuildId,
    Member,
    NonNegativeInt,
    PositiveInt,
    ReminderPreference,
    UserId,
)
from modules.errors import BurnError, InsufficientFunds, SelfTransfer, TransferError
from modules.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Iterable

    from modules.CurrencyLedgerDB import CurrencyLedgerDB, EventReason, EventType
    from modules.Database import Database, WriteTx
    from modules.enums import PlainStat, StatName


# False S608: table names are constants/enums, not user input.
class UserDB:
    USERS_TABLE: ClassVar[str] = "users"
    MEMBERSHIPS_TABLE: ClassVar[str] = "memberships"

    def __init__(self, database: Database) -> None:
        self.database = database
        self.log = logging.getLogger(__name__)

    async def post_init(self) -> None:
        """Initialize user and membership tables."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    discord_id      INTEGER PRIMARY KEY,
                    timezone        TEXT NOT NULL DEFAULT 'UTC',
                    native_language TEXT DEFAULT NULL,
                    autotranslate   INTEGER NOT NULL DEFAULT 0 CHECK(autotranslate IN (0,1))
                ) STRICT
                """,
            )
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS memberships (
                    discord_id               INTEGER NOT NULL REFERENCES users(discord_id)
                                                 ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
                    guild_id                 INTEGER NOT NULL {snowflake("guild_id")},
                    currency                 INTEGER NOT NULL DEFAULT 0 CHECK(currency >= 0),
                    bumps                    INTEGER NOT NULL DEFAULT 0 CHECK(bumps >= 0),
                    xp                       INTEGER NOT NULL DEFAULT 0 CHECK(xp >= 0),
                    level                    INTEGER GENERATED ALWAYS AS
                                                 (CAST(floor(pow(max(xp-6,0),1.0/2.5)) AS INTEGER)) STORED,
                    last_active_timestamp    INTEGER NOT NULL DEFAULT (unixepoch()),
                    daily_reminder_preference TEXT NOT NULL DEFAULT 'NEVER'
                                                 CHECK(daily_reminder_preference IN ('NEVER','ONCE','ALWAYS')),
                    has_claimed_daily        INTEGER NOT NULL DEFAULT 0 CHECK(has_claimed_daily IN (0,1)),
                    PRIMARY KEY (discord_id, guild_id)
                ) STRICT, WITHOUT ROWID
                """,
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memberships_activity ON memberships(guild_id, last_active_timestamp)",
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memberships_pending_reminders ON memberships(guild_id) WHERE daily_reminder_preference IN ('ALWAYS','ONCE')",  # noqa: E501
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memberships_currency ON memberships(guild_id, currency DESC)",
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memberships_xp ON memberships(guild_id, xp DESC)",
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memberships_bumps ON memberships(guild_id, bumps DESC)",
            )
            await conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_bump_decrement
                BEFORE UPDATE ON memberships
                WHEN NEW.bumps < OLD.bumps
                BEGIN
                    SELECT RAISE(ABORT, 'Bump count cannot be decreased');
                END
                """,
            )
            await conn.execute(
                """
                CREATE VIEW IF NOT EXISTS v_user_stats AS
                SELECT discord_id, guild_id, currency, bumps, xp, level
                FROM memberships
                """,
            )
            await conn.commit()

    async def update_last_message(self, member: Member) -> None:
        """Update the timestamp of the last message for a user."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO users(discord_id) VALUES (?)",
                (member.user_id,),
            )
            await conn.execute(
                """
                INSERT INTO memberships (discord_id, guild_id) VALUES (?, ?)
                ON CONFLICT(discord_id, guild_id) DO UPDATE SET
                    last_active_timestamp = unixepoch()
                """,
                (member.user_id, member.guild_id),
            )
            await conn.commit()

    async def set_daily_reminder_preference(
        self,
        member: Member,
        preference: ReminderPreference,
    ) -> None:
        """Set the daily reminder preference for a user."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO users(discord_id) VALUES (?)",
                (member.user_id,),
            )
            await conn.execute(
                """
                INSERT INTO memberships (discord_id, guild_id, daily_reminder_preference)
                VALUES (?, ?, ?)
                ON CONFLICT(discord_id, guild_id) DO UPDATE SET
                    daily_reminder_preference = excluded.daily_reminder_preference
                """,
                (member.user_id, member.guild_id, preference),
            )
            await conn.commit()

    async def disable_reminders(self, user_ids: Iterable[UserId]) -> None:
        """Disable daily reminders for a list of users across all guilds."""
        ids = list(user_ids)
        if not ids:
            return
        async with self.database.get_conn() as conn:
            await conn.execute(
                """
                UPDATE memberships
                SET daily_reminder_preference = 'NEVER'
                WHERE discord_id IN (SELECT value FROM json_each(?))
                  AND daily_reminder_preference != 'NEVER'
                """,
                (json.dumps(ids),),
            )
            await conn.commit()

    async def get_active_users(self, guild_id: GuildId, days: int) -> list[UserId]:
        """Get user IDs active within the specified number of days."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                """
                SELECT discord_id FROM memberships
                WHERE guild_id = ? AND (unixepoch() - last_active_timestamp) <= ? * 86400
                """,
                (guild_id, days),
            )
            rows = await cursor.fetchall()
        return [UserId(row[0]) for row in rows]

    async def get_all_users(self, guild_id: GuildId) -> list[UserId]:
        """Return all user IDs known for a guild."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                "SELECT discord_id FROM memberships WHERE guild_id = ?",
                (guild_id,),
            )
            rows = await cursor.fetchall()
        return [UserId(row[0]) for row in rows]

    async def set_last_active(self, member: Member, timestamp: int) -> None:
        """Upsert a user row with an explicit epoch last_active_timestamp."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO users(discord_id) VALUES (?)",
                (member.user_id,),
            )
            await conn.execute(
                """
                INSERT INTO memberships (discord_id, guild_id, last_active_timestamp)
                VALUES (?, ?, ?)
                ON CONFLICT(discord_id, guild_id) DO UPDATE SET
                    last_active_timestamp = excluded.last_active_timestamp
                """,
                (member.user_id, member.guild_id, timestamp),
            )
            await conn.commit()

    async def get_inactive_users(self, guild_id: GuildId, days: int) -> list[UserId]:
        """Get user IDs inactive for more than the specified number of days."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                """
                SELECT discord_id FROM memberships
                WHERE guild_id = ? AND (unixepoch() - last_active_timestamp) > ? * 86400
                """,
                (guild_id, days),
            )
            rows = await cursor.fetchall()
        return [UserId(row[0]) for row in rows]

    async def get_users_last_active(self, guild_id: GuildId, user_ids: set[UserId]) -> list[tuple[UserId, int]]:
        """Return (user_id, last_active_timestamp) for each given user ID in the guild."""
        if not user_ids:
            return []
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                """
                SELECT discord_id, last_active_timestamp FROM memberships
                WHERE guild_id = ? AND discord_id IN (SELECT value FROM json_each(?))
                """,
                (guild_id, json.dumps(list(user_ids))),
            )
            rows = await cursor.fetchall()
        return [(UserId(row[0]), int(row[1])) for row in rows]

    async def update_active_users(self, members: list[Member]) -> None:
        """Bulk update the last active timestamp for a list of users."""
        if not members:
            return
        async with self.database.get_conn() as conn:
            await conn.executemany(
                "INSERT OR IGNORE INTO users(discord_id) VALUES (?)",
                [(m.user_id,) for m in members],
            )
            await conn.executemany(
                """
                INSERT INTO memberships (discord_id, guild_id) VALUES (?, ?)
                ON CONFLICT(discord_id, guild_id) DO UPDATE SET
                    last_active_timestamp = unixepoch()
                """,
                [(m.user_id, m.guild_id) for m in members],
            )
            await conn.commit()

    async def attempt_daily_claim(self, member: Member) -> bool:
        """Atomically attempt to claim a daily reward. Returns True if successful."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO users(discord_id) VALUES (?)",
                (member.user_id,),
            )
            cursor = await conn.execute(
                """
                INSERT INTO memberships (discord_id, guild_id, has_claimed_daily) VALUES (?, ?, 1)
                ON CONFLICT(discord_id, guild_id) DO UPDATE SET
                    has_claimed_daily = 1
                WHERE memberships.has_claimed_daily = 0
                """,
                (member.user_id, member.guild_id),
            )
            await conn.commit()
            return cursor.rowcount == 1

    async def process_daily_reset_for_guild(self, guild_id: GuildId) -> list[UserId]:
        """Atomically reset all daily claims and fetch users who need a reminder."""
        async with self.database.get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT discord_id FROM memberships
                WHERE guild_id = ? AND daily_reminder_preference IN ('ALWAYS', 'ONCE')
                """,
                (guild_id,),
            )
            user_ids_to_remind = [UserId(row[0]) for row in await cursor.fetchall()]
            await conn.execute(
                """
                UPDATE memberships SET
                    has_claimed_daily = 0,
                    daily_reminder_preference = CASE
                        WHEN daily_reminder_preference = 'ONCE' THEN 'NEVER'
                        ELSE daily_reminder_preference END
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            await conn.commit()
            return user_ids_to_remind

    async def process_daily_reset_all(self) -> list[UserId]:
        """Atomically reset all daily claims across all guilds and fetch users who need a reminder."""
        async with self.database.get_conn() as conn:
            cursor = await conn.execute(
                """
                SELECT DISTINCT discord_id FROM memberships
                WHERE daily_reminder_preference IN ('ALWAYS', 'ONCE')
                """,
            )
            user_ids_to_remind = [UserId(row[0]) for row in await cursor.fetchall()]
            await conn.execute(
                """
                UPDATE memberships SET
                    has_claimed_daily = 0,
                    daily_reminder_preference = CASE
                        WHEN daily_reminder_preference = 'ONCE' THEN 'NEVER'
                        ELSE daily_reminder_preference END
                """,
            )
            await conn.commit()
            return user_ids_to_remind

    async def mint_currency(
        self,
        member: Member,
        amount: PositiveInt,
        event_reason: EventReason,
        ledger_db: CurrencyLedgerDB,
        initiator_id: UserId | None = None,
    ) -> NonNegativeInt:
        """Atomically increment a user's currency and log it as a MINT event."""
        async with self.database.transaction() as conn:
            await conn.execute("INSERT OR IGNORE INTO users(discord_id) VALUES (?)", (member.user_id,))
            cursor = await conn.execute(
                """
                INSERT INTO memberships (discord_id, guild_id, currency) VALUES (?, ?, ?)
                ON CONFLICT(discord_id, guild_id) DO UPDATE SET
                    currency = currency + excluded.currency
                RETURNING currency
                """,
                (member.user_id, member.guild_id, amount),
            )
            new_value_row = await cursor.fetchone()
            await ledger_db.log_event(
                tx=conn,
                guild_id=member.guild_id,
                event_type="MINT",
                event_reason=event_reason,
                sender_id=SYSTEM_USER_ID,
                receiver_id=member.user_id,
                amount=amount,
                initiator_id=initiator_id or member.user_id,
            )
        return NonNegativeInt(scalar_or(new_value_row, "currency", 0))

    async def burn_currency(
        self,
        member: Member,
        amount: PositiveInt,
        event_reason: EventReason,
        ledger_db: CurrencyLedgerDB,
        initiator_id: UserId,
    ) -> Result[int, BurnError]:
        """Atomically decrement currency if sufficient, log as BURN. Returns Ok(new_balance) or Err."""
        async with self.database.transaction() as conn:
            cursor = await conn.execute(
                """
                UPDATE memberships
                SET currency = currency - ?
                WHERE discord_id = ? AND guild_id = ? AND currency >= ?
                RETURNING currency
                """,
                (amount, member.user_id, member.guild_id, amount),
            )
            new_value_row = await cursor.fetchone()

            if new_value_row is None:
                bal_cursor = await conn.execute(
                    "SELECT currency FROM memberships WHERE discord_id = ? AND guild_id = ?",
                    (member.user_id, member.guild_id),
                )
                available = NonNegativeInt(scalar_or(await bal_cursor.fetchone(), "currency", 0))
                await conn.rollback()
                return Err(InsufficientFunds(available=available, required=amount))

            await ledger_db.log_event(
                tx=conn,
                guild_id=member.guild_id,
                event_type="BURN",
                event_reason=event_reason,
                sender_id=member.user_id,
                receiver_id=SYSTEM_USER_ID,
                amount=amount,
                initiator_id=initiator_id,
            )
            return Ok(scalar_or(new_value_row, "currency", 0))

    async def set_currency_balance_and_log(
        self,
        member: Member,
        new_balance: NonNegativeInt,
        event_reason: EventReason,
        ledger_db: CurrencyLedgerDB,
        initiator_id: UserId,
    ) -> None:
        """Atomically set a user's balance and log the delta as MINT or BURN."""
        async with self.database.transaction() as conn:
            cursor = await conn.execute(
                "SELECT currency FROM memberships WHERE discord_id = ? AND guild_id = ?",
                (member.user_id, member.guild_id),
            )
            current_balance = scalar_or(await cursor.fetchone(), "currency", 0)
            delta = new_balance - current_balance

            await conn.execute("INSERT OR IGNORE INTO users(discord_id) VALUES (?)", (member.user_id,))
            await conn.execute(
                """
                INSERT INTO memberships (discord_id, guild_id, currency) VALUES (?, ?, ?)
                ON CONFLICT(discord_id, guild_id) DO UPDATE SET currency = excluded.currency
                """,
                (member.user_id, member.guild_id, new_balance),
            )

            if delta > 0:
                await ledger_db.log_event(
                    tx=conn,
                    guild_id=member.guild_id,
                    event_type="MINT",
                    event_reason=event_reason,
                    sender_id=SYSTEM_USER_ID,
                    receiver_id=member.user_id,
                    amount=delta,
                    initiator_id=initiator_id,
                )
            elif delta < 0:
                await ledger_db.log_event(
                    tx=conn,
                    guild_id=member.guild_id,
                    event_type="BURN",
                    event_reason=event_reason,
                    sender_id=member.user_id,
                    receiver_id=SYSTEM_USER_ID,
                    amount=abs(delta),
                    initiator_id=initiator_id,
                )

    async def get_stat(self, member: Member, stat: StatName) -> NonNegativeInt:
        """Get a single stat for a user, returning 0 if they don't exist."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"SELECT {stat.value} FROM memberships WHERE discord_id = ? AND guild_id = ?",  # noqa: S608
                (member.user_id, member.guild_id),
            )
            result = await cursor.fetchone()
        return NonNegativeInt(scalar_or(result, stat.value, 0))

    async def increment_stat(self, member: Member, stat: PlainStat, amount: PositiveInt) -> NonNegativeInt:
        """Atomically increment a user's stat and return the new value."""
        sql = f"""
            INSERT INTO memberships (discord_id, guild_id, {stat.value})
            VALUES (?, ?, ?)
            ON CONFLICT(discord_id, guild_id) DO UPDATE SET
                {stat.value} = {stat.value} + excluded.{stat.value}
            RETURNING {stat.value}
        """  # noqa: S608
        async with self.database.get_conn() as conn:
            await conn.execute("INSERT OR IGNORE INTO users(discord_id) VALUES (?)", (member.user_id,))
            cursor = await conn.execute(sql, (member.user_id, member.guild_id, amount))
            new_value_row = await cursor.fetchone()
            await conn.commit()
        return NonNegativeInt(scalar_or(new_value_row, stat.value, 0))

    async def decrement_stat(self, member: Member, stat: PlainStat, amount: PositiveInt) -> int | None:
        """Atomically decrement a user's stat if they have sufficient value."""
        sql = f"""
            UPDATE memberships
            SET {stat.value} = {stat.value} - ?
            WHERE discord_id = ? AND guild_id = ? AND {stat.value} >= ?
            RETURNING {stat.value}
        """  # noqa: S608
        async with self.database.get_conn() as conn:
            cursor = await conn.execute(sql, (amount, member.user_id, member.guild_id, amount))
            new_value_row = await cursor.fetchone()
            await conn.commit()
        return scalar_or(new_value_row, stat.value, None)

    async def set_stat(self, member: Member, stat: PlainStat, value: int) -> None:
        """Atomically set a user's stat to a specific value."""
        sql = f"""
            INSERT INTO memberships (discord_id, guild_id, {stat.value})
            VALUES (?, ?, ?)
            ON CONFLICT(discord_id, guild_id) DO UPDATE SET
                {stat.value} = excluded.{stat.value}
        """  # noqa: S608
        async with self.database.get_conn() as conn:
            await conn.execute("INSERT OR IGNORE INTO users(discord_id) VALUES (?)", (member.user_id,))
            await conn.execute(sql, (member.user_id, member.guild_id, value))
            await conn.commit()

    async def transfer_currency(
        self,
        sender_id: UserId,
        receiver_id: UserId,
        guild_id: GuildId,
        amount: PositiveInt,
        ledger_db: CurrencyLedgerDB,
    ) -> Result[None, TransferError]:
        """Atomically transfer currency and log the transaction."""
        if sender_id == receiver_id:
            return Err(SelfTransfer())

        async with self.database.transaction() as conn:
            cursor = await conn.execute(
                """UPDATE memberships SET currency = currency - ?
                WHERE discord_id = ? AND guild_id = ? AND currency >= ?""",
                (amount, sender_id, guild_id, amount),
            )
            if cursor.rowcount == 0:
                bal_cursor = await conn.execute(
                    "SELECT currency FROM memberships WHERE discord_id = ? AND guild_id = ?",
                    (sender_id, guild_id),
                )
                available = NonNegativeInt(scalar_or(await bal_cursor.fetchone(), "currency", 0))
                await conn.rollback()
                return Err(InsufficientFunds(available=available, required=amount))

            await conn.execute("INSERT OR IGNORE INTO users(discord_id) VALUES (?)", (receiver_id,))
            await conn.execute(
                """
                INSERT INTO memberships (discord_id, guild_id, currency) VALUES (?, ?, ?)
                ON CONFLICT(discord_id, guild_id) DO UPDATE SET currency = currency + excluded.currency
                """,
                (receiver_id, guild_id, amount),
            )
            await ledger_db.log_event(
                tx=conn,
                guild_id=guild_id,
                event_type="TRANSFER",
                event_reason="P2P_TRANSFER",
                sender_id=sender_id,
                receiver_id=receiver_id,
                amount=amount,
                initiator_id=sender_id,
            )
            return Ok(None)

    async def get_leaderboard(
        self,
        guild_id: GuildId,
        stat: StatName,
        limit: int = 10,
    ) -> list[tuple[int, UserId, int]]:
        """Retrieve the top users by a stat."""
        query_stat = stat.value
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                f"""
                SELECT
                    RANK() OVER (ORDER BY {query_stat} DESC) as rank,
                    discord_id,
                    {query_stat}
                FROM v_user_stats
                WHERE guild_id = ? AND {query_stat} > 0
                LIMIT ?
                """,  # noqa: S608
                (guild_id, limit),
            )
            rows = await cursor.fetchall()
            return [(row[0], UserId(row[1]), row[2]) for row in rows]

    async def get_level_and_xp(self, member: Member) -> tuple[int, int] | None:
        """Fetch the level and XP for a user."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                "SELECT level, xp FROM memberships WHERE discord_id = ? AND guild_id = ?",
                (member.user_id, member.guild_id),
            )
            return await cursor.fetchone()

    async def apply_wealth_tax(
        self,
        guild_id: GuildId,
        exponent: float,
        ledger_db: CurrencyLedgerDB,
        initiator_id: UserId,
    ) -> tuple[int, int]:
        """Apply a progressive wealth tax to all users' cash and stock collateral.

        Returns (count_of_users_affected, total_amount_burned).
        """
        total_burned = 0
        affected_users = set()
        ledger_events = []
        cash_updates = []
        stock_updates = []

        async with self.database.transaction() as conn:
            cursor = await conn.execute(
                "SELECT discord_id, currency FROM memberships WHERE guild_id = ? AND currency > 10",
                (guild_id,),
            )
            rows = await cursor.fetchall()

            for uid, old_balance in rows:
                new_balance = math.ceil(pow(old_balance, exponent))
                tax = old_balance - new_balance
                if tax > 0:
                    total_burned += tax
                    affected_users.add(UserId(uid))
                    cash_updates.append((new_balance, uid, guild_id))
                    ledger_events.append(
                        (
                            guild_id,
                            "BURN",
                            "WEALTH_TAX",
                            uid,
                            SYSTEM_USER_ID,
                            tax,
                            initiator_id,
                        ),
                    )

            cursor = await conn.execute(
                """SELECT position_id, user_id, collateral_dollars,
                notional_dollars FROM positions WHERE guild_id = ? AND collateral_dollars > 10""",
                (guild_id,),
            )
            rows = await cursor.fetchall()

            for pos_id, uid, old_collat, old_notional in rows:
                new_collat = math.ceil(pow(old_collat, exponent))
                tax = old_collat - new_collat
                if tax > 0:
                    ratio = new_collat / old_collat
                    new_notional = int(old_notional * ratio)
                    if abs(new_notional) < 1:
                        continue
                    total_burned += tax
                    affected_users.add(UserId(uid))
                    stock_updates.append((new_collat, new_notional, pos_id))
                    ledger_events.append(
                        (
                            guild_id,
                            "BURN",
                            "WEALTH_TAX_COLLATERAL",
                            COLLATERAL_POOL_ID,
                            SYSTEM_USER_ID,
                            tax,
                            initiator_id,
                        ),
                    )

            if cash_updates:
                await conn.executemany(
                    "UPDATE memberships SET currency = ? WHERE discord_id = ? AND guild_id = ?",
                    cash_updates,
                )
            if stock_updates:
                await conn.executemany(
                    "UPDATE positions SET collateral_dollars = ?, notional_dollars = ? WHERE position_id = ?",
                    stock_updates,
                )
            if ledger_events:
                await ledger_db.bulk_log_event(conn, ledger_events)

        return len(affected_users), total_burned

    async def set_native_language(self, member: Member, language: str | None) -> None:
        """Set the user's native language for auto-translation."""
        async with self.database.get_conn() as conn:
            await conn.execute(
                """
                INSERT INTO users (discord_id, native_language) VALUES (?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET native_language = excluded.native_language
                """,
                (member.user_id, language),
            )
            await conn.commit()

    async def get_native_language(self, member: Member) -> str | None:
        """Get the user's native language preference."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                "SELECT native_language FROM users WHERE discord_id = ?",
                (member.user_id,),
            )
            return scalar_or(await cursor.fetchone(), "native_language", None)

    async def get_timezone(self, member: Member) -> ZoneInfo | None:
        """Fetch the user's timezone, or None if not set."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                "SELECT timezone FROM users WHERE discord_id = ?",
                (member.user_id,),
            )
            tz_name = scalar_or(await cursor.fetchone(), "timezone", None)

        if tz_name:
            try:
                return ZoneInfo(tz_name)
            except ZoneInfoNotFoundError, ValueError:
                pass
        return None

    async def set_timezone(self, member: Member, tz_name: str) -> bool:
        """Set the user's timezone. Returns False if the timezone is invalid."""
        try:
            ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            return False

        async with self.database.get_conn() as conn:
            await conn.execute(
                """
                INSERT INTO users (discord_id, timezone) VALUES (?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET timezone = excluded.timezone
                """,
                (member.user_id, tz_name),
            )
            await conn.commit()
        return True

    async def set_autotranslate(self, member: Member, enabled: bool) -> None:
        """Set the user's autotranslate preference."""
        value = int(enabled)
        async with self.database.get_conn() as conn:
            await conn.execute(
                """
                INSERT INTO users (discord_id, autotranslate) VALUES (?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET autotranslate = excluded.autotranslate
                """,
                (member.user_id, value),
            )
            await conn.commit()

    async def get_autotranslate(self, member: Member) -> bool:
        """Check if the user has opted in to autotranslate."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                "SELECT autotranslate FROM users WHERE discord_id = ?",
                (member.user_id,),
            )
            return bool(scalar_or(await cursor.fetchone(), "autotranslate", 0))

    async def delete_users(self, guild_id: GuildId, user_ids: list[UserId]) -> int:
        """Delete guild memberships for specific users. Positions cascade via FK.

        Returns the number of membership rows deleted.
        """
        if not user_ids:
            return 0
        ids_json = json.dumps(list(user_ids))
        async with self.database.get_conn() as conn:
            cursor = await conn.execute(
                """DELETE FROM memberships
                   WHERE discord_id IN (SELECT value FROM json_each(?)) AND guild_id = ?""",
                (ids_json, guild_id),
            )
            await conn.commit()
        return cursor.rowcount


async def apply_delta(
    tx: WriteTx,
    member: Member,
    amount: int,
    event_type: EventType,
    event_reason: EventReason,
    ledger_db: CurrencyLedgerDB,
    counterparty: int = SYSTEM_USER_ID,
) -> Result[NonNegativeInt, InsufficientFunds]:
    """Apply a signed currency delta within an active write transaction.

    amount > 0: credit (UPSERT); amount < 0: debit (guarded UPDATE); amount == 0: read-only.
    Returns Ok(new_balance) or Err(InsufficientFunds).
    """
    if amount > 0:
        await tx.execute("INSERT OR IGNORE INTO users(discord_id) VALUES (?)", (member.user_id,))
        cursor = await tx.execute(
            """INSERT INTO memberships (discord_id, guild_id, currency) VALUES (?, ?, ?)
               ON CONFLICT(discord_id, guild_id) DO UPDATE SET currency = currency + excluded.currency
               RETURNING currency""",
            (member.user_id, member.guild_id, amount),
        )
        row = await cursor.fetchone()
        new_balance = NonNegativeInt(scalar_or(row, "currency", 0))
        await ledger_db.log_event(
            tx,
            guild_id=member.guild_id,
            event_type=event_type,
            event_reason=event_reason,
            sender_id=counterparty,
            receiver_id=member.user_id,
            amount=amount,
            initiator_id=member.user_id,
        )
        return Ok(new_balance)

    if amount < 0:
        debit = abs(amount)
        cursor = await tx.execute(
            """UPDATE memberships SET currency = currency - ?
               WHERE discord_id = ? AND guild_id = ? AND currency >= ?
               RETURNING currency""",
            (debit, member.user_id, member.guild_id, debit),
        )
        row = await cursor.fetchone()
        if row is None:
            bal_cursor = await tx.execute(
                "SELECT currency FROM memberships WHERE discord_id = ? AND guild_id = ?",
                (member.user_id, member.guild_id),
            )
            available = NonNegativeInt(scalar_or(await bal_cursor.fetchone(), "currency", 0))
            return Err(InsufficientFunds(available=available, required=PositiveInt(debit)))
        new_balance = NonNegativeInt(scalar_or(row, "currency", 0))
        await ledger_db.log_event(
            tx,
            guild_id=member.guild_id,
            event_type=event_type,
            event_reason=event_reason,
            sender_id=member.user_id,
            receiver_id=counterparty,
            amount=debit,
            initiator_id=member.user_id,
        )
        return Ok(new_balance)

    # amount == 0: read-only, no write, no log
    bal_cursor = await tx.execute(
        "SELECT currency FROM memberships WHERE discord_id = ? AND guild_id = ?",
        (member.user_id, member.guild_id),
    )
    balance = scalar_or(await bal_cursor.fetchone(), "currency", 0)
    return Ok(NonNegativeInt(balance))
