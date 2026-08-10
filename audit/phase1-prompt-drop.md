# Phase 1, item 1.2 — do spawns drop all system prompts but the last?

**REFUTED at current HEAD (`f6bcd58`).** Every prompt fragment reaches the agent. The bug
was real when the cited evidence was taken and was fixed 4.5 minutes later, on
2026-08-08; BUILD-PLAN.md item 1.2 has been stale ever since.

## Which binary was exercised

`sb` on PATH is `/Users/andrew/.local/bin/sb` → `/Users/andrew/Code/switchboard/bin/sb`,
i.e. the MAIN checkout, not this worktree. `diff -rq` over `bin/` and `switchboard/`
between the two shows differences only in `__pycache__/*.pyc`; every `.py` source file is
identical, and both are at `f6bcd58`. So the binary I exercised is the code in this
worktree.

## Empirical evidence — three throwaway spawns

Three agents were spawned with different, stacking combinations of prompt sources, each
told to read its own system prompt and answer YES/NO with a verbatim quote for eight
marker phrases. Reports in `/tmp/sb-prompt-probe/probe-{a,b,c}.md`; verdicts also arrived
as `sb done` summaries and agreed with the files.

Markers: (1) `SWITCHBOARD PROTOCOL` (2) `sb plugin report-bug` — the `@report-bug` plugin
fragment bound to `all` (3) `You are a researcher.` (4) `You are QA.` (5) `Report only
what you actually verified.` — the `evidence` preset (6) ``Before you call `sb done`,
prove your work.`` — the `verify` preset (7) `A procedure you run, not a mood.` — the
`adversarial` preset (8) `xyzzy-pelican-42` — an ad-hoc `--as` string.

| probe | spawn flags | fragments expected | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|---|
| probe-a | `--role researcher` | protocol, report-bug, researcher, evidence | YES | YES | YES | no | YES | no | no | no |
| probe-b | `--role qa --with adversarial` | protocol, report-bug, qa, verify, evidence, adversarial | YES | YES | no | YES | YES | YES | YES | no |
| probe-c | `--as "You are a PURPLE PELICAN agent… xyzzy-pelican-42…" --with evidence --with verify` | protocol, report-bug, ad-hoc role, evidence, verify | YES | YES | no | no | YES | YES | no | YES |

Every cell matches what the configured layering predicts, including the negatives
(`researcher` binds `evidence` but not `verify`; `--as` takes no named role prompt). The
YES answers are verbatim quotes, not paraphrase — e.g. probe-b quoted all six of its
fragments back. **probe-b carried six distinct fragments and reported all six.** That is
the direct refutation: "only the last survives" cannot be true.

probe-b and probe-c also reported RAW ORDER, and both describe the switchboard text as
"one continuous run … with no headers" / "separated by `; ` delimiters" — consistent with
a single space-joined `--append-system-prompt` value, in the order protocol, identity,
workspace, role, presets.

A fourth data point that needed no spawn: this agent (`verify-prompt-drop`, `--role qa`)
can see its own protocol, the qa role prompt, `verify`, `evidence` and the `@report-bug`
fragment in its own system prompt.

## The provider-CLI behaviour behind the original bug is real

Run directly, outside switchboard:

```
$ claude -p "Answer with the codeword only." \
    --append-system-prompt "Your codeword is ALPHA." \
    --append-system-prompt "Your codeword is BRAVO." \
    --append-system-prompt "Your codeword is CHARLIE."
CHARLIE

$ claude -p "List every codeword you were given." \
    --append-system-prompt "Your first codeword is ALPHA. Your second codeword is BRAVO."
ALPHA and BRAVO.
```

So `claude` really does keep only the LAST `--append-system-prompt` and silently discard
the rest, and joining into one flag really does deliver everything. The fix is
load-bearing; the claim's underlying mechanism was correctly diagnosed.

## Where it was fixed

`switchboard/herdr.py`, in `Herdr.start_agent`:

```python
if prompts:
    agent_args += ["--append-system-prompt", " ".join(prompts)]
```

Previously `for p in prompts: agent_args += ["--append-system-prompt", p]`. Commit
`146240a` "Deliver the prompts, then make them worth delivering", **2026-08-08 03:18:05
-0700**. The evidence cited by BUILD-PLAN item 1.2 is `2026-08-08-031337` — 03:13:37, i.e.
**4 minutes 28 seconds before the fix landed**. The plan captured a bug that was already
being fixed as it was written.

There is exactly one spawn path that passes prompts (`broker.py:2608` → `start_agent`).
The other call site, `broker.py:3163`, is `sb restore`, which passes `--resume` and no
prompts — correct, the session carries its own context.

A regression test already exists and passes: `tests/test_herdr.py`
`test_every_prompt_is_delivered_in_ONE_flag`, which asserts
`argv.count("--append-system-prompt") == 1` as well as the joined value. It would fail
against the old code. I added no behaviour, so I added no test.

## Checks run

The repo has no Makefile, pytest.ini or pyproject.toml, and pytest is not installed. Tests
are plain `unittest` modules under `tests/`, each inserting the repo root on `sys.path`. I
ran every one of the 21 modules:

- 20 pass when run directly (`python3 tests/test_X.py`).
- `tests/test_readonly.py` fails that way with `ModuleNotFoundError: No module named
  'switchboard'` — it lacks the `sys.path` insert the others have. With `PYTHONPATH=.` it
  passes (9 tests). Pre-existing, unrelated to this investigation, not fixed.
- `tests/test_broker.py` run directly exits 0 silently (no `unittest.main()` guard reached
  in that invocation); via `python3 -m unittest tests.test_broker` it runs 172 tests, OK.

Nothing failed for a reason I caused, and nothing failed on the prompt-delivery path.

## What the original report was probably seeing

Nothing wrong with it — it was accurate at 2026-08-08 03:13. Anything spawned before
`146240a` genuinely received only its last fragment: no protocol, no role prompt. That
explains the surrounding symptoms recorded elsewhere in the plan (agents not calling
`sb done`, not committing first, using their own question tool instead of `sb block`).
Those observations should be re-checked against post-`146240a` spawns before being treated
as live bugs — they may all share this single dead cause.

## Correction made to BUILD-PLAN.md

Item 1.2 has been rewritten in place to record it as verified-and-closed, with this file
as the evidence, and the "Start with 1.2" preamble updated. No other item was touched.

## What I did not check

- Whether every *other* phase-1 item is likewise stale. I only re-checked 1.2.
- Fragment ordering beyond what the probes self-reported; I did not capture the literal
  `herdr agent start` argv of a live spawn, only the unit-test argv and the agents'
  own reading of the result.
- Any provider CLI other than `claude`.
- The `[limits] plugin_fragment` cap and truncation behaviour on very long joined prompts
  — a long-enough join could in principle be truncated somewhere downstream, and I did not
  test that.
