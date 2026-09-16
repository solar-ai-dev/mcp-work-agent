# 021. 고정 입력의 production Planning·Review 수정 순환 기준선

기준 `e2e1c458`, working tree clean. 목표는 Review finding 수가 아니라
`Review 원판단 → 실제 Supervisor target → Planning 재진입 → 변경된 Action
→ Review RECHECK`의 의미 보존과 비용을 확인하는 것이다. 019/020의
`revision_context`는 제품에 활성화하지 않았다.

## 입력·실행 범위

저장된 012 연결 결과의 023/028 `RequestIntent`, `ToolRoutePlan`,
`WorkAnalysis`, Evidence, Plan과 checkpoint의 current-Run request를
사용한다. 반례는 017에서 이미 검수한 Action 한 필드 변경을 재사용한다.
새 RU/Retrieval·Provider READ·WRITE를 실행하지 않는다. 저장 Evidence는
새 평가 Run의 in-memory EvidenceStore에만 등록한다. 이전 Plan은 제안이고
실행·검증 결과가 아니다. 구조상 필요한 최소 GraphState를 재구성하되,
`ReviewSubgraph`·`PlanningSubgraph`·Supervisor 라우팅·RECHECK는 제품
compiled 경로 그대로 사용하며 finding/disposition을 fake로 반환하지 않는다.
이는 공식 백엔드 Domain Run이나 Live Provider 검증은 아니다.

고정 집합 6개, 각 1 Trial, 순서 고정:

1. `NORMAL_023` — 실제 명시 날짜 정상 Plan.
2. `WRONG_DATE_023` — 017의 합성 Action 날짜 오류.
3. `FORBIDDEN_ATTENDEE_023` — 017의 합성 참석자 Action과 금지 제약.
4. `USER_EDIT_023` — 017의 사용자 Preview 제목 수정 반영 Plan.
5. `MISSING_MAIL_023` — 017의 메일 Evidence·해당 WorkFact가 빠진 입력.
6. `NORMAL_028` — 실제 상대 날짜 정상 Plan.

금지 대조의 저장된 017 Intent에는 참석자 금지 제약이 있지만 012의 원문에는
그 문장이 없었다. 이번 합성 대조에서는 같은 Run의 USER_MESSAGE와
`original_search_request`에 “참석자는 초대하지 마”를 함께 추가해 권위
충돌을 제거한다. 이 입력은 실제 요청이 아니며 업무 성공률 분모에 넣지
않는다. 나머지 오류 대조는 Plan 또는 저장된 Evidence·WorkAnalysis만
변경한다.

Review가 정당한 ISSUE→REVISE를 내고 Supervisor가 Planning 재진입을
선택한 `WRONG_DATE_023`·`FORBIDDEN_ATTENDEE_023`에만 Planning을 한 번
실행한다. 새 Plan이 나오면 제품 Review를 한 번 더 실행한다. 잘못된
finding, 근거 부족, 확인 필요, Schema/timeout은 결과로 남기며 성공으로
대체하지 않는다. 정상·Preview·근거 부족 입력의 허위 REVISE는 실패로
기록하고 강제 수정하지 않는다. 호출·토큰·지연과 첫 structured output,
repair/dispatch, 단계별 SHA를 ignored result에 저장한다.

동일 모델 `qwen3.5:9b` digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
temperature 0/seed 1729, 현행 Prompt/Schema, Run별 독립 기본 budget.
최대 6 initial Review + 2 Planning + 2 RECHECK subgraph invocation이다.
중간 오류가 나면 다른 사례의 실행 조건을 바꾸지 않는다. 한 번의 결과를
반복 안정성으로 해석하지 않는다. 실제 correction과 단순 재생성은
`Planning` 입력에 Review issue가 있는지로 구분한다.

## 첫 실행의 평가 State 결함과 수정된 연결 실행

첫 실행 `baseline.json`에서는 6건의 Review 원판단은 생성됐으나 전부
`RECOVERY`로 라우팅됐다. 평가용으로 복원한 Retrieval artifact의
`meta.based_on`을 빈 배열로 둔 것이 원인이며, 제품의
`RETRIEVAL_RESULT_STALE` 가드가 정상 작동한 것이다. 이 Trial은
수정 순환 결과로 세지 않는다. 의존 참조만 복원한 `connected-fixed.json`
재실행은 Review 첫 호출 입력 SHA-256 6개가 동일한 조건에서 수행했다.
실패 Trial도 삭제하지 않는다.

