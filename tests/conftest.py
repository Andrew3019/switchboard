"""Session-wide test isolation that must apply no matter which file a test lives in."""

from __future__ import annotations

import os
import tempfile

import pytest

from switchboard import usage


@pytest.fixture(autouse=True)
def _isolate_usage_sink():
    """Redirect the cross-repo usage sink to a throwaway dir for every test.

    `cli.main()` appends one usage record per invocation, and many tests across the suite
    (and the subprocesses some of them spawn) call it. Without this, an ordinary `pytest tests`
    run writes real rows — carrying tmp-repo paths — into the developer's or CI box's actual
    `~/.local/state/switchboard/usage/`, permanently contaminating the very analytics this
    feature exists to produce. Setting the env var (rather than monkeypatching) also isolates
    the sink for `sb` subprocesses a test spawns, which inherit the environment.

    Autouse fixtures run for `unittest.TestCase` tests too, so this covers the whole suite.
    """
    previous = os.environ.get(usage.USAGE_DIR_ENV)
    with tempfile.TemporaryDirectory(prefix="sb-usage-test-") as sink:
        os.environ[usage.USAGE_DIR_ENV] = sink
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(usage.USAGE_DIR_ENV, None)
            else:
                os.environ[usage.USAGE_DIR_ENV] = previous
