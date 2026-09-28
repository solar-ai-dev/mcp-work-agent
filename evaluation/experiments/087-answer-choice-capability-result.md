# 087 — 미지원 입력의 기존 authority 보존, 신규 모델 호출 없음

실행 SHA `4d0e1f16`. **exact-wire 재사용 gate9/9 PASS**, 모델/Provider/Graph 호출0.
신규 모델 의미 점수나 새로운9회 성공이 아니다. 지원 입력8개의 기존 모델 응답과,
지원하지 않는 Calendar의 기존 Product 응답1개가 각각 정확히 같은 전송 계약에 결속됐다.

## 실패 → 수정 → 확인

085는 후보를 모든 compose에 적용해 메모 조회2회는 맞았지만 Calendar2회에서
오전10~11시를 오후10~11시로 바꿨다. 087은 시각을 후처리하지 않는다. 검증된 사실
참조 선택지를 제공할 수 없는 입력에는 기존 compose Prompt/schema/wire를 그대로 둔다.
이는 모델 응답을 본 후 재시도하는 fallback이 아니라 dispatch 전 capability 선택이다.
Task snapshot이 있다는 이유로 직접 조회라고 분류하지 않으며, 참조가 가능해도 PROSE를
계속 허용한다. 키워드·Case ID·정답·시간 규칙을 사용하지 않는다.

| 범위 | 확인한 것 | 실제 의미 결과의 출처 |
| --- | --- | --- |
| CORE005 / completed / 정리, 각2개 | 084의 실제 wire bytes·input·schema 그대로 | 084의 기존6 PASS |
| 별도 Task 메모2개 | 085의 실제 wire bytes 그대로, PROSE도 허용 | 085의 기존2 PASS |
| Calendar1개 | 현 Product 재조립→065 실제 baseline bytes와 exact equality | 065의 기존1회 답변: 오전10~11시 / 한빛회의실 |

Calendar baseline은1개만 사용했다. 이를2회 반복 실행 또는 신규 후보 PASS2개로
표시하지 않았다. 085의 Calendar FAIL2개와 raw hash는 그대로 보존한다. 현재 후보가
새 조건에서도 항상 맞는다는 주장은 하지 않는다. 이 gate는 무모델로 불필요한 변경 범위를
제거하고 검증된 wire를 연결한 근거다.

Source snapshot 권한은 기존 caller가 먼저 확인해야 한다. catalog 없음만으로 stale/
foreign-Run과 정상 미지원을 구분할 수 없으므로 helper를 authorization으로 사용하지 않는다.
이번 runner도 exact snapshot을 선행 확인하며 예외를 정상 baseline으로 삼키지 않는다.

## 실제 검증

- 모델0/Provider0, 입력·역사 raw·Product/helper hash 불변, gate9/9.
- 직접·인접135 tests PASS. 변경한 세 파일 Ruff/mypy PASS.
- 모델 없는 단위검사는 unsupported wire 보존, input drift 거절, 후보의 두 branch 유지,
  snapshot/catalog 예외 전파, 저장 wire 불일치·stale snapshot 거절을 포함한다.
- 086의 실제 compiled Planning→terminal gate6/6은 별도 근거다. 이 wire gate의9개와
  합산하지 않는다. 086 또한 새 모델 실행이나 실제 MainGraph 성공은 아니다.
- raw: `evaluation/results/087-answer-choice-capability-t1/raw.json` (local ignored).
- raw SHA256 `448558ac7b5b46ce53233f6e3c4c96dcc0fbd7274fd3323be3b5c084878e98b8`.

## 다음 actual-router 연결 범위 (#288/#300)

현재 상태는 **개발 기준 후보 채택 / Product 미반영**이다. 확정 사실의 값은 snapshot
renderer가, 표현 방식·필드는 compose owner가 고르는 구조를 유지한다. 다음 변경은
규칙 추가가 아니라 현재 private snapshot을 실제 등록된 추론 경계에 전달하는 것이다.

| 경계 | 현재 owner | 최소 연결안 / 보존할 계약 |
| --- | --- | --- |
| producer | Retrieval의 `put_resource_snapshot` | current Run/handle/version을 그대로 유지 |
| validator | `resolve_task_calendar_snapshot` / `project_task_calendar_source_snapshots` | hash·field·identity 검증 유지, 실패를 미지원으로 숨기지 않음 |
| state / projection | Planning `_project_runtime_inputs` / compose projection | snapshot은 private working input. LLM Prompt input에 추가하지 않음 |
| schema / rendering | Planning semantic owner | validated Evidence/outline와 같은 snapshot으로 closed pair 생성·선택값 materialize |
| dispatch | Planning `_semantic_invoker` → 기존 `llm_runtime.infer` | compose node에서 private snapshot 인자를 명시 전달. 기존 2인자 semantic invoker·budget·관측 유지 |
| consumer | 기존 `_validate_answer_candidate` → `_materialize_answer` → terminal | 기존 AnswerDraftCandidate/부분범위·citation·sanitize 및 terminal body 보존 |
| revision | 기존 compose validation/repair owner | `base_projection` / `COMPOSE_ANSWER_PROSE_INVALID` 기존 repair schema 경로 유지 |

구체적으로 현재 compose node는 `working`에 snapshot을 가지고 있지만 `_semantic_invoker`
closure는 원 State만 받는다. private keyword 인자로 해결 가능한 범위이며 새로운 State
artifact·Graph Node·공유 snapshot cache가 필요하다는 근거는 없다. Source snapshot을
출력 schema용 sidecar로 쓸 때도 caller authority가 유지돼야 한다.

union은 기존 answer-draft-v2 출력 계약과 다르므로 정직한 PromptRef/output contract
version/manifest/hash 정합화가 필요하다. 지원하지 않는 입력의 기존 Prompt/schema,
semantic repair, 기존 persisted Run의 profile과 activation DRAFT/release gate를 유지해야
한다. 현재 fake-invoke/replay는 이 registered router 경계까지 검증하지 않았다.

이후 고정된 소수 연결 입력에서 실제 router·budget·첫 응답·repair를 분리 검증하고,
유효하면 기존 성공·복합/부분 답변을 포함한 범위로 확대한다. 현재 결과로 Canonical92나
전체 LangGraph 안정화 완료를 선언하거나 출시 gate를 우회하지 않는다.

Product source/활성 Prompt/Schema/State/Node 변경0, Dataset/Gold 변경0,
실제 Provider READ/WRITE/SEND0. 사용자에게 새 제품 의미 결정을 요청할 blocker는 발견되지 않았다.
