"""Project bounded message evidence using the existing Google header/body parsers."""

from datetime import UTC, datetime

from google_work_agent.adapters.connectors.google.workspace.mcp_server import credential_provider
from google_work_agent.ports.connector.contracts.gmail_message_evidence import (
    MAX_MESSAGE_EVIDENCE_CHARS,
    MAX_THREAD_EVIDENCE_MESSAGES,
    GmailMessageEvidenceV1,
)


def project_message_evidence(
    messages: list[dict[str, object]],
    *,
    thread_id: str,
) -> list[GmailMessageEvidenceV1]:
    projected: list[GmailMessageEvidenceV1] = []
    for message in messages[-MAX_THREAD_EVIDENCE_MESSAGES:]:
        headers = credential_provider._headers(message)
        sender_name, sender_email = credential_provider._email_identity(
            credential_provider._decoded_header(headers.get("from"))
        )
        body = credential_provider._gmail_message_body(message)
        if body is None:
            body = credential_provider._optional_text(message.get("snippet"))
        internal_date = credential_provider._optional_text(message.get("internalDate"))
        received_at = (
            datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC).isoformat()
            if internal_date and internal_date.isdigit()
            else None
        )
        projected.append(
            {
                "message_id": credential_provider._required_response_text(message, "id"),
                "thread_id": thread_id,
                "sender_name": sender_name,
                "sender_email": sender_email,
                "recipients": list(
                    credential_provider._email_addresses(
                        credential_provider._decoded_header(headers.get("to"))
                    )
                )
                + list(
                    credential_provider._email_addresses(
                        credential_provider._decoded_header(headers.get("cc"))
                    )
                ),
                "received_at": received_at,
                "subject": credential_provider._decoded_header(headers.get("subject")),
                "body": None if body is None else body[:MAX_MESSAGE_EVIDENCE_CHARS],
                "body_truncated": body is not None and len(body) > MAX_MESSAGE_EVIDENCE_CHARS,
            }
        )
    return projected
