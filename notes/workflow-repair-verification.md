# Workflow repair — Phase 7 verification record

The evidence for `notes/workflow-repair-plan.md` Phase 7, covering the implementation
Phases 1–6 as they stand on this branch. Written here rather than into a plans-plugin
change record because this change has none: no plan or record document exists for it, and
minting one to hold evidence would have to declare a work path (`direct` or `shaped`) that
is the change owner's call, not this phase's. Whoever opens the PR should copy the identity
block below into the record's `verification` field.

## Identity

| fact | value |
| --- | --- |
| implementation commit | `dbb6479` (Phase 6), with this phase's test commit on top |
| branch | `worker-prompt-audits-2` |
| environment | WSL2 (Linux 6.18), Python 3.11.15, pytest 8 with `-n auto`, herdr 0.8.2, codex-cli 0.149.1, Claude Code 2.1.251 |
| repo | this checkout at `/root/.herdr/worktrees/switchboard/worker-prompt-audits-2` |

## Focused tests

Phases 1–6 already carried most of the focused coverage the plan asks for (model
normalization, waiting/mail, the change record, the human-first comment, legacy stores and
migration). What this phase added is what was missing, plus one stale expectation:

- `tests/test_roles.py` — an unknown `--role` is refused with nearby names, a normalized
  role collision asks for an exact name, and a role already in the store still reads back
  through `get_or_fallback`.
- `tests/test_broker.py` — the spawn path refuses a role nobody defined and starts nothing;
  the instruction manifest reports the delivery of the RESOLVED provider (claude's
  `--append-system-prompt-file` vs codex's private `AGENTS.md`).
- `tests/test_plans_plugin.py` — a structured review renders its identity, its scoped fixes
  and an unresolved major into the PR comment's evidence section.
- `tests/test_capabilities.py` — two expectations that still said the only shipped roles
  holding `spawn` are `dispatcher` and `lead`. The plans plugin contributes `planner`, which
  is seeded with `spawn` for the fresh plan review its specialty commissions, so
  `_delegating_roles()` names three. **These two were failing on `dbb6479` before this
  phase touched anything**: Phase 6 finished without a full-suite run.

## Automated results

| check | command | result |
| --- | --- | --- |
| focused | `python3 -m pytest tests/test_models.py tests/test_roles.py tests/test_broker.py tests/test_plans_plugin.py tests/test_hooks.py tests/test_status.py tests/test_roles_capabilities_cli.py` | 771 passed |
| full suite | `python3 -m pytest tests` | 2206 passed (the two capability failures above, fixed) |
| build | `python3 -m compileall switchboard defaults acceptance tests bin` | clean |
| config parse | every shipped `*.toml` and the plans plugin's `*.json` | parse clean |

There is no linter in this repo — no ruff, flake8 or setup.cfg, and CI runs `python -m
pytest tests` and nothing else — so "applicable lint/build" is the compile and config-parse
pass above.

## Live runs

All in throwaway `git clone`s driven through the clone's own `./bin/sb`, so each opened its
own `state.db` (proven by `sb doctor` naming it) and never the live fleet's. Everything
created was torn down: agents through `sb cleanup --force`, herdr workspaces only where
every path herdr reported was inside the run's own directories, each clone's own collector
by a pid read from its own snapshot, then the directories. Nothing was left behind
(`herdr workspace list` and `~/.herdr/worktrees` checked after each run).

1. **Shipped defaults through the real CLI, no agents.** `sb models`, `sb roles`,
   `sb roles reviewr` (refused, naming `reviewer`), `sb roles RE_VIEWER` (resolves),
   `sb instructions` for `gpt5.6sol` (resolves to `gpt-5.6-sol`), `gpt-5.6-slo` (refused
   with nearby names), `raw:claude-fable-5` (accepted), the `lead`/`worker`/`planner`
   manifests, `sb waiting --help`, and a direct change record created, shown, rendered as
   markdown and validated. `sb delegate --role wroker` was refused and left `sb status`
   empty. Evidence: scratch `live-cli.out`.
2. **A real agent spawns, takes its task and reports.** One codex-tier worker in a fresh
   clone reported its token through `sb done` eleven seconds after the delegate. This is
   the only proof that the rewritten prompt composition survives contact with a provider.
3. **`sb waiting --any` and the causal wake.** A lead delegated one child, ran
   `sb waiting --any`, ended its turn, and was woken by the child's terminal result: its
   own summary was `WOKEN [1] [sb: from worker-…-child] [done] PHASE7B-…`, i.e. the tagged
   payload arrived inline. This is Phase 2's central mechanism, live.

Runs 2 and 3 pin `worker` and `lead` to the `gpt-5.5` codex tier in the clone, for the
reason in the next section.

## Limitations and evidenced baseline failures

- **`acceptance/accept.py` fails on this machine, on this branch and on `main` alike.** All
  four criteria fail identically at `task_undelivered … agent_not_found`: a Claude Code
  spawned into a fresh clone sits on its folder-trust dialog and never takes its task.
  `main` was run as a baseline and failed the same way (check 4, 15s), so this is an
  environment condition and not something this change introduced. Switchboard pre-seeds
  directory trust for codex (`switchboard/codex.py`) and cannot for claude, which is why
  the live runs above use a codex tier. **The four fleet criteria are therefore unproven on
  this branch on this machine.**
- Live coverage stops at the two scenarios above. Inline-vs-fallback mail selection,
  interrupts, blocking, cohort coalescing across several children, restore and cleanup
  refusals are covered by the suite against a fake herdr and were not re-proven live.
- The plans plugin's landing verbs (`create-pr`, `merge`, the PR comment upsert) were
  exercised only against local rendering; no live GitHub PR was created.
- No endurance runs: every live scenario is the smallest that distinguishes working from
  broken, and rare or slow-burn faults will surface in real use.
