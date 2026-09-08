from google_work_agent.application.use_cases.trace_event.resolve_activity_step import (
    resolve_activity_step,
)


def test_activity_step__resolves_direct_and_composite__semantic_owner() -> None:
    direct = resolve_activity_step("context_retriever", "execute_read")
    composite = resolve_activity_step("stage_one", "execute_read")

    assert direct is not None
    assert direct.label == "자료 조회"
    assert composite == direct


def test_activity_step__does_not_invent__unknown_work() -> None:
    assert resolve_activity_step("context_retriever", "unobserved_step") is None


def test_activity_step__build_query_validation__is_observable() -> None:
    result = resolve_activity_step("context_retriever", "build_query")

    assert result is not None
    assert result.label == "검색 조건 검증"
