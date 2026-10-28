# Module contract

You are writing ONE mycelium module. A module is a small service that does one job,
owns its own data, and talks to the rest of the system only through the bus.
The supervisor will refuse to deploy anything that breaks these rules.

## Files you own

```
manifest.yaml     what this module is, what it listens to, emits and answers
app/main.py       the module code (entrypoint: `python -m app.main`)
app/*.py          any helpers you need
tests/            pytest tests; they MUST pass with `python -m pytest -q tests`
requirements.txt  extra pip packages (keep it minimal; stdlib preferred)
Dockerfile        do not change the FROM line or CMD
```

Do not create files outside this folder. Do not edit CONTRACT.md.

## Rules

1. **Use the SDK, never NATS directly.** `from mycelium_sdk import Module`. Register handlers with
   `@mod.on(subject)`, `@mod.on_request(action)`, `@mod.every(seconds)`. Send with
   `await mod.emit(event, data)` and `await mod.observe(type, summary, data, severity)`.
2. **Declare everything in manifest.yaml.** The SDK raises `ContractViolation` if you subscribe,
   emit, answer, or schedule anything not declared.
   - `subscribes`: full subjects or patterns, e.g. `sense.chat`, `mod.receipts.parsed`
   - `emits`: relative event names -> published as `mod.<name>.<event>`
   - `requests`: relative action names -> answered on `rpc.mod.<name>.<action>`
   - `hooks.interval_seconds`: list of intervals (>= 10s)
3. **Never subscribe to your own events** (loops) or to `rpc.*`, `>`, `_INBOX`.
4. **Data lives only in `mod.data_dir`** (mounted at `/data`, persists across restarts).
   Prefer SQLite (`sqlite3` stdlib). Create tables on startup if missing.
5. **No network access** unless `permissions.network: true` (and then justify it in `purpose`).
   **No real-world actions** (home devices, messages, money) unless `permissions.actuation: true`;
   such modules need human approval before deploy.
6. **Observe what matters.** Call `mod.observe(...)` when something happens that a human might care
   about. Use `severity="alert"` only for things that warrant interrupting the user.
   Keep `summary` to one short sentence.
7. **Request handlers return a dict.** The SDK adds `ok: true`. Raise an exception for errors;
   the SDK turns it into `{"ok": false, "error": ...}`. Validate inputs.
8. **Handlers must not crash the module.** The SDK catches exceptions, but write defensive code.
9. **Keep it small.** One job. If the spec asks for two unrelated jobs, implement the first and
   note the second in `manifest.yaml` under `need`.
10. **Time is the user's.** Use `mod.now()` and `mod.today()`: they are in the user's time zone (the
    supervisor sets `TZ`). Never `datetime.now(UTC)` or `datetime.utcnow()` for a day: an expense at
    07:00 in Taipei belongs to that day.

## What you receive

A chat message on `sense.chat` arrives as `msg.data`, a dict:

```json
{"id": "001a17...", "ts": "2026-10-28T09:12:03+00:00", "source": "web", "channel": "web",
 "thread": "web", "text": "dinner 350", "cause": null, "hops": 0}
```

Read the words with `msg.data.get("text", "")`. Every message reaches you, also the ones that are not for
you: ignore what does not match, quietly.

## Tests

- Use `mycelium_sdk.InMemoryBus` so tests never need a real NATS server.
- Build the module with `Module(manifest_path=..., bus=InMemoryBus(), data_dir=tmp_path)`; add
  `tz="Asia/Taipei"` when a test depends on the day.
- Cover: every request action (happy path + bad input), every subscribed event, every emit.
- Tests run in CI and again by the supervisor's verify step in a fresh container with no network and
  no environment beyond `TZ`: a test that needs either fails there.

## Definition of done

- `python -m pytest -q tests` passes.
- `manifest.yaml` validates (`python -c "from mycelium_sdk import load_manifest; load_manifest('manifest.yaml')"`).
- Every handler in `app/main.py` is declared in the manifest and covered by a test.
