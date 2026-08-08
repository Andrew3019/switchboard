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

from switchboard import board, status, store  # noqa: E402
from switchboard import herdr as herdr_mod  # noqa: E402


def agent(name, *, depth=0, state="working", herdr_state="working", alive=True,
          stalled=False, gone=False, unread=0, task=None, blocked_why=None,
          summary=None, parent=None):
    return status.AgentStatus(
        name=name, role="worker", parent=parent, depth=depth, state=state,
        herdr_state=herdr_state, alive=alive, stalled=stalled, gone=gone, unread=unread,
        age=10, idle=5, last_activity=0, workspace="api", task=task,
        blocked_why=blocked_why, summary=summary,
    )


def snap(*agents):
    return status.Snapshot(now=0, agents=list(agents))


class ParseSgrTest(unittest.TestCase):
    def test_a_click_decodes_to_button_column_and_row(self):
        events, rest = board.parse_sgr("\033[<0;12;7M")
        self.assertEqual(rest, "")
        self.assertEqual([e["button"] for e in events], [0])
        self.assertEqual((events[0]["col"], events[0]["row"]), (12, 7))
        self.assertTrue(board.is_left_click(events[0]))

    def test_a_release_is_not_a_click(self):
        [ev], _ = board.parse_sgr("\033[<0;12;7m")
        self.assertFalse(board.is_left_click(ev))

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
        self.assertEqual(board.note(a), "GONE — herdr has no such agent")

    def test_every_glyph_has_a_colour_and_they_are_all_distinct(self):
        kinds = [agent("a", gone=True), agent("b", state="blocked"),
                 agent("c", stalled=True), agent("d", state="done"),
                 agent("e", alive=None), agent("f")]
        glyphs = [board.glyph(a) for a in kinds]
        self.assertEqual(len(set(glyphs)), len(glyphs))
        for g in glyphs:
            self.assertIn(g, board._GLYPH_COLOR)

    def test_a_stalled_agent_wants_you_even_though_it_does_not_know_it(self):
        self.assertTrue(board.wants_you(agent("w", stalled=True)))
        self.assertTrue(board.wants_you(agent("w", gone=True)))
        self.assertFalse(board.wants_you(agent("w")))

    def test_only_one_note_is_ever_shown_and_it_is_the_most_actionable(self):
        a = agent("w", state="blocked", blocked_why="need a key", unread=2,
                  task="do the thing")
        self.assertEqual(board.note(a), "BLOCKED — need a key")


class LayoutTest(unittest.TestCase):
    def test_a_click_resolves_to_the_agent_drawn_on_that_row(self):
        rows = board.layout(snap(agent("one"), agent("two", depth=1), agent("three")),
                            top=0, height=12, width=100, msg="")
        drawn = [(i + 1, a.name) for i, (_, a) in enumerate(rows) if a is not None]
        self.assertEqual([n for _, n in drawn], ["one", "two", "three"])
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
        self.assertIn(status.summary_line(s), rows[0][0])


class SnapshotIsReadOnlyTest(unittest.TestCase):
    """The one impure test in this file, and it earns the exception.

    Everything above is pure because the board's bugs are drawing bugs. This one is not
    about drawing: a board refreshes every two seconds for as long as a human leaves it
    open, on the `status.py` that Python imported at startup, and `collect` writes. Three
    boards older than a fix to the spawn grace once marked every agent spawned that night
    `failed` during its own startup. Nothing else in the suite can catch that, because
    every other caller of `collect` is a process that lives for one command.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state.db"
        db = store.connect(path=self.path)
        # Absent from herdr, past its spawn: the row a reaping readout would end.
        store.create_agent(db, name="w1", role="worker", session_id="s1")
        db.close()

    def test_a_refresh_shows_the_drift_and_writes_none_of_it(self):
        class NoAgents:
            def list_agents(self): return []

        connect = store.connect                       # before the patch shadows it
        with mock.patch.object(store, "connect", lambda: connect(path=self.path)), \
             mock.patch.object(herdr_mod, "Herdr", NoAgents):
            s, note = board.snapshot()

        self.assertEqual(note, "")
        self.assertTrue(s.agents[0].gone)             # the screen says it, exactly as before

        db = store.connect(path=self.path)
        self.addCleanup(db.close)
        row = store.get_agent(db, "w1")
        self.assertEqual(row["state"], "working")     # ...and the store is untouched
        self.assertIsNone(row["ended_at"])
        self.assertEqual(store.recent_events(db, agent="w1"), [])


if __name__ == "__main__":
    unittest.main()
