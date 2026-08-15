# Does codex have a per-agent, repo-untouched prompt channel? — yes: `CODEX_HOME`

**Answer: yes.** Pointing `CODEX_HOME` at a private, per-agent scratch directory containing
its own `AGENTS.md` and `config.toml` gives switchboard a full standing-instructions channel
for codex that never touches the repo, is per-agent, applies on every turn, in both
`codex exec` and the interactive TUI, has no meaningful size limit, needs no line-flattening,
and can pre-seed trust so a fresh worktree never blocks. It also doubles as the place to set
model, reasoning effort, sandbox mode, and the `notify` hook — everything switchboard sets
per-agent for Claude Code today.

Investigated by running `codex-cli 0.147.0` against scratch repos and scratch `CODEX_HOME`
dirs under the scratchpad directory (`.../scratchpad/probe2/...`, all deleted afterward).
Builds on `notes/codex-scout-cli-behaviour.md`, which established the two real instruction
channels (`AGENTS.md` files, `config.toml`) and that there is no appended-system-prompt flag.
This probe answers the follow-up questions that note left open.

Legend: **VERIFIED** = ran the command and observed it directly. **READ** = docs/help text
only. **ASSUMED** = inferred, not directly tested — flagged explicitly wherever it appears.

## 1. `CODEX_HOME/AGENTS.md` as a global instructions channel — VERIFIED, works as hoped

