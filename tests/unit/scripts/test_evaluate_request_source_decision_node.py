from scripts.evaluate_request_source_decision_node import _status_attempt_summaries


def test_status_attempt_summaries_record_binding_without_request_text() -> None:
    request = "출고 확정 메일을 찾아줘."
    output = {
        "statuses": [
            {
                "source_resource_type": "GMAIL_THREAD",
                "value": "SENT",
                "source": "USER_REQUEST",
                "source_text": "확정 메일",
            },
            {
                "source_resource_type": "GMAIL_THREAD",
                "value": "DRAFT",
                "source": "USER_REQUEST",
                "source_text": "없는 인용",
            },
        ]
    }

    summary = _status_attempt_summaries([output], request)

    assert summary == [
        [
            {
                "resource_type": "GMAIL_THREAD",
                "status": "SENT",
                "source": "USER_REQUEST",
                "source_text_in_request": True,
            },
            {
                "resource_type": "GMAIL_THREAD",
                "status": "DRAFT",
                "source": "USER_REQUEST",
                "source_text_in_request": False,
            },
        ]
    ]
    assert "없는 인용" not in str(summary)
