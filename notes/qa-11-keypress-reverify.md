# QA re-verify: AWAITING KEYPRESS at `83773a4` — final gate before merge

Brief: `.scout/qa-reverify.md`. Nothing fixed, nothing committed, nothing pushed.

All live work in an isolated `git clone` at `<scratchpad>/qa11-clone` driving its own
`./bin/sb`, plus a throwaway herdr workspace `w1J5` (label `qa11-keypress`, 4 panes over
the run). Everything created was torn down — see §8.

**Verdict: safe to merge.** Both defects `qa-10` found are gone, proved live on the head
that would merge. The before/after holds on real panes, `sb status`'s NEEDS YOU and DRIFT
now name the state, and the suite is green at 1296.

Two things the brief asked me to confirm did **not** come out as the branch describes them,
neither of them a blocker:

- **Neither of the two new tests fails against the pre-fix code** (§5). Both pass at
  `577b14d`, the commit immediately before. They pin the behaviour; they did not catch it.
- **The claimed residual is wider than "~1 s"** (§4). Measured live: the false-positive
  *screen* window is ~3 s, and the 30 s answer cache holds a single unlucky reading on the
  board for a full **30 s** — I watched a healthy booting agent read AWAITING KEYPRESS for
  30 s straight. The shape is still not reachable via `sb restore` or `sb delegate`, which
  is what makes it a nit rather than a blocker.

---

## 1. Live BEFORE and AFTER, on the current head

Two real panes in `w1J5`, both registered with `herdr agent start ... --kind claude`:

- `qa11-modal` — pane started under a fresh empty `CLAUDE_CONFIG_DIR`, landing on the
  first-run theme picker (pane text read back verbatim: "Let's get started. / Choose the
  text style that looks best with your terminal"). `herdr agent explain --json`:
  `matched_rule: null`, `fallback_reason: default_known_agent_idle_fallback`,
  `state: idle`.
- `qa11-control` — negative control, an ordinary `claude` in the clone at its prompt box,
  turn ended, no `sb done`. `explain` → `matched_rule.id: live_prompt_box` (priority 950,
  region `prompt_box_body`), `fallback_reason: null`.

Store rows authored against the clone's store (`state='working'`, `turn=NULL`,
`created_at` an hour back, `session_id` NULL and so past the startup grace). Rendering
driven through the real `status.collect` + `board.marker` + `richboard`
(`qa11_render.py`).

**BEFORE — clone at `5890c76`, the branch's parent (I also ran the clone's stale local
`main`, `cafc7c8`: identical output):**

```
qa11-control   herdr=done     alive=True  stalled=True  kp=n/a   | marker: STALLED — idle 1h00
qa11-modal     herdr=idle     alive=True  stalled=True  kp=n/a   | marker: STALLED — idle 1h00

# NEEDS YOU
  [idle] qa11-control   STALLED    idle 1h00, nothing running
  [idle] qa11-modal     STALLED    idle 1h00, nothing running
```

**AFTER — same panes, same rows, clone at `83773a4`:**

```
qa11-control   herdr=done     alive=True  stalled=True  kp=False | marker: STALLED — idle 1h00
qa11-modal     herdr=idle     alive=True  stalled=True  kp=True  | marker: AWAITING KEYPRESS — screen herdr cannot read; press a key in its pane

# NEEDS YOU
  [blocked] qa11-modal     KEYPRESS   press a key in its pane — screen herdr cannot read
  [idle]    qa11-control   STALLED    idle 1h00, nothing running
```

Requirement met in both directions: the modal changes, the real prompt-box agent does not.

**A modal herdr *does* recognise, unplanned and worth recording.** Before I accepted the
trust prompt for `qa11-control`, its pane sat on Claude Code's "Is this a project you
created or one you trust?" dialog. `explain` matched `live_blocked_form` (priority 980,
state `blocked`) — so `awaiting_keypress_screen` returns False for it and the row would
read as blocked, not as AWAITING KEYPRESS. That is the trust dialog `researcher-62` and
`qa-10` both left untested, and it lands on the correct side of the rule.

## 2. `qa-10` repro A — the restored-agent false positive: FIXED

