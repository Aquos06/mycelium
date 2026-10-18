"""hello: counts chat messages per day. The reference module the builder learns from."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from mycelium_sdk import Module


class Store:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(data_dir / "hello.sqlite3")
        self.db.execute("CREATE TABLE IF NOT EXISTS counts (day TEXT PRIMARY KEY, n INTEGER NOT NULL)")
        self.db.commit()

    def increment(self, day: str) -> int:
        self.db.execute("INSERT INTO counts (day, n) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET n = n + 1", (day,))
        self.db.commit()
        return self.get(day)

    def get(self, day: str) -> int:
        row = self.db.execute("SELECT n FROM counts WHERE day = ?", (day,)).fetchone()
        return row[0] if row else 0

    def total(self) -> int:
        row = self.db.execute("SELECT COALESCE(SUM(n), 0) FROM counts").fetchone()
        return int(row[0])


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def build(**kwargs) -> Module:
    mod = Module(**kwargs)
    store = Store(mod.data_dir)

    @mod.on("sense.chat")
    async def on_chat(msg):
        n = store.increment(today())
        await mod.emit("message.counted", {"day": today(), "count": n})
        if n in (10, 50, 100):
            await mod.observe("milestone", f"{n} chat messages today", {"count": n}, severity="info")

    @mod.on_request("stats")
    async def stats(data):
        day = data.get("day") or today()
        try:
            date.fromisoformat(day)
        except (TypeError, ValueError) as e:
            raise ValueError(f"day must be YYYY-MM-DD, got {day!r}") from e
        return {"day": day, "count": store.get(day), "total": store.total()}

    @mod.every(3600)
    async def hourly():
        await mod.observe("heartbeat", f"{store.get(today())} messages so far today", severity="info")

    return mod


if __name__ == "__main__":
    build().run()
