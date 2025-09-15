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
        balance = await self.get_balance(discord_id)
        async with self.database.get_conn() as conn:
            balance += amount
            # False S608: CURRENCY_TABLE is a constant, not user input
            await conn.execute(
                f"INSERT INTO {self.CURRENCY_TABLE} (discord_id, balance) VALUES (?, ?)\
                 ON CONFLICT(discord_id) DO UPDATE SET balance = ?",  # noqa: S608
                (discord_id, balance, balance),
            )
            await conn.commit()

    async def remove_money(self, discord_id: int, amount: int) -> None:
        await self.add_money(discord_id, -amount)
