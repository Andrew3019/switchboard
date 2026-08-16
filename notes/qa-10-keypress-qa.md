# QA: AWAITING KEYPRESS (`c1beefc`, `cb951b0`) — independent verification

Brief: `.scout/qa-keypress.md`. Nothing was fixed and nothing was committed, per the brief.
All live work in an isolated `git clone` at
`<scratchpad>/qa10-clone` driving its own `./bin/sb`, plus a throwaway herdr workspace
`w1HX` (label `qa10-keypress`, 8 panes over the run). Everything created was torn down:
`herdr workspace list` no longer lists it, `herdr agent list | grep qa10-` returns nothing.

**Verdict:** the change does what it claims. The before/after holds live, the rule is
correct on real panes, the suite passes, and all three new tests fail without the change.
Two real defects found: a **reproducible false positive on a booting agent whose row has a
session id** (the `sb restore` shape), and a **label that flickers between AWAITING
KEYPRESS and STALLED because of the two-row probe cap**. Plus one gap: `sb status`'s text
NEEDS YOU/DRIFT sections, and the reconciler, were not updated and still tell you to
`sb tell` a pane that cannot read text.

---

## 0. The thing nobody had checked: the `--json` shape

`notes/researcher-62-modal-captures.md` closes with "Whether `herdr agent explain --json`
gives a clean machine-parseable shape for this (`rule`/`fallback_reason` as top-level keys)
— I only saw its `--help` listing `--json` as an option, I did not actually run it." The
implementation reads `matched_rule`, `fallback_reason` and `state`; the text output the
captures record calls the first of those `rule`. If the JSON had followed the text, the
feature would never fire and nothing in the suite would notice (the tests feed hand-written
payloads).

Ran it. It matches:

```
$ herdr agent explain qa10-modal --json     # top level, evaluated_rules elided
{"agent":"claude","fallback_reason":"default_known_agent_idle_fallback",
 "matched_rule":null,"state":"idle","screen_detection_skipped":false, ...}
$ herdr agent explain main-19 --json        # a healthy agent, for contrast
{... "matched_rule":{"id":"live_prompt_box","priority":950,
     "region":"prompt_box_body","state":"idle"}, "fallback_reason":null, ...}
```

`herdr.explain_agent` returns `_call`'s `payload.get("result", payload)`; `explain --json`
emits a bare object with no `result` envelope, so the bare payload comes back and the keys
line up. Verified, not assumed.

## 1. Live BEFORE and AFTER, same panes, same store

Setup, independently reproduced rather than taken from the captures:

- `qa10-modal` — pane with `CLAUDE_CONFIG_DIR` pointed at an empty scratch dir, registered
  with `herdr agent start qa10-modal --kind claude --pane w1HX:p5`. Landed on the first-run
  theme picker. `herdr agent explain qa10-modal` → `rule: none`,
  `fallback_reason: default_known_agent_idle_fallback`, `state: idle`.
- `qa10-control` — negative control, an ordinary `claude` in the clone, sitting at its
  prompt box. `herdr agent explain qa10-control` → `rule: live_prompt_box
  (region=prompt_box_body priority=950)`, `evidence: "❯\u{a0}Try \"fix typecheck errors\"\n"`.
  Same `agent_status: idle` as the modal, which is the whole point.

Store rows for both were authored directly against the clone's store
(`store.create_agent`, then `state='working'`, `turn=NULL`, `created_at` an hour back) — the
provenance of the row is not what is under test, the join of a real herdr reading to a real
`status.collect` is. Rendering driven through the real `status.collect` + `board.marker` +
`richboard.needs_list/needs_kind/needs_reason`.

**BEFORE — clone checked out at `cafc7c8`:**

```
qa10-control   herdr=done     alive=True  stalled=True  | marker: STALLED — idle 1h00
qa10-modal     herdr=idle     alive=True  stalled=True  | marker: STALLED — idle 1h00

# NEEDS YOU
  [idle] qa10-control   STALLED   idle 1h00, nothing running
  [idle] qa10-modal     STALLED   idle 1h00, nothing running
```

**AFTER — same panes, same rows, clone at `cb951b0`:**

```
qa10-control   herdr=done  alive=True  stalled=True  kp=False | marker: STALLED — idle 1h00
qa10-modal     herdr=idle  alive=True  stalled=True  kp=True  | marker: AWAITING KEYPRESS — screen herdr cannot read; press a key in its pane

# NEEDS YOU
  [blocked] qa10-modal     KEYPRESS   press a key in its pane — screen herdr cannot read
  [idle]    qa10-control   STALLED    idle 1h00, nothing running
```

The negative control reads STALLED on both sides, which is the requirement. Both halves
obtained; nothing here is inferred.

