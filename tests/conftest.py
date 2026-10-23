import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in ("services/supervisor", "services/tracer", "services/telegram", "services", "scripts"):
    # "services" -> import memory / gateway / main (each services/<name>/ is a package)
    sys.path.insert(0, str(REPO / p))

NATS_URL = os.environ.get("NATS_URL")
DATABASE_URL = os.environ.get("DATABASE_URL")

needs_nats = pytest.mark.skipif(not NATS_URL, reason="NATS_URL not set")
needs_pg = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
