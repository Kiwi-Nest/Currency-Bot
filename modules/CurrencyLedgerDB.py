from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Final, Literal

from modules.Database import snowflake

if TYPE_CHECKING:
    from modules.Database import Database, WriteTx
    from modules.dtypes import GuildId, UserId

log = logging.getLogger(__name__)

# Define constants for your special IDs
SYSTEM_USER_ID: Final[int] = 0
COLLATERAL_POOL_ID: Final[int] = 1

EventType = Literal["MINT", "BURN", "TRANSFER"]
EventReason = Literal[
    "DAILY_CLAIM",
    "P2P_TRANSFER",
    "TRADE_OPEN_COLLATERAL",
    "TRADE_CLOSE_COLLATERAL",
    "TRADE_PROFIT",
    "TRADE_LOSS",
    "BUMP_SERVER",  # For cogs/bump_handler.py
    "HARVEST_SALE",  # For cogs/s_w_l.py
    "BLACKJACK_BET",  # For /blackjack and "Play Again"
    "BLACKJACK_DOUBLE_DOWN",  # For "Double Down" action
    "BLACKJACK_SPLIT",  # For "Split" action
    "BLACKJACK_WIN",  # For standard win payout
    "BLACKJACK_BLACKJACK",  # For blackjack (3:2) payout
    "BLACKJACK_SURRENDER_RETURN",  # For surrender (1:2) return
    "BLACKJACK_PUSH",  # For push (1:1) return
    "ADMIN_SET",  # For admin commands
    "ADMIN_REMOVE",  # For admin commands
    "ADMIN_MINT",  # For admin mint command
    "WEALTH_TAX",  # For wealth tax on cash
    "WEALTH_TAX_COLLATERAL",  # For wealth tax on stocks
]


class CurrencyLedgerDB:
    """Manages the immutable `currency_ledger` table."""

    TABLE_NAME: ClassVar[str] = "currency_ledger"

    def __init__(self, database: Database) -> None:
        self.database = database

    async def post_init(self) -> None:
        """Initialize the database table for the currency ledger."""
        async with self.database.get_conn() as conn:
            # This is your proposed schema
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    ledger_id    INTEGER PRIMARY KEY,
                    guild_id     INTEGER NOT NULL {snowflake("guild_id")},
                    timestamp    INTEGER NOT NULL DEFAULT (unixepoch()),
                    event_type   TEXT NOT NULL CHECK(event_type IN ('MINT', 'BURN', 'TRANSFER')),
                    event_reason TEXT NOT NULL,
                    sender_id    INTEGER NOT NULL CHECK(sender_id >= 0),
                    receiver_id  INTEGER NOT NULL CHECK(receiver_id >= 0),
                    amount       INTEGER NOT NULL CHECK(amount > 0),
                    initiator_id INTEGER {snowflake("initiator_id")},
                    reference_id TEXT,
                    CHECK(sender_id <> receiver_id)
                ) STRICT
                """,
            )
            # Optional: Add indexes for faster analytics
            await conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_ledger_event_type ON {self.TABLE_NAME}(event_type)
                """,
            )
            await conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_ledger_actors ON {self.TABLE_NAME}(sender_id, receiver_id)
                """,
            )
            await conn.commit()
            log.info("Initialized currency_ledger database table.")

    async def log_event(
        self,
        tx: WriteTx,
        guild_id: GuildId,
        event_type: EventType,
        event_reason: EventReason,
        sender_id: int,
        receiver_id: int,
        amount: int,
        initiator_id: UserId | None = None,
        reference_id: str | None = None,
    ) -> None:
        """Log a single currency event as part of an atomic transaction."""
        if amount <= 0:
            log.warning("Attempted to log a zero or negative currency event. Skipping.")
            return

        sql = f"""
            INSERT INTO {self.TABLE_NAME}
            (guild_id, event_type, event_reason, sender_id, receiver_id, amount, initiator_id, reference_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """  # noqa: S608
        params = (
            guild_id,
            event_type,
            event_reason,
            sender_id,
            receiver_id,
            amount,
            initiator_id,
            reference_id,
        )
        await tx.execute(sql, params)
        log.debug("Logged currency event: %s - %s", event_type, event_reason)

    async def bulk_log_event(
        self,
        tx: WriteTx,
        events: list[tuple[GuildId, EventType, EventReason, int, int, int, UserId | None]],
    ) -> None:
        """Efficiently log multiple events in one go."""
        if not events:
            return

        sql = f"""
            INSERT INTO {self.TABLE_NAME} (guild_id, event_type, event_reason, sender_id,
            receiver_id, amount, initiator_id) VALUES (?, ?, ?, ?, ?, ?, ?)
        """  # noqa: S608
        await tx.executemany(sql, events)
