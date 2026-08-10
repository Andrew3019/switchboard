# AUDIT 2B — FINDINGS: tell-only, and who tell is for

Tree audited: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` @ `a9dd319` (branch `worker-2`).
`git diff origin/main..HEAD -- switchboard/cli.py switchboard/broker.py defaults/protocol.md`
is **empty** — local `main` (`caa6d20`) has the same code, so nothing below is "already fixed on main".
The `sb` on PATH is `/Users/andrew/Code/switchboard/bin/sb` (a different checkout); every run below
was done with the worktree's own `./bin/sb`, and its `--help` output matches this tree.

Verdicts: **0 SATISFIED · 1 PARTIAL · 1 BROKEN**

---

## Entry 1 — "There is `tell` only. No agent ever waits on another agent." (DESIGN-TRUTH.md:212–214)
Related confirmed rejections: **`sb ask`** (283), **`sb wait`** (285), **`sb interrupt` as a verb** (287).

### Verdict: BROKEN

All three rejected verbs are present, wired, documented and shipped to agents.

**`ask` — a blocking agent-to-agent verb, exactly what the entry rejects**
- `switchboard/cli.py:139` `a = cmd("ask", help="send a question and WAIT for the answer")`
- `switchboard/cli.py:370-373` validation branch; `switchboard/cli.py:739-740` `b.ask(...)`
- `switchboard/broker.py:2713` `def ask(...)` — its docstring at 2718-2721 says "Send and block
  until every target answers … For AGENTS only, and it is the only blocking verb."
- Blocking loop: `broker.py:2757-2789` (`while time.time() < deadline: … time.sleep(poll)`)
- Config for it: `broker.py:101-103` `ASK_TIMEOUT` / `ASK_POLL`; `defaults/settings.toml:213`
- Ran: `./bin/sb ask --help` → `usage: sb ask [-h] [--json] [--timeout TIMEOUT] who [who ...] question`

**`wait` — present as a verb**
- `switchboard/cli.py:304-315` `cmd("wait", help="block until an agent reaches a state (for HUMANS,
  not agents)")`; dispatch at `cli.py:911-914`
- `switchboard/status.py:1437` `def wait_for(...)`; `defaults/settings.toml:141, 239, 242`
- The design entry is unconditional ("It has no reason to exist"); the code's justification
  ("for humans, not agents") is a rationale the entry does not grant.

**`interrupt` — present as a verb, not as a delivery mode of `tell`**
- `switchboard/cli.py:288-290` `i = cmd("interrupt", help="change an agent's course mid-flight")`;
  dispatch `cli.py:897-899`
- `switchboard/broker.py:3184` `def interrupt(...)`; its docstring at 3187-3191 argues explicitly
  "**Not a variant of `tell`**", which directly contradicts DESIGN-TRUTH.md:287.
- `./bin/sb tell --help` shows **no** delivery-mode flag of any kind: only `who`, `message`,
  `--json`, and the hidden `--re` (`cli.py:148-151`). So there is no mode for interrupt to be.

**Shipped agent-facing text tells agents to use `ask`**
- `defaults/protocol.md:103-105`: "`sb ask <who> \"<question>\"` sends to another agent and WAITS
  for its answer — for agents only, and only when the answer is seconds away."
- `switchboard/cli.py:3` module docstring: "Seven verbs for agents (`delegate`, `ask`, `tell`, …)"

**`--needs-reply` does not exist**
- `grep -rl "needs.reply"` across the whole repo (excluding `.git`) matches **DESIGN-TRUTH.md only**.
  Nothing in `switchboard/`, `bin/`, `defaults/`, or `tests/`. `./bin/sb tell --help` has no such flag.
- So the replacement mechanism the entry describes is entirely unbuilt: today an agent that needs an
  answer has only the rejected `ask`.

