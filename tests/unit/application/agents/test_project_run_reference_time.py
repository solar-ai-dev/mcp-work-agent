import pytest

from google_work_agent.application.agents.project_run_reference_time import (
    project_run_reference_time,
)


def test_run_reference_time__uses_durable_run_start__in_product_timezone() -> None:
    assert project_run_reference_time({"started_at_ms": 0}) == {
        "reference_time": "1970-01-01T09:00:00+09:00",
        "timezone": "Asia/Seoul",
    }


@pytest.mark.parametrize("started_at_ms", [None, -1, 1.5, "1787071400000"])
def test_run_reference_time__invalid_start__does_not_invent_current_time(
    started_at_ms: object,
) -> None:
    assert project_run_reference_time({"started_at_ms": started_at_ms}) is None
