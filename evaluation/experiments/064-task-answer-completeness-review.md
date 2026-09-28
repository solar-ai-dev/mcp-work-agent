# 064 — Task READ formatter completeness 검토 및 owner-local 수정

## 확인 결함

`project_task_read_answer`는 `READ + TASK + analysis_requirement=NONE`이면 deterministic 답변을 만든다. `_requested_task_fields`는 required_information 중 지원하는 상태·예정일 항목만 선택하고 나머지를 조용히 버린다. 따라서 이미 조회한 notes가 있어도 notes-only 요청을 제목-only 답변으로 바꾸고 `compose_answer`의 LLM 작성 경로를 우회한다.

읽기/직접 pure-function probe 결과:

```json
{
  "required_information": ["notes"],
  "projection_taken": true,
  "owner_calls": [],
  "returned_answer": "I found 1 current item(s) in Google Tasks.\n\n- Task memo review",
  "requested_note_preserved": false,
  "evidence_contains_note": true
}
```

이는 모델 의미 판단 실패나 fixture 부족이 아니라, 확정된 typed Source 정보 요구를 읽은 뒤 formatter가 지원하지 않는 부분을 삭제하는 소비 경계 결함이다. 이 probe는 모델/Graph/Provider를 실행하지 않았다.

근거:

- `project_task_read_answer.py:90–110`: required_information의 일부만 필드로 변환.
- `project_task_read_answer.py:116–139`: 실제 formatter는 title/status/scheduled_date만 출력.
- `compose_answer.py:274–291`: non-None projection이면 LLM 전에 반환.
- `outline_answer.py:157–164`: 동일 shortcut 사용.
- Canonical 06 §3.1의 Source `required_information` 보존 책임, 01-a의 Tasks 조회·날짜/상태 의미와 충돌한다.
- 기존 `test_task_read_answer__status_and_scheduled_date__preserve_both_meanings`는 입력에 notes가 있지만 notes 보존을 검사하지 않아 이 누락을 잡지 못한다.

## 최소 owner-local 수정안

CORE-005 기준 실행(`76f5fa2e`, `evaluation/results/064-core005-main-graph-t1`) 중에는 아래 수정안을 미적용 상태로 보존했다. 기준 실행 종료 후 해당 raw를 변경하거나 재실행하지 않고 Product의 formatter owner에만 적용했다.

1. formatter가 이미 지원하는 typed 정보→출력 필드 mapping을 명시한다.
2. 요청된 `required_information` 전체가 그 mapping으로 표현되는지 확인한다.
3. 하나라도 미지원이면 projection을 `None`으로 반환하여 기존 Planning 작성 owner에 전달한다.
4. notes를 억지로 출력하거나 Source 필드를 삭제하지 않는다. 자연어 요청 parser, Case 단어, Gold/Schema/Prompt 변경도 없다.

아래는 적용한 핵심 diff 내용이다. mapping 값은 현재 formatter가 실제 출력하는 정보만 옮긴 것이며 지원 범위를 늘리지 않는다. `task_identity`는 과거에 unknown drop 뒤 기본 제목이 보였을 뿐 지원 alias가 아니었다. 이를 title로 낮추지 않고 미지원 정보로 기존 작성 owner에 넘긴다.

```python
# project_task_read_answer: 현재 requested_fields 계산 직후
requested_fields = _requested_task_fields(request_intent)
if requested_fields is None:
    return None


def _requested_task_fields(
    request_intent: Mapping[str, object],
) -> frozenset[str] | None:
    # 기존 responsibilities/source_reads 처리와 required_information 수집 유지.
    # 현재 legacy missing-responsibility 제목-only 처리도 이 변경에서는 유지.
    information_to_field = {
        "title": "title",
        "completion_status": "status",
        "status": "status",
        "task_status": "status",
        "due": "scheduled_date",
        "scheduled_date": "scheduled_date",
    }
    if not required_information.issubset(information_to_field):
        return None
    return frozenset(
        {"title", *(information_to_field[item] for item in required_information)}
    )
```

이는 `notes`라는 실패 단어만 막는 규칙이 아니라 **현재 formatter 능력 전체에 대한 completeness gate**다. 미지의 future typed 정보도 임의 생략하지 않고 기존 의미 작성 owner에게 돌려준다. typed 정보가 모두 지원되는 기존 title/status/due 요청은 기존 0-call 경로를 유지한다.

Source required_information은 사용자 표시 필드와 항상 1:1은 아니다. 다만 현재 State에는 별도 answer-field authority가 없으므로 unsupported Source 정보가 필요 없다고 formatter가 자의적으로 판단할 수 없다. 이 guard는 원문·근거를 가진 기존 작성 owner에 판단을 남기는 보수적 fallback이다. 이후 Source가 과도하게 넓은 정보를 선택한 문제는 별도의 Source owner 책임이며 여기서 삭제하지 않는다.

