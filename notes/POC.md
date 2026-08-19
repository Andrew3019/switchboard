# Proof of concept — M1 ∪ M2 ∪ M3

Scope for review. Everything else attaches to this later without redesign.

**Goal:** an agent can spawn a second agent, hand it a task, block until it reports back —
and both transcripts are irrelevant, because the store alone says what happened.

**Not in the PoC:** templates, gates, learnings, plugins, skills, web UI, Codex.

> **Reading this after the fact.** This document was written as the design was being
> settled and then built. Findings that turned out to be wrong are marked **RETRACTED**
> rather than deleted — the wrong turns are the useful part. Two global corrections apply
> throughout and are not repeated at every mention:
>
> - **The command is `sb`, not `wf`.** `wf` was always a placeholder, and nothing
>   depended on it. Read every `wf x` below as `sb x`.
> - **Plugins and skills ARE in, and Codex is not.** What shipped in M3 as `--with`
>   "plugins" is now called **presets** (`switchboard/presets.py`) — prompt text, no code.
>   The word "plugin" was later taken for the other thing: Python that sb imports
>   (`switchboard/plugins.py`, `sb plugin <name> <verb>`), which shipped after the PoC.
>   Read every "plugin" below as **preset** unless it is herdr's plugin system being
>   discussed. Either way the "not in the PoC" line above is out of date on that item.
>
> Everything else that has moved is marked where it sits.

---

## Verified answers

Two design questions were resolved by checking, not guessing.

### Identity — use the agent's own session id

`CLAUDE_CODE_SESSION_ID` is already present in a Claude Code session's environment (with
`CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_PID`, `AI_AGENT`). **We don't mint or inject IDs.**

This inverts registration in a useful way: instead of us assigning an id at spawn, the
agent **self-registers** on first `wf` call using the id it already has. Consequences:

- An agent started by hand — not spawned by us — is still addressable.
- No env plumbing through the spawn path.
- No divergence between "the id we think it has" and "the id it reports".

*Open for Codex:* unverified whether it exposes an equivalent env var. Check when adding
Codex; worst case that one backend falls back to an injected id, entirely inside M2.

