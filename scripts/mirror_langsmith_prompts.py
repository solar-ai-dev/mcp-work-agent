"""Mirror verified repository Prompt sources to private LangSmith prompt history.

The repository manifest remains the only Product runtime authority. This command only
publishes an inspectable copy for development comparison and never pulls Prompt content
into Product execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langsmith import Client

from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry

REPOSITORY = "solar-ai-dev/google-work-agent"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "src"
    / "google_work_agent"
    / "application"
    / "prompt_runtime"
    / "prompt_manifest.json"
)
DEFAULT_NAMESPACE = "google-work-agent"
_SAFE_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class LangSmithPromptClient(Protocol):
    """Narrow external boundary used by the repository-to-LangSmith mirror."""

    def get_prompt(self, prompt_identifier: str) -> object | None: ...

    def pull_prompt(self, prompt_identifier: str, *, include_model: bool = False) -> object: ...

    def push_prompt(
        self,
        prompt_identifier: str,
        *,
        object: object | None = None,
        parent_commit_hash: str = "latest",
        is_public: bool | None = None,
        description: str | None = None,
        readme: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> str: ...

    def update_prompt(
        self,
        prompt_identifier: str,
        *,
        description: str | None = None,
        readme: str | None = None,
        tags: Sequence[str] | None = None,
        is_public: bool | None = None,
        is_archived: bool | None = None,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class PromptMirrorEntry:
    identifier: str
    prompt_id: str
    prompt_version: str
    content_hash: str
    description: str
    readme: str
    prompt: ChatPromptTemplate


@dataclass(frozen=True, slots=True)
class MirrorResult:
    prompt_id: str
    identifier: str
    prompt_version: str
    content_hash: str
    action: str


def prompt_identifier(namespace: str, prompt_id: str) -> str:
    """Return a stable private LangSmith handle without relying on slot punctuation."""

    if not _SAFE_NAMESPACE.fullmatch(namespace):
        raise ValueError("namespace must be a lowercase kebab-case identifier")
    slug = re.sub(r"[^a-z0-9]+", "-", prompt_id.lower()).strip("-")
    if not slug:
        raise ValueError("prompt_id must contain an ASCII identifier")
    identity_suffix = hashlib.sha256(prompt_id.encode("utf-8")).hexdigest()[:8]
    return f"{namespace}--{slug}--{identity_suffix}"


def build_prompt_entry(
    *,
    namespace: str,
    manifest_slot: Mapping[str, object],
    source_text: str,
) -> PromptMirrorEntry:
    """Build the exact fixed source mirror and its safe repository metadata."""

    prompt_id = _required_string(manifest_slot, "prompt_id")
    prompt_version = _required_string(manifest_slot, "prompt_version")
    content_hash = _required_string(manifest_slot, "content_hash")
    actual_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if actual_hash != content_hash:
        raise ValueError(f"Prompt source hash mismatch for {prompt_id}")
    metadata: dict[str, str | int] = {
        "repository": REPOSITORY,
        "source_authority": "repository_manifest",
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "content_hash": content_hash,
        "activation_status": _required_string(manifest_slot, "activation_status"),
        "runtime_node_id": _required_string(manifest_slot, "runtime_node_id"),
        "input_schema_version": _required_int(manifest_slot, "input_schema_version"),
        "output_schema_version": _required_int(manifest_slot, "output_schema_version"),
    }
    prompt = ChatPromptTemplate(
        messages=[SystemMessage(content=source_text)],
        input_variables=[],
        metadata=metadata,
        tags=["repository-mirror"],
    )
    description = (
        f"Private development mirror of {REPOSITORY} Prompt {prompt_id}. "
        "The repository manifest remains the Product runtime authority."
    )
    readme = "\n".join(
        (
            "# Repository Prompt mirror",
            "",
            f"- Prompt ID: `{prompt_id}`",
            f"- Version: `{prompt_version}`",
            f"- SHA-256: `{content_hash}`",
            f"- Activation: `{metadata['activation_status']}`",
            "- Runtime authority: repository source + manifest (not LangSmith)",
            "",
            "This resource is private and intended for diffing Prompt commits against traces.",
        )
    )
    return PromptMirrorEntry(
        identifier=prompt_identifier(namespace, prompt_id),
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        content_hash=content_hash,
        description=description,
        readme=readme,
        prompt=prompt,
    )


def load_prompt_entries(
    manifest_path: Path,
    *,
    namespace: str,
    selected_prompt_ids: frozenset[str] = frozenset(),
) -> tuple[PromptMirrorEntry, ...]:
    """Load only sources already validated by the Product Prompt registry."""

    resolved_manifest = manifest_path.resolve(strict=True)
    registry = PromptRegistry(manifest_path=resolved_manifest)
    payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    raw_slots = payload.get("slots")
    if not isinstance(raw_slots, list):
        raise ValueError("prompt manifest slots must be an array")
    entries: list[PromptMirrorEntry] = []
    seen_identifiers: set[str] = set()
    for raw_slot in raw_slots:
        if not isinstance(raw_slot, Mapping):
            raise ValueError("prompt manifest slot must be an object")
        prompt_id = _required_string(raw_slot, "prompt_id")
        if selected_prompt_ids and prompt_id not in selected_prompt_ids:
            continue
        entry = build_prompt_entry(
            namespace=namespace,
            manifest_slot=raw_slot,
            source_text=registry.source_text(prompt_id),
        )
        if entry.identifier in seen_identifiers:
            raise ValueError(f"duplicate LangSmith prompt identifier: {entry.identifier}")
        seen_identifiers.add(entry.identifier)
        entries.append(entry)
    found_prompt_ids = frozenset(entry.prompt_id for entry in entries)
    missing = selected_prompt_ids - found_prompt_ids
    if missing:
        raise ValueError(f"unknown Prompt IDs: {', '.join(sorted(missing))}")
    return tuple(entries)


def mirror_prompt(
    client: LangSmithPromptClient,
    entry: PromptMirrorEntry,
    *,
    apply: bool,
) -> MirrorResult:
    """Create one commit only when source or version metadata actually changed."""

    remote = client.get_prompt(entry.identifier)
    if remote is None:
        action = "CREATED" if apply else "WOULD_CREATE"
        if apply:
            client.push_prompt(
                entry.identifier,
                object=entry.prompt,
                is_public=False,
                description=entry.description,
                readme=entry.readme,
            )
        return _result(entry, action)

    remote_prompt = client.pull_prompt(entry.identifier, include_model=False)
    content_changed = not _prompt_matches(remote_prompt, entry.prompt)
    metadata_changed = any(
        (
            getattr(remote, "description", None) != entry.description,
            getattr(remote, "readme", None) != entry.readme,
            bool(getattr(remote, "is_public", False)),
        )
    )
    if content_changed:
        action = "UPDATED" if apply else "WOULD_UPDATE"
        if apply:
            client.push_prompt(
                entry.identifier,
                object=entry.prompt,
                parent_commit_hash="latest",
                is_public=False,
                description=entry.description,
                readme=entry.readme,
            )
    elif metadata_changed:
        action = "METADATA_UPDATED" if apply else "WOULD_UPDATE_METADATA"
        if apply:
            client.update_prompt(
                entry.identifier,
                description=entry.description,
                readme=entry.readme,
                is_public=False,
            )
    else:
        action = "UNCHANGED"
    return _result(entry, action)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--apply", action="store_true", help="publish private Prompt commits")
    result.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    result.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    result.add_argument("--prompt-id", action="append", default=[])
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    entries = load_prompt_entries(
        arguments.manifest,
        namespace=arguments.namespace,
        selected_prompt_ids=frozenset(arguments.prompt_id),
    )
    client = Client()
    results = tuple(mirror_prompt(client, entry, apply=arguments.apply) for entry in entries)
    for result in results:
        print(
            f"{result.action} {result.prompt_id} "
            f"version={result.prompt_version} sha256={result.content_hash[:12]} "
            f"langsmith={result.identifier}"
        )
    print(f"mode={'apply' if arguments.apply else 'dry-run'} prompts={len(results)}")
    return 0


def _result(entry: PromptMirrorEntry, action: str) -> MirrorResult:
    return MirrorResult(
        prompt_id=entry.prompt_id,
        identifier=entry.identifier,
        prompt_version=entry.prompt_version,
        content_hash=entry.content_hash,
        action=action,
    )


def _prompt_matches(remote: object, expected: ChatPromptTemplate) -> bool:
    """Compare owned fields while ignoring LangSmith's injected hub metadata."""

    if not isinstance(remote, ChatPromptTemplate):
        return False
    if remote.input_variables or expected.input_variables:
        return False
    try:
        remote_messages = remote.invoke({}).to_messages()
        expected_messages = expected.invoke({}).to_messages()
    except (KeyError, TypeError, ValueError):
        return False
    if len(remote_messages) != 1 or len(expected_messages) != 1:
        return False
    remote_message = remote_messages[0]
    expected_message = expected_messages[0]
    if type(remote_message) is not type(expected_message):
        return False
    if remote_message.content != expected_message.content:
        return False
    expected_metadata = expected.metadata or {}
    remote_metadata = remote.metadata or {}
    if any(remote_metadata.get(key) != value for key, value in expected_metadata.items()):
        return False
    return remote.tags == expected.tags


def _required_string(item: Mapping[str, object], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _required_int(item: Mapping[str, object], field: str) -> int:
    value = item.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
