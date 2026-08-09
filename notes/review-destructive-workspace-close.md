# Adversarial review — `sb workspace close`, the one command that destroys things

Target: `sb workspace close <name>` as built in `03d94c2` and `57cfd2d`, plus
`switchboard/live.py`, the `workspaces` table and its retiring mark (`fe1f560`), and the
liveness work behind "this agent is finished" (`25a777e`, `97362b8`, `5aa874d`).
Specification read: `design/fix-options.md`, Wave 4 section.

## Verdict

**Safe with specific fixes.** I could not make it destroy a checkout that should have been
kept — every failure I found runs the other way: it refuses when it should not, or reports
success while destroying nothing. Two of those are serious enough to fix before a PR: a
retiring mark that nothing can ever clear (F1), and a close that reports the worktree
handled while it is still on disk and still registered (F2).

Suite state at review time: `python -m pytest` → **1657 passed** (ran it myself).

Legend: **PROVED** = I reproduced it and pasted the output. **READ** = established by
reading the code and confirming the surrounding facts. **SUSPECTED** = reasoned, could not
exercise it here; says what it would take.

---

## F1 — A crash inside the destructive window can leave a retiring mark that no flag, no caller and no amount of waiting will ever clear. PROVED

`_close_checkout` (broker.py:1252) wraps the destructive window in `except ValueError`, and
only a `ValueError` releases the mark. Everything else leaves it set:

- `KeyboardInterrupt` — a human pressing Ctrl-C while the panes come down or while
  `git worktree remove` runs. It is a `BaseException`, not a `ValueError`.
- `subprocess.TimeoutExpired` from `_deregister` (broker.py:1611) — that `subprocess.run`
  has a timeout and **no** `try` of its own, unlike every other subprocess call in this
  file. A hanging `git worktree remove` exits by that door.
- `RuntimeError` from `live.is_under` inside the *second* gate — see F6.

