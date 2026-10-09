from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
import time


class SlidingWindowLimiter:
    """Small single-process limiter for development and one-container deployments."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window_seconds - now))
                return False, retry_after
            events.append(now)
            if len(self._events) > 10_000:
                self._events = defaultdict(
                    deque,
                    {name: values for name, values in self._events.items() if values},
                )
            return True, 0


limiter = SlidingWindowLimiter()
