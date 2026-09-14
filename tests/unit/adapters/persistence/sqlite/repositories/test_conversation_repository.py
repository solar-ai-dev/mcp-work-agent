from __future__ import annotations

import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.conversation_repository import (
    SqliteConversationRepository,
)
from google_work_agent.domain.conversation.model import LOCAL_WORKSPACE_ACCOUNT_ID
from google_work_agent.domain.conversation.model import Conversation as ConversationRecord


def _repository() -> SqliteConversationRepository:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE conversations (
            id TEXT PRIMARY KEY, account_id TEXT, title TEXT,
            created_at_ms INTEGER, updated_at_ms INTEGER
        )"""
    )
    connection.execute(
        "CREATE TABLE messages (conversation_id TEXT, content TEXT, created_at_ms INTEGER)"
    )
    connection.execute(
        """CREATE TABLE runs (
            id TEXT, conversation_id TEXT, started_at_ms INTEGER, finished_at_ms INTEGER
        )"""
    )
    return SqliteConversationRepository(connection)


def test_local_conversation__survives_connection_change__without_merging_other_accounts() -> None:
    repository = _repository()
    for index, account_id in enumerate((LOCAL_WORKSPACE_ACCOUNT_ID, "account-1", "account-2")):
        repository.create(ConversationRecord(str(index), account_id, "title", 1, index + 1))
    anonymous, _ = repository.list_keyset(
        account_id=LOCAL_WORKSPACE_ACCOUNT_ID,
        cursor=None,
        page_size=50,
    )
    connected, _ = repository.list_keyset(account_id="account-1", cursor=None, page_size=50)
    assert [item.conversation.id for item in anonymous] == ["0"]
    assert [item.conversation.id for item in connected] == ["1", "0"]


def test_conversation_repository__implements_exact__keyset_surface() -> None:
    repository = _repository()
    for conversation_id, updated_at_ms in (("c-1", 10), ("c-2", 20), ("c-3", 30)):
        repository.create(
            ConversationRecord(
                id=conversation_id,
                account_id="account-1",
                title=conversation_id,
                created_at_ms=updated_at_ms,
                updated_at_ms=updated_at_ms,
            )
        )

    first, cursor = repository.list_keyset(account_id="account-1", cursor=None, page_size=2)
    second, next_cursor = repository.list_keyset(account_id="account-1", cursor=cursor, page_size=2)

    assert [item.conversation.id for item in first] == ["c-3", "c-2"]
    assert [item.conversation.id for item in second] == ["c-1"]
    assert next_cursor is None
    repository.touch_updated_at("c-1", updated_at_ms=40)
    assert repository.get("c-1").updated_at_ms == 40  # type: ignore[union-attr]
