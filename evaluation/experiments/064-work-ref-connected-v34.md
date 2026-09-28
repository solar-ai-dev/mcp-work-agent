# 064 v34 — fresh Work owner의 request-local 위치 결속 후보

## 목적과 현재 상태

비활성 **EVALUATION 전용** 후보다. Product 코드·활성 Prompt·manifest·Graph·persisted State는 변경하지 않는다. 실제 모델/Provider 호출은 **0회**다. 새 평가 실행 예산과 Case 목록은 아직 확정하지 않았다. 직접 fake-wire tests는 다른 모델 batch 종료 후 단일 프로세스로 실행했다. 구조 테스트 성공을 업무 분해의 의미 PASS나 Canonical 92 점수로 사용하지 않는다.

관측된 실패는 fresh `identify_requested_work`가 원문 부분 문자열을 재생성하면서 띄어쓰기를 바꾸어 exact provenance 검증에서 중단되는 것이다. 이번 후보는 업무 판단을 고치는 규칙 대신 **같은 한 호출의 표현만** 바꾼다. 전체 원문은 그대로 입력하고, `\S+` 토큰의 request-local ID를 함께 제공한다. 모델은 업무별 `start_token_id`/`end_token_id` 구간을 선택하고, 원문 문자열과 offset은 코드가 해당 위치에서 그대로 결속한다. 토큰 양 끝을 포함하며 내부 공백·개행도 원문 그대로 보존한다.

파일:

- `scripts/production_work_ref_candidate.py`
- `tests/evaluation/test_production_work_ref_candidate.py`

## Owner와 계약 범위

| 경계 | 기존 계약 / 후보 책임 |
|---|---|
| Producer | RU의 기존 fresh `identify_requested_work` supporting operation 한 번을 재사용한다. 업무 경계만 모델이 고른다. Source/Output/Effect/Constraint/Relation은 생성하지 않는다. |
| Validator | 닫힌 token ID Schema, 올바른 구간 순서, 겹침 금지, 현재 요청의 실제 offset·text 일치만 검사한다. 선택되지 않은 의미를 만들어 넣거나 업무 개수를 강제하지 않는다. |
| State | 기존 `RequestedWorkDefinitionV1`: `work-N`, exact `USER_REQUEST` provenance, 초기 빈 relations. `RequestIntentV3`의 item-owned `work_unit_ids` 계약은 동일하다. |
| Projection | `user_request` 전체 + 해당 원문에서 생성한 `request_tokens`만 Work 호출에 제공한다. 출력 위치를 deterministic하게 기존 typed provenance로 바꾼다. 원문 `.find()`로 재검색하지 않는다. |
| Consumer | 기존 Goal/Source/Output/금지 owner와 downstream handoff는 기존 Work State를 소비한다. 다른 owner 입력·Tool/Query/Approval/Execution은 변경하지 않는다. |
| Revision | 실제 Product structured router의 기존 1회 schema repair와 unaffected-field guard를 사용한다. 새로운 semantic revision이나 fallback 분해는 없다. 구간 구조 검증 실패는 실패로 보존한다. |

Canonical 근거는 `06-agent-workflow.md`의 RequestIntentV3/WorkUnit binding, `15-agent-capability-failure-prompt-contract.md`의 RU 책임과 Prompt assembly 경계다. Product owner가 현재 요구하는 생성형 `request_spans` 출력만 EVALUATION 슬롯 `evaluation.request_understanding.identify_requested_work_refs`의 동적 닫힌-ID Schema로 교체한다. Prompt는 기존 span 생성 지시 한 문장만 ID 구간 선택으로 정합화하고 나머지 업무 경계·금지 책임 문구는 그대로 둔다. 원문/반례별 추가 규칙이나 few-shot은 없다.

후보 PromptRef는 별도 source hash와 input/output version을 가진다. Product registry/activation을 바꾸지 않으며 정상 `assemble_prompt(..., EVALUATION)`를 거친다. 실제 router의 model/runtime 선택, provider dispatch budget, schema repair와 wire observer는 유지한다. FIRST/repair는 기존 observer에, router 검증 후 결과와 materialized State는 별도 event에 기록한다.

