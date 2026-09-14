from __future__ import annotations

from types import SimpleNamespace

import pytest
from evaluation.harness.case_runtime import CanonicalCaseRuntime
from evaluation.harness.fault_adapters import FaultApplyingAdapter
from evaluation.harness.fault_profiles import FaultHarness
from evaluation.harness.stateful_provider import StatefulSimulatedProvider
from scripts.serve_canonical_v8_product import (
    _normalize_provider_resources,
    _RetrievalFaultReadAdapter,
    _simulated_read_result,
)

from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)


def test_acquisition_fault__stops_before_provider_read() -> None:
    provider = StatefulSimulatedProvider(read_result_factory=_simulated_read_result)
    fault = FaultApplyingAdapter(FaultHarness.for_case("CASE-STRESS-009"))
    adapter = _RetrievalFaultReadAdapter(delegate=provider, fault_adapter=fault)

    with pytest.raises(ConnectorOperationFailure) as raised:
        adapter.execute_read(
            SimpleNamespace(tool_id="gmail_search_threads"),
            {"query": "Lumen", "page_size": 20},
        )

    assert raised.value.code is ConnectorFailureCode.RATE_LIMITED
    assert raised.value.detail_code == "ACQUISITION_LIMIT_REACHED"
    assert provider.read_calls == []
    assert len(fault.records) == 1
    assert fault.records[0].boundary == "RETRIEVAL_ACQUISITION"


def test_ranking_fault__binds_simulated_fixture_before_product_consumes_read() -> None:
    runtime = CanonicalCaseRuntime.for_case("CASE-STRESS-010")
    fixture = runtime.simulated_fixture()
    resources = _normalize_provider_resources(fixture["resources"])
    provider = StatefulSimulatedProvider(
        initial_resources=resources,
        read_result_factory=_simulated_read_result,
    )
    fault = runtime.fault_adapter()
    adapter = _RetrievalFaultReadAdapter(delegate=provider, fault_adapter=fault)

    result = adapter.execute_read(
        SimpleNamespace(tool_id="gmail_search_threads"),
        {"query": "Delta", "page_size": 20, "include_thread_metadata": True},
    )

    items = result.output["items"]
    assert [item["payload"]["project"] for item in items] == ["Delta", "Delta Plus"]
    assert [item["payload"]["received_at"] for item in items] == [
        "2026-09-14T12:55:14+09:00",
        "2026-09-16T11:02:30+09:00",
    ]
    assert [item["payload"]["body"] for item in items] == [
        "Delta 포장 승인 요청입니다. 최종 승인자는 수빈이며 시안 의견은 승인 전에 회신합니다.",
        "Delta Plus 포장 승인 건은 수민이 최종 승인하며 수정 의견은 이 요청에 모읍니다.",
    ]
    assert len(fault.records) == 1
    assert fault.records[0].boundary == "RETRIEVAL_RANKING"
