from __future__ import annotations

from scripts import benchmark_gmail_metadata_hydration as benchmark


def test_balanced_blocks__give_each_config__every_position_ten_times() -> None:
    blocks = benchmark._balanced_blocks(100)

    assert len(blocks) == 100
    for config in benchmark.CONFIGS:
        positions = [
            position
            for _, values in blocks
            for position, candidate in enumerate(values)
            if candidate.config_id == config.config_id
        ]
        assert len(positions) == 100
        assert {position: positions.count(position) for position in range(10)} == {
            position: 10 for position in range(10)
        }


def test_canonical_result__ignores_session_handles__but_preserves_order_and_metadata() -> None:
    first = {
        "items": [
            {
                "resource_id": "thread-a",
                "selection_handle": "session-one",
                "link_url": "/one",
                "subject": "subject",
            }
        ],
        "next_page_token": "sealed-one",
    }
    second = {
        "items": [
            {
                "resource_id": "thread-a",
                "selection_handle": "session-two",
                "link_url": "/two",
                "subject": "subject",
            }
        ],
        "next_page_token": "sealed-two",
    }

    assert benchmark._canonical_result_payload(first) == benchmark._canonical_result_payload(second)

    second["items"][0]["subject"] = "changed"  # type: ignore[index]
    assert benchmark._canonical_result_payload(first) != benchmark._canonical_result_payload(second)


def test_percentile__uses_linear__type7() -> None:
    assert benchmark._percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert benchmark._percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 3.8499999999999996


def test_wilson__retains_nonzero_upper_bound__for_zero_failures() -> None:
    lower, upper = benchmark._wilson(0, 100)

    assert lower == 0
    assert upper is not None
    assert 0.036 < upper < 0.038


def test_paired_bootstrap__reports_candidate__reduction() -> None:
    baseline = {index: 100.0 + index for index in range(1, 101)}
    candidate = {index: 50.0 + index for index in range(1, 101)}

    result = benchmark._paired_bootstrap(baseline, candidate)

    assert result["n_pairs"] == 100
    assert result["delta_p95_ms"] == -50.0
    assert float(result["reduction_pct"]) > 0


def test_logical_api_operation_count__counts_list_and_batch__inner_calls_once() -> None:
    rows = [
        {"kind": "GMAIL_THREADS_LIST", "inner_count": None},
        {"kind": "GMAIL_BATCH", "inner_count": 10},
        {"kind": "GMAIL_BATCH", "inner_count": 10},
    ]

    assert benchmark._logical_api_operation_count(rows) == 21
