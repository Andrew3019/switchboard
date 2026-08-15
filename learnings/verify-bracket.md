# Does the workspace bracket appear for two agents genuinely sharing a worktree?

QA log for `notes/task-verify-bracket.md`. Agent `qa-2`, branch `qa-2`.
Mockup under test: `scripts/board_mockup.py` on branch `worker-28`, commit `2f0c05b`
("mockup: fill the pane, with NEEDS YOU and the footer pinned to the bottom") — the tip
at the time I cloned it.

**Answer: YES.** On a live fleet, in an isolated clone, with two worktrees each genuinely
holding three agents, the mockup drew a bracket around exactly those agents — two
brackets, distinct — left the top orchestrator unmarked, and gave the one single-agent
workspace a lone `·`. Frame at 67 columns below.

Test fleet fully torn down (see "Teardown").

---

## Isolation

Everything ran in a throwaway clone, never in Andrew's fleet:

    /private/tmp/claude-501/-Users-andrew--herdr-worktrees-switchboard-qa-2/\
      e0129a47-62e7-4770-a282-10a5a593299e/scratchpad/sbclone

`git clone /Users/andrew/Code/switchboard sbclone`, then `git checkout -b worker-28
origin/worker-28`. Its own `.git`, so its own store (`<clone>/.git/agentflow/state.db`)
and its own snapshot (`<clone>/.git/agentflow/panel/snapshot.json`). Every `sb` call was
the clone's own `./bin/sb`, run from inside the clone; `sb status` printed `(no agents)`
before I began. Forked worktrees landed under `/Users/andrew/.herdr/worktrees/sbclone/…`,
a different tree from the live fleet's `/Users/andrew/.herdr/worktrees/switchboard/…`.

---

## The fleet, and that it really shares worktrees

`sb start` is refused for agents (`cli._agent_caller`, `switchboard/cli.py:509-539`;
`DESIGN-TRUTH.md:49`), so Andrew ran the one human-only command himself, in the clone:

    ./bin/sb start --name qa2top "Read notes/qa2-top-task.md and do exactly what it says."

Everything after that was the fleet building itself from fixture task files I had
committed in the clone (`notes/qa2-top-task.md`, `notes/qa2-mid1-task.md`,
`notes/qa2-mid2-task.md`, clone-only commit `7fcc398`, never pushed): the top delegated
two `orchestrator` children and one `qa` child, and each orchestrator delegated two `qa`
children of its own.

Resulting rows, read straight out of the clone's SQLite `agents` table:

| name | parent | workspace | branch | cwd |
|------|--------|-----------|--------|-----|
| qa2top   | (none) | qa2top  | (none) | …/scratchpad/sbclone *(the clone itself — bare, no checkout of its own)* |
| qa2ws1   | qa2top | qa2ws1  | qa2ws1 | /Users/andrew/.herdr/worktrees/sbclone/qa2ws1 |
| qa2ws1-a | qa2ws1 | qa2ws1  | qa2ws1 | /Users/andrew/.herdr/worktrees/sbclone/qa2ws1 |
| qa2ws1-b | qa2ws1 | qa2ws1  | qa2ws1 | /Users/andrew/.herdr/worktrees/sbclone/qa2ws1 |
| qa2ws2   | qa2top | qa2ws2  | qa2ws2 | /Users/andrew/.herdr/worktrees/sbclone/qa2ws2 |
| qa2ws2-a | qa2ws2 | qa2ws2  | qa2ws2 | /Users/andrew/.herdr/worktrees/sbclone/qa2ws2 |
| qa2ws2-b | qa2ws2 | qa2ws2  | qa2ws2 | /Users/andrew/.herdr/worktrees/sbclone/qa2ws2 |
| qa2solo  | qa2top | qa2solo | qa2solo | /Users/andrew/.herdr/worktrees/sbclone/qa2solo |

Sharing confirmed from the data *and* from disk, which is what the task asked for:

- `qa2ws1`, `qa2ws1-a`, `qa2ws1-b` all carry `workspace = "qa2ws1"` **and the same
  `cwd`**; same for the three `qa2ws2` rows;
- `git worktree list` in the clone showed **one** entry per workspace —

      …/scratchpad/sbclone   7fcc398 [worker-28]
      …/worktrees/sbclone/qa2solo   7fcc398 [qa2solo]
      …/worktrees/sbclone/qa2ws1    7fcc398 [qa2ws1]
      …/worktrees/sbclone/qa2ws2    7fcc398 [qa2ws2]

  three agents to one checkout, not three checkouts that happen to be named alike;
