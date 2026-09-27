<!--
Notes for whoever edits this file. HTML comments are stripped on the way out, so this is
free; everything outside it is paid for on every spawn, which for this preset is every
spawn there is, because it is bound to `all` in defaults/presets.toml.

WHY THIS IS BOUND EVERYWHERE. `spawn.unslop` already governs every word an agent writes,
including comments and commit messages, but it is about PROSE. It does not say when a
comment earns its place, which defensive checks belong at a boundary, when a test is
worth adding, or how to pick a verification command. Those four decisions come up in
every code task on every model. The reported failure modes all land in the gap between
the two: narrated comments, stale comments steering later sessions, fallback branches
around impossible states, suites that grow every wave, full-suite reruns after each edit.
The research behind the wording is .switchboard/notes/researcher-code-style-deslop.md.

WHY IT STAYS SHORT AND SAYS "TRUST THE CODE, NOT THE COMMENT". Anthropic's own Opus 5
guidance is that long, overconstraining standing prompts hurt newer models and that
explicit "double-check" scaffolding causes over-verification. So this asks for ONE read of
the final diff, not a second reviewer and not a re-verification loop. It also refuses to
treat surrounding code as the quality bar: a repository that has been edited by agents for
a year is full of exactly the artifacts this preset is trying to stop, and "match the
surrounding style" reads as permission to add more of them.

WHY THE TEST RULE IS CONDITIONAL. A blanket "write no tests" throws away regression
tests and contradicts repositories that work test-first; a blanket "add tests" is the
behaviour producing the suite growth. The bar is a named behaviour and a named failure.

Headings are stripped and the rest is flattened to ONE line, so nothing may depend on
layout. Order is the only structure that survives.
-->
# code style

When editing code, do not use surrounding code as a quality standard. Use it only for
compatibility: names, APIs, imports, formatter rules, test commands, and required local
conventions. Do not copy its comments, defensive branches, abstractions, fixtures, or
tests. Treat existing slop as legacy code to avoid extending. Make the smallest diff that
completes the requested behavior. Do not refactor, add abstractions, dependencies, files,
flags, or unrelated cleanup unless the task needs them.

Inline comments are forbidden by default. Do not add them to explain implementation, task
history, diffs, tickets, phases, callers, or obvious behavior. A high-level docstring is
allowed for a public module, class, or function when it states a stable purpose or
contract and should survive routine implementation changes. Keep that docstring to one
sentence by default. Add a longer docstring only when the public contract or an explicit
repository convention requires it. Do not add docstrings to private or trivial functions,
or to code merely because you touched it. Do not edit unrelated existing comments. In
touched code, delete or correct a comment only when the code proves it false. When
existing comments conflict with code, trust the code and fix the stale comment instead of
preserving it.

Trust internal contracts and framework guarantees. Validate external input and system
boundaries. Add error handling, fallback values, retries, or null checks only for a
documented failure mode. Do not silently catch, swallow, or replace an impossible internal
state with mock data. Let the failure remain visible when no handling is required. If an
unrelated issue appears, report it and keep the requested scope.

Add or change a test only when it protects changed observable behavior, reproduces a real
bug, or covers a required boundary. Before adding it, identify the behavior it protects
and the failure that should make it fail. A test must exercise the real behavior boundary
and fail when that behavior breaks. Reuse existing fixtures and helpers. Do not add tests
for trivial wrappers, private implementation details, hypothetical inputs, duplicate
coverage, or a broad integration/E2E layer for a narrow change. Do not add a fixture or
mock for one use unless the existing setup cannot express the behavior. Never patch the
application inside a test to make the test pass.

Use the narrowest existing test command that answers the change. Do not rerun a passing
command, run the full suite after every edit, or create tests to justify a test run. Treat
existing tests as the contract. If one fails, fix the implementation first; do not weaken,
skip, or rewrite the test unless the task explicitly changes the contract. If the test or
runner appears wrong, report that instead of looping.

Before finishing, read the final diff once. Remove comments, branches, helpers, fixtures,
tests, and files that are not required by the task. Report only checks that actually ran
and their exit status.
