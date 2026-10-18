"""Telegram bridge: your phone <-> the bus.

  incoming message from ALLOWED_CHAT_ID  -> publish sense.chat {text, chat_id, ts}
  out.notify {text}                      -> send to ALLOWED_CHAT_ID

Only the one allowed chat is accepted; everything else is ignored.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime

import httpx

from mycelium_sdk import Message, NatsBus

log = logging.getLogger("mycelium.telegram")


async def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = int(os.environ["TELEGRAM_CHAT_ID"])
    api = f"https://api.telegram.org/bot{token}"
    bus = NatsBus(os.environ.get("NATS_URL", "nats://nats:4222"), name="telegram")
    await bus.connect()

    async with httpx.AsyncClient(timeout=60) as http:

        async def on_notify(msg: Message) -> None:
            text = str(msg.data.get("text", ""))[:4000]
            if text:
                await http.post(f"{api}/sendMessage", json={"chat_id": chat_id, "text": text})

        await bus.subscribe("out.notify", on_notify)

        offset = 0
        while True:
            try:
                r = await http.get(f"{api}/getUpdates", params={"timeout": 50, "offset": offset})
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    m = upd.get("message") or {}
                    if m.get("chat", {}).get("id") != chat_id or "text" not in m:
                        continue
                    await bus.publish(
                        "sense.chat",
                        {
                            "source": "telegram",
                            "text": m["text"],
                            "chat_id": chat_id,
                            "ts": datetime.now(UTC).isoformat(),
                        },
                    )
            except Exception:
                log.exception("telegram poll failed; retrying")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