Run as a **real `sb restore`**, not a hand-authored row, which is what `qa-10` could not
close. Setup: gave `qa11-control` a genuine session id
(`18a6e693-781c-4198-bc2e-65e570d1c20a`, from `~/.claude/projects/...` after making it take
a real turn), closed its pane, set `ended_at`. Then `./bin/sb restore qa11-control` with a
`collect()` poll running at 0.25 s in a separate long-lived process (`qa11_poll.py`).

`sb restore` printed `restored qa11-control`. 45 s of polling, **`kp=False` on every single
tick**, no AWAITING KEYPRESS at any point:

```
 0.84s herdr=unknown  excuse=None  idle=0     stalled=False kp=False |
 1.11s herdr=idle     excuse=None  idle=0     stalled=False kp=False |
 3.86s herdr=idle     excuse=None  idle=0     stalled=True  kp=False | STALLED — idle 0s
...
44.93s herdr=idle     excuse=None  idle=41    stalled=True  kp=False | STALLED — idle 41s
```

The last lines matter: past 30 s the row IS asked about, and the answer is False — herdr
reads the resumed agent as `live_prompt_box`. So the row is probed and correctly declines,
it is not merely never looked at.

**The gate is load-bearing, and I proved the signal underneath it still lies.** I repeated
the restore polling `herdr agent explain` directly at 0.2 s (no store in the way). A real
restore spends ~2.9 s in exactly the AWAITING KEYPRESS shape while Claude draws its splash:

```
48.06 no agent
48.31 matched= None  fallback= default_known_agent_idle_fallback  state= idle
48.82 matched= None  fallback= default_known_agent_idle_fallback  state= idle
50.59 matched= None  fallback= default_known_agent_idle_fallback  state= idle
51.19 matched= osc_title_idle    fallback= None  state= idle
51.81 matched= live_prompt_box   fallback= None  state= idle
```

What stops the label is `restore`'s own `log_event(kind="restore")` — `restore` is not in
`DONE_TO_THE_AGENT`, so it resets the row's idle clock to 0 (visible as `idle=0` above),
and `_mark_awaiting_keypress`'s `x.idle >= NEEDS_SETTLE` (30 s) refuses to ask for the
whole 30 s. The 3 s window sits comfortably inside that. Robust, but it is one gate, not
two: the commit message's "belt and braces" second half (the summons restarting) governs
what the *board draws*, not what `sb status` prints.

## 3. `qa-10` repro B — the flicker: FIXED

`qa-10`'s shape, toggling how many *other* rows are stalled between ticks, half a second
apart (the current board interval). The modal row and its answer are real throughout — a
real pane and a real `herdr agent explain`; the noise rows are synthetic `AgentStatus`
copies whose only job is to compete for the probe budget, and they are named to sort
*ahead* of `qa11-modal`, the worst case. `qa11_flicker.py`.

**Pre-fix `6b4330c`, noise toggling 1/8:** the label flips every tick, driven entirely by
another agent's state.

```
tick 0: stalled rows=2  qa11-modal kp=True  kind=blocked  marker: AWAITING KEYPRESS — ...
tick 1: stalled rows=9  qa11-modal kp=False kind=idle     marker: STALLED — idle 1h06
tick 2: stalled rows=2  qa11-modal kp=True  kind=blocked  marker: AWAITING KEYPRESS — ...
tick 3: stalled rows=9  qa11-modal kp=False kind=idle     marker: STALLED — idle 1h06
tick 4: stalled rows=2  qa11-modal kp=True  kind=blocked  marker: AWAITING KEYPRESS — ...
tick 5: stalled rows=9  qa11-modal kp=False kind=idle     marker: STALLED — idle 1h06
```

**At `83773a4`, same script, same panes:** `True` on all six ticks, `kind=blocked`
throughout. The brief's exact 2-8-3-8-2-8 shape also holds `True` on all six.

```
tick 0: stalled rows=2  kp=True | tick 1: rows=9  kp=True | tick 2: rows=2  kp=True
tick 3: stalled rows=9  kp=True | tick 4: rows=2  kp=True | tick 5: rows=9  kp=True
```

I also ran 2-8-3-8-2-8 at `6b4330c`: there the modal reads plain STALLED on **all six**
ticks — `qa-10`'s other half ("with four stalled rows both modals silently read STALLED")
reproduces too. The repro discriminates; the fix closes it.

