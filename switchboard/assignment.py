"""The seam that hands a freshly spawned agent its Step and its Plan — sb's side.

WHY A SEAM AND NOT A WRITE. `sb delegate --assign-step <step> --own-plan <plan>` is §11's
"one atomic call" reaching into objects sb does not own: a Step belongs to a plugin, lives
in a plugin's state directory, and carries an invariant — "exactly one accountable owner" —
that the plugin enforces with its own lock, its own changelog and its own review-
independence guard. A spawn that opened that file itself would be a second writer with
none of those, and the first time the two rules differed the plan would be what lost. So
this asks the plugin to run the same assignment an agent types (`plans.take`), and sb
contributes the one thing the plugin cannot: the name of an agent that did not exist when
the call began.

This is the third seam of the family DESIGN-TRUTH blessed for the board — "a seam that
reads a `board.py` beside the plugin, hands it the rows of each worktree group, and draws
what it returns" — after `obligations.py`. Same shape, one difference, and it is the whole
difference: **this one fails loudly.** A readout that loses a plugin's obligations degrades
to what it derived before the seam existed; a `--assign-step` that silently assigns nothing
is a caller told its child owns a Step that nobody owns. So every failure here is the
spawn's failure, reported with the flag that caused it.

TWO CALLS, BEFORE AND AFTER. `check()` runs before anything spawns — a step id typed wrong,
or an owned step with no `--steal`, then costs a refusal rather than a live agent with no
work. `apply()` runs once the child's row is claimed and the name is real. The plugin
answers both from one predicate, so the check cannot pass what the assignment refuses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from . import plugins as plugins_mod
from . import store

#: The function sb looks for on an enabled plugin's package. A plugin that has none simply
#: owns no Steps, and a repo with no such plugin cannot use `--assign-step` at all — which
#: is what the refusal below says, rather than the flag quietly doing nothing.
ASSIGN_HOOK = "assign_on_spawn"


class NoAssigner(RuntimeError):
    """No enabled plugin owns Steps, or more than one claims to."""


class AssignmentRefused(RuntimeError):
    """The plugin refused: no such Step, an owned one with no `--steal`, a broken file."""


def provider(repo: Path) -> plugins_mod.Loaded:
    """The one enabled plugin that owns Steps. Raises rather than choosing between two.

    MORE THAN ONE IS REFUSED, not merged. "Exactly one accountable owner" is a statement
    about one Step in one system; two step systems in one repo each answering `--assign-step`
    would make the flag mean whichever of them happened to hold that id, silently. A repo
    that really runs two disables one or spells the assignment out per plugin.
    """
    found = []
    for name in plugins_mod.enabled(repo):
        p = plugins_mod.load(repo, name)
        if p.status == "ok" and callable(getattr(p.module, ASSIGN_HOOK, None)):
            found.append(p)
    if not found:
        raise NoAssigner(
            "no enabled plugin owns Plan Steps, so there is nothing for --assign-step or "
            "--own-plan to assign. `sb plugin list` says what is enabled; the shipped "
            "`plans` plugin is what provides them.")
    if len(found) > 1:
        raise NoAssigner(
            f"{len(found)} enabled plugins claim Plan Steps "
            f"({', '.join(p.name for p in found)}) — a Step has exactly one accountable "
            f"owner and this spawn cannot tell whose Step you mean. Disable one, or assign "
            f"through that plugin's own verb after the spawn.")
    return found[0]


def check(repo: Path, db, *, agent: Optional[str], step: Optional[str],
          plan: Optional[str], steal: bool) -> dict:
    """Would this assignment land? Reads, writes nothing. Raises on anything but yes.

    Run BEFORE the spawn, which is the whole reason it exists separately: the refusals worth
    catching early — a step id that is not a step, a step somebody owns — are exactly the
    ones a caller can fix by retyping, and paying for them with a pane, a worktree and an
    agent that then has nothing to do is the failure this removes.
    """
    return _call(repo, db, agent=agent, to=None, step=step, plan=plan, steal=steal,
                 check=True)


def apply(repo: Path, db, *, agent: Optional[str], to: str, step: Optional[str],
          plan: Optional[str], steal: bool) -> dict:
    """Assign them, to the agent this spawn just made. Raises if the plugin refuses.

    AFTER THE CLAIM, so the name it records belongs to a row. The window between the check
    and here is real — another agent may have taken the step in it — and it is left open
    rather than locked across a spawn: holding a plugin's ownership lock over `agent start`
    would stop every other ownership verb in the repo for as long as a provider takes to
    answer. What closes it is that the assignment asks again; a race loses here, loudly, on
    a child that is already up, and the caller is told which.
    """
    return _call(repo, db, agent=agent, to=to, step=step, plan=plan, steal=steal,
                 check=False)


def _call(repo: Path, db, *, agent: Optional[str], to: Optional[str], step: Optional[str],
          plan: Optional[str], steal: bool, check: bool) -> dict:
    p = provider(repo)
    d = plugins_mod.state_dir(p, repo)
    ctx = plugins_mod.Context(
        api=plugins_mod.API, name=p.name, state_dir=d, repo=store.repo_root(repo),
        worktree=repo, agent=agent, json=False,
        events=plugins_mod.EventLog.bind(db, agent, p.name))
    hook = getattr(p.module, ASSIGN_HOOK)
    try:
        # The plugin's declared lock, exactly as `_plugin_run` honours it — this is a
        # handler call by another door, not a private read. The shipped `plans` declares
        # `LOCK = False` and takes its own finer locks inside.
        with plugins_mod.locked(d, p.lock):
            got = hook(ctx, to=to, step=step, plan=plan, steal=steal, check=check)
    except Exception as e:                      # noqa: BLE001 — a plugin's crash is ours
        raise AssignmentRefused(f"{p.name}: {e}") from e
    if not isinstance(got, dict):
        raise AssignmentRefused(
            f"{p.name}: {ASSIGN_HOOK} returned {type(got).__name__}, not a dict")
    if not got.get("ok"):
        raise AssignmentRefused(str(got.get("error") or f"{p.name} refused the assignment"))
    return got


def record(db, *, agent: str, parent: Optional[str], got: dict, steal: bool) -> None:
    """The store event for what the assignment did. The plugin logs its own changelog.

    BOTH RECORDS, and they are not duplicates. The plugin's changelog is the plan's history
    — who assigned what, in the file a reader opens to find out. This is the fleet's: `sb
    log` is where a person looks to find out what a spawn did, and a spawn that handed over
    a Step and a Plan did more than start an agent.
    """
    s: Any = got.get("step")
    if isinstance(s, dict):
        # `plan_id`/`step_id` are the log's SUBJECT columns, not payload: an event about a
        # Step is read back through `history(step_id=...)`, and a spawn's assignment has to
        # be findable there beside the verbs that move the same step.
        store.log_event(db, kind="step_stolen" if steal else "step_assigned",
                        agent=agent, parent=parent, plan_id=s.get("plan"),
                        step_id=s.get("step"), notified=s.get("notified"),
                        notice_skipped=s.get("notice_skipped"))
    q: Any = got.get("plan")
    if isinstance(q, dict):
        store.log_event(db, kind="plan_owned", agent=agent, parent=parent,
                        plan_id=q.get("plan"), previous_owner=q.get("previous_owner"))
