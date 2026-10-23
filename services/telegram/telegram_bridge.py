"""Telegram channel: your phone <-> the bus (ARCHITECTURE §8). Carries messages, never decides.

  text from the allowed chat        -> sense.chat     {id, ts, source, channel: telegram, thread, text}
  button tap                        -> sense.feedback {id, ts, ref, answer, channel, thread}
  out.say  {channel: telegram, thread, text}      -> message to that chat
  out.ask  {channel?, thread?, text, choices, ref} -> message with one button per choice
  out.notify {text}                               -> message (unaddressed notifications reach the phone)

Only the one allowed chat is accepted; everything else is ignored.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from pydantic import BaseModel, Field

from mycelium_sdk import Bus, Envelope, Message, NatsBus, ServiceSettings

log = logging.getLogger("mycelium.telegram")

CHANNEL = "telegram"
MAX_CHARS = 4000  # Telegram caps a message at 4096
MAX_CALLBACK_BYTES = 64  # Telegram caps callback_data at 64 bytes
MAX_REMEMBERED_REFS = 500  # long refs are swapped for a short token until the tap comes back


class ChatIn(BaseModel):
    text: str
    thread: str
    message_id: int | None = None


class Feedback(BaseModel):
    ref: str
    answer: str
    thread: str
    callback_id: str
    message_id: int | None = None
    message_text: str = ""


def keyboard(ref: str, choices: list[str]) -> dict[str, Any]:
    """One button per row; callback_data is '<ref>:<index>'. The bridge shortens refs that would not fit."""
    rows = [[{"text": c[:60], "callback_data": f"{ref}:{i}"}] for i, c in enumerate(choices)]
    if any(len(row[0]["callback_data"].encode()) > MAX_CALLBACK_BYTES for row in rows):
        raise ValueError(f"callback_data over {MAX_CALLBACK_BYTES} bytes; shorten the ref")
    return {"inline_keyboard": rows}


def parse_update(upd: dict[str, Any], allowed_chat_id: int) -> ChatIn | Feedback | None:
    if m := upd.get("message"):
        if (m.get("chat") or {}).get("id") != allowed_chat_id or not isinstance(m.get("text"), str):
            return None
        return ChatIn(text=m["text"], thread=str(allowed_chat_id), message_id=m.get("message_id"))
    if cq := upd.get("callback_query"):
        msg = cq.get("message") or {}
        if (msg.get("chat") or {}).get("id") != allowed_chat_id:
            return None
        data = str(cq.get("data") or "")
        ref, _, idx = data.rpartition(":")
        buttons = [b for row in (msg.get("reply_markup") or {}).get("inline_keyboard") or [] for b in row]
        try:
            answer = buttons[int(idx)]["text"]
        except (ValueError, IndexError, KeyError):
            answer = idx
        if not ref:
            return None
        return Feedback(
            ref=ref,
            answer=answer,
            thread=str(allowed_chat_id),
            callback_id=str(cq.get("id")),
            message_id=msg.get("message_id"),
            message_text=str(msg.get("text") or ""),
        )
    return None


def chunks(text: str, size: int = MAX_CHARS) -> list[str]:
    text = text.strip() or "(empty)"
    return [text[i : i + size] for i in range(0, len(text), size)]


class TelegramAPI:
    def __init__(self, token: str, http: Any) -> None:
        self.base = f"https://api.telegram.org/bot{token}"
        self.http = http

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        r = await self.http.post(f"{self.base}/{method}", json=params)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"telegram {method}: {body.get('description')}")
        return body.get("result") or {}

    async def updates(self, offset: int, timeout: int = 50) -> list[dict[str, Any]]:
        r = await self.http.get(f"{self.base}/getUpdates", params={"timeout": timeout, "offset": offset})
        body = r.json()
        if not body.get("ok"):  # bad token, a second poller (409), ...: raise so poll() backs off instead of spinning
            raise RuntimeError(f"telegram getUpdates: {body.get('description') or body}")
        return body.get("result") or []


class TelegramBridge:
    def __init__(self, bus: Bus, api: TelegramAPI, chat_id: int) -> None:
        self.bus = bus
        self.api = api
        self.chat_id = chat_id
        self.thread = str(chat_id)
        self._refs: dict[str, str] = {}  # short token -> full ref, for refs too long for callback_data

    async def start(self) -> None:
        await self.bus.subscribe("out.say", self.on_say)
        await self.bus.subscribe("out.ask", self.on_ask)
        await self.bus.subscribe("out.notify", self.on_notify)

    # ---- bus -> phone ------------------------------------------------------------------------

    def _addressed(self, data: dict[str, Any], default: bool) -> bool:
        channel = data.get("channel")
        if channel is None:
            return default
        return channel == CHANNEL and str(data.get("thread") or self.thread) == self.thread

    async def send(self, text: str, **extra: Any) -> None:
        parts = chunks(text)
        for part in parts[:-1]:
            await self.api.call("sendMessage", chat_id=self.chat_id, text=part)
        await self.api.call("sendMessage", chat_id=self.chat_id, text=parts[-1], **extra)

    async def on_say(self, msg: Message) -> None:
        text = str(msg.data.get("text") or "").strip()
        if text and self._addressed(msg.data, default=False):
            await self.send(text)

    async def on_notify(self, msg: Message) -> None:
        text = str(msg.data.get("text") or "").strip()
        if text and self._addressed(msg.data, default=True):  # a text-less notification is not for the phone
            await self.send(text)

    async def on_ask(self, msg: Message) -> None:
        if not self._addressed(msg.data, default=True):
            return
        ref = str(msg.data.get("ref") or msg.data.get("id") or "")
        choices = [str(c) for c in msg.data.get("choices") or []]
        if ref and choices:
            await self.send(str(msg.data.get("text") or ""), reply_markup=keyboard(self._token(ref), choices))
        else:
            await self.send(str(msg.data.get("text") or ""))

    def _token(self, ref: str) -> str:
        """The ref itself when it fits in callback_data next to ':<index>', else a short token mapped back on tap."""
        if len(ref.encode()) + 3 <= MAX_CALLBACK_BYTES:
            return ref
        token = hashlib.sha1(ref.encode()).hexdigest()[:20]
        self._refs[token] = ref
        while len(self._refs) > MAX_REMEMBERED_REFS:
            self._refs.pop(next(iter(self._refs)))
        return token

    # ---- phone -> bus ------------------------------------------------------------------------

    async def handle_update(self, upd: dict[str, Any]) -> None:
        parsed = parse_update(upd, self.chat_id)
        if isinstance(parsed, ChatIn):
            await self.bus.publish(
                "sense.chat",
                Envelope(source=CHANNEL).stamp(
                    channel=CHANNEL,
                    thread=parsed.thread,
                    text=parsed.text,
                    chat_id=self.chat_id,
                    message_id=parsed.message_id,
                ),
            )
        elif isinstance(parsed, Feedback):
            ref = self._refs.get(parsed.ref, parsed.ref)
            await self.bus.publish(
                "sense.feedback",
                Envelope(source=CHANNEL).stamp(channel=CHANNEL, thread=parsed.thread, ref=ref, answer=parsed.answer),
            )
            await self.api.call("answerCallbackQuery", callback_query_id=parsed.callback_id)
            if parsed.message_id is not None:
                await self.api.call(
                    "editMessageText",
                    chat_id=self.chat_id,
                    message_id=parsed.message_id,
                    text=f"{parsed.message_text}\n\n✓ {parsed.answer}",
                )

    async def poll(self) -> None:
        offset = 0
        while True:
            try:
                for upd in await self.api.updates(offset):
                    offset = int(upd["update_id"]) + 1
                    try:
                        await self.handle_update(upd)
                    except Exception:
                        log.exception("update %s failed", upd.get("update_id"))
            except Exception:
                log.exception("telegram poll failed; retrying")
                await asyncio.sleep(5)


class TelegramSettings(ServiceSettings):
    bot_token: str = Field(min_length=1, validation_alias="TELEGRAM_BOT_TOKEN")
    chat_id: int = Field(validation_alias="TELEGRAM_CHAT_ID", description="the one chat the bridge talks to")


async def main() -> None:
    import httpx

    s = TelegramSettings()
    logging.basicConfig(level=s.log_level)
    bus = NatsBus(s.nats_url, name="telegram")
    await bus.connect()
    async with httpx.AsyncClient(timeout=70) as http:
        bridge = TelegramBridge(bus, TelegramAPI(s.bot_token, http), s.chat_id)
        await bridge.start()
        log.info("telegram bridge ready for chat %s", s.chat_id)
        await bridge.poll()


if __name__ == "__main__":
    asyncio.run(main())
