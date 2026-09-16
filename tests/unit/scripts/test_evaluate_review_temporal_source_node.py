from scripts.evaluate_review_temporal_source_node import _project_input


def _input(axis: str) -> dict[str, object]:
    return {
        "request_intent": {
            "constraints": [
                {"kind": "TIME", "field": "temporal_axis", "value": [axis]}
            ]
        },
        "evidence": [
            {
                "evidence_id": "mail-1",
                "resource_handle": "gmail_thread:thread-1",
                "excerpt": (
                    "Message: message-1\nSubject\nThread messages collected: 1/1\n"
                    "Received: 2026-09-07T02:13:22+00:00\n"
                    "업무 날짜는 8월 8일입니다."
                ),
                "locator": {"received_at": "2026-09-07T02:13:22+00:00"},
            }
        ],
    }


def test_event_time_projection_keeps_content_but_separates_receipt_time() -> None:
    source = _input("EVENT_TIME")

    result = _project_input(source, 1786060803921, include_reference=True)

    assert "Received:" not in result["evidence"][0]["excerpt"]
    assert "업무 날짜는 8월 8일입니다." in result["evidence"][0]["excerpt"]
    assert "received_at" not in result["evidence"][0]["locator"]
    assert result["run_reference_time"]["reference_time"].startswith("2026-08-07")
    assert "Received:" in source["evidence"][0]["excerpt"]


def test_message_time_projection_keeps_receipt_metadata() -> None:
    source = _input("MESSAGE_TIME")

    result = _project_input(source, 1786060803921, include_reference=False)

    assert result == source


def test_unmatched_envelope_keeps_original_evidence() -> None:
    source = _input("EVENT_TIME")
    source["evidence"][0]["locator"]["received_at"] = "different"

    result = _project_input(source, 1786060803921, include_reference=False)

    assert result == source
