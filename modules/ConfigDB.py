"""Manages guild-specific configurations in the database.

This module provides the `guild_configs` table, which serves as the single
source of truth for all server-specific settings. It replaces the reliance on
global environment variables for configurable IDs and values, allowing for
true multi-guild support.

The `ConfigDB` class includes an in-memory cache to minimize database queries
for frequently accessed settings.
"""

from __future__ import annotations

import dataclasses
import logging
import types
from typing import TYPE_CHECKING, ClassVar, Union, get_args, get_origin, get_type_hints

from modules.Database import snowflake

from .dtypes import ChannelId, GuildId, MessageId, RoleId, RoleIdList, UserId

if TYPE_CHECKING:
    from modules.Database import Database

log = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class GuildConfig:
    """A type-safe dataclass to hold all configuration for a single guild."""

    guild_id: GuildId
    mod_log_channel_id: ChannelId | None = None
    join_leave_log_channel_id: ChannelId | None = None
    level_up_channel_id: ChannelId | None = None
    bot_warning_channel_id: ChannelId | None = None
    bumper_role_id: RoleId | None = None
    backup_bumper_role_id: RoleId | None = None
    muted_role_id: RoleId | None = None
    verified_role_id: RoleId | None = None
    automute_role_id: RoleId | None = None
    xp_opt_out_role_id: RoleId | None = None
    inactive_role_id: RoleId | None = None
    roles_to_prune: RoleIdList | None = None
    event_ping_roles: RoleIdList | None = None
    # Server Stats
    member_count_channel_id: ChannelId | None = None
    tag_role_id: RoleId | None = None
    tag_role_channel_id: ChannelId | None = None
    # Inactive Role
    inactive_role_threshold_days: int = 60
    # Pruning
    inactivity_days: int = 14
    custom_role_prefix: str = "Custom: "
    custom_role_prune_days: int = 30
    # QOTD Forwarder
    qotd_source_bot_id: UserId | None = None
    qotd_target_channel_id: ChannelId | None = None
    default_language: str = "en"
    guild_timezone: str | None = None
    # Voice chat
    vc_rgb_role_id: RoleId | None = None
    vc_activity_channel_id: ChannelId | None = None


_SNOWFLAKE_TYPES = {UserId, GuildId, ChannelId, RoleId, MessageId}
_CHILD_TABLE_FIELDS = frozenset({"roles_to_prune", "event_ping_roles"})
_CONFIG_FIELD_NAMES: frozenset[str] = frozenset(f.name for f in dataclasses.fields(GuildConfig))


def _unwrap(hint: type) -> type:
    """Strip X | None → X for Optional fields."""
    origin = get_origin(hint)
    if origin is types.UnionType or origin is Union:
        non_none = [a for a in get_args(hint) if a is not type(None)]
        return non_none[0] if non_none else hint
    return hint


def _is_optional(hint: type) -> bool:
    origin = get_origin(hint)
    if origin is types.UnionType or origin is Union:
        return type(None) in get_args(hint)
    return False


def _build_guild_configs_ddl(table: str) -> str:
    hints = get_type_hints(GuildConfig)
    cols: list[str] = []
    for f in dataclasses.fields(GuildConfig):
        if f.name in _CHILD_TABLE_FIELDS:
            continue
        hint = hints[f.name]
        inner = _unwrap(hint)
        optional = _is_optional(hint)
        has_real_default = f.default is not dataclasses.MISSING and f.default is not None

        if f.name == "guild_id":
            cols.append(f"guild_id INTEGER PRIMARY KEY {snowflake('guild_id')}")
            continue

        if inner in _SNOWFLAKE_TYPES:
            # Optional snowflake - no NOT NULL, no DEFAULT
            cols.append(f"{f.name} INTEGER {snowflake(f.name)}")
        elif inner is int:
            if optional:
                cols.append(f"{f.name} INTEGER")
            else:
                check = f" CHECK({f.name} > 0)" if f.name.endswith("_days") else ""
                default = f" DEFAULT {f.default}" if has_real_default else ""
                cols.append(f"{f.name} INTEGER NOT NULL{default}{check}")
        elif inner is str:
            if optional:
                cols.append(f"{f.name} TEXT")
            else:
                default = f" DEFAULT '{f.default}'" if has_real_default else ""
                cols.append(f"{f.name} TEXT NOT NULL{default}")

    return f"CREATE TABLE IF NOT EXISTS {table} (\n    " + ",\n    ".join(cols) + "\n) STRICT, WITHOUT ROWID"


