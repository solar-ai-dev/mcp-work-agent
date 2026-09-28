# 064 — Task CREATE Route별 충족 여부 연결 후보

## 범위와 판정

- 검토 기준 Product HEAD: `9c080fe3` (`bff2af9b` Sufficiency binding 수정 포함).
- **evaluation-only 직접 연결 후보**이며 Production 적용 또는 실제 모델 의미 품질의 ADOPT 판정이 아니다.
- 새 파일: `scripts/route_task_satisfaction_candidate.py`, `tests/evaluation/test_route_task_satisfaction_candidate.py`.
- Product source / Product Prompt / 활성 Schema / manifest / checkpoint 변경: **0**.
- 실제 모델 호출 / Provider READ / WRITE / 새 Run 생성: **0**.
- Fake owner의 구조화 출력을 기존 scalar validator → 기존 action-necessity consumer → 실제 Planning selector에 전달했다. 기존 compiled WorkAnalysis 전체 실행이나 중복 의미 판단 성공률 검증은 하지 않았다.

## 확정한 최초 구조 손실

V3는 같은 `TASK/CREATE` capability라도 다른 사용자 결과를 별도 Output Route로 보존한다. Canonical 06 §3.4는 Route별 적용 여부를 authoritative 결과로, aggregate `action_necessity`를 compatibility 필드로 정의한다.

그러나 Task 충족 여부 producer 입력에는 frozen Output Route가 없고, 출력은 전역 `requested_work_status` 하나다. 따라서 Task 2개 중 하나만 이미 존재하는 상태를 표현할 수 없다. 이후 `assess_action_necessity`의 복수 Task CREATE guard는 이 모순을 올바르게 거절하고 있다. guard 삭제나 전역 결과 복제는 해결이 아니다.

근거:

- `application/agents/work_analysis/assess_requested_task_satisfaction.py`: `REQUESTED_TASK_SATISFACTION_OUTPUT_SCHEMA`, `_prompt_input`, `_validate_and_materialize`.
- `adapters/langgraph/subgraphs/work_analysis/projections/detect_duplicate_conflict_candidates_projection.py`: frozen Route 대신 `task_duplicate_review_required` boolean만 전달.
- `application/agents/work_analysis/assess_action_necessity.py`: 복수 Task CREATE guard; `SATISFIED`/`UNDETERMINED`의 deterministic lowering.
- `application/agents/work_analysis/contracts/work_analysis_result.py`: 이미 `RouteActionNecessityV1`과 `route_action_necessities`가 존재.
- `application/agents/planning/select_required_output_routes.py`: exact frozen Route coverage를 검증하고 `REQUIRED`만 선택. `UNDETERMINED`를 재해석하지 않는다.

## 후보 계약

```text
frozen Task CREATE Routes + 확정된 WorkUnit binding
→ Route별 existing RequestIntent projection
→ 공유 Task 관측 pool을 한 번 전달
→ 1회 owner 호출: {route_assessments: {closed_route_id: existing_scalar_assessment}}
→ Route별 기존 scalar validator
→ Route 하나씩 기존 action-necessity consumer
→ 기존 RouteActionNecessityV1[]
→ 기존 Planning selector
```

모델 출력은 frozen Task CREATE Route를 정확히 한 번씩 포함하는 closed object다. Route 생성/삭제와 새 WorkUnit 판단은 수행하지 않는다. RequestIntent의 조건·금지·Output은 기존 `project_request_intent_for_work_units`로 투영하며 전체 Goal을 새 의미로 쓰거나 다시 생성하지 않는다.

기존 projection은 `goal`과 `completion_conditions`를 원본 그대로 보존하므로 Route-local 입력에도 다른 업무의 전체 Goal/완료조건이 남는다. typed Constraint/Output/WorkUnit 귀속 검증은 통과했지만, 실제 모델이 이 전역 문맥을 보고 다른 업무의 충족 상태를 섞지 않는지는 **미검증**이다. 본 후보는 이를 숨기려고 Goal을 새로 쓰거나 문자열로 분리하지 않는다.

