"""Appendix A's DERIVED Step and Plan states, and the obligations they put on agents.

Two readers, one derivation, and that is the whole reason this is its own file. `show` and
`list` draw a step's derived state beside its stored `progress`, and `status.collect` needs
to know what each agent OWNS and AWAITS to tell `awaiting external` from `stalled`
(migration_sb_v2.md §6). Those are the same question asked from two processes, and a second
copy of the answer in `switchboard/` is how the board and the plan page come to disagree
about the same step.

**Nothing here is stored.** The five Step words (`pending`, `active`, `blocked`, `failed`,
`complete`) and the three Plan words are derived every time from what IS stored — a step's
`progress`, its immutable `kind`, its deps, and the change record's landing facts — exactly
as `condition` and `owner_status` already are. The stored vocabulary is unchanged and stays
three words (`open`/`done`/`skipped`, plus the bundle's `failed`): re-architecting it would
ripple through every verb, every hand-edit and every plan already on disk, and buys nothing
the derivation does not.

**How sb reaches this without reading a plugin's files.** `switchboard/obligations.py` looks
for this file and for `agent_obligations` on it, the same seam and the same rule as the
board's (`DESIGN-TRUTH.md`: "a seam that reads a `board.py` beside the plugin, hands it the
rows of each worktree group, and draws what it returns"). sb hands over the state directory
it made and never looks inside it; this file, which is part of the plugin and is the only
thing that knows the format, answers with plain data. A repo that replaces the plans plugin
wholesale replaces this too, and a plugin that ships no `derive.py` simply contributes no
obligations — `collect` then derives exactly what it derived before this existed.

**Nothing here asks anybody anything**, for `board.py`'s reason one register up: this runs
inside `status.collect`, which the collector calls twice a second, and `_Live` spends
seconds of `sb status` subprocesses. It could not use one anyway — `_Live.owner` shells out
to `sb status`, which is the very call this runs inside. So an owner's LIVENESS is not
decided here: this says which agent owns which derived step, and `collect` — which has
herdr, the store and wave 4's three-valued liveness in hand — decides what follows from
that. The split is deliberate and is what keeps this side a pure function of the files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from . import (DONE, FAILED, MERGE_KIND, OPEN_PR_KIND, SKIPPED, _STEP_ID, _is_record,
               _kind_of, _num, _owner, _read)

# THE FIVE DERIVED STEP WORDS (migration_sb_v2.md Appendix A, Step). Derived, never stored.
#
# `pending` and `active` are both the stored `open`, split by ELIGIBILITY — whether every
# step this one is `after` has finished. That split is the one Appendix A leans on hardest:
# "`pending` Steps are not actionable owned work and do not defeat `awaiting external`", so
# an agent holding the last step of a plan it cannot start yet is not thereby excused from
# stall derivation, and an agent holding one it CAN start is at work.
#
# `blocked` is narrower than the English word and means exactly one thing: a `merge`-kind
# step whose pull request is open and waiting on a human's merge. It is not "stuck" and no
# other kind of step can be in it — a step waiting on a person for anything else is its
# owner's `gate`, which is prose the owner reads, not a state the plan is in.
#
# `failed` is the bundle's own word passed through: `open-pr` writes it onto the step whose
# sub-operation failed, and `step retry` clears it. It is stored, unlike the other four, and
# is here so that a reader has one vocabulary rather than four words and an exception.
PENDING, ACTIVE, BLOCKED, COMPLETE = "pending", "active", "blocked", "complete"
# `FAILED` is imported from the plugin rather than re-spelled: the stored word and the
# derived word are the same word on purpose, and two spellings of it is how they drift.

# THE THREE PLAN WORDS (Appendix A, Plan), simplified per #306: there is no `awaiting merge`
# and no authorization sub-state. A plan is `in progress` until its PR is open and its merge
# is a human's, and `complete` when the merge is observed. A plan whose owner merges under
# standing authority never passes through the middle word — it goes to `complete` when the
# merge lands, which is what "a Plan is never without a state" means.
IN_PROGRESS, NEEDS_HUMAN_REVIEW, PLAN_COMPLETE = ("in progress", "Needs Human Review",
                                                  "complete")

# The stored words that mean a step is finished, whichever way it got there. `skipped` is
# finished for every purpose this file has: the step will not be worked again, so whatever
# waited on it is waiting no longer (`_next` says the same thing about the same two words).
_CLOSED = (DONE, SKIPPED)



def step_states(plan: dict) -> dict[str, str]:
    """Every step of this plan, by id, in its Appendix A derived state.

    ONE PASS AND NO RECURSION. Eligibility is "every dep is closed", and a dep is closed by
    its STORED word, not by its derived one — so nothing here has to resolve a step before
    it can resolve the step after it, and a plan whose edges form a cycle (which `_defects`
    reports and refuses to let stand) produces a reading rather than a hang.

    THE ORDER OF THE TESTS IS THE CONTRACT, and it is Appendix A's own: a finished step is
    complete whatever its deps say (a `reopen` of an earlier step is what suspends a later
    one, and `reopen` rewrites the stored words itself), a failed step is failed, and only
    then does eligibility split the rest into `pending` and the two eligible readings.
    """
    steps = [s for s in (plan.get("steps") or ()) if isinstance(s, dict)]
    stored = {_num(_STEP_ID, s.get("id")): str(s.get("progress") or "") for s in steps}
    merge_wait = _merge_waits(plan)
    out: dict[str, str] = {}
    for step in steps:
        sid = str(step.get("id") or "")
        if not sid:
            continue
        progress = str(step.get("progress") or "")
        if progress in _CLOSED:
            out[sid] = COMPLETE
        elif progress == FAILED:
            out[sid] = FAILED
        elif not all(stored.get(_num(_STEP_ID, d)) in _CLOSED
                     for d in (step.get("deps") or ())):
            out[sid] = PENDING
        elif _kind_of(step) == MERGE_KIND and merge_wait:
            out[sid] = BLOCKED
        else:
            out[sid] = ACTIVE
    return out


def _merge_waits(plan: dict) -> bool:
    """Is this plan's merge a wait on a person right now?

    Two facts, both on the change record: a pull request has been opened (`change.pr`), and
    nothing has landed it yet (`change.landing`). While both hold, the `merge` step is
    `blocked` — its owner is `awaiting external` and never `stalled`, because the Plan's
    `Needs Human Review` item is already the representation of that wait.

    WHAT THIS CANNOT SEE, stated because Appendix A names it: "an owner with standing
    authority to merge has `Merge` `active` instead". Standing authority is not a fact this
    store holds BEFORE a merge — `merge --standing` writes `landing.kind = "standing"` at
    the moment it lands, and there is no field anywhere that says in advance whose merge
    this plan's is. So the derivation takes the default Appendix A states as the common
    case (a human's merge) and every open PR reads as `Needs Human Review` until it lands,
    which is the reading that surfaces a PR rather than the one that hides it. Deriving the
    `active` branch wants a recorded per-plan merge authorization, which is a plan-model
    change and not this wave's (#329/#335 territory).
    """
    change = plan.get("change")
    if not isinstance(change, dict):
        return False
    pr = change.get("pr")
    opened = isinstance(pr, dict) and pr.get("number") is not None
    landed = isinstance(change.get("landing"), dict)
    return bool(opened and not landed)


def plan_condition(plan: dict, states: Optional[dict] = None) -> str:
    """This plan's Appendix A landing state, derived from its steps.

    Three words and no fourth. `complete` needs every step finished AND — for a plan that
    has one at all — its `merge`-kind step among them, which is Section 4's "a Plan with
    commits cannot reach `complete` without a completed `merge`-kind Step" arriving for
    free rather than as a second test: a plan whose merge is still open has an unfinished
    step, so it cannot be complete anyway.

    `Needs Human Review` is exactly the PR-open-to-merged interval, and it is spelled as the
    two facts that define it rather than as a phase: the `open_pr` step is complete and the
    `merge` step is `blocked`. A plan with no steps is `in progress` — "the vacuous case is
    `in progress`" (Section 4) — which falls out of `all(())` being true being caught by
    the emptiness test first.
    """
    states = step_states(plan) if states is None else states
    if not states:
        return IN_PROGRESS
    if all(v == COMPLETE for v in states.values()):
        return PLAN_COMPLETE
    kinds = {sid: _kind_of(s) for s in (plan.get("steps") or ())
             if isinstance(s, dict) for sid in (str(s.get("id") or ""),) if sid}
    opened = any(states.get(sid) == COMPLETE for sid, k in kinds.items()
                 if k == OPEN_PR_KIND)
    waiting = any(states.get(sid) == BLOCKED for sid, k in kinds.items() if k == MERGE_KIND)
    return NEEDS_HUMAN_REVIEW if opened and waiting else IN_PROGRESS


def agent_obligations(state_dir: Path) -> dict:
    """Every plan in this repo, flattened into what each agent owns and what it awaits.

    The seam's whole payload, and it is plain data — lists and strings, no plugin objects —
    because it crosses into `switchboard/status.py`, which must not grow a dependency on
    this plugin's types. Shape:

        {"steps":  [{"plan", "step", "name", "kind", "state", "owner"}, ...],
         "plans":  {plan_id: condition},
         "owners": {plan_id: [every agent that owns a step of it]}}

    `steps` carries EVERY step of every plan, not only the owned ones: `collect` needs the
    unowned ones too, because "owns ≥1 `blocked` Step and no `active` Step" is a statement
    about one agent and "the plan's only incomplete Steps are owned by OTHER agents" is a
    statement about the rest of them.

    Change RECORDS are in here beside plans and deliberately so: a direct change is born
    with the same execution+landing skeleton, its steps are owned the same way, and an agent
    holding the `merge` step of one is `awaiting external` for exactly the same reason.

    Never raises. A store that is not there, a plan file that will not parse, a shape this
    code does not recognise — every one of them is fewer obligations, which degrades
    `collect` to the derivation it did before this existed. A readout that dies because a
    todo list is malformed is a readout you stop running.

    MEMOISED ON THE FILES THEMSELVES, and that is not an optimisation to skip reading.
    Measured on this repo's own store — 77 plans, 371 steps — parsing them costs 30 ms,
    against a 26 ms `collect` that the collector runs twice a second and that every `sb`
    command pays once. Uncached, this seam doubled the cost of reading the fleet. See
    `_fingerprint` for what invalidates it and for the one staleness window it has.
    """
    state_dir = Path(state_dir)
    mark = _fingerprint(state_dir)
    if mark is not None and _CACHE.get(state_dir) is not None \
            and _CACHE[state_dir][0] == mark:
        return _CACHE[state_dir][1]
    try:
        doc, _ = _read(state_dir)
        plans = doc.get("plans") or []
    except Exception:                          # noqa: BLE001 — see the docstring
        return {"steps": [], "plans": {}, "owners": {}}

    steps: list[dict] = []
    conditions: dict[str, str] = {}
    owners: dict[str, list[str]] = {}
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        pid = str(plan.get("id") or "")
        if not pid:
            continue
        try:
            states = step_states(plan)
            conditions[pid] = plan_condition(plan, states)
        except Exception:                      # noqa: BLE001 — one bad plan, not the fleet
            continue
        seen: list[str] = []
        for step in (plan.get("steps") or ()):
            if not isinstance(step, dict):
                continue
            sid = str(step.get("id") or "")
            if not sid:
                continue
            who = _owner(step)
            if who and who not in seen:
                seen.append(who)
            steps.append({"plan": pid, "step": sid,
                          "name": str(step.get("display") or step.get("name") or sid),
                          "kind": _kind_of(step), "state": states.get(sid, PENDING),
                          "owner": who, "record": _is_record(plan)})
        owners[pid] = seen
    out = {"steps": steps, "plans": conditions, "owners": owners}
    if mark is not None:
        _CACHE[state_dir] = (mark, out)
    return out


# `{state_dir: (fingerprint, answer)}` — one entry per store, which in practice is one.
# Per PROCESS, so a short-lived `sb` command fills it and throws it away, and the collector
# — the caller this exists for — keeps it for its life and re-parses only when a plan is
# written. Never invalidated by time, only by the files (`_fingerprint`).
_CACHE: dict[Path, tuple] = {}


def _fingerprint(d: Path) -> Optional[tuple]:
    """What every file in this store looks like from the outside. None if it cannot be read.

    Name, size and nanosecond mtime for each entry, sorted — enough that any write this
    plugin makes changes it, because every one of them goes through `_atomic`, which
    replaces a whole file. A `migrate` changes the set of names, and a hand-edit in an
    editor changes a size or an mtime.

    ONE STALENESS WINDOW, named because it is real: a filesystem whose mtime resolution is
    coarse could hide a rewrite of exactly the same length inside one tick. The cost of
    that is one reading of the fleet carrying a step's previous state, on a derivation that
    is recomputed twice a second — and the alternative, a timestamp-free cache, is no cache
    at all. `None` (the directory is not there yet, or cannot be listed) disables the cache
    rather than caching an answer nothing can invalidate.
    """
    try:
        out = []
        with os.scandir(d) as entries:
            for e in entries:
                if not e.name.endswith(".json"):
                    continue
                st = e.stat()
                out.append((e.name, st.st_size, st.st_mtime_ns))
        return tuple(sorted(out))
    except OSError:
        return None
