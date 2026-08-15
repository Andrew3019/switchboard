# How the dispatcher role is actually shaped, vs lead

Read-only investigation. Sources: `defaults/roles/dispatcher.md`, `defaults/roles/lead.md`,
`defaults/prompts.toml`, `switchboard/broker.py` (`Broker.delegate`, ~line 3036-3238),
`switchboard/cli.py` (`_agent_caller`, `start`/`board` dispatch, ~line 499-807),
`DESIGN-TRUTH.md`.

## 1. Prompt composition — what actually gets concatenated

`Broker.delegate` (broker.py:3123-3143) builds a list and sends it as one appended
system-prompt file, in this exact order, for EVERY role including dispatcher and lead:

1. `self._protocol()` — the shipped `defaults/protocol.md` (or a repo's own override).
2. `spawn.identity` (prompts.toml:32) — `"You are agent '{name}', role '{role}'. You
   report to '{parent}': they spawned you, and your `sb done` summary is what they see of
   your work."`
3. `spawn.roles` (prompts.toml:49) — `"The roles that exist are: {roles}. That is the
   list `--role` takes; a name that is not on it still works and inherits the default
   role."` — `{roles}` is generated from the live role table, never hardcoded.
4. `spawn.workspace` (prompts.toml:60-66), only if the spawn is placed in a named
   workspace — includes the "re-read a file before you edit it, you may not be alone"
   concurrency rule.
5. The role's own file — `defaults/roles/dispatcher.md` or `defaults/roles/lead.md` body
   (everything after the `+++` frontmatter and HTML comment).
6. Any preset bindings resolved for that role (`_resolve_bindings`) — e.g. a repo's
   `house-rules` preset, bound last.

So dispatcher and lead share fragments 1-4 verbatim and diverge only at 5 (and whatever
presets a repo binds to each role in 6). Nothing in fragments 1-4 mentions dispatcher-
specific or lead-specific behavior.

## 2. The dispatcher-specific text (quoted in full, `defaults/roles/dispatcher.md:146-219`)

Key excerpts:

- Identity/scope: `"You are a dispatcher. Work reaches you from one person, and your job
  is to put it in the hands of an agent that will own it. You hold no task yourself and
  no context about any of them..."` (line 146-149)
- Absolute no-work rule, and that it overrides every other instruction including the
  protocol: `"You do none of the work, and that is unconditional... You are the only
  agent this applies to... where any of it and this file disagree about whether you
  should do something yourself, this file wins."` (151-158)
- Everything goes to a lead, always: `"Spawn a lead with `sb delegate "<the task>" --role
  lead --name <a name for it>` and give it the whole of what you were given."` (161-163)
- The relay rule (Andrew's own framing, per the file's own comment at lines 59-74): `"Pass
  the task as it was written to you, and add nothing of your own about how it should be
  approached — in particular, whether a piece of work is to be carried through to the
  end, or investigated and brought back for a decision first, is the person's call to
  make and not yours to assume. A guess of yours becomes an instruction the child follows
  exactly, so ask them first whenever dispatching would mean deciding something they did
  not say."` (167-172) A vague-but-not-ambiguous task is explicitly NOT a reason to ask:
  `"A merely vague task is a different case and not a reason to stop them... relay the
  vagueness as it stands rather than resolving it."` (172-174)
- Naming is allowed, narrowly: `"Naming the work IS yours, and it is naming only: two or
  three words for the subject..."` (174-177)
- Follow-ups on already-dispatched work go to the owning child, not answered directly:
  `"pass it on with `sb tell <name> "..."` rather than answering it yourself... A child's
  report is its own; you have nothing to add to it and nothing to re-synthesise."`
  (179-182)
- The one report a dispatcher makes: `"...they see an agent only when it blocks, so a
  child's completion that you merely noted to yourself has reached nobody. When a child
  reports done, write in your chat... which piece of work has finished and what that
  child said about where it stands — its words, not a summary you invented — and then `sb
  block`..."` (184-189)
- No cleanup: `"You do not close agents... what stays open below you is their call, made
  from the board they are watching, and it is not yours to tidy."` (191-194)
- Cross-repo work is a stop-and-ask, never a spawn: `"...it is where the files that would
  have to change actually live. If that is outside the checkout you were started in, it
  is not yours to dispatch... Do not dispatch it and do not guess which repo is meant...
  Write the question in your chat... then `sb block`, and start nothing until you have an
  answer."` (196-209)
- No reading license: `"You need read nothing to route... `sb status` for who you have
  out is the whole of your looking. Reaching for a file is the first move of doing the
  work, and the work belongs to a child."` (211-213)

## 3. The lead-specific text (`defaults/roles/lead.md:144-249`, summarized + quoted)

- Owns one task end-to-end and does the actual orchestration: `"You own one task from end
  to end: you hold everything about it, and your job is to get other agents to do the
  work rather than doing it yourself."` (144-145)
- Understand before splitting: spend one scout agent to learn the shape, then plan, then
  split — `"If you do not already understand the task well enough to split it well, your
  first move is to spend one agent finding out — a scout... Do not read the codebase
  yourself to answer that question; a glance at one or two files to place yourself is
  fine, and past that you are doing the work."` (154-158)
- Plan with shape, re-plan as results return, assign disjoint files, serialize
  overlapping writers, parallelize independent parts, sequence dependent ones (160-170).
- Splits its own task into worker or sub-lead children, per part — explicitly forbidden
  from spawning `dispatcher` (`"dispatcher appears in the list of roles you were given
  and is not one of your options: there is one dispatcher, it is the top of the tree, and
  only a human starting one creates it."`, 176-178) and forbidden from cloning itself as
  a whole-task sub-lead (172-176).
- Aggressively cleans up its own subtree: `"`sb cleanup [names]` closes finished agents
  in your subtree. Use it constantly... Two things stay open, and nothing else does: an
  agent blocked waiting on a human, and finished implementation work someone may actually
  want to open."` (192-201) — this is the opposite of the dispatcher's "you do not close
  agents" rule.
- Reporting/synthesis: writes for its parent (which may be the human), synthesizes a
  cohort rather than dripping events, avoids jargon/unintroduced names, and must end with
  a decision when the work called for one (203-235).
- `sb block` only for a genuinely-human decision or its own broken tool, never to hand
  over work or to report (237-248) — mechanically identical two-step procedure
  (chat-then-block) to the dispatcher's.

## 4. Shared across all roles (fragments 1-4 above, plus the protocol)

- Identity/parent framing, the roles list, and (if placed in a shared workspace) the
  concurrency/re-read rule — verbatim, same wording, for dispatcher, lead, and every
  other role (worker, qa, researcher, reviewer).
- Everything in `defaults/protocol.md` (not reproduced here in full — I read the
  dispatcher.md comment's description of it but did not do a line-by-line quote pass
  on protocol.md itself, since the brief's focus was the dispatcher/lead split). The
  dispatcher.md comment (lines 39-48) states protocol.md carries: "do the task you were
  given and nothing beyond it", "run the suite", "commit on your own branch", "prove it
  in an isolated instance" — all written for a role that does work, which is why
  dispatcher.md has to explicitly override it.
- The doorbell/notify strings (`mail`, `child_done`, `interrupt`, `needs_reply`,
  `preset`, `stalled` in prompts.toml:79-153) apply identically to any role when the
  relevant event happens — no dispatcher/lead distinction there either.

## 5. Is "relay the human's words verbatim" an actual instruction, or emergent?

It is an explicit instruction, not emergent behavior. `dispatcher.md:167-172` says it in
so many words ("Pass the task as it was written to you, and add nothing of your own
about how it should be approached..."), and `DESIGN-TRUTH.md:254-260` confirms it as
product decision: `"A dispatcher relays; it does not interpret. Its job is basically to
relay Andrew's words to new leads... without adding instructions of its own about how the
work should be approached... If that is unclear, it does not start: it asks him to
clarify intent before dispatching."` — confirmed 2026-08-14, explicitly superseding an
earlier 2026-08-09 rule that let the top route small tasks directly or spawn its own
scouts.

## 6. Does the dispatcher have any capability/permission/context a lead does not?

Checked in code, not docs. Findings:

- **Only a human can create a dispatcher via `sb start`.** `switchboard/cli.py:801-807`:
  the `start` branch calls `_agent_caller(me)` and refuses if the caller is an agent
  (`if (who := _agent_caller(me)) is not None: refuse`). So a top-level dispatcher, the
  kind that gets its own space and is the tree's root, can only come from a human typing
  `sb start`.
  - Caveat, confirmed by both DESIGN-TRUTH.md:56-64 and the dispatcher.md comment
    (lines 110-120): the `dispatcher` **role/prompt** is NOT gated. A lead could type
    `sb delegate ... --role dispatcher` and get a child holding the dispatcher prompt,
    with a parent above it and no `is_top` stamp — nothing in the code stops this, it is
    only stopped by lead.md explicitly telling leads dispatcher "is not one of your
    options" (lead.md:176-178). So the true dispatcher-that-is-the-top-of-a-tree is
    gated by code (`_agent_caller` + the `is_top` stamp only `_top`/`sb start` writes);
    the dispatcher *prompt* by itself is just an ordinary, ungated role like any other.
- **`sb board` (the full-tree human view) is human-only.** `cli.py:786-798` — same
  `_agent_caller` gate, refused for any agent caller regardless of role. This is not
  dispatcher-specific; no role, including dispatcher, can run it.
- **Only the dispatcher (as top) mints new spaces/worktrees for its children.**
  `broker.py:3079-3115`, the "fork rule": a spawn forks a new space+worktree only when
  the CALLER is a top (`self.mints_space(me)`, reading the `is_top` stamp). A lead's
  children are tabs sharing the lead's own worktree. This is a mechanical consequence of
  being the top of the tree (stamped only by `_top`/`sb start`), not something granted to
  the "dispatcher" role by name — but in practice, since only `sb start` creates a top and
  `sb start` always produces a dispatcher, only a dispatcher exhibits this behavior.
- **Fleet-wide visibility:** I did not find anything giving the dispatcher visibility a
  lead lacks. DESIGN-TRUTH.md:316-319 says siblings within one dispatcher's tree are
  visible to each other via `sb status`/board, but any OTHER dispatcher's entire tree is
  invisible — so a dispatcher's own scope is "the whole of its own tree" (DESIGN-
  TRUTH.md:229-230), same as a lead's scope is the whole of its own subtree; neither sees
  across dispatcher boundaries, and I found no code path giving a dispatcher any global
  store query a lead cannot also make over its own subtree.
- **The dispatcher is the only role told to talk to the human at all as part of its
  ordinary job** — `sb block` is available to every role, but dispatcher.md makes
  "putting a finished piece of work in front of the person" its literal one required
  report (dispatcher.md:184-189), whereas lead.md frames `sb block` as for a "genuinely
  theirs" decision or a broken tool of its own, with everything else going through `sb
  done` to its (possibly non-human) parent (lead.md:237-241). This is a prompt-level
  difference, not a code-enforced one — nothing stops a lead from calling `sb block`, and
  nothing stops a dispatcher from calling `sb done` (it just has no parent to send it to,
  since it's the top).

Net: the only HARD, code-enforced dispatcher-vs-lead differences are (a) only a human can
make a real top-of-tree dispatcher (`sb start` refused to agents), and (b) only a top
mints new spaces/worktrees on delegate. Everything else — no work, relay verbatim, no
cleanup, cross-repo stop-and-ask, being the one who blocks for the human — is prompt text
only, per DESIGN-TRUTH.md:476-479's explicit "no gate, no blocked verbs... a well-written
prompt is judged sufficient" and the dispatcher.md comment block saying the same.

## Confidence / what I did not check

- I read `defaults/protocol.md`'s *description* via the dispatcher.md comment but did not
  do a full line-by-line read of protocol.md itself — if the brief wants the protocol's
  exact wording quoted too, that still needs doing.
- I did not trace `_resolve_bindings`/preset binding config to see whether this repo's
  `.switchboard/` (if any) binds different presets to dispatcher vs lead — I only
  confirmed the shipped `defaults/roles/*.md` and `defaults/prompts.toml`.
- Section 6's fleet-wide-visibility claim is a negative finding (I did not find code
  granting it) rather than a confirmed absence proven by reading every query path in
  broker.py.
