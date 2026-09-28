# 064 — v35 Work selector codec의 fresh-only Product 이관

## 판단과 변경 범위

기준 HEAD: `8eb1d260d01803fab8a9212bc52d55a6dc66920d`.
기존 모델 비교·raw 재검증에서 확인한 공백만 다른 selector의 결속을 Product의 fresh
`request.identify_goal` supporting Work owner에만 이관한다. 이는 **selector admission
계약 확장**이다. exact provenance의 의미를 완화하거나 업무 분해를 교정하는 변경은 아니다.
Canonical 06 Requested Work binding 및 15 §0.3을 먼저 정합화했다.

- exact unique match 우선. exact match가 여러 개면 fallback 없이 거절한다.
- exact match가 없을 때만 Unicode White_Space 25개를 제외한 비교 view에서 모든
  non-whitespace codepoint가 동일한 유일한 연속 원문 구간을 선택한다.
- 최종 offset/source_text는 원문 slice다. 겹치는 구간·공백-only selector·반복 위치·
  대소문자·문장부호·zero-width/BOM·Unicode 정규화 차이를 새로 허용하지 않는다.
- Work 개수·순서 의미·관계·Source·Output·금지는 재판단하지 않는다. 구조적으로 유효한
  금지문장의 별도 Work 승격도 이 codec이 합치거나 의미 PASS로 처리하지 않는다.

## Owner와 호환성

| 경계 | 담당 / 변경 |
| --- | --- |
| Producer | 기존 `identify_requested_work` LLM. 원문, PromptRef, Prompt 본문, wire schema 동일 |
| Admission | physical `identify_goal_node`가 fresh임을 확인한 내부 옵션만 허용 |
| Validator/materializer | owner-local `bind_work_request_span` 및 기존 Work 조립. 최종 exact Typed validator 유지 |
| State | 기존 `RequestedWorkDefinitionV1`, provenance offset/text, unit ID와 relation shape 그대로 |
| Projection/consumer | 기존 Goal 및 atomic semantic owner, 최종 RequestIntentV3, downstream binding 그대로 |
| Revision/resume | candidate revision, confirmation, reconsideration은 기존 exact-only. 확정 Work 재작성 없음 |

기존 Goal/RequestIntent가 있거나 confirmation/reconsideration이 전달된 physical invocation은
새 admission을 사용하지 않는다. LangGraph의 nested restart에서 State에 아직 confirmation이
없더라도 `ConfirmationAwareLLMRuntime`의 current-Run pending 상태를 read-only getter로
확인해 제외한다. getter는 응답을 소비·변경하지 않고 다른 Run의 pending과 격리된다.
budgetless/default supporting caller와 prior 없는 confirmation도 exact-only다.

Prompt/schema/manifest/persisted validator/Graph topology/State shape/권한·승인·Execution 계약
변경 0. checkpoint나 graph/schema version 승격 없음. LLM 호출 및 repair 예산 변경 0.
정확한 공백-only unique selector를 기존 default caller가 허용하던 동작도 유지한다.
새 fresh admission에서만 이를 거절한다.

## 직접 검증

다음 7개 파일의 focused pytest: **193 PASS** (단일 프로세스, 1.87초).

- `tests/unit/application/agents/request_understanding/test_identify_goal.py`
- `tests/unit/application/agents/request_understanding/test_identify_requested_work.py`
- `tests/unit/application/agents/request_understanding/test_work_span_codec_adoption.py`
- `tests/unit/adapters/langgraph/test_confirmation_llm_runtime.py`
- `tests/unit/adapters/langgraph/test_work_span_codec_fresh_gate.py`
- `tests/evaluation/test_production_work_span_codec_candidate.py`
- `tests/evaluation/test_production_work_ref_candidate.py`

신규 Product gate는 evaluation validator patch 없이 actual compiled RU의 Work 호출에
공백 차이 fake output을 전달했다. 기존 5 wire calls 및 Work 원문 입력이 유지됐다.
단 이는 deterministic 연결/호환성 검증이며 새 실제 모델 의미 품질 측정이 아니다.

첫 실행의 신규 테스트 7개는 명시적 fake PromptRef 누락으로 DRAFT release gate에서
실패했다. Product gate를 변경하지 않고 기존 직접 테스트와 같은 명시적 PromptRef
fixture를 제공한 뒤 재검증했다. 최종 집계에 실패를 숨기거나 모델 Trial을 교체하지 않았다.

동결 v34/v35 candidate script/runner는 수정하지 않았다. 이전 후보의 compiled test에만
historical exact-only caller fixture를 명시했다. v34는 새 내부 옵션을 제거한 이전
supporting-operation API fixture도 사용한다. 이 후보 테스트를 새 Product 동작의 성공
근거로 다시 사용하지 않고 별도 Product fresh gate로 검증한다.

변경 파일 Ruff PASS. `identify_requested_work.py`, `bind_work_request_span.py`의
`mypy --follow-imports=silent` 2파일 PASS.

## 기존 실제 raw의 구조적 이관 적합성

새 모델 호출 없이 다음 서로 다른 **27 call record**를 비교했다. 재사용 raw를 신규 모델
성공률이나 반복 Trial로 합산하지 않는다.

| 근거 | FIRST 수 | 기존 exact-only 허용/거절 | 동결 v35 ↔ Product Typed 결과·hash 동일 |
| --- | ---: | ---: | ---: |
| `064-work-span-codec-v35-replay/report-unicode-whitespace.json`이 가리키는 이전 raw | 21 | 14 / 7 | 21 / 21 |
| `064-work-span-codec-v35-connected-t1/CASE-CORE-*/{production,work-span-codec-v35}/calls.json` | 6 | 2 / 4 | 6 / 6 |

원문 input hash, 현재 Work PromptRef, wire schema, 실제 RETURNED/FIRST 여부를 확인했다.
27개 원본 calls 파일의 전후 hash는 동일하다. exact-only 경로는 기준 HEAD의 원본 validator와
accept/reject 및 Typed 결과/오류까지 27/27 동일했다. 추가 8개 compatibility edge
(공백-only, exact 반복, 공백 변형, overlap, 빈 schema 항목 등)도 원본과 동일했다.

비교 row의 Typed 결과 aggregate SHA-256:
`7003b9e6c9cd77de23c5c1cf51ff2c1133b4afc4799a1d78628d9c9a6ad270ad`.

이 표는 codec 이관의 구조적 동일성이지 27개 업무의 성공 판정이 아니다. 후속 Source,
Output, 금지, Work 분해 적합성 및 Retrieval/Planning의 실제 성공은 별도 검증 대상이다.

이번 이관 작업의 모델 호출 0 / 외부 Provider 호출·변경 0.
커밋·push는 root의 최종 diff 검토 이후 수행하며, 관련 없는 동시 변경은 보존한다.
