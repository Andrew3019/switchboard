# AUDIT 4b — reading surfaces: inspect / status / log / human output style

Tree audited: `/Users/andrew/.herdr/worktrees/switchboard/worker-2` (branch worker-2, a9dd319).
Cross-checked against the `sb` on PATH → `/Users/andrew/Code/switchboard` (main, caa6d20): on every
point below main is IDENTICAL, so nothing here is already fixed on main.
Read-only: no repo file was written; the only run commands were `--help`, and one `sb inspect worker-5`
(which writes a `read_output` event — unavoidable, no agent state changed). No agents spawned.

---

## 1. "`sb inspect` is how Andrew reads a blocked agent's full message, and it should show more tail — like 100 lines." (DESIGN-TRUTH.md:245-246)

**Verdict: PARTIAL**

Inspect exists, is wired, and is genuinely the one-agent readout. The tail is **40 lines, not ~100**, and
the block message itself is not reliably readable at that size.

Evidence:
- Verb and default: `switchboard/cli.py:292-301` — `ins.add_argument("-n", type=int, default=status_mod.DEFAULT_LINES)`.
- `switchboard/status.py:1163` — `DEFAULT_LINES = config.setting("display.output_lines")`.
- `defaults/settings.toml:304-305` — `# Lines of terminal output 'sb inspect' shows.` / `output_lines = 40`.
  Same value on main (`/Users/andrew/Code/switchboard/defaults/settings.toml:305`).
- Configurable both ways: per-invocation `-n` (`cli.py:299`, validated `cli.py:406-409`) and per-repo via
  the `display.output_lines` setting. So the fix is a one-number change, but the shipped default is 40.
- Empirically confirmed by running `./bin/sb inspect worker-5` in this tree: the emitted event reads
  `read_output {"source": "pane", "lines": 40, "detail": ""}` and the OUTPUT section printed 40 lines.

Does it surface the blocked agent's *full block message*?
- It prints the recorded `why`, unclipped: `switchboard/status.py:1298-1299` —
  `if a.blocked and a.blocked_why: out.append(f"  blocked    {a.blocked_why}")`. (Contrast the board,
  `board.py:201`, and `status.py:1082` where the same `why` is cut to 70 chars.)
- The agent's *chat* message — the "full length" text DESIGN-TRUTH:236-238 says the human actually reads —
  only reaches inspect through the raw terminal tail: `status.py:1254-1255` →
  `output_mod.read_output(db, h, name, lines=lines)`. Two truncation risks at 40 lines:
  - live pane: 40 lines of a Claude Code TUI is mostly chrome (status bar, input box, spinner) — my own
    inspect run above spent ~15 of its 40 lines on non-content.
  - transcript fallback: each record is clipped to 400 chars, `switchboard/output.py:50` +
    `defaults/settings.toml:195-197` (`output_clip = 400`), so a long block message is cut mid-sentence.
- So: inspect shows *both* (recorded `why` in full, plus raw tail), but the tail is under half the size
  design truth asks for and the transcript path clips the message body.

