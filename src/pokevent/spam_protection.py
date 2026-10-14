"""Short-lived, content-free detection of cross-channel message floods.

The detector is deliberately independent of Discord and the database so it can
be tested without network access. This is *reactive* moderation: a gateway
message has already been sent by the time we observe it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic

WINDOW_SECONDS = 15
MESSAGE_LIMIT = 5
CHANNEL_LIMIT = 3
BLOCK_SECONDS = 10 * 60
MAX_HISTORY = 50


@dataclass(frozen=True)
class SpamDecision:
    blocked: bool = False
    newly_triggered: bool = False
    targets: tuple[tuple[int, int], ...] = ()
    message_count: int = 0
    channel_count: int = 0


class SpamDetector:
    def __init__(self) -> None:
        # Keys are (guild ID, user ID); entries are (time, channel ID, message ID).
        self._history: dict[tuple[int, int], deque[tuple[float, int, int]]] = {}
        self._blocked_until: dict[tuple[int, int], float] = {}
        self._last_cleanup = 0.0

    def clear_guild(self, guild_id: int) -> None:
        """Immediately drop enforcement state when a server switches protection off."""
        for key in list(self._history):
            if key[0] == guild_id:
                del self._history[key]
        for key in list(self._blocked_until):
            if key[0] == guild_id:
                del self._blocked_until[key]

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        for key, history in list(self._history.items()):
            while history and now - history[0][0] > WINDOW_SECONDS:
                history.popleft()
            if not history:
                del self._history[key]
        for key, expiry in list(self._blocked_until.items()):
            if expiry <= now:
                del self._blocked_until[key]

    def observe(
        self,
        guild_id: int,
        user_id: int,
        channel_id: int,
        message_id: int,
        *,
        now: float | None = None,
    ) -> SpamDecision:
        if now is None:
            now = monotonic()
        self._cleanup(now)

        key = (guild_id, user_id)
        if self._blocked_until.get(key, 0) > now:
            return SpamDecision(blocked=True, targets=((channel_id, message_id),))
        self._blocked_until.pop(key, None)

        history = self._history.setdefault(key, deque())
        history.append((now, channel_id, message_id))
        while history and now - history[0][0] > WINDOW_SECONDS:
            history.popleft()
        while len(history) > MAX_HISTORY:
            history.popleft()

        channel_count = len({entry[1] for entry in history})
        if len(history) < MESSAGE_LIMIT or channel_count < CHANNEL_LIMIT:
            return SpamDecision()

        targets = tuple((channel, message) for _, channel, message in history)
        self._history.pop(key, None)
        self._blocked_until[key] = now + BLOCK_SECONDS
        return SpamDecision(
            blocked=True,
            newly_triggered=True,
            targets=targets,
            message_count=len(targets),
            channel_count=channel_count,
        )
