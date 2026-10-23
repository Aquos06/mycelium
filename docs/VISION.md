# Vision

mycelium is a personal assistant for one person (Hansen), closer to Jarvis than to a chatbot, that
**grows its own software**. When Hansen needs something it can't do yet, like tracking expenses, it
doesn't just remember more. It builds a new **module**: a small service with its own data and logic,
plugged into the same event bus as everything else. The system gets bigger and more capable one
module at a time.

It is a hobby/research project. The plumbing (bus, supervisor, contract, builder) is a means to an
end. The point is to find out whether a system can grow like this and still stay small, trustworthy
and quiet.

## The bet

Assistants today grow by adding *skills*: prompts and tools the LLM can call. The bet here is that
some needs should become real *software* instead: written by the agent against a strict contract,
tested, and then running on its own. With real feedback from its user and a record of every
decision, such a system can grow its own abilities without filling up with junk.

## Software, memory, or just an answer?

Not every need should become a module.

- **Software (a module)** when the answer must be exact or repeatable, or something must run on its
  own: totals, counts, schedules, device states, watching a camera all day.
- **Memory** for context and connections: who someone is, what Hansen likes, what happened last
  week.
- **Just answer it** for a one-off question.

Ask memory "how much did I spend in March?" and it guesses. A module with a table adds it up.

The difference from a skill is that **a module runs without the LLM**. It keeps its own data, runs
on a schedule, reacts to events all day and has tests. A skill makes the agent know more; a module
gives it a new part of its body. The price is that every module is code to maintain, so a module is
only built when it's worth that.

## What it is, and what it isn't

**It is** a mostly silent background system. Most of its work never reaches Hansen: logging,
writing memory, acting on devices, deciding *not* to send a notification.

**It is not a chatbot.** Chat is one input and a debug console, not the product. It can arrive on
any channel (Telegram today; a web app, voice, LINE or WhatsApp later), and the system doesn't care
which.

## The system: a small host and growing modules

Think of a phone's operating system and its apps, except the assistant writes the apps.

- **The host** is written by hand once and stays small: the bus, the supervisor, Main, memory and
  the dashboard.
- **Modules** are the only part that grows. The agent produces them, and they must follow the
  contract.

If the host has to change every time a module is added, the design is broken.

Everything talks through **events on a bus**, not direct connections. A sender doesn't know who is
listening. The camera module publishes "person at the door" without knowing that Main, a lights
module and a security log all hear it. A module added next month can listen too, without changing
the camera code. That is what lets the system grow without rewiring. Events are also stored, so
history can be replayed and every decision traced.

## How a module comes to exist

1. **Hansen asks.** "I want to track my expenses." Main drafts a spec, Hansen confirms it, the
   builder writes the module, and the supervisor verifies and deploys it. This is the main path.
2. **The system proposes** (later). "You want to spend less, and you've mentioned 12 expenses in
   chat this month. Should I build an expense tracker?" Hansen approves or declines.
3. **A new device starts the conversation** (later). "New camera found. What is it for?" One
   sentence ("front door, tell me about strangers at night") is enough to write a spec. A device
   alone can't say what it's for: a door camera and a baby-monitor camera need different software.

### Wrap, re-create or fork

Before writing something new, check whether good open software already does it. For each need, in
this order:

1. **Wrap it.** Run the open software unchanged in its own container, with a thin module next to it
   that talks to its API and speaks the bus. The open app is the engine; the module is the plug. For
   big, well-maintained software: Home Assistant, Frigate, Immich, Paperless-ngx, Actual Budget.
   Upstream keeps fixing bugs, and updates come for free.
2. **Re-create it.** The builder writes it from scratch to the contract. For small things: an
   expense tracker is a few hundred lines, and writing it fresh is often easier than learning
   someone else's app.
3. **Fork it.** Last resort. A fork means maintaining all of its code, and every upstream update
   becomes a manual merge. Only when the project is small or abandoned, or the change is tiny.

Rule of thumb: big and well-maintained, wrap it. Small, re-create it. Fork rarely.

Devices and perception are mostly wrap cases: modules glue existing pieces together (Home
Assistant, Frigate, a local model) and write the logic around them. They don't train models.

Adding third-party software needs Hansen's approval, and its version is pinned, because it runs on
the home box next to the cameras and personal data. Re-creating what an app does is fine, but
copying its code brings its license with it (the repo is public), so running GPL or AGPL software
unchanged in its own container is preferred over copying its code.

