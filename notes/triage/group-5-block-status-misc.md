# Group 5 — block, status display, collector, plugins

Triaged against HEAD `fb04859` (2026-08-15). Method for every report below is **by
reading** (code + git history); no live run was made — see the note at the end for what
that leaves unproven.

## 2026-08-11-045346-sb-block-reports-success-but-the

**Verdict:** STILL BROKEN
**Severity:** high
**Evidence:** The defective path is still there and it explains the report exactly.
Every `sb` command resolves the caller first — `me = b.whoami()` (`switchboard/cli.py:784`),
for *every* verb including `sb plugin`. `whoami` → `_revive`, whose blocked branch flips
the row straight back to `working` and logs `unblocked reason=answered_in_pane`
(`switchboard/broker.py:657-663`). Its own docstring names the cost in as many words:
"an agent that runs another `sb` command in the same turn AFTER `sb block` … clears its
own block" (`broker.py:621-627`). main-7 did precisely that — its next act after blocking
was `./bin/sb plugin report-bug file …`, the filing in this very report — so by the time
Andrew looked, the row was no longer blocked. The eviction fix that could otherwise
explain it (`2fce8cc`, 2026-08-10) was already in the reported build `5998a43`, and the
store→snapshot→board render path for a blocked row is intact and test-covered
(`board.marker` at `board.py:214`, `tests/test_board.py:113,223`).
**Issue title:** A blocked agent silently un-blocks itself the moment it runs any other `sb` command, including a read-only one
**Issue body:**
`sb block` sets `state=blocked` and returns. The very next `sb` command from that pane —
any verb, including read-only ones like `sb status`, `sb inbox` or `sb plugin todo list` —
goes through `Broker.whoami()` → `Broker._revive()` (`switchboard/cli.py:784`,
`switchboard/broker.py:657-663`), which sets the row back to `working` and writes an
`unblocked` event. The agent is still stopped and waiting on a person, but the board no
longer says so, and its held mail stops being held.

This is deliberate as far as it goes — the same rule is how "the human typed the answer
into the pane" clears a block — but it cannot tell the human answering from the agent
itself, and every shipped prompt tells agents to file bugs and tidy up, which is `sb`.
It reproduced in the wild on 2026-08-11: main-7 blocked, then filed a bug report with
`sb plugin report-bug file`, and Andrew saw no blocked row. `block` is the one channel to
a person, so losing the signal is a wedged agent nobody is coming for. The row only
returns to NEEDS YOU later, as `STALLED`, under a heading that names the wrong problem.

Likely fixes: only revive on a verb an agent takes to *act* (not the read-only ones), or
have `block` stamp a marker so a same-turn `sb` call by the blocked agent itself does not
count as an answer.
**Same-as:** none certain in my group; any report of a blocked agent's row reading
`working`/`STALLED` instead of blocked is probably this.

## 2026-08-09-214534-sb-block-refuses-a-multi-line-reason

