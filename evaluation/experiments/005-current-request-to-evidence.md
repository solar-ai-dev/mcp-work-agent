# 005. 현재 Request → Query → Evidence 짧은 연결

## 가설·비교 범위

기준 SHA는 `143721d0`다. 기존 Query→Evidence 합성 평가는 저장된
RequestIntent·ToolRoutePlan만 소비하므로, 최신 Request Understanding에서
`TASK`가 살아난 `015/021`의 Evidence 변화는 증명하지 못한다. 이번에는
현재 production Application의 `identify_goal_with_budget → temporal scope →
ambiguity → finalize_intent → Tool Route policy/bind/finalize`를 먼저 실행하고,
그 **실제 출력 객체**를 기존 Retrieval Subgraph에 메모리로 전달한다.

고정 입력은 Core `014`(Task+Event 기존 성공 대조), `015`(Task+FreeBusy+Draft),
`021`(Gmail+Task+가용성→Event) 세 건이다. `024`는 앞 실험에서 같은 원문이
Status 출처 불일치로 두 번 막혔으므로 같은 방법의 재실행으로 PASS를 고르지 않는다.
모델 9B, temperature 0, seed 1729, 동일 canonical92-v8 checkpoint 원문과
합성 Provider fixture를 사용한다. LLM과 합성 READ는 직렬 한 프로세스에서만
실행하며 실제 Provider·WRITE·Planning은 하지 않는다.

판정은 `Source/Output 역할 → 실제 input route → 새 Query에 대응한 READ →
Evidence/충분성`으로 나눈다. Action 결과는 생성·승인·실행하지 않으므로
최종 업무 성공으로 세지 않는다. 이전 저장 RU 평가와 비교할 때 동일 입력
paired trial이 아니며, 개선 원인을 후보 Prompt에 귀속하지 않는다. Query와
조회 결과의 불일치, 필요한 자료가 검색됐지만 Evidence에서 빠지는지, 또는
앞단 Source 자체가 여전히 틀렸는지를 우선 확인한다. User Confirmation 또는
Scope 승인 요구가 나오면 우회하지 않고 별도 결과로 남긴다.

## 첫 연결 관측과 다음 원인 진단

세 건 모두 현재 Request Understanding·Tool Route가 통과했고, Output은 요청대로
Draft CREATE(`014/015`) 또는 Event CREATE(`021`)였다. `014`는 Task·Event
Source를 Route에 넘기고 합성 READ 4회에서 Evidence 4개와 `SUFFICIENT`를
반환했다. `015`는 이전 저장 Intent에서 빠졌던 Task Source가 현재 조립에서는
유지됐고, Task READ가 1개 item을 찾았다. 그러나 Event 검색 0건·FreeBusy
응답 후 Retrieval이 `FINALIZE`로 나가며 parent `retrieval_result`가 없었다.
`021`도 Gmail 검색 2개, Task READ 2개를 찾았지만 Event 검색 0건·FreeBusy
응답 뒤 같은 종결이었다. 이는 생성까지 가지 못한 관측이지, 빈 Event가 곧
가용성 부족이거나 최종 업무가 실패했다는 단정은 아니다.

첫 실행은 Producer LLM 19회(6/6/7), Retrieval LLM 10회, 합성 READ 13회,
WRITE 0회였다. Retrieval `COMPLETED` 1/3, `NO_RETRIEVAL_RESULT` 2/3이며
Action 후속 단계는 모두 미실행이다. 원시 결과는
`evaluation/results/request-to-evidence-core014-015-021-20260916/`에 있다.
저장 RU·Route를 사용한 과거 연결 결과와 입력이 다르므로 같은 Query 후보의
paired 개선률로 해석하지 않는다.

`015/021`의 종결 이유가 첫 평가 출력에 보존되지 않았으므로, 동일 입력을
각 1회만 **원인 진단**으로 재생한다. 추가 기록은 `sufficiency.status`, issue
slot, 선택 segment 수, workflow signal 종류, 최종 상태 종류처럼 비민감
분류값만 남긴다. 성공으로 바뀌어도 첫 실패를 지우지 않고 모델 변동으로
분리한다. 원인 확인 전 `select_evidence`나 Query Prompt를 수정하지 않는다.

### 평가기 결함 발견·교정

