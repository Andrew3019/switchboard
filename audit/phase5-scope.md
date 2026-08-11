# Phase 5 scope — structure

Read-only audit. Base: `phase3-messaging` tip `8f69642` (phase 3 fully merged into that
branch; phase 4 is being built on `phase4-removals`, which as of this read is
byte-identical to `phase3-messaging` — `git diff phase3-messaging phase4-removals --stat`
is empty, so no phase-4 removal has landed on disk yet). Modelled on
`audit/phase3-scope.md` and `audit/phase4-scope.md` (read from `scope-phase4`). Covers
BUILD-PLAN.md's phase 5 bullets 5.1–5.4.

Ground truth taken as given, not re-derived: `DESIGN-TRUTH.md:34-78` (the CUJs — where
each spawn lands, worktree ownership) and `:173-186` (scope). `DESIGN-TRUTH.md:42-47`
states the phase-5 mechanism as already **confirmed** design, not merely proposed — this
document is about whether the *code* matches that confirmed decision, not whether the
decision is right.

**Headline finding.** All four items are real, unbuilt work, closer to phase 4's "nothing
of this is done" pattern than phase 3's "half of this turned out to already be fixed"
pattern — with one nuance worth stating up front: 5.1's *architectural* fact (only `sb
start` produces a bare root) is already true by construction and needs no code change:
what's missing is the *stamp itself*, which literally does not exist as a column, field,
or in-memory marker anywhere. 5.2's *apparent* branching (a top's children get new
worktrees, everyone else's get tabs) is also already true in practice — but for the wrong
reason (it keys off worktree possession, not top-ness), and I found a live, reproducible
case in the store where that distinction actually matters. 5.3 has zero enforcement, and I
found a live agent that has already exploited the gap 17 times over. 5.4 has one command
(`cleanup`) correctly scoped and five unscoped — down from six, because `sb ask` (one of
BUILD-PLAN's six) no longer exists; it was removed by phase 3.6, confirmed by `grep -rn
"\"ask\"\|'ask'" cli.py broker.py` on `phase3-messaging` returning nothing.

I cross-checked all four items against the live store at
`/Users/andrew/Code/switchboard/.git/agentflow/state.db` (249 agent rows as of this read,
2026-08-11 — the brief's "~246" is close; the number moves). That store is written by
whatever `bin/sb` on `PATH` resolves to, which BUILD-PLAN.md's hazard #2 already notes is
`main`, not `phase3-messaging` — so the live rows described below were created under
pre-phase-3 code (their CLI still lists `ask`, confirmed by running `sb --help` directly),
but the *schema* (`agents` table) is shared by both branches unchanged, so what the store
shows about column shape and row shape is valid evidence for phase 5 regardless.

---

## 5.1 — `sb start` is the only path that creates a top; stamp it there

**Two separate claims bundled into one bullet, and they are in different states.**

**Already true, and confirmed two ways — not phase-5 work.** Only `Broker.start` →
`Broker._top` (`broker.py:719-741`, `:789-870`) ever produces a row with `parent IS NULL
AND branch IS NULL` (a bare space with no worktree, over the main checkout).
`Broker.workspace_new` (`broker.py:1091` onward) always calls `_attach_workspace`, which
gets or creates a worktree — a workspace-new row always has a `branch`. `Broker.delegate`
(`broker.py:2959-3186`) either inherits the caller's branch or forks a new one (`branch`
is always non-NULL on the result) — nothing in `delegate` can produce `branch IS NULL`
for anyone but the caller itself, and the caller is never the one being created. Live
cross-check: `SELECT name,parent,role,branch FROM agents WHERE parent IS NULL` returns
exactly 7 rows (`main`, `main-2`..`main-7`), all `branch IS NULL`, all `role='orchestrator'`
— no counterexample. So "`sb start` is the only path" is real and does not need building.

**Not true, and this is the actual phase-5 work.** Nothing is stamped anywhere. `CREATE
TABLE agents` (`store.py:140-186`) has no column recording provenance — no `is_top`, no
`created_by`, nothing. `store.claim_agent` (`store.py:859-875`) takes no such parameter
either. The only way to answer "was this row created by `sb start`" today is the same
inference I just ran by hand (`parent IS NULL AND branch IS NULL`) — which is not a stamp,
it's a coincidence of two other columns that happen to correlate with top-ness *for now*
(see 5.2, where that same coincidence is the actual bug).

**Pass/fail test.** Spawn via `sb start`; query the resulting row for a persisted fact
that says "this was created by `sb start`," independent of `parent`/`branch`. Today: fails
— no such fact exists to query.

**What a fix touches.** `store.py:140-186` (new column on `agents`, e.g. `is_top INTEGER
NOT NULL DEFAULT 0`), `store.py:859-875` (`claim_agent`'s signature, to accept and write
it), `broker.py:789-870` (`_top`, at the point it calls `self.delegate(...)` —
`broker.py:857-858` — to pass the new flag through, or a follow-up `store.update_agent`
call after the row exists).

**Migration.** All 249 live rows, including the 7 live tops, predate this column by
construction — there is no code path today that could have written it. Recommend
backfilling with exactly the inference above (`parent IS NULL AND branch IS NULL` → stamp
`1`), run once as part of the migration that adds the column: it is provably correct for
every row in the store today (I checked all 7 roots match it and nothing else does), and
it is the same fact the code has been relying on implicitly since before this phase. This
is a low-risk migration — unlike 4.2's `cleanup='keep'` question, there is no ambiguity
about which existing rows should get the new value.

**Sequencing.** First — 5.2 and 5.3 both need to read this stamp.

---

## 5.2 — `sb delegate` branches on the stamp

**What happens today: the right *behavior*, for the wrong *reason*, confirmed live.**
`delegate`'s fork rule (`broker.py:3014`, `if inherited and not self.has_worktree(me):`)
forks a new worktree/space whenever the caller has no worktree of its own
(`has_worktree`, `broker.py:2579-2587`, reads `agents.branch IS NOT NULL`). A top always
has `branch IS NULL` (per 5.1), so every top's `delegate` call forks — which *looks like*
5.2's rule. But the rule is keyed on worktree possession, not on being a top, and those
are not the same fact: I found 6 live rows that are non-root (`parent IS NOT NULL`) and
also `branch IS NULL` —
`workspace-debug`, `sb-guard`, `verify-design`, `wm-land`, `design-patch`,
`phase1-split` — deliberately bare, per DESIGN-TRUTH:60-64's "read-only task... we will
not need a write for later on." If any of these delegates, `has_worktree(me)` is False
and the fork rule fires exactly as it would for a real top: a brand-new space and
worktree, for an agent that is not a top and was never meant to mint one. **This is the
concrete, already-live case where "share a role name, no code branches on it" bites**:
nothing distinguishes "bare because I am the top" from "bare because I was deliberately
given a read-only task."

**The other half: `sb workspace new` still exists as a separate command doing the thing
`delegate` is supposed to do itself.** DESIGN-TRUTH:212-214 — "`sb delegate` figures out
where a spawn lands rather than the caller passing flags for it. The top can spawn a
space with either an orchestrator or a single worker" — describes `delegate` subsuming
`workspace_new`'s job. Today they're two different entry points (`broker.py:1091` vs.
`broker.py:2959`), and phase 4's own scoping document already flagged this exact
dependency: "`sb workspace new` is deleted once phase 5 covers space creation" (4.4). 5.2
is where that gets built, not just a small `if` added to the existing fork rule.

**Pass/fail test.**
- A stamped top's `sb delegate` (any role) produces a new space and worktree — already
  true today, but for the wrong reason (see above); should stay true once fixed.
- A non-top agent that happens to be bare (the 6-row case above) delegating must get a
  **tab in its own space**, not a fork. Fails today — reproducible from the current store
  state; any of those 6 names' next `delegate` call forks incorrectly.
- Once 5.2 lands, `sb workspace new` and `sb delegate` from a stamped top should be
  behaviorally equivalent for creating a workspace + orchestrator, which is the
  precondition phase 4's 4.4 is waiting on.

**What a fix touches.** `broker.py:3014` (the fork-rule condition itself — needs the
5.1 stamp, not `has_worktree`, as its input, or needs both: "is this caller a top" for
whether to create a *new named space*, distinct from "does this caller have a worktree"
for whether to fork one), `broker.py:1091` onward (`workspace_new`'s creation logic
folded into `delegate`, or left as a thin wrapper), `store.py` (same stamp column as
5.1). Depends on 5.1 landing first.

---

## 5.3 — a bare agent's `delegate` is refused outright

**Not built at all, and I found a live, already-exploited instance of the exact gap.**
Nothing in `Broker.delegate` (`broker.py:2959` onward) or the CLI dispatch
(`cli.py:786-810`) checks the caller's role, depth, or worktree status before allowing a
spawn — grepped `broker.py` for any role/depth restriction near `delegate`
(`role !=`, `role not in`, `bare agent`, `cannot spawn`) and found nothing. Live proof:
agent `worker-2` — `role='worker'` (`DEFAULT_ROLE`, `defaults/settings.toml:101`,
i.e. exactly the "bare agent" role DESIGN-TRUTH describes as unable to spawn) — has 17
children in the store today: `journey-1..3`, `recheck-1..3`, `recheck-a/b/c` (all
`role='worker'`), and `audit-1..6`, `audit-2b` (all `role='orchestrator'`). A `worker`-role
agent not only delegated, it delegated *orchestrators*. This is not hypothetical; it is
`sb status`-visible right now.

**Open question this item needs answered before it can be sized: what makes an agent
"bare"?** DESIGN-TRUTH:53-58 describes bareness by role-intent ("Top spawns a bare agent
= new worktree/space and agent, and that agent cannot spawn other agents") — note a bare
agent *does* get a worktree in this model, so worktree possession cannot be the
discriminator here (unlike 5.2, where it partially can). The only two candidates I can
see in the current code:
- Check the literal role string (`role == "worker"` / `role == config.setting
  ("vocabulary.default_role")`). Cheap, but `roles.py`'s own docstring states "Vocabulary
  is data (C12) — there is no closed set" — a repo-defined role that isn't named `worker`
  but is still meant to be a leaf would slip through this check.
- Add a field to `Role` (`roles.py:34-42`, alongside `model`/`cleanup`/`prompt`) —
  e.g. `can_delegate: bool = False`, set `True` only by `orchestrator.md`'s frontmatter.
  Consistent with how the rest of the role system is data-driven, and is what I'd
  recommend, but it is a decision, not something to infer.

**Pass/fail test.** As `worker-2` (or any role without delegate rights), `sb delegate`
must be refused with a clear reason. Today: succeeds unconditionally, confirmed by the 17
rows above.

**What a fix touches.** `broker.py:2959` onward (a check near the top of `delegate`, after
`me = me or self.whoami()` at `broker.py:2978`), `roles.py:34-42` (if the field-based
approach is chosen), `defaults/roles/orchestrator.md` (mark `can_delegate = true` in
frontmatter, if that path is chosen) and the other four shipped role files (state plainly
that they cannot delegate — none of them mention this today), `cli.py:786-810`
(`delegate` dispatch — no change needed if the refusal raises from the broker, since CLI
dispatch already surfaces broker exceptions as errors).

**Migration / live-fleet risk — the single biggest risk in this whole document.**
`worker-2` is not a hypothetical past mistake; nothing in the store says it is done, and
if it (or any other currently-running `worker`-role agent leaning on this same
undocumented capability) tries to delegate again after this ships, it will be refused
**mid-task**, with no warning, for a pattern that has worked 17 times in a row for it
already. A query for "worker-role agents with live (not done/failed) children" run at
ship time would surface any others like it before the refusal goes live — I did not run
that query as part of this read (read-only pass, and it would need a definition of "live"
matching `status.stalled`'s rules to be accurate), but it is cheap and I'd recommend
running it immediately before 5.3 ships, not after.

---

## 5.4 — tree boundary

**BUILD-PLAN's list is stale — `sb ask` is gone.** Confirmed by grepping `phase3-messaging`'s
`cli.py` and `broker.py` for `"ask"`/`'ask'` and finding nothing; phase 3.6 removed it
(`broker.py`'s `Broker.ask` no longer exists, and `cli.py`'s parser has no `ask` subcommand).
So the live list is five commands, not six: `tell`, `status`, `inspect`, `log`, `restore`.

**One of five is already correctly scoped — confirmed, not phase-5 work.**
`Broker.cleanup` (`broker.py:3487-3493`): `if me == HUMAN: scope = <everything> else:
scope = self._descendants(me)`. Non-human callers only ever see their own descendants;
Andrew sees everything. This is exactly DESIGN-TRUTH:180-181's rule ("Only agents have the
scope constraints... from it Andrew crosses freely into any tree").

**The other four (plus `tell`) are unscoped, confirmed by reading each:**
- **`tell`** (`broker.py:3241-3289`) resolves any target via `_resolve`
  (`broker.py:651-655`), which does a bare name lookup with no ownership check at all.
  Nothing stops an agent under one top from `sb tell`-ing a name that belongs to a
  different top's tree.
- **`status`** — `status.collect` (`status.py:377-431`) runs `SELECT * FROM agents` (`:431`)
  unconditionally; the *only* scoping mechanism is `mine` (`status.py:384`, threaded
  through `_filter` at `:525` and `:790`), and it is **opt-in**: `cli.py:204`'s `--mine`
  flag defaults to `False`, wired at `cli.py:938` (`mine=(me if args.mine else None)`). An
  agent that does not pass `--mine` sees the whole store, same as Andrew.
- **`inspect`** — `cli.py:1051-1057` → `status.inspect(db, h, args.name, ...)`
  (`status.py:1294` onward) takes a bare name with no caller identity threaded through at
  all — not even an opt-in flag exists here, unlike `status`.
- **`log`** — `cli.py:1066-1070` → `store.recent_events(db, agent=args.agent, limit=...)`,
  globally, no caller scoping in any form.
- **`restore`** — `broker.py:3701` onward, `cli.py:1046-1049` → `b.restore(args.name)`,
  looked up by name with no ownership check.

**The fix cannot just copy `cleanup`'s mechanism, and this is worth flagging explicitly.**
`cleanup` scopes to `self._descendants(me)` — the caller's own descendants only. But
DESIGN-TRUTH:175-178 draws the boundary at the **top's whole tree**, explicitly including
siblings: "Siblings are not invisible to each other; any other top orchestrator's entire
tree is invisible." `_descendants(me)` would hide a sibling from another sibling, which is
narrower than the confirmed rule (and happens to be fine for `cleanup` specifically,
because DESIGN-TRUTH also says "the orchestrator handles cleanup itself" — a different,
tighter rule that's specific to that one command). The other five need a different
primitive: "does the caller's root ancestor equal the target's root ancestor" — which does
not exist anywhere in `broker.py` today (grepped for an ancestor-walk-to-root helper;
`_resolve` at `broker.py:651-655` is the closest thing and it doesn't walk anything). This
is new code, not a reuse of `cleanup`'s.

**Pass/fail test.** From an agent inside top A's tree: `sb tell <agent-in-top-B>` is
refused (today: succeeds). `sb status` (no `--mine`) shows only top A's tree, unless the
caller is Andrew (today: shows every tree to anyone). Same for `sb inspect`/`sb log`/`sb
restore` on a name outside the caller's top (today: all succeed).

**What a fix touches.** `broker.py` (a new root-ancestor-walk helper; `tell`'s
`_resolve`/loop at `:3241-3289`; `restore` at `:3701`), `status.py` (`collect`'s `mine`
default — today only set from an explicit flag, needs to default *on* for non-human
callers the same way `cleanup` already branches on `me == HUMAN`; `inspect` needs the same
parameter added, since it currently has none), `cli.py` (thread `me` into the `inspect`,
`log`, and `restore` dispatch blocks the same way `delegate`/`cleanup` already receive
it), `store.py` (`recent_events` needs either a scope-aware query or a post-filter for
`log`, since it takes no caller identity today). Depends on 5.1's stamp only indirectly —
walking to the root ancestor doesn't need the stamp itself, just intact `parent` chains,
which all 249 live rows have (spot-checked).

**Migration.** No schema change needed for this item specifically (unlike 5.1/5.2) — the
root-walk is computed at call time from `parent`, which is already populated on every live
row. The real risk is behavioral, not data: enforcement lands and immediately hides
cross-tree state that is visible today. Concretely, if any live workflow currently has one
top's agent `tell`ing or `inspect`ing a name that structurally sits under a different top
(I did not find evidence of this in the live store, but nothing prevents it today, so it
cannot be ruled out either), that communication silently breaks the moment this ships,
with no error pointing at why — worth logging a specific refusal message ("that agent is
in a different top's tree") rather than a bare "not found," so a broken workflow is
diagnosable.

---

## Collisions with phase 4's in-flight removals

- **Schema, same table, same migration shape of question.** 4.2 is deciding whether to
  delete the `cleanup` column (`store.py:165`) outright or leave it as a no-op; 5.1 needs
  to *add* a new column (`is_top`) to the exact same `CREATE TABLE agents`
  (`store.py:140-186`). Not a line conflict, but both are schema migrations touching the
  same table in the same window, and both are asking Andrew the same-shaped question
  ("what happens to rows written before this column existed"). Recommend answering both
  at once so the migration pattern (backfill vs. leave-as-default) is decided once, not
  twice, possibly two different ways.
- **`sb workspace new`'s fate is split across the two phases.** 4.1 strips
  `workspace_new`'s `--focus`/`--no-board` flags (cheap, independent, can land any time);
  4.4 defers the command's full deletion to "once phase 5 covers space creation" — which
  is exactly 5.2. Land 4.1's flag-stripping first (no dependency), but do not delete
  `workspace_new` itself until 5.2's `delegate`-side replacement exists and is proven
  equivalent — same "replacement before deletion" rule BUILD-PLAN states elsewhere.
- **Role-file churn, same five files, three different phases.** 4.2 is already rewriting
  all five `defaults/roles/*.md` files' `cleanup`-related paragraphs. 5.3 needs to add
  "this role cannot delegate" text to (at least) `worker.md`. 6.1/6.3 are also going to
  touch these same five files (block rules, generated role list). Recommend one owner
  sequences all of it as one pass per file, the same coordination note
  `audit/phase4-scope.md` already gave for 4.2 vs. 6.1.

## Collisions with phase 6's prompt rewrites

- **6.3** ("every agent is told at spawn what roles exist, generated from the roles
  themselves") and **5.3** (bare-agent refusal) both want `Role` to carry new structured
  data — 6.3 a role *list*, 5.3 a role *capability* (can-delegate). If 5.3 adds a
  `can_delegate` field, 6.3's generator should read the same field when explaining to a
  spawned worker why it can't delegate, rather than the two being built independently and
  drifting apart.
- **Phase 5 before 6, per BUILD-PLAN's own ordering rule** — "the prompt should explain a
  rule the code already enforces." Concretely: `defaults/roles/orchestrator.md`'s framing
  paragraph ("the only difference between the top one and the deepest one is scope... Two
  roles meant two prompts to keep in sync") is itself the thing 6's prompt work would
  rewrite, and it should only be rewritten once 5.1/5.2 make the top/workspace split real
  in code — rewriting it now would describe a rule that doesn't exist yet.

---

## Decisions needed from Andrew

1. **How are the 249 existing (unstamped) agents treated once 5.1 ships a stamp column?**
   Recommend: backfill using `parent IS NULL AND branch IS NULL` at migration time — I
   verified this predicate matches all 7 live roots and nothing else, so it is a safe,
   provably-correct one-time backfill, not a judgment call the way 4.2's `cleanup='keep'`
   question is.
2. **What defines "bare" for 5.3's refusal** — the literal role string, or a new
   `Role.can_delegate` field? Recommend the field: it matches the project's existing
   "vocabulary is data" philosophy (`roles.py`'s own docstring) and survives a repo
   defining its own non-orchestrator role name.
3. **How strict should 5.3's rollout be, given `worker-2`'s 17 live children?** Recommend:
   run a query for worker-role agents with live children immediately before shipping, and
   decide per-result whether to let already-running agents finish their current delegate
   pattern (grandfather by spawn time) or refuse immediately across the board. This is a
   judgment call about breaking live work versus closing the gap now — not mine to make
   read-only.
4. **Does 5.2 delete `sb workspace new` itself, or only make it behaviorally redundant
   and leave deletion for a later pass?** Recommend: land `delegate`'s new branching
   first, confirm it produces the same result `workspace_new` does today, then delete
   `workspace_new` as phase 4's 4.4 already specifies — sequential, not one commit,
   because 4.4's own wording ("once phase 5 covers space creation") implies the
   replacement must exist and be trusted first.

---

## What surprised me

- **The fork rule already produces 5.2's user-visible behavior today, for a reason that
  will misfire on agents that already exist in the store.** I did not expect to find live
  rows (`workspace-debug`, `sb-guard`, `verify-design`, `wm-land`, `design-patch`,
  `phase1-split`) that are simultaneously non-root and worktree-less — the exact shape
  that would trip the fork rule into wrongly minting a new space if any of them delegates.
- **5.3's gap is not hypothetical or narrowly theoretical — it has already happened 17
  times over, live, in the store this document was cross-checked against.** `worker-2`, a
  `worker`-role agent, has both `worker`- and `orchestrator`-role children. Whatever
  refusal 5.3 builds will need to decide what happens to that agent specifically, not just
  to the abstract rule.
- **`cleanup` is scoped correctly, but its scoping rule (own descendants only) is
  actually *stricter* than the boundary the other five commands need (whole top's tree,
  siblings included).** It cannot be copied as-is; the general fix needs a root-ancestor
  comparison that doesn't exist in the code yet, not a reuse of `_descendants`.
