# Audit group 6 of 6 — Removals and flags

Switchboard's real state vs. the confirmed design truth in
`/Users/andrew/.herdr/worktrees/switchboard/worker-2/DESIGN-TRUTH.md` (the only trusted
document). Read-only audit; no code or docs were changed. Findings live only under /tmp.

**Which tree.** Source was read from the worktree
`/Users/andrew/.herdr/worktrees/switchboard/worker-2`. The `sb` on PATH is
`/Users/andrew/.local/bin/sb` -> `/Users/andrew/Code/switchboard/bin/sb`, i.e. the main
checkout, so runtime observations come from **main**, not the worktree. Each finding was
checked against local main (caa6d20); on every item audited the two trees are identical,
so nothing here is worktree staleness and nothing here is "already fixed on main".

**Totals across 14 audited entries: 2 SATISFIED, 2 PARTIAL, 10 BROKEN, 0 UNVERIFIED.**

The three sharpest gaps:

1. **Every one of the six rejected flags is still a live, registered CLI option** —
   `--keep`, `--ephemeral`, `--include-kept`, `--leave-children`, `--no-board`, and a
   focus flag on `sb workspace new`. `--keep`/`--ephemeral` are worse than flags: they
   are persisted state (a cleanup column in the store, a default in settings, a field on
   every role) and all five shipped role prompts actively instruct agents to use them.
2. **The shipped agent protocol still tells every agent to use `sb ask`**, and the store
   holds real ask rows — so agents wait on each other today, which the design truth
   rejects outright. Meanwhile `sb tell` has no interrupt delivery mode at all, so the
   sanctioned replacement for `sb interrupt` does not exist: deleting the verb would
   delete the capability rather than relocate it.
3. **Merging has no gate and no existence.** There is no merge verb, no approval
   mechanism, no guard, no hook, and no prompt anywhere that tells an agent merging
   needs Andrew's approval — so that rule is entirely unenforced and invisible.

The one clean result: the human inbox is genuinely, fully removed, and workspaces really
do fork from `origin/main` with a fetch first.

---

# Part A — the removed verbs and the human inbox

# Audit 6 — Brief A: removed verbs and the human inbox

**Tree audited:** `/Users/andrew/.herdr/worktrees/switchboard/worker-2` (branch `worker-2`).
**Important:** `git diff --stat main -- switchboard bin defaults` is EMPTY — the worktree
code and local `main` are byte-identical over the audited surface. `./bin/sb --help` from
the worktree and from `/Users/andrew/Code/switchboard` print the identical verb list. So
every finding below applies to both trees; nothing here is "already fixed on main".

**Live store inspected read-only:** `/Users/andrew/Code/switchboard/.git/agentflow/state.db`
(the `.switchboard/state.db` in the main checkout is a stale empty file, 0 agents/0 rows).

---

### 1. The human inbox — "100% removed" (DESIGN-TRUTH.md:280-281)

**Verdict:** SATISFIED

**Evidence:**
- `broker.tell` refuses a human target *before writing any row*:
  `switchboard/broker.py:2678-2685` — `if t == HUMAN: raise ValueError("the human has no
  mailbox — a message to them would never be read. Use \`sb block ...\`")`.
  Ran from the worktree: `./bin/sb tell human "audit probe"` →
  `sb: the human has no mailbox — a message to them would never be read. Use `sb block
  "<why>"` if you need an answer, or `sb done "<summary>"` to report what you did.`
- `broker.ask` refuses it too, and refuses the whole fan-out before writing anything:
  `switchboard/broker.py:2739-2745`. Ran `./bin/sb ask human "audit probe"` →
  `sb: there is no way to ask the human and wait — they have no mailbox ... Use `sb block`.`
- `sb inbox` run as the human returns an explicit no-mailbox message, not an empty list:
  `switchboard/cli.py:763-773` (`{"messages": [], "human": True}`).
- `broker.block` writes NO message row — state + event log only, read back by
  `sb status --needs-me`: `switchboard/broker.py:2872-2905`.
- Root `done` writes no row either: `switchboard/broker.py:2854-2857` guards
  `if parent:` before `put_message`, and a root agent's parent is NULL.
- `store.undelivered(..., exclude=(HUMAN,))` at `switchboard/cli.py:756` +
  `switchboard/store.py:1302-1307` exists only to skip *legacy* rows written before
  removal; nothing writes new ones.
- `validate.target` (`switchboard/validate.py:204-215`) accepts `human` as a *shape*
  deliberately, so the broker can give the teaching refusal rather than a shape error.
  That is not a mailbox.
- Store: `select count(*) from messages where to_agent='human' or from_agent='human'` → **0**
  (out of 344 rows: 188 tell, 148 done, 8 ask). No `user`/`andrew` target exists anywhere;
  the only non-agent address name is `vocabulary.human = "human"`
  (`defaults/settings.toml:70-73`).
- Shipped prompts say the same: `defaults/protocol.md:119` — "`sb block "<why>"` is the
  ONLY way to reach a human — they have no inbox"; `defaults/settings.toml:117` — "There
  is deliberately no `blocked_prefix`. A block is not mail: the human has no mailbox".

**Which of CLI / broker / store / config / prompts still contain it:** none as a working
surface. Residue only: `switchboard/status.py:1075` comments the `NEEDS YOU` block list as
"This IS the human's inbox" — a rendering of blocked-agent rows, which is the sanctioned
replacement, not a mailbox; and the `human` shape/exclude affordances above, which exist to
*refuse* and to skip pre-removal rows.

**Gaps:** none.

