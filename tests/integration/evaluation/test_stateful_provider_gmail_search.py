"""Synthetic Gmail search may index detail text without exposing it as preview evidence."""

from types import SimpleNamespace

from evaluation.harness.stateful_provider import StatefulSimulatedProvider


def test_gmail_search__body_index_hit__does_not_expose_body_as_snippet() -> None:
    body = "hidden approval detail"
    provider = StatefulSimulatedProvider(
        initial_resources=[
            {
                "resource_type": "gmail_thread",
                "resource_id": "thread-1",
                "payload": {
                    "subject": "Project update",
                    "messages": [{"body": body, "received_at": "2026-09-16T10:00:00+09:00"}],
                },
            }
        ]
    )

    search = provider.execute_read(
        SimpleNamespace(tool_id="gmail_search_threads"),
        {"query": '"hidden approval detail"', "page_size": 10},
    )
    preview = search["output"]["items"][0]["payload"]
    detail = provider.execute_read(
        SimpleNamespace(tool_id="gmail_get_thread"),
        {"thread_id": "thread-1"},
    )["output"]["item"]["payload"]

    assert preview["snippet"] == ""
    assert "messages" not in preview
    assert detail["messages"][0]["body"] == body


def test_gmail_search__uses_fixture_snippet_when_available() -> None:
    provider = StatefulSimulatedProvider(
        initial_resources=[
            {
                "resource_type": "gmail_thread",
                "resource_id": "thread-1",
                "payload": {
                    "subject": "Project update",
                    "snippet": "Short preview",
                    "messages": [{"body": "Full private text"}],
                },
            }
        ]
    )

    search = provider.execute_read(
        SimpleNamespace(tool_id="gmail_search_threads"),
        {"query": '"private"', "page_size": 10},
    )

    assert search["output"]["items"][0]["payload"]["snippet"] == "Short preview"