Set up a private `CODEX_HOME` (`.../home`) with its own `AGENTS.md` ("Always prepend
`HOMEAGENTS:` to every reply.") and a `config.toml` pre-seeding trust for the scratch repo
directory, then ran `codex exec --json "Say hi in one word."` from that repo with no repo-level
`AGENTS.md` present:

```
$ export CODEX_HOME=.../home
$ codex exec --json "Say hi in one word."
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"HOMEAGENTS: Hi"}}
```

Confirmed by reading the raw rollout JSONL (`$CODEX_HOME/sessions/.../rollout-*.jsonl`) for the
injected `user`-role message — same injection mechanism the earlier scout note documented for
repo `AGENTS.md`, just sourced from `CODEX_HOME` instead:

```
# AGENTS.md instructions for <repo path>

<INSTRUCTIONS>
Always prepend "HOMEAGENTS:" to every reply.
</INSTRUCTIONS>
```

**Combination with a repo `AGENTS.md`, and order — VERIFIED.** Added a repo-level
`AGENTS.md` ("Always append ` [REPOAGENTS]` at the very end of every reply.") alongside the
`CODEX_HOME` one and re-ran:

```
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"HOMEAGENTS:Hi [REPOAGENTS]"}}
```

The rollout shows they are **merged into a single injected block**, `CODEX_HOME` doc first,
repo doc second, separated by a literal `--- project-doc ---` marker:

```
<INSTRUCTIONS>
Always prepend "HOMEAGENTS:" to every reply.

--- project-doc ---

Always append " [REPOAGENTS]" at the very end of every reply.

</INSTRUCTIONS>
```

So `CODEX_HOME/AGENTS.md` acts as the *global* doc and repo `AGENTS.md` as the *project* doc;
codex concatenates both when both exist, global first. Switchboard would only ever populate
the global (`CODEX_HOME`) slot, never a repo file, so this never matters in practice — but it's
useful to know a human's own repo `AGENTS.md` (if one ever exists) would still be respected
underneath switchboard's prompt, not clobbered by it.

**TUI, not just `exec` — VERIFIED.** Launched the interactive TUI in a fresh scratch repo
(`repo2`, never seen by codex before, this session's own private `CODEX_HOME`) and ran
`/status`:

```
Agents.md:  .../home_notrust/AGENTS.md
```

The status panel names the exact `CODEX_HOME` file it loaded, confirming it applies in the TUI
too, not just `exec`.

## 2. Size — VERIFIED, no practical limit for a 12KB prompt, and the global file is *not*
   subject to `project_doc_max_bytes` at all

- **`project_doc_max_bytes` default: 32768 (32 KiB), confirmed empirically.** Wrote a
  59059-byte repo `AGENTS.md` with unique markers at known offsets. The injected text truncated
  the repo doc at exactly **32768 bytes** — matching prefix computed byte-for-byte
  (`matching prefix length: 32768`), truncation is silent (no ellipsis, no error, no warning to
  the model), mid-line.
- **Critical finding: that limit only applies to the repo/project-level doc, not the
  `CODEX_HOME` global doc.** Wrote a 35031-byte `CODEX_HOME/AGENTS.md` with start/end markers
  and re-ran with a trivial repo `AGENTS.md` present: both `HOMEMARKERSTART` and `HOMEMARKEREND`
  came through in full — the global doc was **not** truncated at 32KB, or at all up to the
  35KB tested. (Not tested past 35KB — treat "no limit at all" as unconfirmed above that size,
  but a realistic ~12KB switchboard prompt is nowhere near either boundary.)
- **Realistic-size, multi-line markdown test — VERIFIED.** Wrote a ~10KB `CODEX_HOME/AGENTS.md`
  with headers, a 200-line bullet list, and a code fence, with a codeword buried near the end
  ("If asked for the secret codeword, respond with: PINEAPPLE-42."). Asked codex for the
  codeword; got back exactly `PINEAPPLE-42`, proving the whole file is read and followed, not
  just the head of it.

## 3. `project_doc_fallback_filenames` — VERIFIED, it is a true fallback, not a merge, and not
   needed given `CODEX_HOME` works directly

- Removed repo `AGENTS.md`, added a repo file named `FALLBACK.md`
  ("Always end every reply with the word BANANA."), and ran with
  `-c 'project_doc_fallback_filenames=["FALLBACK.md"]'`: reply came back `Hi! BANANA` — the
  fallback name is read as the project doc when `AGENTS.md` is absent.
- Re-added a repo `AGENTS.md` ("Always start every reply with the word MANGO.") alongside the
  same `FALLBACK.md` and re-ran with the same `-c` override: reply was `MANGO. Hi!` — **BANANA
  did not appear.** So `project_doc_fallback_filenames` is only consulted when `AGENTS.md` is
  absent, exactly as its name implies; it does not merge with an existing `AGENTS.md`.
- This key is a config override (`-c ...` or in `config.toml`), so it could in principle be
  layered into `CODEX_HOME/config.toml` to point at a gitignored, differently-named repo file —
  but since `CODEX_HOME/AGENTS.md` already gives a channel with no repo footprint at all, this
  key isn't needed by switchboard's design. Documenting it here only because the task asked.

## 4. One-line constraint — VERIFIED, does not apply to codex; the file channel is unconstrained

Every test above used real multi-line markdown (headers, bullet lists, a fenced code block,
multi-line prose) written directly to `CODEX_HOME/AGENTS.md` with a normal `Write`/heredoc, and
codex read and obeyed all of it. Switchboard's single-line flattening for herdr's agent-argument
limit is a Claude-Code-specific constraint (`--append-system-prompt-file` argument handling
mentioned in the scout note) — it would be **unnecessary** for a `CODEX_HOME`-based prompt
channel, since the payload is a file, not an argument, and files have no such limit.

## 5. Trust prompt — VERIFIED, per-agent `CODEX_HOME` re-triggers it, and it can be pre-seeded
   to never block

- **`exec` never hits the trust prompt at all**, trust-seeded or not. Ran `codex exec` in a
  brand-new repo (`repo2`, never seen by codex before) with a `CODEX_HOME` that had **no**
  `config.toml` and thus no trust entry whatsoever: it ran cleanly (`EXIT:0`), and no
  `config.toml` was ever auto-created afterward. This matches (and confirms) the earlier scout
  note's tentative observation that `exec` doesn't hit the prompt.
- **The TUI does hit it, in a fresh `CODEX_HOME` + fresh repo.** Launched `codex` (TUI, via
  tmux) in that same never-seen `repo2`, with the same trust-less `CODEX_HOME`:
  ```
  Do you trust the contents of this directory? Working with untrusted contents comes with
  higher risk of prompt injection. Trusting the directory allows project-local config, hooks,
  and exec policies to load.
  › 1. Yes, continue
    2. No, quit
  ```
- **Pre-seeding suppresses it — VERIFIED.** Wrote
  `[projects."<abs repo2 path>"]\ntrust_level = "trusted"` into that same private
  `CODEX_HOME/config.toml` and relaunched the TUI in the same never-seen repo: no trust prompt,
  straight to the normal input screen, and `/status` confirmed the session came up trusted with
  the `CODEX_HOME/AGENTS.md` loaded. So a per-agent `CODEX_HOME` needs its own trust entry
  pre-seeded (the real `~/.codex/config.toml`'s trust entries do not apply — they're keyed by
  absolute repo path in a *different* file), but doing so works and is a plain TOML write, no
  interactivity needed.

## 6. Per-agent config in one place — VERIFIED: model, effort, sandbox, and `notify` all work
   from the same private `config.toml`

Wrote one `CODEX_HOME/config.toml` with all four at once:

```toml
model = "gpt-5.4-mini"
model_reasoning_effort = "low"
sandbox_mode = "read-only"
notify = ["<path>/notify_probe.sh"]

[projects."<repo path>"]
trust_level = "trusted"
```

Ran a single `codex exec` turn and verified each setting actually took effect, not just parsed:

- **Model**: rollout JSONL logged `"model":"gpt-5.4-mini"` for the turn (the model's own
  free-text answer to "what model are you" was unreliable — `UNKNOWN` — so this was checked
  against the rollout log instead, which is authoritative).
- **Reasoning effort**: rollout logged `"effort":"low"` / `"reasoning_effort":"low"`.
- **Sandbox**: asked the model to `touch /tmp/should_not_be_created_probe.txt`; it reported
  back `touch: ...: Operation not permitted`, and the file was confirmed absent afterward.
- **`notify`**: the hook script fired with the same JSON payload shape documented in the scout
  note (`agent-turn-complete`, thread/turn ids, `last-assistant-message`), logged to a file
  outside the sandbox.

So `CODEX_HOME` is a genuine one-stop per-agent home: the standing-instructions file, trust
state, model/effort/sandbox, and the turn-completion hook all live in the same private
directory switchboard would create per agent, symmetric with how it already composes one
prompt file per agent for Claude Code.

## Bottom line for point 7 (least-bad alternative)

Not needed — `CODEX_HOME` works cleanly for everything the task asked about, so there's no
fallback to recommend. The one prerequisite worth calling out: `CODEX_HOME` needs its own
copy of (or a way to read) `auth.json`, or codex fails every request with 401s from the
Responses API — confirmed directly (first attempt against an auth-less private `CODEX_HOME`
failed with repeated `401 Unauthorized` / `Missing bearer or basic authentication` errors on
both the websocket and HTTPS fallback; copying `~/.codex/auth.json` into the private
`CODEX_HOME` fixed it immediately). Switchboard would need to either symlink/copy the real
`auth.json` into each per-agent `CODEX_HOME`, or find/set `OPENAI_API_KEY` some other way —
not otherwise investigated here.

## Practical shape for switchboard, given all of the above

Per agent, before spawning codex:
1. Create a private scratch dir, e.g. `.git/agentflow/codex-home/<agent>/`.
2. Write the composed prompt (unflattened, real markdown) to `<that dir>/AGENTS.md`.
3. Write `<that dir>/config.toml` with `[projects."<abs worktree path>"] trust_level =
   "trusted"`, plus model/effort/sandbox/`notify` as needed.
4. Copy or symlink `auth.json` into that dir (or otherwise get real credentials into it).
5. Spawn `codex`/`codex exec` with `CODEX_HOME=<that dir>` and cwd at the worktree.

This mirrors the existing `--append-system-prompt-file` pattern closely enough that the same
"compose once per agent, write to a private file, point the CLI at it" logic should be directly
reusable, just swapping the file target and adding the `CODEX_HOME` env var plus the one-time
trust/auth seeding.

## What's unverified / not attempted

- Whether `CODEX_HOME/AGENTS.md` has *any* upper size limit — only tested up to 35KB
  untruncated; did not push further since 12KB (the realistic switchboard prompt size) is well
  under any boundary that showed up.
- Whether nested/subdirectory `AGENTS.md` files interact with a `CODEX_HOME` global doc — not
  tested, same open question the scout note already flagged for the repo-only case.
- Whether `codex resume`/`codex fork` sessions started under one `CODEX_HOME` behave any
  differently when later invoked with a different `CODEX_HOME` — not tested.
- The full mechanics of getting `auth.json`/credentials into a per-agent `CODEX_HOME` at scale
  (symlink vs. copy vs. shared read-only mount) — only did a plain file copy for this probe.

## Cleanup performed

- Deleted every session created during this probe via `codex delete --force <id>`, run against
  each scratch `CODEX_HOME` used (both `.../probe2/home` and `.../probe2/home_notrust`) — all
  reported `Deleted session <uuid>.`, confirmed the sessions directories were empty afterward.
- Declined ("No, quit") the one interactive trust prompt shown before testing pre-seeded trust.
- Confirmed the real `~/.codex/config.toml` has no trace of the scratch repo paths used in this
  probe (`grep -i probe2 ~/.codex/config.toml` — no output) — every run used an explicit
  `CODEX_HOME` override, so the real file was never touched.
- Killed both tmux probe sessions (`codexprobe2`, `codexprobe3`) and confirmed via `ps` that no
  `codex` process was left running afterward.
- Deleted the entire scratch tree (`.../scratchpad/probe2/`), including both scratch repos, both
  private `CODEX_HOME` dirs, and the copied `auth.json`.
