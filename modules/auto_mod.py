from __future__ import annotations

import enum
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from modules.BotCore import BotCore

log = logging.getLogger(__name__)

# Accounts newer to the guild than this are kicked instead of timed out (likely raid/throwaway accounts).
NEW_MEMBER_THRESHOLD: timedelta = timedelta(days=3)


class ModerationOutcome(enum.Enum):
    KICKED = enum.auto()
    TIMED_OUT = enum.auto()
    FAILED = enum.auto()


def is_new_member(member: discord.Member) -> bool:
    return member.joined_at is not None and (discord.utils.utcnow() - member.joined_at) < NEW_MEMBER_THRESHOLD


async def escalate_member(
    bot: BotCore,
    member: discord.Member,
    guild: discord.Guild,
    *,
    reason: str,
    trigger: str,
    timeout_duration: timedelta,
    warning_type: str,
) -> ModerationOutcome:
    """Kick recently-joined members (likely raid accounts); fall back to timeout, then to a warning.

    On permission/hierarchy failure, dispatches a cooldown-collapsed `security_alert` under
    `warning_type`. Callers are responsible for their own success-side logging/alerting.
    """
    attempted_kick = is_new_member(member) and guild.me.guild_permissions.kick_members
    can_timeout = guild.me.guild_permissions.moderate_members

    if not attempted_kick and not can_timeout:
        _alert_no_action(bot, guild, member, trigger=trigger, action="no timeout", warning_type=warning_type)
        return ModerationOutcome.FAILED

    if member.is_timed_out():
        return ModerationOutcome.FAILED

    if attempted_kick:
        try:
            await member.kick(reason=f"Auto: {reason}, recently joined")
        except discord.Forbidden, discord.HTTPException:
            log.warning("Failed to kick %s in guild %s, falling back to timeout", member, guild.id)
        else:
            log.info("Auto-kicked new member %s in guild %s for %s", member, guild.id, reason)
            return ModerationOutcome.KICKED

    if can_timeout:
        try:
            await member.timeout(timeout_duration, reason=f"Auto: {reason}")
        except discord.Forbidden, discord.HTTPException:
            log.warning("Failed to timeout %s in guild %s", member, guild.id)
        else:
            log.info("Auto-timed out %s in guild %s for %s", member, guild.id, reason)
            return ModerationOutcome.TIMED_OUT

    action = "neither kick nor timeout" if attempted_kick else "no timeout"
    _alert_no_action(bot, guild, member, trigger=trigger, action=action, warning_type=warning_type)
    return ModerationOutcome.FAILED


def _alert_no_action(
    bot: BotCore,
    guild: discord.Guild,
    member: discord.Member,
    *,
    trigger: str,
    action: str,
    warning_type: str,
) -> None:
    bot.dispatch(
        "security_alert",
        guild_id=guild.id,
        risk_level="HIGH",
        details=(
            "**Auto-Moderation Failed**\n"
            f"{trigger} from {member.mention} but {action} could be applied "
            "(missing permission or role hierarchy)."
        ),
        warning_type=warning_type,
    )
