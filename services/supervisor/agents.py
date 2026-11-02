"""Coding agents as builders' coders: the recipes, and the files that go into and come out of their container.

An agent (OpenCode, Claude Code, Codex, Aider) is a loop that runs commands, so it never runs in the builder
(on the mesh, next to NATS and Postgres). The supervisor runs it in a container of its own: the staged module
copied in at /work/module, the task at /work/PROMPT.md, the variables its recipe maps and nothing else, on
Docker's default bridge network (its model, the internet), never the mesh. What comes back is the folder as the
agent left it, small text files only; the builder decides which of them a coder may write.

    agent_images/agents.yaml   the recipes (AgentRecipe)
    agent_images/<name>/       the agent's image: FROM module-base (Python, the SDK, pytest), plus the agent and run.sh
"""

from __future__ import annotations

import io
import json
import tarfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

import yaml

from .schemas import AgentInfo, AgentRecipe, Unpacked

AGENT_UID = 10001  # module-base's `module` user: the agent runs as it, never as root
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".txt", ".md", ".ini", ".cfg", ".toml"}
SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules"}
FILE_MAX = 64_000  # bytes per file brought back
FILES_MAX = 80  # files brought back
# the files as they travel: JSON with non-ASCII escaped (\uXXXX), so Chinese text takes about twice its UTF-8
# size. The whole reply has to fit in one NATS message (1 MB), with the output and the skipped list beside it.
TOTAL_MAX = 512_000
SKIPPED_MAX = 200  # paths listed as left out; the rest are only counted
REDACTED = "[redacted]"


def load_recipes(path: Path) -> dict[str, AgentRecipe]:
    data = yaml.safe_load(path.read_text()) or {}
    return {name: AgentRecipe.model_validate(r) for name, r in data.items()}


def agent_env(recipe: AgentRecipe, env: Mapping[str, str]) -> dict[str, str]:
    """The agent's variables, from the supervisor's own environment; unset ones are left out."""
    return {inner: env[outer] for inner, outer in recipe.env.items() if env.get(outer)}


def not_ready(recipe: AgentRecipe, env: Mapping[str, str]) -> str | None:
    missing = [n for n in recipe.needs if not env.get(n)]
    return f"set {', '.join(missing)} for the supervisor" if missing else None


def describe(recipes: Mapping[str, AgentRecipe], env: Mapping[str, str]) -> list[AgentInfo]:
    out = []
    for name, r in recipes.items():
        reason = not_ready(r, env)
        out.append(AgentInfo(name=name, description=r.description, ready=reason is None, reason=reason))
    return out


# Redaction takes a key out where an agent wrote it as is (a config line, a log). It is not a boundary: the
# container reaches the internet, so an agent told to send its key somewhere can. Who may write an agent's prompt
# (rpc.sys.agent, and the spec behind rpc.build.start) is the boundary, and the bus has no authorization yet.
def secrets(env: Mapping[str, str]) -> list[str]:
    """Values never to hand back: anything in a *KEY* / *TOKEN* variable."""
    return [v for k, v in env.items() if ("KEY" in k or "TOKEN" in k) and len(v) >= 8 and v != "none"]


def redact(text: str, hidden: list[str]) -> str:
    for value in hidden:
        text = text.replace(value, REDACTED)
    return text


def pack(module_dir: Path, prompt: str) -> bytes:
    """The tar put at /work: module/<the staged files> and PROMPT.md, owned by the agent's user."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        _add_dir(tar, "module")
        for p in sorted(module_dir.rglob("*")):
            rel = p.relative_to(module_dir)
            if p.is_symlink() or any(part in SKIP_DIRS for part in rel.parts):
                continue
            arc = f"module/{rel.as_posix()}"
            if p.is_dir():
                _add_dir(tar, arc)
            else:
                _add_file(tar, arc, p.read_bytes())
        _add_file(tar, "PROMPT.md", prompt.encode())
    return buf.getvalue()


def unpack(archive: bytes, root: str = "module") -> Unpacked:
    """The folder as the agent left it (the tar Docker gives for /work/module): small text files, no links,
    no hidden or dependency folders, paths relative to the module folder. Also the text files left out for
    their size or count or encoding: they are there, so the builder must not take them for deleted."""
    out = Unpacked()
    total = 0

    def leave(rel: PurePosixPath) -> None:
        if len(out.skipped) < SKIPPED_MAX:
            out.skipped.append(rel.as_posix())
        else:
            out.skipped_more += 1

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r") as tar:
        members = sorted(tar.getmembers(), key=lambda m: (len(PurePosixPath(m.name).parts), m.name))  # top first
        for m in members:
            path = PurePosixPath(m.name)
            if not m.isreg() or path.parts[:1] != (root,) or len(path.parts) < 2:
                continue
            rel = PurePosixPath(*path.parts[1:])
            if any(p.startswith(".") or p in SKIP_DIRS for p in rel.parts) or ".." in rel.parts:
                continue
            if rel.suffix not in TEXT_SUFFIXES:
                continue
            if m.size > FILE_MAX or len(out.files) >= FILES_MAX:
                leave(rel)
                continue
            f = tar.extractfile(m)
            try:
                text = f.read().decode() if f else ""
            except UnicodeDecodeError:
                leave(rel)
                continue
            size = len(json.dumps(text)) + len(json.dumps(rel.as_posix()))  # as the bus will send it
            if total + size > TOTAL_MAX:
                leave(rel)
                continue
            out.files[rel.as_posix()] = text
            total += size
    return out


def _add_dir(tar: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.uid, info.gid = tarfile.DIRTYPE, 0o755, AGENT_UID, AGENT_UID
    tar.addfile(info)


def _add_file(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.uid, info.gid = len(data), 0o644, AGENT_UID, AGENT_UID
    tar.addfile(info, io.BytesIO(data))
