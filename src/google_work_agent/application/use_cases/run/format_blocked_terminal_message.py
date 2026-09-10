"""Format user-facing blocked results from bounded terminal reason facts."""

from collections.abc import Sequence


def format_blocked_terminal_message(
    *,
    source_kind: str,
    reason_codes: Sequence[str],
) -> str:
    """Explain the blocked outcome without exposing internal reason codes."""

    reasons = frozenset(reason_codes)
    if reasons & {"LOCAL_UNAVAILABLE", "MODEL_NOT_APPROVED"}:
        return (
            "사용할 로컬 AI 모델이 준비되지 않아 요청을 실행하지 않았습니다. "
            "설정에서 모델을 검사하고 준비된 모델을 선택한 뒤 새로 요청해 주세요."
        )
    if "API_KEY_MISSING" in reasons:
        return "API AI 연결이 필요합니다. 설정에서 API Key를 등록한 뒤 새로 요청해 주세요."
    if "CONSENT_REQUIRED" in reasons:
        return (
            "외부 AI 전송 동의가 없어 요청을 실행하지 않았습니다. "
            "설정에서 동의하거나 준비된 로컬 AI를 선택한 뒤 새로 요청해 주세요."
        )
    if "RUNTIME_MODE_BLOCKED" in reasons:
        return "선택한 AI 실행 방식은 사용할 수 없습니다. 설정을 확인한 뒤 새로 요청해 주세요."
    if "CONTEXT_BLOCKED" in reasons:
        return (
            "요청을 뒷받침할 충분한 근거를 확보하지 못해 작업을 완료하지 못했습니다. "
            "외부 변경은 실행하지 않았습니다. 검색 조건을 바꾸거나 확인할 자료를 "
            "지정해 다시 요청해 주세요."
        )
    if reasons & {
        "OUTPUT_SCHEMA_INVALID",
        "REQUEST_STATUS_PROVENANCE_MISMATCH",
        "REQUEST_AMBIGUITY_RESOLUTION_OWNER_CONFLICT",
        "REQUEST_AMBIGUITY_OWNER_FIELDS_MISMATCH",
        "RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID",
        "QUERY_OPERATION_FIELD_MISMATCH",
        "QUERY_OPERATION_UNAVAILABLE",
        "RETRIEVAL_ROUTE_SCOPE_VIOLATION",
        "QUERY_USER_CONSTRAINT_MISSING",
    }:
        return (
            "요청을 처리하는 중 내부 검증에 실패해 결과나 변경안을 준비하지 못했습니다. "
            "외부 변경은 실행하지 않았습니다. 잠시 후 다시 요청해 주세요."
        )
    if source_kind == "INVALID_REQUEST":
        return (
            "요청을 처리하는 데 필요한 조건을 확인하지 못해 안전하게 중단했습니다. "
            "요청 대상을 더 구체적으로 알려주세요."
        )
    return (
        "안전 정책 또는 필수 조건 때문에 요청하신 작업을 실행하지 않았습니다. "
        "외부 변경은 실행하지 않았습니다."
    )


__all__ = ["format_blocked_terminal_message"]
