"""services/nats/nats.conf and the SDK agree on what a module may do on the bus."""

import re
from pathlib import Path

from mycelium_sdk.subjects import MODULE_ANSWERS, MODULE_LISTENS, MODULE_PUBLISHES

CONF = (Path(__file__).resolve().parents[2] / "services" / "nats" / "nats.conf").read_text()


def _allowed(kind: str) -> set[str]:
    block = CONF[CONF.index("user: module") :]
    m = re.search(rf"{kind}: {{ allow: \[([^\]]*)\] }}", block)
    assert m, f"no {kind} allow list for the module user"
    return {s.strip().strip('"') for s in m.group(1).split(",")}


def test_the_module_login_allows_what_the_sdk_says_and_nothing_else():
    assert _allowed("publish") == set(MODULE_PUBLISHES)
    assert _allowed("subscribe") == {*MODULE_LISTENS, MODULE_ANSWERS}
    assert "allow_responses: true" in CONF


def test_no_module_may_ask_for_anything():
    allowed = _allowed("publish") | _allowed("subscribe")
    assert not any(
        s.startswith(("rpc.sys", "rpc.build", "rpc.llm", "rpc.memory", "trace", "stream", "_INBOX", "$JS"))
        for s in allowed
    )
    assert ">" not in allowed and "rpc.>" not in allowed


def test_both_passwords_come_from_the_environment():
    assert "password: $NATS_CORE_PASSWORD" in CONF and "password: $NATS_MODULE_PASSWORD" in CONF
