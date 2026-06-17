"""User privacy operations: erasure (GDPR Art. 17) and data access (GDPR Art. 15)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from modules.dtypes import (
    ErasureReport,
    UserDataReport,
    UserGuildRow,
    UserId,
    UserInvite,
    UserLedgerRow,
    UserPosition,
    UserReminder,
)

if TYPE_CHECKING:
    from modules.Database import Database
    from modules.VoiceChatDB import VoiceChatDB

log = logging.getLogger(__name__)


class PrivacyDB:
    """Manages user erasure and data export across all tables."""

    def __init__(self, database: Database, voicechat_db: VoiceChatDB) -> None:
        self.database = database
        self.voicechat_db = voicechat_db

    async def erase_user(self, user_id: UserId) -> ErasureReport:
        """Atomically erase a user from all tables.

        Deleting `users` cascades to `memberships`, `positions`, and `reminders`.
        `invites` has no FK and is deleted explicitly.
        currency_ledger rows are intentionally NOT deleted (deferred).
        """
        async with self.database.transaction() as conn:
            # Count rows before cascade so we can report accurate totals
            mem_row = await (await conn.execute("SELECT COUNT(*) FROM memberships WHERE discord_id = ?", (user_id,))).fetchone()
            pos_row = await (await conn.execute("SELECT COUNT(*) FROM positions WHERE user_id = ?", (user_id,))).fetchone()
            rem_row = await (await conn.execute("SELECT COUNT(*) FROM reminders WHERE user_id = ?", (user_id,))).fetchone()

            mem_count = int(mem_row[0])
            pos_count = int(pos_row[0])
            rem_count = int(rem_row[0])

            await conn.execute("DELETE FROM users WHERE discord_id = ?", (user_id,))
            invites_cursor = await conn.execute("DELETE FROM invites WHERE invitee_id = ? OR inviter_id = ?", (user_id, user_id))
            vc_deleted = await self.voicechat_db.erase_on_conn(conn, user_id)

        report = ErasureReport(
            positions=pos_count,
            reminders=rem_count,
            invites=invites_cursor.rowcount,
            users=mem_count,
            voicechat_sessions_deleted=vc_deleted,
        )
        log.info(
            "Erased user %s: positions=%d, reminders=%d, invites=%d, memberships=%d, vc_sessions=%d",
            user_id,
            report.positions,
            report.reminders,
            report.invites,
            report.users,
            report.voicechat_sessions_deleted,
        )
        return report

    async def get_user_data(self, user_id: UserId) -> UserDataReport:
        """Fetch all personal data stored for a user across all tables."""
        async with self.database.get_cursor() as cursor:
            # Guild memberships - JOIN users for person-level prefs
            await cursor.execute(
                """
                SELECT m.guild_id, m.currency, m.xp, m.bumps, m.level,
                       m.last_active_timestamp, u.native_language, u.timezone,
                       m.daily_reminder_preference
                FROM memberships m JOIN users u ON u.discord_id = m.discord_id
                WHERE m.discord_id = ?
                """,
                (user_id,),
            )
            guilds = [
                UserGuildRow(
                    guild_id=int(row["guild_id"]),
                    currency=int(row["currency"]),
                    xp=int(row["xp"]),
                    bumps=int(row["bumps"]),
                    level=int(row["level"]),
                    last_active_timestamp=int(row["last_active_timestamp"]),
                    native_language=row["native_language"],
                    timezone=str(row["timezone"]),
                    daily_reminder_preference=str(row["daily_reminder_preference"]),  # type: ignore[arg-type]
                )
                for row in await cursor.fetchall()
            ]

            await cursor.execute(
                "SELECT inviter_id, guild_id, joined_at FROM invites WHERE invitee_id = ?",
                (user_id,),
            )
            invites = [
                UserInvite(
                    inviter_id=int(row["inviter_id"]) if row["inviter_id"] is not None else None,
                    guild_id=int(row["guild_id"]),
                    joined_at=str(row["joined_at"]),
                )
                for row in await cursor.fetchall()
            ]

            await cursor.execute(
                "SELECT message, remind_at, created_at FROM reminders WHERE user_id = ? ORDER BY remind_at",
                (user_id,),
            )
            reminders = [
                UserReminder(
                    message=str(row["message"]),
                    remind_at=int(row["remind_at"]),
                    created_at=row["created_at"] or 0,
                )
                for row in await cursor.fetchall()
            ]

            await cursor.execute(
                """
                SELECT ticker, notional_dollars, collateral_dollars, entry_price, timestamp
                FROM positions WHERE user_id = ? ORDER BY timestamp DESC
                """,
                (user_id,),
            )
            positions = [
                UserPosition(
                    ticker=str(row["ticker"]),
                    notional_dollars=int(row["notional_dollars"]),
                    collateral_dollars=int(row["collateral_dollars"]),
                    entry_price=float(row["entry_price"]),
                    timestamp=int(row["timestamp"]),
                )
                for row in await cursor.fetchall()
            ]

            await cursor.execute(
                """
                SELECT guild_id, timestamp, event_type, event_reason,
                       sender_id, receiver_id, amount, initiator_id, reference_id
                FROM currency_ledger
                WHERE sender_id = ? OR receiver_id = ? OR initiator_id = ?
                ORDER BY timestamp DESC
                """,
                (user_id, user_id, user_id),
            )
            ledger = [
                UserLedgerRow(
                    guild_id=int(row["guild_id"]),
                    timestamp=int(row["timestamp"]),
                    event_type=str(row["event_type"]),
                    event_reason=str(row["event_reason"]),
                    sender_id=int(row["sender_id"]),
                    receiver_id=int(row["receiver_id"]),
                    amount=int(row["amount"]),
                    initiator_id=int(row["initiator_id"]) if row["initiator_id"] is not None else None,
                    reference_id=str(row["reference_id"]) if row["reference_id"] is not None else None,
                )
                for row in await cursor.fetchall()
            ]

        voice = await self.voicechat_db.get_user_voice_stats(user_id)

        return UserDataReport(
            user_id=user_id,
            guilds=guilds,
            invites=invites,
            reminders=reminders,
            positions=positions,
            ledger=ledger,
            voice=voice,
        )

    async def get_user_guild_ids(self, user_id: UserId) -> list[int]:
        """Fetch all guild IDs where a user has a membership."""
        async with self.database.get_cursor() as cursor:
            await cursor.execute(
                "SELECT DISTINCT guild_id FROM memberships WHERE discord_id = ?",
                (user_id,),
            )
            rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]
