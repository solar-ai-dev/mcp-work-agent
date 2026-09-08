from __future__ import annotations

import json
from pathlib import Path

import pytest

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)


def test_signed_registry__loads_exact__installed_connector_tool_set() -> None:
    registry = load_signed_tool_registry()

    assert len(registry.entries) == 28
    assert {entry.connector_id for entry in registry.entries} == {
        "github",
        "google_workspace",
    }
    assert registry.entries_hash == (
        "44399339803dd17f8a0c3e930225e2ac333219b15d679ecc8ca1b99e88545679"
    )

    github = [entry for entry in registry.entries if entry.connector_id == "github"]
    assert {entry.tool_id for entry in github} == {
        "github_list_issues",
        "github_get_issue",
        "github_create_issue",
        "github_update_issue",
        "github_close_issue",
        "github_reopen_issue",
    }
    assert {entry.resource_type for entry in github} == {"github_issue"}
    assert all(
        entry.retry_class == ("READ_BOUNDED" if entry.effect == "READ" else "WRITE_NO_AUTO_RETRY")
        for entry in github
    )


def test_signed_registry__binds_effect__and_entry_hash() -> None:
    registry = load_signed_tool_registry()

    binding = registry.bind_required("google_workspace", "gmail_send", "SEND")

    assert binding.tool_id == "gmail_send"
    assert binding.effect == "SEND"
    assert len(binding.registry_entry_hash) == 64
    with pytest.raises(ValueError, match="effect mismatch"):
        registry.bind_required("google_workspace", "gmail_send", "READ")


def test_signed_registry__loader_rejects__manifest_drift(tmp_path: Path) -> None:
    source = load_signed_tool_registry.__globals__["_IMPLEMENTATION_MANIFEST"]
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="fields mismatch"):
        load_signed_tool_registry(path)
    with pytest.raises(ValueError, match="release hash mismatch"):
        load_signed_tool_registry(source, expected_sha256="0" * 64)

    path.write_text(
        '{"schema_version":1,"schema_version":1,"contract_version":"1",'
        '"entries":[],"entries_hash":"x"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate signed tool registry"):
        load_signed_tool_registry(path)
