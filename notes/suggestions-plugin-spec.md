# Spec: the `suggestions` plugin

Approved in principle by Andrew on 2026-08-15. Built as a sibling of `report-bug`, whose
conventions this follows exactly unless stated otherwise.

## Purpose

An agent that hits recurring friction while doing its task files it, so the cost lands
somewhere instead of dying in a `sb done` summary. `report-bug` catches "sb is broken";
this catches "sb works and is costing me anyway."

## Scope and constants

| Thing | Value | Why |
|---|---|---|
| `API` | `1` | Same as report-bug. |
| `SCOPE` | `"user"` | A suggestion about switchboard is a fact about switchboard, not about the repo you stood in. Same reasoning as report-bug's docstring. |
| `LOCK` | `False` | Filenames cannot collide; nothing for a lock to protect. |
| `STAMP` | `"%Y-%m-%d-%H%M%S"` | Chronological sort, readable as a date. |
| `MAX_SUMMARY` | `200` | Detail goes in the flags. |
| `SLUG_MAX` | `40` | Same. |
| `TAIL_LINES` | `20` | Same cap, same reason: evidence, not transcript. Not agent-raisable. |
| `TIMEOUT` | `5` | Subprocess version calls. |

One markdown file per suggestion in `ctx.state_dir`. No index, no database, no dedup.

## The bar, enforced in code

This is the whole design. A suggestion that does not clear the bar is **refused**, not
filed with empty fields. Three flags, all required; `file` returns `ok=False` naming the
missing one:

- `--friction` — what you actually hit in the task you were doing. Concrete, not
  hypothetical.
- `--cost` — what it cost you. Time, retries, extra agents, work thrown away.
- `--recurs` — why this will happen again, or where you have already seen it happen.

Rationale for `--recurs` specifically: Andrew's condition is that the friction be
"decently frequent". An agent cannot be trusted to self-assess frequency in the abstract,
so it is asked for evidence of recurrence rather than a rating.

Cross-task frequency needs no mechanism. Following report-bug's no-dedup doctrine: the
same suggestion filed by five agents is five files, and five files IS the frequency
signal. Identical summaries produce identical slugs and sort adjacently, so `list` shows
repetition for free.

## Commands

Mirroring report-bug's `register()` exactly:

- `file` (audience both) — positional `what` (one line, <= `MAX_SUMMARY`), plus the three
  required flags above.
- `list` (audience both) — every suggestion filed on this machine.
- `show <id>` (audience both) — one in full; partial ids resolve if unambiguous.
- `drop <id>` (audience **human**) — delete. Agents must not be able to bin their own
  or each other's suggestions.

## Captured automatically

Identical to report-bug, and reuse its helpers wherever they are importable rather than
copying: sb version (`git describe --always --dirty`), herdr version, python, platform,
repo and worktree, filing agent, and the bounded session tail via `sb inspect --json`.
Tail is skipped silently when a human files or when it cannot be read.

## Explicit non-goals

- **No dedup, no index.** Duplicates are the signal.
- **No surfacing.** Deferred by Andrew, same as bugs. Recorded here as the known risk:
  `todo` was unbound from `all` precisely because a list nobody is driven to read does not
  repay its per-spawn cost. This plugin has the same failure mode and it is accepted
  knowingly, not overlooked.
- **No auto-implementation.** Filing a suggestion never changes code and never spawns
  anything.
- **No priority or severity field.** Nothing consumes it.

## Binding

Two states, both needed:

1. Enabled in `plugins.toml`.
2. Bound in `defaults/presets.toml` under `all = [...]`, alongside `@report-bug`.

Bound to `all` because an agent that is not told the verb exists will never use it. Note
the standard that file sets for `all`: "genuinely universal and nothing that is merely
useful belongs here", paid on every spawn forever. The fragment must therefore be short
and fit well under `[limits] plugin_fragment` (4000).

## Tests

Two or three, pinning decisions rather than buying confidence:

1. `file` refuses when any of `--friction`, `--cost`, `--recurs` is missing, and names it.
2. `file` with all three writes one markdown file containing all three fields.
3. `drop` is refused for an agent caller and allowed for a human.

Unproven and stated: that agents actually file good suggestions, and that anyone reads
them. Neither is testable here.
