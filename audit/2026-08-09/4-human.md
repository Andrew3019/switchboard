# Audit group 4 — HUMAN SURFACES

Audited against `/Users/andrew/.herdr/worktrees/switchboard/worker-2/DESIGN-TRUTH.md` (the only trusted
document). All other docs treated as untrusted; code comments verified against code.

**Which tree.** Source read is the worktree `/Users/andrew/.herdr/worktrees/switchboard/worker-2`
(branch `worker-2`, HEAD a9dd319). The `sb` on PATH is a symlink to `/Users/andrew/Code/switchboard/bin/sb`
— a **different checkout**, branch `main` at caa6d20 — so every `sb` run exercised main, not the audited
worktree. Checked in both directions: main's recent commits are workspace-teardown work only, and
`board.py`, `panel.py`, `cli.py` are byte-identical between the two trees. **Main fixes none of the
findings below.**

Detail reports: `/tmp/sb-audit-4a-block.md`, `/tmp/sb-audit-4b-read.md`, `/tmp/sb-audit-4c-board.md`.

## Verdicts

| # | Design-truth entry | Verdict |
|---|---|---|
| 1 | Blocking agent writes the full message in chat first; `why` is bookkeeping Andrew never sees (:233-236) | **BROKEN** |
| 2 | After Andrew answers a block the agent just continues (:237) | **PARTIAL** |
| 3 | `sb inspect` is how Andrew reads a blocked agent; ~100 lines of tail (:245-246) | **PARTIAL** |
| 4 | `sb board` stays as it is — full tree, nested, archived collapsed, click to focus (:174-179) | **PARTIAL** |
| 5 | The click is not working sometimes; Andrew believes the side panel (:181-182) | **DIAGNOSED — cause is not the side panel** |
| 6 | `sb status` is not for Andrew, only `sb board` is (:210) | **BROKEN** |
| 7 | `sb log` is not for him but it stays (:260) | **SATISFIED** |
| 8 | When something needs me, the board shows it (:187-188) | **PARTIAL** |
| 9 | Human-facing output is concise and skimmable (:117-123) | **BROKEN** |
| 10 | Agents avoid blocking unless really needed, and its five triggers (:124-127) | **PARTIAL** |

Counts: SATISFIED 1 · PARTIAL 4 · BROKEN 3 · plus entry 4 PARTIAL and entry 5 an investigation.
(By verdict column: 1 satisfied, 5 partial, 3 broken, 1 diagnosis.)

---

## 1. Block writes the message in chat; `why` is bookkeeping — BROKEN

- No prompt anywhere instructs an agent to write the full "need human input: …" message in its chat
  before calling `sb block`.
- `defaults/protocol.md:119-122` teaches the **opposite**: the human "read that one message, so say in it
  what you were asked" — i.e. put the human-facing content into `why`.
- The `why` **is** shown to the human in six places: desktop notification `broker.py:3466`; herdr state
  message `broker.py:2902`; `sb status --needs-me` `status.py:1081-1084`; `sb inspect` `status.py:1298-1299`;
  the board `board.py:200-201`; JSON `status.py:295`.
- The bookkeeping-only nature is stated nowhere; `sb block --help` gives `why` no help string at all
  (`cli.py:161-162`).

## 2. After Andrew answers, the agent just continues — PARTIAL

- The resume itself is correct: `sb tell` → `_unblock_if_needed` (`broker.py:3429`, `:3440-3460`) pushes
  herdr WORKING and pokes the same session — it continues rather than restarting.
- But the **only** channel that clears a block is `sb tell`, which DESIGN-TRUTH:229-231 says Andrew does
  not use. Typing into the pane leaves the row blocked forever.
- The related rule at DESIGN-TRUTH:223-225 (when-idle mail held until a block is answered) is not
  implemented: `sb tell` has no delivery-mode flags at all (`cli.py:148-151`).

## 3. `sb inspect` — PARTIAL

- Exists and prints the recorded block `why` unclipped (`status.py:1298`).
- Tail defaults to **40** lines, not ~100 (`defaults/settings.toml:305`, `status.py:1163`); confirmed by
  running it. Same on main.
- It shares `display.output_lines` with other output, so it needs its own setting rather than a bump.
- Transcript records are clipped to 400 chars (`output.py:50`, `settings.toml:197`), truncating a long
  block message mid-sentence in the fallback path.

## 4. `sb board` stays as it is — PARTIAL

- Full tree SATISFIED (`board.py:258`), nesting SATISFIED (`board.py:287`), archived collapsed SATISFIED
  (`board.py:280-285` + `status.display_rows`).