두 번째 관측도 `015/021`에서 같은 `NO_RETRIEVAL_RESULT`였지만, Subgraph가
종결 시 Local `sufficiency`와 selection을 Parent 출력에서 제거하므로 추가한
진단 필드는 null이었다. 같은 방식으로 다시 돌리지 않는다. 대신 Query의
검증된 temporal constraint를 읽으니 `015`의 “내일”이
`2026-09-17~18`로 바인딩됐다. 이 사례의 고정 Run 기준 시각은
`2026-08-07T09:00:00+09:00`이므로 잘못된 평가 입력이다.

원인은 연결 평가기가 저장 원문·Intent를 사용하면서 Retrieval용 새
`retry_budget.started_at_ms`를 실행 당일로 생성한 데 있다. Product Query Planner는
그 Budget 시작 시각을 상대 기간 해석에 사용한다. 수정 평가기는 저장된 Run
시각을 semantic clock과 Budget에 동일하게 넣고, dispatch budget의 경과 시간만
실제 재생 경과에 따라 증가시킨다. 제품 temporal resolver나 validator는
바꾸지 않는다. 앞선 두 연결 Trial의 temporal·업무 결론은 **무효**로 분리하고,
`014/015/021`을 같은 조건에서 고정 clock으로 다시 평가한다. 이는 PASS를
고르기 위한 반복이 아니라 잘못된 평가기 입력을 바로잡은 새 기준 Trial이다.

## 고정 시각 기준 Trial·판정

고정 semantic clock에서 `015`의 Calendar Event/FreeBusy Query 범위는
`2026-08-08~09`로 바로잡혔다. 앞선 `2026-09-17~18` Query는 폐기한다.
새 기준 결과는 다음과 같다.

| Case | 현재 업무 Source → 실제 합성 READ | Retrieval 경계 |
| --- | --- | --- |
| 014 | Task·Event → Event/Task 및 접근용 Calendar/TaskList | `SUFFICIENT`, Evidence 2개, Planning 전달 |
| 015 | Task·Event·FreeBusy → Event/FreeBusy만 READ | `CONTEXT_BLOCKED`, parent RetrievalResult 없음 |
| 021 | Gmail Thread·Task·Calendar·FreeBusy → Gmail/Task/Event/FreeBusy READ | `CONTEXT_BLOCKED`, parent RetrievalResult 없음 |

`015`에서는 Task가 RequestIntent와 frozen input route에는 있지만 새 Query에 따른
실제 READ에서는 빠졌다. 이 손실은 앞단 Source 누락이라고 할 수 없고,
Query Planner·route materialization/실행 경계의 다음 진단 대상이다.
`021`은 Gmail/Task를 조회했으나 Calendar Event 조회 결과는 0건이었고,
FreeBusy 응답 후에도 최종 충분성은 차단됐다. Event 0건이 곧 불가능인지,
빈 일정과 가용성의 의미가 충분성에서 잘못 결합됐는지 이 결과만으로
정하지 않는다. 021의 `10:00`은 현재 Intent의 날짜 제약에 보존돼 있지만
Query는 하루 범위로 조회했다. 이것이 실제 기능 실패인지 다음 consumer의
시간 결속을 봐야 한다.

세 건 합계 Producer LLM 19회(입력 46,365·출력 1,489 tokens,
관측 Provider 지연 61,421ms), Retrieval LLM 9회(70,040·3,856 tokens,
133,821ms), 합성 READ 10회, WRITE 0회다. `014`만 parent RetrievalResult가
있고, Action 생성·승인·실행은 전혀 평가하지 않았다. 원시 결과는
`evaluation/results/request-to-evidence-fixed-clock-core014-015-021-20260916/`.

Subgraph는 종결하면서 Local sufficiency/selection을 Parent 출력에서 제거하므로
현 평가 결과로 두 차단의 issue slot까지 확인할 수 없다. 동일 연결 실행을
반복하지 않고, 다음에는 경계 내부의 비민감 status·issue 요약을 단일 Node
입력에 대해 관측하는 방법으로 바꾼다. Source Status provenance 반복 실패,
Calendar over-selection, `015`의 Task route 미실행을 서로 다른 failure family로
유지한다. `select_evidence` 또는 Query Prompt의 임시 문구 추가는 보류한다.