수정된 연결에서 정상 023/028은 PASS→DOMAIN_VALIDATION, 날짜·참석자
반례는 REVISE→PLANNING_REVISE_PLAN→PLAN_REVIEW_INSPECT까지 연결됐다.
두 Plan 모두 지적된 필드를 바로잡고 다른 주요 값을 보존했으나 RECHECK는
각각 RETRIEVE_MORE·CONFIRM으로 빠졌다. 사용자 Preview 수정 반영안도
REVISE로 오판했고, 실제 메일 Evidence 부족은 CONFIRM으로 분류됐다.
따라서 현재 결과는 수정 순환 성공이 아니라 후단 판정 실패의 진단 근거다.

## 추가 원인 분해 후보: 기존 initial Review 분해 재사용

RECHECK는 1회 호출에서 세 dimension을 동시에 판단하며, 수정 후 Plan에
존재하지 않는 이전 action_id를 `affected_action_ids`로 전달한다. 두
RECHECK 원출력은 요청된 생성이 아직 실행되지 않았다는 사실을 ISSUE로
보거나, 이미 있는 메일·Task Evidence를 없다고 하거나, 확인 요청을
새로 만들었다. Prompt에는 이미 “해결된 문제를 복사하지 말라”는 지시가
있으므로 문구 추가를 우선하지 않는다.

진단 Candidate는 동일 수정 Plan/Evidence/Intent를 기존 초기 Review의
3개 책임 호출에 넣는 것이다. 대상은 날짜·참석자 2건, 각 1 Trial,
최대 2 Review subgraph·6 LLM 호출이다. 새 Provider READ/WRITE는 0.
두 건에서 빈 finding/PASS를 얻으면 분해된 판단과 fused RECHECK의
차이를 좁힐 수 있지만, 단발 PASS만으로 제품 경로 채택·안정성을
선언하지 않는다. 여전히 실패하면 입력 역할·권위·action binding을
다음 원인으로 본다. 비용은 호출/토큰/지연을 같이 기록한다.

분해 진단 `split-diagnostic.json`은 두 건 모두 3회 호출 후 허위
REVISE였다. 날짜를 바로잡은 Plan의 title/description이 실제로 있는데
없다고 했고, 참석자를 제거한 Plan에서는 `attendees` 필드가 없다는
이유로 초대 위험을 제기했다. 호출 1→3, 총 입력 토큰 약 12.5k→34k로
증가했으나 의미 판정은 개선되지 않았다. 이 분해안을 기각한다.

다음 단일 변수 후보는 RECHECK의 `affected_action_ids`를 이전 Plan의 ID가
아닌, 같은 affected route의 현재 Plan Action ID로 바꾸는 것이다.
저장된 RECHECK prompt input은 그 외 바이트를 유지한다. 날짜·참석자
2건 각 1 Trial, 최대 2 LLM 호출, 실제 Provider I/O 0. 결과에 관계없이
stale ID는 계약 결함으로 분리하며, PASS가 우연히 나오더라도 단발
품질 안정화로 보지 않는다. 후보가 실패하면 새 Prompt 문구보다
역할·대상 표현과 모델 원출력을 다시 조사한다.

## 결과·채택 판단

`current-action-binding.json`에서도 날짜·참석자 두 건 모두 1회 LLM
원출력에 근거 부족/미수정 금지/추가 확인 finding이 남았다. 현재 Action ID로
바꾼 입력만으로는 개선되지 않는다. 또한 06/08 Canonical은 직전 issue의
Action ID를 bounded context로 전달한다고 명시하므로, 이를 현재 ID로
무조건 바꾸는 제품 변경은 채택하지 않는다. 그렇다고 기존 ID가 현재
Action identity라는 뜻은 아니다. 이전 제안과 현재 제안의 관계 표현은
별도 설계·반례 비교가 필요하다.

수정된 연결 Trial의 분리 판정은 다음과 같다.

