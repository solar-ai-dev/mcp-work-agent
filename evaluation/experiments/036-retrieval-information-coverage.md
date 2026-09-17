# 036. Retrieval 정보 충족성·후속 조회 경계

기준 SHA `4d612d6f`, clean tree. LoRA·WRITE·승인 우회·전역 State 변경은 제외한다.

## 사전 가설과 비교

034의 저장된 실제 Run에서는 Task 항목의 제목·내용·마감일이 필요했으나 RU의
`source_reads`는 `TASK_LIST`였고, frozen `TASK` detail Route는 초기 Query에서
미시도였다. Sufficiency 입력은 `TASK_LIST`의 완료 상태를 coarse `TASK`로
표시하고 미시도 `TASK` Route는 제외했다. 목록 제목 Evidence만으로
`SUFFICIENT`가 된 최초 경계는 Query 누락과 충분성 입력의 역할 손실이 함께
있는 것으로 본다. 015의 최신 RU/Route 연결은 `TASK`를 business source로
포함했으나 Query가 누락한 다른 조건이다. 두 사례를 같은 원인으로 합치지 않는다.

후보 A는 Sufficiency의 기존 `source_statuses`에서 frozen Route의 정확한
resource type과 business/dependency 역할, 미시도 상태를 전달한다. 새
의미 판정이나 모든 Route 강제 실행은 하지 않는다. 모델이 요청의
`required_information`과 실제 Evidence를 대조해 필요한 Route-bound Issue를
출력하는지를 먼저 본다. 효과가 없으면 Prompt 문구·필드 추가를 반복하지
않고 RU source 책임과 Query 출력 부담을 다시 조사한다.

동일 9B digest, temperature 0, seed 1729, 현재 Prompt/Schema를 고정한다.
034 저장 Run 1건과 그 입력에서 목록 이름만 필요/항목 상세 필요/상세 확보/
정상 미발견/사용자 선택 필요/Calendar 내용 필요로 만든 **합성 대조 6건**을
분리 표시한다. 각 입력마다 baseline·후보 첫 structured inference 1회씩,
최대 14개 Node 호출을 직렬 실행한다. 입력·Prompt·Schema fingerprint와
원출력·호출 실패·토큰·지연을 ignored 결과에 모두 저장한다. 첫 호출 전
fixture 직렬화와 결과 기록 경로를 검사한다. `SUFFICIENT` 숫자만으로 채택하지
않고 실제 부족 정보의 Issue와 route binding, 목록-only의 불필요 조회,
이미 충분한 입력·미발견·사용자 선택의 오분류를 함께 판정한다.

유력하면 기존 Node/인접 구간에서 실제 후속 Query→합성 READ→Evidence→
Work Analysis·Planning·Review로 확인한다. 실제 Provider READ와 새 SHA
LangSmith Live는 별도 조건·결과로 남긴다. 매 수정마다 92개 E2E는 돌리지 않는다.

## 결정 기록

| 실패 유형 | 시도 방법 | 조건·근거 | 결과·회귀 | 판단 | 재시도 조건 |
| --- | --- | --- | --- | --- | --- |
| 034 목록 근거를 항목 정보로 오인 | 정확한 Route 상태·역할 투영 A/B/C | 저장 Run + 합성 대조, 동일 입력 A/B | 잘못된/미지정 후속 Route, Calendar 대조 false SUFFICIENT | 기각 | 사실 owner와 Route 책임 표현 변경 |
| 015 비정책 Task 미조회 | 별도 Query/Route 진단 | 최신 RU/Route의 Task business source | 첫 Query 누락, unbound Issue가 Route 재고려로 종료 | 미해결 | 새 Query→READ→Evidence 연결 |
| 034/028 Query Route 혼동 | canonical resource type 단독 투영 D | 저장 Query 6개 + 034/028 합성 연결 | 034 후속 실패, 028 READ 1회 증가 | 기각 | owner·business/dependency 관계를 함께 보존하는 후보 |