class ConfigDB:
    """Manages the `guild_configs` table with an in-memory cache."""

    TABLE_NAME: ClassVar[str] = "guild_configs"

    def __init__(self, database: Database) -> None:
        self.database = database
        self._cache: dict[GuildId, GuildConfig] = {}

    async def post_init(self) -> None:
        """Initialize the database table for guild configurations."""
        async with self.database.get_conn() as conn:
            await conn.execute(_build_guild_configs_ddl(self.TABLE_NAME))
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS guild_prune_roles (
                    guild_id INTEGER NOT NULL REFERENCES {self.TABLE_NAME}(guild_id) ON DELETE CASCADE,
                    role_id  INTEGER NOT NULL {snowflake("role_id")},
                    PRIMARY KEY (guild_id, role_id)
                ) STRICT, WITHOUT ROWID
            """)
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS guild_event_ping_roles (
                    guild_id INTEGER NOT NULL REFERENCES {self.TABLE_NAME}(guild_id) ON DELETE CASCADE,
                    role_id  INTEGER NOT NULL {snowflake("role_id")},
                    PRIMARY KEY (guild_id, role_id)
                ) STRICT, WITHOUT ROWID
            """)
            await conn.commit()
            log.info("Initialized guild_configs database table.")

    def _invalidate_cache(self, guild_id: GuildId) -> None:
        """Remove a guild's configuration from the cache."""
        self._cache.pop(guild_id, None)
        log.debug("Invalidated cache for guild ID %s.", guild_id)

    async def get_guild_config(self, guild_id: GuildId) -> GuildConfig:
        """Fetch all settings for a guild, using the cache if available.

        If no configuration exists, a default one is returned but not saved.
        """
        if guild_id in self._cache:
            return self._cache[guild_id]

        async with self.database.get_cursor() as cursor:
            field_names = [f.name for f in dataclasses.fields(GuildConfig) if f.name not in _CHILD_TABLE_FIELDS]
            await cursor.execute(
                f"SELECT {', '.join(field_names)} FROM {self.TABLE_NAME} WHERE guild_id = ?",  # noqa: S608
                (guild_id,),
            )
            row = await cursor.fetchone()

            if row:
                config = GuildConfig(**dict(zip(field_names, row, strict=True)))

                prune_rows = await (
                    await cursor.execute("SELECT role_id FROM guild_prune_roles WHERE guild_id = ?", (guild_id,))
                ).fetchall()
                config.roles_to_prune = [RoleId(r[0]) for r in prune_rows] or None

                ping_rows = await (
                    await cursor.execute("SELECT role_id FROM guild_event_ping_roles WHERE guild_id = ?", (guild_id,))
                ).fetchall()
                config.event_ping_roles = [RoleId(r[0]) for r in ping_rows] or None
            else:
                config = GuildConfig(guild_id=guild_id)

        self._cache[guild_id] = config
        return config

    async def set_setting(self, guild_id: GuildId, setting: str, value: int | str | RoleIdList | None) -> None:
        """Update a single configuration value for a guild."""
        if setting not in _CONFIG_FIELD_NAMES:
            msg = f"'{setting}' is not a valid configuration setting."
            raise ValueError(msg)

        async with self.database.get_conn() as conn:
            if setting == "roles_to_prune":
                await conn.execute(
                    f"INSERT OR IGNORE INTO {self.TABLE_NAME}(guild_id) VALUES (?)",  # noqa: S608
                    (guild_id,),
                )
                await conn.execute("DELETE FROM guild_prune_roles WHERE guild_id = ?", (guild_id,))
                if isinstance(value, list):
                    await conn.executemany(
                        "INSERT INTO guild_prune_roles VALUES (?, ?)",
                        [(guild_id, r) for r in value],
                    )
            elif setting == "event_ping_roles":
                await conn.execute(
                    f"INSERT OR IGNORE INTO {self.TABLE_NAME}(guild_id) VALUES (?)",  # noqa: S608
                    (guild_id,),
                )
                await conn.execute("DELETE FROM guild_event_ping_roles WHERE guild_id = ?", (guild_id,))
                if isinstance(value, list):
                    await conn.executemany(
                        "INSERT INTO guild_event_ping_roles VALUES (?, ?)",
                        [(guild_id, r) for r in value],
                    )
            else:
                sql = f"""
                    INSERT INTO {self.TABLE_NAME} (guild_id, {setting}) VALUES (?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET {setting} = excluded.{setting}
                """  # noqa: S608
                await conn.execute(sql, (guild_id, value))
            await conn.commit()

        self._invalidate_cache(guild_id)
        log.info("Updated setting '%s' for guild %s.", setting, guild_id)

    async def on_guild_remove(self, guild_id: GuildId) -> None:
        """Clean up data when the bot is removed from a guild."""
        async with self.database.get_conn() as conn:
            await conn.execute(f"DELETE FROM {self.TABLE_NAME} WHERE guild_id = ?", (guild_id,))  # noqa: S608
            await conn.commit()

        self._invalidate_cache(guild_id)
        log.info("Removed configuration for guild %s.", guild_id)
