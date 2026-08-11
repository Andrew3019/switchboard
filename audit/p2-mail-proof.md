# Phase 2, the mail cluster — the evidence

Branch `p2-mail` at `c3271e0`. Two isolated `git clone`s of this repo under this session's
scratchpad, one checked out at the branch and one at `main` (`19fc485`), each driven only
by its own `./bin/sb` from inside itself. Ten throwaway agents (`--model cheap`), all
closed and every worktree, pane and workspace removed afterwards; the live fleet's store
was read once, read-only, to confirm none of these names ever reached it (`0 of 230 rows`).

Suite: `/Users/andrew/anaconda3/bin/python -m pytest tests -q` → **1805 passed**.

---

## 1. Mail nobody can deliver — before and after, same commands, two builds

`cee` is spawned, reports `sb done`, and is then sent one message by the human. Its pane
is still open at that point, so the message is held gently (`mail_unannounced`) and the row
correctly says `1 unread, not picked up` on both builds. Then the pane is taken away:

```
$ ./bin/sb cleanup cee
closed: cee
```

| | `main` | `p2-mail` |
|---|---|---|
| `sb status --needs-me` after the close | `cee  1 unread, not picked up` | `(no agents)  [1 hidden by filters]` |

On `main` that row cannot be moved by anything: the pane is gone, `flush_pending` chases
`unseen()` and the message left that set the moment it was stamped un-announceable, and
`cleanup` has already run. It is the queue entry that never clears.

On the branch, `cleanup` clears the backlog as it takes the pane. Nothing is read, deleted
or hidden — the store row afterwards:

```
{'id': 1, 'to_agent': 'cee', 'read_at': None, 'delivered_at': 1786414242,
 'undeliverable_at': 1786414261,
 'body': 'please also check the migration path — a question you will never read'}
```

and `sb inspect cee` still prints it in full, under `MAIL — 1 unread`, with a
`mail_cleared` event beside it in the log.

## 2. Answering a block by typing into the pane

`bii` (branch) and `mbii` (`main`) are given the same task: run `sb block "which branch
should I target, A or B?"`, stop, and when answered run `sb status` and reply in chat —
never `sb done`. A sibling then sends each one an unrelated message, which is held. Both
sides reach the identical state:

```
state  blocked   herdr: done  << UNDELIVERED 1 << BLOCKED
```

The answer is typed straight into each pane, with no `sb` anywhere:

```
$ herdr pane send-text wF7:p1 "target branch A"; herdr pane send-keys wF7:p1 Enter
```

Ninety seconds later:

| | `main` (`mbii`) | `p2-mail` (`bii`) |
|---|---|---|
| store state | `blocked` | `working` |
| `--needs-me` | `blocked: which branch should I target, A or B?` | `stalled 1m — its turn ended without sb done` |
| the held message | `<< UNDELIVERED 1, 2m` | delivered **and read** |

The branch's event log for `bii`, in order:

```
blocked   {"why": "which branch should I target, A or B?"}
ring_held {"reason": "blocked"}
unblocked {"reason": "answered_in_pane"}
```

The first run of this proof let the agent finish with `sb done` after being answered, and
both builds then looked the same — `done` overwrites `blocked` on its way past. That is
worth recording: the bug only bites while the agent is still working, which is most of the
time an agent is answered, and forever if it never calls `sb done`.

## 3. What the three new tests are worth

Copied onto `main`'s source in the throwaway clone, all three fail there and pass here —
including the queue assertion, which fails with the live defect printed in full
(`state='failed' … unread=1` still in `--needs-me`).

## 4. Not proven

- Nothing here shows what happens if the human answers in the pane and the agent then
  runs no `sb` command at all. The row stays blocked; nothing watches panes and nothing in
  this change does either.
- The same-turn case — an agent that runs another `sb` command after `sb block` instead of
  stopping — was reasoned about, not run: it clears its own block, and the row returns to
  the human's list as STALLED rather than vanishing.
- No endurance run. The queue was watched over minutes, not hours.
