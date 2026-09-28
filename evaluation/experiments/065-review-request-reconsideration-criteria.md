# 065 — Review가 요청 의미의 반증을 owning RU로 전달하는 후보

## 근거와 비교 경계

기준 Production `1c37ad3a`와 활성 Prompt는 유지한다. 064 Source producer v41~44를
새 표현으로 반복하지 않는다. 별도 확인한 Review→owner 반환 경계의 공백을 다룬다.

기존 CORE-005 MainGraph T2는 `7f8fb2c5`에서 실행된 원 기록이다. Output FIRST(call5)가
조회 요청을 TASK/UPDATE + GMAIL_MESSAGE/SEND로 바꿨다. Review goal inspector(call14)는
그 모순을 설명했지만 typed `finding_kind=ROUTE_ISSUE/code=ROUTE_ISSUE`였다. action/route
inspector(call15)는 빈 findings였다. call8·17의 Query 입력과 Intent revision1이 같았다.
현재 Review Prompt도 당시와 같은 hash지만 이것이 현재 모델의 재발 빈도 증명은 아니다.
원 calls에는 최종 aggregate snapshot이 없으므로 최종 Route 판정은 기존 보고서와 현재
결정적 mapping으로 설명한다. 새 모델 실행 없이 과거 실패를 현재 SHA 점수로 바꾸지 않는다.

현재 Review는 Request 의미 반증 kind/status가 없고, RequestReconsiderationRequiredV1은
Work Analysis의 외부 Evidence 관측만 지원한다. 그 계약에 원문을 가짜 Evidence로 넣거나,
자유 code/설명 문구에서 새 owner를 추론하지 않는다. 기존 Route 진단 전달 수정은 유지한다.

## 가장 작은 평가용 계약

| 책임 | 후보 경계 | 유지 |
| --- | --- | --- |
| producer | 기존 goal/evidence Review inspector에 REQUEST_SEMANTICS_ISSUE variant | 다른 inspector·새 LLM 호출 없음 |
| 모델 선택 | 현재 WorkUnit ID, 실제 semantic field path, 관측한 불일치 설명 | old ROUTE_ISSUE/ISSUE/GAP을 코드가 재분류하지 않음 |
| binding | 현재 Intent meta·Plan ref, 선택한 WorkUnit의 검증된 원문 provenance, 해당 field의 실제 값 | 모델이 원문 span/값을 다시 생성하지 않음 |
| validator | closed IDs/path, source-bound span, current revision, pre-publication 범위 | 업무 해석·정답·수정값을 만들지 않음 |
| projection | USER_REQUEST_PROVENANCE origin의 평가용 revision 요청 | 외부 Evidence와 구분; stable semantic item ID 발명 없음 |
| consumer | RU의 기존 요청 재판정 입력에 전달 가능성을 component로 확인 | RequestIntent 의미 변경은 RU만 소유 |
| production migration | 후보 검증 후 Canonical/Review result/signal/Supervisor/resume 범위를 판단 | 이번 prototype을 활성 Main authority로 등록하지 않음 |

semantic field 선택은 기존 `goal/completion_conditions/constraints/source_reads/outputs/
effect_prohibitions`의 소유 필드 범위다. 새로운 business category가 아니다. 해당 항목의
Work binding을 확인하고 현재 item 자체를 전달한다. 승인된 실행 순서·Action dependency나
정책 허용으로 해석하지 않는다. Request 재판정 후 dependent artifact invalidation과 기존
budget을 우회하는 별도 Run을 만들지 않는다.

## 먼저 수행할 component gate

모델0 / Provider0 / 테스트 동시성1. 필요한 original Work provenance는 fixture로 고정하되
fake finding의 의미를 실제 모델 PASS로 채점하지 않는다.

- Intent 오류: 명시적 새 typed finding만 RU 후보 projection으로 전달.
- capability 오류 / Planning 인자 오류 / Evidence gap / 정상 결과: 기존 owner 유지.
- stale Intent·Plan, unknown Work/field/Action/Route/Evidence, 다른 요청 span, 승인 후 범위 거절.
- field 값·원문·intent를 재작성하지 않음. free code/설명만 Request 오류인 경우 자동 승격0.
- 실제 current RU 입력 소비 경계를 확인하되, 평가용 shape가 permissive Mapping을 통과한
  사실만으로 전체 Main Graph/기존 checkpoint migration 완료라고 주장하지 않음.

이 gate 이후에만 현재 Review의 bounded 모델 비교를 별도 사전 고정한다. 실제 Core 원기록,
독립 합성 control, 전체 Canonical 점수를 섞지 않는다. First 출력과 validation/repair를
분리하고 실패 Trial을 교체하지 않는다. 이번 단계에서 Canonical92·Provider 실행은 하지 않는다.