- depths in the published snapshot were `qa2top 0`, `qa2ws1/qa2ws2/qa2solo 1`, the four
  grandchildren `2` — so the shared runs' shallowest row is depth 1, which is what the
  gutter rule turns on.

The snapshot was published by the clone's own collector and was **2.0 s old** when read
(`collected_at`, `format 1`, pid 67179) — this is live data, not a fixture and not
archived.

## The frame — 67 columns

`scripts/board_mockup.py --once --width 67 --height 22 --source live`, run inside the
clone, `NO_COLOR=1`:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 8 alive                                          │
│  ● qa2top        idle       19s                                 │
│  ◌ ╭ qa2ws1      idle      1h40  STALLED — idle 1h40            │
│  ○ │   qa2ws1-a  failed    1h43                                 │
│  ○ ╰   qa2ws1-b  failed    1h42                                 │
│  ● ╭ qa2ws2      working   1h41                                 │
│  ○ │   qa2ws2-a  failed    1h40                                 │
│  ○ ╰   qa2ws2-b  failed    1h39                                 │
│  ○ · qa2solo     failed    1h41                                 │
│    + 4 archived                                                 │
│                                                                 │
│                                                                 │
│                                                                 │
│                                                                 │
│                                                                 │
│                                                                 │
│                                                                 │
│  NEEDS YOU · 1                                                  │
│   IDLE     qa2ws1  idle 1h40, nothing running                   │
│ live snapshot · mockup, not the board                           │
╰─────────────────────────────────────────────────────────────────╯
```

Every claim in the task's checklist, read off that frame:

- **A bracket around exactly the agents sharing a worktree.** `╭ │ ╰` spans `qa2ws1`,
  `qa2ws1-a`, `qa2ws1-b` — the three rows with `workspace = qa2ws1` — and nothing else.
  Same for the `qa2ws2` three. No row outside a shared workspace is enclosed.
- **The top orchestrator is unmarked.** `qa2top` has no bracket and no dot.
- **A single-agent workspace shows a dot.** `qa2solo`, one agent in its own worktree,
  gets the `·`.
- **A run of three runs the full height.** The rule is corner-rule-corner, not two
  corners: `╭` on the lead, `│` on the middle row, `╰` on the last. The bracket is drawn
  inside the indentation, so the name column did not move — `qa2top` and `qa2ws1` still
  start at the same column.
- **Two multi-agent workspaces on screen at once stay distinct.** `qa2ws1`'s `╰` and
  `qa2ws2`'s `╭` are adjacent lines and read as two brackets, not one: the run closes and
  a new one opens. They are at the same indent and (in colour mode) the same cyan, so
  what separates them is the corner glyphs alone — which is exactly what
  `gutter_column`'s docstring argues for over rotating colours. It works, but it is a
  one-character distinction between two touching groups; worth Andrew's eye rather than
  my verdict.
- **A collapsed-archive row did not break grouping.** `+ 4 archived` (my earlier torn-down
  fleet) sits below the last run and carries no mark, as `group_runs` says it should.

### Other widths — the gutter holds, but a truncated run is left unclosed

Same live snapshot at `--width 40 / 50 / 100` (height 14, so the list truncates):

```
╭─ switchboard ────────────────────────╮        ╭─ switchboard ──────────────────────────────────╮
│  switchboard · 8 alive               │        │  switchboard · 8 alive                         │
│  ● qa2top        idle                │        │  ● qa2top        idle        1m                │
│  ◌ ╭ qa2ws1      idle     STALLED —… │        │  ◌ ╭ qa2ws1      idle      1h40  STALLED — id… │
│  ○ │   qa2ws1-a  failed              │        │  ○ │   qa2ws1-a  failed    1h44                │
│  ○ ╰   qa2ws1-b  failed              │        │  ○ ╰   qa2ws1-b  failed    1h43                │
│  ● ╭ qa2ws2      working             │        │  ● ╭ qa2ws2      working   1h42                │
│  ○ │   qa2ws2-a  failed              │        │  ○ │   qa2ws2-a  failed    1h41                │
│   + 3 more below                     │        │   + 3 more below                               │
```

The gutter costs no columns at any width — it is drawn into indentation the row already
had — and the name column is unmoved down to 40. One cosmetic consequence, not a bug and
not fixed by me: when `+ N more below` cuts a run, the bracket that is still open ends in
`│` with no `╰`, because its closing row is off-screen. It reads as "this group continues
below", which is arguably right, but it is a shape nobody has looked at deliberately.

---

## Two things found on the way (reported, not fixed)

**1. A `worker` cannot delegate, so it cannot be the middle of the chain.** My first
attempt built the shape with `--role worker` in the middle; the worker forked a worktree
fine and then reported:

    Both sb delegate attempts failed with the same error:
      'a worker does not spawn agents — only a …'

That is `Broker._refuse_bare_delegate` → `roles_mod.get(...).delegate`
(`switchboard/broker.py:711`). Correct behaviour — but anyone reproducing a shared
worktree must give the middle agent `--role orchestrator` or no sharing ever happens.

**2. A human-rooted shared workspace gets no mark at all.** Before Andrew's `sb start` I
built the same sharing with *me* as the parent: `sb delegate --role orchestrator --name
qa2mid` from the human position, and `qa2mid` then delegated `qa2kid-a` and `qa2kid-b`.
The store confirmed all three shared `workspace = qa2mid` and one `cwd`
(`/Users/andrew/.herdr/worktrees/sbclone/qa2mid`, one `git worktree list` entry, three
panes of herdr workspace `w1DB`). The frame at 67 columns:

```
╭─ switchboard ───────────────────────────────────────────────────╮
│  switchboard · 4 alive                                          │
│  ○ qa2lead     done     5m                                      │
│  ● qa2mid      idle     1m                                      │
│  ◌   qa2kid-a  idle     2m  STALLED — idle 2m                   │
│  ◌   qa2kid-b  idle     1m  STALLED — idle 1m                   │
╰─────────────────────────────────────────────────────────────────╯
```

No bracket, and no dot on the single-agent workspace either. `gutter_column` skips a run
whose shallowest row is depth 0 ("a depth-0 run is a top's own workspace"), and a
human's direct delegate *is* depth 0 — so three agents demonstrably sharing one worktree
are drawn unmarked. This only arises when a human delegates directly instead of using
`sb start`, so it is not what Andrew's fleet looks like. Reporting it, not calling it a
bug, and not fixing it.

---

## Teardown

Test fleet gone, verified rather than assumed:

- `sb cleanup` leaves-up: the five grandchildren/solo, then `qa2ws1 qa2ws2`, then
  `qa2top` (naming a parent before its children is refused — "the subtree closes from
  the leaves up").
- `sb workspace close qa2ws1 / qa2ws2 / qa2solo --yes` → "worktree removed" each;
  `qa2top` → "no checkout of its own, so nothing was deleted".
- `git worktree list` in the clone is back to the clone alone.
- `herdr workspace list` has no `qa2*` workspace and no `sbclone` workspace left.
- The earlier fleet (`qa2lead`, `qa2mid`, `qa2kid-a`, `qa2kid-b`) was torn down the same
  way before Andrew's command.
- Two `switchboard.collector` processes existed; I checked each one's cwd with `lsof` and
  killed **only** pid 67179, the one whose cwd was the clone. The live fleet's collector
  (pid 40401, cwd `…/worktrees/switchboard/accept-concurrent`) was left running. Same for
  pid 42623 earlier, the clone's first collector. No `pkill`, ever, scoped or otherwise.
- No process with a cwd inside the clone remains.

The clone directory itself is still on disk in my scratchpad; it holds nothing running.

---

## What I did not test

- **Colour.** Every frame here was captured with `NO_COLOR=1`. Whether the gutter's cyan
  reads well against the border's blue, and whether two touching brackets are
  distinguishable *in colour*, is unchecked — I read text.
- **`--gutter bar|tick|none` and `--gutter-colour rotate`.** Only the default `bracket`
  and `single` were exercised.
- **A run of four or more.** Three is what I built; the middle `│` repeating for a
  fourth row is code-evident but unrendered. I started to add a fourth child and stopped
  when the run was interrupted.
- **The real board.** `switchboard/board.py` was never run. This is the mockup only, and
  the mockup deliberately reimplements the board's rules rather than importing them, so
  nothing here says the board agrees with it.
- **The repo's test suite** was not run: I changed no code, only added this note.
