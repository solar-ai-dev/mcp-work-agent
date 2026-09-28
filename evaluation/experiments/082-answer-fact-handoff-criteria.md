# 082 — 저장된 fact selection의 실제 Planning 연결 gate

## 목적과 동결 범위

081의 독립 `planning.compose_answer` 후보 FIRST 4개가 만든 `items[{evidence_ref, field}]`를
새 모델 호출 없이 실제 compiled Planning의 consumer에 연결한다. 정답 field를 생성하지 않고
저장된 선택만 재사용한다. 081 원 raw·점수·실험 조건과 Product 활성 경로는 수정하지 않는다.
이것은 새로운 모델 trial, Canonical 92 점수 또는 업무 성공률 측정이 아니다.

- 입력: `evaluation/results/081-answer-fact-selection-t1/raw.json`.
- 원 raw SHA256: `3e3c20e0f8ee4167adaecce95bd1567f21f9cf07b4a94662006fc2759dead390`.
- 실제 CORE005 lookup의 두 selection 및 synthetic completed control의 두 selection을 모두 보존한다.
- 각 row의 원 payload/input/response와 hash를 검사하며 081 Product source와 renderer source는 동일해야 한다.
- 새 LLM·Provider 호출 0, 새 Run/DB 기록 0. 결과 파일은 전용 디렉터리에 최초 한 번만 만든다.

## 실제 authority와 component 경계

CORE005는 067 DB의 정확한 pre-Planning checkpoint를 read-only `mode=ro`, `query_only=ON`,
`pickle_fallback=False`로 읽는다. namespace/id/blob hash/DB hash를 고정하며 최신 checkpoint나
Prompt의 축약된 collection을 역추정하지 않는다. 과거 DB·Run을 재개하거나 변경하지 않는다.

- DB SHA256: `5838f3d98b1caedc78a44d195d4cca7fcde693fc483aacf5432955c9a8987f70`.
- namespace: `planning:75e22c70-973f-d965-df2c-8038f025dc72`.
- checkpoint: `1f1bb599-42f5-6850-8000-d6b5ac6f3e5e`.
- blob SHA256: `f86e3ad415149615f8f0a79ef1efd172df1dc8db2ee7abf6dece2d08687a0d44`.

이 checkpoint의 확정 RequestIntent/ToolRoutePlan/RetrievalResult/WorkAnalysis와 081 Evidence 및
snapshot을 새 in-memory component Run에 복사한다. historical Run authority를 새 Run이라고
주장하지 않는다. Synthetic completed control은 역사 checkpoint가 아니라 081에서 명시한
READ projection과 ANSWER route fixture를 사용한다. 이 control의 upstream 분해·Route 선택은
측정 대상이 아니다.

| 구간 | 실제 owner와 검사 |
| --- | --- |
| 입력·개요 | 실제 `PlanningSubgraph`의 outline → compose Node/projection. 새 Graph를 만들지 않는다. |
| 원 snapshot | 실제 `_project_runtime_inputs`가 `RunScopedEvidenceStore.resolve_resource_snapshot`을 현재 component Run/handle/version으로 호출한다. 실제 resolution 결과만 renderer가 사용한다. |
| 선택·렌더 | injectable semantic boundary에서 저장된 selection을 081 renderer에 전달. 현재 compose input과 원 081 input은 전체 exact equality를 요구한다. |
| 답변 검증·State | 기존 Product `compose_answer` validator/sanitizer와 compiled `final_result`를 사용한다. |
| Artifact | 동일 Product Planning `_materialize_answer`로 새 component artifact meta를 붙인다. Supervisor merge를 수행한 것으로 주장하지 않는다. |
| Terminal | 실제 `build_terminal_commit_intent`/`BuildTerminalMessageHandler`로 ANSWER_DRAFT 본문 exact 보존·terminal composer 0을 확인한다. fact snapshot은 명시적 component PLANNING 상태이며 Domain DB 사실이 아니다. |

실제 Main route dispatch, Supervisor merge, DB terminal commit, UI delivery, durable checkpoint
호환성 및 자동 eligibility는 범위 밖이다. Terminal intent `SUCCESS`는 주입한 component 상태의
제품 구조 결과이며 평가의 semantic PASS가 아니다.

## 성공·실패·반례 기준

정상 selection은 compiled compose 경계를 정확히 1번 소비하고, 081 renderer가 만든 draft가
기존 Product validator → final_result → terminal message에 유지되어야 한다. 저장된 081 draft는
보존 비교에만 사용하며 답변 생성 입력이나 expected-value 공급자로 사용하지 않는다.

현재 outline/projection이 원 입력을 바꾸면 첫 다른 top-level field를 실패로 기록한다.
hash를 맞추기 위해 개요·Evidence·collection을 덮어쓰지 않는다. 승인되지 않은 ref, stale/hash가
다른 snapshot, 동일 Resource의 conflicting version, 다른 Run에만 존재하는 snapshot은 답변
생성 성공으로 취급하지 않는다. 빈 선택은 답변 미생성이며 정상 미발견으로 바꾸지 않는다.

필수 field 누락은 Product 구조 validator를 통과할 수 있다. 이 경우 구조 통과와 의미 불충분을
구분하고 자동 semantic PASS를 부여하지 않는다. 직접 테스트는 누락을 허용된 품질로 선언하는
것이 아니라 이 한계를 명시적으로 고정한다. 모든 replay의 의미 판정은 `NOT_EVALUATED`다.

시작·종료 HEAD, 원 raw/DB, Product/helper 및 gate support 파일의 hash가 달라지면 전체 gate는
FAIL이다. 원 raw는 수정하지 않고 별도 082 artifact에만 결과를 저장한다.

## 실행과 미검증

```text
python scripts/verify_answer_fact_handoff.py --result-dir evaluation/results/082-answer-fact-handoff-t1
python -m pytest tests/evaluation/test_answer_fact_handoff.py
```

이 문서는 gate 실행 전 범위 정의다. 모델 선택의 일반화, 여러 Resource·분석·요약·복합 요청,
올바른 필드 선택률, Production migration/Prompt activation은 증명하지 않는다. 15 EVALUATION의
비활성 lookup 출력 계약만 사용하며 Product Prompt/Schema/Registry는 변경하지 않는다.