---

### 2. `sb ask` — rejected (DESIGN-TRUTH.md:283)

**Verdict:** BROKEN — fully present in CLI, broker, store, config and shipped prompts.

**Evidence:**
- CLI verb exists and is advertised: `./bin/sb --help` lists `ask` →
  `ask   send a question and WAIT for the answer`. Parser at `switchboard/cli.py:139-143`
  (`a = cmd("ask", help="send a question and WAIT for the answer")`), dispatch at
  `switchboard/cli.py:370` and `switchboard/cli.py:739-740` (`b.ask(...)`).
  `./bin/sb ask --help` prints `--timeout TIMEOUT` and `who ... question`.
- Broker implements it as the blocking verb: `switchboard/broker.py:2713-2810`
  (`def ask(...)`, "it is the only blocking verb"), with its own poll loop.
- Message kind: `store.put_message(..., kind="ask")` at `switchboard/broker.py:2752-2754`;
  the schema documents the kind at `switchboard/store.py:194`
  (`kind TEXT NOT NULL, -- ask | tell | done`), plus `store.pending_ask`
  (`switchboard/broker.py:2691`) and `store.reply_to_ask` (`switchboard/broker.py:2769`).
- Config: `timeouts.ask` / `timeouts.ask_poll` at `defaults/settings.toml:213` and
  `switchboard/broker.py:101-103`.
- **Shipped prompts still instruct agents to use it** — `defaults/protocol.md:103-105`,
  verbatim:
  > ``sb ask <who> "<question>"`` sends to another agent and WAITS for its answer — for
  > agents only, and only when the answer is seconds away.

  and `defaults/prompts.toml:71` rings a dedicated doorbell for it:
  `mail_question = "You have mail (a question) — someone is waiting on your answer and
  cannot continue without it. Run: sb inbox"`.
- It is in live use, not vestigial: the store holds **8 rows with `kind='ask'`**.

**Which of CLI / broker / store / config / prompts still contain it:** **all five.**

**Gaps:**
- `ask` subparser + dispatch still in `switchboard/cli.py:139-143, 370, 739-740`.
- `Broker.ask` and its wait loop still in `switchboard/broker.py:2713-2810`.
- Message kind `ask` still written and still documented in the schema comment
  (`switchboard/store.py:194`); `pending_ask` / `reply_to_ask` helpers still in `store.py`.
- `tell`'s auto-correlation to a pending ask (`switchboard/broker.py:2687-2692`) depends on
  the ask kind and would have to go with it.
- `timeouts.ask` and `timeouts.ask_poll` still in `defaults/settings.toml:213-226`.
- `defaults/protocol.md:103-105` still teaches every agent to call `sb ask` — this is the
  prompt agents actually obey.
- `notify.mail_question` (`defaults/prompts.toml:67-71`) exists only to announce an ask.

---

### 3. `sb wait` — rejected (DESIGN-TRUTH.md:285)

**Verdict:** BROKEN — present in CLI, broker/status layer and config. Absent from prompts.

**Evidence:**
- `./bin/sb --help` lists `wait  block until an agent reaches a state (for HUMANS, not
  agents)`. Parser at `switchboard/cli.py:305`, dispatch at `switchboard/cli.py:411` and
  `switchboard/cli.py:911-914`.
- `./bin/sb wait --help` works and prints `--for {done,failed,blocked,working,idle}` and
  `--timeout TIMEOUT` (default 900).