Cross-check with DESIGN-TRUTH.md:270-271 (inspect is one of Andrew's three surfaces): inspect is **not**
gated to the human — any agent can run it, and status/board hints actively tell agents to
(`status.py:1087, 1101, 1104, 1119, 1139`; `broker.py:3140`). That is consistent with truth (truth says
which surfaces are *his*, not that they are exclusive), so no gap recorded — but note `sb board` IS
identity-gated (`cli.py:690-701`) and inspect is not, so the two "human surfaces" are enforced differently.

---

## 2. "`sb status` is not for Andrew — only `sb board` is." (DESIGN-TRUTH.md:210)

**Verdict: BROKEN**

`sb status` is repeatedly presented to the human as *his* surface — in human-facing output, in help text,
and in the code's own stated model of the world.

Evidence:
- `switchboard/status.py:1074-1079` — the `NEEDS YOU` section, commented:
  `# This IS the human's inbox. There is no other one: an agent that needs a person blocks, and a block is
  a row here until somebody answers it.` This is `sb status` output declaring itself the human's inbox.
- `switchboard/cli.py:769-772` — the *human* branch of `sb inbox` (reached only when `me == HUMAN`,
  `cli.py:764`) prints to Andrew: `"you have no inbox — agents that need you BLOCK, and a block waits for
  you in \`sb status --needs-me\` (answer with \`sb tell <agent> \"...\"\`)"`. That is human-facing output
  pointing the human at `sb status`. (It also points him at `sb tell`, which DESIGN-TRUTH:219-221 says
  Andrew does not use.)
- `switchboard/cli.py:796-797` — `sb block` tells the blocking agent: `"blocked — surfaced to the human,
  who will see it in \`sb status --needs-me\` until they answer"`. The system's stated model of where
  Andrew reads blocks is status, not board.
- `switchboard/cli.py:172` — `--mine` help: `"only your own subtree (for a human: every agent)"`. The help
  text has a human branch, i.e. status's CLI contract anticipates a human caller.
- `switchboard/cli.py:700` — when an agent is refused `sb board`: `"Use \`sb status\` for the same tree as
  text."` (This one is fine — it is addressed to an agent — but it does state the two are interchangeable
  views, which is the framing that lets status drift into the human's lane.)
- `switchboard/store.py:1324` and `broker.py:2681, 2824, 2880` all repeat "…until they deal with you /
  `sb status --needs-me`" as the human's reading path.
- Shape of the output: it is *both*. Agent-shaped parts exist (a parent's children, `--mine`), but
  `NEEDS YOU` / `UNDELIVERED` / `DRIFT` (`status.py:1066-1141`) are written for whoever can act on a
  human's behalf, in the second person ("NEEDS YOU"), with `→ sb tell` / `sb inspect` remedies.
- No identity gating at all: unlike `board` (`cli.py:690-701`, refuses any caller with an agent row),
  `status` has none, and nothing in its help says it is not the human's.

Main is identical (`/Users/andrew/Code/switchboard/switchboard/cli.py:766, 771, 797`).

---

## 3. "`sb log` is not for Andrew either, but it stays — it could be useful." (DESIGN-TRUTH.md:260)

**Verdict: SATISFIED**

Evidence:
- It exists: `switchboard/cli.py:317-319` — `lg = cmd("log", help="recent events (debugging)")`, with
  `--agent` and `-n` (default `config.setting("display.log_events")` = 30, `defaults/settings.toml:310-311`).
- Validated at `cli.py:418-421`; implemented at `cli.py:917-922`: reads `store.recent_events`, prints
  `id / agent / kind / payload[:80]` oldest-last, `--json` supported.
- Verified runnable: `./bin/sb log --help` in this tree prints the usage above.
- Audience: nothing surfaces it to Andrew. It is absent from `sb start` output (`cli.py:710-716`), from the
  board (`board.py` has no reference), and from every human-facing message. Its own help says
  "(debugging)". The only mentions are internal comments (`broker.py:2706, 3366, 3479`, `plugins.py:351`,
  `panel.py:511`) and a settings comment (`defaults/settings.toml:310`).
- It stays and is not hidden from agents (visible in `sb --help`), which matches "it stays — it could be
  useful".

Minor note, not a gap: `log` is listed under "a few more for the human" in the module docstring
(`switchboard/cli.py:3-5`), alongside `inspect` and `wait`. That is a comment, not behaviour, and it names
the wrong audience for `log`.

---

## 4. "Human-facing output is concise, skimmable and well formatted." (DESIGN-TRUTH.md:117-123)

**Verdict: BROKEN** — as an instruction to agents, it does not exist anywhere.

Where it should be given and is not:
- `defaults/protocol.md` (the injected protocol — its text matches the protocol block in this session's
  system prompt verbatim) says nothing about formatting human-facing output. Its only formatting rule is
  about the *parent*-facing summary: `protocol.md:110-116` — "Keep it to a line or two of plain, simple
  language: what you were asked, what you found or did, and what it means."
- The block instruction, `protocol.md:119-122`, is the whole of what an agent is told about writing for
  Andrew: "`sb block \"<why>\"` is the ONLY way to reach a human … They read that one message and open no
  files, so say in it what you were asked and where you are." No bullets, no lists, no sections, no
  diagrams, no numbered questions, no recommended answers.
- Grepped `defaults/` (protocol.md, prompts.toml, roles/*.md, presets/*.md, presets.toml, settings.toml),
  `switchboard/roles.py`, `switchboard/presets.py` for `skimmable|bullet|numbered|recommended answer|
  concise|well formatted|diagram|skim|recommend`: **zero hits** that are this instruction. The only near
  hits are `defaults/roles/orchestrator.md:30` (bullets become `;` separators when passed as an argument —
  the opposite advice, for message payloads) and `orchestrator.md:86-87` (the word "recommends" inside an
  unrelated example).

Element-by-element against DESIGN-TRUTH.md:117-123:

| required | present? | where |
|---|---|---|
| concise | partial | `protocol.md:113` ("a line or two"), but that is the `done` summary, i.e. parent-facing |
| skimmable / bullets / lists / nested lists / diagrams | **no** | nowhere |
| sections where they help, without overdoing spacing | **no** | nowhere |
| say what you did, then the result | partial | `protocol.md:114-115` — again parent-facing, not human-facing |
| then questions, numbered | **no** | nowhere |
| each question with a recommended answer | **no** | nowhere |
| applies to what is written before `sb block` | **no** | `protocol.md:119-122` gives only "say what you were asked and where you are" |

Related defect on the same surface: DESIGN-TRUTH.md:236-238 says the agent writes the full message in the
chat first and "Andrew will not see the `why`; it is just for bookkeeping. This must be made clear."
`protocol.md:121-122` instead tells the agent the human "read[s] that one message" — i.e. the `why` — and
`cli.py:796-797` confirms it to the agent on every block ("surfaced to the human, who will see it in
`sb status --needs-me`"). So the shipped instruction teaches the opposite model of where the human reads,
which is also why nothing ever tells the agent to write the long form in chat.

Does the tool's own human-facing output honour the style?
- Mostly yes, and this half is the healthy one. `status.render` / `_attention`
  (`switchboard/status.py:1066-1141`) uses capitalised section headings, one line per agent, aligned
  columns, and an explicit `→ <command>` remedy per row, with the stated rule at `status.py:1069-1070`
  ("Kept to one line per agent. A status readout that needs scrolling … gets skimmed past").
  `render_detail` (`status.py:1285-1372`) is sectioned most-urgent-first with clipped one-line entries.
  `board.py:256-297` is one line per agent.
- The prose emits are the weak spot: `cli.py:769-772`, `cli.py:796-797`, `cli.py:712-716`
  (`sb start`) and `_workspace_closed` (`cli.py:927+`) are running sentences, not bullets. These are short,
  so "concise" holds; "skimmable / bulleted" does not.
- Note `switchboard/output.py` does no human formatting of its own — it is a reader (`output.py:1-27`);
  the formatting lives in `status.render_detail`.

---

## Gaps

1. `display.output_lines` is 40 (`defaults/settings.toml:305`), but design truth asks `sb inspect` for
   ~100 lines of tail. Raise the default to 100 (same on main).
2. A 40-line pane tail is largely TUI chrome, so a blocked agent's full chat message is often not readable
   in `sb inspect` at all — worth verifying against a real block after the bump, not just raising the number.
3. `switchboard/output.py:50` / `defaults/settings.toml:197` clip each transcript record to 400 chars, so
   inspect's transcript fallback truncates a long block message mid-sentence. Either raise the clip or
   exempt the block message from it.
4. `switchboard/status.py:1074-1079` calls the `NEEDS YOU` section of `sb status` "the human's inbox".
   Design truth says only `sb board` is Andrew's. Move that framing to the board, or state in status that
   it is the agent-side view.
5. `switchboard/cli.py:769-772` — the human branch of `sb inbox` points Andrew at `sb status --needs-me`
   (and at `sb tell`, which he does not use). Should point at `sb board`.
6. `switchboard/cli.py:796-797` — `sb block` tells the agent the human reads its `why` in
   `sb status --needs-me`. Wrong surface (should be the board) and wrong model (DESIGN-TRUTH:236-238 says
   Andrew never sees the `why`).
7. `switchboard/cli.py:172` — `--mine` help carries a "(for a human: …)" branch; status's help should not
   have a human audience at all.
8. `sb board` is identity-gated (`cli.py:690-701`) but `sb status` has no counterpart marking, so nothing
   stops or discourages the human from treating status as his readout.
9. No instruction anywhere in `defaults/` tells an agent how to format human-facing output. Add the
   DESIGN-TRUTH:117-123 rule (bullets/lists/nested lists/diagrams; sections without over-spacing;
   what you did → the result → numbered questions each with a recommended answer) to `defaults/protocol.md`
   next to the `sb block` paragraph.
10. `defaults/protocol.md:121-122` tells the agent the human reads the `why`, contradicting
    DESIGN-TRUTH:236-238; nothing tells the agent to write the full message in chat before calling
    `sb block`.
11. Prose emits at `cli.py:712-716`, `769-772`, `796-797` and `_workspace_closed` are sentences rather than
    skimmable lines — the one part of the tool's own output that does not follow its own rule.
12. `switchboard/cli.py:3-5` lists `log` among the commands "for the human"; design truth says it is not.
    Comment-only, but it is the file's stated audience map.
