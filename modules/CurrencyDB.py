import asyncio
from typing import ClassVar

from modules.Database import Database


class CurrencyDB:
    CURRENCY_DB: ClassVar[str] = "currency.db"
    CURRENCY_TABLE: ClassVar[str] = "currencies"

    def __init__(self, database: Database) -> None:
        self.database = database
        # No other way to do this
        asyncio.create_task(self._postInit())  # noqa: RUF006

    async def _postInit(self) -> None:
        async with self.database.get_conn() as conn:
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.CURRENCY_TABLE}
                (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id TEXT UNIQUE NOT NULL,
                    balance    NUMBER      NOT NULL
                )
                """,
            )

            await conn.commit()

    async def get_balance(self, discord_id: int) -> int:
        async with self.database.get_cursor() as cursor:
            # False S608: CURRENCY_TABLE is a constant, not user input
            await cursor.execute(
                f"SELECT balance FROM {self.CURRENCY_TABLE} WHERE discord_id = ?",  # noqa: S608
                (discord_id,),
            )
            balance = await cursor.fetchone()

        return int(balance[0]) if balance else 0

    async def add_money(self, discord_id: int, amount: int) -> None:
        async with self.database.get_conn() as conn:
            # False S608: CURRENCY_TABLE is a constant, not user input
            await conn.execute(
                f"""
                INSERT INTO {self.CURRENCY_TABLE} (discord_id, balance)
                VALUES (?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                balance = balance + ?
                """,  # noqa: S608
                # The first two `?` are for the INSERT, the third `?` is for the UPDATE.
                (discord_id, amount, amount),
            )
            await conn.commit()

    async def remove_money(self, discord_id: int, amount: int) -> None:
        await self.add_money(discord_id, -amount)

    async def transfer_money(self, sender_id: int, receiver_id: int, amount: int) -> bool:
        """Atomically transfers a specified amount from a sender to a receiver.

        This entire operation is performed within a single database transaction.
        If any step fails (e.g., insufficient funds), the entire transaction
        is rolled back.

        Returns
        -------
            bool: True if the transfer was successful, False otherwise.

        """
        async with self.database.get_conn() as conn:
            # Step 1: Check the sender's balance within the transaction to prevent race conditions.
            cursor = await conn.cursor()
            await cursor.execute(
                f"SELECT balance FROM {self.CURRENCY_TABLE} WHERE discord_id = ?",  # noqa: S608
                (sender_id,),
            )
            balance_row = await cursor.fetchone()
            sender_balance = int(balance_row[0]) if balance_row else 0

            # Step 2: If funds are insufficient, abort the transfer.
            if sender_balance < amount:
                return False

            # Step 3: Perform the transfer using the atomic add_money logic.
            # Debit the sender.
            await conn.execute(
                f"""
                UPDATE {self.CURRENCY_TABLE} SET balance = balance - ?
                WHERE discord_id = ?
                """,  # noqa: S608
                (amount, sender_id),
            )

            # Credit the receiver.
            await conn.execute(
                f"""
                INSERT INTO {self.CURRENCY_TABLE} (discord_id, balance) VALUES (?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET balance = balance + ?
                """,  # noqa: S608
                (receiver_id, amount, amount),
            )

            # Step 4: Commit the transaction.
            await conn.commit()
            return True
