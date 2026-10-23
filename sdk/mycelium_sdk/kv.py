"""Key-value store: NATS KV for real, a dict for tests.

Used for small, rebuildable state: Main's conversation threads, the gateway's monthly usage counter.
Nothing here is the source of truth; everything can be rebuilt from `events`.

NATS KV keys may only contain `-/_=.a-zA-Z0-9` and may not start or end with `.` or contain `..`
(a key is a subject; `.` separates tokens). `kv_key()` turns anything else into something valid.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Protocol

_BAD = re.compile(r"[^-/_=.a-zA-Z0-9]")
_DOTS = re.compile(r"\.{2,}")


def kv_key(*parts: str) -> str:
    """Join parts with '/'; bad characters become '_', dots never lead, trail or repeat."""
    out: list[str] = []
    for p in parts:
        raw = str(p)
        if not raw:
            continue  # empty parts are dropped
        s = _DOTS.sub(".", _BAD.sub("_", raw)).strip(".")
        out.append(s or "_")  # a part that was only dots still has to occupy its place
    return "/".join(out)


class KV(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def put(self, key: str, value: dict[str, Any]) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def keys(self, prefix: str = "") -> list[str]: ...


class InMemoryKV:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        v = self._data.get(key)
        return copy.deepcopy(v) if v is not None else None

    async def put(self, key: str, value: dict[str, Any]) -> None:
        self._data[key] = copy.deepcopy(value)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def keys(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self._data if k.startswith(prefix))


class NatsKV:
    """A JetStream KV bucket. `open()` creates the bucket when it does not exist."""

    def __init__(self, nc, bucket: str, history: int = 1) -> None:
        self._nc = nc
        self.bucket = bucket
        self.history = history
        self._kv = None

    async def open(self) -> NatsKV:
        from nats.js.api import KeyValueConfig

        js = self._nc.jetstream()
        try:
            self._kv = await js.key_value(self.bucket)
        except Exception:
            self._kv = await js.create_key_value(KeyValueConfig(bucket=self.bucket, history=self.history))
        return self

    @property
    def kv(self):
        if self._kv is None:
            raise RuntimeError(f"kv bucket {self.bucket!r} not opened")
        return self._kv

    async def get(self, key: str) -> dict[str, Any] | None:
        from nats.js.errors import KeyNotFoundError

        try:
            entry = await self.kv.get(key)
        except KeyNotFoundError:
            return None
        if entry.value is None:
            return None
        value = json.loads(entry.value)
        return value if isinstance(value, dict) else {"value": value}

    async def put(self, key: str, value: dict[str, Any]) -> None:
        await self.kv.put(key, json.dumps(value, default=str).encode())

    async def delete(self, key: str) -> None:
        from nats.js.errors import KeyNotFoundError

        try:
            await self.kv.purge(key)
        except KeyNotFoundError:
            return

    async def keys(self, prefix: str = "") -> list[str]:
        from nats.js.errors import NoKeysError

        try:
            all_keys = await self.kv.keys()
        except NoKeysError:
            return []
        return sorted(k for k in all_keys if k.startswith(prefix))