## 4. The claimed residual — real, and wider than claimed

The branch says: "a one-shot `sb status` fired inside a ~1 s window on a row with a session
id and an old idle clock would print the state." Two corrections, both measured.

**(a) The window is the boot's unmatched window (~3 s), not ~1 s** — §2's explain trace.

**(b) The 30 s answer cache turns one unlucky probe into 30 s of wrong label.** Seeded a
row (`qa11-boot`) with an hour-old idle clock and no restore event — i.e. exactly the shape
the branch says is unreachable — then started a real Claude in its pane with a `collect()`
poll running at 0.25 s in one long-lived process, as the collector is:

```
 1.39s herdr=idle  idle=3602  stalled=True kp=True  | AWAITING KEYPRESS — screen herdr cannot read; press a key in its pane
 ... 116 consecutive ticks, unbroken ...
30.83s herdr=idle  idle=3631  stalled=True kp=True  | AWAITING KEYPRESS — ...
31.10s herdr=idle  idle=3632  stalled=True kp=False | STALLED — idle 1h00
```

**29.7 s of a healthy agent sitting at its prompt box telling the human to go press a key**,
and 29.7 s in NEEDS YOU's `blocked` bucket. `herdr agent explain` on that pane at the end
says `live_prompt_box` — the pane was fine for most of that window; the cache was not.
`_KEYPRESS_SEEN` is symmetric, so it holds a wrong `True` exactly as long as it holds a
right one.

**Why this is a nit and not a blocker.** Reaching it needs a row that is stalled with an
idle clock older than 30 s *and* a pane that is booting an agent. Neither switchboard path
produces that: `sb restore` resets the clock (§2, proved), `sb delegate` is excused by the
session-id grace (`qa-10` proved, and the settle gate now covers it as well). What is left
is a human relaunching an agent by hand in a stalled agent's pane. Wrong for half a minute,
recovers by itself, and the advice it gives ("go and look at the pane") is not dangerous.

**Does anything on the board itself show it?** No. Nothing in the live fleet drives a row
into that shape, and the transitions that could all restart the summons debounce. I did not
find a switchboard command that produces it.

**One more cap residual, on `sb status` specifically.** `KEYPRESS_PROBE_MAX = 8` still
decides a first opinion, and a one-shot process has no second tick to rotate into. Cold
process, modal sorting last:

```
8 candidates  →  kp=True   AWAITING KEYPRESS
9 candidates  →  kp=False  STALLED — idle 1h07
13 candidates →  kp=False  STALLED — idle 1h07
```

So with 9+ agents stalled past the settle window at once, `sb status` (not the board — the
collector rotates) can silently print STALLED for a parked modal. Fails to the old row,
which is the required direction. Nit.

## 5. The two new tests do not fail against the pre-fix code

The brief asked me to confirm they do. They do not.

```
$ git checkout 577b14d -- switchboard/status.py     # the commit immediately before
$ pytest tests/test_status.py -k "booting_agent or no_row_s_label"
2 passed, 141 deselected in 0.10s
```

Why, read off the code rather than guessed:

- `test_a_booting_agent_is_not_asked_about_however_its_row_got_there` turns on
  `idle >= NEEDS_SETTLE`, and that gate was added in `577b14d`, not in `83773a4` — the
  commit message says so itself ("the settle gate added in the previous commit").
- `test_no_row_s_label_depends_on_who_else_is_stalled` ticks one second apart, so every
  tick after the first is answered from `_KEYPRESS_SEEN` inside `KEYPRESS_PROBE_GAP` — the
  gap check runs before the cap check at `577b14d` too. The cap-ordering fix the test is
  named for is never exercised. Ticking outside the gap, or clearing the cache between
  ticks, is what would make it bite.

Against `6b4330c` and `1d5594c` all five `AwaitingKeypressTest` tests fail, but those revs
lack `KEYPRESS_PROBE_GAP`/`_KEYPRESS_SEEN` entirely, so that is a collection error rather
than the tests catching the defect.

The fixes themselves are real and proved live (§2, §3). This is a note about test value,
not about the change.

## 6. `sb status` NEEDS YOU and DRIFT — updated, verbatim