**Verdict:** FIXED
**Severity:** low
**Evidence:** The complaint filed was the wrong citation, not the refusal. `sb block` no
longer goes through `validate.line` (whose text names herdr's `invalid_agent_argument`);
it has its own `validate.reason` (`switchboard/validate.py:122-163`), which refuses a
newline *and* a reason over `[limits] block_reason` = 200 chars
(`defaults/settings.toml:219`), with one message that blames nobody but the field's job:
"It is bookkeeping on a board row, NOT the message the human reads". Landed in `0f69733`
(2026-08-09 22:33, ~48 min after this was filed) and refined in `e85abc5` (2026-08-14).
`cli.py:381` is the call site.

My call on your question: **not a bug, and the badly-worded error was the whole of it.**
A block reason is a row label; the message goes in the agent's own chat. The refusal now
says that, so an agent that hears it stops flattening its message to fit — which is what
the old herdr-citing wording actively taught it to do.
**Same-as:** 2026-08-09-002336 (same root cause — agents were putting the whole message
in the reason field; both are closed by `0f69733`).

## 2026-08-09-002336-sb-status-truncates-a-blocked-agent-s

**Verdict:** FIXED
**Severity:** low
**Evidence:** The truncation is real and still there — `status.py:1754` clips the reason
to 70 chars in the `NEEDS YOU` block, while the detail view prints it whole
(`status.py:1988`) and the board row prints `BLOCKED — <why>` clipped only by terminal
width (`board.py:214`, `richboard.py:239`). But the bug as filed was "the human never sees
the question", and that premise no longer holds: a reason can no longer *contain* a
question. `0f69733` caps it at 200 chars and the refusal (`validate.py:156-162`) tells the
agent the human reads its chat and nothing in this field, and `status.py:1740-1743` says
in the code that this list is not the human's inbox at all — `sb board` is.

You asked for a call, so: **the truncated compact line is not the bug.** Closing the door
at the source (an answer cannot be filed here) is what fixes the incident; a 70-char
pointer in an *agent-facing* list is the right shape for a pointer. Residual worth
knowing but not worth an issue: cap 200 vs clip 70, so the tail of a legal reason is
invisible in `sb status --needs-me`. Cosmetic, and the full text is one `sb inspect` away.
**Same-as:** 2026-08-09-214534.

## 2026-08-11-014308-the-collector-runs-stale-pre-fix-code

**Verdict:** FIXED
**Severity:** high (it cost ~4h of held mail when it bit)
**Evidence:** `9751d0f` "Collector: exit when its own source changes on disk"
(2026-08-11 01:54, eleven minutes after this was filed). The collector now hashes its own
`switchboard/*.py` at startup and re-hashes every `SOURCE_CHECK_GAP`
(`collector.py:348-411`), and on a difference breaks the loop at a tick boundary
(`collector.py:539-545`); the lock goes with the process and a renderer elects a fresh
one within seconds. Content hash, not a commit, so an uncommitted working-tree edit counts
— the case that actually happens. Pinned by `tests/test_panel.py:561-592`. The report's
own "no mechanism publishes a code version" is exactly what got added.
**Same-as:** the two mail-delay reports this incident is blamed for in `collector.py:43-45`
— 2026-08-09-004538 and 2026-08-09-035933 (both in someone else's group).

## 2026-08-07-202820-sb-plugin-todo-drop-is-human-only-and

**Verdict:** STILL BROKEN
**Severity:** low
**Evidence:** `drop` is still registered `audience="human"`
(`defaults/plugins/todo/__init__.py:98`) while `add`, `list`, `show` and `done` are
`"both"`. There is no `update` verb and no way to re-state an existing row, so an agent
that filed a todo by mistake has exactly one route: `todo done`, which records the mistake
as finished work. The gate itself is defensible — "not going to happen" is a priority call
— but withdrawing your own bad filing is not a priority call, and it has no route at all.
**Issue title:** An agent can file a todo but has no way to withdraw one it filed by mistake
**Issue body:**
`sb plugin todo add` is open to agents; `sb plugin todo drop` is `audience="human"`
(`defaults/plugins/todo/__init__.py:98`), and there is no other verb that changes an
existing row's state. An agent that adds a todo in error can only close it with
`todo done`, which writes `state: "done"` — the list then claims work was finished that
never existed. The agent prompt fragment actively encourages filing (`todo/agent.md`:
"work you notice but were not asked to do: `todo add …`"), so mis-filings are expected,
not exotic.

Two cheap shapes: open `drop` to agents but only for a row whose `created_by` is the
caller; or add an agent-visible `withdraw` that writes `state: "withdrawn"` (the state
vocabulary is deliberately open — see the module docstring). Low priority: the noise is a
stale row, nothing is lost.
**Same-as:** none.

## 2026-08-08-020044-still-files

**Verdict:** NOT A BUG
**Severity:** low
**Evidence:** Malformed test filing — title "still files", filed `by: human` from a
`tmp…/repo/not json at all` worktree with `sb: not json at all`. No command, expected or
actual. It is the artefact of a test that checks report-bug still files when the context
probe returns garbage. Nothing to triage. (Confirmed as such in the triage brief.)
**Same-as:** none.

## 2026-08-14-143944-agents-can-be-spawned-into-an

**Verdict:** DUPLICATE of GitHub issue #38
**Severity:** high (as #38)
**Evidence:** #38 ("Agents wedge on Claude Code's first-run auto-mode dialog…", opened
2026-08-14 22:07, ~7h after this filing) is the same incident, investigated far further:
it has the decompiled dialog gate, the `~/.claude.json` `autoModeEnvSetup` state showing
it re-arms ~2026-08-21, why `_interrupt` cannot clear it, and three undecided options.
**What #38 is missing from this report:** only the pointer that this filing supersedes the
earlier report `2026-08-14-125645`, which blamed `--interrupt` as the trigger — worth
knowing so that older report is not triaged as a separate bug.
**Same-as:** 2026-08-14-125645 (the superseded, wrong-cause version of the same incident).

---

**Unproven, stated:** no live run was made for any of these. The one that most deserves
it is `2026-08-11-045346`: the mechanism is plain in the code and matches the reported
sequence, but I did not reproduce it. What would settle it: in a throwaway clone, have an
agent call `sb block "x"` and then any second `sb` command in the same turn, and read the
row's state — I expect `working`, plus an `unblocked reason=answered_in_pane` event that
no human caused.