The real CLI agrees — `./bin/sb status` in the clone prints `<< AWAITING KEYPRESS` in the
flags column for `qa10-modal` and `<< STALLED` for `qa10-control`.

## 2. FINDING (blocker-ish): a false positive on a booting agent with a session id

The implementer's claim — that the startup excuse blocks a freshly *delegated* agent — is
true, and I confirmed it live. What it does not block is a row that already has a session
id, which is exactly what `sb restore` leaves behind.

`Broker.restore` (switchboard/broker.py, the `UPDATE agents SET ended_at=NULL,
state='working', turn=NULL WHERE name=?` at the end of the method) keeps `session_id` — it
*requires* one, it refuses to restore without — and clears `turn` to NULL. In
`status.collect`, `starting` is `row["session_id"] is None and ...`, so the startup grace
does not apply; `awaiting_task` is not set by restore either. The row is therefore
`stalled=True` on the first tick herdr calls the pane idle — while the resumed Claude is
still drawing its splash screen and herdr's manifest matches nothing.

Reproduced live, twice, with a real `herdr agent start` booting a real Claude in a fresh
pane under a row of exactly that shape (session id present, `turn=NULL`, `state='working'`,
created an hour ago), polled every 0.25 s:

```
 0.00s herdr=unknown  excuse=None  stalled=False kp=False |
 0.25s herdr=idle     excuse=None  stalled=True  kp=True  | AWAITING KEYPRESS — screen herdr cannot read; press a key in its pane
 0.50s herdr=idle     excuse=None  stalled=True  kp=True  | AWAITING KEYPRESS — ...
 0.75s herdr=idle     excuse=None  stalled=True  kp=True  | AWAITING KEYPRESS — ...
 1.00s herdr=idle     excuse=None  stalled=True  kp=True  | AWAITING KEYPRESS — ...
 1.25s herdr=idle     excuse=None  stalled=True  kp=True  | AWAITING KEYPRESS — ...
 1.50s herdr=idle     excuse=None  stalled=True  kp=False | STALLED — idle 1h00
```

A ~1.25 s window of a healthy agent telling the human to go press a key in its pane, and
of the row jumping into NEEDS YOU's `blocked` bucket. At `main`'s new 0.5 s board refresh
that is two to three consecutive frames.

**What I proved and what I did not.** I proved the *store shape* produces the false
positive, against a real booting Claude and a real herdr. I did not run an actual
`sb restore` end to end — the row was authored to match `restore`'s own final UPDATE. If
someone wants that closed, one real `sb restore` of a closed agent, watched at 0.25 s, does
it.

**The brief's case, for contrast — no false positive.** A freshly delegated row
(`session_id` NULL, `created_at` now) under the same real booting Claude:

```
 0.25s herdr=idle  excuse=starting up  stalled=False kp=False |
 ... unchanged for the whole boot ...
```

`starting up` holds it out of `stalled`, so the probe is never asked. The gate works exactly
as the commit message says it does — for the spawn path.

## 3. FINDING: the label flickers, and the cause is the probe cap

Watched a parked modal over 20 consecutive `collect`s at 2 s intervals with the fleet
otherwise quiet: **rock solid**, `awaiting_keypress=True` on all 20, controls `False` on all
20. The probe itself does not flicker.

The cap does. `KEYPRESS_PROBE_MAX = 2` takes the first two stalled rows *in tree order*, so
which rows get an opinion depends on how many other agents happen to be stalled and what
they are called. With four stalled rows and the two `qa10-control*` names sorting ahead
alphabetically, **both modals read plain STALLED** — the feature silently did not fire at
all on the run where it was most needed.

Demonstrated as a live flip, toggling only an unrelated agent's state between ticks. The
modal pane and its row never changed:

```
tick 0: stalled rows=4  qa10-modal marker: STALLED — idle 1h02
tick 1: stalled rows=3  qa10-modal marker: AWAITING KEYPRESS — screen herdr cannot read; press a key in its pane
tick 2: stalled rows=4  qa10-modal marker: STALLED — idle 1h02
tick 3: stalled rows=3  qa10-modal marker: AWAITING KEYPRESS — ...
tick 4: stalled rows=4  qa10-modal marker: STALLED — idle 1h02
tick 5: stalled rows=3  qa10-modal marker: AWAITING KEYPRESS — ...
```

The row also moves between NEEDS YOU's `blocked` and `idle` kinds as it flips, so the
section re-sorts too. Answering the brief directly: yes, it flickers in practice, and yes, a
stalled row flips back and forth — but the cause is not "nothing remembers a previous
probe", it is "which rows get probed is a function of who else is stalled".

**The cost measurement behind the cap does not reproduce.** `cb951b0` justifies dropping the
cap from 4 to 2 with "~120 ms per call on this machine, five times the whole tick". Measured
here, 10 calls each, machine carrying 21 live herdr agents:

