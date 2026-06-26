# ADR 0001 — Collapse the background updater into a process-global singleton

- Status: Proposed (for review with Alex / Samuel)
- Date: 2026-06-26
- Context: PR #404, follow-up to the 19 Jun huddle

## The call

Replace the instantiable `UpdatePrices` class + per-instance `start()`/`stop()` with a
single process-global, ref-counted updater fronted by one function:

```python
handle = genai_prices.update_prices_in_background(
    *, url=..., interval=3600, timeout=...,   # all optional
)
...
handle.close()                                # or: with update_prices_in_background() as h: ...

genai_prices.wait_for_update(timeout=...)         # sync   (role unchanged)
await genai_prices.wait_for_update_async(...)     # async
```

`UpdatePrices` is **deprecated**, not removed: it stays importable as a thin shim that
warns and routes through the singleton. It is removed in a later release.

## Why

There is exactly **one** price snapshot per process — `data_snapshot.set_custom_snapshot()`
is a process-global. "Updating prices" is therefore inherently a singleton activity: two
"independent" updaters would both write the same global.

The current public API contradicts that domain fact. It exposes an instantiable class with
per-instance `start()`/`stop()`/config/context-manager, while every instance secretly shares
one global snapshot. That mismatch — N instances pretending to be independent — is the root
cause of the complexity we maintain:

- `RuntimeError` "only one can be active at a time"
- takeover / precedence logic (manual instance preempts the shared updater)
- the duplicated entry points (`update_prices_in_background()` _and_ `UpdatePrices().start()`)
- refcount living in module globals while ownership lives on instances

None of that is essential to the problem; it is all tax on pretending instances are independent.
Folding `update_prices_in_background()` into `start()` (the huddle's lighter option) does not
remove the tax — it just relocates the unanswered question (what happens with mismatched config
across instances) from API names into behaviour. Deleting the class answers it by construction.

## User-facing model

"Call `update_prices_in_background()` from anywhere, as many times as you like; close your
handle when done." Libraries (logfire, pydantic-ai) call it config-less and never close.
App authors who want a custom URL pass it, early in startup.

Prior art: the `logging` / threading-singleton pattern — a process-global resource you
reference, not instantiate. The "configure early" rule below is the same discipline
`logging.basicConfig` teaches.

## Config-conflict rule: first-wins + warning

Two callers passing _different_ config (the multi-URL case) is the only real ambiguity.

- **First-wins (chosen):** first caller's config sticks; a later caller with mismatched
  config gets a warning and a handle on the already-running updater. Config-less library
  calls always just join — they never conflict. App authors who want custom config call
  early, before libraries initialize.
- Last-wins / takeover — rejected: reintroduces the exact state machine we are deleting.
- Raise — rejected: a library starting first would crash the app author.

This keeps the lifecycle a monotonic state machine: empty -> configured+running ->
(refcount hits 0) -> stopped. No backward transitions, no preemption.

## Decisions parked deliberately

### Revert-on-close: KEEP today's behaviour

When the last handle closes, prices revert to the package-bundled data (not the
last-fetched snapshot). The "a fetch in flight at stop time can never publish afterward"
fencing invariant therefore **stays**. We considered leaving the fresh snapshot in place
(which would let us drop the fencing entirely) but chose to preserve current semantics for
now. Revisit if/when we want that simplification.

### Fork support: separate, stacked PR

The `os.register_at_fork` hooks (surviving gunicorn `preload_app=True`) are orthogonal and
land as a follow-up so this change can be reviewed on its own. Under the simpler singleton
core the fork story is also easier: one thread, one config, no takeover to revive.

## What stays / goes internally

- A single module `_lock` (`RLock`) — **stays, and is now the only lock.** Load-bearing for
  refcount + thread-handle bookkeeping (two racing first-calls must not both spawn a thread).
  NOTE for the huddle's "worst case is just redundant network calls": that undersells it —
  without the lock, two racing starts leak an untracked daemon thread and corrupt the refcount,
  which is a correctness bug.
- The separate `_snapshot_lock` — **gone.** Its fencing job (ordering the snapshot install in
  the background thread against the stop/revert) is folded onto the same module `_lock`, since
  both ultimately guard the one process-global snapshot. `set_custom_snapshot` is a bare global
  assignment (no internal lock, no callback), so holding `_lock` across it cannot deadlock or
  invert lock order. Result: one lock guarding a trivial state machine (a pointer, an int, the
  snapshot).
- Takeover / precedence / `RuntimeError` "only one active" — **gone.**
- `UpdatePrices.start()/stop()`/context-manager — **gone** (live on only via the deprecated shim).

## Deprecation shape

`UpdatePrices(...).start()` emits `DeprecationWarning` and routes into the singleton with its
config (first-wins); it stores the returned handle and `.stop()` closes it. The context
manager maps to start/close. Behavioural deltas on this deprecated path (e.g. two `.start()`
calls no longer raise; mismatched config warns instead of preempting) are acceptable for a
deprecated surface at 0.x.

## Status / open questions for review

- Confirm with Samuel **why** `stop()` reverts to the bundled snapshot — Alex flagged this as
  worth understanding before we lock in revert-on-close.
- Confirm Alex is bought into deleting the class (his huddle scope was "tweak `start`"), this
  is a larger break — version bump to 0.1.0.