### 후보 A 첫 비교

14/14 첫 structured 출력이 기록됐다(실제 저장 입력 2, 합성 12).
034의 A=`SUFFICIENT`에서 후보 A=`PARTIAL`로 바뀌었으나 Task와
Calendar에 `HAS_MORE` 부족을 함께 만들고 route_id를 주지 않았다. 이
상태는 복수 Google Route에서 후속 조회로 결속되지 않으므로 근거 확보 성공이
아니다. `calendar_event_needed` 합성은 두 쪽 모두 잘못 `SUFFICIENT`였다.
`task_item_complete`는 둘 다 SUFFICIENT, `user_choice_needed`는 둘 다
NEEDS_CONFIRMATION이었다. `list_name_only`는 저장 034의 부분 pagination
상태를 물려받아 양쪽 PARTIAL이므로 불필요 READ 회귀의 유효한 판정 입력이
아니다. 이 fixture 결함은 첫 Trial을 폐기·교체하지 않고 보존한다.

후보 A 단독 채택을 보류한다. 다음 후보 B는 같은 7개 입력과 A의 exact
Route 상태를 유지하고, 이미 검증된 `resource_responsibilities.source_reads`
정보를 해당 business Route 상태 옆에 좁게 투영한다. Evidence는 내용 충족을
결정하지 않고 같은 resource type의 **관측 ref와 역할**만 연결한다. 이는
Route 완료와 정보 충족의 관계를 모델이 직접 판단하게 하려는 입력 표현이다.
Schema·Prompt·모델은 그대로 두고 B만 각 1회, 최대 7개 직렬 호출한다.
이번 변경으로 A의 호출/결과를 덮지 않는다. B가 034의 잘못된 충분성을
줄이더라도 실제 해결 Route가 없는 Issue만 내면 채택하지 않는다.

B의 7/7 첫 결과에서도 034는 `NEEDS_MORE_DATA`를 말했지만 Task·Calendar
`HAS_MORE`를 Route ID 없이 출력했다. `calendar_event_needed`는 계속 잘못
`SUFFICIENT`, `task_item_complete`·사용자 선택은 유지됐다. B 입력의
관계 투영도 후속 획득 경계를 해결하지 못했다. A/B 모두 활성 제품 코드에
채택하지 않는다.

첫 출력에서 여러 Google Route 중 `route_id`가 없는 외부 부족 Issue는
기존 `_bind_issue_routes`가 `ROUTE`로 바꿔 재선택을 요구한다. 다음 후보 C는
Prompt·입력 B를 고정하고, 외부 부족 Issue에 frozen `route_id`를 명시하거나
`resolution_source=ROUTE`로 불확실성을 표현하게 **출력 구조만** 제한한다.
이는 존재하는 Route를 자동 선택·실행하는 규칙이 아니다. 같은 7개 입력에
첫 호출 각 1회(최대 7개) 직렬 비교하며 Schema repair/출력 누락을 분리한다.
빈 issues로 회피하거나 잘못된 Route를 고르면 즉시 기각한다.

C의 7/7 첫 결과는 Task item이 미조회인 합성 입력에 올바른 `TASK` Route
Issue를 주었지만, 저장 034에서는 잘못된 `TASK_LIST`와 과잉 Calendar
`HAS_MORE`를 Route-bound로 만들었다. Calendar item 내용 대조도 여전히
`SUFFICIENT`였다. 따라서 C는 실제 근거 획득으로 연결하지 않고 기각한다.

### 원인 범위 재검토: Query 입력의 Resource 구분

