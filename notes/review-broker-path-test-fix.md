# Review brief: commit 8e486f2 (branch worker-fix-broker-path-test)

Worktree: /root/.herdr/worktrees/switchboard/worker-fix-broker-path-test

## The change

One test-only edit plus a comment: `tests/test_broker.py`, `BrokerTest.setUp` now does
`self.repo = Path(self.tmp.name).resolve()`.

## Background

`tests/test_broker.py::BrokerTest::test_start_inside_a_worktree_is_refused_and_names_the_main_checkout`
built the main checkout as `self.repo / "checkout"` (unresolved) and asserted that string
appears in the refusal message. But `Broker._refuse_outside_main_checkout`
(`switchboard/broker.py:2044`) resolves the main checkout before naming it. The two sides
were the same path in two spellings; it only passed on macOS because `/var/folders/X` is a
substring of the `/private/var/folders/X` the code reports. Same class of fix as PR #252
(commit `48a7550`).

## What I verified (re-run it yourself, don't trust these numbers)

- With `TMPDIR` pointed at a symlinked directory: target test **fails before** the fix
  (1 failed, 310 passed), whole file **passes after** (311 passed).
- Under a plain `TMPDIR`: 311 passed.
- Python here is `python3`, not `python`. Suite is `python3 -m pytest tests/test_broker.py`;
  `-n0` for a single process.

## Judge these

1. **Right place?** `setUp` for the whole class, versus resolving only inside the one test.
   Does resolving `self.repo` for every `BrokerTest` test risk masking or weakening any
   other assertion in that class — tests that deliberately compare unresolved paths, or the
   `home = Path(self.tmp.name) / ...` paths that stay unresolved?
2. **Still pinning the behaviour it names?** The test claims the refusal names BOTH the main
   checkout to run from AND the worktree the user is in. Has resolving made either assertion
   trivially true?
3. **Nearby latent twins?** Any other test with the same path-mixing that this fix leaves
   broken — report it, do NOT fix it (out of scope for this change).
4. **Comment and commit message.** Is the added comment correct? Does the commit message
   overstate anything?

Report findings; do not change the code. `sb done` with your verdict.