fresh RU physical invocation에만 scoped owner를 설치한다. 기존 Goal/RequestIntent·confirmation·reconsideration 경로는 원래 owner를 유지한다. 기존 GoalOutput evaluation bridge와 함께 사용할 수 있지만 둘의 의미 authority는 합치지 않는다. persisted checkpoint 또는 resume migration을 수행한 후보가 아니다.

## 055/062와 같고 다른 조건

`055-two-stage-exact-span-ref-v5.md`에서는 exact span 결속이 19/24에서 24/24로 개선됐으나 의미 결과는 14 PASS/10 PARTIAL/0 FAIL에서 10/13/1로 악화돼 REJECT였다. 특히 금지를 별도 Work로 승격하고 공통 대상 identity·요청 동사를 누락하는 회귀가 있었다. **위치 결속 성공은 의미 보존 성공이 아니다.**

이번에는 당시 Stage 1의 optional Source/조건 의미 동시 생성과 Stage 2 재서술을 반복하지 않는다. 현재 Production Work operation은 이미 업무 경계와 provenance만 소유한다. 이 책임 축소가 달라진 비교 조건이며, 개선을 보장하지 않는다.

062의 `_request_tokens`와 `_requested_work_ref_schema`를 재사용한다. 단 기존 문자열-span adapter로 되돌리지 않는다. Product string validator의 `find(exactly once)`는 같은 문구가 서로 다른 위치에 반복될 때도 거절하므로, 후보 owner가 offset을 직접 기존 typed validator에 전달한다. 동일 문구·서로 다른 offset은 허용하고 동일 offset 중복/겹침은 거절한다.

## 직접 검증과 남은 의미 검증

작성한 직접 controls: Unicode/공백/개행 보존, repeated literal의 서로 다른 occurrence, 읽기 순서 ID, 역방향·겹침·닫힌 집합 밖 ID·빈 출력 거절, 실제 router/assembly/budget/repair guard, 기존 PromptRef 유지, full request 전달, invocation/Run 격리, GoalOutput bridge 조합, prior-state resume 및 scope 종료 원복.

실제 직접 검증:

- `pytest tests/evaluation/test_production_work_ref_candidate.py -q`: **19 PASS**.
- 위 파일과 기존 `test_production_goal_output_candidate.py`를 함께 실행: **37 PASS**. 실제 Product `identify_goal` compiled gate의 기존 5-call fake-wire 경계도 유지한다.
- Ruff 두 파일 PASS.
- 후보 파일 mypy `--follow-imports=silent`: PASS. 일반 mypy는 기존 imported `evaluation/request_semantic_authority_candidate.py:843`의 `Mapping` indexed assignment 오류 1건으로 FAIL이며 해당 공유 파일은 수정하지 않았다. 후보 자체 typing 성공을 전체 import graph 성공으로 표시하지 않는다.
- 위 검증에서 발견된 후보 코드 결함은 없으며 모델/Provider 호출과 Product 변경은 0이다.

직접 테스트는 정확한 업무 개수나 특정 decomposition을 Gold로 만들지 않는다. 여러 구조가 계약상 허용됨과, 빠진 공통 identity를 코드가 임의 복원하지 않음을 확인한다. 다음은 **실제 모델에서 아직 미검증**이다.

- 055의 금지 표현 별도 Work 승격 및 공통 identity 누락 회귀.
- 복합/단순 업무 경계, 결과 소비 관계, 과분해/누락.
- 공백 없는 긴 한국어 요청이나 단일 토큰 내부에서 나누어야 하는 경계. 현재 whitespace-token 구간은 토큰 내부 offset을 선택할 수 없다.
- 위치 참조 입력 증가가 의미 선택·토큰·지연에 미치는 영향.
- 실제 compiled RU→Tool Route 및 이후 Retrieval/Planning 업무 성공.

추가 Node/LLM call은 없다. 호출당 입력 token table은 증가한다. 실제 호출·토큰·지연 변화는 추정 PASS로 채우지 않고 후속 고정 비교에서 측정한다. 현재 모델 실행 0, 외부 Provider READ/WRITE 0, Product 활성화 0이다.