## 직접 회귀 테스트

`tests/unit/application/agents/planning/test_project_task_read_answer.py`에 다음 계열을 추가했다(실제 테스트에는 `task_identity`와 원래 mixed 정보 조합도 포함):

```python
@pytest.mark.parametrize(
    "required_information",
    [["notes"], ["body"], ["title", "notes"],
     ["status", "due", "notes"], ["unknown_future_information"]],
)
def test_task_read_answer__unsupported_information__uses_semantic_owner(
    required_information: list[str],
) -> None:
    result = project_task_read_answer(
        user_request="Return the requested Task information.",
        request_intent=_field_selecting_intent(required_information),
        evidence=[_structured_task()],
    )
    assert result is None
```

추가 control:

- title/status/due 각각과 실제 지원 alias 조합은 현재 결과/날짜-only/미완료 의미 그대로.
- 같은 Task Resource의 두 Source item 중 하나만 unsupported여도 전체 shortcut을 사용하지 않는다.
- Task notes가 Evidence에 존재하고 원문도 notes 요청인 실제 `outline_answer → compose_answer` 연결에서 fake semantic invoke가 notes를 포함한 답변을 반환하는지 확인한다. 예상 새 호출은 `planning.compose_answer` 1회이며 근거 reference는 기존 validation을 거친다.
- 그 연결 테스트에서 원본 RequestIntent와 Evidence가 수정되지 않았는지 확인한다.
- 기존 제목 또는 상태/예정일만 검증하는 fixture의 required_information에서 notes/task_identity를 제거해 입력과 목적을 맞추고, 기존 notes/task_identity 포함 입력은 별도 unsupported 회귀 테스트로 보존한다. Dataset/Gold는 변경하지 않았다.
- 분석/혼합 Resource/WRITE 요청은 기존 None 경로 유지.

검증 결과:

- 수정 전 notes/body/미지 필드·복수 Source·실제 compose 연결 반례: **8 FAIL / 58 PASS**. 현재 typed 요구를 생략하는 경계를 재현했다.
- 첫 제안에서 task_identity를 title alias로 둔 부분도 직접 반례 **3 FAIL / 66 PASS**로 확인한 뒤 mapping에서 제거했다. Source 의미를 formatter가 낮추지 않는다.
- identity handoff test는 기존 identifier sanitizer가 내부 Resource ID를 가리는 것을 확인했다. 따라서 실제 ID 공개 성공을 요구하는 assertion 대신 **semantic owner에 원본 Evidence가 전달됨, 제목으로 대체하지 않음, 기존 sanitizer 유지**를 검증한다. sanitizer/Product 공개 정책은 변경하지 않았다.
- 최종 Planning unit 및 연결·persistence/review-execution 검사 **239 PASS**, compiled Planning component **1 PASS**: 합계 **240 PASS**. Fake 경계 검사이지 실제 모델 업무 성공률은 아니다.
- 부모 검토에서 Planning unit 전체와 production agent subgraph component 전체를 함께 실행해 **279 PASS**를 재확인했다. 앞 검사와 중복되므로 합산하지 않는다.
- 변경한 Python 3파일 Ruff/Mypy, `git diff --check` PASS.

## 영향과 미검증

- 최소 수정 owner: `planning/project_task_read_answer.py`만. 두 production caller가 같은 helper를 소비하므로 별도 분기 수정은 필요 없다.
- Prompt/Schema/State/Node/Approval/실행 의미 변경: 0.
- 지원 필드 요청의 추가 호출: 0. 미지원 정보 요청에서는 기존 compose LLM 경로가 필요해 0→1 이상으로 증가할 수 있다(기존 repair 정책 유지). 실제 연결 fake test에서 status/due는 0, notes/task_identity는 `planning.compose_answer` 1회였다. Source owner가 보조 identity 정보를 포함하는 경우에도 이 보수적 fallback으로 호출이 늘 수 있다.
- 실제 LLM이 notes를 올바르게 답하는 성공률은 이 코드 검토로 증명하지 않았다.
- 현재 CORE-005 baseline은 이 수정 전 Product로 실행하며, 이 후보의 결과로 baseline을 덮어쓰지 않는다.
- 최종 Product 변경: formatter 1파일, Canonical 15에 범위 1행 정합화, 직접 테스트 2파일. Prompt/Schema/State/Node/Dataset/Gold/Approval/실행 계약 변경: 0.
- 실제 모델·Provider 호출 / 실제 Main Graph 재실행: 0. compiled fake component 검사만 수행했다.
- commit/push는 부모 작업에서 처리하며 이 하위 작업은 실행하지 않았다.