### Component 관측

직접 **37 PASS / 0.43초**, helper mypy PASS. 최초 실행의 36 PASS/1 FAIL은 테스트가
명시적 EVALUATION PromptRef를 주지 않아 DRAFT의 Product Release gate에 막힌 준비 결함이다.
명시적 평가 참조를 주입했으며 activation/Release guard 자체는 변경하지 않았다.

RU 첫 Goal 입력까지 signal과 원문이 그대로 도달했으나 이는 fake Work owner 뒤의 입력
capture이며 의미 재판정 성공이 아니다. 현재 Main PLAN_REVIEW는 새 signal을 받아 RU로
보내지 않는다는 점도 검사했다. **Production migration과 실제 revision 복구는 미완료**다.
schema2 평가는 Python Mapping 수용성을 이용한 compatibility 승인이 아니다.

실행기 포함 최종 사전검사는 **113 PASS / 4.80초**, Ruff와 후보/실행기 mypy PASS다.
첫 실행기 준비 검사에서 합성 UPDATE의 파생 required_information constraint 누락과
실제 Prompt assembler의 trailing newline을 반영하지 못한 오류가 각각 9개 setup error로
드러났다. 기존 canonical derivation과 실제 frame을 사용해 고쳤다. 모델 호출 전 준비 오류이며
Product/모델 실패 또는 semantic PASS로 세지 않는다. 실제 원기록 byte·current Product wire·
Dataset·fixture·model digest 일치도 generation 없이 확인했다.

## 실제 모델 비교의 사전 고정

위 gate 후 diagnostic4 입력에서 current baseline / candidate 각각 FIRST1회, **최대8회**.
repair0, retry0, 병렬 generation0(동시성1), rerun-to-pass0. timeout180초, 현재 설치된 동일
9B digest와 기존 Review의 실제 옵션(temperature 미전송 포함)을 보존해 plan에 결속한다.
활성 Prompt·Canonical Dataset·Fixture bytes는 바꾸지 않는다.

1. CORE-005 T2의 실제 frozen Review input: 원문의 READ와 잘못된 Output authority의 모순.
2. 별도 합성 control: 사용자 값만으로 완결된 정상 Task CREATE 제안.
3. 같은 합성 Intent에서 Plan의 제목만 변경한 반례: Planning 오류이지 Request 오류 아님.
4. 별도 합성 selected Task UPDATE, 기존 target snapshot 부재: 근거 부족이지 Request 오류 아님.

합성3은 독립 diagnostic controls이며 Canonical Case를 고치거나 새 평가셋 Gold로 등록하지
않는다. 직접 CREATE의 실제 최적화는 inspector를 생략할 수 있으므로, 이 모델 비교는
해당 호출의 입력 계약 진단이지 실제 Graph 호출수/latency 측정이 아니다.

후보는 현재 role+고정 경계 설명, authoritative `user_request` input, 새 finding variant와
그 typed projection을 하나의 연결된 표현 후보로 비교한다. Core 원 raw와 현재 baseline의
관계는 따로 남기고 후보가 채택할 수 없는 old result shape만을 실패 점수로 만들지 않는다.
양쪽의 mismatch 인식, 최초 실패 위치, 실제 수정 owner 전달 가능성, 불필요 재해석을
구별해서 검수한다. closed Action/Route/Evidence ref 진단은 양 arm 동일하게 적용하고
Product schema 통과와 따로 기록한다. Gold/정답 kind/control label은 모델에 제공하지 않는다.

채택 확대 조건은 Intent 오류에서 타당한 field/Work 관측이 선택되고 정상·Planning·Evidence
반례에서 불필요 RU 재판정을 만들지 않는 것이다. 한 번의 성공은 안정성이나 전체 복구율
증명이 아니며, 현 단계 결과만으로 Production back-edge를 켜지 않는다.

## 안전 및 범위

Production Prompt/Schema/State/Node/Edge 변경0. evaluation-only helper와 직접 tests만 만든다.
실제 Approval/Permission/Scope/Identity/Execution/Verification/Recovery 경계 변경0.
새 consumer 계약이 기존 persisted V1과 충돌하면 형상 호환으로 숨기지 않고 migration 필요로
기록한다. 후보가 실패하면 failure owner 구분/결속/consumer 중 최초 경계만 추적한다.

원자료: `evaluation/results/064-core005-main-graph-t2/calls.json` (249KB), `raw.json` (30KB).
기존 근거: `064-production-snapshot-workflow.md`, `064-review-selection-reconsideration-handoff.md`.