Sufficiency 입력·Schema 세 방식 모두 034의 실제 필요 Route를 안정적으로
고르지 못했다. Query Planner의 `_prompt_route`도 frozen `TASK_LIST`와
`TASK`를 둘 다 coarse `TASK`로, `CALENDAR`·`CALENDAR_EVENT`·
`CALENDAR_FREEBUSY`를 모두 coarse `CALENDAR`로 투영한다. Tool ID는 다르지만
현재 Node가 해야 할 목록/항목/가용성의 차이가 필드에서 손실된다. 이 경계를
먼저 평가한다. 후보 D는 frozen route의 canonical resource_type을 **그대로
투영**하며 Route/Tool 선택 강제나 Prompt 문구는 바꾸지 않는다.

고정 저장 Query 입력 `014/015/021/028/036/058`의 현재 SHA baseline과
D를 각 1회(최대 12 Node 실행, repair/revision 별도 집계) 직렬 비교한다.
015 저장 입력은 Task Route 자체가 없는 과거 State이므로 별도 모집단이다.
034 저장 Run의 RequestIntent·ToolRoute·설정에서 재구성한 동결 입력은
baseline/D 각 1회(최대 2 Node 실행)로 따로 평가한다. 먼저 평가기 기록
경로와 input fingerprint를 preflight한다. 초기 Route 포함, Query 의미,
repair/revision, 실제 READ 가능성, 과잉 Route, token/latency를 분리한다.
Query만 좋아도 Evidence 확보·후단 성공으로 계산하지 않는다.

Query Node 현재 기준 6건은 2/6 first-call semantic-valid, 2건 Policy
composition 회복, 2건 실패였다. D는 2/6 first-call semantic-valid 유지,
2건 Policy composition 회복 유지, 036의 schema repair 회복으로 최종
5/6(기준 4/6), 058 temporal 실패는 그대로다. 028은 `TASK_LIST` Route도
선택해 필요한 discovery인지 과잉인지 연결 전까지 미판정이다. 기준의
schema repair 실패는 provider dispatch 2회를 썼지만 token/latency가
0으로 기록되어 후보 총 token과 직접 비용 비교할 수 없다.

034 저장 Run의 동일 Query 입력을 한 프로세스에서 coarse/D 각 1회 비교했다.
두 쪽 모두 첫 structured inference 1회·repair 0. 기준은 TASK_LIST만,
D는 TASK_LIST와 TASK item Route를 함께 선택했다. D의 TASK SEARCH는
검증된 container_ref를 사용하며 미허용 Tool은 선택하지 않았다. 이것은
조회 계획 개선이지 item Evidence 확보 증거가 아니다.

다음 짧은 연결은 034와 원문이 동일한 Core-023 합성 Provider fixture에서
저장 034 RequestIntent/ToolRoute를 고정해 기준/D를 각 1회 직렬 실행한다.
사전 preflight는 동일 upstream fingerprint·fixture 직렬화와 실패 기록
경로를 확인했다. Query→허용 READ→Evidence→Sufficiency까지만 먼저 본다.
Task item READ·내용 Evidence·coverage가 유효한 후보만 Work Analysis 이후
Planning/Review 연결로 확장한다. 입력이 같은 합성 Provider 비교와 034
과거 백엔드 Live는 동일 Provider 결과 반복으로 세지 않는다.

실제 저장 upstream + Core-023 합성 Provider 연결 1회씩: 기준은 READ 6회,
Task item 0, `coverage=SUFFICIENT`로 Work Analysis에 넘어갔다. D는 READ
7회 중 `tasks_list_tasks` 1회와 item 후보 1건을 확보했다. 그러나 후속
`DETAIL_FETCH`에서 모델은 Gmail+Task detail을 골랐고, 기존 round validator가
`TASK_LIST` business Source 재조회도 요구해 실패했다. 즉 **조회 후보 확보는
개선됐지만 Evidence 선택·충분성·후단 전달은 미완료**다. 이 실패를 Query
Route 선택만의 성공으로 채택하지 않는다.

