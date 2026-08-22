"""The `# setup:` annotation lint.

`sb setup` does not carry a hardcoded list of what it may offer a repo. It discovers that
list by reading `# setup: {...}` comment lines in `defaults/*.toml`: the tag IS the
allowlist. That makes the tags load-bearing prose — a typo in one is a setting silently
dropped from the interview, or an interview question about a key that does not exist.

So two different things are tested here and they are not the same thing:

  1. the GRAMMAR, against in-file fixtures — this is the part that stays meaningful when
     there are zero real tags, and it is what actually pins the rules down;
  2. every REAL tag currently shipped in `defaults/*.toml`, checked against the same
     parser and against the value it claims to describe.

What is deliberately NOT asserted: that any particular key IS tagged. Which settings are
worth offering a human is an editorial call made by whoever writes the tag, not a rule a
test gets to enforce.
"""

from __future__ import annotations

import re
import sys
import tomllib
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import config  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIPPED = REPO / "defaults"

# One tag is one whole comment line. Anything else on the line means it is not a tag.
_TAG = re.compile(r"^\s*#\s*setup:\s*(\{.*\})\s*$")
# The `[section]` a following bare key belongs to. Not `[[array of tables]]`.
_SECTION = re.compile(r"^\s*\[([^\[\]]+)\]\s*$")
# `key = value`, bare or quoted, possibly dotted.
_ASSIGN = re.compile(r"""^\s*((?:[A-Za-z0-9_\-]+|"[^"]*"|'[^']*')(?:\s*\.\s*(?:[A-Za-z0-9_\-]+|"[^"]*"|'[^']*'))*)\s*=""")

TYPES = {"string": str, "list": list, "bool": bool, "enum": str}


class TagError(ValueError):
    """A `# setup:` tag switchboard cannot use. The message names file and line."""


@dataclass(frozen=True)
class Tag:
    key: str          # dotted target, positional or explicit
    payload: dict
    line: int         # 1-based line of the tag itself
    where: str        # file name, for messages

    def __str__(self) -> str:
        return f"{self.where}:{self.line} ({self.key})"


# -- the parser + validator under test -----------------------------------------
#
# Kept in the test module on purpose. Nothing in switchboard reads tags at runtime —
# the skill does, by hand, at setup time — so there is no production implementation to
# import, and inventing one only to test it would be inventing the thing under test.


def parse(text: str, where: str = "<fixture>") -> list[Tag]:
    """Every `# setup:` tag in one TOML document, with its target resolved.

    Raises TagError on anything that is a tag by its comment line but cannot be read as
    one: bad TOML payload, a payload that is not a table, or a tag that does not sit
    immediately above a key.
    """
    lines = text.splitlines()
    out: list[Tag] = []
    section = ""
    for i, line in enumerate(lines):
        head = _SECTION.match(line)
        if head:
            section = head.group(1).strip()
            continue
        m = _TAG.match(line)
        if not m:
            continue
        at = f"{where}:{i + 1}"
        try:
            payload = tomllib.loads("v = " + m.group(1))["v"]
        except tomllib.TOMLDecodeError as e:
            raise TagError(f"{at}: payload is not a TOML inline table: {e}") from e
        if not isinstance(payload, dict):
            raise TagError(f"{at}: payload is not a table")
        out.append(Tag(_target(lines, i, section, at, payload), payload, i + 1, where))
    return out


