"""Canonical Google provider operation for gmail send."""

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _gmail_send(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    payload = workspace_support._dict_argument(arguments, "payload")
    draft_id = (
        workspace_support._text_argument(arguments, "draft_id", maximum=2048)
        if "draft_id" in arguments else None
    )
    workspace_support._validate_claim_context(
        state,
        tool_name="gmail_send",
        claim_context=arguments.get("claim_context"),
        execution_arguments=workspace_support._execution_arguments(arguments),
    )
    workspace_support._validate_gmail_reply(state, payload, existing_draft_id=draft_id)
    message: dict[str, object] = {
        "raw": workspace_support._b64url_encode(workspace_support._build_gmail_mime(payload)),
    }
    if payload.get("thread_id"):
        message["threadId"] = payload["thread_id"]
    endpoint = "messages/send" if draft_id is None else "drafts/send"
    body: dict[str, object] = message if draft_id is None else {"id": draft_id, "message": message}
    response = workspace_support._google_api_post(
        state, f"https://gmail.googleapis.com/gmail/v1/users/me/{endpoint}", body
    )
    headers = workspace_support._headers(response)
    message_id = workspace_support._required_response_text(response, "id")
    return {
        "item": workspace_support._snapshot(
            "gmail_message",
            message_id,
            workspace_support._optional_text(response.get("threadId")),
            (),
            response.get("historyId"),
            {"subject": headers.get("subject"), "sent": True, "draft_id": draft_id},
        )
    }


class SendMessageOperation:
    tool_id = "gmail_send"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_send(state, arguments)


__all__ = ["SendMessageOperation"]
