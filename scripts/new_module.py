#!/usr/bin/env python3
"""Scaffold a new module folder from template/.

python scripts/new_module.py expenses            -> modules/expenses/
python scripts/new_module.py expenses --dest /tmp/x
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".txt", ".ini", ""}


def scaffold(name: str, dest_root: Path) -> Path:
    if not NAME_RE.match(name):
        raise SystemExit(f"invalid module name: {name!r} (lowercase slug, 2-31 chars)")
    dest = dest_root / name
    if dest.exists():
        raise SystemExit(f"{dest} already exists")
    shutil.copytree(REPO / "template", dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    for p in dest.rglob("*"):
        if p.is_file() and p.suffix in TEXT_SUFFIXES and p.name != "Dockerfile":
            text = p.read_text()
            if "__NAME__" in text:
                p.write_text(text.replace("__NAME__", name))
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--dest", type=Path, default=REPO / "modules")
    args = ap.parse_args(argv)
    path = scaffold(args.name, args.dest)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
