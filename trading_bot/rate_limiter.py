"""
Sliding-window rate limiter.

Thread-safe: uses a lock around the shared deque so the same instance
can be checked from multiple coroutines running in one event loop, or
from threads if you ever move to a threaded executor.
"""
import time
from collections import deque
from threading import Lock


class RateLimiter:
    """
    Allow at most *max_calls* events inside any rolling *period_seconds* window.

    Example
    -------
    limiter = RateLimiter(max_calls=5, period_seconds=60)
    if limiter.is_allowed():
        do_thing()
    """

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be positive")

        self.max_calls = max_calls
        self.period = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = Lock()

    def is_allowed(self) -> bool:
        """Return True and record the call if within the rate limit."""
        with self._lock:
            now = time.monotonic()
            self._evict(now)
            if len(self._timestamps) < self.max_calls:
                self._timestamps.append(now)
                return True
            return False

    def remaining(self) -> int:
        """Number of calls still available in the current window."""
        with self._lock:
            self._evict(time.monotonic())
            return max(0, self.max_calls - len(self._timestamps))

    def _evict(self, now: float) -> None:
        cutoff = now - self.period
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
