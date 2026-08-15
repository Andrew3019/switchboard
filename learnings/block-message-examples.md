# Real pre-`sb block` messages, recovered from transcripts

Task: find real examples of the human-facing message an agent writes as the last
message in its own chat right before calling `sb block`, and check whether they
actually follow the format rule (numbered questions, recommended answers, bullets,
skimmable).

## Where transcripts live (verified, not guessed)

- `switchboard/store.py:1687` (`transcript_dir`) and `:1700` (`transcript_path`):
  each agent's Claude Code transcript is at
  `~/.claude/projects/<cwd-with-non-alnum-replaced-by-dashes>/<session_id>.jsonl`.
  The STORE's `state.db` records `cwd` and `session_id` per agent
  (`store.py:147`) and that's the only join key — the transcript itself carries
  no agent name or role.
- There is no separate "per-agent transcript" kept by switchboard itself; it
  relies entirely on the Claude Code `.jsonl` files, which is what
  `transcript_path` reads.
- Each `.jsonl` line is a JSON event (`type`: `user`, `assistant`, `attachment`,
  etc.). An `sb block` call shows up as an `assistant` event containing a
  `tool_use` block with `name: "Bash"` and an `input.command` starting with
  `sb block "..."` or `./bin/sb block "..."`.
- Agent name recovery: the transcripts do **not** log the injected system
  prompt (no "You are agent 'X'" string appears anywhere), so there is no
  reliable in-transcript agent name. What I report below is the **worktree/
  workspace directory name** the transcript file lives under (e.g.
  `switchboard-fix-fork-branch` → workspace `fix-fork-branch`), which by the
  protocol is usually the agent's own name for a delegated/forked agent, but
  is a best-effort inference, not a verified agent name.

## Method

Scanned all 1042 directories under `~/.claude/projects/`. Grepped every
`.jsonl` for an `assistant` `tool_use` (`Bash`) event whose command matches
`^(\./bin/)?sb\s+block\b` (top-level, not embedded in a delegated child's task
text or a documentation quote — that filter cut out a lot of false positives,
e.g. an orchestrator delegating a child with instructions that say "then
`sb block` yourself" is not this agent's own block call). For each real match,
took the `text` blocks in the same assistant turn (or, if empty, walked
backward to the nearest prior assistant turn with text) as the pre-block
message. 74 real `sb block` invocations survived the filter; ~40 had a
substantial (>150 char) pre-block message worth reading. Below are 8 distinct
ones spanning different situations (decision needed, harness limitation,
handover, doc conflict, awaiting task, accidental pane close, permission
refusal, role refusal).

## Examples

### 1. `teardown-fix` — spec self-contradiction, needs a numbered decision
> Everything but the load-time assertion is done, committed, and the full
> suite passes. The assertion as specified can't be satisfied, so I need a
> decision: [...] Which do you want? (1 is my recommendation.)
> 1. Assert timeouts.gone_grace >= SPAWN_GRACE at load, and raise gone_grace
>    from 60 to >= 287 in defaults/settings.toml so it holds. [...]
> 2. Keep my window at 60s and assert the direction that is satisfiable [...]
> 3. Raise gone_confirm_grace to >= 287s and assert exactly as my task words
>    it. The doc explicitly rejects this [...]

`sb block "Stage 4a (liveness debounce) is built and committed as 25a777e — ..."`

### 2. `delivery-experiment` (top orchestrator) — deliberate handover, no question at all
> I was asked to be the top orchestrator for a measurement experiment: spawn
> exactly three worker children from a shared task file, then stop and hand
> control to whoever is running the experiment.
>
> All three are now running: subject-one, subject-two, and subject-three. [...]
>
> I am deliberately doing nothing further. [...] There are no questions for
> you and no decision I am holding back — this is a handover, not a blocker
> in the usual sense.

`sb block "experiment subjects running; the experimenter drives from here"`

### 3. `fix-doorbell-path` — harness limitation, one line
> The foreground `sleep 200` is blocked by the harness sandbox, and every
> substitute I can think of changes what this test is measuring. Writing up
> the decision for you and blocking.

`sb block "harness blocks foreground sleep 200; need a call on the substitute"`

### 4. `fix-fork-branch` — DESIGN-TRUTH conflict, three numbered questions with recommendations
> I have the facts I need. Before writing code I have to resolve a conflict
> with `DESIGN-TRUTH.md`, which the brief reserved for the human.
>
> **need human input: changing what a delegated child forks from contradicts
> a confirmed DESIGN-TRUTH entry**
>
> **What I found (facts, not proposals)**
> - The fork only ever happens on one path: `Broker.delegate` → `_fork_for` →
>   `_attach_workspace(name)` (`switchboard/broker.py:2748`, `:2669`). [...]
>
> **Questions**
> 1. **Does entry 279 yield to "a delegated child forks from the branch its
>    parent's checkout is on"?** *Recommended: yes, narrowed rather than
>    replaced.* [...]
> 2. **Uncommitted work in the parent's checkout.** [...] *Recommended: fork
>    from the committed tip, and say so.* [...]
> 3. **Is "top-level orchestrator starting fresh still wants `main`" a case
>    that needs its own answer?** *Recommended: no.* [...]

`./bin/sb block "need a decision: forking children from the parent's branch contradicts DESIGN-TRUTH:279"`

### 5. `worker-24` (clone) — genuinely no task yet
> **Where I stand**
> - You told me to await your instructions; I have no task yet.
> - I've taken no actions and spawned no agents.
>
> **Question**
> 1. What would you like me to work on? (No recommendation possible — I have
>    nothing to go on yet.)

`sb block "awaiting task from Andrew"`

### 6. `worker-25` — accidental pane close during otherwise-finished work
> **What you asked for (via board-fix)** [...]
> **Done, committed `0305804` on `worker-25`**
> - Second dim line removed — one row per agent, like the real board.
> - [...] every marker word and mail count survive down to 32 columns [...]
> Cost of the rule, visible on live data: [...]

`sb block "closed your right pane by accident; need a split re-created or a go-ahead"`

### 7. `finish-1-3` — permission classifier refused a real action, terse writeup
> Everything that could be done without the blocked permissions is done.
> Writing up for a human.
> ---
> ## Where this stands
> **Done**
> - **PR #20 (`small-fixes`)** — verified mergeable, `CLEAN`. **Not merged**
>   (see below). [...]

`./bin/sb block "permission classifier denies gh pr merge and git worktree remove"`

### 8. `live-mpq7k-kid` — role-permission refusal, two numbered questions with recommendations
> **What I was asked** [...]
> **What happened**
> I ran it verbatim. It failed, exit code 1: [error quoted] [...]
> **Questions**
> 1. Do you want the delegate run from an agent that has delegate rights
>    instead [...]? — *Recommended: yes, that's the intended path [...]*
> 2. Or is this refusal itself the thing you were testing, in which case
>    nothing further is needed? — *If so, no action; I'll close out.*
>
> I'm not taking either path without your say-so, since both are decisions
> about the agent tree that weren't mine to make.

`sb block "delegate refused: worker role lacks delegate rights"`

## Did they follow the format rule?

Mixed, and roughly split by whether there was an actual decision to ask about.

- **When there's a real decision** (examples 1, 4, 8, and several others seen
  but not excerpted, e.g. multi-question landing blockers under
  `Users-andrew-Code-switchboard`), the format rule is followed closely:
  numbered questions, each with an explicit `*Recommended: ...*` line, bold
  headers separating "what I found" from "questions," and bullets for
  supporting facts. This is the dominant, well-established pattern.