### Gaps (one line each)
1. `sb ask` exists as a blocking verb — remove the subcommand (`cli.py:139-146, 370-373, 739-748`).
2. `Broker.ask` and its poll loop still exist (`broker.py:2713-2789`) along with `ASK_TIMEOUT`/`ASK_POLL` (`broker.py:101-103`, `defaults/settings.toml:213, 226`).
3. `sb wait` exists (`cli.py:304-315, 911-914`) plus `status.wait_for` (`status.py:1437`) and `timeouts.wait*` settings (`defaults/settings.toml:141, 239, 242`).
4. `sb interrupt` exists as its own verb (`cli.py:288-290, 897-899`; `broker.py:3184`) instead of a delivery mode of `tell`.
5. `sb tell` has no delivery-mode flag at all (`cli.py:148-151`) — next-turn/when-idle/interrupt are not selectable.
6. `tell --needs-reply` is unimplemented anywhere in the codebase — the static "you must reply at some point" prompt does not exist.
7. `defaults/protocol.md:103-105` instructs every agent to use `sb ask` and wait — shipped text teaching a rejected verb.
8. `switchboard/cli.py:3-11` and `broker.py:9-25` document `ask`/`wait`/`interrupt` as load-bearing distinctions, so removal means rewriting those headers too.
9. `store.pending_ask` / `reply_to_ask` / `mark_collected` correlation machinery (`broker.py:2687-2708`, `2769`) exists to serve `ask` and needs a decision on removal.
10. ~59 test references to `ask(`/`wait_for(`/`interrupt(` across `tests/` will need rewriting with the verbs.

---

## Entry 2 — "`sb tell` is for agents only, both ways round." (DESIGN-TRUTH.md:229-231)

### Verdict: PARTIAL

**The "cannot address a human" half is SATISFIED, and enforced in code, not just documented.**
- `switchboard/broker.py:2676-2685`: `if t == HUMAN: raise ValueError("the human has no mailbox — a
  message to them would never be read. Use \`sb block …\`")` — raised before any row is written.
- Ran `./bin/sb tell human "audit probe"` →
  `sb: the human has no mailbox — a message to them would never be read. Use \`sb block "<why>"\` …`
  (Nothing written; the guard is before `store.put_message`.) `sb ask human` is refused likewise at
  `broker.py:2739-2745`.
- `defaults/settings.toml:71` records `human` as a non-target for both verbs.
- Agent-facing text is consistent: `defaults/protocol.md` (block is "the ONLY way to reach a human"),
  `defaults/roles/worker.md:52`.

**The "Andrew does not use it" half is BROKEN — the code repeatedly makes `sb tell` the human's verb
for answering a block, and even sends tells as the human.**
- `switchboard/cli.py:161` — the `block` subcommand's own help: *"stop and surface to the human
  (**they answer with `sb tell`**)"*. This is the human being handed `tell`.
- `switchboard/broker.py:2884` — `"The human answers with \`sb tell <agent> \"...\"\`, which rings the
  doorbell …"` in `block`'s documentation of the flow.
- `switchboard/status.py:1084`, `:1140`, `:1316` — the `status`/`--needs-me` surface prints
  `→ sb tell <name> "..."`, `sb tell <name> "wrap up and run sb done"`, `sb tell <name> "answer …"`
  as the suggested human next action.
- `switchboard/cli.py:771` — the human typing `sb inbox` is told: *"answer with `sb tell <agent>
  \"...\"`"*.
- `switchboard/cli.py:715`, `broker.py:3140`, `broker.py:3210` — more human-facing `sb tell …` hints.
- `switchboard/broker.py:562` — `self.tell([name], task, me=HUMAN)`: the broker writes messages whose
  **sender is the human**, so `tell` is not agents-only in the from-direction either. Same shape with
  `me=` a human caller at `broker.py:878, 2094, 2135`.
- There is **no** guard on the sender side: `Broker.tell` checks only the target (`broker.py:2676`),
  never `me == HUMAN`.

DESIGN-TRUTH.md:279-283 also says the human inbox is 100% removed and (203-206) that after a block
"the agent just continues" — but no code path other than `sb tell` is offered for the human to send
that answer, so removing the human's use of `tell` needs a replacement decision, not just a deletion.

### Gaps (one line each)
1. `cli.py:161` block help names `sb tell` as the human's reply verb — contradicts "Andrew does not use it".
2. `status.py:1084, 1140, 1316` print `sb tell …` as the human's suggested action on the board/needs-me surface.
3. `cli.py:715` and `cli.py:771` hint `sb tell` to a human caller.
4. `broker.py:2884, 3140, 3210` document/emit `sb tell` as the human's route.
5. `Broker.tell` has no sender-side human guard (`broker.py:2670-2685`), and `broker.py:562` sends with `me=HUMAN`.
6. No decided replacement exists for how Andrew answers a block if `tell` stops being his — this is a design gap, not just a code one.

---

## Process notes
- Read-only throughout; no code or docs changed, nothing spawned, nothing written inside the repo.
- Two mutating-looking probes (`sb tell human`, `sb ask human`) were run deliberately: both are
  refused before any store write, verified by reading the guards first.
- Both refusals exit **1** with `sb: …` — correct behaviour, no issue.
- No `sb` bug encountered; the CLI behaved as its source says.
