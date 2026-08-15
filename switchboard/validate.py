"""Argument validation — the boundary between what a caller typed and what herdr gets.

Everything here is a pure function of its input: no store, no herdr, no state at all. That
is deliberate — validation must be cheap enough to run on every argument before anything is
spawned or written, and testable without a database. The one import is config.py, which
reads files and nothing else: the caps below are tunable per repo, and a cap written as a
literal here is a cap nobody can adjust without a patch.

Two rules do most of the work, and both come from herdr:

  * an agent name must match ``[a-z][a-z0-9_-]{0,31}``;
  * **no agent argument may contain a newline**. herdr answers
    ``invalid_agent_argument`` ("agent arguments cannot be encoded safely for the target
    shell") and refuses. This covers the ``--append-system-prompt`` lines AND the task
    text handed to ``agent prompt``.

One rule is ours rather than herdr's, and it is in `reason`: a `sb block` reason is capped
short, because the human never reads that field and a long one is an answer the agent has
sent nowhere. See that docstring — it is the one place here enforcing a shape.

Left to herdr, both surface as an error that names neither the flag the human typed nor
the fix — and in the ``ask`` case as a wedged shell that blocks for the full timeout.
Shell injection is NOT the concern: every subprocess call is an argument list and
``shell=True`` appears nowhere. The concern is invalid input reaching herdr.

Validators return the *normalised* value (stripped) so the caller can use what came back
rather than the raw argument, and raise `Invalid` — a ValueError, so the CLI's existing
handling of it is already correct.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from . import config

# Every cap here is `[limits]` in defaults/settings.toml. No fallback value is repeated
# here: a spare copy in Python is a second place to update, which is the thing moving
# configuration into files was meant to end. Read the file for what each cap is FOR — the
# reasoning lives next to the number.
MAX_AGENT_NAME = config.setting("limits.agent_name")
MAX_TEXT = config.setting("limits.text")
MAX_BLOCK_REASON = config.setting("limits.block_reason")
MAX_PROMPT = config.setting("limits.prompt")
MAX_REF = config.setting("limits.ref")
MAX_TOKEN = config.setting("limits.token")

# herdr's rule, verbatim: one leading letter plus up to MAX_AGENT_NAME - 1 more. The shape
# is herdr's and not negotiable; only the length is read from config, and only so that the
# rule and the number it is checked against cannot drift apart.
AGENT_NAME = re.compile(r"[a-z][a-z0-9_-]{0,%d}\Z" % (MAX_AGENT_NAME - 1))

# Addresses, not agents. Both happen to satisfy AGENT_NAME, but naming them here means a
# rename of either cannot silently start failing validation.
RESERVED_TARGETS = (config.setting("vocabulary.parent"),
                    config.setting("vocabulary.human"))

# Named in the error you get for a multi-line prompt, because that error's whole job is to
# say where multi-line guidance DOES belong. Assembled from `[paths]` so it cannot become
# a lie the day someone moves the directory.
PRESET_DIR_HINT = "{}/{}/".format(config.setting("paths.repo_dir"),
                                  config.setting("paths.presets_dir"))

# C0 control characters, minus the whitespace we tolerate (\t \n \r). These arrive from
# copy-paste and terminal escape sequences; they corrupt any pane they are echoed into.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_NOT_IN_NAME = re.compile(r"[^a-z0-9_-]+")

# git check-ref-format, the parts expressible as a character class: no control chars, no
# space, and none of ~ ^ : ? * [ \
_BAD_IN_REF = re.compile(r"[\x00-\x20~^:?*\[\\\x7f]")


class Invalid(ValueError):
    """A caller's argument is unusable. The message is written for the person who typed
    it: what is wrong, and what to do instead."""


# -- text ----------------------------------------------------------------


def text(value: Optional[str], field: str, *, max_len: int = MAX_TEXT) -> str:
    """Free text that stays inside switchboard — a message body, a question.

    Newlines are allowed here: these are stored and read back through `sb inbox`, and
    only ever reach herdr truncated to a notification. Emptiness is not: an empty message
    rings someone's doorbell for nothing, which costs them a turn (C0).
    """
    v = _require_str(value, field).strip()
    if not v:
        raise Invalid(f"{field} is empty — say something, or omit it")
    if _CONTROL.search(v):
        raise Invalid(f"{field} contains control characters; send plain text")
    if len(v) > max_len:
        raise Invalid(
            f"{field} is {len(v)} characters, over the {max_len} limit. Write it to a "
            f"file and send the path — switchboard passes paths, never contents."
        )
    return v


def line(value: Optional[str], field: str, *, max_len: int = MAX_TEXT) -> str:
    """Text that will become a herdr argument, so it must be one line.

    A task, a prompt, a summary, an interrupt. All of these end up either in
    `agent prompt` or in `--append-system-prompt`/`--message`, and herdr rejects a newline
    in any of them outright.
    """
    v = text(value, field, max_len=max_len)
    if "\n" in v or "\r" in v:
        raise Invalid(
            f"{field} must be a single line: herdr refuses any agent argument containing "
            f"a newline (invalid_agent_argument), so this would fail at spawn. Put "
            f"multi-line guidance in a file and pass the path, or in a "
            f"{PRESET_DIR_HINT}<name>.md preset."
        )
    return v


def reason(value: Optional[str], field: str = "reason") -> str:
    """`sb block "<why>"` — a one-line note on a board row, not a message to the human.

    The only validator here that is enforcing a SHAPE rather than a constraint somebody
    else imposes, and the reason it has to be mechanical is C6: the right shape was
    written down in the protocol and an orchestrator still put its whole answer here.
    The human reads a blocked agent's own chat, with `sb inspect`; this field reaches him
    as at most a clipped row on the board. So a `why` big enough to be the answer is not
    a long reason, it is an answer that has been sent nowhere — and the agent cannot tell,
    because `block` succeeded.

    Both refusals therefore say the same thing and name the same fix, including the one
    that used to blame herdr. herdr's newline rule is real (the reason travels on to
    `report-agent --message`) but it is the wrong thing to tell the caller: an agent that
    hears "herdr refuses newlines" learns that its text is fine and its formatting is not,
    flattens six paragraphs into one line, and gets through — which is exactly what
    happened, and it filed a bug against the refusal afterwards. The cap is what closes
    that door, so the two checks are one message with one fix in it.

    What the refusal does NOT do is say what the chat message should contain. It used to
    name the parts ("the findings, the options, the numbered questions") and close with a
    specimen block call, and it is read at exactly the moment the agent is composing for a
    human — so it anchored harder than any prompt text could. DESIGN-TRUTH 2026-08-14:
    nothing may be turned into something to copy. It names the field's job, the mistake,
    and where the message goes; shape is the protocol's business, not an error string's.
    """
    v = _require_str(value, field).strip()
    if not v:
        raise Invalid(f"{field} is empty — say in one line what you need")
    if _CONTROL.search(v):
        raise Invalid(f"{field} contains control characters; send plain text")
    if "\n" in v or "\r" in v or len(v) > MAX_BLOCK_REASON:
        problem = (f"is {len(v)} characters, over the {MAX_BLOCK_REASON} a block reason "
                   f"may carry" if len(v) > MAX_BLOCK_REASON else "must be a single line")
        raise Invalid(
            f"{field} {problem}. It is bookkeeping on a board row, NOT the message the "
            f"human reads — they read your own chat, and nothing you put here. So do not "
            f"shorten or flatten your message to fit: leave it whole, as the last thing "
            f"in your chat, where they will read it, and keep this field to one line "
            f"naming what you are waiting for."
        )
    return v


def token(value: Optional[str], field: str, *, max_len: int = MAX_TOKEN) -> str:
    """A single identifier-ish word — a model name, a tier."""
    v = line(value, field, max_len=max_len)
    if re.search(r"\s", v):
        raise Invalid(f"{field} must be one word, got {v!r}")
    return v


# -- names ---------------------------------------------------------------


def agent_name(value: Optional[str], field: str = "agent name") -> str:
    """An explicit agent name, checked against herdr's rule rather than herdr's error.

    Rejecting `QA` here costs a typo; letting it through costs a failed spawn whose
    message mentions neither the name nor the rule.
    """
    v = _require_str(value, field).strip()
    if not v:
        raise Invalid(f"{field} is empty")
    if not AGENT_NAME.fullmatch(v):
        why = (f"it is {len(v)} characters, over the {MAX_AGENT_NAME} herdr allows"
               if len(v) > MAX_AGENT_NAME else
               "it must start with a lowercase letter and contain only lowercase "
               "letters, digits, '_' and '-'")
        raise Invalid(
            f"bad {field} {v!r}: {why} (herdr requires [a-z][a-z0-9_-]{{0,31}}). "
            f"Try {slug_name(v)!r}."
        )
    return v


def slug_name(value: str, *, reserve: int = 0) -> str:
    """Force any string into a legal agent name.

    Names are derived from things people choose freely — a role, a branch, a workspace —
    so `--role "QA Bot"` would otherwise produce the agent name `QA Bot-1` and fail at
    spawn. `reserve` holds back room for a suffix the caller will append (`-1`, `-99`),
    because truncating AFTER appending is how a name loses the part that made it unique.
    """
    limit = max(1, MAX_AGENT_NAME - max(0, reserve))
    s = _NOT_IN_NAME.sub("-", (value or "").strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-_")
    if not s or not ("a" <= s[0] <= "z"):
        s = "w-" + s            # a name must start with a letter; keep the rest visible
    return s[:limit].strip("-_") or "w"


def ref_name(value: Optional[str], field: str = "workspace name") -> str:
    """A workspace name, which IS the git branch name — no prefix, no escaping.

    So git's rules are the rules (`git check-ref-format`). Caught here they name the
    offending character; caught by git they arrive as "fatal: invalid reference" from
    inside a herdr call three layers down.
    """
    v = _require_str(value, field).strip()
    if not v:
        raise Invalid(f"{field} is empty")
    if len(v) > MAX_REF:
        raise Invalid(f"{field} is {len(v)} characters, over the {MAX_REF} limit")
    bad = _BAD_IN_REF.search(v)
    problem = None
    if bad:
        problem = ("whitespace and control characters are not allowed"
                   if bad.group() <= " " else f"{bad.group()!r} is not allowed")
    elif ".." in v or "//" in v or "@{" in v:
        problem = "'..', '//' and '@{' are not allowed"
    elif v.startswith(("-", "/", ".")):
        problem = "it may not start with '-', '/' or '.'"
    elif v.endswith(("/", ".", ".lock")):
        problem = "it may not end with '/', '.' or '.lock'"
    elif v == "@":
        problem = "'@' on its own is not a branch name"
    if problem:
        raise Invalid(
            f"bad {field} {v!r}: it is used verbatim as the git branch name, and "
            f"{problem}. Try {slug_name(v)!r}."
        )
    return v


def target(value: Optional[str], field: str = "recipient") -> str:
    """Who a message is for: an agent name, `parent`, or `human`.

    Shape only — whether the agent exists is the broker's business, and it already fails
    fast on an unknown one rather than blocking for the whole timeout.

    `human` is a legal shape and NOT a legal recipient: a person has no mailbox, so the
    broker refuses it with a sentence naming `sb block`. Rejecting it here instead would
    answer "who do I tell?" with a shape complaint, which teaches nobody the one way in.
    """
    v = _require_str(value, field).strip()
    if v in RESERVED_TARGETS:
        return v
    return agent_name(v, field)


def targets(values: Iterable[str], field: str = "recipient") -> list[str]:
    out = [target(v, field) for v in values]
    if not out:
        raise Invalid(f"no {field} given")
    return out


# -- numbers -------------------------------------------------------------


def positive_int(value, field: str, *, max_value: Optional[int] = None) -> int:
    """A count or a timeout. `--timeout 0` is a fifteen-minute-looking call that returns
    nothing; a negative one is the same bug wearing a different sign."""
    n = int(value)
    if n < 1:
        raise Invalid(f"{field} must be at least 1, got {n}")
    if max_value is not None and n > max_value:
        raise Invalid(f"{field} must be at most {max_value}, got {n}")
    return n


# -- internals -----------------------------------------------------------


def _require_str(value: Optional[str], field: str) -> str:
    if value is None:
        raise Invalid(f"{field} is required")
    if not isinstance(value, str):
        raise Invalid(f"{field} must be text, got {type(value).__name__}")
    return value
