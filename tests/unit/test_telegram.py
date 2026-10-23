"""The Telegram channel: updates -> bus events, bus outputs -> API calls. No network."""

import pytest

from mycelium_sdk import InMemoryBus
from telegram_bridge import ChatIn, Feedback, TelegramAPI, TelegramBridge, chunks, keyboard, parse_update

CHAT = 4242


def text_update(text, chat=CHAT, update_id=1):
    return {"update_id": update_id, "message": {"message_id": 7, "chat": {"id": chat}, "text": text}}


def tap_update(ref, idx, chat=CHAT, choices=("7pm", "9pm")):
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb1",
            "data": f"{ref}:{idx}",
            "message": {
                "message_id": 9,
                "chat": {"id": chat},
                "text": "Which one?",
                "reply_markup": keyboard(ref, list(choices)),
            },
        },
    }


def test_parse_text_from_allowed_chat_only():
    assert parse_update(text_update("hi"), CHAT) == ChatIn(text="hi", thread="4242", message_id=7)
    assert parse_update(text_update("hi", chat=1), CHAT) is None
    assert parse_update({"update_id": 3, "message": {"chat": {"id": CHAT}, "photo": []}}, CHAT) is None
    assert parse_update({"update_id": 4, "edited_message": {}}, CHAT) is None


def test_parse_button_tap_recovers_the_answer_text():
    fb = parse_update(tap_update("abc123", 1), CHAT)
    assert fb == Feedback(
        ref="abc123", answer="9pm", thread="4242", callback_id="cb1", message_id=9, message_text="Which one?"
    )
    assert parse_update(tap_update("abc123", 1, chat=1), CHAT) is None
    assert (
        parse_update(
            {"update_id": 5, "callback_query": {"id": "x", "data": "", "message": {"chat": {"id": CHAT}}}}, CHAT
        )
        is None
    )


def test_keyboard_one_button_per_choice_with_short_callback_data():
    kb = keyboard("0192f3a1b2c3d4e5f6a7b", ["7pm", "9pm"])
    assert [row[0]["text"] for row in kb["inline_keyboard"]] == ["7pm", "9pm"]
    assert kb["inline_keyboard"][1][0]["callback_data"] == "0192f3a1b2c3d4e5f6a7b:1"
    assert all(len(row[0]["callback_data"].encode()) <= 64 for row in kb["inline_keyboard"])
    with pytest.raises(ValueError, match="64 bytes"):
        keyboard("r" * 70, ["a", "b"])


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class FakeHTTP:
    def __init__(self, body):
        self.body = body

    async def get(self, url, params=None):
        return FakeResponse(self.body)


async def test_get_updates_error_raises_so_poll_backs_off():
    api = TelegramAPI(
        "token", FakeHTTP({"ok": False, "error_code": 409, "description": "Conflict: terminated by other"})
    )
    with pytest.raises(RuntimeError, match="Conflict"):
        await api.updates(0)
    assert await TelegramAPI("token", FakeHTTP({"ok": True, "result": []})).updates(0) == []


def test_chunks_respects_the_limit():
    assert chunks("") == ["(empty)"]
    parts = chunks("x" * 9000)
    assert [len(p) for p in parts] == [4000, 4000, 1000]


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def call(self, method, **params):
        self.calls.append((method, params))
        return {"message_id": 1}


@pytest.fixture
async def bridge():
    bus = InMemoryBus()
    b = TelegramBridge(bus, FakeAPI(), CHAT)
    await b.start()
    return b


async def test_say_goes_only_to_this_channel_and_thread(bridge):
    await bridge.bus.publish("out.say", {"channel": "telegram", "thread": "4242", "text": "hello"})
    await bridge.bus.publish("out.say", {"channel": "cli", "thread": "x", "text": "not for the phone"})
    await bridge.bus.publish("out.say", {"channel": "telegram", "thread": "999", "text": "other chat"})
    await bridge.bus.publish("out.say", {"thread": "4242", "text": "no channel"})
    assert bridge.api.calls == [("sendMessage", {"chat_id": CHAT, "text": "hello"})]


