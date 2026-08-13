# Resolving four stale BUGS.md entries (2026-08-12)

Brief: `/private/tmp/claude-501/-Users-andrew-Code-switchboard/b33424bc-3874-4f8c-aeb2-10ee998636c2/scratchpad/briefs/bugs-writeup.md`.
All four turned out to be resolvable from the code, following BUGS.md's own convention of
dated postscripts (nothing deleted, corrections appended). No entry needed to go to Andrew.

## 1 & 2. `Herdr.wait` bugs (table entries 2 and 3)

Both were already marked `STATUS: FIXED in the adapter` (BUGS.md:191, :263). The open
question from the brief was whether the surviving `Herdr.wait` method (herdr.py:994) is
still reachable, since `sb wait` — the CLI verb that used to call it via
`status.wait_for` — was deleted in phase 3.

Checked with grep across the whole tree:

- `Herdr(...)` is constructed in exactly three places: `switchboard/cli.py:612`,
  `switchboard/collector.py:197`, `scripts/06-board.py:94`.
- `.wait(...)` is called nowhere in any of those files, nor anywhere else in
  `switchboard/`. Every remaining call site is in `tests/test_herdr.py` (lines 608, 614,
  626, 633, 645, 660, 753).
- `status.wait_for` and `status._next_transition`, the functions that used to call
  `Herdr.wait`, no longer exist in `switchboard/status.py` — confirmed by grep, they are
  simply absent.

So the existing postscript on entry 5 (BUGS.md:446-451), which says "`Herdr.wait` survives
... and are still live code," is misleading: it's live in the sense of "still in the file
and tested," not in the sense of "reachable from any `sb` command." I added a follow-up
postscript (BUGS.md, after line ~451) correcting this, and appended a note to table rows 2
and 3 pointing at it. This is dead code, not a live bug — nothing for Andrew to decide.

## 3. `timeouts.gone_grace` / the `ask`-timeout entry (BUGS.md:550)

This entry (under "STATUS UPDATE — 2026-08-07", BUGS.md:547-554) isn't one of the five
numbered table entries — it's a fix logged inline, for "`ask` waiting out its timeout on a
child that died recording nothing." It says the fix reads `timeouts.gone_grace` (300s) from
`defaults/settings.toml`.

Checked: neither `ask` (as a CLI verb or a function) nor `_will_never_answer` nor
`gone_grace` exist anywhere in `switchboard/*.py` or `defaults/settings.toml` any more.
`sb ask` was deleted in the same phase-3 sweep as `sb wait` ("no agent waits on another
agent" — same phrasing as the `sb wait` postscript already in the file). What does exist
today is `gone_confirm_grace` = 60.0 (`defaults/settings.toml:242`), read into
`GONE_CONFIRM_GRACE` at `switchboard/status.py:226`, and used by `_confirmed_gone`
(status.py:852) / `_record_gone` (status.py:970) — the general "has `collect` seen this row
absent long enough to call it dead" reconciliation that runs on every `sb` call, not a
blocking wait inside a deleted `ask` command.

These are different mechanisms answering different questions, not the same setting renamed:
`gone_grace` gated how long a blocking `ask` call would keep waiting on one specific child;
`gone_confirm_grace` gates how many consecutive absent readings the passive reconciler
needs before it marks any row dead. The entry's bug (a blocked `ask` sitting out its whole
timeout) died with `ask` itself — nothing at the new name inherited it. Added a postscript
saying so.

`REVIEW.md:328` repeats the same stale `gone_grace`/300s reference in its "Still open"
section. I left `REVIEW.md` untouched — it's a dated snapshot of one review pass
(2026-08-07), not a document with an established postscript/correction convention like
BUGS.md, and the brief's targeted-pass instruction argued against extending edits into it.
Noted the staleness in the BUGS.md postscript instead, so anyone who follows the reference
from REVIEW.md lands on the correction.

## 4. The haiku / effort-level entry (BUGS.md:579-582)

Entry says `defaults/models.toml` `tiers.cheap` resolves to `sonnet` at `effort = "low"`.
Checked `defaults/models.toml:38-53`: `tiers.cheap` is `sonnet` at `effort = "medium"`
(line 53), not `low`. The file's own comment (lines 39-44) explains the change: the
`cheap` tier used to have one consumer (`researcher`) where low effort was fine, but an
orchestrator's first move is now to spend a researcher agent understanding a task before
splitting it — making that tier's output load-bearing for the whole job, which is why
effort was moved up a notch.

The underlying fix (no tier uses haiku) is still correct and unchanged; only the effort
number drifted after the entry was written. Added a one-line postscript correcting `low` to
`medium`. Nothing for Andrew to decide.

## Scope note

Did not sweep the rest of BUGS.md or REVIEW.md beyond these four items, per the brief.
While reading around, table entry 1 (`Broker._adopt`) and its postscript looked internally
consistent and current — not re-verified beyond a skim, since it wasn't in scope.
