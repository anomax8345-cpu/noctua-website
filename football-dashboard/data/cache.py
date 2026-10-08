"""A tiny thread-safe TTL cache.

Used to avoid hammering APIs: every rendering must NOT trigger fresh API calls.
Keys are arbitrary strings; values are kept with an expiry timestamp.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expiry, value = item
            if time.time() > expiry:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            self._store[key] = (time.time() + max(1, ttl), value)

    def get_or_set(self, key: str, ttl: int, producer: Callable[[], Any]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = producer()
        if value is not None:
            self.set(key, value, ttl)
        return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


CACHE = TTLCache()