Changing an existing module ("add categories to the expense tracker") matters as much as building a
new one. A system that can only create grows by making copies.

## Direction: Hansen's goals

The system doesn't grow randomly. It keeps a short list of Hansen's goals, like "spend less", "sleep
better" or "know who's at the door". Every proposal must point at one of them. No matching goal, no
proposal.

## Who handles what

```
module handles it itself     (simple rule: log the expense)
  -> Main decides            (judgment: is this unusual?)
    -> hands it to a module  (turn on the porch light)
      -> asks Hansen         (unknown person at 2am: call someone?)
```

Main is for judgment, not for routing everything. Simple chains like "motion → light on" go directly
from module to module.

## Permission and earned autonomy

Permission depends on risk:

| Action | Permission |
|---|---|
| Log, remember, summarize | None, done silently |
| Build or change a module | Hansen approves |
| Add third-party software (wrap or fork) | Hansen approves, version pinned |
| Act on the real world (lights, locks, money, messages to other people) | Approved per module, and asked per action at first |

Autonomy is earned. When Hansen approves the same kind of action again and again, it moves one step
toward automatic:

```
ask -> ask with a default answer -> do it and report -> do it silently
```

Hansen's answers become both the eval data and the record of how much the system is trusted. Some
things never become automatic: door locks, payments and messages to other people.

## The questions it exists to answer

1. **What should exist?** Hansen asking is the first answer. Later: when is the evidence strong
   enough to propose a module, and when should an existing module change instead?
2. **When should it speak, and when should it stay quiet?** Interrupting Hansen costs something.
   Most events should change state silently, and only a few should reach Hansen.
3. **How does it avoid filling up with junk?** Modules go through canary, then are promoted or
   retired based on real use and feedback, not on whether they deployed.
4. **How much should it trust itself?** Which actions can move toward automatic, and how fast.

## Principles

- **Every decision is explainable.** Each decision is logged with its inputs, so "why did you say
  that?" always has an answer.
- **Hansen's reactions are the eval set.** 👍/👎 reactions and approvals are the labels used to tune
  thresholds, gates and autonomy.
- **Fast gate, slow thinker.** Jev makes the cheap, frequent calls (escalate, notify, route,
  classify) on a small state snapshot. The LLM gets full context only on escalations, direct
  questions and builds.
- **The builder never grades itself.** Generated modules are verified independently before they
  run.
- **Raw data stays local.** Screen pixels, audio and camera frames become text on the home box.
  Only text leaves it.
- **Memory is about connections.** The event log is the source of truth. On top of it: entity notes
  with links, day/week/month summaries, and retrieval that reads and follows links. Similarity
  search is only a way in.
- **Safety rails are enforced in code.** Manifests declare everything, modules are sandboxed, and
  anything that acts on the real world needs explicit approval.

## What success looks like

- Hansen describes a piece of software in a sentence or two and gets a working module with no human
  edits.
- Changing a module is as easy as asking for a new one.
- Later, proposals come from observed behavior, each one points at a goal, and most get approved.
- Hansen is interrupted rarely, and when it happens, it was worth it.
- More actions become automatic over time, because Hansen's approvals earned it.
- The module count stays **small**. Each live module earns its place through use, and the ones that
  don't are retired. A system that grows 30 half-working modules has failed, even if every one of
  them deploys.
- Over time, decisions move from the cloud to the local model, once the traces show the local model
  agrees often enough.

## Roadmap

1. **Skeleton (done):** bus, event log, supervisor, module SDK and contract, example module,
   builder, CI/CD.
2. **Prove the builder:** `specs/expenses.md` becomes a module that deploys without human edits.
3. **Main:** the Jev gate, the planner, notifications, and asking for a module from chat (draft
   spec → confirm → build).
4. **Memory:** the memory service over the event log and the markdown vault.
5. **Growth:** changing existing modules, the goals list and proposals, canary → promote / retire,
   earned autonomy.
6. **Perception and devices:** new manifest permissions for devices, GPU and network, and backend
   containers for wrapped open software; then cloud connectors (Gmail, Calendar, Drive), screen,
   voice, camera (Frigate) and Home Assistant as new input sources.
7. **Dashboard:** a host shell where modules mount their own panels, plus a trace viewer.

When the builder fails on a spec, the fix goes into the contract, the template or the builder's
prompt, never into a hand-written module. That loop is the core experiment.
