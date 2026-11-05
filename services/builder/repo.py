"""GROWN_DIR as a git repo: one commit per build, tagged <name>-v<version>, the rollback point.

The builder creates the repo on start, so the supervisor (which reads GROWN_DIR) knows it is really there.
`.staging/` is ignored: only modules that passed verify are ever committed.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("mycelium.builder.repo")

GITIGNORE = ".staging/\n__pycache__/\n.pytest_cache/\n"
IDENTITY = ["-c", "user.name=mycelium builder", "-c", "user.email=builder@mycelium.local", "-c", "commit.gpgsign=false"]


class GrownRepo:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def ensure(self) -> None:
        if (self.root / ".git").exists():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        await self._git("init", "-q", "-b", "main")
        (self.root / ".gitignore").write_text(GITIGNORE)
        await self._git("add", ".gitignore")
        await self._git("commit", "-q", "-m", "grown modules: the repo the builder writes, one commit per build")

    async def commit(self, name: str, version: str, message: str) -> str:
        """Commit GROWN_DIR/<name> as it is now and tag it; returns the commit's short hash. Raises only when
        nothing was committed (and then leaves the index as it was); a tag that fails is logged, the commit stays.
        The tag moves to this commit: a module grown again under its old name is rolled back to this build."""
        await self.ensure()
        try:
            await self._git("add", "-A", "--", name)
            await self._git("commit", "-q", "-m", message, "--", name)
        except RuntimeError:
            await self._git("reset", "-q", "--", name)
            raise
        sha = (await self._git("rev-parse", "--short=12", "HEAD")).strip()
        try:
            await self._git("tag", "-f", f"{name}-v{version}")
        except RuntimeError as e:
            log.warning("committed %s as %s but could not tag it: %s", name, sha, e)
        return sha

    async def last_commit(self, name: str) -> str | None:
        """The commit GROWN_DIR/<name> was last built in: where a change to it can go back to."""
        try:
            sha = (await self._git("log", "-1", "--format=%h", "--abbrev=12", "--", name)).strip()
        except RuntimeError:
            return None
        return sha or None

    async def _git(self, *args: str) -> str:
        def run() -> str:
            p = subprocess.run(
                ["git", "-c", "safe.directory=*", *IDENTITY, *args],
                cwd=self.root,
                capture_output=True,
                text=True,
            )
            if p.returncode != 0:
                raise RuntimeError(f"git {args[0]}: {(p.stderr or p.stdout).strip()}")
            return p.stdout

        return await asyncio.to_thread(run)