| 유형 | Review→Planning→RECHECK | 의미 판정 |
| --- | --- | --- |
| 정상 023/028 | PASS→DOMAIN_VALIDATION | 정상 Plan 불필요 수정 없음. 이후 Domain Validation/WRITE 미실행. |
| 날짜 오류 | REVISE→새 Plan→RETRIEVE_MORE | 첫 finding 정확, 날짜 수정과 주요 값 보존 확인. 재검토는 이미 있는 메일·Task Evidence 및 실행 전 정책 결과를 부족하다고 판단. 순환 성공 아님. |
| 참석자 금지 | REVISE→새 Plan→CONFIRM | 첫 finding 정확, 참석자 제거 확인. 재검토는 금지 위반이 남았다고 하면서 사용자에게 이미 명확한 생성 여부를 다시 물음. 순환 성공 아님. |
| Preview 사용자 제목 수정 | REVISE | 원래 제목을 기준으로 허위 불일치. 사용자가 정한 `payload.title` override가 Plan에 있으므로 Review 오판. 수정 실행 안 함. |
| 메일 Evidence 부족 | CONFIRM | 부족한 외부 근거를 사용자 생성 확인으로 전환. 입력 부족과 Review 분류 오류를 동시에 기록. 수정 실행 안 함. |

이번 범위에서 원출력의 날짜·참석자 첫 finding과 Planning 결과는 좋지만,
재검토와 Preview/근거 부족 분류가 반복 실패한다. Node 실행 완료,
Schema 통과, 안전하게 WAITING_CONFIRMATION/CONTEXT_RETRIEVAL에 멈춘
것을 업무 수정 성공으로 계산하지 않는다. 첫 실행의 일괄 RECOVERY는
제품 실패가 아니라 평가 State 결함이다. `connected-fixed.json` 10단계에서
LLM dispatch 24회(Review initial 18, Planning 4, RECHECK 2), 입력/출력
266,670/6,351 tokens, 단계 경과 합 285,891ms, 호출/repair 실패 0이었다.
이는 모델 품질 성공률과 별도의 시스템 수행·비용 지표다. 단발 Trial이므로
반복 신뢰성은 미검증이다.

Prompt manifest SHA-256 `534e596cf93ee7bec0dc75ee7a73b7832d4ad7146e70c8ce4f35250f7579c871`,
input contract SHA-256 `4c5a4e49bec4f4d407726bfb7911ec982b2ef49da4fa1efb87b56582eb94c69e`.
원결과는 ignore 정책을 따르는 `evaluation/results/planning-review-cycle-20260917/`
에 보존했다. 특히 `connected-fixed.json` SHA-256은
`9d28c86db78d53b7511a0400d843f43c68513827bf7eb8bdfc55f79061b8c297`.
저장 결과 원문에는 개인 메일/Resource 내용이 포함되므로 원격에 올리지
않는다. 비민감 판단은 이 파일에 남긴다.

다음 공통 가설은 Prompt 문구가 아니라 현재 요청/수정 권위·이전 제안·현재
제안·Evidence 역할을 좁은 관계 표현으로 투영하는 것이다. 이전 finding은
검토 가설이며 권위가 아니고, 이미 있는 외부 정보와 실제 부족 정보를
구분해야 한다. 기존 018의 WorkAnalysis 전체 삭제는 제목 허위 ISSUE를
만들어 기각됐으므로 재시도하지 않는다. 다음 비교는 날짜/금지/Preview/
근거 부족/정상 023·028을 같은 설계로 묶고, 첫 의미 판단·수정 재진입·
재검토를 분리해 측정해야 한다. 아직 이 후보를 제품에 활성화하지 않는다.

실제 백엔드 Domain Run·LangSmith trace·실제 Provider READ/WRITE는
수행하지 않았다. 이번 local compiled subgraph의 모든 LLM prompt input,
structured output, Supervisor target은 저장돼 있어 현재 경계 분석에
LangSmith가 추가 근거를 주지 않는다. 실제 Domain Run의 호출 계층이나
저장·resume 차이를 확인하는 단계에서는 LangSmith root/child/LLM trace를
조회해야 한다. 제품 코드·Prompt·Schema·Canonical 변경 없음. 관련
Review/Planning/Supervisor unit test 67개 PASS, 세 평가 script Ruff PASS.
