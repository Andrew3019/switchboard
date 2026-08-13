# The 1024-byte ceiling on a spawn, measured — and what it costs to stop paying it

Work by agent `prompt-via-file` on branch `prompt-via-file`, forked from `main` at
`d23a05a`. Everything below was measured before anything was built; phase 2 was
conditional on phase 1 coming out as predicted, and it did. `DESIGN-TRUTH.md` untouched.

## 1. The claim under test

`agent start` types the provider CLI's whole command line into the pane's shell, and that
line carried the ~12KB system prompt as one quoted argument. While a shell is still
running its startup files the tty is in **canonical mode**, where the line discipline keeps
`MAX_CANON` bytes of a typed line and silently discards the rest.

The claim: **the limit applies to the characters typed, not to the argument that results.**
A short line that names a file should therefore deliver the whole prompt even in canonical
mode, because the shell reads the short line first and expands it afterwards in its own
memory.

## 2. Phase 1 — the measurement

At the herdr layer, the way PR #23's A/B was done. Each trial creates a fresh tab and
writes into it **at once**, with no warm-up — the moment `agent start` would go in. The
probe is a two-line shell script that prints the **length and md5 of `argv[1]` as the
process received it**, so "the command parsed" and "the prompt arrived whole" are separate
answers. 8 trials per arm, `/tmp/.../probe/measure.py`.

| arm | what is typed | bytes typed | result, 8 trials |
|---|---|---|---|
| `calib-long` | probe + 12KB of quote-free payload | 12,143 | **8/8 truncated**, `len=881` every time |
| `literal-long` | probe + the real prompt, `shlex.quote`d | 12,181 | **8/8 left on `dquote>`** — the quote cut open mid-argument |
| `file-short` | `probe "$(cat <path>)"` | **300** | **8/8 delivered 12,078 bytes, md5 exact** |

The calibration arm is the number that matters: the probe path is 142 bytes, plus a space,
plus the 881 bytes that arrived, is **exactly 1024** — `MAX_CANON` in
`sys/syslimits.h`, reproduced 8 times out of 8 with no variance at all. The literal arm is
the shipped fault verbatim: a command cut inside the quote around the prompt.

**The new ceiling.** What the process receives is now bounded by `ARG_MAX`, which is
**1,048,576** on this machine — about 86× the 12KB prompt, against the 1024 bytes that
bounded it before. The typed line went from 12KB to ~300 bytes, so it uses under a third of
the canonical-mode budget even if the shell is not ready.

## 3. The part of the claim that did NOT survive: `"$(cat …)"`

The provider-neutral form works when typed straight into a shell (arm 3 above) and is dead
through the layer spawns actually use. Measured with a 116-byte file holding a codeword and
a live `claude`:

| how the prompt was passed to `herdr agent start` | did the agent know the codeword? |
|---|---|
| `--append-system-prompt '$(cat <path>)'` | **no** — it went and read the file with a tool call |
| `--append-system-prompt-file <path>` | **yes**, answered `ZEPHYR-771` |

herdr shell-quotes every agent argument (that is the same encoding that rejects a newline
in one), so the substitution never runs and the **literal string `$(cat <path>)` becomes
the agent's system prompt**. That is the worst failure available: it parses, it starts, and
nothing complains — an agent with no protocol.

So the build uses the provider's own flag. Everything else in `agent_args` is a Claude Code
flag already (`--permission-mode`, `--settings`, `--append-system-prompt`), so it is no new
coupling; another provider needs its own equivalent, and the note in `_prompt_flags` says
so.

Whole-prompt check, since a 116-byte file proves nothing about 12KB: the same test with a
**12,195-byte** file of real protocol text and the codeword as its **last sentence** —
answered `QUASAR-903`. The end of the file arrives.

## 4. Phase 2 — what was built

- `herdr._prompt_flags` joins the fragments and hands down
  `--append-system-prompt-file <path>` instead of 12KB of typed argument.
- `herdr.write_prompt_file` / `prompt_file_path` / `forget_prompt_file`. The file sits
  beside the report gate's settings file under the shared `.git` (`store.store_dir`), keyed
  by agent name, name-checked against `validate.AGENT_NAME` so nothing joins an unchecked
  string onto a path. Tmp-then-rename, as the settings file does, because spawns race here.
- **Loud, not best-effort.** It is written and read back before `agent start` is called, and
  a failure raises `PromptFileError` — the spawn fails and the broker records the husk.
  `stop_hook_args` may degrade to `[]` because a missed nudge costs a visible stalled row;
  a missing system prompt costs the agent every rule it has, silently.
- `sb cleanup` deletes it where it closes the board, so files do not accumulate.
- `_ready_pane` is **untouched**.

## 5. Proof

- **The case that started this.** `sb delegate` in a scratch repo that is not switchboard,
  driven by an isolated clone's own `./bin/sb`. The agent came up with a **6,874-byte**
  system prompt and was asked two things only the protocol teaches. It answered both — what
  `--when-idle` does (early in the protocol) and that `sb block` is the only way to reach a
  human (late in it) — and reported with `sb done`, which nothing else would have told it to
  do. Its prompt file was gone from the store after `sb cleanup`.
  - `sb start` itself was **refused**, correctly and by design: `_agent_caller` stops an
    agent creating a top orchestrator from a clone. `sb delegate` exercises the same
    `_ready_pane` + `start_agent` + prompt-delivery path; what is unproven is the
    orchestrator role's own fragments, which differ only in content.
- **Suite:** `1157 passed` (1155 on `main`, +4 new, −2 replaced).
- **Acceptance**, `./acceptance/accept.py prompt-via-file`, verbatim:

```
  1  a cold fan-out of six starts six         PASS   6/6 took their task and reported into 6 new checkouts, 0 spawns misreported   [36s]
  2  a child's report wakes its parent        PASS   deferred while the parent worked, then delivered by the doorbell 49s later; the parent woke and read it   [2m04s]
  3  a block holds until the human answers    PASS   held 26s against a sibling, released by the human's answer and read it   [1m37s]
  4  a sweep names what it refused            PASS   closed 1, refused 1 and said why: 'refused sbc0hy9m4-k: blocked, not finished — it has not reported an end'   [45s]

all 4 pass — the fleet is sound   (2m10s)
```

Everything was run in throwaway clones and scratch repos; every pane, workspace, worktree
and clone created here was torn down, and no unscoped `pkill` was used.

## 6. Could `_ready_pane` be dropped now?

It could, and it should not be dropped on this evidence. The 12KB line was the only thing
`MAX_CANON` could plausibly cut; a ~300-byte line has two thirds of the budget spare, so the
truncation this was written for cannot recur. But `_ready_pane` does two other things that
are not about length: it **pins the checkout's own `bin/` on PATH**, which is what keeps a
worktree's agents running that worktree's code, and it is the one place a pane is **proved
to answer at all** before a spawn is attempted. Dropping it would take those with it. It is
insurance now rather than the mechanism, which is the right place for a timing fix to end
up.

## 7. Noticed, not fixed

- **Prompts could now be multi-line.** The single-line rule was herdr's, about arguments; a
  file has no such limit. The check in `start_agent` is kept and its comment now says why —
  every prompt in `defaults/` is written single-line and `sb presets` reads them back that
  way, so lifting it is somebody's decision, not a side effect of this.
- `sb restore` passes `--resume` and no prompts, so it delivers no system prompt at all and
  never did. Unchanged here, and worth someone confirming that a resumed session really
  keeps its protocol.
- The 200-character clip on a `done` summary cut the proof agent's second answer out of the
  stored event; the full text was only recoverable from its transcript.
