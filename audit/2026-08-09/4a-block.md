# AUDIT 4a — sb blocking behaviour vs DESIGN-TRUTH.md

Tree audited: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` (branch worker-2, a9dd319).
All `file:line` below are from THAT tree unless marked otherwise. The `sb` on PATH is
`/Users/andrew/Code/switchboard/bin/sb` (branch main, caa6d20) — used only for `--help` /
`sb status --json` readouts, noted where relevant. `git -C /Users/andrew/Code/switchboard log`
shows main's recent work is workspace teardown; nothing there touches block/why/unblock, so
main does not already fix anything below.

---

## Entry 1 — "blocking writes the full message in the chat first … Andrew will not see the `why`; it is just for bookkeeping. This must be made clear." (DESIGN-TRUTH.md:233-235)

**Verdict: BROKEN.**

Two independent failures: nothing instructs the write-in-chat-first behaviour, and the `why`
*is* surfaced to the human in three places, so the premise the truth rests on is inverted.

### Nothing instructs "write the full message in the chat first"

- `defaults/protocol.md:119-122` is the only place every agent is told about blocking. It says
  the opposite of the truth: "`sb block "<why>"` is the ONLY way to reach a human … **They read
  that one message and open no files, so say in it what you were asked and where you are.**"
  "that one message" is the `why` argument — the agent is told to put the content INTO `why`.
- `defaults/protocol.md:52-54` repeats it in the rationale block: "a human sees you only when you
  `block` — one message, the final turn, no scrolling, no files opened (stated at `block`)."
- `defaults/roles/researcher.md:10-11`: "The human sees an agent only when it calls `sb block`,
  reads one message with no scrolling, and opens no files".
- `defaults/roles/worker.md:51-53` and `defaults/roles/orchestrator.md:193-196` name `sb block`
  and say when to use it; neither mentions writing anything in the pane first.
- Grep over `defaults/` for any pane-first instruction ("need human input", "write … first",
  "in the chat") returns nothing. The protocol is assembled into the spawn system prompt at
  `switchboard/broker.py:99` (`PROTOCOL_LINE = config.protocol()`), `broker.py:307-308`,
  `broker.py:2549` — so protocol.md IS the live text, and it carries the contradiction.

### The `why` IS shown to the human — in four places

- `switchboard/broker.py:2903` → `_surface(me, why)` → `broker.py:3464-3466`: desktop
  notification `f"{who}: {text[:NOTIFY_CLIP]}"`, clip 120 chars (`defaults/settings.toml:200`).
- `switchboard/broker.py:2902` → `_push_state(a, IDLE, why)` → `broker.py:3494-3499`: `why` is
  pushed to herdr as the state `message`, so it renders in herdr's own status/UI.
- `switchboard/broker.py:2904`: logged as event `kind="blocked", why=why[:200]`, and
  `switchboard/status.py:642-659` (`_block_reasons`) reads it straight back out of that log for
  display; `status.py:474` puts it on `AgentStatus.blocked_why`.
- Rendered to the human at `switchboard/status.py:1081-1084` (the NEEDS YOU block, whose own
  comment at 1075-1076 says "This IS the human's inbox"), `status.py:1298-1299` (`sb inspect`),
  and `switchboard/board.py:200-201` (`BLOCKED — {a.blocked_why}`). It is also a public JSON
  field (`status.py:295`, `blocked_why`) — confirmed live: `sb status --needs-me --json` emits
  `"blocked_why"` per agent (run against main's checkout).
- The docstring at `broker.py:2878-2882` states the design *as built*: "`sb status --needs-me`
  lists this agent with `why` for as long as it stays blocked" — i.e. the code deliberately
  makes `why` the human-facing payload. Same in `switchboard/cli.py:796-797` and
  `defaults/settings.toml:117-119`.

### "Must be made clear" — it is not

Nothing anywhere tells an agent the `why` is bookkeeping-only. Every text that mentions it tells
the agent the opposite. `sb block --help` (run on main) is bare: `usage: sb block [-h] [--json]
why`, with no help string on `why` at all (`cli.py:161-162` sets none).

### Supporting gap: reading the pane is 40 lines, not 100

If the design intent (message in the pane, `why` as bookkeeping) were implemented, `sb inspect`
would be the read path. `cli.py:299` defaults `-n` to `status_mod.DEFAULT_LINES`
(`status.py:1163`) = `display.output_lines` = **40** (`defaults/settings.toml:305`), against
DESIGN-TRUTH.md:229's "more tail — like 100 lines".

---

## Entry 2 — "After Andrew answers a block, the agent just continues." (DESIGN-TRUTH.md:237)

**Verdict: PARTIAL.** The resume mechanism is real and correct. The *answer channel* it depends
on is `sb tell`, which DESIGN-TRUTH.md:229-231 says Andrew does not use; and the related
when-idle hold (DESIGN-TRUTH.md:223-225) is not implemented at all.

### The resume path (works, and does poke rather than restart)

1. `switchboard/broker.py:2891` — `sb block` sets store state `blocked`; herdr is told `IDLE`,
   not blocked, deliberately (`broker.py:2892-2901`), so the agent stays targetable.
2. Human answers with `sb tell <agent> "…"` → `broker.py:2670-2710`; message row is stored, then
   `_ring(t, …)` at `broker.py:2710`.
3. `_ring` → `broker.py:3429` `self._unblock_if_needed(who)` → `broker.py:3440-3460`: pushes
   herdr `WORKING`, sets store state back to `working`, logs `unblocked`.
4. `broker.py:3431` `self.h.prompt(who, text)` injects the doorbell into the existing session —
   `defaults/prompts.toml:65` `mail = "You have mail. Run: sb inbox"`. Same session, same
   context: continues, is not restarted and is not made to re-report.

So the agent genuinely just continues. `sb block` itself returns immediately and ends the turn
(`cli.py:794-797`) — no waiting.

### But the answer channel contradicts the truth

DESIGN-TRUTH.md:229-231: "Andrew does not use it [`sb tell`] — he types directly into the
session." The code makes `sb tell` the *only* thing that clears a block: `broker.py:2884-2885`
("The human answers with `sb tell <agent> "…"`, which rings the doorbell and unblocks it"),
`cli.py:161` (`block` help: "they answer with `sb tell`"), `cli.py:771`, `status.py:1082-1083`
(the NEEDS YOU row literally prints `→ sb tell <name> "..."`). If Andrew types into the pane as
the truth describes, nothing calls `_unblock_if_needed`: the store row stays `blocked` forever,
the agent keeps showing in `sb status --needs-me` and on the board, and only a later `sb tell`
or a stale-block cleanup clears it. No code path anywhere detects a human typing into a pane
(grep for any pane-input/at-prompt-derived unblock: none — `status.py` only *reads* `at_prompt`).

### Related truth (DESIGN-TRUTH.md:223-225) — when-idle mail held until the block is answered

**Not implemented, and the current behaviour is the failure the truth exists to prevent.**

- There are no delivery modes on `sb tell` at all: `cli.py:148-151` defines only
  `who`, `message`, and a hidden `--re`. No `--when-idle`, no `--interrupt` flag on `tell`.
  (`sb tell --help` on main confirms the same three.)
- Deferred delivery exists but is gated on *busy*, not on *blocked*: `broker.py:3344-3350`
  (`flush_pending`) skips a target only `if self._busy(who)`, and `_busy` (`broker.py:3296-3302`)
  is `herdr state == WORKING`. A blocked agent was pushed to herdr as **IDLE**
  (`broker.py:2902`), so it reads as not busy and gets rung.
- The ring then silently cancels the block: `_ring` → `_unblock_if_needed`
  (`broker.py:3429`, `3440-3460`) sets it back to `working`. Any agent's `tell` — not just the
  human's answer — clears a block and buries the question.
- `flush_pending`'s own docstring (`broker.py:3312-3318`) names exactly this hazard, but only for
  *already-read* mail: it uses `store.unseen` rather than `store.undelivered` because otherwise
  it would "silently cancel a `block`, putting an agent that stopped to ask a person back to
  `working` with its question never surfaced". Unseen mail still does precisely that.

---

## Entry 3 — "Agents should avoid blocking unless it is really needed", five triggers (DESIGN-TRUTH.md:124-127)

**Verdict: PARTIAL.** Two of five triggers exist in some form, three are absent, one trigger
present in the prompts is not in the truth, and the "avoid unless really needed" framing is
never stated.

Where blocking guidance actually lives: `defaults/protocol.md:117-122` (every agent),
`defaults/roles/orchestrator.md:132-135` and `:193-196`, `defaults/roles/worker.md:51-53`. Not in
`switchboard/roles.py` or `presets.py` (both only assemble files — `presets.py:18-20`), and not
in any of `defaults/presets/*.md` (grep for "block": no hits).

| Truth trigger (DESIGN-TRUTH.md:124-127) | Live prompt text | Verdict |
|---|---|---|
| a genuine, big, behaviour-changing design question | `orchestrator.md:194-195` "Use it when a decision is genuinely theirs"; `worker.md:51-52` "a decision that was not yours to make" | present, weaker — no "big / behaviour-changing" bar |
| being blocked on running some command | `protocol.md:117-118` "Stop and get a human if a tool fails twice … Never work around a broken tool"; `orchestrator.md:133-134` "if a tool you yourself depend on is broken, `sb block`" | present, phrased as broken tools rather than blocked-on-a-command (e.g. an interactive/permission-gated command that has not failed twice is not covered) |
| being explicitly told to block | nothing | **absent** |
| going back and forth with the agent itself | nothing | **absent** |
| finished work that needs Andrew's input or approval to complete | nothing; and `orchestrator.md:195-196` says "do not use it to report — that goes to your parent through `sb done`", which reads as forbidding it | **absent, arguably contradicted** |
| — | `protocol.md:118` "if you are about to do work you were told to delegate" | extra trigger not in the truth |
| — | `protocol.md:117` "if an instruction is ambiguous" | extra trigger not in the truth |
| "avoid blocking unless it is really needed" (the umbrella) | nearest is `orchestrator.md:195` "Do not use it to hand over work" — a prohibition, not a scarcity norm; workers get nothing | **absent** |

Also relevant to how a block should be written (DESIGN-TRUTH.md:115-121, human-facing output is
concise/skimmable/numbered-with-recommendations): grep over `defaults/` for
skimmable/bullet/concise/numbered finds only `orchestrator.md:30` (a warning that bullets become
`;` in a task string). No formatting guidance for what an agent puts in front of a human exists.

---

## Gaps

1. `defaults/protocol.md:119-122` tells every agent to put the human-facing content INTO
   `sb block`'s `why` ("They read that one message"); DESIGN-TRUTH.md:233-235 says the message
   goes in the chat and `why` is bookkeeping Andrew never sees. One of the two must change —
   decide which, then make protocol.md, `roles/researcher.md:10-11` and `protocol.md:52-54` agree.
2. No prompt anywhere instructs "write the full message — 'need human input: …' at full length —
   in the chat before calling `sb block`". Add it wherever the block instruction lives.
3. The bookkeeping-only nature of `why` is stated nowhere an agent sees; `sb block --help`
   gives `why` no help string at all (`cli.py:161-162`).
4. `why` is surfaced to the human in four places — notification (`broker.py:3466`), herdr state
   message (`broker.py:2902`), `sb status --needs-me` (`status.py:1081-1084`) and `sb inspect`
   (`status.py:1298-1299`) plus the board (`board.py:200-201`) and JSON (`status.py:295`). If the
   truth stands, these all need re-pointing at the pane tail instead.
5. `sb inspect` shows 40 lines of tail (`settings.toml:305` `output_lines = 40`), not the ~100
   DESIGN-TRUTH.md:229 asks for — and it is the same knob other output uses, so it needs its own
   setting rather than a bump.
6. Answering by typing into the pane — the way DESIGN-TRUTH.md:229-231 says Andrew answers —
   never clears the `blocked` state. Only `sb tell` calls `_unblock_if_needed`
   (`broker.py:3429`). Needs either a pane-typed-answer detection path or an explicit human
   unblock verb.
7. `sb tell` has no delivery modes: `cli.py:148-151` defines no `--when-idle` / `--interrupt`
   flag, so DESIGN-TRUTH.md:216-227's three modes are one mode. When-idle delivery cannot be
   held for a blocked agent because it does not exist.
8. Mail to a blocked agent silently cancels the block: blocked is pushed to herdr as IDLE
   (`broker.py:2902`), `_busy` therefore says not-busy (`broker.py:3296-3302`), `flush_pending`
   rings (`broker.py:3348-3350`) and `_ring` unblocks (`broker.py:3429`). The question is never
   answered and the agent goes back to `working`. Gate `flush_pending`/`_ring` on store state
   `blocked` for non-human senders.
9. Three of the five block triggers are missing from every prompt: explicitly told to block;
   going back and forth with the agent itself; finished work needing Andrew's input or approval.
10. The last of those is contradicted by `orchestrator.md:195-196` ("do not use it to report"),
    which needs an exception for work finished-but-needing-approval.
11. The umbrella norm "avoid blocking unless it is really needed" is stated nowhere; the prompts
    present blocking as an available verb with two prohibitions, not as a last resort.
12. `protocol.md:117-118` carries two triggers ("an instruction is ambiguous", "about to do work
    you were told to delegate") that are not in the confirmed five — reconcile or confirm them.
