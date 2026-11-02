#!/usr/bin/env python3
"""Scaffold a new module folder from template/ (the builder's own scaffold, for a module written by hand).

python scripts/new_module.py expenses            -> modules/expenses/
python scripts/new_module.py expenses --dest /tmp/x
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services"))

from builder.workspace import scaffold as _scaffold  # noqa: E402


def scaffold(name: str, dest_root: Path) -> Path:
    return _scaffold(name, dest_root, REPO / "template")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--dest", type=Path, default=REPO / "modules")
    args = ap.parse_args(argv)
    try:
        path = scaffold(args.name, args.dest)
    except (ValueError, FileExistsError) as e:
        raise SystemExit(str(e)) from None
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