```
agent explain  median 7.5 ms  (min 6.2, max 13.7)
agent list     median 6.7 ms  (min 6.4, max 10.3)
```

`explain` costs about what `agent list` costs — roughly a sixteenth of the figure the commit
message cites. I cannot say what the implementer measured; I can say the cap of 2 is buying
very little and costing the correctness above.

## 4. Probe cap degrades quietly — yes

Three stalled rows, the modal third in tree order: no error, no traceback, the third row
reads today's plain `STALLED — idle 1h01`, `collect` returned in 39 ms.

```
qa10-control   stalled=True  kp=False | STALLED — idle 1h01
qa10-modal     stalled=True  kp=True  | AWAITING KEYPRESS — screen herdr cannot read; press a key in its pane
qa10-modal2    stalled=True  kp=False | STALLED — idle 1h01
```

Confirmed as designed. Note this is the same mechanism as finding 3 — quiet degradation and
silent flicker are the same behaviour seen from two angles.

## 5. GAP: only one of switchboard's four surfaces learned the new state

`sb status` — the text view, which is what an agent gets and what a human gets without the
rich panel — was not updated. Live, with the modal parked:

```
qa10-modal     worker  idle      idle        -    1h09    1h09  qa10   << AWAITING KEYPRESS    ← updated

NEEDS YOU
  qa10-modal    stalled 1h10 — its turn ended without sb done  →  sb tell qa10-modal "wrap up and run sb done"     ← NOT updated

DRIFT
  qa10-modal    STALLED  herdr says idle — turn ended, `sb done` never called, quiet 1h10                          ← NOT updated
                →  sb inspect <name>, then: sb tell <name> "wrap up and run sb done"
```

`status._flags` grew the branch; `status.py`'s own NEEDS YOU and DRIFT renderers (the
`elif a.stalled:` arms around switchboard/status.py:2107 and :2175) did not. `richboard`'s
NEEDS YOU did. So two of the three text sections recommend `sb tell` — the one action the
commit message says the dialog swallows.

**And the reconciler acts on it.** `Broker.reconcile` pings every `stalled` row and has no
`awaiting_keypress` exemption. Live:

```
$ ./bin/sb reconcile
pinged qa10-control, qa10-modal
$ herdr pane read w1HX:p5     # the modal pane, immediately after
   ... still the theme picker, byte for byte unchanged ...
```

Switchboard identified the pane as one that cannot read text, then sent it text. This is
pre-existing behaviour and not a regression — but the change makes it visible, and it is the
obvious next thing.

## 6. Suite

`/Users/andrew/anaconda3/bin/python -m pytest tests` in the clone at `cb951b0`:
**1284 passed in 86.91s**. No failures, no skips reported.

Do the three new tests fail without the change? Yes, all three, checked by reverting the
logic in the clone (and reverting the revert afterwards — `git status` clean but for my
untracked scratch scripts):

- Made `status.awaiting_keypress_screen` return `False` unconditionally →
  `test_only_an_unmatched_screen_counts_and_anything_unreadable_is_no_opinion` and
  `test_only_already_stalled_rows_cost_a_subprocess` both FAIL (2 failed, 189 passed).
- Removed the `if a.awaiting_keypress:` arm from `board.marker` →
  `test_a_pane_herdr_cannot_read_asks_for_a_keypress_instead_of_reporting_a_stall` FAILS
  (`'AWAITING KEYPRESS' not found in '... STALLED — idle 5s ...'`).

Worth naming: the two `status` tests feed hand-written payload dicts, so neither can catch a
herdr that renames `matched_rule`. That is the risk section 0 covers by hand, and it stays
uncovered by the suite.

## 7. What I did not test

- **The trust-folder and auto-mode dialogs** — same credential wall `researcher-62` hit. The
  only modal family proven end to end is first-run onboarding (theme picker). Still open.
- **`screen_detection_skipped` / `skipped_update_reason`.** herdr's `explain --json` carries
  both. If herdr ever skips screen detection and reports `matched_rule: null` with the same
  `fallback_reason`, this rule fires on a pane herdr never looked at. I could not force that
  state and did not enumerate herdr's `fallback_reason` values.
- **Non-modal unfamiliar screens** — a foreign REPL, a crashed TUI, a different Claude Code
  version. `researcher-62` left this open and I did not close it.
- **A real `sb restore`**, per section 2.
- **Long-horizon flicker.** Longest continuous watch was 20 ticks / 40 s (house rules: no
  endurance testing).

## Reproduction index

Scratch scripts (in the clone, deleted with it): `qa10_seed.py` (store rows),
`qa10_render.py` (collect + marker + NEEDS YOU, version-agnostic so it runs at both
commits), `qa10_boot.py` (section 2, session-id row), `qa10_spawn.py` (section 2, NULL
session-id row).
