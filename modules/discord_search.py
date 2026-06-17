"""Discord guild message search API wrapper."""

import asyncio
import os
from typing import TYPE_CHECKING, Any

import aiohttp

from modules.errors import SearchError
from modules.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Callable

    from modules.dtypes import ChannelId, GuildId, MessageId, UserId


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bot {os.getenv('TOKEN')}"}


async def _guild_search[T](
    http_session: aiohttp.ClientSession,
    guild_id: GuildId,
    params: Any,  # noqa: ANN401
    on_200: Callable[[Any], Result[T, SearchError]],
    retry_on_429: bool = False,
    max_retries: int = 3,
) -> Result[T, SearchError]:
    url = f"https://discord.com/api/v10/guilds/{guild_id}/messages/search"
    last_status = 0
    for attempt in range(max_retries):
        try:
            async with http_session.get(url, params=params, headers=_auth_headers()) as resp:
                last_status = resp.status
                if resp.status == 200:
                    return on_200(await resp.json())
                if resp.status == 202:
                    await asyncio.sleep(2**attempt)
                    continue
                if resp.status == 429:
                    if retry_on_429:
                        try:
                            retry_data = await resp.json(content_type=None)
                            wait = float(retry_data.get("retry_after", 2**attempt))
                        except ValueError:
                            wait = float(2**attempt)
                        await asyncio.sleep(wait)
                        continue
                    return Err(SearchError("Rate limited by Discord"))
                if resp.status >= 500:
                    return Err(SearchError("Discord server error"))
                return Err(SearchError(f"HTTP {resp.status} from Discord API"))
        except aiohttp.ClientError as e:
            return Err(SearchError(f"Network error: {type(e).__name__}"))
        except (TimeoutError, ValueError) as e:
            return Err(SearchError(f"API error: {type(e).__name__}"))
    if last_status == 429:
        return Err(SearchError("Rate limited by Discord after retries"))
    return Err(SearchError("Search index not ready after retries"))


def _total_results(data: Any) -> Result[int, SearchError]:  # noqa: ANN401
    return Ok(data.get("total_results", 0))


async def count_messages_in_range(
    http_session: aiohttp.ClientSession,
    guild_id: GuildId,
    channel_id: ChannelId,
    lo_id: MessageId,
    hi_id: MessageId,
    max_retries: int = 3,
) -> Result[int, SearchError]:
    """Count messages in a channel within a snowflake ID range."""
    return await _guild_search(
        http_session,
        guild_id,
        {"channel_id": [channel_id], "min_id": lo_id, "max_id": hi_id, "limit": 1, "include_nsfw": "true"},
        _total_results,
        max_retries=max_retries,
    )


async def fetch_author_stats(
    http_session: aiohttp.ClientSession,
    guild_id: GuildId,
    user_id: UserId,
    max_retries: int = 5,
) -> Result[tuple[int, str | None], SearchError]:
    """Return (message_count, last_message_timestamp) for a user in the guild.

    Timestamp is ISO-8601 or None if the user has no messages.
    """

    def extract(data: Any) -> Result[tuple[int, str | None], SearchError]:  # noqa: ANN401
        count: int = data.get("total_results", 0)
        for group in data.get("messages", []):
            for msg in group:
                if msg.get("hit") is True:
                    return Ok((count, msg["timestamp"]))
        return Ok((count, None))

    return await _guild_search(
        http_session,
        guild_id,
        {"author_id": user_id, "sort_by": "timestamp", "sort_order": "desc", "limit": 1, "include_nsfw": "true"},
        extract,
        retry_on_429=True,
        max_retries=max_retries,
    )
