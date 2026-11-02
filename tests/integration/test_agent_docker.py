"""Real Docker: a coding agent's container end to end, with a scripted agent in place of a model.

The stand-in agent copies a finished module into /work/module, runs its tests the way a real agent would, and
prints what it can see. That proves the plumbing every agent shares: the folder in and back out, the prompt,
not root, only its own variables, the key redacted, and the round then passing the real sealed verify.
"""

import pytest

from builder.coders import AgentCoder
from builder.schemas import BuildRecord
from mycelium_sdk import InMemoryBus
from supervisor.registry import MemoryRegistry
from supervisor.schemas import AgentRecipe
from supervisor.service import Supervisor
from tests.integration.test_verify_docker import STACK, _docker_up
from tests.unit.builder_fakes import GOOD, REPO, SPEC, git, make_pipeline

pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _docker_up(), reason="no Docker daemon")]

KEY = "sk-test-0123456789abcdef"
DOCKERFILE = """\
ARG BASE_IMAGE=mycelium/module-base:latest
FROM ${BASE_IMAGE}
USER root
COPY solution /opt/solution
COPY run.sh /usr/local/bin/run-agent
RUN chmod 755 /usr/local/bin/run-agent && mkdir -p /work && chown module:module /work
USER module
WORKDIR /work/module
CMD ["run-agent"]
"""
RUN = """\
#!/bin/sh
set -eu
echo "uid=$(id -u) key=$MODEL_KEY module=$MODULE_NAME tz=$TZ nats=${NATS_URL:-none}"
head -c 60 /work/PROMPT.md; echo
cp -r /opt/solution/. /work/module/
python -m pytest -q -p no:cacheprovider tests
"""


async def test_an_agent_writes_the_module_in_its_own_container(tmp_path):
    from supervisor.docker_ops import RealDockerOps

    agents = tmp_path / "agents"
    scripted = agents / "scripted"
    for rel, text in {**GOOD, "manifest.yaml": "name: notes\n" + GOOD["manifest.yaml"]}.items():
        (scripted / "solution" / rel).parent.mkdir(parents=True, exist_ok=True)
        (scripted / "solution" / rel).write_text(text)
    (scripted / "Dockerfile").write_text(DOCKERFILE)
    (scripted / "run.sh").write_text(RUN)

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
        agents={"scripted": AgentRecipe(description="test", env={"MODEL_KEY": "AGENT_KEY"}, needs=["AGENT_KEY"])},
        agents_dir=agents,
        agent_timeout=300,
        env={"AGENT_KEY": KEY, "MODULE_TZ": "Asia/Taipei", "NATS_URL": "nats://nats:4222"},
    )
    await bus.subscribe("rpc.sys.verify", sup._wrap(sup.verify))
    await bus.subscribe("rpc.sys.agent", sup._wrap(sup.agent))

    async def deploy(msg):
        await msg.respond({"ok": True, "name": msg.data["name"], "image": "stub", "status": "running"})

    await bus.subscribe("rpc.sys.deploy", deploy)
    rounds = []

    async def on_round(rec, rnd):
        rounds.append(rnd)

    record = BuildRecord(name="notes", spec=SPEC, coder="scripted")
    await make_pipeline(bus, grown).run(record, AgentCoder(bus, "scripted", timeout=300), on_round)

    log = rounds[0].log
    assert "uid=10001" in log and "key=[redacted]" in log and KEY not in log
    assert "module=notes tz=Asia/Taipei nats=none" in log
    assert "You are writing one mycelium module, `notes`" in log  # the prompt was at /work/PROMPT.md
    assert "6 passed" in log  # the agent ran the tests itself, the builder's contract test among them
    assert (rounds[0].stage, rounds[0].passed) == ("tests", True) and "6 passed" in rounds[0].output
    assert git(grown, "tag", "-l").split() == ["notes-v0.1.0"]
    assert not ops.client.containers.list(all=True, filters={"label": "mycelium.agent"})