def _target(lines: list[str], i: int, section: str, at: str, payload: dict) -> str:
    """The dotted key a tag points at: explicit `key` field, else the next key below it."""
    explicit = payload.get("key")
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit.strip():
            raise TagError(f"{at}: 'key' must be a non-empty string")
        return explicit.strip()
    for line in lines[i + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            raise TagError(
                f"{at}: a tag must sit immediately above the key it targets — "
                f"found a blank or comment line instead"
            )
        assign = _ASSIGN.match(line)
        if not assign:
            raise TagError(f"{at}: the line below a tag is not a `key = value`: {line.strip()!r}")
        key = ".".join(p.strip().strip("\"'") for p in assign.group(1).split("."))
        return f"{section}.{key}" if section else key
    raise TagError(f"{at}: tag is the last line of the file, with no key below it")


def validate(tag: Tag, doc: dict) -> None:
    """One tag against the document it lives in. Raises TagError on the first fault."""
    p = tag.payload
    known = {"type", "hint", "choices", "when", "key"}
    unknown = sorted(set(p) - known)
    if unknown:
        raise TagError(f"{tag}: unknown field(s) {unknown}")

    kind = p.get("type")
    if kind is None:
        raise TagError(f"{tag}: no 'type'")
    if kind not in TYPES:
        raise TagError(f"{tag}: unknown type {kind!r} — one of {sorted(TYPES)}")

    hint = p.get("hint")
    if not isinstance(hint, str) or not hint.strip():
        raise TagError(f"{tag}: 'hint' must be a non-empty string")

    when = p.get("when")
    if when is not None and (not isinstance(when, str) or not when.strip()):
        raise TagError(f"{tag}: 'when' must be a non-empty string when present")

    choices = p.get("choices")
    if kind == "enum":
        if not isinstance(choices, list) or not choices:
            raise TagError(f"{tag}: type='enum' needs a non-empty 'choices' array")
    elif choices is not None:
        raise TagError(f"{tag}: 'choices' is only for type='enum'")

    value = _lookup(doc, tag.key)
    if value is _MISSING:
        raise TagError(f"{tag}: no key '{tag.key}' in {tag.where}")
    want = TYPES[kind]
    # bool is an int in Python but never the other way round; TOML keeps them apart anyway.
    if not isinstance(value, want) or (want is not bool and isinstance(value, bool)):
        raise TagError(
            f"{tag}: type={kind!r} but the shipped value is {type(value).__name__}"
        )
    if kind == "enum" and value not in choices:
        raise TagError(f"{tag}: value {value!r} is not one of {choices}")


_MISSING = object()


def _lookup(doc: dict, dotted: str):
    node = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def check(text: str) -> list[Tag]:
    """Parse + validate one document, the way the lint below runs over a real file."""
    doc = tomllib.loads(text)
    found = parse(text)
    for tag in found:
        validate(tag, doc)
    return found


# -- 1. the grammar, on fixtures -----------------------------------------------


GOOD = """
[editor]
# the CLI your editor opens folders with
# setup: { type = "string", hint = "your editor's CLI" }
command = "cursor"

[sweep]
# setup: { type = "list", hint = "extra docs dirs", when = "only if the repo has any" }
docs_dirs = ["docs"]

[display]
# setup: { type = "bool", hint = "show archived agents?" }
show_archived = false
# setup: { type = "enum", hint = "how wide?", choices = ["narrow", "wide"] }
width = "wide"
"""


class GrammarTest(unittest.TestCase):
    """The rules, stated as fixtures. Meaningful with zero real tags in the tree."""

    def test_a_well_formed_document_yields_its_tags_with_targets_resolved(self):
        got = {t.key: t.payload["type"] for t in check(GOOD)}
        self.assertEqual(
            got,
            {
                "editor.command": "string",
                "sweep.docs_dirs": "list",
                "display.show_archived": "bool",
                "display.width": "enum",
            },
        )

    def test_an_explicit_key_field_overrides_the_positional_target(self):
        text = '[a]\n# setup: { type = "bool", hint = "h", key = "b.flag" }\nx = 1\n\n[b]\nflag = true\n'
        self.assertEqual([t.key for t in check(text)], ["b.flag"])

    def test_a_comment_that_is_not_a_whole_tag_line_is_not_a_tag(self):
        text = '[a]\nx = 1  # setup: { type = "bool", hint = "h" }\n'
        self.assertEqual(check(text), [])

    def _rejects(self, text: str, because: str):
        with self.assertRaises(TagError) as caught:
            check(text)
        self.assertIn(because, str(caught.exception))

    def test_malformed_payload_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "string" hint = "h" }\nx = "v"\n', "not a TOML inline table")

    def test_missing_type_is_rejected(self):
        self._rejects('[a]\n# setup: { hint = "h" }\nx = "v"\n', "no 'type'")

    def test_missing_hint_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "string" }\nx = "v"\n', "'hint' must be a non-empty string")

    def test_an_empty_hint_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "string", hint = "  " }\nx = "v"\n', "'hint' must be a non-empty string")

    def test_an_enum_without_choices_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "enum", hint = "h" }\nx = "v"\n', "needs a non-empty 'choices'")

    def test_choices_without_an_enum_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "string", hint = "h", choices = ["v"] }\nx = "v"\n', "only for type='enum'")

    def test_an_unknown_type_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "toggle", hint = "h" }\nx = true\n', "unknown type 'toggle'")

    def test_a_type_that_does_not_match_the_shipped_value_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "list", hint = "h" }\nx = "v"\n', "the shipped value is str")

    def test_a_bool_tag_on_a_string_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "bool", hint = "h" }\nx = "yes"\n', "the shipped value is str")

    def test_a_string_tag_on_a_bool_is_rejected(self):
        """bool is an int in Python — the check must not wave this through either way."""
        self._rejects('[a]\n# setup: { type = "string", hint = "h" }\nx = true\n', "the shipped value is bool")

    def test_an_enum_whose_value_is_not_among_its_choices_is_rejected(self):
        self._rejects(
            '[a]\n# setup: { type = "enum", hint = "h", choices = ["p", "q"] }\nx = "r"\n',
            "is not one of",
        )

    def test_a_when_that_is_not_a_non_empty_string_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "string", hint = "h", when = "" }\nx = "v"\n', "'when' must be")

    def test_an_unknown_field_is_rejected(self):
        """Absence means not offered; a misspelt field would mean silently not asked."""
        self._rejects('[a]\n# setup: { type = "string", hint = "h", hnit = "x" }\nx = "v"\n', "unknown field")

    def test_a_tag_pointing_at_a_key_that_does_not_exist_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "bool", hint = "h", key = "nope.gone" }\nx = 1\n', "no key 'nope.gone'")

    def test_a_tag_separated_from_its_key_by_a_blank_line_is_rejected(self):
        self._rejects('[a]\n# setup: { type = "string", hint = "h" }\n\nx = "v"\n', "immediately above")

    def test_a_tag_that_is_not_above_a_key_at_all_is_rejected(self):
        self._rejects('[a]\nx = "v"\n# setup: { type = "string", hint = "h" }\n[b]\ny = 1\n', "not a `key = value`")