- Click-to-focus is correct in mechanism (`board.py:525-534` → herdr agent focus) but intermittently
  defeated by the bug in §5.
- Two rejected-design items still present: `--no-board` (`cli.py:113`, `cli.py:256`) though
  DESIGN-TRUTH:293 rejects it; `sb workspace new --focus` (`cli.py:255`) is focus-as-a-flag, rejected at
  DESIGN-TRUTH:295.

## 5. The click — root cause, and it is **not** the side panel

`board._fit` / `_visible_len` (`board.py:331-344`) and `status.clip` (`status.py:1018-1020`) measure
**code points, not terminal columns**. A row whose task or summary text contains an emoji, CJK or
combining character draws wider than the pane, wraps to a second line, and pushes every row below it down
one — while `agent_at` (`board.py:317`) still maps the raw mouse row against the *unwrapped* list. The
click therefore lands on the wrong agent, or on a padding line where it silently does nothing.
Reproduced by driving `board.layout` at width 44: a 44-code-point row occupies 45 columns.

The side panel is a **contributing** cause only: `panel.py` is a snapshot collector and draws nothing,
but the board opens at 34% width (`board.py:81`), which puts nearly every row at the truncation limit
where a single wide glyph tips it over. Widen the pane and the same clicks work — which is exactly why it
looks like the panel.

Ranked alternates: the multiplexer swallowing the first click; `is_left_click` requiring `button == 0`
exactly, so modifier-held clicks are dropped (`board.py:136`).

## 6. `sb status` is not for Andrew — BROKEN

It is actively presented as his surface:
- `status.py:1074` comments the `NEEDS YOU` section as "This IS the human's inbox".
- `cli.py:769-772` — the human branch of `sb inbox` sends him to `sb status --needs-me` (and to `sb tell`,
  which he does not use).
- `cli.py:796-797` — `sb block` tells the agent the human reads its `why` there.
- `cli.py:172` — `--mine` help carries a "(for a human: …)" branch.
- `sb board` is identity-gated (`cli.py:690-701`); `sb status` has no counterpart marking.

## 7. `sb log` — SATISFIED

Exists (`cli.py:317`, `cli.py:917`), help labels it "(debugging)", surfaced to no human path. One nit:
`cli.py:3-5` lists `log` among commands "for the human" in a comment.

## 8. When something needs me, the board shows it — PARTIAL

Blocked agents are marked by glyph, word plus reason, an arrow marker and a header count
(`board.py:156-218`, `:294`, `status.py:1043`) — but never sorted, pinned or hoisted, so a blocked row can
scroll off-screen behind a dim `+N more below` (`board.py:259-307`) that does not say how many hidden rows
need a human. As the **only** notification channel (DESIGN-TRUTH:239-240) that is thin. The board also has
no `NEEDS YOU` list; only `sb status` does (`status.py:1079`), and that readout is explicitly not his.

## 9. Human-facing output is concise and skimmable — BROKEN

The rule at DESIGN-TRUTH:117-123 is given to agents **nowhere**: grep of `defaults/`, `roles.py`,
`presets.py` finds zero hits for it. The tool's own structured readouts (status, board, inspect) are
sectioned and skimmable; the prose emits (`cli.py:712-716`, `:769-772`, `:796-797`, `_workspace_closed`)
are sentences.

## 10. Avoid blocking unless really needed, and its five triggers — PARTIAL

- Two of the five triggers exist in weaker wording; **three are absent**: explicitly told to block; going
  back and forth with the agent itself; finished work needing Andrew's input or approval.
- The last of those is actively contradicted by `orchestrator.md:195-196` ("do not use it to report").
- The umbrella framing "avoid blocking unless it is really needed" is stated nowhere — blocking is
  presented as an available verb with two prohibitions, not a last resort.
- `protocol.md:117-118` carries two triggers not among the confirmed five ("an instruction is ambiguous",
  "about to do work you were told to delegate").

---

## Gaps (build tasks)

