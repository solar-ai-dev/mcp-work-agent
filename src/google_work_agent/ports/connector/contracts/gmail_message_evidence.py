"""Additive, bounded per-message evidence in a Gmail thread snapshot payload."""

from typing import NotRequired, TypedDict

MAX_THREAD_EVIDENCE_MESSAGES = 20
MAX_MESSAGE_EVIDENCE_CHARS = 12000


class GmailMessageEvidenceV1(TypedDict):
    message_id: str
    thread_id: str
    sender_name: str | None
    sender_email: str | None
    recipients: list[str]
    received_at: str | None
    subject: str | None
    body: str | None
    body_truncated: bool
    rfc822_message_id: NotRequired[str | None]
    references: NotRequired[str | None]
