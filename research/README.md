# research/ — exploratory, and stale

Ten reports and a synthesis, written over 2026-08-06 and 2026-08-07, **before a line of
switchboard existed**. (The synthesis covers 01–06 only; 07–10 landed after it.) They are the landscape survey the design was argued from: what other agent
orchestrators do, what they got wrong, what herdr already gives us for free, and which
workflow-engine and memory formats were worth stealing from.

**Read them as evidence about August 2026, not as a description of switchboard.** They
predate the build entirely, so:

- Where a report proposes a design, it was a proposal. Some of it shipped, some was
  reversed on contact with the code, some was never attempted. `../DESIGN-TRUTH.md` is
  the only record of what was actually decided, and `../notes/FEATURES.md` of what was
  actually built.
- Where a report describes another project's version, star count, release cadence or
  open-issue count, that was true on the date at the top of the file and is certainly not
  true now. The dates are left in for exactly that reason.
- `01-herdr.md` inspects herdr **0.8.0** (protocol 19). Later versions will differ.

Nothing here has been revised since it was written. Corrections live in the documents
that cite these reports rather than in the reports themselves — `../notes/PRINCIPLES.md`
carries the conclusions that survived, with `[NN]` references pointing back here.

| # | File | Topic |
|---|---|---|
| — | [00-synthesis.md](00-synthesis.md) | Cross-cutting conclusions. **Start here**; the numbered reports are the evidence. |
| 01 | [01-herdr.md](01-herdr.md) | herdr deep dive — socket API, agent control, state authority, what it does and does not give us |
| 02 | [02-orchestrators.md](02-orchestrators.md) | The multi-agent coding orchestrator landscape |
| 03 | [03-ui.md](03-ui.md) | One state model, two surfaces: web vs terminal |
| 04 | [04-workflow-engines.md](04-workflow-engines.md) | Workflow engines, step machines and template formats — adopt, steal, or build |
| 05 | [05-memory-learnings.md](05-memory-learnings.md) | Agent memory and the learnings store |
| 06 | [06-agent-comms.md](06-agent-comms.md) | Agent communication, plugin substrates, programmatic control, hooks |
| 07 | [07-gastown-github.md](07-gastown-github.md) | Gas Town: what the repo actually contains |
| 08 | [08-gastown-sentiment.md](08-gastown-sentiment.md) | Gas Town: what its users actually said |
| 09 | [09-gascity-core.md](09-gascity-core.md) | Gas City: evaluation |
| 10 | [10-gascity-fit.md](10-gascity-fit.md) | Gas City: practical fit for this use case |
