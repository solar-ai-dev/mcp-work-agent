"""GITHUB-1 skeleton must stay unreachable from production composition.

`build_connectors()` spawns a real subprocess and touches the OS keyring, so
these guards check the composition root's source directly instead of
invoking it -- that keeps the isolation contract locked without paying for a
full app boot in a focused test run.
"""

from __future__ import annotations

import inspect

from google_work_agent.launcher.connector_composition import build_connectors


def test_build_connectors_source_does_not_reference_github() -> None:
    source = inspect.getsource(build_connectors).lower()

    assert "github" not in source


def test_build_connectors_only_registers_google_workspace() -> None:
    source = inspect.getsource(build_connectors)

    assert source.count("registry.register(") == 1
    assert source.count("tool_catalog.register(") == 1
    assert "google_connector" in source
