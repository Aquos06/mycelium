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
   `@mod.on(subject)`, `@mod.on_request(action)`, `@mod.every(seconds)`, `@mod.at("21:00")`. Send with
   `await mod.emit(event, data)` and `await mod.observe(type, summary, data, severity)`.
2. **Declare everything in manifest.yaml.** The SDK raises `ContractViolation` if you subscribe,
   emit, answer, or schedule anything not declared.
   - `subscribes`: full subjects or patterns, e.g. `sense.chat`, `mod.receipts.parsed`
   - `emits`: relative event names -> published as `mod.<name>.<event>`
   - `requests`: relative action names -> answered on `rpc.mod.<name>.<action>`, each **described**:
     a `description`, the `params` it takes and what it `returns`, as `name: type` (`optional <type>` when it may be left out),
     and `writes: true` on one that changes the data (adds, deletes, sets) or `writes: false` on one that only reads.
     Main reads these to call the module, so a request it cannot read is a request it guesses at; a page, or Main
     looking on its own, never calls one that writes:
     ```yaml
     requests:
       add:
         description: Store one expense.
         params: {amount: number, description: string, day: optional date}
         returns: {id: number}
         writes: true
     ```
   - `views`: how Hansen sees the module's data, on its page in the web app and when Main shows it in the chat.
     Each names a request that **only reads** (never `add`, `delete`, ...: opening a page changes nothing), the
     `args` it sends (a `$` word is a date worked out when the view is shown: `$today`, `$yesterday`,
     `$week_start`, `$month_start`, `$year_start`, `$7_days_ago`), and the block it makes: `show: table` (a list
     of entries), `chart` (numbers by a name, `chart: line` or `area` over time), `stats` (a few headline numbers),
     `details` (one record) or `meter` (a number against a goal); `path` is where in the reply the data is, and
     `fields` which ones, in order (`{key: amount, format: money}` for money). Two to four views, the most useful
     first:
     ```yaml
     views:
       week: {title: This week, request: summary, args: {from: $week_start}, show: stats}
       by_category: {title: By category, request: summary, args: {from: $month_start}, path: by_category, show: chart}
       entries:
         title: Entries
         request: history
         path: expenses
         show: table
         fields: [day, description, {key: amount, format: money}]
     ```
   - `hooks.interval_seconds`: list of intervals (>= 10s)
   - `hooks.daily`: list of times in the user's day, quoted: `["21:00"]` -> `@mod.at("21:00")` runs then, every day
3. **Never subscribe to your own events** (loops). Subscribe only to events: `sense.*`, `brain.*`, `mod.*`, `sys.*`,
   `build.*`, `out.*`. A module's bus login cannot send requests, read `rpc.*`, `trace.*` or `stream.*`.
4. **Data lives only in `mod.data_dir`** (mounted at `/data`, persists across restarts).
   Prefer SQLite (`sqlite3` stdlib). Create tables on startup if missing.
5. **No network access** unless `permissions.network: true` (and then justify it in `purpose`).
   **No real-world actions** (home devices, messages, money) unless `permissions.actuation: true`;
   such modules need human approval before deploy.
6. **Observe what matters; tell the user only what the spec asks for.** `mod.observe(type, summary, data,
   severity, once)` tells Main, and the `summary` is what the user reads, as you wrote it.
   - **How loud.** `info`: for the record (an entry added, a total changed); nobody is told, and the nightly memory
     and the event feed read it. `notice`: worth telling the user at the next good moment. `alert`: worth
     interrupting the user now, even at night (a door opened at 3am); one an hour per module, more are told as
     notices; never for money, goals or anything routine.
   - **Only what the spec asks.** A `notice` or an `alert` is for what the spec says the user wants to hear about: a
     budget passed, a goal missed, something expected that did not come, an expense over a line. A spec that asks for
     none of that gets none.
   - **Its shape.** `type` is a stable snake_case name of the kind of news (`budget_passed`), the same each time.
     `summary` is one short sentence to the user with the numbers and the period, since Main tells it as
     `<module>: <summary>`: "NT$31,200 spent in November, over your NT$30,000 budget." `data` holds the numbers
     behind it: `{"spent": 31200, "budget": 30000, "month": "2026-11"}`.
   - **`once`: what makes it the same news.** For something that stays true, the period: `once="2026-11"`. For an
     event, the entry: `once=f"expense-{id}"`. Main tells one `once` of a type once and remembers it for weeks, so do
     not keep your own record of what was told: observe it **each time you find it true** (after every `add` while
     the month is over budget). Main waits for a good moment (not at night, not mid-conversation, not over the
     day's few messages) but lets go of a notice held about 10 hours; the next time you observe it, it is told then.
   - **Check where it can change.** After anything that moves the total or the line: `add` and `delete`, and the
     request that sets the line. Count an entry in its own period (an expense dated in October counts toward
     October, and the summary says "in October").
   - **The line.** One the spec gives ("over 3000") is the default; one the user should be able to change is kept
     by a request that writes (`set_budget {amount: number}`, `writes: true`; its reply says what is set now) and
     read by one that reads. With no line at all, it tells nothing.
   - **Something that did not happen by a time** ("nothing logged by evening") is a `hooks.daily` time whose handler
     looks at the data and observes a `notice` (with `once` = the day) only when there is something to say.
   - **Test each one.** In tests, `bus.events("brain.observe")` lists `(subject, data)` pairs; a notice's data has
     `type`, `summary`, `severity_hint` ("notice") and `once`. Test that it is observed when true and not before,
     with the `once` you meant. `await mod.run_at("21:00")` runs that daily time's handlers now.
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
