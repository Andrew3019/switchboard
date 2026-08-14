# notes/ — working notes

Switchboard's design record. These are working documents, not product documentation:
they were written while the thing was being built, they argue with each other, and
several of them are annotated with what turned out to be wrong.

**`../DESIGN-TRUTH.md` is the only document that is authoritative.** Everything in this
directory is subordinate to it, and where a note and the code disagree, the code wins.
Each file below says what it is and how far you can trust it.

## Current

| File | What it is |
|---|---|
| [FEATURES.md](FEATURES.md) | The maintained inventory of what `sb` actually does, verb by verb, derived by reading the code. **Start here** if you want to know what the system is. |
| [PRINCIPLES.md](PRINCIPLES.md) | The fifteen engineering principles (C0–C15) the design is argued from, the failure evidence behind each, and what they rule out. Referenced by file and number throughout the codebase. |
| [REMAINING.md](REMAINING.md) | Where the code and `DESIGN-TRUTH.md` still disagree. Six open questions, all of them decisions rather than code. |

## Design record — partly built, partly retracted

| File | What it is |
|---|---|
| [PLAN.md](PLAN.md) | The module map and the numbered decisions (D1–D7). M1–M3 shipped and are annotated as such; **M4 onwards is still unbuilt and this is still the plan for it**. |
| [POC.md](POC.md) | The proof-of-concept design, plus the herdr adapter rules that came out of verifying it live — state authority, `--seq` semantics, the doorbell. Wrong turns are marked **RETRACTED** rather than deleted. |
| [HOOKS.md](HOOKS.md) | The Stop gate and the activity signal, which are built, and the hook candidates that are not. |
| [braindump.md](braindump.md) | The original unfiltered thinking, before any research or code. Preserved as the starting point; nothing in it is a commitment. |

## History

| File | What it is |
|---|---|
| [bugs-writeup-stale-entries.md](bugs-writeup-stale-entries.md) | A later pass over `BUGS.md` itself, correcting entries that had gone stale. `BUGS.md` is gone (see below); this is the record of what those corrections were. |

**`BUGS.md`, `QA-FINDINGS.md` and `REVIEW.md` are gone.** They were an August-2026 bug
log, a live-agent QA run and a one-off review pass. Every finding in them was fixed, or
was about a verb that has since been deleted; the two facts still worth having are in the
code that carries them (`tests/test_status.py::test_the_grace_outlasts_herdrs_own_retry_loop`
for the spawn-grace hole, `switchboard/status.py`'s `DONE_TO_THE_AGENT` comment for the
idle-clock one). Bugs against switchboard now go to the `report-bug` plugin
(`sb plugin report-bug file …`), which is bound to every spawn. The files themselves are in
git history.

## Two notes on reading these

**`audit/` is gone.** Several files below cite `audit/<something>.md` — a directory of
per-phase build and verification write-ups that was removed when this repo was made
public. Those citations are still accurate about what was measured; the files themselves
are only in git history now.

**Cross-references are by bare filename.** A note that says `PRINCIPLES.md` or `POC.md`
means the file of that name in this directory. Comments elsewhere in the codebase cite
them with the `notes/` prefix.