**Blocking**
1. `defaults/protocol.md:119-122` tells agents to put human-facing content in `why`; DESIGN-TRUTH:233-235 says the message goes in chat and `why` is unseen — reconcile, then align `roles/researcher.md:10-11` and `protocol.md:52-54`.
2. No prompt instructs "write the full 'need human input: …' message in chat before calling `sb block`" — add it.
3. The bookkeeping-only nature of `why` is stated nowhere; `sb block --help` gives `why` no help string (`cli.py:161-162`).
4. `why` is surfaced to the human in six places (`broker.py:3466`, `broker.py:2902`, `status.py:1081-1084`, `status.py:1298-1299`, `board.py:200-201`, `status.py:295`) — re-point them at the pane tail if the truth stands.
5. Answering by typing into the pane never clears `blocked`; only `sb tell` calls `_unblock_if_needed` (`broker.py:3429`). Needs a pane-typed-answer path or an explicit human unblock verb.
6. `sb tell` has no delivery modes (`cli.py:148-151`); DESIGN-TRUTH:216-227's three modes are one, so when-idle mail cannot be held for a blocked agent.
7. **Mail to a blocked agent silently cancels the block**: blocked pushes herdr IDLE (`broker.py:2902`), `_busy` says not-busy (`broker.py:3296-3302`), `flush_pending` rings (`broker.py:3348-3350`), `_ring` unblocks (`broker.py:3429`). Gate on store state `blocked` for non-human senders.
8. Three block triggers missing from every prompt: explicitly told to block; going back and forth with the agent; finished work needing approval.
9. `orchestrator.md:195-196` ("do not use it to report") contradicts the finished-work-needing-approval trigger — needs an exception.
10. "Avoid blocking unless really needed" is stated nowhere as a norm.
11. `protocol.md:117-118` carries two unconfirmed triggers — reconcile or confirm.

**Reading surfaces**
12. `display.output_lines` is 40 (`defaults/settings.toml:305`); raise `sb inspect` to ~100 via its own setting.
13. A 40-line pane tail is largely TUI chrome — verify a real block message is actually readable after the bump.
14. `output.py:50` / `settings.toml:197` clip transcript records to 400 chars, truncating long block messages; raise or exempt.
15. `status.py:1074-1079` calls status's `NEEDS YOU` "the human's inbox" — move that framing to the board.
16. `cli.py:769-772` points the human at `sb status --needs-me` and `sb tell` — should point at `sb board`.
17. `cli.py:796-797` tells the blocking agent the human reads `why` in status — wrong surface and wrong model.
18. `cli.py:172` `--mine` help has a "(for a human: …)" branch; status should have no human audience.
19. `sb board` is identity-gated (`cli.py:690-701`) but `sb status` has no counterpart marking.
20. No instruction in `defaults/` tells an agent how to format human-facing output — add DESIGN-TRUTH:117-123 next to the `sb block` paragraph in `protocol.md`.
21. Prose emits (`cli.py:712-716`, `:769-772`, `:796-797`, `_workspace_closed`) are sentences, not skimmable lines.
22. `cli.py:3-5` lists `log` among commands "for the human".

**Board**
23. `_fit`/`_visible_len` (`board.py:331-344`) measure code points not columns — use a display-width measure (east-asian width, combining marks, emoji) in both `_fit` and `status.clip`.
24. Nothing sanitises agent-authored text of ambiguous-width characters before it reaches a fixed-width row; `status.clip` (`status.py:1018-1020`) flattens whitespace only.
25. `is_left_click` (`board.py:136-137`) matches `button == 0` exactly, dropping modifier-held and motion-tagged clicks; mask like `scripts/05-mouse.py:66-80`.
26. Nothing verifies the SGR row the board receives is pane-local; `agent_at` (`board.py:317`) assumes it.
27. Wheel scrolling does not clamp `top` (`board.py:521`) against `layout`'s clamp (`board.py:260`).
28. `--no-board` exists (`cli.py:113`, `:256`) though DESIGN-TRUTH:293 rejects it; `board.py:4`, `:40-41` still document it as intentional.
29. `sb workspace new --focus` (`cli.py:255` → `cli.py:888` → `broker.py:824`) is focus-as-a-flag, rejected at DESIGN-TRUTH:295.
30. The board never hoists, pins or sorts an agent needing a human (`board.py:258-298`).
31. `+N more below` (`board.py:303-307`) does not say how many hidden rows need a human, though collapsed-archived sets the precedent (`status.py:821-834`).
32. The board has no `NEEDS YOU` list; only `sb status` has one (`status.py:1079`).

## Process notes
- The `sb` on PATH is a different checkout from the audited worktree (see header). Every finding was
  cross-checked against main; none is already fixed there.
- No live blocked agent existed, so the block-rendering findings for entries 1-2 are evidenced from code
  plus `sb status --needs-me --json`, not from a real blocked row.
- No `audit-sim-*` agents were spawned by this group; nothing was left behind.
- Read-only throughout: no repo file was changed; `git status` clean.