RU의 034 source read는 항목 title/notes/due를 `TASK_LIST`에 결속한 반면
이미 있는 RU source candidate의 owned fact 종류와 Prompt는 item 정보의
owner가 `TASK`라고 정의한다. 원인 분리용으로만 034 intent/route의
`TASK_LIST` business ↔ `TASK` dependency 결속을 뒤집은 합성 입력을
1회 연결한다. D 코드와 같은 Core-023 합성 Provider를 쓰며 이 결과를 실제
RU 개선이나 같은 입력 반복, 업무 성공률로 세지 않는다. 이 진단에서
후단까지 가면 RU 첫 결속을 별도 제품 Owner 후보로, 안 가면 Retrieval
후속/선택 계약도 함께 재검토한다.

합성으로 source owner만 바로잡은 진단 입력은 READ 7회 중 `tasks_list_tasks`
1회, 최종 Evidence에 `task` 항목을 포함해 `coverage=SUFFICIENT`로 Work
Analysis에 도달했다. 같은 원문이어도 수정 전후 upstream fingerprint가
다르므로 순수 Query 효과로 합치지 않는다. 이 진단은 RU의 Task item owner
결속이 실제 병목임을 지지한다. 한 번 더 이 **진단 입력에서만** producer
Evidence가 Work Analysis→Planning→Review까지 소비되는지 인접 연결 1회를
실행한다(Provider 합성 READ, WRITE 0). 첫 호출·최종 업무 성공률은 이
연결만으로 주장하지 않는다.

Query D가 container/item 구분을 넓게 개선하는지 반례를 추가한다. 저장 034의
frozen Route 구조에서 Task List **이름만** 필요한 합성 입력과 Calendar
**이름만** 필요한 합성 입력을 만든다. 기준/D 각 1회씩 최대 4개 Node 호출,
합성 입력 fingerprint·첫 structured output·과잉 item Route·repair/비용을
별도 기록한다. 실제 Provider 조회와 업무 성공률로 세지 않는다. container
정보만 충분한데 item Route를 첫 호출에서 불필요하게 선택하면 D 채택을
재검토한다.

목록-only와 Calendar-only 합성 Query 대조는 각 기준/D 모두 첫 호출에
container Route 하나만 선택했고 item/detail Route를 과잉 선택하지 않았다
(각 1 Trial, Provider 0). 다만 028 저장 Query 입력에서 D가 baseline보다
`TASK_LIST` discovery를 하나 더 제안했다. 이 경로가 실제 중복 READ·
후단 회귀인지 판단하려고 같은 저장 028 upstream과 Core-028 합성 Provider를
기준/D 각 1회 Query→Evidence까지 직렬 연결한다. extra READ를 감추지 않고
필요한 Task 내용·coverage·추가 호출과 함께 평가한다.

## 연결 결과와 채택 판단

028 저장 upstream + Core-028 합성 Provider의 동일 fingerprint 비교에서 두
입력 모두 Task item Evidence와 `SUFFICIENT`를 얻었다. 기준은 READ 6회,
LLM 4회, provider 지연 49.8초였고 D는 READ 7회, LLM 4회, 53.7초였다.
추가 READ는 `tasks_list_tasklists`였으며 이 Trial의 정보 확보·충분성 이득은
확인되지 않았다. 034의 실제 upstream에서는 D가 Task item 후보를 조회했지만
후속 Query가 잘못 결속된 `TASK_LIST` business Route를 누락해 검증 실패했다.
따라서 034 실제 입력의 최종 Evidence 확보율은 기준·D 모두 0/1이며, D의
첫 Query 개선을 업무 성공이나 후단 전달 성공으로 집계하지 않는다.

Source owner만 바꾼 **합성 진단**은 별도 fingerprint에서 Task item Evidence
3건 중 1건을 Work Analysis에 전달했다. 이어진 한 번의 인접 연결은 Work
Analysis 사실 5개 → Planning Action 1개 → Review `CONFIRM`/확인 대기까지
실행됐다. Retrieval 4 + Work Analysis 5 + Planning/Review 5 = LLM 14회,
합성 READ 7회, 총 158.5초다. `CONFIRM`의 정당성·최종 업무 성공은 이
연결만으로 판정하지 않는다. 실제 034 입력을 고친 제품 결과로 세지 않는다.

