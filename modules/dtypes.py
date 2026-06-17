from dataclasses import dataclass
from typing import Literal, NewType, TypeIs, cast

import discord

# Nominal Types for Discord IDs
# Using NewType creates distinct types that are not interchangeable.
# A function expecting a GuildId will raise a type error if given a UserId.
UserId = NewType("UserId", int)
GuildId = NewType("GuildId", int)
ChannelId = NewType("ChannelId", int)
RoleId = NewType("RoleId", int)
MessageId = NewType("MessageId", int)
type RoleIdList = list[RoleId]

DISCORD_EPOCH_MS: int = 1_420_070_400_000


# Semantic Type Aliases
# For complex types that appear in multiple places.
@dataclass(frozen=True, slots=True)
class Member:
    user_id: UserId
    guild_id: GuildId


# Literals for Closed Sets of Values
# Enforces that a variable must be one of these specific string values.
type ReminderPreference = Literal["ONCE", "ALWAYS", "NEVER"]
type AnalysisStatus = Literal["OK", "ERROR", "WARN"]

# A specific type for an inviter ID, which can be a real user or unknown (None).
type InviterId = UserId | None

# A new nominal type for integers that represent quantities and should be positive.
PositiveInt = NewType("PositiveInt", int)
NonNegativeInt = NewType("NonNegativeInt", int)


def is_positive(num: int) -> TypeIs[PositiveInt]:
    """Safely cast an int to a PositiveInt."""
    return num > 0


def is_non_negative(num: int) -> TypeIs[NonNegativeInt]:
    """Check if a number is a non-negative integer (>= 0)."""
    return num >= 0


# Define a more specific type for a message we know is from a guild
class GuildMessage(discord.Message):
    author: discord.Member = cast("discord.Member", None)
    guild: discord.Guild = cast("discord.Guild", None)


class GuildInteraction(discord.Interaction):
    # We explicitly tell the type checker: "In this subclass, guild is NOT None"
    guild: discord.Guild
    # You might also want to assert user is a Member, not just User
    user: discord.Member


def is_guild_message(message: discord.Message) -> TypeIs[GuildMessage]:
    """Check if a message is from a guild context."""
    return message.guild is not None and isinstance(message.author, discord.Member)


@dataclass(frozen=True, slots=True)
class UserVoiceStats:
    """Aggregate voice chat stats for a user."""

    total_minutes: int
    peak_day: str | None
    last_seen: str | None


@dataclass(frozen=True, slots=True)
class ErasureReport:
    """Summary of rows deleted during user erasure."""

    positions: int
    reminders: int
    invites: int
    users: int
    voicechat_sessions_deleted: int = 0


@dataclass(frozen=True, slots=True)
class UserGuildRow:
    """User data for a single guild membership."""

    guild_id: GuildId
    currency: int
    xp: int
    bumps: int
    level: int
    last_active_timestamp: int
    native_language: str | None
    timezone: str
    daily_reminder_preference: ReminderPreference


@dataclass(frozen=True, slots=True)
class UserInvite:
    """User's invite record."""

    inviter_id: InviterId
    guild_id: GuildId
    joined_at: str


@dataclass(frozen=True, slots=True)
class UserReminder:
    """User's reminder record."""

    message: str
    remind_at: int
    created_at: int


@dataclass(frozen=True, slots=True)
class UserLedgerRow:
    """A single currency ledger entry involving the user."""

    guild_id: GuildId
    timestamp: int
    event_type: str
    event_reason: str
    sender_id: int
    receiver_id: int
    amount: int
    initiator_id: int | None
    reference_id: str | None


@dataclass(frozen=True, slots=True)
class UserPosition:
    """User's trading position."""

    ticker: str
    notional_dollars: int
    collateral_dollars: int
    entry_price: float
    timestamp: int


@dataclass(frozen=True, slots=True)
class MemberEvent:
    """A single member count event to be stored in the database."""

    message_id: MessageId
    guild_id: GuildId
    channel_id: ChannelId
    bot_id: UserId
    delta: int
    anchor_count: int | None


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Summary of a reconcile pass."""

    rows_updated: int
    max_drift: int
    current_count: int


@dataclass(frozen=True, slots=True)
class UserDataReport:
    """All personal data stored for a user across all tables."""

    user_id: UserId
    guilds: list[UserGuildRow]
    invites: list[UserInvite]
    reminders: list[UserReminder]
    positions: list[UserPosition]
    ledger: list[UserLedgerRow]
    voice: UserVoiceStats | None = None
