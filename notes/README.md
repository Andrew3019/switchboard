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

Kept for the measurements and the wrong theories, which are the useful part. All three
describe code as it stood in August 2026; much of what they discuss has since been fixed,
renamed, or deleted outright, and each carries a preamble saying so.

| File | What it is |
|---|---|
| [BUGS.md](BUGS.md) | One entry per bug: what was run, what was expected, what happened, and the exact error. Every entry carries a **STATUS** line. |
| [QA-FINDINGS.md](QA-FINDINGS.md) | A live-agent exercise of the verbs that had unit tests but had never been run against real agents. Eleven findings, B1–B11. |
| [REVIEW.md](REVIEW.md) | A whole-repo review pass, 2026-08-07: what was consolidated, what was deliberately not, and what was deleted as dead. |
| [bugs-writeup-stale-entries.md](bugs-writeup-stale-entries.md) | A later pass over `BUGS.md` itself, correcting entries that had gone stale. |

## Two notes on reading these

**`audit/` is gone.** Several files below cite `audit/<something>.md` — a directory of
per-phase build and verification write-ups that was removed when this repo was made
public. Those citations are still accurate about what was measured; the files themselves
are only in git history now.

**Cross-references are by bare filename.** A note that says `PRINCIPLES.md` or `BUGS.md`
means the file of that name in this directory. Comments elsewhere in the codebase cite
them with the `notes/` prefix.
