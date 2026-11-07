"""What every coder is told, whichever it is: the contract, the SDK in a page, a working module, the spec.

The contract is template/CONTRACT.md, the same file a module folder carries; the example is hello, the
hand-written module (its code and its tests). A coder that reads only this brief has everything it needs.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

SDK = """\
## The SDK in a page (`from mycelium_sdk import Module`)

```python
def build(**kwargs) -> Module:            # keep this shape: tests call build(manifest_path=..., bus=..., data_dir=...)
    mod = Module(**kwargs)
    mod.data_dir                          # Path: your folder, kept across restarts; put SQLite here
    mod.now(), mod.today()                # datetime / date in the user's time zone

    @mod.on("sense.chat")                 # an event; msg.data is a dict
    async def on_chat(msg): ...

    @mod.on_request("summary")            # answers rpc.mod.<name>.summary (described under `requests`); return a
                                          # dict, raise ValueError for bad input
    async def summary(data: dict) -> dict: ...

    @mod.every(3600)                      # every N seconds (declared under hooks.interval_seconds)
    async def hourly(): ...

    await mod.emit("expense.logged", {...})                           # publishes mod.<name>.expense.logged
    await mod.observe("big_expense", "One sentence.", {...}, severity="notice")   # info | notice | alert
    return mod

if __name__ == "__main__":
    build().run()
```

In tests: `bus = InMemoryBus()`, `mod = build(manifest_path=ROOT / "manifest.yaml", bus=bus, data_dir=tmp_path)`,
`await mod.start()`, then `await bus.publish("sense.chat", {"text": "dinner 350"})`,
`reply = await bus.request("rpc.mod.<name>.summary", {})` (the SDK adds `"ok": True`, or gives
`{"ok": False, "error": ...}` when the handler raised), `bus.events("mod.<name>.expense.logged")` lists
`(subject, data)` pairs, and `await mod.stop()` at the end. Use `Module(..., tz="Asia/Taipei")` when a test
depends on the day. asyncio mode is auto: `async def test_...` needs no decorator.
"""

RULES = """\
## The rules of this build

- Standard library only: no packages to install.
- You may write only `manifest.yaml`, `app/<x>.py` (app/main.py is the entry point) and `tests/test_<x>.py`.
  Dockerfile, requirements.txt, CONTRACT.md, pytest.ini, tests/conftest.py, SPEC.md and tests/test_contract.py
  are the builder's and are put back after you.
- The builder sets the manifest's name, version, permissions (no network, no actuation) and resources.
- Every request is described in manifest.yaml: `description`, `params` and `returns`, each field `name: type`
  (`optional <type>` when it may be left out). Main calls the module from these alone; the build fails without.
- Declare two to four `views` in manifest.yaml (CONTRACT.md): how Hansen sees the data on the module's page and in
  the chat. Each reads with a request that only reads, takes only the args that request takes, and its `path` is a
  field that request returns; the build fails on one that does not fit.
- Not allowed in the code: subprocess, socket, http/urllib and other network libraries, raw nats, the
  module's `.bus`, eval/exec, dynamic imports. A module talks to the world only through `mod`.
- tests/test_contract.py (the builder's) checks that the module starts, answers health, answers every
  declared request with a reply instead of hanging, and survives a chat message that is not for it.
- Tests run in a container with no network and nothing in the environment but TZ.
"""


class Brief(BaseModel):
    contract: str
    example_manifest: str
    example_code: str
    example_tests: str

    @classmethod
    def load(cls, template: Path, example: Path) -> Brief:
        tests = sorted((example / "tests").glob("test_*.py"))
        return cls(
            contract=(template / "CONTRACT.md").read_text(),
            example_manifest=(example / "manifest.yaml").read_text(),
            example_code=(example / "app" / "main.py").read_text(),
            example_tests="\n\n".join(p.read_text() for p in tests),
        )

    def text(self) -> str:
        """The part of every prompt that never changes within a build (a local model's prefix cache keeps it)."""
        return "\n\n".join(
            [
                self.contract.strip(),
                SDK.strip(),
                RULES.strip(),
                "## A module that works: hello\n\n"
                f"manifest.yaml\n```yaml\n{self.example_manifest.strip()}\n```\n\n"
                f"app/main.py\n```python\n{self.example_code.strip()}\n```\n\n"
                f"tests/test_hello.py\n```python\n{self.example_tests.strip()}\n```",
            ]
        )


def coder_test_file(name: str) -> str:
    """The coder's own test file: tests/test_<name>.py, with a hyphen as an underscore."""
    return f"tests/test_{name.replace('-', '_')}.py"


KEEP_DATA = """\
It is running now with Hansen's data in its data folder (`mod.data_dir`), and the new version starts on that same
data: keep it readable. Keep the tables and files the module has and the meaning of their columns; add what the
change needs (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN` when the column is missing, a default for
the old rows), and never drop, rename or recreate a table or a file. Keep every request it answers unless the change
says otherwise; a request may take new optional fields. Update its description in manifest.yaml when it changes."""

UPGRADE_TEST = (
    "Add tests for the change, and one that writes a data folder the way the old code did (its tables, a row or two), "
    "starts the new module on it and checks the old entries still read."
)


def spec_text(name: str, spec: str, change: bool = False) -> str:
    if change:
        return (
            f"## The module to change: `{name}`\n\nSPEC.md, what Hansen approved and each change since, oldest "
            f"first; the last section is the change this build makes:\n\n{spec.strip()}"
        )
    return f"## The module to write: `{name}`\n\nSPEC.md, what Hansen approved:\n\n{spec.strip()}"


def files_text(files: dict[str, str]) -> str:
    if not files:
        return "(no files yet)"
    return "\n\n".join(f"{rel}\n```{_lang(rel)}\n{text.rstrip()}\n```" for rel, text in files.items())


def _lang(rel: str) -> str:
    return "python" if rel.endswith(".py") else "yaml" if rel.endswith((".yaml", ".yml")) else ""