async def test_notify_reaches_the_phone_even_unaddressed(bridge):
    await bridge.bus.publish("out.notify", {"text": "someone at the door"})
    await bridge.bus.publish("out.notify", {"channel": "cli", "text": "not here"})
    assert bridge.api.calls == [("sendMessage", {"chat_id": CHAT, "text": "someone at the door"})]


async def test_blank_say_and_notify_send_nothing(bridge):
    await bridge.bus.publish("out.notify", {})
    await bridge.bus.publish("out.notify", {"text": "   "})
    await bridge.bus.publish("out.say", {"channel": "telegram", "thread": "4242", "text": ""})
    assert bridge.api.calls == []


async def test_long_ref_is_shortened_for_callback_data_and_restored_on_tap(bridge):
    ref = "module-question-" + "x" * 70
    await bridge.bus.publish("out.ask", {"ref": ref, "text": "Approve?", "choices": ["yes", "no"]})
    _, params = bridge.api.calls[0]
    buttons = [row[0] for row in params["reply_markup"]["inline_keyboard"]]
    assert all(len(b["callback_data"].encode()) <= 64 for b in buttons)
    tap = {
        "update_id": 2,
        "callback_query": {
            "id": "cb9",
            "data": buttons[1]["callback_data"],
            "message": {
                "message_id": 9,
                "chat": {"id": CHAT},
                "text": "Approve?",
                "reply_markup": params["reply_markup"],
            },
        },
    }
    await bridge.handle_update(tap)
    fb = bridge.bus.events("sense.feedback")[0][1]
    assert fb["ref"] == ref and fb["answer"] == "no"  # the full ref comes back, not the token


async def test_ask_renders_buttons(bridge):
    await bridge.bus.publish(
        "out.ask",
        {
            "id": "r1",
            "ref": "r1",
            "channel": "telegram",
            "thread": "4242",
            "text": "7 or 9?",
            "choices": ["7pm", "9pm"],
        },
    )
    method, params = bridge.api.calls[0]
    assert method == "sendMessage" and params["text"] == "7 or 9?"
    assert params["reply_markup"] == keyboard("r1", ["7pm", "9pm"])


async def test_long_say_is_split(bridge):
    await bridge.bus.publish("out.say", {"channel": "telegram", "thread": "4242", "text": "y" * 5000})
    assert [len(p["text"]) for _, p in bridge.api.calls] == [4000, 1000]


async def test_text_update_becomes_sense_chat(bridge):
    await bridge.handle_update(text_update("dinner 350"))
    events = bridge.bus.events("sense.chat")
    assert len(events) == 1
    e = events[0][1]
    assert e["text"] == "dinner 350" and e["channel"] == "telegram" and e["thread"] == "4242"
    assert e["source"] == "telegram" and e["id"] and e["ts"] and e["cause"] is None
    assert bridge.api.calls == []


async def test_tap_becomes_feedback_and_the_buttons_are_closed(bridge):
    await bridge.handle_update(tap_update("ask77", 0))
    fb = bridge.bus.events("sense.feedback")[0][1]
    assert fb["ref"] == "ask77" and fb["answer"] == "7pm" and fb["channel"] == "telegram" and fb["thread"] == "4242"
    assert bridge.api.calls[0] == ("answerCallbackQuery", {"callback_query_id": "cb1"})
    assert bridge.api.calls[1] == ("editMessageText", {"chat_id": CHAT, "message_id": 9, "text": "Which one?\n\n✓ 7pm"})


async def test_updates_from_strangers_do_nothing(bridge):
    await bridge.handle_update(text_update("hi", chat=1))
    assert bridge.bus.published == [] and bridge.api.calls == []