**후보 A/B/C/D 모두 기각, 활성 제품 변경 없음.** A/B는 부족함을 감지해도
후속 Route를 안정적으로 지정하지 못했고, C는 잘못된 `TASK_LIST`를 지정했다.
D는 034 첫 Query의 item Route 선택, 고정 Query 036의 schema repair 회복
(`4/6 → 5/6` 최종 검증 통과)에 이득이 있었지만 첫 호출 의미 유효는
`2/6 → 2/6`이고, 실제 034 연결은 실패했으며 028의 중복 READ가 생겼다.
제품 Query·Canonical 변경은 되돌리고 이 기록과 비활성 비교 도구만 남긴다.
Sufficiency 후보들의 출력 계약 강제나 미발견 일괄 BLOCK도 채택하지 않는다.

015는 034와 별개다. 저장된 과거 015는 Task Route 자체가 없었다. 009의
최신 RU/Route 연결에서는 Task business Route가 있지만 첫 Query가 누락했고,
Sufficiency는 Task title/notes/due/status 부족을 감지했으나 route_id 없는
Issue가 `ROUTE_RECONSIDERATION_REQUIRED`로 끝나 Task READ를 실행하지 못했다.
이번 D의 015 저장 Query 비교는 **과거 State**이므로 최신 015 해결 증거가
아니다. 015의 새 Query→READ→Evidence 연결은 미검증으로 남긴다.

다음 재시도는 RU `required_information`의 사실 owner를 Source 결정에서
어떻게 표현·검증할지, 그리고 Query의 container/item Route 역할을 한
호출에서 어떻게 구분할지 함께 평가해야 한다. 특히 003에서 기각한 원문만
남기기/양성 Source만 출력, 이번 A/B의 필드 나열, C의 Route 강제, D의
Resource type 단독 변경을 그대로 반복하지 않는다. 원문 키워드로
`TASK`를 강제하거나 `TASK_LIST` guard를 약화하지 않는다.

| Owner | 채택 변경 | 이번 비교·연결 | 잔여 실패 | 미검증 |
| --- | --- | --- | --- | --- |
| RU | 없음 | 034 owner 오류와 owner만 바꾼 합성 진단 분리 | 항목 fact가 container에 결속 | 새 표현의 복수 요청 비교 |
| Retrieval | 평가 결과 저장 개선만 | Sufficiency 7입력 A/B/C, Query 6입력 + 034/028 연결 | 034 실제 입력 후속 실패, 015 Task 미조회 | 새 후보의 실제 정보 충족 |
| Work Analysis | 없음 | 합성으로 owner 수정된 Evidence 1회 소비, 사실 5개 | 실제 034 Evidence 부재 | 실제 upstream 수정 후 의미 검토 |
| Planning | 없음 | 같은 합성 연결 Action 1개 | 최종 업무 성공 미판정 | 실제 upstream 연결 |
| Review | 기존 RECHECK 유지 | 같은 합성 연결 `CONFIRM` 확인 | 근거 부족/사용자 선택 분류 별도 | 실제 upstream·Live RECHECK |

이번 기록의 Query `4/6 → 5/6`은 저장 입력에서의 최종 검증 통과율이고
근거 확보율·업무 성공률이 아니다. 기준의 실패 호출 중 2 dispatch가
token/latency 0으로 기록돼 전체 비용 합계의 정확한 A/B 비교도 불가하다.
합성 Provider 결과와 이전 SHA의 034 LangSmith Trace만 확인했다. 새 제품
SHA의 백엔드 Run·실제 계정 READ·원격 Trace는 실행하지 않았고, 후보가
실제 연결에서 실패했으므로 Live 성공으로 표기하지 않는다. WRITE는 0이다.
원시 비교 결과는 ignored
`evaluation/results/retrieval-information-coverage-20260917/`에 보관한다.

