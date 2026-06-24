"""Tiny in-process TTL cache for hot, expensive metrics (e.g. admin dashboard).

This is intentionally simple and per-process. In a multi-instance deployment a
shared cache (Redis) would replace it; the interface is kept minimal so that swap
is easy.
"""
import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic() + self.ttl, value)

    def clear(self) -> None:
        self._store.clear()
