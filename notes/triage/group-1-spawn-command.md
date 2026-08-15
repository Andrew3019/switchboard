# Group 1 triage — spawn command construction (shell quoting, prompts)

Four reports. **All four are FIXED**, by two commits. Three of the four are the same bug
seen three times; the fourth is its sibling in the same function.

Decided **by reading** in every case: current code at HEAD, the commits that changed it,
and `tests/test_herdr.py` (59 tests, all passing at HEAD —
`/Users/andrew/anaconda3/bin/python -m pytest tests/test_herdr.py`). No live spawn was
run; see "What is not proven" at the bottom.

## The two commits that close this group

- **`146240a`** (2026-08-08 03:18) — *Deliver the prompts, then make them worth
  delivering*. One `--append-system-prompt` flag carrying all fragments joined, instead of
  one flag per fragment. `claude` honours only the last such flag and discards the rest.
- **`1120221`** (2026-08-12 21:04) — *spawn: hand the system prompt over as a path, not as
  12KB of typed line*. The prompt is now written to a file and passed as
  `--append-system-prompt-file <path>`, so the line typed into the pane's shell is ~300
  bytes rather than ~12KB.

`1120221` is the one that matters for the parse errors. The root cause was never the
quoting logic: `herdr agent start` **types** the provider command line into the pane's
shell, and a shell still running its startup files leaves the tty in canonical mode, where
the line discipline keeps `MAX_CANON` bytes (1024 on this machine) and silently discards
the rest. A 12KB single-quoted prompt was cut mid-argument, which left the quote open and
handed zsh the trailing parentheses and backticks of the protocol text unquoted — hence
`parse error near ')'`. The commit message records the measurement: 8/8 fresh panes given
a 12,143-byte line delivered exactly 1024 bytes; 8/8 given the real quoted prompt were
left on `dquote>`; 8/8 given a ~300-byte line naming a file delivered all 12,078 bytes.

Current code: `switchboard/herdr.py:473-515` (`_prompt_flags`) and `herdr.py:577-580`.
Both spawn call sites — `broker.py:3194` (delegate/start) and `broker.py:3952` (restore) —
go through `start_agent`, so there is one path and no second one to drift.

Pinned by regression tests: `tests/test_herdr.py:131` asserts the typed line is under 1024
bytes and that the prompt text itself is absent from it; `tests/test_herdr.py:157` asserts
one flag and the fragments joined whole and in order.

## On the free datum from my parent

`sb delegate` refusing a task containing a newline is **adjacent, not the fix**. It is
`validate.line()` in `switchboard/validate.py:104-119`, and it enforces herdr's rule that
no agent *argument* may contain a newline (`invalid_agent_argument`). That function is
present in the **initial commit `86fac25` (2026-08-07)** — it predates all four of these
reports rather than being a guard added since. It also guards the wrong thing for these
reports: the failures were driven by prompt *length* on a typed line, not by newlines, and
none of the reported tasks contained one.

---

## 2026-08-11-195801-the-claude-command-switchboard-builds

**Verdict:** FIXED
**Severity:** high (a spawn produced a dead pane and no agent)
**Evidence:** by reading. Filed 2026-08-11 19:58 against `sb 8ce345c`; `1120221` landed
2026-08-12 21:04, one day later, and removed the mechanism — the ~12KB prompt is no longer
typed into the shell at all, so there is nothing for `MAX_CANON` to truncate and no cut
quote to expose the protocol's parentheses. `herdr.py:504-515`; pinned by
`tests/test_herdr.py:131`. The report's own diagnosis ("the single-quoted prompt appears
to terminate early") is exactly right about the symptom and the commit's measurement
explains why.
**Same-as:** 2026-08-09-221323, 2026-08-08-232843 — one bug, three sightings.

## 2026-08-09-221323-sb-delegate-can-dump-the-whole-agent

**Verdict:** FIXED
**Severity:** high (two of three spawns in a batch lost, delegate reporting success)
**Evidence:** by reading. Two halves, both closed. The parse error and the prompt echoed
into the pane shell: `1120221`, as above. "delegate reports success" while the row says
`state=working`: `97362b8` (2026-08-09, *Stop the close loop and the spawn path from lying
about what happened*) — a `start_agent` that exhausts its retries now writes
`store.set_state(..., GONE_STATE)` and logs a `spawn_failed` event before re-raising
(`broker.py:3195-3212`), so the row reads failed rather than working.
**Unproven / not mine:** one sentence in this report describes a different failure mode —
"a second spawn in the same batch left pane w1T:p1 completely empty (no session id, no
cwd)". Nothing in `1120221` or `97362b8` addresses an empty pane, and I did not settle it.
It looks like the subject of `2026-08-09-161323-second-spawn-failure-mode-agent-starts`,
which is not in my group.
**Same-as:** 2026-08-11-195801, 2026-08-08-232843 (the quoting half);
2026-08-09-161323 (the empty-pane sentence, guess only).

## 2026-08-08-232843-sb-delegate-opened-a-pane-but-no-agent

**Verdict:** FIXED
**Severity:** high (the report's own account: "a whole implementation task was handed to an
agent that did not exist")
**Evidence:** by reading. Three distinct complaints, all closed:
1. The mangled spawn command / `parse error near ')'` — `1120221`, as above.
2. "A spawn that fails after all retries should mark the row failed, not leave it
   working" — done by `97362b8`; `broker.py:3195-3212` sets `GONE_STATE` and logs
   `spawn_failed` in the `except` around `start_agent`, deliberately leaving a husk rather
   than deleting the row so the attempt survives as a fact.
3. "Anything that spawned in the background and did not read that exit code would never
   learn the agent was not there" — the `spawn_failed` event plus the failed row are now
   in the store, so `sb status` and the board show it without anyone reading an exit code.
The second occurrence in this report used `sb workspace new`, which no longer exists —
deleted in `860b620` (2026-08-11).
**Same-as:** 2026-08-11-195801, 2026-08-09-221323.

## 2026-08-08-031337-every-spawn-silently-drops-all-system

**Verdict:** FIXED
**Severity:** high (every agent ever spawned ran with no protocol and no role prompt)
**Evidence:** by reading. Filed 2026-08-08 03:13:37; `146240a` landed 2026-08-08 03:18:05,
five minutes later, and is this report written up as a commit message — same ALPHA/BRAVO/
CHARLIE verification against the real CLI. The cited defect at `herdr.py:357` (one flag per
fragment) is gone: `herdr.py:514-515` joins every fragment with a space and emits exactly
one flag, now `--append-system-prompt-file`. `tests/test_herdr.py:157` asserts the flag
COUNT is 1 and the joined text is whole and in order — the test note says why asserting
"each fragment appears in argv" was not enough.
**Same-as:** none. Distinct bug from the other three, same function.

---

## What is not proven

No live spawn was run for this group. Every verdict here is code reading plus commit
history plus the unit tests, and the triage rules are right that reading rules a bug *out*
poorly. Specifically:

- I have not watched a real agent spawn at HEAD and come up with its protocol intact. What
  I have is the measurement recorded in `1120221` (8 panes per arm, at the herdr layer)
  and two unit tests that pin the two numbers the fix turns on.
- The reports describe the parse error as **intermittent** — retrying the identical spawn
  succeeded, and role prompts of different lengths behaved differently. That is exactly
  what a length ceiling on a typed line looks like when the line hovers near it, and it is
  consistent with the fix. But intermittency means a single successful live spawn would
  not have proven much either.
- The empty-pane sentence inside `2026-08-09-221323` is a separate mode I did not settle.
