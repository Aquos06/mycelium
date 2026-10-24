#!/usr/bin/env python3
"""One request to laya-serve with the three question types memory and Main will use. Standard library only.

    python3 smoke.py http://localhost:8100 [api-key]

The state is a chat line; the questions are the shapes from docs/MEMORY.md §4: which kind of memory the
message needs (choice), how urgent it is (score), whether it states a fact worth remembering (yes/no).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

REQUEST = {
    "state": {"document": "remember that 小美 is moving to Tainan in December, we should visit her before then"},
    "questions": {
        "memory_kind": {
            "type": "choice",
            "instructions": "Which kind of memory does answering or acting on this message need?",
            "criteria": {
                "none": "small talk or a question that needs no memory",
                "entity": "a person, place, project or thing that may have a note",
                "time": "a day, week or period: what happened when",
                "module-data": "exact numbers or records a module keeps (spending, counts, logs)",
            },
        },
        "urgency": {
            "type": "score",
            "instructions": "How soon does this need attention?",
            "criteria": ["not urgent", "soon", "blocking"],
        },
        "durable_fact": {
            "type": "noul",
            "instructions": "Does the message state a durable fact about a person, place or plan worth remembering?",
        },
    },
}


def main(base: str, api_key: str | None = None) -> int:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{base.rstrip('/')}/v1/systemone", data=json.dumps(REQUEST).encode(), headers=headers)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(
                "401 from laya-serve: auth is on. Either pass the key as the second argument, or, if you did not "
                "mean to set one, remove the LAYA_API_KEY line from infra/laya/.env (an empty value still turns auth "
                "on) and recreate the container with `docker compose up -d`."
            )
            return 2
        print(f"{e.code} from laya-serve: {e.read().decode(errors='replace')[:500]}")
        return 2
    ms = int((time.monotonic() - t0) * 1000)
    answers = body.get("answers", body)
    print(json.dumps(answers, indent=2, ensure_ascii=False))
    print(f"\n{ms} ms; routing: {body.get('routing')}; usage: {body.get('usage')}")
    kind = answers.get("memory_kind", {})
    ok = kind.get("choice") == "entity"
    print("expected memory_kind=entity:", "ok" if ok else f"got {kind.get('choice')!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(
        main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8100", sys.argv[2] if len(sys.argv) > 2 else None)
    )
