# Phase 4 scope — removals

Read-only audit. Base: `main` tip `5998a43` (phases 1-2 merged, phase 3's scoping doc
merged, phase 3's build itself still in flight on unmerged branches). Modelled on
`audit/phase3-scope.md`. Covers BUILD-PLAN.md's phase 4 bullets, turned into pass/fail
tests against the code as it reads today on `main`.

Ground truth taken as given, not re-derived: `DESIGN-TRUTH.md:305-327` ("Explicitly
rejected") is the authority for *why* each item goes; this document only establishes
*whether it is gone yet* and *what removing it touches*.

**Headline finding, stated up front because it changes how this phase should be read.**
Unlike phase 3's scoping pass — which found four items already fixed on `main` — every
item DESIGN-TRUTH.md's "Explicitly rejected" section names is **still fully live** in the
code as of this commit. `DESIGN-TRUTH.md` was last touched 2026-08-09 (`git log -1 --
DESIGN-TRUTH.md`); it records a *decision*, not a build. Phase 4 is real, ground-up removal
work on every bullet in the brief. The one thing that *is* already partly done is the role
layer: all five shipped role `.md` files have already dropped a per-role `keep`/`ephemeral`
**field**, with prose explaining why (see 4.2 below) — but those same five files still
actively *teach* agents to reach for the `--keep`/`--ephemeral` **flags** this phase
removes, so the prompt-text work is not shortened, only reshaped.

---

## 4.1 — `--keep`, `--ephemeral`, `--include-kept`, `--leave-children`, `--no-board`,
focus as a flag: all still live CLI options

**What happens today.** Every one of these still parses.

| flag | command | parser | usage |
|---|---|---|---|
| `--keep` | `sb delegate` | `cli.py:143` | `cli.py:747` → `cleanup="keep"` |
| `--ephemeral` | `sb delegate` | `cli.py:144` | `cli.py:747` → `cleanup="close"` (see note below) |
| `--include-kept` (alias `--all-idle`) | `sb cleanup` | `cli.py:245-248` | `cli.py:949` → `Broker.cleanup(include_kept=...)`; gate at `broker.py:3631-3632` |
| `--leave-children` | `sb cleanup` | `cli.py:255-257` | `cli.py:950` → `Broker.cleanup(leave_children=...)`; gate at `broker.py:3553`, refusal text `broker.py:3562` |
| `--no-board` | `sb start` **and** `sb workspace new` | `cli.py:113-114`, `cli.py:273-274` | `cli.py:737`/`991` → `board=args.board` |
| focus as a flag | `sb start` (`--no-focus`) **and** `sb workspace new` (`--focus`) | `cli.py:112`, `cli.py:272` | `cli.py:737`/`991` → `focus=args.focus` |

**Correction to the brief's framing: `--ephemeral` is not a third persisted state.**
`cli.py:747` — `cleanup = "keep" if args.keep else ("close" if args.ephemeral else None)`
— maps `--ephemeral` onto the exact same `cleanup="close"` value the column already
defaults to (`store.py:165`, `defaults/settings.toml:115`). `--ephemeral` is a no-op
today except as documentation of intent; passing neither flag produces the identical
stored value. Worth Andrew knowing before removal is scoped as "delete two flags that map
to two states" — it is two flags mapping to one state plus its own default.

**Correction to the brief's framing: "focus as a flag" is two separate CLI surfaces, not
one.** `sb start --no-focus` (default on, flag turns it off) and `sb workspace new
--focus` (default off, flag turns it on) are different parsers, different defaults, and
different call sites. `sb delegate` has no focus flag at all — nothing else can ask for
focus, matching DESIGN-TRUTH's "nothing can ask for it" for every command except these
two. Both need removing to satisfy DESIGN-TRUTH's "**Only** `sb start` focuses on
spawn" — read literally, `sb start` should focus *unconditionally*, with no flag at all,
not merely be the sole command with a flag.

**Pass condition, per sub-item:**
- `sb delegate --keep` / `--ephemeral` no longer parse (fail = they do; `argparse` raises
  today for unknown flags, so "no longer parses" is a literal, testable claim).
- `sb cleanup --include-kept` / `--all-idle` / `--leave-children` no longer parse.
- `sb start --no-focus` no longer parses; `sb start` always focuses (no branch left in
  `Broker._top`/`broker.py:796,824` — both currently call `self._focus(name, focus)`
  with `focus` threaded from the CLI).
- `sb workspace new --focus` no longer parses; `Broker.workspace_new`'s `focus` parameter
  (`broker.py:1046-1055`, default `False`) either goes with the whole command in phase 5
  or, if `sb workspace new` outlives phase 4 (see 4.5 below), is pinned to `False` with no
  way to override it in the interim.
- `--no-board` no longer parses on either command; `board` becomes unconditionally `True`
  (`Broker._top`/`workspace_new`'s `board: bool = True` default stays, the CLI-side
  override is deleted).

**What removal touches.** `cli.py` parser blocks at the six line ranges above, plus their
dispatch reads (`cli.py:737,747,949-950,991`); `broker.py` signatures that currently
accept these as parameters (`cleanup` throughout the delegate path — see 4.2 for the
fuller chain; `Broker.cleanup`'s `include_kept`/`leave_children` params, `broker.py:3484-
3486`; `Broker._top`'s and `workspace_new`'s `focus`/`board` params, `broker.py:744-745,
1046-1055`).

---

## 4.2 — `keep`/`ephemeral` as persisted state: store column, settings default, role
field, five shipped role prompts

**Correction to the brief's framing: there is one store column, not two.**
`store.py:165` — `cleanup TEXT NOT NULL DEFAULT 'close'` inside `CREATE TABLE agents`
(`store.py:140-186`) — is the only persisted state. It holds exactly two string values in
practice, `'keep'` and `'close'` (grep of `broker.py` for `cleanup=` finds only these two
literals plus the pass-through `cleanup or r.cleanup` at `broker.py:3029`). There is no
`ephemeral` value ever written.

**Settings default.** `defaults/settings.toml:111-115`:
```
# What a role file gets for a field it does not set. Every shipped role sets both, so these
# only ever apply to a role somebody wrote in three lines — which is exactly the case that
# should not have to know what a tier is called.
default_tier    = "default"
default_cleanup = "close"
```
Read at `roles.py:51` — `self.cleanup = self.cleanup or config.setting
("vocabulary.default_cleanup")`. The comment above it is already stale: it says "every
shipped role sets both," but as of the role-file changes described below, **no shipped
role sets `cleanup` any more** — every one of the five now falls through to this default
unconditionally. Worth fixing the comment as part of this item, not a separate pass.

**Role field.** `roles.py:40` — `Role` dataclass still carries `cleanup: str = ""` as a
first-class field, populated by `__post_init__` (`roles.py:51`) from the settings default
when a role file doesn't set it. This is the mechanism, not the data: the *field* still
exists in code (`Role.cleanup`), it is simply unpopulated by any shipped file. Whether
this field should be deleted outright (collapsing `cleanup` to always `"close"`,
consistent with DESIGN-TRUTH's "cleanup is the orchestrator's, and it always takes the
children") or left as dead-but-harmless infrastructure for a `.switchboard/roles.toml`
override some repo might still want is a decision item — see below.

**Already true, contrary to the brief's plain reading — worth stating plainly.** "A field
on every role" is **not** true today. All five shipped role files carry the same
statement, in nearly the same words:

- `defaults/roles/orchestrator.md:15` — "No `cleanup` field, here or in any role. It used
  to say `keep`, on the reasoning that closing an agent someone is talking to is never
  what anyone wanted however idle it looks — which is true, and still not a property of a
  KIND of agent."
- `defaults/roles/qa.md:35`, `defaults/roles/reviewer.md:18`,
  `defaults/roles/researcher.md:25`, `defaults/roles/worker.md:44` — same claim,
  "No `cleanup` field, here or in any [other] role."

So the *field-on-a-role* half of the brief's claim is already closed, and has been for
some prior commit on `main` — this document does not re-list it as work. But it does not
follow that the prompt work is done:

**Still true, and this is the actual remaining prompt work.** All five files, in the very
same paragraph that disclaims a `cleanup` field, tell the agent to reach for the CLI
flags instead:

- `defaults/roles/orchestrator.md:20` — "It is a run-time call — `sb delegate --keep` /
  `--ephemeral` per spawn, and the sweep below"
- `defaults/roles/qa.md:36` — "(`sb delegate --keep` / `--ephemeral`, and the
  orchestrator's own sweep), not a property of..."
- `defaults/roles/researcher.md:26` — "`sb delegate --keep` / `--ephemeral`, and the
  orchestrator deciding what survives its sweep"
- `defaults/roles/reviewer.md:19` — "(`sb delegate --keep` / `--ephemeral`, and the
  orchestrator's own sweep), not a property of..."
- `defaults/roles/worker.md:45` — "`sb delegate --keep` / `--ephemeral` and swept by an
  orchestrator, never a property of a..."

**Pass condition.** `store.py:165`'s `cleanup` column either stops existing or stops ever
being written `'keep'` (a migration question, see below — a column with only one live
value is a smaller problem than a live `'keep'` row with nothing left to interpret it).
`defaults/settings.toml`'s `default_cleanup` key and `roles.py`'s `Role.cleanup` field are
removed or pinned to the single surviving behavior. Grep of `defaults/roles/*.md` for
`--keep` and `--ephemeral` returns zero hits, and each of the five paragraphs above is
rewritten to describe the DESIGN-TRUTH replacement — "cleanup is the orchestrator's, and
it always takes the children" — rather than a flag that no longer exists.

**What removal touches.** `store.py:140-186` (schema), `defaults/settings.toml:111-115`
(default + its now-doubly-stale comment), `roles.py:40,51` (`Role.cleanup` field and its
fallback), `broker.py:813,2423,2476,3029,3484-3486,3553,3562,3631-3632` (every site that
reads, writes, or gates on `cleanup`/`include_kept`/`leave_children`), and all five
`defaults/roles/*.md` files at the line numbers above.

**Decision needed.** Does "cleanup is the orchestrator's, and it always takes the
children" mean the `cleanup` column collapses to a constant (delete the column, delete
`Role.cleanup`, delete `default_cleanup`, `sb cleanup` always takes finished agents with
no keepers gate at all) — or does keeping some agents around stay possible, just no
longer as a *spawn-time* flag (an orchestrator simply never runs `sb cleanup <name>` on an
agent it wants to keep talking to, and the column/gate logic stays to support `--force`
overriding a *different* fact)? The five role files, in the paragraph already quoted
above, read as anticipating the second interpretation — "What stays open depends on what
is happening in the room... It is a run-time call" (`orchestrator.md:16-20`) describes an
orchestrator's *judgment* about calling `cleanup` at all, not a stored disposition. If
that is the intended shape, `include_kept`'s refusal gate (`broker.py:3631-3632`,
"role %s is kept, not closed") has nothing left to refuse once no row is ever
`'keep'` — which argues for deleting the column entirely and simplifying `Broker.cleanup`
to drop that gate, not just deleting the CLI flags that used to set it. Recommend the full
collapse (delete column, field, setting, gate) — it is the reading DESIGN-TRUTH's own
wording supports most directly, and it removes a live migration hazard (below) rather
than leaving a column nothing can set to anything but its own default.

**Migration — what happens to rows already carrying `cleanup='keep'`.** This is real, not
hypothetical: `broker.py:813` and `:2423` both write `cleanup="keep"` for the human's own
top-level agent and for a restored workspace lead respectively, so any live store has
`'keep'` rows today, not just ones a user opted into via `--delegate --keep`. If the
column is deleted outright, every existing row needs either a schema migration that drops
the column (matching `store.py`'s existing migration machinery — see `store._reconcile`
mentioned in phase 3's notes, `store.py:267-743`) or, if the column stays but the
`'keep'` value stops being writable, those rows are frozen at `'keep'` forever with no
code path left to change or interpret them — `sb cleanup`'s gate at `broker.py:3631-3632`
would keep refusing to close them (harmless, since that gate's *reason string* still
matches) or, if the gate itself is deleted alongside the flags, silently start closing
agents that were explicitly marked to survive a sweep, which is the actual hazard: an
orchestrator's own live pane (`broker.py:813`'s `cleanup="keep"` write is exactly the
human's own top-level agent) could be swept the next time `sb cleanup` runs, with no flag
left to have prevented it. **Recommend:** land the column-collapse and the flag removal in
the same commit, with a migration that reads existing `'keep'` rows and does *not* auto-
close them on the first `sb cleanup` after the change — either a one-time grandfather pass
that leaves currently-keep agents alone until they're named explicitly, or (simpler)
treat the removal as "no code writes `'keep'` any more" without deleting the column or its
read-side gate at all, so old rows keep behaving exactly as before and only new spawns are
affected. The second option is less pure but has no migration hazard at all — it only
requires deleting the *write* paths (CLI flags, `broker.py:813,2423,2476`'s explicit
`cleanup="keep"`) while leaving `broker.py:3631-3632`'s read-side gate in place as a no-op
that will simply never trigger again once no code writes `'keep'`. This is Andrew's call,
not mine to make read-only.

---

## 4.3 — `sb wait` is still live; the human inbox is genuinely gone

**`sb wait` — still fully live, contrary to DESIGN-TRUTH.md:315's "It has no reason to
exist."** Parser at `cli.py:321-332`:
```
wt = cmd(
    "wait", help="block until an agent reaches a state (for HUMANS, not agents)", ...)
wt.add_argument("name")
wt.add_argument("--for", dest="until", default="done", choices=status_mod.WAIT_STATES, ...)
wt.add_argument("--timeout", type=int, default=status_mod.WAIT_TIMEOUT, ...)
```
Validated at `cli.py:431-433`; dispatched at `cli.py:1014-1018` → `status.wait_for`
(`status.py:1519-1564`, `WAIT_STATES`/`WAIT_TIMEOUT` read from `config.setting
("states.wait")`/`config.setting("timeouts.wait")`). Its own help text (`cli.py:6-10`)
already argues against itself — "an agent that blocks on a child is burning a turn to do
what the doorbell already does for free" — but the command still exists and still runs.

**Pass condition.** `sb wait` no longer parses. `status.wait_for`, `WAIT_STATES`,
`WAIT_TIMEOUT` either delete with it or become dead code with nothing calling them (delete
them too — no reason to carry the machinery once the only caller is gone).

**What removal touches.** `cli.py:5,321-332,431-433,1014-1018` (module docstring listing
it as a human verb, parser, validation, dispatch), `status.py:1515,1519,1522,1547-1564`
(`WAIT_SLICE_MS`, `WAIT_STATES`, `WAIT_TIMEOUT`, `wait_for`), and
`defaults/settings.toml:136-157,236-272` (`[states] wait = [...]` at line 157,
`[timeouts] wait = 900` at line 266, `wait_slice_ms = 30000` at line 272) — confirmed
these three settings keys exist and have no other reader (grep of `config.setting(` for
`states.wait`/`timeouts.wait`/`timeouts.wait_slice_ms` across `switchboard/` finds only
the `status.py` lines above), so they delete cleanly with no other caller left stranded.

**Human inbox — genuinely gone as a readable mailbox, but not as a code path.** No
`HUMAN`-addressed message table or column exists in `store.py` (grep for `HUMAN`-scoped
mail state returns nothing). What remains is a deliberate refusal, not leftover
infrastructure: `cli.py`'s `inbox` dispatch (`cli.py:835-848`) special-cases `me == HUMAN`
and returns a fixed redirect string — "you have no inbox — agents that need you BLOCK..."
— rather than falling through to `b.inbox(...)`. `broker.py:3252,3267`'s `ask` similarly
refuses any target that resolves to `HUMAN`. **This is correct behavior, not a bug to
fix** — the brief's claim ("the human inbox is genuinely gone") holds for the thing that
matters (nothing a human could read exists), and this document does not list it as phase 4
work. Flagging only so nobody greps for "inbox" during 4.3's cleanup, finds these six
lines, and mistakes an intentional guard for a stray removal target — they should stay
exactly as they are (and if `sb ask` itself is removed per phase 3.6, the `broker.py`
guard goes with it as part of that item, not this one).

---

## 4.4 — `sb workspace new` is deleted once phase 5 covers space creation

**Confirmed still live and out of scope for phase 4, per the brief's own framing.**
Parser at `cli.py:260-274`, dispatch at `cli.py:989-991` → `Broker.workspace_new`
(`broker.py:1046` onward). Cross-referenced from `sb delegate --workspace`'s help text
(`cli.py:139-141`, "open one with: `sb workspace new <name>`") and from
`defaults/roles/orchestrator.md:8` ("`sb start` spawns it at the top, `sb workspace new`
spawns it as a workspace lead"). Not touched by this phase; recorded here only to confirm
the brief's framing matches the code and to flag the one place it interacts with phase
4.1's flag removal:

**Interaction with 4.1.** `sb workspace new` currently carries two of the flags 4.1
removes — `--focus` (`cli.py:272`) and `--no-board` (`cli.py:273-274`). If phase 4 lands
before phase 5 deletes the whole command (the stated order — see BUILD-PLAN.md's
"Phase 4 before 6," and phase 5 is unstarted as of this commit), `sb workspace new` needs
these two flags stripped in the same pass as `sb start`'s, even though the command itself
survives until phase 5. Otherwise phase 4 ships with one command's focus/board flags gone
and a sibling command's still live — an inconsistency inside the same release, not a real
technical blocker, but worth doing together rather than leaving for phase 5 to notice.

---

## Sequencing

**Within phase 4, no item depends on another** — `4.1`'s CLI flags, `4.2`'s persisted
state, and `4.3`'s `sb wait` touch disjoint code (CLI parser blocks are independent per
command; `4.2`'s store/settings/role work is its own vertical slice). They can be built by
one owner in any order, or split across owners with no handoff, **except**:
- `4.1`'s flag deletions on `sb delegate`/`sb cleanup` and `4.2`'s column/field collapse
  are two views of the same change (the flags exist only to set the column) — one owner,
  one commit, so the migration decision above is made once, not twice.
- `4.4`'s `sb workspace new` flag-stripping should land in the same commit as `4.1`'s
  `sb start` flag-stripping, for the reason given above, even though the rest of
  `sb workspace new` is untouched until phase 5.

**Against phases elsewhere:**
- Phase 3 before phase 4, per BUILD-PLAN.md's own rule ("nothing is deleted before its
  replacement exists") — but this pass found phase 4's items have **no actual dependency**
  on phase 3's replacements. `--keep`/`--ephemeral`/`--include-kept`/`--leave-children`/
  `--no-board`/focus-as-a-flag/`sb wait` are none of them related to the tell/interrupt/ask
  messaging cluster phase 3 is replacing. The ordering rule reads as a blanket "3 before
  4," but nothing in this phase's five items actually needs phase 3's work to land first —
  worth flagging to whoever sequences the build, since it means phase 4's items are
  parallelizable against phase 3 today, not just after it.
- Phase 4 before phase 6, unchanged from BUILD-PLAN.md: phase 6's prompt rewrite can't
  land while prompts still teach flags phase 4 is about to delete, and 4.2 already
  requires touching all five role files' `--keep`/`--ephemeral` paragraphs — whoever does
  4.2 should coordinate with whoever eventually does 6.1 so the same five paragraphs
  aren't rewritten twice for unrelated reasons.
- `sb workspace new`'s full deletion waits for phase 5, as the brief states; only its
  `--focus`/`--no-board` flags are phase 4's concern (4.4 above).

---

## Collision with phase 3's in-flight work

**Confirmed live via `sb status` at the time of this pass:** an agent named `tell-modes`
is currently `working`, tasked with "the `sb tell` cluster for phase 3: items 3.1 and 3.3,
then 3.2, then 3.6, in that order" — i.e. it owns exactly the `broker.py`
tell/interrupt/ask cluster and `sb interrupt`'s/`sb ask`'s deletion
(`audit/phase3-scope.md`'s own conflict map, `broker.py:3196-3320,3840-3882`,
`cli.py:130-160,305`). This is *not* the same code phase 4 touches — phase 4's `4.1`
(`sb delegate`/`sb cleanup`/`sb start`/`sb workspace new` flags) and `4.3` (`sb wait`) sit
in disjoint parser blocks and disjoint `Broker` methods from `tell`/`interrupt`/`ask`
(`cli.py:130-160` for `delegate`'s flags vs. `cli.py:305` for `interrupt` — different
`cmd()` calls, no shared lines). **No file-line collision expected between phase 4 and
`tell-modes`'s work**, but both will produce commits touching `cli.py` and (for 4.2)
`broker.py` in the same file, different regions — a merge, not a conflict, but sequence
them as separate commits/PRs rather than one sprawling diff so a `git blame` on either
region stays attributable to the phase that made it.

**Also relevant, already merged to branches but not yet to `main`:** `phase3.5a-needs-
reply` (branch `phase3-tell-modes`, commit `d41a6c6`) touches `cli.py`, `store.py`,
`broker.py`, and `defaults/prompts.toml` — the same four files 4.1/4.2 touch, though for
an unrelated feature (`--needs-reply`, not in phase 4's scope at all). Confirmed via
`git diff --stat main phase3-tell-modes`. Once that branch merges, phase 4's `cli.py` and
`store.py` edits will be diffing against a slightly different base than this document was
written against — not a blocker, just worth whoever builds phase 4 re-checking line
numbers against `main` at merge time rather than trusting this document's numbers past
that point.

---

## What surprised me

- **Every single item DESIGN-TRUTH.md's "Explicitly rejected" section names is still
  fully live in the code**, unlike phase 3's pass, which found four of its targets
  already fixed. `DESIGN-TRUTH.md` records a decision made 2026-08-09; none of it has been
  built. Treat this phase as ground-up removal work across the board, not a verification
  pass.
- **The one place something *is* already done — the per-role `cleanup` field — is done in
  a way that makes the remaining work larger, not smaller.** All five role files already
  carry prose explaining *why* there's no field any more, and that same prose is the exact
  text that now needs rewriting to stop naming the flags. A brief reading of "already
  removed from roles" could undercount this as finished; it isn't — the field is gone, the
  five paragraphs that used to justify it are the new liability.
- **`--ephemeral` has never been a distinct persisted state.** It maps onto the same
  `cleanup="close"` value the column defaults to with no flag at all. This shrinks 4.1's
  "delete two flags, migrate two states" framing to "delete one meaningful flag
  (`--keep`) and one flag that has always been a no-op (`--ephemeral`)."
- **A live `sb status` check found an actual in-progress collision risk** the brief asked
  to watch for — agent `tell-modes` is mid-flight on the exact cluster (`sb interrupt`,
  `sb ask`) phase 3 is replacing — but the collision turned out to be non-file-overlapping
  with phase 4's own targets, which is worth Andrew knowing before assuming the brief's
  warning means the two phases must serialize.