- Implementation: `switchboard/status.py:1378-1411` ("`sb wait` — block until an agent gets
  somewhere"), module docstring at `switchboard/status.py:1`.
- Config: `defaults/settings.toml:141` (`--for` state list), `:239`, `:242`.
- An internal caller also exists: `switchboard/herdr.py:667` calls
  `self._call("agent", "wait", name, "--until", until, ...)` — note this is *herdr's* wait,
  not `sb wait`, and `herdr.py:682` mentions `sb wait` only in a comment.
- Not in shipped prompts: no hit for `sb wait` in `defaults/protocol.md`, `defaults/roles/*`,
  `defaults/presets/*`, `defaults/plugins/*/agent.md`.

**Which of CLI / broker / store / config / prompts still contain it:** CLI ✅ present,
broker/status layer ✅ present, config ✅ present, store — nothing persisted, prompts —
clean.

**Gaps:**
- `wait` subparser + dispatch in `switchboard/cli.py:305, 411, 911-914`.
- `wait()` implementation and its constants in `switchboard/status.py:1378-1411`.
- `wait.states` / wait timeout settings in `defaults/settings.toml:141, 239, 242`.
- Code still justifies it in prose ("for HUMANS, not agents", `switchboard/cli.py:9`,
  `switchboard/status.py:1381`) — that rationale is what DESIGN-TRUTH.md:285 overrules
  ("It has no reason to exist"), so the comments must go too or they will re-argue for it.

---

### 4. `sb interrupt` as a verb — must exist ONLY as a delivery mode of `tell`
(DESIGN-TRUTH.md:287-288)

**Verdict:** BROKEN — on both halves. The standalone verb exists; the `tell` delivery mode
does not exist at all.

**Evidence:**
- Standalone verb present: `./bin/sb --help` lists
  `interrupt  change an agent's course mid-flight`; `./bin/sb interrupt --help` →
  `usage: sb interrupt [-h] [--json] name text`. Parser `switchboard/cli.py:288`, dispatch
  `switchboard/cli.py:402` and `:897-899` (`b.interrupt(args.name, args.text)`).
- Broker implements it as its own operation: `switchboard/broker.py:3184-3226`
  (`def interrupt(self, name, text, ...)`) — sends `esc`, waits `INTERRUPT_SETTLE`, then
  puts the instruction on the wire; logs `kind="interrupt"` (`broker.py:3226`) and
  `kind="interrupt_stop_failed"` (`broker.py:3219`).
- **No delivery mode on `tell`.** `./bin/sb tell --help` →
  `usage: sb tell [-h] [--json] who [who ...] message` — there is no `--interrupt`, no
  `--mode`, no `--now`. `Broker.tell` (`switchboard/broker.py:2670-2676`) takes only
  `reply_to` and `kind`, and `kind` is never set to `interrupt` by any caller
  (`cli.py` passes the default `"tell"`); interrupt does not go through `tell` at all —
  `switchboard/store.py:1264` says "`ask` and `interrupt` write their rows themselves".
- Design intent is written into the code the *opposite* way round:
  `switchboard/broker.py:12-15` documents "`tell` vs `interrupt`" as two separate verbs.
- Config: `timeouts.interrupt_settle = 0.5` (`defaults/settings.toml:248-251`,
  `switchboard/broker.py:105-107`).
- Prompt text: `defaults/prompts.toml:84` and `:94` define `notify.interrupt`, the body
  delivered by the verb (`[INTERRUPT — stop now] ...`). No `defaults/` file tells an agent
  to *call* `sb interrupt`, and `switchboard/cli.py:4` scopes it to the human — but the
  verb is still on the public CLI surface, which is what the rejection names.
- `switchboard/plugins.py:25` lists `interrupt` in the verb/cost table.
- Events named `interrupt` are persisted in the store's event log
  (`switchboard/broker.py:3219, 3226`).

**Which of CLI / broker / store / config / prompts still contain it:** **all five** — CLI
verb, `Broker.interrupt`, `interrupt` event kinds in the store, `timeouts.interrupt_settle`
in config, `notify.interrupt` in shipped prompts. (The prompt string itself would survive a
correct design as the body of `tell --interrupt`; the others would not.)

**Gaps:**
- `interrupt` subparser + dispatch still on the CLI: `switchboard/cli.py:288, 402, 897-899`.
- No `--interrupt` / `--mode interrupt` flag on `sb tell` — the sanctioned form does not
  exist, so removing the verb today would remove the capability entirely.
- `Broker.tell` has no path that cancels the turn; `Broker.interrupt`
  (`broker.py:3184-3226`) is a parallel implementation that must be folded into `tell` as a
  mode, including the `force` ring at `broker.py:3391-3420`.
- `switchboard/broker.py:12-15` and `switchboard/plugins.py:25` document/list interrupt as
  a peer verb of `tell` and would contradict the folded design.

---

## Summary

Four items: **1 SATISFIED, 3 BROKEN, 0 PARTIAL, 0 UNVERIFIED.** The human inbox is
genuinely and thoroughly gone — refused in `tell` and `ask` before any row is written, no
row from `block` or from a root `done`, an explicit "you have no inbox" from `sb inbox`, zero
`human` rows in the live store, and prompts that say so; the only residue is a `human` target
*shape* kept deliberately so the refusal can teach `sb block`. The other three rejections have
not happened at all: `ask`, `wait` and `interrupt` are all still live CLI verbs, identical in
this worktree and in local `main`. My three sharpest gaps: (1) `defaults/protocol.md:103-105`
still instructs every agent to use `sb ask` and `defaults/prompts.toml:71` rings a doorbell
for it — the store holds 8 `kind='ask'` rows, so agents are blocking on each other right now;
(2) `sb tell` has no `--interrupt`/`--mode` delivery mode at all, so the design-truth shape
for interrupting does not exist and deleting the verb would delete the capability; (3) `sb
wait` is not just present but argued for in code comments ("for HUMANS, not agents"), which
will re-litigate the rejection unless the comments go with the code.

Process notes: everything above was read from the worktree and cross-checked with
`git diff --stat main` (empty over `switchboard/`, `bin/`, `defaults/`), so the PATH-`sb`
hazard in the common brief did not bite — I invoked `./bin/sb` from the worktree explicitly,
and confirmed the main checkout's `sb --help` matches. Two probes mutated nothing (`sb tell
human`, `sb ask human` both refuse before writing). I spawned no agents. One thing I could
not check directly: `sb inbox` and `sb status` *as the human* — I am an agent, so `whoami`
can never resolve to HUMAN for me; the human-side branches at `switchboard/cli.py:764-773`
were verified by reading only. The stale empty `.switchboard/state.db` in the main checkout
briefly misled me before I found the real store at `.git/agentflow/state.db`.

---

# Part B — the removed flags

# Audit 6 — Brief B: removed flags

Tree audited: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` (branch `worker-2`).
All line refs are from that tree unless stated. Checked against local `main`
(`caa6d20`) via `git show main:switchboard/cli.py` and the main checkout at
`/Users/andrew/Code/switchboard` — **the flag parsers are byte-identical there**, so main
does not fix any of this. Help output below was produced by running
`python3 -m switchboard.cli ... --help` **from the worktree** (not the PATH `sb`, which is
the main checkout).

Design truth audited: DESIGN-TRUTH.md:288-296.

---

### `--keep`
**Verdict:** BROKEN

**Evidence:**
- CLI: `switchboard/cli.py:136` — `d.add_argument("--keep", action="store_true", help="do not auto-close when finished")`. Confirmed live: `python3 -m switchboard.cli delegate --help` prints `--keep  do not auto-close when finished`.
- Dispatch: `switchboard/cli.py:720` — `cleanup = "keep" if args.keep else ("close" if args.ephemeral else None)`, passed to `b.delegate(..., cleanup=cleanup, ...)` (`cli.py:731`).
- Broker: `switchboard/broker.py:2488` (`cleanup: Optional[str] = None` on `delegate`); the disposition is enforced at `broker.py:3018` — `if a["cleanup"] != "close" and not (include_kept or names): continue`. `broker.py:583` and `:2113` and `:2166` hard-code `cleanup="keep"` for tops, workspace leads and adopted rows.
- Store: `switchboard/store.py:165` — `cleanup TEXT NOT NULL DEFAULT 'close'` column on the agents table; written by `add_agent`/`update_agent` (`store.py:793,819,850,867`) and exposed in the readable-field set at `store.py:980`.
- Config: `defaults/settings.toml:101` — `default_cleanup = "close"`, consumed by `switchboard/roles.py:51` into `Role.cleanup` (`roles.py:40`, propagated `roles.py:89`).
- Prompts: `defaults/roles/orchestrator.md:20`, `defaults/roles/worker.md:37-38`, `defaults/roles/qa.md:35-36`, `defaults/roles/reviewer.md:18-19`, `defaults/roles/researcher.md:25-26` all tell the reader the disposition is "set per spawn by `sb delegate --keep` / `--ephemeral`".

**Which of CLI / broker / store / config / prompts still contain it:** all five.

**Gaps:**
- `switchboard/cli.py:136` still registers `--keep` on `delegate`.
- `switchboard/cli.py:720` still maps it onto a `cleanup="keep"` disposition.
- `switchboard/store.py:165` still carries a per-agent `cleanup` column persisting the disposition.
- `switchboard/broker.py:3018` still lets a stored disposition veto a cleanup sweep.
- `defaults/settings.toml:101` still ships a `vocabulary.default_cleanup` key.
- `switchboard/roles.py:40,51` still gives every role a `cleanup` field.
- Five shipped role prompts still name `sb delegate --keep` as the way to set it.

---

### `--ephemeral`
**Verdict:** BROKEN

**Evidence:**
- CLI: `switchboard/cli.py:137` — `d.add_argument("--ephemeral", action="store_true", help="close as soon as it finishes")`. Live in `delegate --help`.
- Dispatch: `switchboard/cli.py:720` (same line as `--keep`) maps it to `cleanup="close"`.
- Broker/store/config: same `cleanup` machinery as above (`broker.py:2488,3018`; `store.py:165`; `defaults/settings.toml:101`; `roles.py:40,51`).
- Prompts: named alongside `--keep` in all five role files listed above (`orchestrator.md:20`, `worker.md:38`, `qa.md:36`, `reviewer.md:19`, `researcher.md:26`).

**Which of CLI / broker / store / config / prompts still contain it:** all five (store/config/broker via the shared `cleanup` disposition it writes, not a field of its own name).

**Gaps:**
- `switchboard/cli.py:137` still registers `--ephemeral` on `delegate`.
- Same shared `cleanup` disposition plumbing as `--keep` (store column, config default, broker veto).
- Same five shipped prompts name it.

---

### `--include-kept` (and its alias `--all-idle`)
**Verdict:** BROKEN

**Evidence:**
- CLI: `switchboard/cli.py:228-233` — `c.add_argument("--include-kept", "--all-idle", dest="include_kept", action="store_true", help="also close finished agents that were spawned to be kept")`. Confirmed live: `cleanup --help` prints `--include-kept, --all-idle`.
- Dispatch: `switchboard/cli.py:867` — `b.cleanup(args.name, include_kept=args.include_kept, ...)`.
- Broker: `switchboard/broker.py:2914` — `def cleanup(self, names=(), *, include_kept: bool = False, ...)`; used at `broker.py:3018` and documented at `broker.py:2935-2936`.
- Store: no `include_kept` field; it only exists because the `cleanup` column at `store.py:165` does.
- Config: no key of this name.
- Prompts: `grep -rn -- "include-kept\|include_kept\|all-idle" defaults/` returns nothing.

**Which of CLI / broker / store / config / prompts still contain it:** CLI and broker. (Store indirectly — the flag exists only to override `store.py:165`'s `cleanup` value. Config and prompts are clean.)

**Gaps:**
- `switchboard/cli.py:228` still registers `--include-kept` / `--all-idle` on `cleanup`.
- `switchboard/broker.py:2914` still takes an `include_kept` parameter, and `broker.py:3018` still branches on it.

---

### `--leave-children`
**Verdict:** BROKEN

**Evidence:**
- CLI: `switchboard/cli.py:238-240` — `c.add_argument("--leave-children", action="store_true", help="close an agent whose children are still working, leaving them running with no pane above them (--force does not do this)")`. Confirmed live in `cleanup --help`.
- Dispatch: `switchboard/cli.py:868` — `..., leave_children=args.leave_children, me=me)`.
- Broker: `switchboard/broker.py:2916` (`leave_children: bool = False`), documented `broker.py:2947`, and acted on at `broker.py:2978` — `held = {} if leave_children else {...}`, i.e. the flag empties the set of children that would otherwise hold a parent open.
- Store: no `leave_children` field.
- Config: no key.
- Prompts: `grep -rn -- "leave-children" defaults/` returns nothing.

**Which of CLI / broker / store / config / prompts still contain it:** CLI and broker only.

**Gaps:**
- `switchboard/cli.py:238` still registers `--leave-children` on `cleanup`.
- `switchboard/broker.py:2916,2978` still implement "close the parent, leave the children running".

---

### `--no-board`
**Verdict:** BROKEN

**Evidence:**
- CLI: two parsers still carry it.
  - `switchboard/cli.py:113-114` — `st.add_argument("--no-board", dest="board", action="store_false", help="do not open the clickable board beside it")` on `sb start`.
  - `switchboard/cli.py:256-257` — the same flag on `sb workspace new`.
- Dispatch: `switchboard/cli.py:711` (`b.start(..., board=args.board)`) and `cli.py:888` (`board=args.board` into `workspace new`).
- Broker: `board` is a real parameter threaded through every spawn path — `broker.py:477,515` (`start`/`_top`), `:564,587` (open or decline), `:825,843,885,888` (`workspace new`; the docstring at `:843` literally says "`board=False` declines it, as `sb start --no-board` does"), `:2081,2116`, and `:2495,2636` (`delegate`, where `if board:` gates `_open_board`).
- Store: no `board` column — `grep -n "board" switchboard/store.py` matches only an argparse prog string at `store.py:1456`. Not persisted.
- Config: no `board`-suppressing key; `defaults/settings.toml:317,327,335,340` are only board refresh/collector tuning.
- Prompts: `grep -rn -- "no-board" defaults/` returns nothing. The only doc mentions are code comments in `switchboard/board.py:4,40`.

**Which of CLI / broker / store / config / prompts still contain it:** CLI (two verbs) and broker (the `board` parameter on every spawn path). Store, config and prompts are clean.

**Gaps:**
- `switchboard/cli.py:113` still registers `--no-board` on `sb start`.
- `switchboard/cli.py:256` still registers `--no-board` on `sb workspace new`.
- `switchboard/broker.py:477,825,2495` still accept a `board` parameter, and `:564,888,2636` still branch on it — so a caller can suppress the board even with no CLI flag.
- Code comments at `switchboard/board.py:4,40` still describe `--no-board` as a supported way to decline.

---

### Focus as a flag
**Verdict:** BROKEN (two flags survive; the *behavioural* half of the rule is satisfied)

**Evidence — the flags that should not exist:**
- `switchboard/cli.py:112` — `st.add_argument("--no-focus", dest="focus", action="store_false")` on `sb start`. A way to *ask* about focus on spawn.
- `switchboard/cli.py:255` — `wn.add_argument("--focus", action="store_true")` on `sb workspace new`. This is the direct violation of "only `sb start` focuses on spawn, and nothing can ask for it": a non-`start` spawn path with an opt-in focus flag. Dispatched at `cli.py:888` (`focus=args.focus`) into `broker.py:824` (`focus: bool = False`), which reaches `self._focus(lead, focus)` at `broker.py:881,899`.
- `sb delegate` and `sb restore` have **no** focus flag (`delegate --help` shows none; `restore` parser takes only a name).

**Evidence — `sb start` DOES focus:**
- `switchboard/cli.py:112` defaults `args.focus` to `True` (`store_false`), passed at `cli.py:710` as `b.start(..., focus=args.focus, ...)`.
- `switchboard/broker.py:477` — `start(..., focus: bool = True, ...)` → `_top(...)` at `:492-493` → `switchboard/broker.py:566` and `:594` call `self._focus(name, focus)`, which at `:806-810` short-circuits on `not focus` and otherwise calls `self.h.focus(name)` → `herdr agent focus` (`herdr.py:508-510`).

**Evidence — spawn paths other than `start` do NOT focus:**
- `delegate` (`broker.py:2480-2497`) has no `focus` parameter at all, and `grep -n "self\._focus(" switchboard/broker.py` returns exactly four call sites: `566, 594` (start/`_top`) and `881, 899` (`workspace new`). None in `delegate`, none in `restore`.
- `restore` (`broker.py:3122-3160`) creates its pane through `_tab_for` and never focuses; its comment at `:3147` says so.
- Pane/tab creation defaults to no focus: `switchboard/herdr.py:256,283,297` default `focus: bool = False` and emit `--no-focus`; worktree create/open hard-code `--no-focus` (`herdr.py:345,364`).

**Which of CLI / broker / store / config / prompts still contain it:** CLI (`start --no-focus`, `workspace new --focus`) and broker (`focus` parameter on `start`/`_top`/`workspace new`, plus the `focus=` parameter on `herdr.py` tab/pane helpers). Store has no focus field. Config has no focus key. Prompts: `grep -rn -- "--focus\|no-focus" defaults/` returns nothing.

**Gaps:**
- `switchboard/cli.py:255` — `sb workspace new --focus` lets a non-`start` spawn ask to be focused; this is the rule's exact prohibition.
- `switchboard/cli.py:112` — `sb start --no-focus` is still a focus flag on the CLI surface.
- `switchboard/broker.py:824,881,899` still implement focus-on-spawn for the workspace lead.

---

## Summary

Six items, six verdicts: **0 SATISFIED, 0 PARTIAL, 6 BROKEN, 0 UNVERIFIED.** Every flag
DESIGN-TRUTH.md:288-296 says no longer exists is still registered in
`switchboard/cli.py`, still plumbed through `switchboard/broker.py`, and confirmed live in
`--help` output run from this worktree; local `main` (`caa6d20`) carries the identical
parser, so nothing here is a worktree-only staleness artifact. My three sharpest gaps:
(1) the `--keep`/`--ephemeral` disposition is not just a flag but a persisted schema column
(`store.py:165`), a shipped config default (`defaults/settings.toml:101`), a `Role` field
(`roles.py:40,51`) and a documented instruction in all five shipped role prompts — removing
the flags alone leaves four layers of dead state behind, and the prompts are the part
agents actually obey; (2) `sb workspace new --focus` (`cli.py:255`) is a live opt-in focus
flag on a spawn path that is not `start`, the precise thing the rule forbids — though the
behavioural half is genuinely correct, `start` focuses and `delegate`/`restore` provably do
not; (3) `--no-board` survives on two verbs *and* as a `board` parameter on every broker
spawn entry point (`broker.py:477,825,2495`), so suppressing the board stays reachable even
if the CLI flags go. Process notes: all checks were read-only — grep over the worktree plus
`python3 -m switchboard.cli <verb> --help` executed from the worktree, deliberately not the
PATH `sb` (which resolves to the main checkout); no agents were spawned; nothing was
modified. Nothing failed. One thing I could not check by execution: whether a *repo-local*
`.switchboard/settings.toml` or roles override anywhere on this machine reintroduces a
`cleanup` value — I only audited the shipped `defaults/`, as the brief scopes it.

---

# Part C — spawning, forking and merging

# Audit group 6 — brief C: spawning, forking, merging

All source refs are the worktree under audit,
`/Users/andrew/.herdr/worktrees/switchboard/worker-2/` (branch `worker-2`), unless a line
says otherwise. Runtime `sb` on PATH is `/Users/andrew/.local/bin/sb ->
/Users/andrew/Code/switchboard/bin/sb` (MAIN checkout); every runtime observation below is
labelled, and I checked `main` for the two places it could differ (`git show
main:defaults/settings.toml` line 305 and `git show main:switchboard/cli.py` — identical to
the worktree for `output_lines` and for `delegate`'s flags).

---

### 1. DESIGN-TRUTH.md:269 — "Andrew will never call the spawn and lifecycle commands himself, other than `sb start`. The surfaces that are his are the board, the session he types into, and `sb inspect`."

**Verdict:** PARTIAL

**Evidence:**

*The spawn/lifecycle set.* From the parser (`switchboard/cli.py:104-321`): spawn —
`start`, `delegate`, `workspace new`; lifecycle — `cleanup`, `restore`, `interrupt`,
`workspace close`, `done`, `block`, `wait`. Andrew's claimed surfaces: `board`
(`cli.py:117`), the session he types into, `inspect` (`cli.py:294-303`).

*The CLI is flat.* Ran (worktree) `python3 -m switchboard.cli --help`: one undifferentiated
list of 19 verbs — `start, delegate, ask, tell, inbox, done, block, status, presets,
plugin, models, init, doctor, cleanup, workspace, restore, interrupt, inspect, wait, log`.
Nothing in that listing says which are agent-only. The list is built from `visible` in
`cli.py:100-103`, and the only verb ever removed from it is `board` (`cli.py:117`, hidden
`cmd("board", hidden=True)`) — i.e. the one surface the truth says IS Andrew's is the one
surface `sb --help` never mentions.

*What is actually gated, and in which direction.* Only four identity gates exist, and three
of them run the other way:
- `board` refuses AGENTS (`cli.py:698-702`, `if me != broker_mod.HUMAN: ... "board is a
  human-only view"`).
- `done` refuses the human (`broker.py:2851-2852`, `raise ValueError("`sb done` is for
  agents")`), `block` likewise (`broker.py:2888-2889`).
- `inbox` special-cases the human with an explanatory message (`cli.py:764-772`); `tell`
  refuses the human as a TARGET (`broker.py:2678-2686`).

There is **no** gate, refusal or warning on `delegate`, `cleanup`, `restore`, `interrupt`,
`workspace new`, `workspace close` or `wait` when the caller is the human. Two of them are
positively BUILT for him: `cleanup` widens its scope to every agent in the store when
`me == HUMAN` (`broker.py:2957-2959`, `scope = self.db.execute("SELECT * FROM agents")`),
and `wait`'s own help says it is "for HUMANS, not agents" and tells agents not to use it
(`cli.py:305-315`) — the exact inverse of the claim. `sb delegate` from a human-run shell
is fully supported: `delegate` writes `parent=(None if me == HUMAN else me)`
(`broker.py:2582`).

*Docs/prompts/board.* `defaults/protocol.md` (what agents obey) hands agents `delegate`,
`status`, `cleanup`, `restore`, `done`, `block`, `inbox`, `tell` (lines 106-119) and never
mentions `board` — correct for agents, but it is not a human-facing surface statement. The
board itself is navigation only: `board.py` has three keys, `q`/`^C`, `r`, `a`
(`board.py:512-516`), no spawn or cleanup action — consistent with the claim. `sb status`
output points at `sb inspect` in four places (`status.py:1087, 1101, 1104, 1119, 1139`).

*`sb inspect` exists and does roughly what the surrounding truth says* — one agent, its
task/state/workspace/mail/last summary/events plus a terminal tail (`status.py:1209-1257`,
`render_detail` from `status.py:1284`), and it prints the block reason
(`status.py:1296-1297`, `blocked {a.blocked_why}`). Runtime check (MAIN checkout): `sb
inspect --help` prints the same three options as the worktree parser.

*The tail length is 40, not ~100.* `cli.py:301` `ins.add_argument("-n", ...,
default=status_mod.DEFAULT_LINES)`; `status.py:1163` `DEFAULT_LINES =
config.setting("display.output_lines")`; `defaults/settings.toml:305` `output_lines = 40`.
Same value on `main`.

**Which of CLI / broker / store / config / prompts reflect the claim:** CLI — barely (only
`board` hidden + agent-refused; `wait` marked human-only, which contradicts). Broker —
contradicts (human-scoped `cleanup`, human-parented `delegate`). Store — n/a. Config —
nothing. Prompts — agent-side only; nothing states Andrew's surfaces.

**Gaps:**
- Nothing hides or marks `delegate`, `cleanup`, `restore`, `interrupt`, `workspace` as
  agent-only in `sb --help`; the verb list is flat (`cli.py:100-103, 318-320`).
- No refusal or warning when the human runs `delegate` / `cleanup` / `restore` /
  `interrupt` / `workspace new|close`; the claim holds by convention only.
- `broker.cleanup` gives the human a store-wide scope (`broker.py:2957-2959`), which is a
  feature built for a caller the truth says never calls it.
- `wait` is explicitly documented as the human's verb (`cli.py:305-315`), directly against
  "the surfaces that are his are the board, the session, and `sb inspect`".
- `board` — one of Andrew's three surfaces — is suppressed from `sb --help`
  (`cli.py:117`), so nothing points him at it.
- `sb inspect` tail defaults to 40 lines, not the "like 100" the truth asks for
  (`defaults/settings.toml:305`).

---

### 2. DESIGN-TRUTH.md:192 — "`sb delegate` figures out where a spawn lands rather than the caller passing flags for it. The top can spawn a space with either an orchestrator or a single worker."

**Verdict:** PARTIAL

**Evidence:**

*Flags `sb delegate` accepts* (worktree run of `python3 -m switchboard.cli delegate
--help`, matching `cli.py:119-140`): `task`, `--role`, `--as`, `--with`, `--name`,
`--workspace NAME`, `--model`, `--keep`, `--ephemeral`, `--json`. Of these exactly one is a
placement flag: `--workspace NAME`, "join this EXISTING workspace instead of working where
you are" (`cli.py:132-135`). There is no `--worktree`, `--branch`, `--here`, `--new-space`
or `--base` on `delegate`.

*Real derivation logic exists.* `broker.delegate` (`broker.py:2479-2545`):
- `inherited = workspace is None` (`:2504`), then `ws = self._workspace_of(me)` — a child
  inherits its parent's workspace with nobody passing it (`:2506`).
- THE FORK RULE (`:2514-2531`): `if inherited and not self.has_worktree(me): forked =
  self._fork_for(name, parent=me)`. `has_worktree` is read from `agents.branch`
  (`broker.py:2224-2238`) and answers False for the human and for a bare space.
- `_fork_for` (`broker.py:2433-2463`) branches on the CHILD'S NAME and attaches a
  workspace; a colliding branch raises `BranchTaken`, any other failure is non-fatal and
  the child lands in the parent's space.
- `--workspace` is resolved to those same internal placement keywords by
  `join_workspace` (`broker.py:902-935`) and passed as `**join` (`cli.py:727-731`), so
  there is one spawn path, not two.

*The top's spawn does produce a space.* `sb start` → `_top` makes a BARE herdr workspace
over the main checkout, no worktree (`broker.py:475-492`, `_record_workspace(name, None)`
at `:540`) — matching DESIGN-TRUTH.md:35. So `has_worktree(top)` is False, and the top's
first `delegate` takes the fork branch and creates a worktree/space
(`broker.py:2531-2543`).

*Orchestrator-or-single-worker is chosen by `--role`*, defaulting to `worker`
(`cli.py:121`, `DEFAULT_ROLE` = `broker.py:83` ← `defaults/settings.toml:87
default_role = "worker"`; `workspace_role = "orchestrator"` at `:95`). Both produce the
same fork; only the prompt differs (`defaults/roles/orchestrator.md`,
`defaults/roles/worker.md`).

**Which of CLI / broker / store / config / prompts still let the caller decide placement:**
CLI — `sb delegate --workspace` (`cli.py:132`) and `sb workspace new --base` (`cli.py:253`).
Broker — placement kwargs `workspace`/`branch`/`workspace_id`/`cwd`/`pane` on
`delegate` (`broker.py:2490-2494`), internal but callable. Store — `agents.branch` is the
derivation input, correct. Config — role defaults only. Prompts — `protocol.md:112` teaches
`sb delegate "<task>" --role <role>` with no placement flag, consistent with the claim.

**Gaps:**
- `--workspace NAME` is a caller-passed placement flag on `delegate` (`cli.py:132-135`);
  the claim as written says placement is figured out, not passed.
- Placement is derived from the PARENT's worktree only (`broker.py:2531`), never from the
  role: an orchestrator and a single worker spawned from the top are placed identically,
  so "either an orchestrator or a single worker" is a role-prompt difference, not a
  placement one.
- Nothing enforces the related rule at DESIGN-TRUTH.md:35 that a top-spawned bare/single
  worker "cannot spawn other agents": `protocol.md:112` teaches every agent to delegate,
  and `defaults/roles/worker.md:54-55` only advises against it — no code gate in
  `broker.delegate`.

---

### 3. DESIGN-TRUTH.md:255 — "A workspace forks from `origin/main` by default."

**Verdict:** SATISFIED

**Evidence:** The default is the literal string: `defaults/settings.toml:111
base_branch = "origin/main"`, read into `broker.py:81 BASE_BRANCH =
config.setting("vocabulary.base_branch")`, and used as the default of
`_attach_workspace(..., base=BASE_BRANCH)` (`broker.py:1887`) and `workspace_new`
(`broker.py:823`). The fork path calls `forked_from, fallback = self._fork_base(base)` then
`self._call_adapter("create_worktree", branch, base=forked_from, cwd=str(self.repo))`
(`broker.py:1918-1923`). `_fork_base` (`broker.py:1940-1979`) fetches first —
`self._git("fetch", remote, ref, check=True)` at `:1970` — and forks from the
remote-tracking ref `origin/main` after verifying it (`:1974`). It is HEAD-independent and
current-branch-independent: `_git` runs with `cwd=str(self.repo)` and never reads HEAD
(`broker.py:2000-2013`). Documented fallbacks, both logged: fetch failed but `origin/main`
present → fork from the stale remote ref, event `fetch_failed` (`:1970-1973`); no remote or
no such remote ref → fork from LOCAL `main`, events `no_remote` / `base_fallback`
(`:1965-1978`). The fallback is recorded on the workspace so a stale fork is visible
(`broker.py:1880-1884`, `"base"`, `"base_fallback"`).

**Overridability, and consistency with claim 2:** only `sb workspace new --base`
(`cli.py:253-254`, validated at `cli.py:392`). `sb delegate` has no `--base`, so the
derived-placement path never lets a caller choose the fork point — consistent with claim 2.

---

### 4. DESIGN-TRUTH.md:257 — "Who merges depends, but merging needs explicit approval from Andrew."

**Verdict:** BROKEN

**Reasoning:** the claim is a guarantee about a gate. switchboard has no merge feature at
all, and — more to the point — no approval mechanism of any kind that a merge could be
gated behind, so the guarantee is unenforced and unstated everywhere an agent would read
it. That is a real gap, not an absence of evidence, which is why this is BROKEN rather than
UNVERIFIED. Nothing here is a claim that agents are *told* to merge — they are not.

**Evidence:**
- No merge verb. The full verb list (`cli.py:100-321`, and the runtime `sb --help`) has no
  `merge`, `push`, `land`, `pr` or `approve`. `grep -rni "merge|git push|pull request"` over
  `switchboard/*.py bin/sb defaults/` returns only: config-table merging
  (`config.py:189-198`, `models.py:219-245`), the workspace listing's `git branch --merged`
  read (`broker.py:1070-1085`), and one prose mention.
- No approval mechanism. `sb block` (`cli.py:797-801`, `broker.py:2884-2900`) is the only
  human-facing gate in the product, and nothing anywhere ties it to merging or pushing.
  No hooks exist in source or defaults: `grep -rn "hook"` over `switchboard/*.py` and
  `defaults/settings.toml` yields one unrelated comment (`cli.py:1051`) — whatever
  HOOKS.md describes is not implemented here.
- Agents are not stopped from merging or pushing themselves either. Nothing in the broker
  restricts what an agent runs in its worktree; the only git safety net is on teardown,
  `git branch -d` and never `-D`, so an unmerged branch survives workspace close
  (`broker.py:1379-1389`).
- Shipped prompts do NOT tell agents to merge. `grep -rni "push|commit|approv|merge"` over
  `defaults/`: `protocol.md:106-107` says "commit your work, then call `sb done`" (commit,
  not push, not merge); `defaults/roles/researcher.md:32` echoes the commit rule;
  `defaults/roles/orchestrator.md:123` mentions merges only as a reason to keep parallel
  writers off the same files. No prompt mentions pushing, merging, or asking Andrew for
  approval.
- Note the adjacent, unmet half: DESIGN-TRUTH.md:250-251 says "the push is the recovery
  path for the work, not restore", and `defaults/settings.toml`/prompts never instruct a
  push — so work in an aggressively cleaned-up worktree has no recorded escape route.

**Which of CLI / broker / store / config / prompts contain a merge or approval:** none of
the five. CLI has no verb, the broker has no path, the store has no state for it, config
has no setting, and the prompts say nothing about merging or approval.

**Gaps:**
- No approval gate exists that merging could be routed through; `sb block` is not tied to
  it anywhere in source or prompts.
- No prompt tells an agent that merging (or pushing to main) requires Andrew's approval,
  so the rule is invisible to the only parties that would break it.
- Nothing decides or records "who merges" — there is no owner field, event kind, or verb.
- The push that DESIGN-TRUTH.md:250 makes the recovery path is never instructed in
  `defaults/protocol.md`, so aggressive cleanup can destroy uncommitted-to-remote work.

---

## Summary

Four items: **1 SATISFIED** (fork-from-`origin/main`), **2 PARTIAL** (Andrew's surfaces;
`delegate` placement), **1 BROKEN** (merge approval), 0 UNVERIFIED. Sharpest three gaps:
(1) merging has no approval gate and no mechanism anywhere in the product — the shape of
the guarantee simply does not exist, and no shipped prompt states the rule; (2) the CLI is
flat, so "these commands are not Andrew's" is pure convention — worse, `cleanup` is
store-wide FOR the human (`broker.py:2957`), `wait` is documented as the human's verb
(`cli.py:305`), and `board`, one of his three surfaces, is hidden from `sb --help`
(`cli.py:117`); (3) `sb inspect` shows a 40-line tail where the truth asks for ~100
(`defaults/settings.toml:305`), which is exactly the readout used to read a blocked agent's
full message. Process notes: everything above is source reading plus non-mutating runs
(`--help` in both trees, `git show main:<path>` comparisons); I spawned nothing. The two
things I could not check by running: fork behaviour end-to-end (it needs a real spawn, so
`_fork_base` is evidenced by source only), and `sb inspect` against a live blocked agent
(same reason — the 40-line default is read from config, not observed truncating).