공유 READ는 재실행하지 않는다. `source_state`의 관측 pool, facts, Evidence를 모델 입력에 각각 한 번 전달하고 각 Route는 기존 `RetrievalSourceStatusV1.work_unit_ids`로 해당 Source Route를 참조한다. Route별 closed fact/candidate/evidence membership는 이 접근 범위에서 파생한다. **이 membership는 접근 가능한 관측이라는 뜻이지 특정 Task가 해당 업무를 이미 만족한다는 의미 증명이 아니다.** 만족 여부는 owner 출력과 기존 검증 경계에 남긴다.

이는 현재 존재하는 SourceStatus WorkUnit binding과 current full Task candidate pool을 재사용한 것이며 새 조회 범위를 만들지 않는다. 이번 direct gate의 READ 호출 증가량은 **0**이다. 실제 Provider dispatch가 포함된 compiled 전체 경로의 비용을 측정한 결과는 아니다.

### producer → validator → state → projection → consumer → revision

| 경계 | 현재 Product | 평가 후보 / Production 이관 시 최소 필요 변경 |
| --- | --- | --- |
| Producer | 요청 전체의 Task 충족 상태 1개 | frozen Task Route closed set 전체를 같은 호출에서 독립 평가 |
| Validator | scalar schema + 실제 관측·전체 조회 검증 | outer exact Route coverage + Route별 기존 `_validate_and_materialize` 재사용 |
| State | `DuplicateConflictAssessmentV1` scalar와 fact 관계 후보 혼합 | Route→scalar assessment map을 WorkAnalysis local typed 계약에 명시; fact↔fact 관계 authority는 유지 |
| Projection | whole intent와 Task review 필요 boolean | Route ID/WorkUnit binding + Route-local 기존 semantic items + 공유 관측 pool |
| Consumer | 2개 Task CREATE면 fail-closed | 후보는 각 Route에 기존 consumer 호출; Production에는 해당 map 소비와 잔여 model routes의 기존 batch 호출 정합화 필요 |
| Planning | `RouteActionNecessityV1[]` 소비 | **변경 불필요**. 현재 selector가 혼합 상태와 독립 identity를 표현 가능 |
| Revision owner | Task satisfaction owner의 bounded semantic revision | Route-keyed raw/failure field path로 동일 owner 및 기존 budget 안에서 revision; 후보는 fake direct gate여서 실제 repair를 실행하지 않음 |

`SATISFIED`는 해당 Route만 `NOT_REQUIRED`, `UNDETERMINED`는 해당 Route만 미확정으로 유지한다. `NOT_SATISFIED`를 `REQUIRED`로 강제하지 않는다. 사용자 조건이 false이면 기존 필요성 owner가 관측을 인용해 `NOT_REQUIRED`를 선택할 수 있다.

## 직접 검증

- 신규 direct tests: **26 PASS**.
- 기존 `assess_action_necessity`, `assess_requested_task_satisfaction`, `assemble_work_analysis`, `select_required_output_routes` unit tests 22개와 합계: **48 PASS**.
- Ruff: 신규 두 Python 파일 PASS.
- Mypy: 후보 script PASS. 두 파일 동시 검사 시 기존 import된 `tests/support/fakes/llm.py:287,293`의 `list(object)` 오류 2개가 관측되어 해당 타 작업 파일은 수정하지 않았다.
- 최초 테스트 작성 때 fixture의 Source `required_information`에 대응하는 Constraint projection이 없어 24개가 fixture validation에서 실패했다. 테스트 fixture에 같은 정보와 같은 WorkUnit binding을 정합화한 뒤 통과했다. Product validator나 assertion은 완화하지 않았다.

확인 항목:

- Task 2개 중 `SATISFIED`/`NOT_SATISFIED` 혼합: 하나만 Planning에 남고 정확한 Route와 WorkUnit identity 유지.
- 조건 false인 `NOT_SATISFIED`: `REQUIRED` 강제 없음.
- `UNDETERMINED`: 기존 Planning 거절 유지.
- 두 Task 모두 충족: necessity LLM 호출 0.
- missing/unknown Route, 필수 status 누락, invalid status, unknown fact/candidate/evidence 거절.
- 다른 WorkUnit 전용 Source의 candidate를 참조하면 거절.
- Task 관측 불완전, 관측 count/pool 불일치, matched observation 없는 `SATISFIED`, Task가 아닌 matched fact를 기존 validator가 거절.
- unknown WorkUnit/invalid frozen Route ID는 inference 이전 거절.
- 요청의 Route-local 조건/금지와 입력 원본 불변.
- 현재 Product의 복수 Task CREATE guard가 그대로 남아 있는지 반례 고정.

