import json
from pathlib import Path
from typing import cast

from scripts import benchmark_gmail_execute_read_node as benchmark

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1


def test_materialize_input__from_production_registry__uses_signed_binding() -> None:
    registry = load_signed_tool_registry()

    plan, binding, arguments = benchmark._materialize_input(registry)

    assert plan["operation_kind"] == "SEARCH"
    assert plan["prior_read_result_handle"] is None
    assert plan["detail_candidate_ref"] is None
    assert arguments["query"] == benchmark.EXPECTED_FIXED_QUERY
    assert arguments["page_size"] == 20
    assert arguments["include_thread_metadata"] is True
    assert binding == registry.bind_required("google_workspace", "gmail_search_threads", "READ")


def test_result_hashes__when_metadata_changes__detect_projection_only() -> None:
    original = ConnectorReadResultV1(
        1,
        "gmail_search_threads",
        "request",
        {
            "items": [
                {
                    "resource_type": "gmail_thread",
                    "resource_id": "thread-1",
                    "parent_id": None,
                    "related_resource_ids": [],
                    "version": "1",
                    "payload": {"subject": "subject"},
                }
            ]
        },
        "page",
        1,
    )
    changed_metadata = ConnectorReadResultV1(
        1,
        "gmail_search_threads",
        "request",
        {
            "items": [
                {
                    "resource_type": "gmail_thread",
                    "resource_id": "thread-1",
                    "parent_id": None,
                    "related_resource_ids": [],
                    "version": "2",
                    "payload": {"subject": "changed"},
                }
            ]
        },
        "page",
        1,
    )

    assert benchmark._identity_hash(original) == benchmark._identity_hash(changed_metadata)
    assert benchmark._metadata_hash(original) != benchmark._metadata_hash(changed_metadata)


def test_summary__from_measured_rows__excludes_dataset_drift(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    for config_id, latency, http_count in (
        ("S3_BASELINE", 4000.0, 21),
        ("B20W1", 1000.0, 2),
    ):
        rows.extend(
            {
                "sample_kind": "MEASURED",
                "config_id": config_id,
                "measurement_validity": "COMPARABLE",
                "node_latency_ms": latency,
                "provider_wall_ms": latency - 2,
                "mcp_wall_ms": latency - 1,
                "physical_http_request_count": http_count,
                "logical_provider_call_count": 21,
                "cpu_time_ms": 1,
                "peak_rss_bytes": 2,
                "peak_thread_count": 3,
                "is_timeout": False,
                "is_429": False,
                "is_rate_limited": False,
                "is_5xx": False,
                "provider_write_send_count": 0,
                "retry_count": 0,
            }
            for _ in range(100)
        )
    rows.append(
        {
            "sample_kind": "MEASURED",
            "config_id": "B20W1",
            "measurement_validity": "DATASET_DRIFT",
            "node_latency_ms": 1,
        }
    )
    (tmp_path / "node_trials.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    summary = benchmark._summary(tmp_path)

    configs = {row["config_id"]: row for row in cast(list[dict[str, object]], summary["configs"])}
    assert configs["B20W1"]["comparable_attempts"] == 100
    assert configs["B20W1"]["dataset_drift_count"] == 1
    assert configs["B20W1"]["p95_node_latency_ms"] == 1000
    assert summary["selected_config"] == "B20W1"
