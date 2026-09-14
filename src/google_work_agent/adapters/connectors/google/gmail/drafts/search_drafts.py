"""Canonical Google provider operation for Gmail Draft search."""

from concurrent.futures import ThreadPoolExecutor

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _gmail_search_drafts(
    state: workspace_support.GoogleWorkspaceCredentialProvider,
    arguments: dict[str, object],
) -> dict[str, object]:
    query = workspace_support._text_argument(
        arguments, "query", maximum=2048, allow_empty=True
    )
    params = workspace_support._page_params(arguments)
    if query:
        params["q"] = query
    payload = workspace_support._google_api(
        state,
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
        params,
    )
    draft_ids = [
        workspace_support._required_response_text(item, "id")
        for item in workspace_support._object_list(payload.get("drafts"))
    ]
    with ThreadPoolExecutor(
        max_workers=workspace_support.GMAIL_METADATA_HYDRATION_MAX_WORKERS
    ) as executor:
        items = list(
            executor.map(
                lambda draft_id: workspace_support._gmail_draft_snapshot(
                    workspace_support._google_api(
                        state,
                        "https://gmail.googleapis.com/gmail/v1/users/me/drafts/"
                        + workspace_support.quote(draft_id, safe=""),
                        {"format": "full"},
                    )
                ),
                draft_ids,
            )
        )
    return {
        "items": items,
        "next_page_token": workspace_support._optional_text(payload.get("nextPageToken")),
    }


class SearchDraftsOperation:
    tool_id = "gmail_search_drafts"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_search_drafts(state, arguments)


__all__ = ["SearchDraftsOperation"]
