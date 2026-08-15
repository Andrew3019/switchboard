# How is a decision request best presented to a human? (research)

Question: when an agent writes one message to a human, asking for a decision, and then
stops — what does the research on reading, writing, and choice actually say about how
that message should be shaped? Web research only, real sources, no LLM blog spam.

Findings are grouped by territory. For each: the source, what it actually found, and what
it implies for our messages. Disagreements are called out, not averaged.

---

## 1. People don't read on screens, they scan

**Source:** Nielsen Norman Group, ["F-Shaped Pattern For Reading Web Content"](https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content-discovered/)
(original eye-tracking study) and the [2020 update](https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content/).

- On an average page, users read at most 28% of the words during a visit — 20% is more
  likely. This number has held for ~20 years across devices.
- Eye-tracking shows a first full horizontal pass near the top, a second shorter pass
  lower down, then a vertical scan down the left edge. Attention drops off sharply after
  the first couple of lines and increasingly falls to first-words-of-line only.

**Implication:** whatever the decision and the reasoning behind it are, assume only the
top ~2 lines and the left edge of every subsequent line get real attention. This is not
an argument for a template — it's an argument that *where* the load-bearing content sits
matters more than how much of it there is. A message that puts the ask in the middle,
however short, is read as if the ask isn't there.

---

## 2. Concise / scannable / objective, with real usability numbers

