# Design records

Design documents that are still authoritative for a shipped subsystem, plus the evidence
that they were checked. Unlike `research/` (prior art on other people's systems) and
`reference/` (herdr's own docs, vendored), everything here is switchboard's design of its
own internals.

| file | what it is |
|---|---|
| `PLUGIN-REDESIGN.md` | The design of record for the preset/plugin split. Shipped in `06232d9`. |
| `verification.md` | The read-only fact-check of that document against the codebase. |
| `history/` | Superseded inputs to the above. Historical — do not treat as current. |

## Reading `PLUGIN-REDESIGN.md`

It is self-contained; you do not need `history/` to follow it. It describes the world after
the split: a **preset** is prompt text (`sb delegate --with X`, `defaults/presets/`), a
**plugin** is Python that sb imports (`sb plugin todo add …`, `defaults/plugins/`).

Not everything in it was built. Sections that remain open say so in place — most notably
§4.6's `sb doctor` check for a plugin reaching into switchboard internals, which is
**deliberately not built** rather than merely deferred; the reason is written into §4.6.

## Reading `verification.md`

It is a snapshot, not a live document. It was run against `plugins-redesign` @ `86fac25`,
before implementation, and its purpose was to catch false claims in the design *while the
design was still being decided*. It found two, and `PLUGIN-REDESIGN.md`'s header records
how each was corrected. Its `file:line` citations point at pre-redesign code and will not
resolve against `main`.
