# The doorbell's own build, and mail to an agent that has finished — proof

Run 2026-08-10 03:53–04:02 by agent `fix-doorbell-path`, against branch `fix-doorbell-path`
(`phase-1` + one commit) in an isolated `git clone` under this session's scratchpad, driven
only by the clone's own `./bin/sb`. Two throwaway agents, both closed; the clone deleted.
Nothing installed, nothing pushed, nothing merged, `main`, `DESIGN-TRUTH.md` and
`BUILD-PLAN.md` untouched. Suite: `1776 passed` (was 1764).

## 1. The doorbell delivers with nothing arranged by hand

`audit/phase1-acceptance-3.md` §3.2 measured 55 doorbells in 5.5 minutes, all failed with
`sb: error: argu…`, because `collector.ring_doorbell` ran `shutil.which("sb")` and the board
pane's PATH resolves the machine-wide symlink into the main checkout. It now runs
`doorbell_sb()`, which names the `bin/sb` of the checkout the collector is *running from* —
`panel.ensure_collector` launches it with that checkout on `PYTHONPATH`, so `__file__` is
the answer, and it is the same file `broker._pin_sb` puts in front of a spawned agent's
PATH. PATH stays as the fallback for a `switchboard` with no `bin/` beside it.

Measured in the clone, with a board opened by `sb start` and no PATH arranged by anybody:

| time | what |
|---|---|
| 03:57:14 | `./bin/sb start … --name dbp-two`; the board it opens elects a collector, pid 73040, cwd = the clone |
| 03:57:50 | `./bin/sb tell dbp-two "…"` while it was mid-turn → `ring_deferred`, `delivered_at` NULL. **The last `sb` command anyone ran.** |
| 03:58:22 | delivered — `agent prompt dbp-two You have mail. Run: sb inbox`, rc 0 |
| 03:58:27 | `read_at` set; the agent ran `sb done "woken by the doorbell at 03:58:38"` |

Nothing between 03:57:50 and 03:58:22 was run by me. Over the whole run the collector
published `doorbells: 5, doorbell_error: None, errors: 0`. The control that makes the
error count decisive is the one the acceptance run used: from inside the clone,
`sb flush` (installed, on PATH) → `invalid choice: 'flush'`; `./bin/sb flush` → `rang
nobody`; `collector.doorbell_sb()` → `<clone>/bin/sb`. A doorbell that had run the PATH
build could not have exited 0 even once.

**A board must still be open.** Unchanged and untouched by this: `ring_doorbell` is called
only from `collector.tick`, and only a renderer starts or keeps a collector alive. The
wake-up is still a property of a window being open.

## 2. Mail to a finished agent

`broker._finished_and_unreachable` asked `_agent_states()` whether herdr still listed the
name. An evicted agent *is* listed — as `{"agent": "<name>"}` — and `Agent.from_json` fills
a missing `name` from `agent`, so the guard read its own fallback as proof of the binding
whose loss it exists to detect. `Agent.bound` now carries which of the two the name came
from, and the guard asks that.

Mail that can never be announced is stamped `delivered_at` on the spot
(`store.mark_unannounceable`) and left **unread**: that takes it out of `unseen()`, which is
the set both `flush_pending` and the collector's doorbell chase, while leaving it in the
inbox of an agent whose pane is still open.

Measured, same clone. `dbp-lead` reported done at 03:56:29 (name evicted), and a `tell` at
03:56:38 landed on exactly that state:

- `ring_skipped {"reason": "finished"}` — no herdr call attempted, and `ring_failed` events
  over the whole run: **0** (§6.1 measured 21 in 71 seconds and rising).
- `mail_unannounced`, `delivered_at` set, `read_at` NULL — `sb inspect dbp-lead` still shows
  it, and the agent's own `sb inbox` would still read it.
- 100 seconds with that message sitting there: `doorbells` 5 → **5**, `undelivered` 0.
  Before, that was one spawned `sb flush` every ten seconds for the life of the row.
- `./bin/sb cleanup dbp-lead` → `closed: dbp-lead`, **no `--force`**.
- `sb tell` now says so instead of promising a ring: `sent to dbp-lead (dbp-lead UNREACHABLE
  — herdr no longer answers to its name and the doorbell will not ring again; the message is
  stored and still in its inbox, but somebody has to go to its pane)`.

## 3. Disclosed side effect on the live store

At 03:54:37, before the clone existed, I ran the clone's `./bin/sb status` from **my own
worktree**, which is the live store. Every `sb` command flushes, so the new code ran there
once: seven messages addressed to four agents that finished long ago (`split-fixer` ×4,
`fix-options-2`, `board-teardown`, `main-6`) were stamped `delivered_at` and logged
`mail_unannounced`. None was marked read, none was altered, and all seven still show as
unread in `sb status --needs-me`. What they lost is the retry — which is the fix doing its
job on real data, on rows that are the subject of `2026-08-09-233230`. Every later reading
of any store in this run was `sqlite3 … ?mode=ro`.

## 4. Noticed, not fixed

- **Something types into agent panes.** `audit/phase1-acceptance-3.md` §6.5 recorded this
  twice; it happened again here. `did the doorbell fire before the sleep finished?` was
  sitting unsubmitted in `dbp-lead`'s input box at 04:00. I did not put it there, and no
  result above depends on that pane's input.
- **`2026-08-09-233230` touches the same ground.** Mail to agents that died long ago no
  longer drives the doorbell and no longer pins their rows shut, but it still sits unread in
  the human's list with no way to clear it. That half is untouched.

## 5. Teardown

Created: `dbp-lead`, `dbp-two`, both in the clone, both closed with `sb cleanup` (no
`--force`). `herdr workspace list` afterwards holds neither. The one collector the run
started was killed **by pid** (73040, cwd verified as the clone first); no `pkill`, scoped
or otherwise, was used. The clone directory was deleted. The live fleet's collector (pid
1871) was running before this and is running after it.