**Source:** Nielsen Norman Group / Jakob Nielsen, ["Concise, SCANNABLE, and Objective: How
to Write for the Web"](https://www.nngroup.com/articles/concise-scannable-and-objective-how-to-write-for-the-web/).

A controlled study rewrote the same content four ways and measured task performance
against a baseline ("marketese", promotional prose):
- Concise phrasing alone: **+58%** measured usability
- Scannable formatting alone: **+47%**
- Objective (non-promotional) tone alone: **+27%**
- All three combined: **+124%**
- A follow-up applying this to real pages found **+159%**

Notable: conciseness alone (58%) beat scannable *formatting* (47%) beat tone (27%). Cutting
words mattered more than headings/bullets, which mattered more than tone.

**Implication:** if we had to rank levers, trimming word count for its own sake outranks
adding structure, which outranks softening the tone. This argues against "add a bolded
summary line" as the fix and for "say it in fewer words" as the fix — structure is a
distant second, not the main event. It also is evidence *against* imposing a fixed
section list: the win came from deciding what to cut, which is a judgment call per
message, not a shape to replicate.

---

## 3. BLUF — bottom line up front

**Source:** U.S. Army Regulation 25-50 (1988, still the standard across service branches);
summarized in [Matt Ström-Awn, "Bottom Line Up Front: write to make decisions
faster"](https://mattstromawn.com/writing/bluf/) and [AirOps' overview](https://www.airops.com/blog/bottom-line-up-front-bluf).

- The doctrinal structure is two moves: a purpose sentence (why this message exists, what
  you need from the reader) immediately followed by the main point — the actual
  conclusion, recommendation, or decision needed.
- Explicit distinction in the source material: a BLUF is not a topic sentence. "This memo
  addresses the proposed budget revision" is a topic sentence. "I recommend we cut the Q3
  budget by $200k to cover the facilities overrun" is a BLUF. The difference is that a
  BLUF is actionable on its own — a reader who stops after sentence one can already act.

**Implication:** the test for our first sentence shouldn't be "does it state the topic" —
it should be "if the human read only this sentence and nothing else, could they still
make the call?" That's a property to check for, not a phrase to copy, so it survives the
anchoring constraint.

---

## 4. Inverted pyramid — same idea, from journalism

**Source:** [NN/g, "Inverted Pyramid: Writing for Comprehension"](https://www.nngroup.com/articles/inverted-pyramid/);
general journalism-craft literature on the structure.

- Information goes from most-important to least, so a reader who stops at any point still
  has the most important facts they've reached so far.
- NN/g's stated rationale is about *mental models*: leading with the conclusion lets the
  reader build a scaffold that makes the following detail easier to place and interpret,
  rather than holding facts in memory ungrounded until a conclusion arrives at the end.
- Caveat: NN/g's own article does not cite a controlled study with numbers for this claim
  — it's argued from observed reading behavior (see #1), not measured directly. Treat this
  one as well-reasoned but not independently quantified.

**Implication:** order the message so each additional sentence is answering "given what
you already know, here's the next most important thing" — not building up to a reveal.
This is the same shape as BLUF but framed as *reader comprehension*, not just attention:
leading with the conclusion also makes the supporting detail easier to understand, not
just more likely to be seen.

---

## 5. Plain language standards are blunt about structure, not style

**Source:** [Federal Plain Language Guidelines](https://www.plainlanguage.gov/guidelines/),
Plain Writing Act of 2010; [GOV.UK content design guidance](https://www.gov.uk/guidance/content-design/writing-for-gov-uk).

- Federal guidelines: write for the audience, organize around what the reader needs to do,
  cut anything that doesn't serve that, avoid jargon and redundancy.
- GOV.UK: ~80% of visits to GOV.UK guidance pages are task-driven, and their own citation
  of NN/g research is that people will not read background text that isn't relevant to the
  task in front of them. Their applied rule is to front-load the actionable content and
  push background/justification later or drop it.

**Implication:** both standards converge on the same test — is this sentence in service of
the reader completing their task (here: deciding), or is it context the writer wanted to
include? Background that doesn't change the decision is a tax on the reader, not a
courtesy. This is a screening question the writer applies per-sentence, which again avoids
being a pattern to mechanically copy.

---

## 6. Line length: there's a real sweet spot, and getting it wrong measurably hurts

**Source:** Dyson & Haselgrove (typography research, summarized in ["Optimal Line Length in
Reading — A Literature Review"](https://www.researchgate.net/publication/234578707));
[Baymard Institute, "Readability: The Optimal Line Length"](https://baymard.com/blog/line-length-readability);
WCAG.

- Medium line length (~55 characters per line) supported effective reading at both normal
  and fast reading speeds better than very short or very long lines in Dyson & Haselgrove's
  study.
- Baymard found product-description text wider than 80 characters per line was **skipped
  41% more often** than text kept to 60–70 characters per line.
- WCAG's accessibility guidance caps body text at 80 characters per line (40 for CJK) as a
  hard ceiling, not a target.
- General convergence across sources: **~50–75 characters per line**, both too-short and
  too-long lines cost readability, not just too-long.

**Implication:** this is about the terminal's actual rendered width, not prose length —
irrelevant to what our message *says*, but relevant to how it should be laid out if we
ever format it (paragraph width, avoiding one giant unbroken line). Since the terminal
generally reflows to its column width already, the more directly actionable version of
this finding is: don't manually hand-wrap text or paste content whose native line length
is very different from the terminal's — let it reflow, because both under- and
over-wrapping have a measured comprehension cost, not just an aesthetic one.

---

## 7. Choice overload: real, but the effect is smaller and more conditional than commonly repeated

**Sources, in tension:**
- Iyengar & Lepper's original ["jam study"](https://www.jstor.org/) (2000): 24-jam display
  drew more browsers (60% vs 40%) but far fewer buyers (3% vs 30%) than a 6-jam display.
  Widely cited as proof more options reduce action.
- **Scheibehenne, Greifeneder & Todd (2010), "Can There Ever Be Too Many Options? A
  Meta-Analytic Review of Choice Overload,"** *Journal of Consumer Research* 37(3),
  [PDF](https://scheibehenne.com/ScheibehenneGreifenederTodd2010.pdf) — a meta-analysis of
  50 experiments (63 conditions, N=5,036) found the **average effect size across all
  studies was statistically indistinguishable from zero**, with high variance between
  studies. Choice overload showed up reliably only under specific preconditions: options
  that are hard to compare, high perceived stakes, and a chooser without domain expertise
  in that decision.

**These sources disagree, and the disagreement matters more than either finding alone.**
The famous "more options = worse" result does not replicate as a general law; it's real
only in a specific pocket of conditions. Our decision requests plausibly *do* sit in that
pocket some of the time (unfamiliar tradeoffs, agent-authored options the human didn't
generate themselves) but not always (a human choosing between two things they already
understand well isn't at risk).

**Implication:** don't treat "fewer options is always better" as a law to apply
mechanically — the actual finding is that overload risk rises specifically when the
options are hard to compare or the human lacks context, which is a property of the
specific decision, not a fixed number to cap at. The lever that's actually supported by
evidence is *making options easy to compare* (See #8), not just counting them down to some
number.

---

## 8. Leading with a recommendation moves the outcome — that's a lever, not free

**Source:** general anchoring-bias literature (Tversky & Kahneman's original anchoring
work; summarized in [The Decision Lab](https://thedecisionlab.com/biases/anchoring-bias)
and others) plus applied pricing-page research on "highlighted"/recommended options
increasing selection of that option.

- Anchoring bias: the first number or option a person sees becomes a reference point that
  subsequent judgment is pulled toward, even when the anchor is arbitrary or irrelevant.
  This is one of the most replicated findings in judgment-and-decision-making research.
  Adjustment away from an anchor is typically insufficient.
- Applied result: marking one option as "recommended" measurably increases the rate people
  pick it, independent of the option's actual merits.

**In tension with:** Yaniv & Kleinberger's advice-taking research (["Advice Taking in
Decision Making: Egocentric Discounting and Reputation
Formation"](https://ratio.huji.ac.il/files/dp212.pdf)) found that people systematically
**discount** advice relative to their own judgment — they weight their own reasoning more
heavily than an advisor's, because they have access to their own reasons but not the
advisor's. This cuts the other way from anchoring: it suggests people don't blindly
follow a stated recommendation, they weigh it down.

**These two literatures point in different directions and neither is about our exact
case** (a message with only a recommendation on offer, not a menu with one item
highlighted, and not an advisor giving a second opinion after the person already formed
a view). Be honest that this is inference, not a direct finding: stating a recommendation
plausibly does pull the outcome toward it (anchoring), but a human who has their own
stake in the decision won't just default to it uncritically (egocentric discounting).

**Implication:** whether to state a recommendation isn't answered cleanly by the
literature — it depends on whether the goal is *fast correct-enough decisions* (favors
stating one, per BLUF and plain-language conventions above) or *avoiding steering the
human's independent judgment on a genuinely open call* (favors laying out options
neutrally). The honest takeaway is: this is a tradeoff to make consciously per-decision,
not a settled question — don't encode "always recommend" or "never recommend" as a rule.

---

## 9. Working memory caps how much can be weighed at once

**Source:** George Miller, "The Magical Number Seven, Plus or Minus Two" (1956); revised
downward by Cowan (2001), summarized in [Journal of
Cognition](https://journalofcognition.org/articles/10.5334/joc.387) — Cowan's later work
puts the real limit closer to **~4 chunks** when rehearsal/support is controlled for,
not 7.

**Implication:** this is really the mechanism behind #7 (choice overload) and behind why
messages that list many separate considerations become hard to hold in mind at once. The
actionable version isn't a hard cap on option count — it's that each additional
independent thing the reader has to hold in mind while deciding (a fact, a tradeoff, an
option) has a real, measured cost once you're past a small handful. This argues for
grouping related considerations into one point rather than listing them as separate ones —
chunking, not truncating.

---

## 10. Closed (yes/no) questions get faster, more decisive answers than open ones

**Source:** general survey-methodology literature on closed- vs. open-ended questions
(no single canonical study, but the finding is consistent across the methodology
literature) — closed-form questions are answered faster and more consistently because the
respondent isn't also doing the work of generating the option space.

**Implication:** the most direct lever we have isn't message length at all, it's whether
the message can be answered with a word. A message built so the actual ask resolves to a
yes/no, a pick-one-of-a-small-set, or a single number is doing more for the human's
answering speed than any amount of trimming prose around a genuinely open-ended question.
If the underlying decision truly isn't reducible to that shape, no amount of brevity
elsewhere fully compensates — the fix is upstream, in how the question was framed before
it was ever written down.

---

## 11. Decision fatigue / cognitive load: relevant but overstated if taken as "just be short"

**Source:** Baumeister et al. on ego depletion (1998, self-control as a depletable
resource); more recent critical literature (e.g. summarized in [Global Council for
Behavioral Science](https://gc-bs.org/articles/the-depleted-mind-the-science-of-decision-fatigue-and-ego-depletion/))
notes the original "resource depletion" model has been substantially challenged by
replication failures, and current thinking treats motivation and framing, not just
cumulative decision count, as comparably important drivers of decision quality.

**Implication:** don't lean on "decision fatigue" as if it's settled science that any
single message must be minimized at all costs — the mechanism is contested. What is not
contested is the simpler point already covered above (#9): more independent things to
hold in mind at once measurably costs the reader. Ground any brevity argument in working
memory / attention research (solid), not in ego-depletion (shakier).

---

## 12. "Caveman mode" / telegraphic register — what's actually known

Added scope from main-16/Andrew: research telegraphic writing (dropping articles,
auxiliaries, filler — "spec contradicts itself, two options, pick one") as a register.
Where it comes from, whether comprehension research supports it, how it interacts with
skimming, and critically what it costs. Andrew wants partial application (~10–25%
telegraphic), so the real question is whether there's a principled line for *which parts*
of a message can go telegraphic, not a global dial.

**Where the term comes from, split into two unrelated traditions:**

1. **Developmental linguistics.** Roger Brown & Colin Fraser coined "telegraphic speech" in
   the early 1960s for toddlers' two/three-word utterances that drop function words
   (articles, auxiliaries, prepositions, tense morphemes) and keep only content words —
   named for its resemblance to a paid-by-the-word telegram. ([Springer summary](https://link.springer.com/rwe/10.1007/978-1-4419-1698-3_1123))
2. **"Caveman mode" as an LLM-prompting fad (2026).** Circulates as a Claude Code plugin
   convention (`/caveman`), explicitly targeting *token cost*, not human reading —
   dropping articles, filler, pleasantries, and sign-offs to cut LLM output tokens by
   60–80%. ([Medium writeup](https://medium.com/data-science-in-your-pocket/what-is-caveman-prompt-reduce-llm-token-usage-by-60-6a552734a493),
   [example implementation](https://pasqualepillitteri.it/en/news/846/claude-code-caveman-mode-token-saving))
   This tradition optimizes for a different reader (a tokenizer/model) than ours (a human
   deciding something), and its "no measurable quality drop" claims are about code output
   correctness, not about a human's speed or accuracy reading a decision request — it is
   not evidence for our case and shouldn't be cited as if it were.

**The closest real evidence to our question is a third, distinct tradition: "headlinese."**
Newspaper headlines are a long-studied telegraphic register — omitting determiners,
auxiliaries, and copulas, using infinitives for future tense — and there is actual
comprehension research on it, not just style commentary:

- **Register affects language comprehension: ERP evidence from article omission in
  newspaper headlines**, *Journal of Neurolinguistics* (2010).
  ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0911604410000989))
  Readers were shown article-less noun phrases ("policeman arrests monk") either knowing
  they were reading headlines or not. Finding: an N400 effect showed up regardless —
  article-less phrases carry a real processing cost — but the *source* of that cost is at
  the syntax-discourse "linking" level (working out what the missing article would have
  specified — a *specific* policeman vs *a* policeman), **not** at the level of basic
  grammatical parsing. In other words: omission doesn't break parsing, but it does make the
  reader do extra inferential work to recover what was dropped, every single time,
  independent of whether they know to expect the register.
- **Reading between the (head)lines: A processing account of article omissions in
  newspaper headlines and child speech** ([full text PDF via academia.edu mirror](https://www.academia.edu/27170550/Reading_between_the_head_lines_A_processing_account_of_article_omissions_in_newspaper_headlines_and_child_speech)).
  Frames headline and child-speech omission as the same underlying phenomenon: articles
  and other function words get dropped first under processing/production pressure because
  they carry the least unique information relative to their cost — content words (nouns,
  verbs) are dropped last because they carry the most.
- **Headline linguistics literature more broadly** ("headlinese" as a register since
  Straumann 1935): omission of function words is a deliberate economy-of-processing
  choice, but it is explicitly identified as **the source of headline ambiguity** — the
  same omissions that save space are what make headlines infamous for accidental double
  meanings ("garden path" misreadings), and this is treated as a real, not merely comic,
  cost in the literature. ([overview](https://jalt.com.pk/index.php/jalt/article/download/766/589/1362))

**What this converges on — a principled line, not a percentage:**

Function words aren't decoration; they're where reference and scope live. "The bug" vs "a
bug," "will" vs "did," "and" vs "or" — dropping these doesn't just cost elegance, it
removes the exact information that resolves *which one, when, whether, and how many*.
Content words (what the thing is, what decision is needed) survive compression fine
because the reader can reconstruct them from context; function words don't, because
they're what tells the reader how to relate the content words to each other and to the
world outside the sentence.

So the line isn't "which sentences" or "what fraction of the message" — it's **which
words within a sentence carry disambiguating information versus which carry only fluency**.
Concretely, from the research above:
- Safe to drop: filler, hedges, pleasantries, restated context, throat-clearing —
  words that add smoothness but that a reader would reconstruct identically whether
  present or absent.
- Costly to drop, precisely where the ERP evidence says the processing cost lands:
  articles/determiners when singular-vs-general or specific-vs-any is doing real work
  ("a fix" vs "the fix" when there are multiple candidate fixes); tense and modals when
  they distinguish what already happened from what's proposed, or what must happen from
  what could ("will break" vs "may break"); conjunctions when they distinguish "and" from
  "or" in an option list — this is exactly the kind of place headline ambiguity research
  documents as a real failure mode, not a hypothetical one; negation, always.
- The parts of a decision message where telegraphic compression is cheapest are
  exactly the parts BLUF/plain-language findings above (§3, §5) already say should be cut
  entirely rather than compressed — throat-clearing, restated context, hedged framing. The
  parts that must stay full prose are the ones doing modal, temporal, or quantificational
  work: the actual proposition being decided, and any place where "some/all," "will/may,"
  "or/and" is the entire content of the sentence.

**This gives a test that survives the anti-anchoring constraint:** before cutting a
function word, ask whether a reader who reconstructed it wrong would land on a different
understanding of the decision. If dropping "the" vs "a," or "will" vs "might," changes
what the human thinks they're being asked, it stays. If it doesn't, cutting it costs
nothing and is exactly the kind of trim the concise-writing research (§2) already rewards.
That's a per-word judgment call while writing, not a dial or a template.

---

## Net read, across sources

The literature converges cleanly on a small number of *properties* a message should have,
and is genuinely split or thin on a few others. Worth stating both, since the instruction
here is to avoid anything that reads as a template:

**Solid, convergent, across multiple independent literatures (NN/g, BLUF/military,
GOV.UK, plain language):**
- The actionable ask must be answerable from the first sentence alone — not just
  introduced, *answerable*. That's the actual test, not "is it short."
- Every sentence should be there because it's load-bearing for the decision, not because
  it's true or interesting. Cutting words the reader doesn't need to decide beats adding
  structure to make more words scannable.
- Order matters as much as length: most-decision-relevant first, regardless of how much
  total content there is.

**Real but conditional, don't over-apply:**
- Fewer options help mainly when the options are hard to compare or unfamiliar to the
  reader — it's not a universal "always fewer" rule, and the classic finding (jam study)
  did not replicate as a general law.
- Leading with a recommendation shapes the outcome (anchoring) but doesn't erase the
  human's independent judgment (egocentric discounting) — whether to state one is a
  genuine per-decision tradeoff, not a fixed default in either direction.

**Thin or contested — don't build on these alone:**
- "Decision fatigue" as commonly invoked rests on ego-depletion research that has
  significant replication problems. The working-memory/chunking finding (Miller/Cowan) is
  the sturdier version of the same intuition.
- The inverted-pyramid comprehension claim is well-reasoned but NN/g's own article cites
  no controlled study measuring it directly — it's inferred from the scanning-behavior
  data (#1), not independently verified.
- "Caveman mode" as an LLM-prompting fad has no comprehension research behind it at all —
  it optimizes token cost, not human reading. The real evidence (headlinese/ERP research,
  §12) says telegraphic compression is not free: it reliably costs processing effort
  exactly at function words that carry reference, tense, or scope, and is a documented
  source of ambiguity in headlines. It's real and usable, but only word-by-word, on the
  principled line in §12 — not as a global percentage.

**Because the fix can't anchor:** the throughline across the solid findings above is not a
shape to copy but a question to ask while writing — *if the human reads only the first
sentence, can they act? Is every subsequent sentence changing what they'd decide, or just
adding true things?* Those are tests applied while writing, not a structure to fill in,
which is what makes them usable without becoming a template themselves.
