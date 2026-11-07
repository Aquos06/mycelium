"""What the builder checks before anything runs: the manifest it pins, the files' sizes, the code's imports.

Every view the manifest declares must be one a page can show: a request it has, that only reads, with the arguments
it takes and a path its reply has (mycelium_sdk.views). The manifest's name, version, permissions and resources are
the builder's, set from what Hansen approved, so a
coder cannot grant its module the internet or real-world actions. `emits` and `requests` are relative names
(the SDK prefixes them), so `mod.`, `rpc.` or the module's own name in front is a mistake caught here.

The code checks are guards against mistakes and lazy escapes, not a sandbox: the sandbox is the container
(no network for verify, the bus-only network when deployed). They ban what a module of one job never needs:
processes, sockets and HTTP, raw NATS, the SDK's bus behind the Module, eval/exec, dynamic imports.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import yaml

from mycelium_sdk import Manifest, ManifestError, validate_manifest
from mycelium_sdk.views import problems as view_problems

FILE_MAX = 40_000  # bytes per file: one module, one job
TOTAL_MAX = 100_000  # bytes for all of a coder's files: they go back into the next round's prompt
BANNED_MODULES = {
    "subprocess", "socket", "ssl", "ctypes", "multiprocessing", "pty", "signal", "importlib", "builtins", "nats",
    "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "websockets", "ftplib", "smtplib", "telnetlib",
}  # fmt: skip
BANNED_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint"}  # as bare names: re.compile stays fine
DYNAMIC = {"eval", "exec", "__import__"}  # banned however they are reached: x.eval, getattr(x, "exec"), an import
BANNED_ATTRS = {
    "system", "popen", "fork", "forkpty", "startfile", "posix_spawn", "posix_spawnp",
    "execv", "execve", "execl", "execle", "execlp", "execlpe", "execvp", "execvpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "create_subprocess_exec", "create_subprocess_shell", "open_connection", "start_server", "open_unix_connection",
}  # fmt: skip
BANNED_NAMES = {"NatsBus", "NatsKV", "__builtins__"}
APP_ONLY_ATTRS = {"bus", "nc"}  # the Module's bus: emit/observe/on are the way out; tests may hold an InMemoryBus


def pin_manifest(module_dir: Path, name: str, version: str) -> tuple[Manifest | None, list[str]]:
    """Rewrite manifest.yaml with the builder's fields, then validate it. (manifest, problems)."""
    path = module_dir / "manifest.yaml"
    try:
        data = yaml.safe_load(path.read_text()) if path.exists() else None
    except yaml.YAMLError as e:
        return None, [f"manifest.yaml: not valid YAML: {e}"]
    if not isinstance(data, dict):
        return None, ["manifest.yaml: must be a mapping (purpose, subscribes, emits, requests, hooks)"]
    data.update(
        name=name,
        version=version,
        permissions={"network": False, "actuation": False},
        resources={"memory_mb": 256, "cpus": 0.5},
    )
    problems = relative_names(data, name)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    try:
        manifest = validate_manifest(data)
    except ManifestError as e:
        return None, problems + [f"manifest.yaml: {e}"]
    if missing := manifest.undescribed():  # Main reads these to call the module: a bare name is a guess
        problems.append(
            f"manifest.yaml: describe every request (description, params, returns), Main reads them to call it; "
            f"not described: {', '.join(missing)}. E.g. requests: {{add: {{description: Store one expense., "
            f"params: {{amount: number, day: optional date}}, returns: {{id: number}}}}}}"
        )
    problems += [f"manifest.yaml: {p}" for p in view_problems(manifest)]  # a page or Main would refuse it later
    return (None if problems else manifest), problems


def relative_names(data: dict[str, Any], name: str) -> list[str]:
    """`emits` and `requests` are relative: the SDK puts mod.<name>. / rpc.mod.<name>. in front."""
    out = []
    for field in ("emits", "requests"):
        for v in data.get(field) or []:
            if isinstance(v, str) and v.startswith(("mod.", "rpc.", f"{name}.")):
                bare = v
                for prefix in ("rpc.", "mod.", f"{name}."):
                    bare = bare.removeprefix(prefix)
                out.append(f"manifest.yaml: {field} has {v!r}; names are relative: write {bare!r}")
    return out


def check_files(module_dir: Path, files: dict[str, str]) -> list[str]:
    """Sizes and the code rules over a coder's files ({path: text})."""
    problems: list[str] = []
    total = 0
    for rel, text in files.items():
        size = len(text.encode())
        total += size
        if size > FILE_MAX:
            problems.append(f"{rel}: {size} bytes; keep a file under {FILE_MAX}")
        if rel.endswith(".py"):
            problems += check_python(rel, text, app=rel.startswith("app/"))
    if total > TOTAL_MAX:
        problems.append(f"{total} bytes of code in all; a module does one job, keep it under {TOTAL_MAX}")
    if "app/main.py" not in files:
        problems.append("app/main.py is missing")
    return problems


def check_python(rel: str, text: str, app: bool) -> list[str]:
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as e:
        return [f"{rel}:{e.lineno}: syntax error: {e.msg}"]
    out = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            out += [f"{rel}:{line}: import {a.name}: not allowed" for a in node.names if _banned_module(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.module and _banned_module(node.module):
                out.append(f"{rel}:{line}: from {node.module} import ...: not allowed")
            out += [
                f"{rel}:{line}: import of {a.name}: not allowed"
                for a in node.names
                if a.name in BANNED_NAMES | BANNED_ATTRS | DYNAMIC
            ]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
            out.append(f"{rel}:{line}: {node.func.id}(): not allowed")
        elif isinstance(node, ast.Call) and _getattr_banned(node, app):
            out.append(f"{rel}:{line}: getattr of {node.args[1].value!r}: not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRS | DYNAMIC or (app and node.attr in APP_ONLY_ATTRS):
                out.append(f"{rel}:{line}: .{node.attr}: not allowed")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            out.append(f"{rel}:{line}: {node.id}: not allowed")
    return sorted(set(out), key=lambda s: (s.split(":")[0], int(s.split(":")[1] or 0)))


def _banned_module(name: str) -> bool:
    return name.split(".")[0] in BANNED_MODULES


def _getattr_banned(node: ast.Call, app: bool) -> bool:
    banned = BANNED_ATTRS | DYNAMIC | (APP_ONLY_ATTRS if app else set())
    return (
        isinstance(node.func, ast.Name)
        and node.func.id in ("getattr", "setattr")
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value in banned
    )