### 호출 비용: 최적화 완료로 보고하지 않음

| Fake owner 결과 | satisfaction 호출 | 기존 necessity 호출 | 합계 |
| --- | ---: | ---: | ---: |
| SATISFIED + NOT_SATISFIED | 1 | 1 | 2 |
| SATISFIED + SATISFIED | 1 | 0 | 1 |
| UNDETERMINED + NOT_SATISFIED | 1 | 1 | 2 |
| NOT_SATISFIED + NOT_SATISFIED | 1 | 2 | 3 |

현재 Product의 복수 Task 경로는 guard로 실패하므로 이 수치를 Product 성능 개선률로 환산하지 않는다. 후보는 기존 scalar consumer를 안전하게 재사용하기 위해 Route별로 호출한다. 따라서 아직 결정되지 않은 N개 Route에 최대 N번 necessity 호출이 발생한다. 이를 한 호출의 closed Route batch로 묶는 것은 채택 전 계약 이관 범위이며 이번 prototype에서는 구현하지 않았다. 토큰·지연은 fake 값이므로 실제 모델 수치로 보고하지 않는다.

## Production migration 범위와 미검증

1. `work_analysis_candidates.py`, WorkAnalysis local state, Task satisfaction producer/output schema와 input projection, node/graph 호출·초기화·budget/revision 처리를 atomic하게 이관해야 한다. 전역 scalar와 Route map을 동시에 live authority로 두지 않는다.
2. `assess_action_necessity`는 validated map으로 SAT/UNDET Route를 lowering하고 남은 Route를 기존 필요성 owner에 한 번 전달하도록 연결할 수 있다. 이는 새로운 의미 owner나 Node 추가가 아니라 기존 호출 계약 이관이다. 이번 후보에서 이 최적화는 미구현이다.
3. `assemble_work_analysis`의 duplicate override 감지는 현재 전역 scalar를 사용한다. Route별 해당 matched candidate만 참조하도록 이관하고 기존 `PolicyConfirmationReceiptV1`의 current `based_on`/decision-context 검증을 그대로 유지해야 한다. 선택적으로 어떤 duplicate만 override 승인할지 새 정책을 이 후보가 정하지 않는다.
4. `WorkAnalysisResultV2.route_action_necessities` 및 현재 Planning selector는 필요한 표현을 이미 보유한다. Approval → Execution → Verification/Recovery, READ scope, Task duplicate policy, receipt 의미는 변경하지 않는다.
5. 기존 persisted WorkAnalysis local checkpoint에는 scalar가 있다. 현재 graph resume boundary는 `resume-contract-v3`이고 invocation이 graph version 일치를 검사한다. 기존 scalar를 여러 Route에 복제하거나 Route mapping을 추측하면 안 된다. 정확히 한 frozen Task CREATE인 기존 결과만 기계적 매핑 가능성을 검토할 수 있으며, 다중 Route는 기존 checkpoint/budget 기반 owner 재진입 또는 명시적 graph/schema compatibility 경계가 필요하다. 실제 migration/resume는 **미구현·미검증**이다.
6. Canonical 06/15, Task satisfaction Prompt input/output contract/version/hash, manifest와 관련 테스트를 함께 갱신해야 한다. 이번에는 Product Prompt를 수정하거나 새 Prompt slot을 활성화하지 않았고 fake `evaluation.route_task_satisfaction` reference만 사용했다.

결론: **global scalar의 구조적 모순과 Route-local map의 bounded 직접 연결 가능성은 확인**했다. 실제 모델의 Task 충족 판단 안정성, compiled 전체 WorkAnalysis와 재개, 다중 Route override 정책 및 비용 최적화가 닫히기 전에는 Production migration 완료나 전체 업무 성공으로 표시하지 않는다.
