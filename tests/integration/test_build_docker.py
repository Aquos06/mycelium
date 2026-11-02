"""Real Docker: a build verified by the real supervisor in its sealed container, then promoted and committed.

The coder is scripted (the model is not under test here) and deploy is answered by a stub: what this proves is
that a build's folder (template, the coder's files, the builder's contract test) passes verify as it ships.
"""

import pytest

from builder.schemas import BuildRecord
from mycelium_sdk import InMemoryBus
from supervisor.registry import MemoryRegistry
from supervisor.service import Supervisor
from tests.integration.test_verify_docker import STACK, _docker_up
from tests.unit.builder_fakes import BROKEN, GOOD, REPO, SPEC, FakeCoder, git, make_pipeline

pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _docker_up(), reason="no Docker daemon")]


async def test_a_build_passes_the_real_verify_on_its_second_round(tmp_path):
    from supervisor.docker_ops import RealDockerOps

    bus = InMemoryBus()
    grown = tmp_path / "grown"
    ops = RealDockerOps("nats://nowhere:4222", "none", "none", stack=STACK, tz="Asia/Taipei")
    ops.ensure_base_image(REPO / "sdk")
    (tmp_path / "modules").mkdir()
    sup = Supervisor(
        bus=bus,
        docker=ops,
        registry=MemoryRegistry(),
        modules_dir=tmp_path / "modules",
        sdk_dir=REPO / "sdk",
        grown_dir=grown,
        verify_timeout=120,
    )
    await bus.subscribe("rpc.sys.verify", sup._wrap(sup.verify))
    deployed = []

    async def deploy(msg):
        deployed.append(msg.data["name"])
        await msg.respond({"ok": True, "name": msg.data["name"], "image": "stub", "status": "running"})

    await bus.subscribe("rpc.sys.deploy", deploy)
    record = BuildRecord(name="notes", spec=SPEC, coder="fake")
    rounds = []

    async def on_round(rec, rnd):
        rounds.append(rnd)

    await make_pipeline(bus, grown).run(record, FakeCoder([BROKEN, GOOD]), on_round)

    assert [(r.stage, r.passed) for r in rounds] == [("tests", False), ("tests", True)]
    assert "assert 'buy milk' == 'buy bread'" in rounds[0].output
    assert "6 passed" in rounds[1].output
    assert deployed == ["notes"] and git(grown, "tag", "-l").split() == ["notes-v0.1.0"]
    assert not ops.client.images.list(name=f"{STACK}/mod-notes")
