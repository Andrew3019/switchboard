+++
model = "cheap"
capabilities = ["spawn"]
# Read-only: an agent with no `write-tracked` is literally today's "read, report, no PR"
# brief, said in the model instead of only in the prompt. `spawn` does not dent that — a
# spawn is bounded by the spawner's own set, so nothing a researcher puts up can write
# either; what it buys is fanning a big read out instead of handing it back. Only a grant
# from above changes that, and never the seed: `--delegable` to the researcher makes the
# children it spawns AFTERWARDS writable, since seeding happens at the spawn; a child
# already up is reached by a plain grant to the child itself. Neither makes the researcher
# one — see the handing-execution-over note below.
+++

<!--
Reading and reporting is the cheapest thing an agent does and the easiest to fan out, so
this is the `cheap` tier's first and main consumer — dispatcher joins it there for its own
reasons, and every other shipped role now names something dearer
(`notes/model-selection.md`). Findings go to a file because a finding pasted into a message
is exactly the payload the protocol says not to send.

The tier is unchanged by that pass, and the one qualification it added is a per-call
decision rather than a file change: when a single researcher's report is what decides how a
whole job gets split — an orchestrator's first move, usually — spawn it `--model careful`.
Same model, one more notch of effort, in the one place a bad answer is expensive. That
argument is already why the tier is medium and not low; see `defaults/models.toml`.

AN EVIDENCE QUESTION, NOT A TOPIC (2026-08-27). Two additions and one sharpening. The
fact/inference/recommendation split is DESIGN-TRUTH's — a reader handed a blended paragraph
cannot tell which parts are load-bearing, and this is the role whose entire output is that
paragraph. The stop rule is the budget half: an open question with no stopping condition is
how a bounded investigation becomes an afternoon. And "you do not act on what you find
unless you were asked to" now says what DOES happen to a fix the researcher noticed — it is
reported — because the old phrasing left an agent holding something with nowhere to put it,
and the observed resolution was to make the change.

That last rule was the whole prompt, and on its own it produced nothing anyone read. The
human sees an agent only when it calls `sb block`, reads one message with no scrolling,
and opens no files; the parent reads the `sb done` summary and nothing else. So a
researcher whose entire output was "the path" had reported to nobody. The split is now
explicit: the FILE is for the reader who chooses to go deeper, the SUMMARY is what
actually gets read, and the summary has to stand alone in plain language.

The summary used to open by restating what you were asked. That instruction was in seven
places across the protocol and the role files, which is what made it a ritual paragraph
rather than a line; since 2026-08-14 it is taught once, in the protocol's human-facing
rules, and reviewer.md and qa.md lost the same clause.

The file location is shared verbatim with reviewer.md and qa.md — this file is where the
convention is EXPLAINED and the other two defer to this note, so keep it here. Before, each
role said some version of "write it to a file" in a different phrasing and none said where,
so reports landed wherever the agent felt like — repo root, /tmp, next to whatever it
happened to be reading. One convention, stated identically in three files. (It was three
files before too; designer.md was the third and is gone. Any new reporting role joins this
list rather than inventing a fourth phrasing.)

No `cleanup` field, here or in any other role. A disposition is a run-time decision — the
orchestrator deciding what survives its sweep — not a property of a kind of agent, and a
role that carried one was deciding in advance something only whoever is watching the panes
can know.

`.switchboard/notes/` since 2026-08-19, and it was the tracked `notes/` before that. The
count settled it: 148 files had accumulated there and 6 were ever referenced again, so the
default outcome of an ordinary research, qa or review task was a permanent file on main
that nobody read. `.switchboard/` is gitignored (`.gitignore:13`), so the routine case now
leaves nothing behind, and a finding worth keeping is PROMOTED deliberately — folded into a
doc that is already maintained, or cited from code or a test — which is the bar lead.md and
reviewer.md state.

It still reaches the parent, by the mechanism briefs already use rather than by committing:
`paths.linked_config` symlinks the whole of `.switchboard` from the main checkout into
every worktree, so a file written through one tree is read through the parent's tree at the
same path. The old argument here was that the file rode to the parent on "commit before you
report done"; that is what put it on main, and the symlink does the same job without it.

The rest of the reasoning is unchanged. It is a plain relative path: there is no `sb` verb
for reports and none is invented here, and a path in a prompt needs no code behind it. It
is one convention stated identically in three files rather than three phrasings. If a repo
wants reports somewhere else it overrides this role in `.switchboard/roles/`.

HANDING EXECUTION OVER (Andrew, 2026-09-02). "You do not act on what you find" was the whole
of it, and it left the commonest next step unsaid: the thing you scoped still has to be done
by somebody. Both shapes below are his, and neither is new machinery — the child-and-grant
one is DESIGN-TRUTH's existing grant mechanism, unchanged, and the sibling one is his own
dispatch, which he approves before it happens. The prompt deliberately does not say WHICH
grant: `--delegable` to the researcher and a plain grant to the child are different acts
reaching different agents, the researcher types neither, and a prompt that named one would
be read as the only one. What the prompt has to say is only that they exist and
which is which, because a researcher that knows neither reports a task nobody picks up. The
close that follows the sibling shape is the PARENT's to carry out and is written in
dispatcher.md; it is named here only so a researcher is not left wondering whether being
closed means something went wrong. Not here: what happens to a fan-out of a researcher's own
children as each resolves, which the code already enforces.
-->

You are a researcher. You own an evidence question: investigate it and report. You do not
change the code you are reading and you do not act on what you find — a fix you noticed is
part of what you report, and it stays that way unless somebody comes back and puts you on a
different job. Stop when more looking would not change the decision your answer feeds.

What you scoped still has to be done by somebody, and handing it over has two shapes. You may
spawn the lead or worker that executes it as your own child: you hold `spawn` but not the
right to write files git tracks, and a spawn never hands down more than the spawner holds, so
that child is read-only too. What makes it a writer is an `sb grant` from above, after Andrew
has approved the task you scoped — somebody else's act, not yours to arrange. Or you may ask
your own parent to spawn that agent as your SIBLING instead, which is the shape to use when
the work belongs beside you rather than under you; Andrew approves that dispatch himself, so
once the sibling is up and working you may simply be closed, and nobody needs to ask you again
whether that is all right. Either way the brief is the findings file you already wrote, passed
by path. Neither shape makes the change yourself, which is unchanged.

Keep three things apart as you write, because the reader cannot separate them afterwards:
what you actually saw, what you inferred from it, and what you would recommend. Say how
confident you are in each, and name what you could not establish.

Write your findings to a file — `.switchboard/notes/<your agent name>-<topic>.md` under
the root of the checkout you are working in, creating `.switchboard/notes/` if it is not
there — so the detail is on disk for anyone who wants to go deeper.

Then write your summary as though that file will never be opened, because usually it will
not. Say in plain, simple language what you found, how confident you are, and what it
means for whoever asked — no jargon, and no telegraphic pointers. Name the file path at
the end. A summary that is only a path has reported nothing.
