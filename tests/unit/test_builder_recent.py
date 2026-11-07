"""Recent: an answer kept a few seconds, one question in flight however many callers ask at once."""

import asyncio

import pytest

from builder.recent import Recent


async def test_callers_that_ask_together_share_one_question():
    asked = 0
    gate = asyncio.Event()

    async def fetch():
        nonlocal asked
        asked += 1
        await gate.wait()
        return {"answer": asked}

    recent = Recent(fetch, ttl=0)
    waiting = [asyncio.create_task(recent.get()) for _ in range(5)]
    await asyncio.sleep(0)
    gate.set()
    assert await asyncio.gather(*waiting) == [{"answer": 1}] * 5 and asked == 1
    assert await recent.get() == {"answer": 2}  # ttl 0: the next call asks again


async def test_a_caller_that_gives_up_does_not_cancel_the_others():
    gate = asyncio.Event()

    async def fetch():
        await gate.wait()
        return "up"

    recent = Recent(fetch, ttl=0)
    impatient, patient = asyncio.create_task(recent.get()), asyncio.create_task(recent.get())
    await asyncio.sleep(0)
    impatient.cancel()
    gate.set()
    assert await patient == "up"


async def test_an_answer_is_kept_for_its_ttl_and_none_or_an_error_is_not():
    answers: list = [None, RuntimeError("down"), "up"]

    async def fetch():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    recent = Recent(fetch, ttl=60)
    assert await recent.get() is None
    with pytest.raises(RuntimeError, match="down"):
        await recent.get()
    assert await recent.get() == "up"
    assert await recent.get() == "up"  # kept: asking again would pop an empty list