- **When there's no real decision** — a pure handover (#2), a status report
  with nothing to ask (#7), or "I have literally no task" (#5) — agents
  correctly skip the numbered-question machinery rather than manufacturing a
  fake question, but still keep it skimmable: short bolded state line, plain
  bullets, one line of "nothing needed from you" or a single unavoidable
  question. This looks like the right degradation, not a rule violation: the
  rule is "numbered questions with recommended answers" for when there are
  questions, and these agents didn't invent one to force the shape.
- **Terse one-liners** (#3, and many of the "WOKEN by the doorbell" /
  "awaiting instructions" messages seen during the scan) skip structure
  entirely — a single sentence, no bullets, no headers. These are still
  skimmable by virtue of being short, but they're the cases furthest from the
  documented "numbered, recommended-answer" ideal; whether that's fine depends
  on whether a human reading only the summary would have enough to act on
  (for "harness blocks X" it's borderline — the full reasoning was in the
  `sb block` argument string itself, not in the pane message).
- No example found where an agent asked an *unnumbered* pile of questions or
  omitted a recommendation while still posing multiple real decisions — the
  numbered+recommended shape seems to hold reliably once there's more than one
  live question.

## Caveats / what's unverified

- Agent names above are inferred from worktree directory names, not read from
  any transcript field — I did not find agent identity logged in the `.jsonl`
  files themselves. Treat the names as "workspace" not "confirmed agent name."
- I did not cross-reference against `state.db` to confirm these agents'
  recorded role/parent, since the STORE for most of these worktrees is long
  torn down; this is transcript-only evidence.
- Scan was regex-based over Bash tool commands; it would miss an `sb block`
  invoked through a different tool path (none observed, but not proven
  impossible) and any transcript that predates or falls outside
  `~/.claude/projects/`.
