#!/usr/bin/env python3
"""Run every module's tests in its own pytest process (each module has its own `app` package),
plus a smoke check that a freshly scaffolded template passes its own tests, and that the builder's contract
test (services/builder/contract.py) passes on the template and on hello."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "services"))

from builder.contract import CONTRACT_TEST  # noqa: E402
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
        template = scaffold("tmplcheck", Path(tmp))
        hello = shutil.copytree(
            REPO / "modules" / "hello", Path(tmp) / "hello", ignore=shutil.ignore_patterns("__pycache__")
        )
        for name, d in (("template", template), ("contract on hello", hello)):
            (d / "tests" / "test_contract.py").write_text(CONTRACT_TEST)
            if not run(d):
                failed.append(name)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print("all module tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
