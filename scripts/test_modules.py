#!/usr/bin/env python3
"""Run every module's tests in its own pytest process (each module has its own `app` package),
plus a smoke check that a freshly scaffolded template passes its own tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from new_module import scaffold  # noqa: E402


def run(module_dir: Path) -> bool:
    print(f"== {module_dir.name}", flush=True)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=module_dir)
    return r.returncode == 0


def main() -> int:
    failed = []
    for d in sorted((REPO / "modules").iterdir()):
        if (d / "tests").is_dir() and not run(d):
            failed.append(d.name)
    with tempfile.TemporaryDirectory() as tmp:
        if not run(scaffold("tmplcheck", Path(tmp))):
            failed.append("template")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print("all module tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