The design accepts that ("only a crash may leave one behind, and the way back from a crash
is a person… `--resume`"). The way back does not exist when the owner is the human, which
is the most likely caller of a destructive command. `_owner_gone` (broker.py:1551) returns
`None` for `HUMAN` by an explicit early return, `None` is rendered as "cannot be confirmed
gone, which reads here as still going", and `--resume` is offered *only* for `gone is True`.

Reproduced with `_deregister` raising `TimeoutExpired`, against the repo's own test harness
(script: `notes/review-destructive-repro2.py`):

```
mark after the crash: human
resume=False: refused -> 'api' is already being closed by human, claimed 0s ago, and human
  cannot be confirmed gone, which reads here as still going — one teardown at a time.
resume=True:  refused -> ... `--resume` takes a mark over from an owner confirmed gone, and
  never from a live one.
other caller with --resume: refused -> (same)
```

No route out. `workspace new`, `start --name` and `--workspace` all call `_refuse_retiring`,
so the name is also locked out of being *reopened*. Recovery is hand-editing the store.
This is precisely the shape `_take_over`'s own docstring warns about: "the three rules that
are each right on their own … compose into a name no verb can ever reach again."

**Recommend**, in order of importance:
1. Release the mark on *any* exit from the window, not just `ValueError` —
   `try/except BaseException: release; raise`, or a `finally` with a success flag.
2. Give a human-owned mark a way back. A human has no row, so it can never be adjudicated;
   either treat `HUMAN` as resumable (the person reading the refusal *is* the owner or can
   see whether another terminal is running it) or add an explicit release verb.
3. Put `_deregister`'s `subprocess.run` inside a `try` like `_ignored_weight`'s.

---

## F2 — The recorded path is matched by resolution in one place and by string in another, so a close can report success while the checkout survives untouched. PROVED

- `store.checkout_verdict` (store.py:1194) compares `Path(...).resolve()` on both sides.
- `Broker._deregister` (broker.py:1609) compares `wt["path"] == checkout` — **exact
  strings** — and treats "no match" as `"unregistered"`, i.e. success, and skips the
  removal entirely.

So a recorded path that resolves to the worktree but is not git's own string for it passes
the verdict as `CHECKOUT_OK`, takes the full destructive route, and then quietly deletes
nothing. `_finish` still deletes the branch and still stamps the workspace retired with its
path cleared. Repro (`notes/review-destructive-repro1.py`, recorded path via a symlinked parent — the shape
`/tmp → /private/tmp` and `/var → /private/var` give you on macOS):

```
RESULT: {'kind': 'worktree', 'worktree': 'unregistered', 'branch_deleted': False, ...}
still on disk: True
still registered: ['.../repo', '.../wt/api']
row: {'checkout': None, 'retired_at': 1786280467, ...}
```

And the state it lands in is a dead end (`notes/review-destructive-repro3.py`): the next close returns
`{'already': True, 'kind': 'retired', 'worktree': 'gone'}` while the directory is still
there. `sb workspace list` also renders it `retired` with no checkout, so the listing stops
showing the thing that survived. There is an escape — `sb workspace new <name>` re-attaches
and re-records the real path — but nothing tells the reader that.

Not currently triggered on this machine: I checked the real store read-only, every recorded
`agents.cwd` under `~/.herdr/worktrees/switchboard/` is already git's own string. It bites
wherever the worktree root contains a symlink, which includes anything under `$TMPDIR`.
The test harness sidesteps it deliberately — `test_workspace_list.Harness.setUp` does
`Path(self.tmp.name).resolve()` with the comment "git answers with the real path".

**Recommend**: match by resolved path in `_deregister` (and pass git the path git itself
reported); and on the general path, treat "verdict said OK but the registry has no entry"
as a contradiction to refuse on, not as success. `"unregistered"` as a success value belongs
to `_close_gone`, where it is true.

---

## F3 — `sb workspace list` surfaces checkouts `sb workspace close` structurally cannot act on. PROVED

`workspace_close` refuses outright when `store.get_workspace` returns `None` (broker.py:1120).
The `workspaces` backfill derives rows from `agents` only, so a registered checkout with zero
agent rows never gets one — and that is exactly the case the listing's three-source union was
built to surface. `03d94c2`'s own commit message names it: "only git knows the orphan checkout
with no rows (`fix-options`, on disk, zero rows)". I confirmed `fix-options` is a live entry in
`git worktree list` in `/Users/andrew/Code/switchboard` with no `agents` rows.

```
listed: {'main': ('ok', ['git']), 'orphan': ('ok', ['git'])}
refused -> no workspace called 'orphan' is recorded, so there is nothing here to close
```

**Recommend**: when the name has no row but `git worktree list` reports a checkout for it,
record it and proceed (the gate re-validates the path anyway, so nothing is trusted that
isn't). Failing that, the refusal should name `sb workspace new <name>` as the way in
instead of pointing at the listing that just showed it.

---

## F4 — The re-confirmation may refuse on the shells of the panes the command itself just closed. SUSPECTED

Step 3 re-runs the whole gate, including the `lsof` half, immediately after `_stop_panes`
returns. `close_pane` returning is not the same as the pane's shell having left the process
table, and that shell's cwd is under the checkout. `_live_under` excludes only our own
ancestors and descendants; a pane shell is a child of the tmux/herdr server, not of us, so
it is not excluded. There is no settle, no retry, no bounded wait — one look, then refuse.

If it fires, it fires on the ordinary success path, and it costs the panes: the second gate
runs *after* the panes are down. `test_the_re_confirmation_catches_what_arrived_during_the_stop_step`
asserts exactly that cost is acceptable for a genuine arrival; it is a different trade when
the "arrival" is the command's own teardown.

Not reproduced: the process scan is faked in the tests and I have no real herdr here. What
it would take is one real workspace with a live pane, closed with `lsof` unfaked, run a few
times to see whether the shell is gone by the time the second scan lands.

**Recommend**: after `_stop_panes`, poll for the closed panes' pids to leave (bounded, a
second or two) before the second gate is allowed to refuse — or carry the pids of the panes
we just closed into the second gate's exclusion set.

---

## F5 — `lsof` answers exit-0 while omitting every process the caller does not own. PROVED (measurement)

The module's strictness is about *shape*, and the shape holds — I ran `live.scan()` on this
machine: rc 0, 1428 lines, 357 processes parsed clean, 0.07–0.22s. The unproven item #1 in
the design holds up.

What the shape check cannot see is omission. Same moment, `ps -Ao pid=` reports 561
processes; `lsof` reports 356. Every one of the 205 missing is owned by another user
(116 `root`, the rest system accounts); all 353 of my own are present. So "nothing is
running in that directory" means "nothing **of mine**". A `sudo`-run editor, or a
root-owned daemon or indexer sitting in the checkout, is invisible to the gate and the
removal proceeds. This is the only path I found where the command can destroy something it
should not have.

**Recommend**: at minimum say so — the refusal/success wording claims the machine was asked
and it was asked incompletely. If it matters, the scan can compare its pid set against `ps`
and refuse when the gap is not explainable, though that is likely more cost than the risk
justifies. Worth a line in `live.py`'s docstring either way, since that docstring currently
reads as though the scan is total.

---

## F6 — `Path.resolve()` raises `RuntimeError` on a symlink loop, not `OSError`, so three docstrings describe handling that is not there. PROVED

`live.is_under` (live.py:111), `_same_dir` (broker.py:243) and `store.checkout_verdict`
(store.py:1182) all catch `OSError` with the comment "unreadable, or a symlink loop".
On CPython 3.11:

```
RuntimeError: Symlink loop from '/private/tmp/.../a/x'
```

`OSError` is caught internally by `pathlib` and re-raised as `RuntimeError`. So the loop
case is an uncaught traceback rather than the documented safe answer. In `_gate` it is
mid-window, which means it lands in F1 (mark stranded, no escape). `_same_dir`'s stated
guarantee — "two paths we cannot resolve are treated as the SAME, because … the answer to
that question is never allowed to be a guess" — is the primary-checkout guard and it does
not hold for this input.

Also worth noting the *direction* of `is_under`'s failure: it returns `False`, i.e. "not
contained", i.e. not live, i.e. the gate passes. That is the fail-open direction in a
function whose whole purpose is refusing. Everything else in this change is careful to fail
closed.

**Recommend**: catch `(OSError, RuntimeError)` in all three; and consider whether
`is_under` should raise rather than answer `False`, so the caller can turn it into the
refusal it means.

---

## Smaller things

- `store.checkout_verdict`'s `subprocess.run(["git", "worktree", "list", ...])`
  (store.py:1184) has **no timeout**, alone among the subprocess calls in this change. A
  hung git hangs the command. READ.
- `_finish` (broker.py:1273) falls back to the workspace *name* as the branch when
  `workspace_branch` has nothing. For a workspace with no agent rows carrying a branch,
  that can aim `git branch -d` at an unrelated branch that merely shares the name. `-d`
  limits the damage to a merged branch and the reflog keeps the tip, so this is small —
  but the fallback is a guess in a command that otherwise refuses rather than guesses.
  READ.
- `store.record_workspace` sets `checkout` via `ON CONFLICT DO UPDATE` and does not clear
  `retired_at`, so it can produce a retired row *with* a checkout. `Broker._record_workspace`
  routes around this correctly (it calls `reopen_workspace` for retired rows), so the only
  way in is a direct call to the store function — but the store function is the one with
  the general-sounding name. READ.
- `_inventory_gate` is not re-run at step 3, only the gate proper. An ignored file that
  appears while the panes come down is deleted without having been shown. Mitigated by
  `git worktree remove` refusing a dirty tree, and genuinely marginal. READ.

## Things I attacked and found sound

- The check → stop → re-confirm → delete ordering, and the second gate being the *same*
  function as the first — it is genuinely equivalent, same exclusions, same two halves.
- The records/live disjointness. "Could not tell" survives from `live.scan`'s `None`
  through `processes_in` through `_live_under` to a mandatory refusal, with no place where
  it collapses into "nothing found". `_parents()` failing degrades to the two pids the
  kernel hands us, which costs a refusal — the safe direction, and correct.
- Component-wise containment. `.../fix-options-2/x` does not pass against `.../fix-options`.
  Sibling prefixes are handled everywhere the gate reads a path.
- Caller exclusion. Ancestors and descendants only; another agent's pane, being a sibling
  under the tmux server, is not swallowed. `_ancestry` is cycle-safe. Reading `ps` after
  `lsof` for the sake of `lsof`'s own pid is right and the reasoning in the docstring
  matches the code.
- The retiring mark's atomicity: `UPDATE … WHERE retiring IS NULL` with `rowcount` as
  arbiter, `release` scoped to `WHERE retiring=?`, so a loser cannot clear a winner's mark.
  `--resume` against a live owner is refused, and "cannot tell" reads as live.
- The bare path being separate code rather than skipped steps, and its gate being own-rows
  by name. Routing a workspace that *has* a checkout down it requires a NULL `checkout` on
  a non-retired row, and `_record_workspace` explicitly refuses to write NULL over a live
  path. I could not construct it through the public verbs.
- The primary-checkout refusal as a rule of the gate rather than something git catches last.
- `git worktree remove` by name, never a bare prune; `git branch -d`, never `-D`.
