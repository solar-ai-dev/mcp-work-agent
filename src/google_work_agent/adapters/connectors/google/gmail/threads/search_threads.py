"""Canonical Google provider operation for gmail search threads."""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, urlencode

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)
from google_work_agent.ports.connector.contracts.delivery_certainty import DeliveryCertainty


@dataclass(frozen=True, slots=True)
class GmailMetadataHydrationConfig:
    transport: Literal["INDIVIDUAL", "BATCH"]
    batch_size: int | None
    http_concurrency_limit: int

    def __post_init__(self) -> None:
        if self.http_concurrency_limit < 1:
            raise ValueError("http_concurrency_limit must be positive")
        if self.transport == "INDIVIDUAL":
            if self.batch_size is not None:
                raise ValueError("individual hydration must not define batch_size")
            return
        if self.batch_size is None or not 1 <= self.batch_size <= 50:
            raise ValueError("batch_size must be between 1 and 50")


GMAIL_METADATA_HYDRATION_CONFIG = GmailMetadataHydrationConfig(
    transport="BATCH",
    batch_size=20,
    http_concurrency_limit=1,
)


def _gmail_search_threads(
    state: workspace_support.GoogleWorkspaceCredentialProvider,
    arguments: dict[str, object],
    *,
    hydration_config: GmailMetadataHydrationConfig | None = None,
) -> dict[str, object]:
    config = hydration_config or GMAIL_METADATA_HYDRATION_CONFIG
    query = workspace_support._text_argument(arguments, "query", maximum=2048, allow_empty=True)
    include_thread_metadata = arguments.get("include_thread_metadata", True)
    if not isinstance(include_thread_metadata, bool):
        raise workspace_support._WorkspaceToolError("INVALID_ARGUMENT")
    params = workspace_support._page_params(arguments)
    if query:
        params["q"] = query
    if not include_thread_metadata:
        params["fields"] = "threads/id,nextPageToken"
    list_started = time.perf_counter_ns()
    try:
        payload = workspace_support._google_api(
            state, "https://gmail.googleapis.com/gmail/v1/users/me/threads", params
        )
    except Exception:
        workspace_support._notify_provider_phase(
            state, phase="LIST", started=list_started, status="FAILED"
        )
        raise
    workspace_support._notify_provider_phase(
        state, phase="LIST", started=list_started, status="SUCCESS"
    )
    threads = workspace_support._object_list(payload.get("threads"))
    thread_entries = [
        (
            workspace_support._required_response_text(thread, "id"),
            workspace_support._optional_text(thread.get("snippet")),
            thread.get("historyId"),
        )
        for thread in threads
    ]
    if include_thread_metadata:
        detail_started = time.perf_counter_ns()
        try:
            metadata_items = _hydrate_thread_metadata(state, thread_entries, config=config)
        except Exception:
            workspace_support._notify_provider_phase(
                state, phase="DETAIL", started=detail_started, status="FAILED"
            )
            raise
        workspace_support._notify_provider_phase(
            state, phase="DETAIL", started=detail_started, status="SUCCESS"
        )
    else:
        metadata_items = [{} for _ in thread_entries]
    projection_started = time.perf_counter_ns()
    items = []
    for (thread_id, _list_snippet, history_id), metadata in zip(
        thread_entries, metadata_items, strict=True
    ):
        items.append(
            workspace_support._snapshot("gmail_thread", thread_id, None, (), history_id, metadata)
        )
    workspace_support._notify_provider_phase(
        state, phase="PROJECTION", started=projection_started, status="SUCCESS"
    )
    return {
        "items": items,
        "next_page_token": workspace_support._optional_text(payload.get("nextPageToken")),
    }


def _hydrate_thread_metadata(
    state: workspace_support.GoogleWorkspaceCredentialProvider,
    thread_entries: list[tuple[str, str | None, object]],
    *,
    config: GmailMetadataHydrationConfig,
) -> list[dict[str, object]]:
    if not thread_entries:
        return []
    if len(thread_entries) == 1:
        thread_id, list_snippet, _history_id = thread_entries[0]
        return [
            workspace_support._gmail_thread_list_metadata(
                state=state,
                thread_id=thread_id,
                list_snippet=list_snippet,
            )
        ]
    if config.transport == "INDIVIDUAL":
        return _map_bounded(
            lambda entry: workspace_support._gmail_thread_list_metadata(
                state=state,
                thread_id=entry[0],
                list_snippet=entry[1],
            ),
            thread_entries,
            concurrency_limit=config.http_concurrency_limit,
        )
    batch_size = config.batch_size
    if batch_size is None:
        raise ValueError("batch transport requires batch_size")
    batches = [
        thread_entries[index : index + batch_size]
        for index in range(0, len(thread_entries), batch_size)
    ]
    hydrated_batches = _map_bounded(
        lambda entries: _hydrate_thread_metadata_batch(state, entries),
        batches,
        concurrency_limit=config.http_concurrency_limit,
    )
    return [item for batch in hydrated_batches for item in batch]


def _hydrate_thread_metadata_batch(
    state: workspace_support.GoogleWorkspaceCredentialProvider,
    thread_entries: list[tuple[str, str | None, object]],
) -> list[dict[str, object]]:
    params = urlencode(
        {
            "format": "metadata",
            "metadataHeaders": ["From", "Subject", "Date"],
            "fields": "messages(internalDate,payload/headers),snippet",
        },
        doseq=True,
    )
    targets = tuple(
        f"/gmail/v1/users/me/threads/{quote(entry[0], safe='')}?{params}"
        for entry in thread_entries
    )
    results = workspace_support._google_batch_get(state, targets)
    if len(results) != len(thread_entries):
        raise workspace_support._WorkspaceToolError(
            "INVALID_MCP_OUTPUT",
            delivery_certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
        )
    metadata_items: list[dict[str, object]] = []
    for expected_ordinal, (entry, result) in enumerate(zip(thread_entries, results, strict=True)):
        if result.ordinal != expected_ordinal:
            raise workspace_support._WorkspaceToolError(
                "INVALID_MCP_OUTPUT",
                delivery_certainty=DeliveryCertainty.MAY_HAVE_BEEN_SENT,
            )
        workspace_support._notify_provider_payload(
            state,
            kind="GMAIL_THREAD_GET",
            message_count=(
                len(messages)
                if isinstance((messages := result.payload.get("messages")), list)
                else 0
            ),
        )
        metadata_items.append(
            workspace_support._gmail_thread_list_metadata_from_payload(
                result.payload,
                list_snippet=entry[1],
            )
        )
    return metadata_items


def _map_bounded[InputT, OutputT](
    operation: Callable[[InputT], OutputT],
    values: list[InputT],
    *,
    concurrency_limit: int,
) -> list[OutputT]:
    if concurrency_limit == 1 or len(values) == 1:
        return [operation(value) for value in values]
    with ThreadPoolExecutor(max_workers=min(concurrency_limit, len(values))) as executor:
        return list(executor.map(operation, values))


class SearchThreadsOperation:
    tool_id = "gmail_search_threads"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_search_threads(state, arguments)


__all__ = ["GmailMetadataHydrationConfig", "SearchThreadsOperation"]