> **PARTLY RETRACTED — identity is the PANE, not the session.** The "don't inject, don't
> mint" half stands, and so does everything about self-registration being better than
> spawn-time env (finding #16 below is the evidence). What changed is which pre-existing
> id is used. `Broker.whoami` matches on **`HERDR_PANE_ID`**, which herdr injects into
> every pane: it is there from the first instant, whereas the session id only lands once
> the agent has made a call, so a session-keyed lookup would return `human` for an agent's
> very first `sb` invocation — and being attributed to the human is the failure mode QA
> found (B1) when it happened for a different reason.
>
> The session id is still recorded (`Broker._claim_session`) and still load-bearing: it is
> what `sb restore` resumes and what locates the on-disk transcript. It is just not the
> identity key. `store.agent_by_session` is the reverse lookup, and has no caller today.

### herdr's `blocked` is real and settable

```
herdr pane report-agent <pane_id> \
  --state (idle|working|blocked|unknown) \
  --message TEXT --seq N \
  --agent-session-id ID  --agent-session-path PATH
```

- **`blocked` is first-class** — we don't invent a status, we set theirs.
- **`--agent-session-id`** links the pane to `CLAUDE_CODE_SESSION_ID`. One identity from
  our store through herdr to the agent.
- **`--seq N`** is the `state_change_seq` that makes `agent wait` turn-scoped and therefore
  trustworthy `[01]`.
- Related: `report-agent-session`, `release-agent` (on cleanup), and `report-metadata`
  (`--state-label`, `--token NAME=VALUE`) for sidebar rendering later.

**How it's set today, and why we override:** herdr's default detection is regex over the
agent's TUI — matching the spinner, `"do you want to proceed?"`, the `❯` prompt box `[01]`.
Calling `report-agent` takes **authoritative** state ownership, so state stops being
guessed from pixels (C5).

---

## M1 — Store

**Location:** `$(git rev-parse --git-common-dir)/agentflow/state.db`, WAL mode.

`.git` is already shared across every worktree of a repo, so one store is automatically
visible from all workspaces — which is required, since the top-level orchestrator lives on
`main` while its children live in worktrees. No config, no registry, can't be committed by
accident, and it dies with the repo. **`wf` resolves this path; agents never see it** (P0).

**Scope: per repo. There is no global store.** The top-level orchestrator is just the root
agent (`parent_id NULL`) of that repo's store. Cross-repo orchestration doesn't exist in v0.

**No migrations.** Everything here is *operational* state — agents, messages, events. The
only durable data (learnings) lives in JSON files, so **the DB is disposable by
construction**. On schema change: if no agents are live, drop and recreate; if any are
live, refuse and say so. Ten lines instead of a migration framework.
*Rule that keeps this true: never put anything precious in this DB.*

> **RETRACTED in practice — "drop, or refuse" is a deadlock, and it happened.** The
> disposability argument is still right and the DB still holds nothing precious. But
> "refuse while agents are live" cannot be the whole story, because `connect()` is the
> first thing EVERY command does — including the `sb done` an agent would have to run to
> stop being live. Adding one nullable column wedged seven live agents at once and the
> only way in was herdr directly. Worse, the trigger is a hash of the SCHEMA string, so
> editing a *comment* in it was enough.
>
> What ships instead (`store.connect`, `store._migrate_additive`): added nullable columns
> are applied in place with `ALTER TABLE` and the hash is restamped — no reset, no
> refusal. Only a genuinely incompatible change (a dropped column, a new table, a NOT NULL
> with no literal default) falls through to a reset, the liveness check asks **herdr**
> rather than the store's own drifting `state` column, and `sb doctor --reset-store
> --force` is the way out. A non-additive change while agents are live is still a hard
> stop; that one is open.

The only shared state; modules meet here and nowhere else (C7).

```sql
-- As designed. The shipped schema is store.SCHEMA; the differences are noted below it.
agents(
  id            TEXT PRIMARY KEY,   -- CLAUDE_CODE_SESSION_ID (self-registered)
  parent_id     TEXT,               -- NULL = root. Tree, not graph (C1). No edges table.
  role          TEXT,               -- free text. Vocabulary is data (C12)
  task          TEXT,
  state         TEXT,               -- working | blocked | done | failed
  herdr_terminal_id TEXT,           -- STABLE handle. NOT pane_id (changes on move)
  herdr_name    TEXT,               -- best practical addressing key for CLI calls
  seq           INTEGER,            -- OUR --seq: guards WRITES. Plain counter, per agent
  last_seen_seq INTEGER,            -- THEIR state_change_seq: guards READS (stale waits)
  created_at    INTEGER,
  ended_at      INTEGER
);

messages(
  id            INTEGER PRIMARY KEY,
  from_agent    TEXT,
  to_agent      TEXT,
  kind          TEXT,               -- ask | tell | reply
  body          TEXT,
  reply_to      INTEGER,            -- → messages.id. Correlation agents never see (C2)
  created_at    INTEGER,
  read_at       INTEGER
);

events(
  id            INTEGER PRIMARY KEY,
  agent_id      TEXT,
  kind          TEXT,
  payload_json  TEXT,
  created_at    INTEGER
);                                  -- append-only; the board reads this
```

**How the shipped schema differs, and why** (`switchboard/store.py`):

| designed | shipped | why |
|---|---|---|
| `agents.id` = session id | `agents.name` PRIMARY KEY | agents are addressed by useful names, never opaque ids (M2 decision 3), and the name being the key is what makes a concurrent workspace open resolvable — the PRIMARY KEY index is the only arbiter two openers share |
| `herdr_name` | *(gone — the key IS the name)* | one place a name can live |
| `herdr_terminal_id` | `terminal_id`, plus `pane_id` | the stable handle is still the one to trust; `pane_id` is kept for debugging and for pane-targeted input when herdr loses a name binding |
| `last_seen_seq` | *(gone)* | herdr's `state_change_seq` is snapshotted per wait and never outlives it, so storing it would only let it go stale |
| — | `session_id`, `cwd` | restore, and locating the on-disk transcript (which is bucketed by cwd) |
| — | `workspace`, `workspace_id` | where an agent lives, recorded rather than re-derived: a name resolves to a checkout one-to-many, and a child spawned from a re-derived id lands in the wrong workspace |
| — | `cleanup` | the role's disposition, per agent |
| `messages.kind` = `ask\|tell\|reply` | `ask\|tell\|done` | there is no `reply` verb — a plain `tell` answers a pending ask, because correlation is the tool's job (C2). `done` is its own kind so summaries are findable |
| — | `messages.delivered_at` | the doorbell is deferred while a target is mid-turn, so "written" and "announced" are different facts |

Everything later — runs, step_results, gates, learnings — is **more rows, not new
plumbing.** That has held: every column above arrived by `ALTER TABLE ADD COLUMN`.

---

## M2 — herdr adapter

The only file that knows herdr exists. Shell out to the CLI for v0; socket API later.

Exact commands, socket params, and error codes: `reference/herdr-adapter-reference.md`.
Copied upstream docs: `reference/{socket-api,cli-reference,agent-automation}.mdx`,
`reference/herdr-SKILL.md`, `reference/herdr-api-schema.json`. Pinned to **v0.8.0,
protocol 19**.

| Our call | herdr | Note |
|---|---|---|
| `spawn(role, task, parent)` | `worktree create` → **create pane** → `agent start <name> --kind claude --pane <id> -- --permission-mode auto` | `agent start` **never creates topology** — it needs a pre-existing idle shell pane. Three steps, not one. **Always pass `--permission-mode auto`** — the default is `manual` and agents will sit waiting on every tool call. |
| `poke(agent, text)` | `agent prompt <name> "<text>"` | queues against a busy agent, but doesn't track turns. Stalls after 5s if a non-working agent shows no lifecycle change. |
| `set_state(...)` | `pane report-agent --source --state --message --seq --agent-session-id` | see state rules below |
| `wait(agent, until)` | `agent wait --until idle` | **no default timeout** — always pass one. **`--until` takes exactly ONE status**: `--until idle,blocked` is refused ("invalid agent status"), and repeating the flag has no defined meaning. `Herdr.wait` comma-joined a sequence for a while and its own default argument was therefore unusable — every call failed instantly and nothing waited. It also returns INSTANTLY when the agent is already in the state asked for, which turned the stale-seq retry into a 100%-CPU spin; callers ask for the state the agent is NOT in (`status._next_transition`) and the adapter backs off. |
| `attach(agent)` | `agent focus` (socket) / `agent attach` (**CLI-only**) | how the human jumps to a leaf (C14) |
| `release(agent)` | `pane release-agent` (narrow) or `pane close` (full) | on cleanup (C3) |

**Identity:** `terminal_id` is the stable handle — **`pane_id` changes on cross-workspace
moves**, so never store it. Agent *name* is the best practical addressing key for CLI
calls. Store both.

**Socket protocol:** newline-delimited JSON over `~/.config/herdr/herdr.sock`, and it is
**one request per connection** — confirmed in `src/api/server.rs::handle_connection`,
which reads one line, writes one response, and returns. A second write hits a closed
socket by design. `events.subscribe` is the exception: it holds the connection open.

**Stability (from CHANGELOG):** the agent facade had a past breaking rework but is now
stable; the worktree API has been stable since protocol 10; **live handoff and the plugin
API are explicitly experimental** — don't depend on them in v0.

**Gotchas:** the headless `done`-vs-`idle` seen-bit trap; reading an alt-screen pane
requires it to be idle; a server restart loses processes; and pane move/replace mid-`wait`
is a live race.

**Rules:** pin a minimum `herdr --version` and fail loudly below it; contract tests cover
exactly these six calls and run after every `herdr update`. If herdr dies, this file is
what gets replaced (`[01]`: one dominant maintainer).

### State authority — verified, we win

Full evidence with file:line in `reference/herdr-state-authority.md`. Effective state is:

```
visible_blocker_overrides_hook() ? Blocked : hook_authority.state ?? detector_state
```

`hook_authority` is **always effective** for our source — herdr only privileges a
six-name whitelist (`pi`, `omp`, `mastracode`, `opencode`, `kilo`, `kimi`), and Claude and
Codex aren't on it. The built-in Claude hook never reports state at all, so on a Claude
pane we are the sole authority against the regex detector.

Adapter rules that follow — **items 1–4 verified live on v0.8.0**, not inferred:

0. **`--agent LABEL` is required on EVERY call**, not just the first. Omitting it errors
   with `missing required --agent`. Same for `release-agent`.
1. **Pick one `--source` id and keep it forever.** Authority is per-source and sticky —
   no TTL, held until superseded, `release-agent`, or process exit.
   *Verified:* a **different** source can take over state at will (last-writer-wins, no
   exclusive lock). Harmless while we're the only writer, but two source ids in our own
   code would silently fight each other.
2. **Own `--seq` as a strict monotonic counter per source, and ALWAYS pass it.** Two
   distinct ways to silently lose a write, both returning success:
   - *Verified:* reusing a seq → **dropped**, no error.
   - *Verified:* **omitting `--seq` entirely → also dropped.** It does not mean
     "auto-assign".
   Persist the counter in M1 (`agents.seq`); never reuse, never roll back.
2b. **`state_change_seq` is NOT our `--seq`** — same-sounding name, opposite job.
   - **Ours guards writes.** *Verified:* seq is scoped **per (source, pane)** — pane B
     accepted `seq=5` immediately after pane A used `seq=1000`. So a plain per-agent
     integer starting at 1 is sufficient; agents cannot block each other, and no global
     counter is needed.
     **Consequences are bounded:** omitting seq drops every write (badge never updates);
     reusing one drops that write (badge stale until the next report). Neither can corrupt
     anything — our store is the truth and herdr is display, so it self-heals.
     **The one real race:** parent's `ask` times out and marks a child `failed` at the same
     instant the child reports `done` — two writers, one pane. Seq also makes retries safe
     (a duplicate is a harmless no-op).
   - **Theirs guards reads.** It's herdr's global transition counter (observed 73→74→75→76
     across two panes) and it's how we detect a **stale `agent wait`** — `wait` is *not*
     turn-scoped, so a previous turn's transition can satisfy it instantly:
     ```
     before = state_change_seq
     herdr agent prompt <a> "…" ; herdr agent wait --until blocked --timeout N
     if state_change_seq <= before:  # satisfied by an OLD transition — wait again
     ```
   Never round-trip one as the other.
3. **`done` cannot be reported.** The enum is `idle|working|blocked|unknown`; herdr
   derives done read-side (idle + unfocused → done; focusing → idle). So `wf done` sets
   herdr `idle`, and **our store holds the real terminal state.**
4. **Accept the one override.** If the detector sees a live permission prompt after our
   last report and we hadn't said `blocked`, herdr forces `Blocked`. It never forces us
   *out* of blocked, and a spinner never overrides us. This override is desirable — a
   permission prompt genuinely is blocked — so don't fight it; reconcile to it.
5. **Call `release-agent` on cleanup** to hand state back to the detector. *Verified:* it
   releases **authority only** — the agent stays registered and its state falls back to
   whatever the detector reports (observed: `idle`). To actually remove it, `pane close`.
   Note `clear-agent-authority` is **socket-only**, not a CLI command.
6. **Don't trust event provenance** — `pane_agent_status_changed` looks identical whether
   reported or detected. Our store is the truth (C5, C7).

---

## M3 — Broker (`wf` CLI)

The whole agent-facing surface. Every other future surface (MCP, hooks, UI) is a shim over
these same verbs (C13). Every command emits JSON with `--json`.

| Agent wants | Command | Shipped as |
|---|---|---|
| "do this for me" | `wf delegate <role> "<task>"` → returns child id | `sb delegate "<task>" --role <role>` — the task is the argument and the role is the flag, because the task is what varies |
| "I need an answer" | `wf ask <who> "<q>" [--timeout N]` → **blocks**, returns the reply | `sb ask <who>… "<q>"` — and it takes SEVERAL targets, because "ask three researchers and wait" is the common fan-out and looping would cost a turn per child |
| "FYI, don't wait" | `wf tell <who> "<msg>"` | `sb tell <who>… "<msg>"` |
| "anything for me?" | `wf inbox` → non-blocking; you were poked | `sb inbox` |
| "here's your answer" | `wf reply <msg-id> "<answer>"` | **RETRACTED — there is no `reply` verb.** A plain `sb tell` back to whoever asked satisfies the pending ask: `store.pending_ask` finds it and `tell` sets `reply_to` itself. Correlation is the tool's job and an agent that has to name a message id is doing protocol work (C2) — which is exactly what the P0 rewrite of `send`/`report` was for |
| "I'm done" / "I'm stuck" | `wf done [--payload]` / `wf blocked "<why>"` | `sb done "<summary>"` / `sb block "<why>"` — one line, not a payload: a summary long enough to need a payload is one the parent should not be reading (C4) |
| "who can help?" | `wf who` | **RETRACTED — never built, and not missed.** `sb status` answers the question it was for, jointly from the store and herdr. `who` would have listed roles and capabilities, which is a roster — and there is no roster (C3) |

Agents learn these from ~8 lines via `--append-system-prompt`. That's the only instruction
text in the system.

> The shipped protocol is `defaults/protocol.md`, still one line, still injected at every
> spawn. It is longer than eight lines' worth: two failures observed against live agents
> cost sentences here rather than a mechanism. Agents treated mail as an untrusted
> suggestion and stalled waiting for a human, so parent authority is now stated; and
> nothing told them `sb block` existed, so a stuck agent held a pane on `sb ask human` for
> the full fifteen minutes.

### Delivery — doorbell + mailbox

Only the asker blocks. The receiver never polls.

```
A: wf ask B "question"
     1. INSERT message                                → store
     2. herdr agent prompt B "mail: run `wf inbox`"   → doorbell (no payload)
     3. block on store until reply row appears        → returns to A

B: (poked mid-session) wf inbox   → the message, non-blocking
   … works …
   wf reply <msg-id> "answer"     → store → A unblocks
```

Payloads never cross a terminal — nothing scraped, nothing lost to alt-screen (C5). No
channels, no `turn/steer`, no research-preview flags. Works the same for Codex later.

On `--timeout`, the asker gets `timed_out` and decides (C9 — later, that routes to a gate).

### `wf blocked` — the shortcut, present from day one

`wf blocked "<why>"` does three things:

1. writes the row (store),
2. `set_state(blocked)` so herdr marks the pane and `agent wait --until blocked` works,
3. notifies **the human directly** — not the parent.

There's no UI in v0, so "notify" is a herdr notification / bell. The **path** is what
matters: leaf → store → human, bypassing the tree, so parent context never grows with
blocks (C14, C4). Building it any other way now means retrofitting later.

> **Step 2 is RETRACTED. We must never report herdr's `blocked`.** Verified against
> 0.8.0: `pane report-agent --state blocked` **deregisters the agent's name**. `agent get`
> and `agent prompt` then answer `agent_not_found`, a pane-targeted prompt answers
> `agent_not_ready`, and re-reporting `working` does not bring the binding back once herdr
> has seen the agent leave the foreground — which `sb` running in that pane causes.
>
> So the one verb whose entire purpose is "stop and get a human" was leaving the human no
> channel back in. `sb block` now reports `idle`, which is honest — the agent IS idle,
> waiting — and keeps it reachable. Blocked-ness lives in our store, which is the truth
> anyway (C5). `Broker._unblock_if_needed` pushes `working` before any doorbell, for the
> rows written before this was understood.
>
> Steps 1 and 3 stand, and step 1 grew: the reason also goes into the **human's mailbox**,
> not just a notification. `sb block` and `sb ask human` are the same want and now share
> the same mailbox and the same `_surface`; a notification alone is gone the moment it is
> dismissed, and `sb inbox` was silent about blocks while `sb status` listed them.
>
> Losing herdr's `blocked` as a badge costs one thing: `agent wait --until blocked` no
> longer fires for our blocks. It still fires for herdr's own detector spotting a
> permission prompt on screen, which `sb status` reports separately as AT PROMPT.

---

## Smoke-test results (v0.8.0, run 2026-08-06)

**The doorbell + mailbox design works end to end.** Two live Claude agents, files standing
in for SQLite: A wrote a message, poked B with no payload, B read the file, worked, wrote
a reply, A's poll returned it. ~30s round trip for a trivial task.

Verified:

| # | Finding | Consequence for M2 |
|---|---|---|
| 1 | `agent start <name> --kind claude --pane <id>` works; `--timeout` waits for `interactive_ready: true` | spawn is reliable and synchronous |
| 2 | **`agent_session` is auto-populated** by the installed integration: `{kind:"id", source:"herdr:claude", value:"<uuid>"}` | **identity is solved for us** — herdr already ties the Claude session UUID to the pane. No env plumbing, no self-registration race. |
| 3 | `agent prompt` **auto-submits**, even with the session in *manual mode* | the doorbell needs no keystroke simulation |
| 4 | The `agent prompt` **response returns before state changes** (came back `idle`, seq unchanged) | **never** infer "it started" from the prompt's return value. Snapshot seq *before* poking. |
| 5 | `state_change_seq` advanced 88→92 over one turn | reliable change signal, several transitions per turn |
| 6 | Payload never crossed a terminal; agent followed a 2-step file instruction | mailbox pattern holds |
| 7 | Agent returned to `idle` after replying | clean turn boundary — `wait --until idle` is meaningful |
| 8 | `agent list` reports `name` separately from `agent` (kind) | address by `name`; `agent` is just "claude" |

| 9 | ~~Poking a busy agent queues~~ ~~**WRONG — RETRACTED.** … **`agent prompt` INTERLEAVES**~~ **THE RETRACTION WAS ITSELF WRONG — the original finding stands.** `agent prompt` **queues**: measured three times against a single 90-second `Bash` call, prompted ~10s in and watched from outside the agent, all three loops ran to completion and all three agents saw the text attached to that call's result (`Herdr.prompt`'s docstring, `audit/phase3-delivery-primitive.md`). The +13s/+63s reading was a turn made of several short tool calls, where delivery-at-the-next-boundary is indistinguishable from interleaving. | The doorbell is **not** disruptive: the default mode rings immediately and the text waits at the next tool-call boundary. `--when-idle` needed no daemon — `Broker.flush_pending`, run by every `sb` invocation and by the collector, is the trigger — and `--interrupt` (which does send `esc`) is a third mode of `sb tell` rather than a verb. `sb wait` was built and deleted. |

| 10 | **Agent args pass through after `--`.** Verified: `argv: ["claude","--permission-mode","auto","--resume","<uuid>"]` | role profiles, model tiers, and resume all ride this |
| 11 | **`--resume <session-uuid>` in a FRESH pane fully restores an agent** — context *and* a replay of the prior transcript into the new pane | **closing a pane costs nothing.** Aggressive cleanup is safe by default; `wf restore` is real |
| 12 | `agent start` **immediately** after `pane split` fails — the pane isn't at an interactive shell prompt yet | M2 must retry/wait between the two |
| 13 | Reading an alt-screen pane needs `--source recent`; the default read shows only the empty prompt frame | any pane read in M2 must pass `--source recent` |

**The whole delivery path is now confirmed.** Nothing in the doorbell design rests on
untested behaviour.

### M3 verb-design validation (4 rounds, real agents, file-backed shim)

Ran the verb surface end to end with a throwaway `wf` (`scripts/wf-shim.sh`, files not
SQLite). **Round 4 passed fully**: depth-3 tree, fan-out to two children, `done` poking the
parent, orchestrator aggregating and reporting. The design works.

| # | Finding | Consequence |
|---|---|---|
| 14 | **herdr rejects multi-line agent args** — `{"code":"invalid_agent_argument","message":"agent arguments cannot be encoded safely for the target shell"}`. There is no `--append-system-prompt-file`. | Role prompt must be **one line**. **Verb docs go in `CLAUDE.md`** (auto-discovered, unlimited, written once per workspace) — which is also cheaper per C0, since they stop being paid per agent. |
| 15 | **Pane splits exhaust after ~4** — `pane split` returns no pane_id when there's no room, silently breaking fan-out mid-round | **One agent per TAB, not per pane.** This reverses decision 7 on evidence: panes can't hold a fan-out. |
| 16 | **Identity must come from `CLAUDE_CODE_SESSION_ID`**, looked up in the store. The shim injected `WF_ME` via `pane split --env`; switching to `tab create` silently dropped it and every child re-parented to `human`. | Never derive identity from spawn-time env — it doesn't survive a change in how panes are made. Confirms the original M3 design. |
| 17 | **Spawn is flaky** — occasional `agent start` failures even with the 4s wait | M2 needs retry-with-backoff. Agents also self-heal: one orchestrator re-delegated a failed child unprompted. |
| 18 | **Agents do the work themselves when `delegate` fails** — an orchestrator computed `15*15` itself and (honestly) flagged it as unverified | **Silent C4 violation.** The protocol needs an explicit rule: *if delegate fails, report blocked — do not do the child's work.* Added to `CLAUDE.md`. |
| 19 | Orchestrators reported failures accurately and unprompted, including which child was re-run | structured `done` summaries are trustworthy enough to be the parent's only input (C5) |

### Debuggability — almost entirely free

No wrapper, no extra tool calls, no transcript capture.

| Layer | Location | Cost |
|---|---|---|
| **Agent transcripts** | `~/.claude/projects/<escaped-cwd>/<session-id>.jsonl` — **verified**: round 4's orchestrator is at `…/0ab49686-….jsonl`, the exact session id we stored | free, already written by Claude Code |
| **herdr internals** | `~/.config/herdr/herdr-server.log`, `herdr-client.log` | free, already written |
| **Our calls** | `wf` appends one JSONL line per invocation: verb, args, herdr response, exit code, duration | one file append inside a call we're already making |

Rules:
- **Never swallow a herdr error.** The shim's `2>/dev/null` is why finding #17's cause is
  still unknown. Log the response, surface the code, retry with backoff.
- **Store `cwd` next to `session_id`** — transcripts are bucketed by cwd, so agents in
  different worktrees land in different project dirs and resolution becomes a search without it.
- Transcripts survive pane close (as does `wf restore`), so aggressive cleanup stays safe.

### Prompt inheritance (deferred, but noted)

Prompts should layer, not be re-specified per agent. Rough hierarchy, most general first:

```
global defaults (~/.config/agentflow/)   ← always inherited
  └ repo (<repo>/.agentflow/)            ← repo-specific rules and templates
      └ workspace                        ← this run's context
          └ role                         ← role profile
              └ per-call (--with)        ← throwaway injection
```

Each level inherits and may override. Some rules ("when to block", the wf protocol) should
be **unconditionally inherited** at the global level and never restated. This is the
overlay/directive split worth borrowing from Gas Town (`replace` / `append` / `skip`).

**Deferred:** the "when to block" injection itself. Revisit when it bites.

### Finding #20 — the claude integration and state authority are mutually exclusive

**Verified while building M2.** Earlier findings were taken on a *bare shell* pane; on a
pane running a real Claude agent the picture inverts.

| `herdr integration install claude` | our state reports | `session_id` at spawn |
|---|---|---|
| installed | **rejected** — herdr owns state | free |
| uninstalled | **accepted** — we own state | empty |

Cause, in `src/terminal/state.rs` (~L631–643): a report is dropped by
`known_agent_label_conflicts_with_detected_agent` / `current_session_owner_conflicts`
before it ever reaches the seq check. The installed integration registers itself as the
pane's session owner, so source `switchboard` cannot take over. It fails **silently** —
`report-agent` returns success and the state simply doesn't change.

**Decision: uninstall the claude integration.** State authority is load-bearing (it is
what makes `agent wait --until blocked` trustworthy and the board honest); the session id
is not lost, it just arrives by a better route:

- `wf` reads `CLAUDE_CODE_SESSION_ID` from its own environment on first call — the M3
  identity design, already validated.
- We then register it under our own source with
  `pane report-agent-session --source switchboard --agent <name> --agent-session-id <id>`,
  so switchboard owns session *and* state under one source.

This reverses the earlier "install the integration" recommendation. It also means finding
\#2's silent-drop trap has a second cause: a rejected write looks identical to a stale seq.

### Cleanup & restore (settled)

- Disposition is a **role property**: `cleanup: close | keep`, overridable per call with
  `--ephemeral` / `--keep`.
- **Default is `close`** — justified by finding #11: closing loses nothing, since
  `wf restore <name>` brings back both context and transcript.
- Orchestrators **may** clean up their own children, aggressively, for anything marked
  closeable — and *only* their own subtree, never a sibling's.
- Never auto-close an agent that is `blocked` or has unread messages.
- `sb cleanup [<name>…] [--include-kept] [--force] [--dry-run]`. `--workspace` and
  `--older-than` were never built and nothing has wanted them. `--all-idle` shipped and
  survives as an alias, but the name was a lie: it has only ever closed agents that
  FINISHED, and a sweep by idleness would close an agent between turns. What it actually
  does is lift the role's `keep` disposition, which is what `--include-kept` says.
  `<name> --force` is the escape hatch — an agent whose state never advanced, or that
  holds mail it can never read, is unreachable by every sweep, and a QA run had to leave
  three panes running for want of it.
- The store keeps `agent_session_id`, summaries, and message threads forever. Closing
  touches only the pane, so `wf status` and any future board are unaffected.

**Cost note:** the trivial exchange showed $0.12 on one agent's meter.

---

## M2 decisions (settled)

M2 holds no product logic, but these knobs are set. Several exist to *support* M3
behaviour that isn't built yet.

| # | Decision |
|---|---|
| 1 | **1 workspace = 1 worktree.** Multiple workspaces may share one worktree, but never the reverse. An **agent group** (one orchestration unit) lives inside one workspace. |
| 2 | **Worktree is a command param**, defaulting to `main` when unspecified. |
| 3 | **Agents are addressed by useful names, never opaque ids.** herdr already supports this (`agent start <name>`, address by name) — no id-mapping layer needed. |
| 4 | **Always `--permission-mode auto`.** Spawn accepts **multiple prompt fragments** (role prompt + injected prompts). |
| 5 | **Claude first. Codex deferred** — but nothing may hard-code "claude" outside M2. |
| 6 | **Use herdr's four states as-is. We do not own a status vocabulary.** No `reviewing`/`researching`/etc. — too much to invent, too hard to keep in sync, and herdr's states come with UI grouping we'd lose. If it's something I want to *see*, it maps to `blocked`. |
| 7 | ~~**One agent per pane, for now.**~~ **RETRACTED by finding #15 below** — `pane split` returns no pane id once a workspace has about four, silently breaking a fan-out mid-round. It is one agent per **tab**. Not a preference; splits cannot hold a fan-out. |
| 8 | **Notify on blocked.** |
| 9 | **No autofocus.** Focus follows the human's tools, not the system's opinion. |
| 10 | **CLI now**, socket when we need `events.subscribe`. |

### Two things this forces into M2

**A. `create_run` is a separate primitive from `spawn_agent`.**

A **global/main orchestrator** lives outside every run. Told "run the fix-issue template",
it calls a command that scaffolds a whole group:

```
create_run(template, issue) → worktree create → workspace create
                            → tab create → agent start <run>/orchestrator
```

So M2 exposes two spawn shapes: *start a run* (worktree + workspace + lead agent) and
*add an agent to an existing run* (tab + agent, inside the caller's workspace). The main
orchestrator is spawned with neither — global, no worktree, no run.

**B. Status stays herdr's.** `idle | working | blocked | unknown`, nothing more. Detail
that matters lives in our store and in the `--message` text, not in a parallel status
vocabulary we'd have to keep in sync. `report-metadata --token` remains available for
*grouping* data (run, role) — that's not a status.

### Everything is wrapped. Agents never see herdr or Claude flags.

```
agent   →  wf delegate reviewer "check PR 42" --with security --with perf
              │                    (M3: resolves role + skill NAMES to prompt text)
              ▼
M2      →  spawn(name, prompts=[<role text>, <security text>, <perf text>], worktree, kind)
              │                    (M2: knows nothing about roles or skills)
              ▼
herdr   →  agent start <name> --kind claude --pane <id> --
              --permission-mode auto
              --append-system-prompt "<…>"  --append-system-prompt "<…>"  …
```

Each layer hides the one below (C2, C13). **M2 takes a list of prompt strings and nothing
else** — no concept of a role, a skill, or a template. That vocabulary is M3's, so it can
change freely without touching the adapter, and so a future Codex backend needs no new
vocabulary either.

### Spawn signature

```
spawn(name, prompts[], worktree=main, kind=claude) → agent handle
  → tab create --workspace <id>      # NOT pane split — see finding #15
  → agent start <name> --kind claude --pane <id> --timeout N --
        --permission-mode auto
        --model <m> --effort <e>     # resolved from a TIER by models.py, never a name
        --append-system-prompt <p>   for each p in prompts    # flag verified repeatable
```

`--workspace` on `tab create` is not optional in practice: without it a tab lands in
whichever workspace happens to be FOCUSED, so a child appears in a stranger's workspace
purely because something called focus recently.

**Is M2 customizable enough?** Yes, because it deliberately isn't the customizable part.
Every choice you'd want to tune — which prompts, which skills, which model, which tools a
role may touch — is a *value passed into* `spawn`, resolved from YAML by M3. M2's only job
is to faithfully hand those values to herdr.

---

## Roles

No agent types. `role` is free text (C12). Two behaviours emerge from context, not config:

- **Worker** — given a task, does it, reports, exits.
- **Orchestrator** — a role, not a component. *With* a template it already knows what to
  do and sees it through, spawning per step. **Without** a template it simply awaits my
  instructions. Templates don't exist in v0, so every orchestrator is the second kind —
  which is exactly the PoC we want.

---

## Done when

An agent spawns a second agent, delegates, blocks on `ask`, gets a reply, and finishes —
and `wf agents` plus the `events` table tell the whole story without opening a transcript.

## Open for review — and how each was answered

1. **Cleanup.** Who calls `release-agent` when a child exits — the child on `done`, or the
   parent? Child is simpler; parent is more reliable if the child dies badly.
   → **Neither: whoever runs `sb cleanup`.** `done` is a *report*, not a teardown, and an
   agent that dies badly never gets to `done` at all — which is precisely the case that
   needs cleaning up. So `done` only records and pokes the parent, and closing is a
   separate, idempotent sweep any ancestor (or the human) can run at any time.
2. **Self-registration timing.** First `wf` call creates the row — but `delegate` needs the
   child's id *before* the child has run anything.
   → **The parent writes the row, keyed by NAME, before herdr is asked for anything.**
   The first of the two options, and it turned out to be load-bearing for a second reason:
   the row *is* the claim, and `agents.name` being a PRIMARY KEY is the only arbiter two
   concurrent openers of one workspace share. Recording after the spawn instead raced, and
   lost about one open in twenty-five. The child fills in its session id on first call
   (`_claim_session`); identity itself comes from `HERDR_PANE_ID`, so nothing waits.
3. **`wf who` scope.** Whole tree, or only my parent and children? C1 argues the latter.
   → **Moot: `who` was never built.** `sb status` shows the whole tree, and shows it to
   agents too. C1 constrains who may *talk* to whom, not who may look — and a parent that
   cannot see two levels down cannot tell that a grandchild has stalled.
4. **Timeout default** on `ask`. Long enough for real work, short enough to not wedge.
   → **900s**, with the reasoning next to the number in `defaults/settings.toml`. The
   wedging risk turned out to be a typo'd target rather than a slow one, so `ask` resolves
   its targets against the store first and fails immediately on a name nobody has.
5. **Failure of a child mid-task** — parent is blocked on `ask` and the child dies. Detect
   via herdr pane state, or purely by timeout?
   → **By the STORE, and only partly.** `ask` stops waiting on any target that has reached
   `done` or `failed`: that is something the agent recorded about itself, so the answer is
   provably not coming and sitting out the remaining fourteen minutes would be a lie. This
   covers the common case — a child that called `sb done` without answering, since a `done`
   summary does not satisfy a pending ask.
   Deliberately **not** by herdr pane state: an agent missing from `agent list` looks the
   same whether it died or herdr hiccupped, and treating a hiccup as death would make every
   `ask` return nothing the moment herdr coughed.
   **Still open:** a child that dies without recording anything (its pane closed under it)
   is invisible to `ask` and it will wait the full timeout. `sb status` names that case as
   GONE; `ask` has no cheap way to be sure, so it waits.
