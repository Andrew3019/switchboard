"""Board tests — the pure half of the clickable view.

`switchboard/board.py` had no tests at all, which is a problem specific to this file: it
is the one surface where being *subtly* wrong is invisible. A misdrawn row still looks
like a row, and the click that follows focuses a different agent than the one under the
cursor — silently, and indistinguishably from a correct click.

So what is pinned here is the mapping, not the appearance: decode → layout → agent_at.
That half is pure, which is why the terminal, herdr and the store are absent from it. The
last class is the exception, and says why it has to be.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import board, panel, richboard, status  # noqa: E402


def agent(name, *, depth=0, state="working", herdr_state="working", alive=True,
          stalled=False, gone=False, unread=0, task=None, blocked_why=None,
          summary=None, parent=None, archived=False, undelivered=0, undelivered_age=0,
          idle_excuse=None):
    """One agent. `archived=True` sets what being absent from herdr past the spawn
    grace actually looks like, so the real `AgentStatus.archived` decides — nothing
    here mocks the predicate."""
    return status.AgentStatus(
        name=name, role="worker", parent=parent, depth=depth, state=state,
        herdr_state=None if archived else herdr_state,
        alive=False if archived else alive,
        stalled=stalled, gone=gone, unread=unread,
        age=int(status.SPAWN_GRACE) + 1 if archived else 10,
        idle=5, last_activity=0, workspace="api", task=task,
        blocked_why=blocked_why, summary=summary,
        undelivered=undelivered, undelivered_age=undelivered_age,
        idle_excuse=idle_excuse,
    )


def snap(*agents):
    return status.Snapshot(now=0, agents=list(agents))


def blocks(rows):
    """The display ROWS drawn, one entry each, in order.

    An agent owns one screen line and a collapsed group one, but the breaks between
    first-level groups own none, so "what is on screen" and "how many lines is that" are
    not the same list. Consecutive lines with the same owner count once — which is the
    invariant the mapping rests on: a row's lines are adjacent and all carry it.
    """
    out = []
    for _, a in rows:
        if a is not None and (not out or a is not out[-1]):
            out.append(a)
    return out


class ParseSgrTest(unittest.TestCase):
    def test_a_click_decodes_to_button_column_and_row(self):
        events, rest = board.parse_sgr("\033[<0;12;7M")
        self.assertEqual(rest, "")
        self.assertEqual([e["button"] for e in events], [0])
        self.assertEqual((events[0]["col"], events[0]["row"]), (12, 7))
        self.assertTrue(board.is_left_click(events[0]))

    def test_a_sequence_split_across_two_reads_is_held_not_mangled(self):
        """os.read gives no guarantee of landing on an escape-sequence boundary."""
        events, rest = board.parse_sgr("\033[<0;12")
        self.assertEqual(events, [])
        self.assertEqual(rest, "\033[<0;12")
        events, rest = board.parse_sgr(rest + ";7M")
        self.assertTrue(board.is_left_click(events[0]))
        self.assertEqual(rest, "")

    def test_keystrokes_survive_alongside_mouse_events(self):
        events, _ = board.parse_sgr("q\033[<0;1;1M")
        self.assertEqual(events[0]["raw"], "q")
        self.assertIsNone(events[0]["button"])
        self.assertTrue(board.is_left_click(events[1]))

    def test_the_wheel_is_only_read_on_press(self):
        [up], _ = board.parse_sgr("\033[<64;1;1M")
        [down], _ = board.parse_sgr("\033[<65;1;1M")
        [release], _ = board.parse_sgr("\033[<64;1;1m")
        self.assertEqual((board.wheel(up), board.wheel(down)), (-1, 1))
        self.assertEqual(board.wheel(release), 0)


class GlyphTest(unittest.TestCase):
    def test_gone_outranks_everything(self):
        """A row saying `working` about a pane herdr cannot see is the one lie this view
        must never tell, so `gone` wins even over a block."""
        a = agent("w", gone=True, state="blocked", unread=3)
        self.assertEqual(board.glyph(a), "✗")
        self.assertEqual(board.marker(a), "GONE — herdr has no such agent")

    def test_every_glyph_has_a_colour_and_they_are_all_distinct(self):
        kinds = [agent("a", gone=True), agent("b", state="blocked"),
                 agent("c", stalled=True), agent("d", state="done"),
                 agent("e", alive=None), agent("f")]
        glyphs = [board.glyph(a) for a in kinds]
        self.assertEqual(len(set(glyphs)), len(glyphs))
        for g in glyphs:
            self.assertIn(g, board._GLYPH_COLOR)

    def test_only_one_marker_is_ever_shown_and_it_is_the_most_actionable(self):
        a = agent("w", state="blocked", blocked_why="need a key", unread=2,
                  task="do the thing")
        self.assertEqual(board.marker(a), "BLOCKED — need a key")


class RowSaysOneThingTest(unittest.TestCase):
    """The row must not contradict itself.

    Andrew reported seeing one agent drawn as `working` and `STALLED` at once. It was not
    a logic bug: the STATE column printed the store's self-report ("task still open") and
    the note printed the pane observation ("no turn is running"), two vocabularies on one
    line with nothing reconciling them. What is pinned here is that the column now shows
    the joined word and STALLED is only ever a qualifier beside it.
    """

    def line(self, a):
        """The agent's row. One line now, and the contradiction pinned here would be a
        contradiction wherever on it the two halves were drawn."""
        rows = board.layout(snap(a), top=0, height=10, width=200, msg="")
        return "\n".join(t for t, row in rows if row is a)

    def test_a_stalled_agent_reads_idle_and_never_working_as_well(self):
        line = self.line(agent("w", state="working", herdr_state="idle", stalled=True))
        self.assertIn("idle", line)
        self.assertNotIn("working", line)
        self.assertIn("STALLED", line)

    def test_the_word_is_whatever_the_pane_was_observed_to_be_doing(self):
        """An open task reads `working` or `idle` on herdr's observation alone — and on
        nothing at all when there was no observation to make: with herdr unreachable
        (`alive is None`) the store's own word stands, the same rule `stalled` and `gone`
        are built on, and `render` says at the top that ALIVE is unknown."""
        # Explained idle — a lead waiting on live children. Same word, no warning.
        lead = self.line(agent("lead", state="working", herdr_state="idle",
                               stalled=False, task="mind the children"))
        self.assertIn("idle", lead)
        self.assertNotIn("STALLED", lead)
        self.assertIn("working", self.line(agent("w", herdr_state="working")))
        unreachable = self.line(agent("u", state="working", herdr_state=None, alive=None))
        self.assertIn("working", unreachable)
        self.assertNotIn("idle", unreachable)


class IdleReadsAsOneThingTest(unittest.TestCase):
    """Idle told apart from stalled, which is the question Andrew asked of this row.

    Both rows say `idle` and they mean opposite things: one is a lead doing exactly what
    the protocol asked of it, the other quietly died. What is pinned here is that the row
    says which, rather than leaving a reader to infer it from the tree.
    """

    def line(self, a):
        """The agent's row. One line now, and the contradiction pinned here would be a
        contradiction wherever on it the two halves were drawn."""
        rows = board.layout(snap(a), top=0, height=10, width=200, msg="")
        return "\n".join(t for t, row in rows if row is a)

    def test_an_explained_idle_row_says_what_explains_it(self):
        line = self.line(agent("lead", state="working", herdr_state="idle",
                               idle_excuse="waiting on children", task="mind them"))
        self.assertIn("idle", line)
        self.assertIn("waiting on children", line)
        self.assertNotIn("STALLED", line)

    def test_an_unexplained_idle_row_reads_as_needing_attention(self):
        a = agent("w", state="working", herdr_state="idle", stalled=True,
                  task="fix the parser")
        line = self.line(a)
        self.assertIn("STALLED", line)
        self.assertTrue(board.wants_you(a))       # the ← marker, and the ◌ glyph
        self.assertEqual(board.glyph(a), "◌")

    def test_a_pane_herdr_cannot_read_asks_for_a_keypress_instead_of_reporting_a_stall(self):
        """The narrower label REPLACES the word and nothing else: same row, same section,
        same glyph, and it says what a person has to do. The stalled row above is the
        control — detection saying no, or never being asked, still reads STALLED."""
        a = agent("w", state="working", herdr_state="idle", stalled=True,
                  task="fix the parser")
        a.awaiting_keypress = True
        line = self.line(a)
        self.assertIn("AWAITING KEYPRESS", line)
        self.assertIn("press a key in its pane", line)
        self.assertNotIn("STALLED", line)
        self.assertTrue(board.wants_you(a))
        self.assertEqual(richboard.marker_short(a), "KEYPRESS")
        self.assertEqual(richboard.needs_kind(a), "blocked")
        self.assertIn("press a key in its pane", richboard.needs_reason(a))
        self.assertIn(a, richboard.needs_list([a]))

    def test_mail_alone_no_longer_marks_the_agent_row(self):
        """It used to: unread mail took over the note and the `←`, so an agent with mail
        looked like an agent in trouble. Mail names itself where it is drawn, and the
        row goes back to saying what the agent is doing."""
        a = agent("w", unread=2, task="fix the parser")
        self.assertFalse(board.wants_you(a))
        self.assertEqual(board.tail_note(a), "fix the parser")


class OneLineTest(unittest.TestCase):
    """Every agent is exactly one line, and everything it has to say is on it.

    The row was split in two and Andrew did not like it, so it is back: identity, then
    as much of `detail_bits` as the width allows, in priority order. What a test can
    catch is the "exactly one" — a block that is sometimes one line and sometimes two
    is a tree a reader cannot scan and a click path that has to be re-argued.
    """

    def rows(self, *agents, height=20, width=80):
        return board.layout(snap(*agents), top=0, height=height, width=width, msg="")

    def lines(self, rows, a):
        return [board._ANSI.sub("", t) for t, row in rows if row is a]

    def test_every_agent_costs_exactly_one_line_whatever_it_has_to_say(self):
        loud = agent("loud", state="blocked", blocked_why="need a key", unread=3,
                     undelivered=1, undelivered_age=60, task="do the thing")
        quiet = agent("quiet")
        rows = self.rows(loud, quiet)
        self.assertEqual(len(self.lines(rows, loud)), 1)
        self.assertEqual(len(self.lines(rows, quiet)), 1)

    def test_identity_and_detail_share_the_one_row(self):
        a = agent("w", state="blocked", blocked_why="need a key", unread=2,
                  task="fix the parser")
        [line] = self.lines(self.rows(a), a)
        self.assertIn("blocked", line)                      # name, state, timing
        for said in ("BLOCKED", "need a key", "unread", "fix the parser"):
            self.assertIn(said, line)

    def test_priority_is_trouble_then_mail_then_context(self):
        a = agent("w", state="blocked", blocked_why="need a key", unread=2,
                  task="fix the parser")
        self.assertEqual([kind for _, _, kind in board.detail_bits(a)],
                         ["marker", "mail", "tail"])
        [line] = self.lines(self.rows(a), a)
        self.assertLess(line.index("BLOCKED"), line.index("mail:"))
        self.assertLess(line.index("mail:"), line.index("fix the parser"))

    def test_context_is_dropped_first_and_mail_is_never_crowded_out(self):
        """Sixty columns, a verbose block and mail waiting. The task head goes, because
        it is the piece a reader can get elsewhere — and the mail stays, because it is
        quite possibly the answer that ends the block."""
        a = agent("w", state="blocked", unread=1, undelivered=1, undelivered_age=900,
                  blocked_why="whether to merge #33 before or after the board work lands",
                  task="put every agent back on one line")
        [line] = self.lines(self.rows(a, width=60), a)
        self.assertIn("BLOCKED", line)
        self.assertIn("UNDELIVERED", line)
        self.assertNotIn("put every agent", line)

    def test_an_explained_idle_agent_shows_its_excuse_on_the_row(self):
        """The distinction Andrew asked for survives the return to one line: the excuse
        rides in rank three, and an agent with an excuse has no marker competing for the
        room, so it is what the row shows."""
        a = agent("lead", state="working", herdr_state="idle",
                  idle_excuse="waiting on children", task="mind them")
        [line] = self.lines(self.rows(a, width=60), a)
        self.assertIn("idle", line)
        self.assertIn("waiting on children", line)
        self.assertNotIn("STALLED", line)

    def test_undelivered_is_named_and_the_rest_counted_by_subtraction(self):
        """UNDELIVERED is the loud one: unread means we rang and it has not looked;
        undelivered means it was never told. Never double-counted — undelivered is a
        subset of unread."""
        a = agent("w", unread=3, undelivered=1, undelivered_age=720)
        self.assertEqual(board.mail_note(a), "mail: UNDELIVERED 1, 12m · 2 unread")
        self.assertEqual(board.mail_note(agent("q")), "")

    def test_a_click_resolves_to_the_agent_on_that_row(self):
        """THE PROOF, at the shape the board is actually drawn in."""
        rows = self.rows(agent("one", unread=2), agent("two"), agent("three"))
        drawn = [(i + 1, a.name) for i, (_, a) in enumerate(rows) if a is not None]
        self.assertEqual([n for _, n in drawn], ["one", "two", "three"])
        for row, name in drawn:
            self.assertEqual(board.agent_at(rows, row).name, name)

    def test_a_row_never_widens_the_screen(self):
        rows = board.layout(snap(agent("日本語", unread=99, undelivered=99,
                                       undelivered_age=99999,
                                       task="日本語の説明" * 20)),
                            top=0, height=10, width=40, msg="")
        for text, _ in rows:
            self.assertLessEqual(board._visible_len(text), 40)


class GroupBreakTest(unittest.TestCase):
    """A blank line between first-level groups, and nowhere else.

    Each direct child of the top orchestrator usually bounds one task, along with its
    whole subtree, and the tree is much easier to read in those blocks. Two things can go
    wrong and both are pinned here: a break INSIDE a subtree, which splits one task in
    half, and a break that belongs to an agent, which would make a click on empty space
    focus somebody.
    """

    def tree(self, **kw):
        """main, and two first-level groups, one of them two deep."""
        return snap(agent("main"),
                    agent("lead", depth=1, parent="main"),
                    agent("w1", depth=2, parent="lead"),
                    agent("w2", depth=2, parent="lead"),
                    agent("solo", depth=1, parent="main"))

    def shape(self, rows):
        """The tree part of the screen as names and blanks, in order."""
        out = []
        for text, a in rows:
            plain = board._ANSI.sub("", text).strip()
            if a is not None:
                out.append(getattr(a, "name", "GROUP"))
            elif out and plain == "":
                out.append("")
        while out and out[-1] == "":
            out.pop()
        return out

    def test_the_break_falls_between_groups_and_never_inside_one(self):
        rows = board.layout(self.tree(), top=0, height=14, width=60, msg="")
        self.assertEqual(self.shape(rows),
                         ["main", "", "lead", "w1", "w2", "", "solo"])

    def test_a_break_is_owned_by_nobody_so_clicking_it_does_nothing(self):
        rows = board.layout(self.tree(), top=0, height=14, width=60, msg="")
        blank = next(i for i, (t, _) in enumerate(rows)
                     if board._ANSI.sub("", t).strip() == ""
                     and any(a is not None for _, a in rows[:i]))
        self.assertIsNone(board.agent_at(rows, blank + 1))

    def test_every_other_row_still_resolves_to_the_agent_drawn_on_it(self):
        rows = board.layout(self.tree(), top=0, height=14, width=60, msg="")
        drawn = [(i + 1, a.name) for i, (_, a) in enumerate(rows) if a is not None]
        self.assertEqual([n for _, n in drawn],
                         ["main", "lead", "w1", "w2", "solo"])
        for row, name in drawn:
            self.assertEqual(board.agent_at(rows, row).name, name)

    def test_a_break_costs_a_line_of_the_window_rather_than_overflowing_it(self):
        """The break is paid for out of the same screen, or the footer ends up claiming
        rows that were pushed off the bottom."""
        height = board.CHROME + 4                   # main, break, lead, w1
        rows = board.layout(self.tree(), top=0, height=height, width=60, msg="")
        self.assertEqual(len(rows), height)
        self.assertEqual(self.shape(rows), ["main", "", "lead", "w1"])
        self.assertIn("+2 more below", "\n".join(t for t, _ in rows))

    def test_a_group_at_the_top_of_the_window_is_not_pushed_down_by_its_break(self):
        """Scrolled so a group starts the window: the top of the screen already says a
        new group starts here, and a blank first line would only cost a row."""
        rows = board.layout(self.tree(), top=1, height=board.CHROME + 4, width=60,
                            msg="")
        self.assertEqual(self.shape(rows), ["lead", "w1", "w2"])


class LayoutTest(unittest.TestCase):
    def test_a_click_resolves_to_the_agent_drawn_on_that_row(self):
        rows = board.layout(snap(agent("one"), agent("two", depth=1), agent("three")),
                            top=0, height=12, width=100, msg="")
        drawn = [(i + 1, a.name) for i, (_, a) in enumerate(rows) if a is not None]
        self.assertEqual([a.name for a in blocks(rows)], ["one", "two", "three"])
        for row, name in drawn:
            self.assertEqual(board.agent_at(rows, row).name, name)

    def test_a_click_off_the_agents_resolves_to_nobody(self):
        rows = board.layout(snap(agent("one")), top=0, height=12, width=100, msg="")
        self.assertIsNone(board.agent_at(rows, 1))          # the header
        self.assertIsNone(board.agent_at(rows, len(rows)))  # the help line
        self.assertIsNone(board.agent_at(rows, 0))          # rows are 1-based
        self.assertIsNone(board.agent_at(rows, 9999))

    def test_scrolling_moves_which_agent_a_row_means(self):
        agents = [agent(f"a{i}") for i in range(20)]
        first = board.layout(snap(*agents), top=0, height=10, width=100, msg="")
        later = board.layout(snap(*agents), top=3, height=10, width=100, msg="")
        self.assertEqual(board.agent_at(first, 3).name, "a0")
        self.assertEqual(board.agent_at(later, 3).name, "a3")

    def test_scrolling_past_the_end_stops_rather_than_emptying_the_view(self):
        agents = [agent(f"a{i}") for i in range(6)]
        rows = board.layout(snap(*agents), top=999, height=10, width=100, msg="")
        self.assertTrue([a for _, a in rows if a is not None])

    def test_no_line_may_wrap_because_a_wrapped_line_shifts_every_click_below_it(self):
        wide = agent("w", task="x" * 400)
        rows = board.layout(snap(wide), top=0, height=10, width=40, msg="m" * 200)
        for text, _ in rows:
            self.assertLessEqual(board._visible_len(text), 40)

    def test_a_wide_character_row_does_not_wrap_and_the_rows_below_it_still_map(self):
        """The defect this file was short of: `len()` said the row fit, the terminal
        disagreed, and every click below it landed one agent low. The task here is 30
        characters and 60 columns — inside an ASCII budget of 40, twice over it in a
        terminal — and the row after it is the one whose click has to survive."""
        rows = board.layout(snap(agent("cjk", task="日本語の説明" * 5), agent("below")),
                            top=0, height=10, width=40, msg="")
        for text, _ in rows:
            self.assertLessEqual(board._visible_len(text), 40)
        row = next(i + 1 for i, (_, a) in enumerate(rows) if a is not None
                   and not board._is_group(a) and a.name == "below")
        self.assertEqual(board.agent_at(rows, row).name, "below")

    def test_an_emoji_sequence_is_one_glyph_two_columns_wide(self):
        """Zero-width joiners, skin tone and a flag are all one glyph each — measuring
        their codepoints would over-count and truncate a row that fits."""
        self.assertEqual(board._visible_len("👩‍👩‍👧‍👦"), 2)
        self.assertEqual(board._visible_len("👨🏽‍💻"), 2)
        self.assertEqual(board._visible_len("🇯🇵"), 2)
        rows = board.layout(snap(agent("👩‍👩‍👧‍👦-team", task="🚀 " * 30), agent("plain")),
                            top=0, height=10, width=40, msg="")
        for text, _ in rows:
            self.assertLessEqual(board._visible_len(text), 40)

    def test_the_state_column_lines_up_under_a_wide_name(self):
        """Padding in characters leaves the columns ragged, which is the same
        mismeasurement seen before it becomes a wrap."""
        rows = board.layout(snap(agent("日本語", state="working"),
                                 agent("ascii", state="working")),
                            top=0, height=10, width=200, msg="")
        drawn = [t for t, a in rows if a is not None and "working" in t]
        self.assertEqual(*[board._visible_len(t[:t.index("working")]) for t in drawn])

    def test_the_screen_is_exactly_the_height_it_was_given(self):
        for height in (6, 10, 24, 50):
            rows = board.layout(snap(agent("one"), agent("two")), top=0, height=height,
                                width=80, msg="")
            self.assertEqual(len(rows), height)

    def test_an_empty_board_says_what_to_do_instead_of_nothing(self):
        rows = board.layout(snap(), top=0, height=10, width=80, msg="")
        self.assertIn("sb start", "".join(t for t, _ in rows))

    def test_the_header_counts_come_from_status_so_the_two_readouts_cannot_disagree(self):
        s = snap(agent("a", stalled=True), agent("b", gone=True, alive=False))
        rows = board.layout(s, top=0, height=10, width=200, msg="")
        self.assertIn(status.summary_line(s), board._ANSI.sub('', rows[0][0]))


class HeadlineTest(unittest.TestCase):
    """Alive is the number a person reads first, and at 60 columns it is the one that
    survives. The rest are ordered by how much they matter and dropped whole from the
    tail — a half-written `2 bloc` says nothing, and a dangling `·` says less."""

    def head(self, s, width):
        rows = board.layout(s, top=0, height=10, width=width, msg="")
        return board._ANSI.sub("", rows[0][0])

    def test_the_headline_is_alive_and_it_comes_first(self):
        s = snap(agent("a"), agent("b", stalled=True), agent("c", archived=True))
        head = self.head(s, 200)
        self.assertIn("2 alive", head)
        self.assertLess(head.index("alive"), head.index("agents"))
        self.assertIn(status.summary_line(s), head)

    def test_a_narrow_board_drops_whole_counts_from_the_least_important_end(self):
        s = snap(agent("a"), agent("b", stalled=True))
        head = self.head(s, 34)
        self.assertIn("2 alive", head)
        self.assertNotIn("agents", head)          # the total goes before the trouble does
        self.assertFalse(head.rstrip().endswith("·"))

    def test_the_headline_alone_is_never_dropped(self):
        head = self.head(snap(agent("a")), 20)
        self.assertIn("alive", head)


class RefreshTest(unittest.TestCase):
    """The one impure test in this file, and it earns the exception.

    Everything above is pure because the board's bugs are drawing bugs. This one is about
    where the rows come from, which used to be the store and is now a file one elected
    collector publishes. It used to prove that a two-second tick here wrote nothing —
    three boards older than a fix to the spawn grace once marked every agent spawned that
    night `failed` during their own startup. That guarantee did not weaken; it moved,
    with the connect, to `tests/test_readonly.py::CollectorTick`, and `tests/test_panel.py
    ::RendererImports` now makes it structural: this file cannot reach the store to write
    to it. What is left to check here is the renderer's half of the bargain — that it
    reads what was published, and that it says so when what it read is old.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = panel.Paths(Path(self.tmp.name) / "panel")
        self.sup = panel.Supervisor(self.paths)

    def _publish(self, **counters):
        meta = {"pid": 7, "started_at": 0.0, "polls": 3, "errors": 0,
                "collected_at": panel.now(), "wrote_at": panel.now(), "tick_ms": 9.0,
                "last_error": None, "last_error_at": None}
        meta.update(counters)
        snap = status.Snapshot(now=100, agents=[agent("w1", gone=True, alive=False)])
        panel.publish(self.paths, panel.envelope(snap.as_dict(), meta))

    def test_a_refresh_draws_what_the_collector_published(self):
        self._publish()
        with mock.patch.object(panel, "ensure_collector", lambda *a, **k: False):
            snap, note_text = board.refresh(self.sup)
        self.assertEqual(note_text, "")
        self.assertTrue(snap.agents[0].gone)          # the screen says it, exactly as before
        rows = board.layout(snap, top=0, height=10, width=120, msg="", note_text=note_text)
        self.assertEqual(board.agent_at(rows, 3).name, "w1")

    def test_an_old_snapshot_is_labelled_rather_than_drawn_as_now(self):
        """The failure a shared cache introduces, and the one thing the design asked to be
        loud: forty panes quietly agreeing on stale data."""
        self._publish(collected_at=panel.now() - 40)
        with mock.patch.object(panel, "ensure_collector", lambda *a, **k: False):
            snap, note_text = board.refresh(self.sup)
        self.assertIn("snapshot 40s old", note_text)
        rows = board.layout(snap, top=0, height=10, width=120, msg="", note_text=note_text)
        self.assertIn("snapshot 40s old", "".join(t for t, _ in rows))

    def test_a_refresh_says_a_panel_is_still_being_looked_at(self):
        """The collector's only reason to keep running, and so the only reason it cannot
        outlive the panels."""
        self._publish()
        with mock.patch.object(panel, "ensure_collector", lambda *a, **k: False):
            board.refresh(self.sup)
        self.assertLess(panel.demand_age(self.paths), 5)

    def test_a_refresh_with_nothing_published_yet_draws_a_screen_anyway(self):
        with mock.patch.object(panel, "ensure_collector", lambda *a, **k: False):
            snap, note_text = board.refresh(self.sup)
        self.assertEqual(snap.agents, [])
        self.assertIn("collector", note_text)
        self.assertEqual(len(board.layout(snap, top=0, height=12, width=80, msg="",
                                          note_text=note_text)), 12)