## 후속 RU 현재 경계 단일 진단 (사전 조건)

저장 034의 이전 SHA Source 오류가 현재 RU에서 재현되는지 구분하기 위해
034와 원문이 같은 Core-023의 고정 request/checkpoint에서 현재 production
`identify_goal_with_budget → Tool Route`를 **1회** 직렬 실행한다. 현행
Prompt/Schema/모델 9B temperature 0 seed 1729, Provider/WRITE 0,
결과는 새 ignored 파일에 저장한다. 이 새 upstream Trial은 034 저장
input 반복도 아니고 후보 효과 비교도 아니다. Task item 필요 정보가
`TASK`에 결속되는지, `TASK_LIST`에 결속되는지와 Source 첫 추론·보정
호출을 분리해 기록한다. 이 한 번의 성공을 RU 안정성으로 채택하지 않는다.

현행 Core-023 단일 Trial은 Goal 조립과 Tool Route까지 Schema를 통과했다.
Source는 `GMAIL_THREAD`, `TASK`, `CALENDAR`, `CALENDAR_FREEBUSY`였고
`TASK_LIST`가 item 정보의 business owner로 남지 않았다. Tool Route도
`TASK`를 포함했다. 7 provider dispatch, 16,984/617 tokens, 25.4초
provider 지연이다. 이는 034의 이전 저장 Run과 다른 새 upstream 출력이다.
이 한 번은 034의 과거 오류가 현행 버전에서 항상 재현된다는 가설을
뒷받침하지 않지만 RU Source 안정성을 증명하지도 않는다. `CALENDAR`
container 과잉 가능성은 003의 기존 관측과 일치하며, 이번 결과를
Retrieval 확보·후단 성공으로 계산하지 않는다.

## Source 결속 영향의 paired 확인 (사전 조건)

앞서 저장한 owner 교정 합성 입력과 **동일 fingerprint**에서 기존 coarse
Query를 1회 Query→합성 READ→Evidence까지 연결한다. 이미 수행한 D exact
Query Trial과 분리된 순차 paired 비교로, provider/model 조건은 동일하다.
기준 Query도 Task item 근거를 확보하면 D의 `034` 조회 이득이 exact type
단독 효과가 아니라 Source 결속에 의존한다고 판단한다. 새 upstream/Gold
Evidence를 끼워 넣지 않고, 실제 업무 성공률로 계산하지 않는다.

동일 owner 교정 합성 upstream fingerprint `6fc3cbdf…`에서 기존 coarse
Query도 Task item Evidence 1건을 확보하고 `SUFFICIENT`로 Work Analysis에
전달했다. 기준/D 모두 Retrieval LLM 4회였고, 기준은 합성 READ 6회·
provider 지연 48.3초, D는 READ 7회·52.2초였다. D의 추가 READ는 TaskList
discovery로, 이 비교에서 근거 확보 이득이 없었다. 따라서 034의 최종
근거 확보 차이는 Resource type 단독 투영보다 **RU의 item fact owner
결속에 더 민감**하다. 단, 이는 실제 RU가 아닌 owner를 바꾼 합성 입력이며
현행 RU의 여러 Trial 안정성이나 실제 Provider 결과를 증명하지 않는다.

제품 코드·Prompt·Canonical은 기준과 동일하게 유지했다. 평가기/인접 구간
직접 영향 테스트는 Retrieval 597개, RECHECK·Preview 10개 통과했고,
ruff 검사와 세 비교기의 post-revert fixture/preflight 기록을 확인했다.
이 테스트는 새 제품 개선의 의미 검증이 아니라 기존 계약 비회귀 확인이다.