`./bin/sb status` in the clone at `83773a4`, modal parked:

```
qa11-control  worker  idle      done        -    1h00    1h00  qa11       << STALLED
qa11-modal    worker  idle      idle        -    1h00    1h00  qa11       << AWAITING KEYPRESS

NEEDS YOU
  qa11-control  stalled 1h00 — its turn ended without sb done  →  sb tell qa11-control "wrap up and run sb done"
  qa11-modal    idle 1h00 on a screen herdr cannot read  →  press a key in its pane: sb inspect qa11-modal

DRIFT — ...
  qa11-control  STALLED  herdr says done — turn ended, `sb done` never called, quiet 1h00
  qa11-modal    AWAITING KEYPRESS  herdr's classifier recognises nothing on that screen — text sent to it goes into whatever is drawn over it, quiet 1h00
                →  sb inspect <name>, then: sb tell <name> "wrap up and run sb done"
                →  except an AWAITING KEYPRESS one: go to its pane and press a key, a tell cannot reach it
```

Both sections name the state and send the human to the keyboard. `qa-10`'s §5 gap is
closed for these two surfaces.

**Wording nit.** DRIFT's generic `→ sb inspect <name>, then: sb tell <name> ...` still
prints *above* the exception line, so a skimmer meets the wrong advice first. Reversing the
two lines, or putting the exception inline on the row, would fix it.

## 7. The reconciler still types into the pane — `qa-10`'s §5, unfixed

Not in the brief's list, pre-existing, and not a regression — but it got worse-looking
under test, so it is worth recording precisely.

```
$ ./bin/sb reconcile          # via Broker.reconcile
['qa11-control', 'qa11-modal', 'qa11-boot']
```

`qa11-modal` was on the theme picker before. Immediately after, its pane was on the
**login-method picker** — the ping's keystrokes were swallowed by the dialog and advanced
it. So switchboard classifies a pane as one that cannot read text, then sends it text, and
the text changes what is on screen. `Broker.reconcile` pings every `stalled` row and has no
`awaiting_keypress` exemption.

## 8. Suite, and teardown

`/Users/andrew/anaconda3/bin/python -m pytest tests` in the clone at a clean `83773a4`:
**1296 passed in 101.27s**. No failures, no skips reported.

Teardown: herdr agents `qa11-modal`, `qa11-control`, `qa11-boot` and every pane of
workspace `w1J5` closed, workspace removed. No `pkill` of any kind was run. The clone is a
scratch directory and its store never touched the live fleet's.

## 9. What I did NOT test

- **The auto-mode dialog.** Same credential wall `researcher-62` and `qa-10` hit. Of the
  modal family, first-run onboarding (theme picker, login picker) is proven, and the trust
  dialog is now proven to be *recognised* by herdr (§1) — the auto-mode one is still open.
- **Non-modal unfamiliar screens** — a foreign REPL, a crashed TUI, an older Claude Code.
  Open, as it was.
- **`screen_detection_skipped` / `skipped_update_reason`.** Both were `false`/`null` on
  every payload I saw; I did not force herdr into a state that sets them, so the risk that
  a skipped detection reads as an unmatched screen is still uncovered.
- **A fleet with 9+ genuinely stalled real agents.** §4's cap result uses synthetic
  competitor rows against a real probe; I did not stand up nine real Claudes.
- **Long-horizon behaviour.** Longest continuous watch was 60 s (house rules: no endurance
  testing).
- **The `--json` snapshot contract** beyond reading that `awaiting_keypress` is in
  `AgentStatus`'s export tuple. `qa-10` verified the herdr `--json` key names; I
  re-confirmed them live on my own captures (§1) but did not re-audit switchboard's own
  `--json`.

## Reproduction index

Scratch scripts, in the clone and deleted with it: `qa11_seed.py` (store rows),
`qa11_render.py` (collect + marker + NEEDS YOU, runs at any commit), `qa11_poll.py`
(0.25 s `collect` poll, §2 and §4), `qa11_flicker.py` / `qa11_flicker_compat.py` (§3),
`qa11_cold.py` (§4's cap result). Poll logs: `/tmp/qa11_restore_poll.txt`,
`/tmp/qa11_explain_poll.txt`, `/tmp/qa11_boot_poll.txt`.
