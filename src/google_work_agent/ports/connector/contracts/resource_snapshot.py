"""Connector-neutral resource observation contracts."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ResourceType(StrEnum):
    GMAIL_THREAD = "gmail_thread"
    GMAIL_MESSAGE = "gmail_message"
    GMAIL_DRAFT = "gmail_draft"
    TASK_LIST = "task_list"
    TASK = "task"
    CALENDAR = "calendar"
    CALENDAR_EVENT = "calendar_event"
    CALENDAR_FREEBUSY = "calendar_freebusy"
    GITHUB_ISSUE = "github_issue"


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    fixture_snapshot_id: str
    resource_type: ResourceType
    resource_id: str
    parent_id: str | None
    related_resource_ids: tuple[str, ...]
    version: str
    recovery_fingerprint: str | None
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ResourcePage:
    items: tuple[ResourceSnapshot, ...]
    next_page_token: str | None


__all__ = ["ResourcePage", "ResourceSnapshot", "ResourceType"]