# -- 2. the tags actually shipped ----------------------------------------------


def _shipped_files() -> list[Path]:
    return sorted(SHIPPED.glob("*.toml"))


class ShippedTagTest(unittest.TestCase):
    """Every real `# setup:` in `defaults/*.toml`, through the same parser.

    Passes on an empty set — no tag is a valid state of the tree, and how many there
    should be is not this test's business.
    """

    def test_defaults_dir_is_where_it_is_expected(self):
        self.assertTrue(_shipped_files(), f"no shipped TOML found under {SHIPPED}")

    def test_every_shipped_tag_parses_and_describes_the_value_it_sits_on(self):
        for path in _shipped_files():
            text = path.read_text()
            doc = tomllib.loads(text)
            with self.subTest(file=path.name):
                for tag in parse(text, path.name):
                    validate(tag, doc)

    def test_shipped_tags_resolve_through_the_config_layer_too(self):
        """A tag's target has to be reachable by the same dotted lookup `sb` uses."""
        for path in _shipped_files():
            if path.name != "settings.toml":
                continue  # only settings.toml is behind config.setting()
            for tag in parse(path.read_text(), path.name):
                with self.subTest(tag=str(tag)):
                    self.assertIsNot(
                        config.setting(tag.key, default=_MISSING, repo=None), _MISSING
                    )


if __name__ == "__main__":
    unittest.main()
