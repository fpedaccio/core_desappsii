"""Bounded, process-local fixed-window limiter for authentication."""

import math
import time
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock


class AuthRateLimiter:
    """Ten admitted attempts per key in sixty seconds by default.

    State is local to this instance, not shared across processes.
    Full capacity rejects new keys instead of evicting active counters.
    """

    def __init__(
        self,
        limit: int = 10,
        window: float = 60,
        capacity: int = 5000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window <= 0 or capacity < 1:
            raise ValueError("Limiter settings must be positive")
        self.limit = limit
        self.window = window
        self.capacity = capacity
        self.clock = clock
        self._buckets: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._lock = Lock()

    def check(self, key: str) -> int:
        """Return zero if admitted, otherwise Retry-After in seconds."""
        with self._lock:
            now = self.clock()
            while self._buckets:
                first_key = next(iter(self._buckets))
                expires, _ = self._buckets[first_key]
                if expires > now:
                    break
                del self._buckets[first_key]

            if key in self._buckets:
                expires, count = self._buckets[key]
                if count >= self.limit:
                    return max(1, math.ceil(expires - now))
                self._buckets[key] = (expires, count + 1)
                return 0

            if len(self._buckets) >= self.capacity:
                expires, _ = next(iter(self._buckets.values()))
                return max(1, math.ceil(expires - now))

            self._buckets[key] = (now + self.window, 1)
            return 0