class CollapseLayoutTest(unittest.TestCase):
    """Collapse in the panel — and the mapping it could break.

    `layout` used to window `snap.agents` directly and `agent_at` used to be able to
    assume every carried object was an agent. Neither is true once a display row can
    stand for a whole subtree, and both failures are of the silent kind this file exists
    for: a click that focuses somebody, just not the row under the cursor.
    """

    def drawn(self, rows):
        return blocks(rows)

    def text(self, rows):
        return "\n".join(t for t, _ in rows)

    def body(self, rows):
        """The tree only. The hint line permanently contains the word "archived", so
        asserting over the whole screen would pass no matter what was drawn."""
        return "\n".join(t for t, a in rows if a is not None)

    def test_an_archived_subtree_is_one_row_and_its_agents_are_not_drawn(self):
        rows = board.layout(snap(agent("main"),
                                 agent("lead", depth=1, parent="main", archived=True),
                                 agent("w1", depth=2, parent="lead", archived=True)),
                            top=0, height=12, width=100, msg="")
        self.assertEqual([getattr(a, "name", "GROUP") for a in self.drawn(rows)],
                         ["main", "GROUP"])
        self.assertIn("+ 2 archived", self.text(rows))

    def test_a_click_on_a_collapsed_row_never_resolves_to_an_agent(self):
        """The misclick this whole file is about. `agent_at` hands back whatever the row
        carries, so a collapsed row that read as an agent would focus one — and which one
        depends on nothing the human can see."""
        rows = board.layout(snap(agent("main"),
                                 agent("a", depth=1, parent="main", archived=True),
                                 agent("b", depth=1, parent="main", archived=True)),
                            top=0, height=12, width=100, msg="")
        at = [(i + 1, a) for i, (_, a) in enumerate(rows) if a is not None]
        groups = [(r, a) for r, a in at if board._is_group(a)]
        self.assertEqual(len(groups), 1)
        row, got = groups[0]
        self.assertIs(board.agent_at(rows, row), got)
        self.assertIsInstance(got, status.Collapsed)
        self.assertFalse(hasattr(got, "name"))

    def test_a_live_agent_is_still_clickable_next_to_a_collapsed_group(self):
        rows = board.layout(snap(agent("main"),
                                 agent("live", depth=1, parent="main"),
                                 agent("dead", depth=1, parent="main", archived=True)),
                            top=0, height=12, width=100, msg="")
        named = [(i + 1, a.name) for i, (_, a) in enumerate(rows)
                 if a is not None and not board._is_group(a)]
        for row, name in named:
            self.assertEqual(board.agent_at(rows, row).name, name)

    def test_scrolling_is_an_offset_into_drawn_rows_not_into_agents(self):
        """`top` indexed `snap.agents` before, and the clamp was `len(agents) - capacity`.
        With 30 of 34 agents collapsed away there are 5 rows on screen, so a `top` of 4
        is already past the end — but in agent-space it clamps to 31 and the window fills
        with archived rows that collapse says must not be drawn at all.
        """
        agents = [agent("main")]
        agents += [agent(f"live{i}", depth=1, parent="main") for i in range(3)]
        agents += [agent("dead", depth=1, parent="main", archived=True)]
        agents += [agent(f"d{i}", depth=2, parent="dead", archived=True) for i in range(29)]
        height = board.CHROME + 6                       # capacity 3 rows, 5 to show

        rows = board.layout(snap(*agents), top=0, height=height, width=100, msg="")
        self.assertEqual([getattr(a, "name", "GROUP") for a in self.drawn(rows)],
                         ["main", "live0", "live1"])
        rows = board.layout(snap(*agents), top=9999, height=height, width=100, msg="")
        self.assertEqual([getattr(a, "name", "GROUP") for a in self.drawn(rows)],
                         ["live1", "live2", "GROUP"])
        # Nothing hidden by collapse can be reached by scrolling to it.
        for top in range(0, 40):
            got = self.drawn(board.layout(snap(*agents), top=top, height=height,
                                          width=100, msg=""))
            self.assertFalse([a for a in got if not board._is_group(a) and a.archived])

    def test_the_more_below_count_counts_rows_on_screen_not_agents(self):
        """A footer that contradicts the screen is worse than no footer: the human
        scrolls looking for thirty rows that were never going to be drawn."""
        agents = [agent(f"live{i}") for i in range(6)]
        agents += [agent("dead", archived=True)]
        agents += [agent(f"d{i}", depth=1, parent="dead", archived=True) for i in range(40)]
        # capacity = height - CHROME, in LINES; small enough that something is below.
        height = board.CHROME + 6
        rows = board.layout(snap(*agents), top=0, height=height, width=100, msg="")
        self.assertEqual(len(self.drawn(rows)), 3)
        self.assertIn("+4 more below", self.text(rows))      # 7 drawn rows, 3 shown

    def test_a_fleet_that_has_entirely_finished_still_draws(self):
        """Every root archived, so the window is one collapsed row and there is no agent
        left to size a column against. This is the ORDINARY end-of-session state, and
        `max()` over an empty sequence raises."""
        rows = board.layout(snap(agent("a", archived=True), agent("b", archived=True)),
                            top=0, height=12, width=100, msg="")
        self.assertIn("+ 2 archived", self.text(rows))
        self.assertEqual(len(rows), 12)

    def test_show_archived_draws_every_agent_again(self):
        s = snap(agent("main"), agent("gone", depth=1, parent="main", archived=True))
        rows = board.layout(s, top=0, height=12, width=100, msg="", show_archived=True)
        self.assertEqual([a.name for a in self.drawn(rows)], ["main", "gone"])
        self.assertNotIn("archived", self.body(rows))

    def test_a_herdr_outage_draws_the_whole_fleet_rather_than_one_row(self):
        """`alive is None`, so nothing is archived however old the rows are. A panel that
        collapsed the fleet on a subprocess hiccup would be worse than no panel."""
        unknown = [agent(f"a{i}", alive=None, herdr_state=None) for i in range(4)]
        for a in unknown:
            a.age = int(status.SPAWN_GRACE) + 1
        rows = board.layout(snap(*unknown), top=0, height=12, width=100, msg="")
        self.assertEqual([a.name for a in self.drawn(rows)], ["a0", "a1", "a2", "a3"])
        self.assertNotIn("archived", self.body(rows))

    def test_the_panel_and_sb_status_share_one_default(self):
        """Two renderings of one snapshot. If the panel kept its own default they could
        disagree about the same fleet on the same screen, and `display.show_archived`
        would be a setting that only half the product obeyed."""
        s = snap(agent("main"), agent("gone", depth=1, parent="main", archived=True))
        rows = board.layout(s, top=0, height=12, width=100, msg="")
        self.assertEqual([getattr(a, "name", "GROUP") for a in self.drawn(rows)],
                         ["main", "GROUP"])
        with mock.patch.object(status, "SHOW_ARCHIVED", True):
            rows = board.layout(s, top=0, height=12, width=100, msg="")
            self.assertEqual([a.name for a in self.drawn(rows)], ["main", "gone"])

    def test_the_header_still_counts_every_agent_a_collapse_hid(self):
        """Collapse shortens the tree, not the readout. Three agents, two rows — so a
        header that had quietly started counting rows would read "2 agents" here."""
        s = snap(agent("main"),
                 agent("d1", depth=1, parent="main", archived=True),
                 agent("d2", depth=1, parent="main", archived=True))
        rows = board.layout(s, top=0, height=12, width=200, msg="")
        self.assertEqual(len(self.drawn(rows)), 2)
        self.assertIn("3 agents", rows[0][0])
        self.assertIn(status.summary_line(s), board._ANSI.sub('', rows[0][0]))


if __name__ == "__main__":
    unittest.main()
