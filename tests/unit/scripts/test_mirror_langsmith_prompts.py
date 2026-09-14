from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from langchain_core.load.dump import dumps
from langchain_core.prompts import ChatPromptTemplate
from scripts.mirror_langsmith_prompts import (
    PromptMirrorEntry,
    build_prompt_entry,
    mirror_prompt,
    prompt_identifier,
)


@dataclass
class _RemotePrompt:
    description: str
    readme: str
    is_public: bool = False


class _PromptClient:
    def __init__(self) -> None:
        self.resources: dict[str, _RemotePrompt] = {}
        self.prompts: dict[str, object] = {}
        self.pushes = 0
        self.metadata_updates = 0

    def get_prompt(self, prompt_identifier: str) -> object | None:
        return self.resources.get(prompt_identifier)

    def pull_prompt(self, prompt_identifier: str, *, include_model: bool = False) -> object:
        assert include_model is False
        return self.prompts[prompt_identifier]

    def push_prompt(
        self,
        prompt_identifier: str,
        *,
        object: object | None = None,
        parent_commit_hash: str = "latest",
        is_public: bool | None = None,
        description: str | None = None,
        readme: str | None = None,
        tags: object | None = None,
    ) -> str:
        assert parent_commit_hash == "latest"
        assert is_public is False
        assert object is not None
        assert description is not None
        assert readme is not None
        assert tags is None
        self.resources[prompt_identifier] = _RemotePrompt(description, readme)
        self.prompts[prompt_identifier] = object
        self.pushes += 1
        return "https://smith.langchain.com/prompts/private"

    def update_prompt(
        self,
        prompt_identifier: str,
        *,
        description: str | None = None,
        readme: str | None = None,
        tags: object | None = None,
        is_public: bool | None = None,
        is_archived: bool | None = None,
    ) -> dict[str, object]:
        assert tags is None
        assert is_archived is None
        assert is_public is False
        assert description is not None
        assert readme is not None
        self.resources[prompt_identifier] = _RemotePrompt(description, readme)
        self.metadata_updates += 1
        return {}


def _entry(source: str = "Do the bounded work.\n") -> PromptMirrorEntry:
    import hashlib

    return build_prompt_entry(
        namespace="google-work-agent",
        manifest_slot={
            "prompt_id": "request_understanding.identify_goal",
            "prompt_version": "1.0.52",
            "content_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "activation_status": "DRAFT",
            "runtime_node_id": "request.identify_goal",
            "input_schema_version": 2,
            "output_schema_version": 10,
        },
        source_text=source,
    )


def test_prompt_identifier__for_slot_and_model__is_stable_and_collision_resistant() -> None:
    first = prompt_identifier("google-work-agent", "request_understanding.identify_goal")
    second = prompt_identifier("google-work-agent", "request-understanding.identify-goal")

    assert first.startswith("google-work-agent--request-understanding-identify-goal--")
    assert first != second


def test_build_prompt_entry__with_manifest_slot__keeps_source_and_metadata() -> None:
    entry = _entry("Keep literal {json} unchanged.\n")

    message = entry.prompt.invoke({}).to_messages()[0]
    assert message.content == "Keep literal {json} unchanged.\n"
    assert entry.prompt.input_variables == []
    assert entry.prompt.metadata is not None
    assert entry.prompt.metadata["source_authority"] == "repository_manifest"
    assert entry.prompt.metadata["prompt_version"] == "1.0.52"


def test_mirror_prompt__after_initial_create__is_unchanged() -> None:
    client = _PromptClient()
    entry = _entry()

    planned = mirror_prompt(client, entry, apply=False)
    created = mirror_prompt(client, entry, apply=True)
    unchanged = mirror_prompt(client, entry, apply=True)

    assert planned.action == "WOULD_CREATE"
    assert created.action == "CREATED"
    assert unchanged.action == "UNCHANGED"
    assert client.pushes == 1
    assert dumps(client.prompts[entry.identifier]) == dumps(entry.prompt)


def test_mirror_prompt__with_hub_metadata__ignores_non_source_fields() -> None:
    client = _PromptClient()
    entry = _entry()
    mirror_prompt(client, entry, apply=True)
    remote = cast(ChatPromptTemplate, client.prompts[entry.identifier])
    assert remote.metadata is not None
    remote.metadata["lc_hub_commit_hash"] = "remote-commit"

    result = mirror_prompt(client, entry, apply=True)

    assert result.action == "UNCHANGED"
    assert client.pushes == 1


def test_mirror_prompt__when_source_changes__creates_new_commit() -> None:
    client = _PromptClient()
    first = _entry("First source.\n")
    changed = _entry("Changed source.\n")
    mirror_prompt(client, first, apply=True)

    result = mirror_prompt(client, changed, apply=True)

    assert result.action == "UPDATED"
    assert client.pushes == 2
    assert dumps(client.prompts[first.identifier]) == dumps(changed.prompt)
