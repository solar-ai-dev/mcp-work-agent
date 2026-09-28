# 064 — Semantic authority order and deterministic binding

## 실행 전 고정

기준 Product HEAD `4f07c3b5`, 현재 Production과 062 v4를 보존한다.
063의 v6/v7/v8/v9/v10은 재실행하지 않는다. 후보 REJECT는 다음 근거 선택이지
전체 작업 종료 조건이 아니다. 상세 raw는 `evaluation/results/064-*`에 보존한다.

원문/골드 authority와 기존 063 corrected semantic review를 사용한다. 평가 점수는
owner 단독, RU→Route 연결, Retrieval 이후 업무 성공을 분리한다. Gold·Fixture·실제
Provider 데이터는 변경하지 않는다. 실제 Provider READ/WRITE/SEND는 0으로 유지한다.

### 확인한 최초 경계

- v4 CORE-009: WorkUnit exact span은 정상. 첫 Goal에 READ를 외부 변경으로 바꾼 뒤
  requested_outputs와 마지막 requested_result_mode도 그 해석을 따른다.
- v8 CORE-025: 모든 Source 선택 중 GitHub가 추가되어 repository authority guard가
  Confirmation을 반환했다. ambiguity 모델 오판이나 Calendar 검색 실패가 아니다.
- 검증된 parent Source를 merge에서 원문 regex로 제거하는 잔존 경계는 별도 코드 결함으로
  직접 회귀 테스트한다. Source LLM의 과선택을 deterministic 삭제로 숨기지 않는다.

### v11 — one-call authority generation order

v4의 입력, Prompt, 허용 schema 값, semantic owner, 모델·sampling을 유지한다.
출력 순서만 `requested_result_mode → requested_outputs → goal/conditions/constraints`로
바꾼다. 생성한 Goal이 결정 전 해석을 고정하는지 검증한다. v5와 달리 동일 호출에서
Registry context를 볼 수 있고, 새 분류·규칙·추가 LLM 호출은 없다. schema는 어떤
업무 정답을 강제하지 않는다. 값 검증 언어는 v4와 동등해야 한다.

Core 009/012/013/019/023/025/027/049/059의 기존 v4 실제 Goal 입력을 frozen replay,
각 1회, repair 최대 1회로 고정한다. READ/WRITE·Draft/SEND 반례, 모호한 시간,
복합 산출물, Source 혼동을 포함한다. 기존 raw 동일 owner와 먼저 비교한다.
명백한 회귀면 반복/전수 확장하지 않는다. 유력할 때만 compiled RU→Route와
고정 2회 반복으로 넓히며 확대 Case/횟수는 실행 전에 추가 기록한다.

실제 runtime: qwen3.5:9b의 설치 digest 확인, temperature=0, seed=20260923,
think=false, num_ctx=16384. 실패·repair도 transport 수준으로 계수한다.

## Ownership

| 의미 | producer | validator | state/projection | consumer/revision |
| --- | --- | --- | --- | --- |
| v11 결과/목표 | v4와 동일 공동 owner, 생성 순서만 변경 | 기존 구조·ID·mode 일관성 | 기존 Goal + cached Output | 기존 RU merge/Route, revision은 producer |
| Source 보존 | 기존 Source owner | 기존 Source contract | merge에서 그대로 보존 | Route shared READ; 의미 수정은 Source owner |

Production Prompt activation, Approval/Permission/Execution/Verification/Recovery는
변경하지 않는다. 실험 artifact를 release에 포함하지 않는다.

## 다음 축 — v12 Source inference runtime (실행 전)

v11에서는 실제 generation mode-first를 확인했고 009의 불필요 WRITE가 사라졌다.
그러나 027의 Goal이 업무 마감을 메일 발송 시각으로 바꾸는 등 의미 손실도 있어
아직 Production 채택 후보로 확장하지 않는다. 결과 전체와 회귀를 먼저 판정한다.

기존 Source 원문·schema·Prompt·sampling을 바꾼 후보가 계속 같은 Source 누락을
보였으므로 다음 축은 판단 runtime이다. 설치된 같은 qwen3.5:9b의 `/api/show`가
`thinking` capability를 반환했다. 새 모델로 교체하거나 판단 규칙을 추가하지 않는다.
기존 frozen Source8(001/013/019/023/025/027/045/049)에서 **Source 호출의 think만 true**로
설정한다. v4 실제 owner 입력과 동일하며 각 1회, 기존 timeout/repair 한도 유지.
기존 063 think=false raw와 비교하되 runtime 차이를 숨기지 않는다. 사고 본문은
기록하지 않고 응답 여부·길이·전체 output tokens·latency만 관측한다. 개선될 때만
connected 비교를 사전 고정해 넓힌다. Source 의미 실패를 숨기는 validator 보정 없음.

### v12 결과와 v13 transport 대조 (실행 전)

설치 Ollama 0.34.0. v12는 첫 3 Case가 첫 출력·repair 모두 최종 content가 비었고
thinking metadata만 있었다. 총 6 dispatch 후 기존 circuit breaker가 뒤 5 Case를
모델 호출 없이 차단했다. 따라서 8개 의미 실패가 아니라 transport 결과 없음 3건,
runtime 차단 5건이다. JSON을 사고 본문에서 추출해 성공 처리하지 않는다.

Ollama 공식 structured-output 예시는 `/api/chat`을 사용한다:
https://docs.ollama.com/capabilities/structured-outputs
과거 issue는 환경이 다르므로 이번 설치의 원인 증명으로 사용하지 않는다.
다음 v13는 v12의 동일 Source 입력·schema·think=true를 유지하고 endpoint만 chat으로
전환한다. system/prompt를 messages 역할로 전달하고 최종 content만 소비한다.
우선 Core001/013 각 1회 preflight로 compatibility를 확인한다. 여전히 최종 content가
없으면 더 넓히지 않고 이 runtime 축을 기각한다. 통과할 때만 나머지 frozen Core6을
각 1회 이어서 실행한다. 기존 v12 실패는 보존하며 대체하지 않는다.

## Source scope 표현 공백 — v14 (실행 전)

현재 persisted Constraint는 work-local `SCOPE.required_sources/forbidden_sources`를
지원하고 Policy가 소비하지만 Goal producer의 출력 schema에는 이 두 필드가 없다.
금지가 올바르게 typed 생성되더라도 direct READ는 기존 scope 검사에서 빠졌다.
후자는 모델 필요 없는 consumer 안전 결함으로 기존 확인 경계를 복구한다.

v14는 별도 evaluation context에서 기존 `additional_constraints`에 위 두 필드만
표현 가능하게 한다. 이미 있는 category EMAIL/TASK/CALENDAR/ISSUE와 `work_unit_ids`를
사용하고, 의미 판단은 기존 Goal owner가 한다. 문자열 parser·scope 강제·새 State 없음.
일반 업무값 및 Source 제한이라는 필드 설명 외 Prompt 규칙은 추가하지 않는다.
Schema/normalization은 같은 표현 계약으로 연결하며 exit 시 기존 schema로 복구한다.

Core002(명시적 전체 Source 제외),001/004(선택 identity의 다른 대상 검색 제외),009
(복수 근거 대조),013(근거 한정과 외부 결과)을 기존 v4 frozen Goal 입력으로 각1회.
v4 원본과 비교하되 source scope만이 아니라 Output/조건 회귀도 본다. selected Resource
밖의 탐색 금지를 전체 Resource category 금지로 확대하면 실패다. 유형별 작은 검증을
통과하기 전 Production schema/Prompt에는 반영하지 않는다.

## Production deterministic 결함 교정

`6d97adf5`는 검증된 parent Source 삭제, shared READ binding 누락,
Source 정보×WorkUnit 교차 귀속, Policy READ의 전체 WorkUnit 과결속을 교정했다.
`099bb52e`는 direct Source READ도 현재 WorkUnit의 typed Source scope와 기존
범위 확장 receipt를 검증하도록 했다. 확인 전 Registry READ materialization은 0이고
정확한 현재 intent revision/interrupt receipt만 통과한다. 모델이 자연어 금지를
올바르게 생성한다는 증명은 아니며 그 표현 공백은 v14로 별도 평가한다.

- 관련 RU/Route/Planning/execution/verification/approval/architecture: 최초 618 PASS.
- direct scope 추가 후 넓힌 검증: 632 PASS, 2 FAIL.
- 2 FAIL은 시작 SHA와 동일한 기존 evaluation architecture 위반이다. test 파일 변경0,
  기존 allowlist 외 Python 15개, 기존 7파일의 Product import 25개가 경로·라인까지 동일.
  assertion/allowlist를 완화하지 않았고 이 두 gate를 PASS로 보고하지 않는다.
- 새 평가 adapter/관측/script tests: 81 PASS, 기존 1 SKIP. 제품 의미 점수와 구분한다.
- 모델 후보는 계속 비활성이다. Product Prompt/activation/Registry/Approval 실행 의미 변경0.

Source scope 확인 개선은 새 권한을 부여하지 않는다. 기존 V3 WorkUnit binding을
소비하여 무관한 업무의 제한을 전역화하지 않고, 필요한 READ의 한 적용 업무라도
제한되면 기존 확인을 요구한다. persisted artifact schema와 resume version은 불변이다.

## v11~v14 고정 진단 결과

| 후보 | 관측 | 판단과 다음 축 |
| --- | --- | --- |
| v11 생성 순서 | 동일 frozen Goal 입력 9/9, 첫 출력 schema 9/9. 009의 불필요 WRITE 제거, 049의 추가 시각 제거. 반면 025는 Source를 제목 요구로, 027은 업무 마감을 메일 발송시각으로 바꿈 | REJECT: 일부 개선만으로 채택하지 않음. `064-goal-order-review.json`에 원문 의미 비교 보존 |
| v12 Source think=true | 첫 3 Case의 첫 출력+repair 6회 모두 최종 content 없음. 뒤 5 Case는 기존 circuit breaker가 dispatch 없이 차단 | REJECT: 모델 의미 점수가 아니라 runtime compatibility 실패. 사고 본문을 답으로 사용하지 않음 |
| v13 chat+think=true | 001/013 각 한 번, 각각 180초 timeout. 최종 content/usage 없음 | REJECT: 나머지 6건 확대하지 않음. 원인 확정 또는 runtime 변경 근거 없이 반복하지 않음 |
| v14 기존 Source scope 필드 노출 | 5/5 반환/schema 통과, 5개 모두 additional_constraints=[]; 002의 명시적 Source 제외와 013의 Source 한정이 typed scope로 생성되지 않음. 009 기존 불필요 WRITE도 지속 | REJECT: schema 표현 가능성만 열어서는 의미 생성 개선 없음. Source 판단을 제외한 Goal owner와 범위 제한 ownership을 재검토 |

001/004의 다른 객체 탐색 금지를 전체 EMAIL/CALENDAR 금지로 만들지 않은 것은
필요한 반례 확인일 뿐, 해당 제한이 downstream까지 보존됐다는 증명이 아니다.
completion의 미래 완료 조건을 실제 Provider effect 발생으로 채점하지 않는다.
v14의 CLI 첫 시도는 잘못된 candidate 이름으로 argparse에서 종료됐고 모델 호출 0이다.
정정 명령의 사전 고정 5회만 실행했으며 실패 Trial을 대체하지 않았다.

| 범위 | dispatch | input/output tokens | reported ms | wall ms | usage 미확인 |
| --- | ---: | --- | ---: | ---: | ---: |
| v11 Goal9 | 9 | 25,268 / 3,565 | 137,852 | 138,207 | 0 |
| v12 Source8 | 6 | 24,508 / 2,531 | 98,851 | 100,064 | 0 |
| v13 Source2 | 2 | 미확인 | 미확인 | 360,323 | 2 |
| v14 Goal5 | 5 | 14,927 / 1,518 | 59,166 | 59,381 | 0 |

v12 output token은 최종 답변 토큰이 아니다. v13의 raw 집계 0은 usage 미수신이며
0-token/0-latency 실행이 아니다. Owner replay를 업무 PASS나 새 92개 점수로 표현하지 않는다.

Raw(ignored, 원격에는 위 요약과 비민감 수동 판정만 보존):

- `evaluation/results/064-ordered-goal-v11-t1/raw.json`: `6d668dece516f0193e256265bda90fe1d2bc3a2c21af05796d2b3bd2a945cdfd`
- `evaluation/results/064-source-thinking-v12-t1/raw.json`: `7be8e9c710fc6d6674e7b1fdc326b928c6d9535dc55a9f908f6e79539f70478a`
- `evaluation/results/064-source-chat-thinking-v13-preflight/raw.json`: `a64964a97f7f284f7359522cb0e0c17edef7f4c11bba8f6065fedc76a6aca57e`
- `evaluation/results/064-source-scope-v14-t1/raw.json`: `7a52b237e06c5d04e17f8b93c35401152931f6831994c602fdbe9720eb4eec42`

## v15 Source family → subtype — 실행 전 계획

기존 v6/v7/v9/v10의 32 replay 중 반환28건을 재검토하면 명시 Source family 누락이
12건이며 단순 container/item 혼동은 주원인이 아니었다. 원문을 생성 needs로 대체한
v7과 달리 첫 판단을 기존 coarse Resource category membership에만 한정한다.
원문·선택 identity·WorkUnit은 그대로 두고, 다음 기존 Source owner에는 같은 원문과
선택 family의 Registry 후보를 한 번에 전달한다. family별 호출 복제·키워드 추출·Goal
재생성은 하지 않는다.

Core001/002/013/023/025/027/045/049의 같은 v4 frozen Source 입력을 각1회 실행한다.
family recall/과잉 family → subtype → required_information → schema를 분리해서 확인한다.
첫 판단의 잘못된 제외는 후단에서 복구하지 못하는 새로운 위험이다. 악화되면 규칙을
추가하지 않고 후보를 기각한다. ISSUE positive가 없으므로 그 의미 정확도는 미검증이다.
보통 Source1→2call, family가 없으면 후단0call이다. 품질 이득 없는 호출 증가는 채택하지
않는다. 이 후보만으로 Goal/Output·Source 범위 제한의 잔여 문제가 해결됐다고 하지 않는다.

## v16 Source 범위 Constraint의 producer/consumer 어휘 정합화 — 실행 전

v14는 필드만 열고 Goal Prompt의 'Source를 판단하지 않는다'와 additional_constraints의
'명시적 실행 값' 설명을 그대로 두었다. 반면 consumer는 required_sources를 조회 필요성
목록이 아닌 **배타적 허용 category**로 소비한다. 이름만 열어서는 owner 계약이 닫히지 않는다.
기존 Goal의 Constraint ownership은 유지하고 Source responsibility/capability 선택만 별도
owner라는 뜻으로 기존 문장 한 곳을 한정한다. Schema 설명도 기존 consumer의 범위 뜻과
정합화한다. v14와 같은 허용값/필드/cardinality/normalizer이며 새 Node/State/규칙 예시는 없다.
선택 identity 내부의 다른 객체 탐색 금지를 category 전체 금지로 확대해서는 안 된다.

기존 v14와 같은 Goal frozen Core002/001/004/009/013 각1회. scope의 개선과 Goal/Output
회귀를 함께 확인한다. 단발 개선이면 다음 검증은 compiled owner/소비 경계이지 더 많은
Prompt 문구 추가가 아니다. 이 후보도 사용되지 않으면 표현만의 문제가 아니라 원문과
제약의 결속 구조를 다시 검토한다. 실제 Provider I/O는 0으로 유지한다.

## v15 결과 → v18 positive handoff (실행 전)

v15는 8/8 반환/schema 유효지만 의미 성공은 아니다. family 선택은 013의 Output 초안을
EMAIL Source로 오인한 1건을 제외하면 필요한 family를 포함했다. 그 뒤 기존 Source owner가
025 EMAIL+TASK, 027 TASK, 045 전체, 049 EMAIL+TASK를 다시 NOT_REQUIRED로 바꿨다.
023은 필요한 family가 있지만 불필요 Draft도 추가한다. 001/002의 실제 selected identity
결속은 Route를 실행하지 않아 미검증이다. family 선택의 오류와 다음 owner의 삭제를 분리한다.

v18은 v15의 실제 Stage1 raw(오답013 포함)를 **같은 원문/선택/WorkUnit/catalog hash일 때만**
재사용한다. 새 Stage1 호출0. Stage2 입력에 확정된 selected_source_families를 명시하고
각 family 안에서 하나 이상 구체 Source를 선택하는 계약으로 닫는다. subtype·조회 정보는
모델이 판단하며 validator가 답을 대신 만들지 않는다. family 필요 여부를 후단에서 다시
생성하지 않는 typed handoff 후보로, schema만 바꾼 실험이라고 표현하지 않는다.
Product Prompt allowlist에 몰래 필드를 추가하지 않고 evaluation-owned Prompt ID/입력/
책임 설명을 사용한다. 원본 Source 설명에 handoff 책임을 붙인 hash도 기록한다.

Core001/013/025/045 각1회 Source refinement, repair 기존1회. 원래 family가 틀린013을
의미 성공으로 세지 않는다. family retention, 실제 subtype/facts, 최초/repair 의미를 분리한다.
잘못된 family가 고정되는 위험 때문에 retention 자체는 품질 향상의 충분조건이 아니다.

### v16/v18 실제 결과와 다음 handoff 축

v16: 5건 모두 첫 출력/schema 유효지만 002/013의 category 범위 제한은 여전히 누락됐다.
004는 required_sources=[CALENDAR]를 생성했으나 이는 다른 Calendar 검색 금지의 정확한
표현이 아니다. 001의 다른 메일 검색 금지도 typed scope로 보존되지 않았고 009의 잘못된
Draft+Task CREATE가 지속됐다. **REJECT**, 문구·설명을 더 누적하지 않는다.

v18: 4건 중 3건 반환, 025는 첫 출력과 기존1회 repair 모두 EMAIL/TASK 결속을 빠뜨려
schema 실패로 남았다. 045는 앞서 제거됐던 세 family를 유지했으나 subtype/fact 정확성과
후속 사용은 별도다. 013은 기존 잘못된 EMAIL/Draft 판단을 그대로 보존해 의미 실패다.
001은 Thread 외 Message도 추가했으며 실제 selected-route 중복 여부는 미검증이다.
**REJECT**: positive retention guard는 손실을 탐지하지만 스스로 의미 판단을 개선하지 못했다.
v18 family0 cached logical-call 관측은 실험 뒤 테스트로 수정했다. 이번 4건은 모두
nonempty family여서 실제 실행·채점·raw는 변경하지 않았다.

| 범위 | 실제 신규 calls | input/output tokens | reported/wall ms |
| --- | ---: | --- | --- |
| v15 Source8 | 16 | 33,130 / 1,378 | 67,597 / 69,184 |
| v16 Goal5 | 5 | 15,217 / 1,536 | 60,214 / 60,388 |
| v18 Source4 refinement | 5 | 15,098 / 1,028 | 43,627 / 43,825 |

v18의 Stage1은 이전 실제 결과 재사용이며 0회로 숨긴 신규 추론이 아니다. Production 적용 시
Stage1 비용도 다시 필요하다. 위 숫자는 scope가 다르므로 후보간 총비용 우열로 비교하지 않는다.

- v15 raw hash: `99e5a44433ef35a4b8d6c5f6cd3535697252b179356be24ae541342ad8a0399e`
- v16 raw hash: `cb2dff3b5f5a375f24450f33be9081b45c1fc29c13fd4f827293b2dbe1601d77`
- v18 raw hash: `dd507a2fd46f1a39b7e88ecdf7b80c80b659ae8c86208064358ed379c6b1ff08`

`67e68be5`의 연결 회귀2건은 실제 compiled ToolRouting·Planning과 실제 Query/READ/finalize
소비 경계를 확인했다. shared READ는 fake Connector dispatch1/Evidence1로 WorkUnit2개에
결속되고, 독립 Draft는 같은 capability에서도 Route/Action2 및 각각의 수신자를 유지한다.
ANSWER 호출은1이다. acquisition/selection은 fixture이고 실제 모델 의미나 전체 Retrieval
workflow 검증이 아니다. 이번 새 후보/관측/연결 관련 검증은 69 PASS다.

다음 원인 가설: v4 Goal 호출에서 Output이 이미 생성됐지만 Source에 그 typed 역할은
전달되지 않고 Source 이후 Output operation에서만 cache를 반환한다. 기존 joint schema 통과를
effect-prohibition 검증까지 마친 확정으로 혼동하지 않는다. 앞에서 기존 Output validator와
동일 WorkUnit 금지 검증을 먼저 적용한 읽기전용 역할 handoff를 평가한다. 전체 역할을 한 번에
다시 생성한 v8과 달리 Source만 판단하며 원문/WorkUnit/선택/Output을 변경하지 않는다.

## v20 Output → Source handoff — 실행 전 계획

Core001/009/013/023/025/027/049/060 각각1회 Source replay. 같은 v4 기록의 실제 GoalOutput,
effect prohibitions, Source input을 hash로 연결하며 Gold를 입력하지 않는다. READ-only와
upstream WRITE 오판, 신규 Draft, 복수 Source 성공/실패, 금지, 복합 CREATE, Task UPDATE를
포함한다. Source가 009의 잘못된 Output을 후처리로 고쳐서는 안 된다. CREATE와 같은 Resource의
기존 Source를 삭제하지 않으며 UPDATE의 기존 상태 읽기도 보존한다.
새 field는 evaluation-only input 계약에서 선언하고 Product loader/Prompt activation은 유지한다.
이득이 있으면 actual upstream을 쓰는 compiled RU→Route로 비교를 확장하며, replay 성공만으로
Production을 채택하지 않는다.

## v21 생성 Goal 제거 — 실행 전 계획

v11과 같은 Core009/012/013/019/023/025/027/049/059의 frozen Goal 입력을 각각1회 사용한다.
v11의 mode→Output 순서와 나머지 판단은 유지하고 생성 schema에서 goal만 제거한다.
제품에 전달되는 goal은 현재 user_request 원문을 deterministic하게 복사한다.
원시 모델 출력과 deterministic projection은 별개로 보존한다. 완료조건은 실제 관측 가능한
업무 완료의 의미를 담아야 하므로 raw span으로 대체하지 않고 기존 owner가 판단한다.
Source는 이미 원문 extractive projection을 받으므로 이 후보를 Source 원문 복원으로
보고하지 않는다. 생성 Goal만 제거해도 Output/조건 오판이 남으면 그 실패를 그대로 기록한다.
이 후보는 confirmation resume 의미·후속 Planning의 Goal 계약까지 검증한 제품 변경이 아니다.

### v21 결과

9/9 첫 출력/schema 유효, 신규9calls, input25,034/output3,353tokens,
reported129,269ms/wall129,636ms. v11과 같은 frozen 입력을 사용했다.
원문 Goal은9/9 정확하게 전달됐지만 의미 성공을 보장하지 못했다.
009는 v11 ANSWER에서 불필요 GMAIL_MESSAGE/SEND로 회귀했고, 023은 확인할 기존 Task가
완료됐는지를 완료조건으로 바꾸었다. 049는 CREATE/due는 유지되지만 completion의
'작업 완료'가 생성 완료인지 업무 수행 완료인지 불명확하다. 실제 UPDATE 지시로 단정하지 않는다.
025의 잘못된 title 강제와027의 메일 발송시각 치환은 사라졌지만, 원문 보존과 생성된
Output/완료조건 사이의 충돌은 남는다. 027은 정보 부족 시 한계 답변 대신 있음/없음을
확정하도록 요구하는 위험이 남는다. 012/013/019/059의 요청 Output은 유지됐다.
REJECT: 단순히 Goal 재서술을 제거하는 것만으로 공동 해석이 안정되지는 않았다.
Source/Route/Planning은 이 replay에서 실행하지 않았다.

raw: `evaluation/results/064-grounded-goal-v21-t1/raw.json`
SHA256: `93cdd9e5fd99eb38e77447ed06cc8fa71b71f7f3c85e2a1bcc5f5e18c1a9473a`.
최초 CLI 호출은 모듈 경로 오류로 모델 호출 전에 종료했고, `python -m scripts...`로
정정했다. 실패 Trial을 재실행한 것이 아니며 위9건 외 모델 호출은 없다.

### 실제 Runtime 조건 정정 (감사 진행 중)

runner의 sampling_temperature=0.0 설정은 모든 owner의 실효값이 아니다.
Product router는 Goal0.1/Source0.05 등을 prompt별로 override한다.
v15 family는0.0, 기존 Source owner는0.05였고, v18 직접 Source adapter는0.0이었다.
따라서 v15↔v18을 sampling까지 같은 단일변수 비교로 표현하지 않는다.
실패 raw는 그대로 보존하며 비교 제한을 추가한다. v20은 기존 Source router 정책을
직접 재사용하고 first/repair의 actual transport sampling도 별도로 기록한다.

## v22 Source의 동일 입력 중복 envelope 제거 — 실행 전 계획

runtime 감사에서 Product Source는 동일 입력 JSON을 system assembly와 user prompt.input에
두 번 전달하는 것으로 확인됐다. v10은 schema 본문 중복만 제거했으므로 이번 input 중복은
다른 미검증 축이다. 중복이 의미 실패 원인이라는 결론은 아직 내리지 않는다.
현재 Product Source 경로의 FIRST 호출에서 system에 동일 JSON이 이미 존재함을 검증하고
wire prompt.input 복사만 제거한다. system bytes, Prompt 의미, schema 본문/format, 모델·
seed·실효 temperature0.05·timeout은 유지한다. revision/repair는 다른 정보이므로 그대로
유지하고 별도로 기록한다. precondition 불일치는 dispatch 전 오류이며 조용히 조건을 바꾸지 않는다.

Core001/013/019/023/025/027/045/049: 같은 v4 frozen Source 입력에 현재 Product 대조1회,
v22 후보1회. source owner 입력·actual sampler를 맞춘 새로운 paired 진단이다.
새 Schema·Source 규칙·Few-shot을 추가하지 않는다. 과거 다른 집합의 결과로 성공률을 주장하거나
성공할 때까지 반복하지 않는다. Source recall/과잉/대상·사실 결속/repair/토큰·지연을 비교한다.
대조와 후보 각8개가 범위이며, 의미 개선이 없으면 추가 반복·전수평가는 하지 않는다.

### v20/v22 결과

v20은 Output authority/input 검증8/8, first schema7/8→repair후8/8이다. 그러나
013은 불필요 Draft까지 조회하고, 023/025는 Google Source9종을 전부 선택하며,
049는 이전 Event Source마저 없앤다. 009는 upstream의 잘못된 Output을 보존한 상태라
새 Output 오류로 이중 집계하지 않는다. 060의 UPDATE snapshot 필요는 유지한다.
**REJECT**, Output 역할을 알려줬다는 사실만으로 Source 의미가 안정되지 않았다.

v22는 같은 actual input/schema/system/model/temperature0.05/seed/timeout을 쓰는
fresh Product 대조와 비교했다. 025는 Mail·Task가 사라지고,027은 Mail·Task 마감 근거를
버린 뒤 원문에 없는09:00~10:00 조회창을 required_information에 생성한다. 013은
첫 출력부터 Draft만 선택한다. 비용 감소는 있지만 의미 회귀 때문에 **REJECT**다.
대조 HEAD7a60e505→후보6c5630a9는 confirmation 병합 수정이며 frozen Source 호출의
입력·코드 변화가 아니다. 같은 전체 제품 SHA의 connected 평가로 표현하지 않는다.

| 범위 | calls/repair | input/output tokens | reported/wall ms |
| --- | --- | --- | --- |
| v20 Source8 | 9/1 | 37,527/2,267 | 99,915/100,320 |
| fresh Product Source8 | 9/1 | 36,559/1,792 | 84,063/85,471 |
| v22 Source8 | 8/0 | 25,195/1,602 | 69,785/71,120 |

- v20 raw SHA256: `87d476d2badd5323c075a7851a165246d6d9e521cf42897f752f2da90b3755d1`
- paired baseline raw SHA256: `3f8ae5d4cfe28f0ba306558e0a7ac4aa152114d4593bf66947acb070c33c6ef5`
- v22 raw SHA256: `2b397faf0754a4bfe22e86d3a2fefa76cccf72dfb20ab07b4a49cfe7ed22ffa6`

추가 최초 손실을 분리했다. fresh baseline013의 첫 출력에는 Task+Event가 이미 있었다.
TaskList/Task 중복과 누락 후보를 고치는 schema repair가 이를 전부 NOT_REQUIRED로
바꿨다. v20은 같은 첫 의미를 schema-valid하게 내서 repair 손실을 피했을 뿐이다.
따라서 'Output 전달로 처음 Task/Event를 이해했다'는 인과 설명은 사용하지 않는다.
다음 축은 이미 유효한 Source 항목까지 다시 생성하는 **repair 수정 범위**다.

### 확정 코드 결함 수정 추가

`6c5630a9`: confirmation merge가 kind/field/value만으로 중복 제거해 다른 WorkUnit에
같은 수신자 등을 확정한 결과를 버리는 결함을 수정했다. provenance와 Source binding까지
동일한 항목만 제거하며 valid status/Goal/Output/금지는 보존한다. RU·Route·Planning·연결
소비 경계 관련553 PASS. Product Prompt/Schema/Node/안전 경계 변경0, Provider I/O0.

Planning의 route-local Intent는 두 endpoint가 같은 Route 안에 없으면 업무 관계를 제거한다.
기존 canonical에 이 관계의 별도 context 입력 계약이 없었다. 비활성
`planning_work_relation_context_candidate.py`는 들어오는 관계와 양끝 provenance만
별도로 전달하고 타 업무의 Output/조건을 현재 Route로 되살리지 않는다. 직접10 PASS지만
이는 관계 metadata 전달이며 실제 내부 WorkProduct/계획명세 소비 성공은 아니다.

## v23 Source item-local schema repair — 실행 전 계획

first에서 고유 closed Resource ID이며 개별 schema가 유효한 항목은 그대로 보존한다.
서로 모순된 중복 항목은 어느 쪽도 코드가 선택/union하지 않고 해당 Resource만 수정 대상으로
둔다. 누락 Resource의 판정도 모델이 하며 NOT_REQUIRED를 자동 생성하지 않는다.
원문/WorkUnit/기존 Source owner/실효 Runtime/repair1회 한도는 유지한다.
parse 실패·unknown identity·분해할 수 없는 cross-item 제약은 기존 full repair로 위임한다.
최종 full schema와 기존 범위 guard를 통과해야 하며 guard를 우회하지 않는다.

먼저 새 첫 호출 없이 fresh Product baseline의 CORE023 정상 first(새 모델0회),
CORE013 실패 first(새 repair 최대1회)를 재사용한다. 원본 파일/input/schema/모델/실효
sampling을 검증하고, 과거 first와 새 repair의 비용·원시 출력을 분리한다.
v20 CORE001은 다른 evaluation 입력에서 생성돼 같은 Production 조건으로 혼합하지 않고
구조적 직접 테스트 참고로만 사용한다. synthetic 반례는 모델 품질 점수로 세지 않는다.
본질적으로 틀렸지만 구조적으로 유효한 Draft 결정도 freeze한다. 따라서 보존에 성공해도
business PASS나 첫 Source 의미 개선으로 표현하지 않는다.

### v23 결과와 generic repair guard 수정

정상023 first는 그대로 반환해 신규 모델0회다. 013은 신규 repair1회,
input3,533/output58tokens, reported9,619ms/wall9,679ms를 사용했다.
고유·개별 schema-valid 항목6개는 모두 정확히 보존됐고 full schema 및 기존 outer guard를
통과했다. Event REQUIRED는 보존됐지만 mutable Task/TaskList는 모델이 NOT_REQUIRED로
판단했다. 구조상 유효하지만 의미상 잘못된 Draft REQUIRED도 그대로 남는다.
따라서 **repair handoff 보존 확인 / 업무 의미 실패 유지 / Production adapter 채택 보류**다.
새 첫 응답이나 성공 Trial 대체는 없다. Source owner 뒤 Retrieval/Planning은 실행하지 않았다.

raw: `evaluation/results/064-source-item-repair-v23-t1/raw.json`
SHA256: `3e0407b72e0366acebe89b6629b1c404e53854d5c696fd0e656ca07ffe81dec8`.

별도의 확정 Product 결함은 `67ce1c16`에서 수정했다. generic repair guard가 모순된 중복
또는 malformed/missing identity를 만나 전체 배열의 stable 비교를 포기하던 문제다.
이제 식별 가능한 peer를 별도로 검사하고 미식별 부분에는 기존 positional 제한을 유지한다.
모순된 duplicate의 어느 의미가 맞는지 코드가 선택하지 않으며 기존 repair budget/최종
schema/closed identity 제한을 완화하지 않는다. Source뿐 아니라 route_id 배열 반례도 포함한다.
guard/router/v23 직접62 PASS와 관련 adapter/Query/Review/RU231 PASS, 총293개 관련 검사
PASS. 실제013의 잘못된 full repair는 거절하고 v20의 정당한001 repair는 허용한다.
Product Prompt/Schema/Node 변경0, 외부 Provider I/O0이다. 이 guard 수정은 모델 의미
실패를 자동 복구하지 않으며 미승인 후보를 Product에 활성화한 것도 아니다.

## v24 기존 Source 범위 제약의 연결 계약 — 실행 전 계획

v14/v16은 Goal에 기존 SCOPE field를 열었지만 normalized category와 원문 span의
provenance, Source projection, 최종 Intent validator까지 연결되지 않았다. 기존
Goal Constraint owner는 유지하고 required_sources/forbidden_sources의 선택값과 정확한
원문 proof를 같은 item에 담아 기존 WorkUnit별 ScopeExpansionResolver까지 전달한다.
Source subtype 선택·필수 조회·Provider permission·선택 identity는 이 제약과 별개다.
category allowlist를 필요한 Source 목록으로 해석하거나 선택 Resource를 family 제약으로
낮추지 않는다. 원문의 특정 단어를 해석하는 코드나 새 semantic owner/call은 없다.

먼저 model-free connected invariants를 검증한다. 이어 v16과 같은 frozen Goal
Core002/001/004/009/013을 각1회(기존 repair최대1회) 비교한다. 실제 Goal 기본0/seed 및
입력은 같고 바뀐 schema/provenance/선언한 handoff 계약은 별도 hash로 남긴다.
Goal의 scope 누락을 projection이나 validator가 보충하지 않는다. producer 누락이 지속되면
contract closure만으로 개선됐다고 하지 않고 추가 Source/전수 실행으로 확대하지 않는다.
이 경계가 유력할 때만 실제 compiled RU→Route에서 성공·반례와 함께 연결성을 확인한다.

새 total Resource-key map은 이번에 실행하지 않는다. v9의 key map8/8은 이미 구조가
유효해도 Source 오판을 해결하지 못했고 fresh Product first8 중 exact-set 실패는1건이다.
v23은 그 repair 손실을 별도로 다룬다. 따라서 다시 형식만 바꾸는 모델 실험의 우선순위를
낮추고 typed Source 범위가 실제 소비자에 도달할 수 없는 계약 공백을 먼저 닫는다.

### v24 결과

연결 계약 직접·관련72 PASS이며 실제 Goal5회 비교는 first schema3/5,
repair 후4/5다. 002는 EMAIL allowlist를 생성했지만 원문 proof를 첫 응답·repair 모두
누락해 거절됐다. 001은 scope0으로 선택 identity를 category 금지로 낮추지 않았고,
004는 CALENDAR 허용 + EMAIL/TASK/ISSUE 제외를 생성했다. 원문은 다른 Calendar 검색
제외이므로 이 범주 제약은 정밀한 선택 identity 제한을 대신하지 못하고 과잉 제약 위험이 있다.
009는 앞선 Goal에서 이미 READ를 메일/Task 생성으로 바꿨고 repair가 잘못된 Message CREATE를
SEND로 수정했다. 최초 업무 의미 변경은 첫 Goal이며 schema 통과가 올바른 WRITE를 뜻하지 않는다.
013은 여전히 scope0이다. 다만 '작업·슬롯만'이라는 업무 개념을 특정 Provider category로
강제 생성해야 한다는 새 정답은 만들지 않는다. 실제 근거 획득 책임과 원문 한정 보존을
후속 연결에서 확인해야 한다.

신규7calls, input23,342/output2,451tokens, reported100,051ms/wall100,295ms.
raw SHA256: `37bd8c0d9ea87849eeec10648c4a331457190196f7ce63d9a6d2c74b08e6171a`.
경로: `evaluation/results/064-scope-handoff-v24-t1/raw.json`.
**연결 계약만으로 의미 안정화되지 않음 / Production 비활성 유지**.
새 Source 호출이나 Canonical92 실행으로 확대하지 않는다.

### Source-only 판정 범위 재검토

`064-source-semantic-boundary-review.json`은 Gold나 새 정답셋이 아니라 위 실제 raw9 Case의
관측 범위 재검토다. TaskList→Task, Calendar→Event dependency와 Thread/Message 공유 경로를
고려하면 Source Resource 이름만으로 업무 실패를 단정할 수 없다. 추가 READ도 자동 금지
위반이 아니다. 필요한 사실의 Source 책임 누락, route 접근 가능, 과잉 acquisition 위험,
실제 Evidence 확보·업무 성공을 분리한다. 기존 raw/점수는 수정하지 않는다.
v20의 기존 REJECT는 Product 미채택 기록으로 유지하되 전체 business 실패의 증명으로 쓰지
않는다. 013/023/025/027의 사실 접근 가능성 회복과049 메일 책임 누락을 함께 기록한다.

## v25 동일 scope 계약의 discriminated schema — 실행 전 계획

v24 CORE002의 첫 출력과 repair는 scope 값은 만들었으나 조건부 필수 proof를 둘 다
누락했다. 다음은 의미 규칙 추가가 아니라 동일 valid output 언어의 Schema 표현 비교다.
WorkUnit IDs를 기존 builder로 닫은 뒤 additional_constraints.items의 조건부
if/then을 ordinary / required_sources / forbidden_sources의 명시적 oneOf로 표현한다.
범주 선택이나 scope 생성 자체를 강제하지 않고 Goal/Source Prompt와 의미·provenance
계약은 그대로 유지한다. 6,600개 조합 및 malformed 반례에서 두 Schema의 허용/거절
동등성을 먼저 검사했다. 이로써 Ollama의 특정 Schema keyword 미지원이 확정된 것은 아니다.

v24와 같은 frozen Goal5를 각각1회, repair최대1회로 비교한다. 실제 scope 누락·잘못된
범주·Output 오판과 구조 누락을 별도 기록한다. 구조만 나아져도 의미 개선으로 표현하지 않는다.
v24 raw는 보존하며, 새 후보는 다른 Schema hash의 고정 비교로서 실패 Trial 대체가 아니다.

### v25 결과

first schema5/5, repair0으로 v24의3/5→repair후4/5보다 구조가 안정됐다. 002는
EMAIL 허용과 TASK/CALENDAR 제외 및 실제 원문 proof를 모두 생성했다. 반면001은
'다른 메일 검색 금지'를 TASK/CALENDAR/ISSUE 금지로 잘못 표현했고,004도 같은
identity/category 구분 오류 위험이 남았다. 009는 여전히 정보 요청에 Draft CREATE와
Task UPDATE를 추가했다. 013의 Draft CREATE/수신자와 내용 범위는 유지됐다.
따라서 **동등 Schema 표현의 필드 누락 감소는 관측 / 의미 안정화·Production 채택은 아님**.
추가 규칙이나 범주 강제 생성으로 이를 보정하지 않는다.

raw: `evaluation/results/064-scope-discriminated-v25-t1/raw.json`
SHA256: `b244d62179c8359e156212fcf5b3aa927c9a2928989095f74758f5cf512bd10f`.
신규5calls, input17,942/output2,436tokens, reported95,850ms/wall96,048ms.
기존 v24와 같은 Goal Prompt·frozen 입력·sampler이며 출력 Schema 표현만 다르다.
보호된 typed handoff의 직접 관련62 PASS와 실제 모델 의미 결과를 합쳐 성공률로 쓰지 않는다.

### frozen Source→connected component gate (모델 호출0)

Core001/013/023/027의 v20 Source와 같은 authority의 기존 raw를 재사용하되, 후속 owner
입력이 정확히 일치할 때만 과거 응답을 허용했다. 4건 모두 Source-status 입력이 달라져
`NEW_SEMANTIC_CALL_REQUIRED`에서 멈췄다. 과거 빈 status/ambiguity를 새 Source에 복사해
가짜 connected 성공을 만들지 않았다. 변경 없는 v4 finalized Intent의 실제 compiled
ToolRoute control4개는 반환됐지만 v20 성공으로 세지 않는다.

별도 deterministic merge→policy→Registry component에서013의 Draft와023의
Draft/Attachment가 업무 필수 READ인데 해당 fixture inventory가 비어 있음을 확인했다.
이는 과잉 acquisition의 구체적 위험이며, 실제 Query/Evidence/Sufficiency를 실행한
BLOCKED 판정은 아니다. 직접10 + 기존 connected2 PASS, 모델/Provider I/O0.
raw: `evaluation/results/064-source-frozen-connected-component-gate/diagnostic-final.json`
SHA256: `c188c4792bbb11d3d9dd224d7d388d38f2c017d56eda4563a38208676f2a4863`.

## 확정된 selected/confirmation binding 손실 수정

선택 Resource READ fast-path와 RU의 selected identity 보강이 기존 Source binding을
무시하고 전체 WorkUnit으로 넓혔다. 이제 같은 Resource의 확정 Source 또는 기존 대상
UPDATE/DELETE Output binding을 소비하며, Thread가 Message READ를 공유하는 기존 의미도
동일 helper로 보존한다. 복수 업무인데 귀속이 없으면 전체 업무에 주입하지 않고 기존
`REQUEST_EXISTING_RESOURCE_SOURCE_REQUIRED` Source revision을 사용한다. Goal/Output은
재생성하지 않으며 기존 1회 예산 소진·재실패 시 추정 binding을 만들지 않는다.
단일 업무의 유일한 binding과 selected exact identity authority는 유지한다.

confirmation 재개 때도 `required_information`을 전체 Source WorkUnit에 교차 적용하던
문제가 있었다. 정상 RU와 같은 binding별 canonical derivation을 재사용한다.
직접·관련 RU/ToolRoute/budget366 PASS. 후속 Sufficiency 수정과 함께 root 재검증한
RU/ToolRoute/assessor 직접 집합477 PASS. 모델/Provider0이며 업무 성공률 측정이 아니다.

## 실제 Policy→Registry→Sufficiency handoff 수정

순수 Task/Event CREATE의 policy READ에 Registry dependency reason이 추가되면,
정상 COMPLETE empty 조회도 business Evidence 부족으로 차단됐다. 반대로 명시적 business
Source와 policy READ가 합쳐져 reason이 POLICY로 바뀌면 empty 결과가 fast-path에서 잘못
SUFFICIENT가 됐다. 실제 Policy/Registry producer와 합성 acquisition/LLM을 연결해 수정 전
4 FAIL을 재현했다.

Sufficiency owner는 기존 `source_reads`와 route WorkUnit의 교집합을 먼저 확인하고
policy reason + 기존 dependency reason만 있는 조회를 구별한다. 명시적 business Source는
빈 근거로 통과시키지 않으며, COMPLETE가 아닌 policy 조회·미시도·unknown reason·불명확한
mixed legacy 입력은 계속 fail-closed한다. 모델의 SUFFICIENT 판단을 강제로 생성하지 않는다.
직접15 + 관련 assessor/Query(q19/EXHAUSTIVE)/Registry/Policy 합계202 PASS.
두 수정 모두 Product Prompt/State/Schema/Node·승인/실행 경계 변경0, 실제 모델/Provider0.
이 연결 결함 수정은 Source producer의 잔여 의미 오판을 해결했다는 주장이 아니다.

## 상태 집합의 READ argument lowering 손실

SourceStatus 귀속 감사 중 별도의 결정적 소비 결함을 재현했다. 이미 확정된 Query의
OPEN+CLOSED는 GitHub CLOSED 하나로, DRAFT+SENT는 Gmail AND 형태로 바뀌었다. 공유 READ의
한쪽 업무에 필요한 상태가 사라지므로 provider argument projection에서만 수정했다.
동일 상태의 중복은 제거하고 ANY의 상태 비제한 의미를 보존한다. keyword/container·Tool
authority·Route binding은 그대로이며 조회 횟수나 WRITE 권한을 추가하지 않는다.

공식 [Gmail search operators](https://support.google.com/mail/answer/7190?hl=en)의 OR group과
[GitHub repository issues](https://docs.github.com/en/rest/issues/issues#list-repository-issues)의
state=all 계약 및 기존 Connector enum을 확인했다. Provider 자체에는 연결하지 않았다.
수정 전 직접14개 중7 FAIL, 수정 후 keyword 결합 반례를 포함한15개와 관련 projector/Connector
총87 PASS. Task/Calendar의 모든 상태 materialization을 검증했다는 결과는 아니며,
SourceStatus producer의 잘못된 WorkUnit union은 별도 비활성 후보로 검증 중이다.

## Query 업무 귀속의 수평 수정

1. exact anchor: mail/work-1 Alpha와 Task/work-2 Beta가 전역 수집돼 Gmail에서 Beta만
   검색한 Query도 schema·validator를 통과했다. 현재 Route WUID와 교차하는 Constraint만
   projection/keyword·participant schema/초기 validator/CONCEPT 사용 조건이 함께 소비한다.
   initial/follow-up Route에도 frozen WUID를 그대로 전달하며 shared READ union은 유지한다.
2. 정책 shortcut: Calendar/Task CREATE의 policy READ와 업무 Source가 겹쳐도 전체 초기
   조회가 새 생성 대상의 정책 검색으로 확정됐다. 실제 Source·검증 selected ref가 있으면
   기존 planner로 전달한다. 순수 policy의 deterministic/LLM0 경로는 유지한다.
3. 기간: 별개 업무의 기간을 전역 집계해 없던 필터를 적용하거나 실제로 각각 해석 가능한
   기간을 충돌로 오인했다. 동일한 route constraint projector를 사용하고, 공유 Route는
   모든 적용 업무의 기간·axis가 동일하게 확정될 때만 결정적으로 결속한다. 하나의 업무만
   기간이 있으면 다른 업무에도 적용하지 않는다. 다른 기간을 코드가 선택·합성하지 않는다.

Query Prompt는 새 규칙/사례를 추가하지 않고 flat anchor→route별 목록이라는 기존 책임의
입력 형상만 정합화했다. input v6, Prompt1.0.41/hash/manifest/Canonical05·15를 함께
변경했고 DRAFT 및 모든 activation gate는 유지한다. Output schema/Node/State는 불변이다.
SourceStatus prototype은 이 Product 변경에 활성화하지 않았다.

직접 반례는 policy shortcut 수정 전6 FAIL→직접11 PASS, 기간 수정 전5 FAIL→공유조회
반례 추가 포함11 PASS다. 전체 관련 Agent/RU/ToolRoute/Retrieval/Analysis/Planning/Review,
LangGraph adapter, PromptRuntime, Approval/ExecutionAttempt/Verification/Recovery 및 status
비활성 prototype을 함께 실행해 **1,843 PASS**를 확인했다. 편집 도중 실행에서 발생한
manifest/입력 버전 동기화3건은 동결 후 같은 집합에서 재검증했으며 모델 trial이 아니다.
실제 모델·Provider0. Source 의미 품질이나 전체92 업무 PASS로 합산하지 않는다.
남은 수평 감사는 concept/지원 constraint kind의 work binding과 SourceStatus 생성 계약이다.

## v26 WorkUnit-bound SourceStatus — 실행 전 고정

현재 status output은 Resource당 한 항목만 허용하고 normalize가 같은 Resource의 모든
WorkUnit으로 적용 범위를 넓힌다. 두 Task 업무가 서로 다른 현재 상태를 요청하면 표현
자체가 막히거나 한쪽 조건이 다른 업무에 적용된다. 비활성 후보는 기존 status 호출에
확정 WorkUnit provenance를 전달하고 항목이 해당 Resource의 확정 Source WorkUnit subset을
명시하도록 한다. 의미 owner·호출 수·원문 provenance·현재 상태 enum은 그대로다.
Main State는 기존 ConstraintV1이며 status input v2/output v3 후보는 Product에 활성화하지 않는다.

직접 component는 Schema→normalize→finalized V3→Planning local projection과 실제 compiled
ToolRoute(shared Task route1/Work2)까지 닫았다. Task union query는 typed fixture이고
Query LLM의 올바른 관계 판단을 증명하지 않는다. 신규17/기존 관련 포함23 PASS.

모델 owner 비교는 합성4(서로 다른 Task 상태, 서로 다른 Gmail 상태, 공통 상태 제한,
상태 제한 없는 두 업무) 및 Canonical CORE005/060 원문 control로 고정한다. 각6건을
baseline/후보 각각1회, schema repair최대1회, semantic revision0으로 실행한다.
확정 WorkUnit·Source·Output fixture는 status 판단 입력일 뿐 분해 성적이나 새로운 Gold가
아니다. Core control과 합성 진단을 구분하고 Canonical92 점수에 합산하지 않는다.
동일 Product Prompt 원문·qwen3.5:9b digest·temperature0/seed20260923/ctx16384/thinkfalse/
timeout180으로 계약 표현만 비교한다. first/repair와 calls/tokens/latency, 잘못된 binding 및
상태 과잉/누락을 각각 기록한다. 실제 Provider 연결0, Production activation0이다.

### Query concept/지원 종류도 동일 업무 귀속으로 닫음

exact anchor 이후 `resolve_requested_gmail_concepts`가 다른 업무 concept을 모든 Gmail
Route에 복제하고, 지원 constraint 종류도 다른 업무의 상태/시간 제약으로 확대하는
동형 손실을 확인했다. 같은 route constraint projector를 사용해 해당 업무의 concept
합집합과 허용 종류만 계산한다. V3 누락 binding을 전역 값으로 복구하지 않고 기존 기본
discovery 능력·shared READ·legacy 호환·선택 exact DETAIL의 LLM0을 유지한다.
신규10개 포함 관련112 PASS, Product Ruff/mypy/diff-check PASS. 모델/Provider0.
이는 Source/기간/개념을 새로 해석하거나 특정 Case의 검색어를 주입하는 변경이 아니다.

### v26 실제 owner 비교 결과 — 미채택, 다음 표현 축으로 이동

실행 HEAD `66a771281253984f6e861680ef4c1272ed0c8485`, 사전 고정한 6건을 각 arm 1회
실행했다. 첫 schema는 양쪽 모두6/6, repair0이었다. Product Prompt 본문은 동일하며
candidate의 requested_work 입력과 WorkUnit-bound output 계약만 달랐다.

| 진단 | baseline | v26 | 최초 의미 차이 |
| --- | --- | --- | --- |
| 서로 다른 Task 상태 | FAIL | PASS | baseline은 조건 누락, 후보는 업무별 INCOMPLETE/COMPLETED 보존 |
| Draft/Sent 별개 Mail 업무 | FAIL | FAIL | 두 출력 모두 빈 status로 명시 조건 누락 |
| 공통 미완료 제한 | FAIL | PASS | 후보는 두 업무에 같은 INCOMPLETE 제한 보존 |
| 상태 제한 없는 두 Task 업무 | PASS | FAIL | 후보가 두 업무에 요청하지 않은 INCOMPLETE 필터 추가 |
| CORE005 현재 상태 답변 | PASS | FAIL(owner) | 후보가 COMPLETED/INCOMPLETE 필터 생성; 합집합은 ANY와 같으므로 실제 업무 실패로 단정하지 않음 |
| CORE060 완료 상태로 UPDATE | FAIL | PASS | baseline은 현재 Source에 INCOMPLETE를 추정, 후보는 Output effect와 구분 |

owner 의미 판정은2/6→3/6이나 기존 PASS2건이 모두 회귀했다. Typed carry 손실은 없고
최초 잔여 실패는 LLM의 현재 상태 필터 판단이다. provenance exact span이 존재해도 그
span이 선택한 상태 의미를 정당화한다는 증명은 아니다. **Production 미채택**이다.

각 arm6 calls. baseline input9,401/output76 tokens/reported14,532ms;
candidate input10,869/output437 tokens/reported21,322ms. 동일 qwen3.5:9b digest,
temperature0/seed20260923/ctx16384/thinkfalse. rerun0, Provider0, activation0.
원본: `evaluation/results/064-status-work-bound-owner6-t1/raw.json`, SHA256
`fa210a5fe796dc6586fd260f4250eac3b27f8e90a44120fd5e5c1bdc11c52d6e`.

이는 실제 upstream decomposition이 아닌 고정 typed fixture를 사용한 owner 진단이다.
특히 공통 Task fixture의 required_information은 title/status/due를 포함하므로 NONE의
두 번째 업무 요청보다 넓다. 입력을 사후 변경하지 않았고 이 제한을 결과와 함께 보존한다.
현재 상태를 답하는 데 필요한 fact와 검색 상태 제한은 다른 의미다. 이 결과를 Canonical92,
RU→Route 연결, Retrieval/Planning 이후의 업무 성공률로 승계하지 않는다.

다음 v27은 같은 Resource×WorkUnit membership에서 모델이 NO_FILTER 또는 상태 조건을
명시적으로 선택하는 계약 표현만 비교한다. 빈 출력에 NO_FILTER를 기본 주입하지 않으며
기존 원문·Goal·Source·Output 입력과6건/1회 예산을 유지한다. 새 규칙·few-shot·Node는
추가하지 않고 v26 raw를 비교 기준으로 재사용한다.

## v28 Source requirement group 표현 — 비활성 connected component

Source owner 출력은 Resource당 SOURCE_REQUIRED 한 항목만 허용하고, 그 항목에 하나의
required_information/target_scope와 여러 WorkUnit을 둔다. 같은 메일 Resource라도 업무1은
단일 본문, 업무2는 여러 제목이 필요한 경우 서로 다른 요구를 표현할 수 없었다. 한 항목으로
합치면 정보×업무의 교차 적용이 발생하고 merge도 Resource-key 하나만 남겼다.

후보는 Resource exact-set/NOT_REQUIRED를 유지하고 SOURCE_REQUIRED의 기존 세 필드만
requirements[]로 묶는다. 각 group은 기존 Source validator와 responsibility normalizer를
거쳐 기존 V3 Source item으로 flat-map된다. 의미 추정이나 새 필수 Source 선택은 없다.
Main State/Route/Planning public schema, Node/Edge, Source·Output owner와 실행 권한은 불변이다.

직접19 PASS, 기존 Source/merge/GoalBinding/connected 포함69 PASS. 실제 compiled ToolRoute의
합성 ANSWER/ACTION 두 경로에서 Source2항목→공유 InputRoute1/WorkUnit union을 유지했고,
독립 Draft Output2개와 Planning의 자기 업무 정보/scope를 보존했다. fake LLM0/Provider0이다.
단순 요청은 baseline merge와 동등하며 NOT_REQUIRED, 중복/unknown ID, 빈 facts와 같은
WorkUnit 내 scope 충돌은 기존 계약대로 거절한다. 실제 Query/LLM 의미 성공으로 세지 않는다.

Product 채택에는 owner-local 타입/Schema/validator, merge, Prompt의 출력 형상 설명과
버전/hash, Canonical06·15, raw/fake adapter/repair 호환을 함께 닫아야 한다. 현재는 미활성
prototype이며 9B 생성 정확도·tokens/latency·local revision 호환을 검증하지 않았다.

## Ambiguity 업무 귀속 손실과 전역 target 소비 수정

확정된 두 Source의 WorkUnit 귀속을 서로 바꾸어도 실제 ambiguity infer 입력이 완전히
같아졌다. projection이 requested_work와 source work_unit_ids를 버렸기 때문이다.
이제 기존 Work 정의·item binding·exact provenance를 복사해 전달하고 connector-owned
information에도 원항목 binding만 유지한다. legacy binding은 만들어 채우지 않는다.
입력 v3/Prompt1.0.18/hash/Canonical06·15를 정합화했고 출력2/State/Node/Edge/DB는 불변이다.

또한 ambiguity의 missing_fields에는 WorkUnit ID가 없는데, 전역 anchor 양수나 같은 Resource
종류의 selected identity만으로 USER/target_resource를 CONNECTOR로 덮거나 거절했다.
명시적 multi-work에서는 그 증거만으로 다른 업무의 target이 해결됐다고 판정하지 않고
원래 USER 후보를 보존한다. 단일 업무·legacy·CONNECTOR/NONE·repository 검증은 유지한다.
Source/Output 의미를 만들거나 어느 업무의 target인지 코드로 추정하지 않는다.

carry 반례4 FAIL→5 PASS(legacy control 포함), 소비 반례3 FAIL→12 PASS(controls 포함).
직접/compiled node/Prompt97 PASS, root RU·Prompt339 PASS. 모델·Provider0이다.
기존 Prompt의 전역 count 기반 판단 설명은 입력 형상 설명 외에는 변경하지 않았다.
따라서 모델 ambiguity 의미 안정화 자체는 미검증이며, 이 기계적 count 판단이 복수 업무
binding과 충돌하는 문제는 별도 평가 후보로 다룬다. 입력 보존을 의미 PASS로 승계하지 않는다.

### v27 명시적 상태 slot 결과

HEAD52f95859에서 v26 raw6개를 동일 input/Schema/Prompt/runtime/모델 digest/owner 코드
hash 검증 후 재사용했다. 신규 후보는6회만 호출, first schema6/6, repair0이다.
v26의3/6→v27의4/6: 불필요 필터(NONE·CORE005)는 없어졌지만 서로 다른 Task 상태의
기존 PASS가 NO_FILTER 두 개로 회귀했다. Mail Draft/Sent는 계속 누락됐다.
공통 미완료/UPDATE 효과 구분은 유지했다. 공통 상태의 proof가 각 slot에 중복됐지만
동일 필터의 업무 귀속은 유지되므로 이를 업무 실패나 회귀로 세지 않는다.

**새 후보 역시 미채택**이며 불필요 필터와 명시 필터 누락 사이의 의미 불안정이 남는다.
신규6calls/input12,450/output240tokens/reported21,838ms, 재사용6calls는 신규비용에서 분리.
rerun0/Provider0/activation0. raw:
`evaluation/results/064-status-explicit-slot-owner6-v27-reuse-t1/raw.json`, SHA256
`855a7c51e331652afdb87d1e15ad9d93986a5956eff0104e915a54a17546161d`.

### v28 실제 owner 비교 사전 고정

Core001/013/023은 `064-source-paired-baseline-v22-t1/raw.json`의 실제 첫 Source 입력과
모든 기존 attempt4개를 재사용한다. 023은 현재 Canonical의 지연 메일·대체 일정 Task를
참고한 점검 Event 생성 요청이며, Task/Calendar 요약으로 잘못 표기하지 않는다.
001 upstream이 금지 문장을 별도 WorkUnit으로 분해한 상태도 변경하지 않는다.
013의 과거 repair는 현재 보호 guard에서 거절됨을 원기록과 별도로 표시하고,
이를 requirements 표현 후보의 개선으로 계산하지 않는다.

추가 합성2건은 같은 Source Resource의 서로 다른 정보/scope 요구와 READ/독립 WRITE
책임 구별을 검증한다. Source 후보 판단을 정답으로 강제하지 않는다. 각각 baseline/후보
1회, Core3은 후보만1회: 신규 first최대7, 각 schema repair최대1, semantic revision0이다.
새 schema/payload 형상 설명만 바꾸며 원문·Goal·Work·candidate catalog 입력은 양쪽 같다.
실제 기존 Source sampler0.05/seed20260923/ctx16384/thinkfalse/180s와 모델 digest를 결속한다.
구조 검증과 정보·범위·업무 귀속·Source 누락/과선택·금지 보존은 별도로 검토한다.
새 runner18+prototype19=37 PASS; 모델 실행 전의 준비 결과이며 Product activation0이다.

### v28 실제 owner 결과 — 표현 개선과 Source 의미 실패를 분리

실행 HEAD `7e75e8170e6ff61641b050acb32041287407cbdb`, 계획 hash
`ae9a3caf8a4be92ae0d2f594a3286687f89b29a53164a93f75e2112f985fd70c`로
Core3의 기존 baseline4 attempts와 합성2의 신규 baseline, 후보5를 비교했다.
신규 FIRST7회는 모두 첫 schema를 통과했고 새 repair0, semantic revision0이다.
후보의5/5 구조 통과를 의미5/5나 업무5/5로 표시하지 않는다.

| 입력 | baseline FIRST / 기존 repair | v28 FIRST와 최초 차이 | 의미 판정 범위 |
| --- | --- | --- | --- |
| CORE001 선택 메일, 다른 메일 검색 금지 | Thread SINGULAR/work-1 | 같은 Thread에 Message(sender/body) SINGULAR/work-1 추가 | 메일 내용 근거 요구 유지. 선택 Thread의 Message를 읽는 대안일 수 있어 Resource 수 증가만으로 실패 아님. 실제 selected-only Route/Query 준수는 미실행 |
| CORE013 작업·슬롯 → 새 Draft | FIRST부터 Task/Event와 잘못된 기존 Draft READ가 있음. Task/TaskList 중복과 Freebusy/Issue 누락으로 schema 실패; 과거 repair는 전부 NOT_REQUIRED로 소실 | Task/Event는 그대로 있고 기존 Draft READ 오판도 유지. GitHub Issue READ까지 새로 추가 | 필요한 Task/Event를 새로 찾아낸 성공이 아님. 최초 의미 오류는 Source owner의 새 Draft 목적을 기존 Draft 조회 요구로 해석한 부분. Issue 추가도 조회 범위 확대 위험이며 개선으로 계산하지 않음 |
| CORE023 Kestrel 메일·대체 일정 Task → 점검 Event | Thread+Message+TaskList+Task+Event | Thread(message_history)+TaskList+Task+Event, Message 제외 | 메일과 Task 근거 요구는 유지. Thread/Message는 내용 획득의 대안이므로 Message 제거 자체로 누락 실패 아님. Task/Event의 실제 대상·시각 보존과 신규 Event 계획은 미검증 |
| 합성 READ: 선택한 Thread 전체 내용 + 별도 결제 Thread 제목 목록 | work-1 SINGULAR만 생성, work-2 Source 누락 | Thread에 work-1 SINGULAR/내용과 work-2 CRITERIA/subject를 따로 생성. Message는 work-1에만 추가 | 두 업무의 정보·범위 binding이 최초 owner 출력부터 복원됨. work-2에 전체 본문을 교차 적용하지 않음 |
| 합성 독립 Draft2: 선택 Thread 요약안 + 결제 Thread 제목 목록안 | work-1 SINGULAR만 생성, work-2 Source 누락 | 같은 Thread에 두 requirements를 SINGULAR/내용 및 CRITERIA/subject로 구별 | 정보·범위 binding 개선. 새 Draft를 기존 Draft Source로 오인하지 않았음. 이번 모델 진단은 Output owner/실제 Draft2 Planning 성공을 실행한 것은 아님 |

합성2건은 양쪽 모두 금지한 Task/Calendar Source를 만들지 않았다. 단, 합성 READ 후보가
work-1 Message에 sender/recipients/labels까지 넓은 fact 집합을 요청한 점은 비용·최소조회
측면의 잔여 관찰이다. 이것을 다른 업무의 내용 유출과 동일시하지 않으며 실제 추가 READ
횟수는 아직 측정하지 않았다. CORE001의 금지 문장을 work-2로 나눈 기존 upstream도
고치지 않았다. 그 work-2에 Source가 없다는 사실만으로 금지 의미가 실제 소비됐다고
판정하지 않는다.

CORE013의 Task/Event는 **baseline FIRST에 이미 존재**했다. 현재 Product repair guard로
과거 전부 NOT_REQUIRED repair를 재검사하면 unaffected Draft/Event 변경이 거절된다.
이 guard의 개선은 이미 별도 Product 수정이며 requirements 후보의 성과가 아니다.
v28이 이번 단발에서 중복/누락 없이 schema를 만들었다는 관측과, Source 의미의 오판을
해결했다는 주장은 구분한다. 잘못된 Draft Source는 두 FIRST 모두 남았다.

비용은 신규와 재사용을 분리한다.

| 측정 구간 | calls | input / output tokens | reported latency |
| --- | ---: | ---: | ---: |
| 합성2 baseline 신규 | 2 | 8,436 / 333 | 16,566ms |
| 합성2 v28 신규 | 2 | 8,602 / 417 | 19,606ms |
| Core3 v28 신규 | 3 | 12,275 / 763 | 38,480ms |
| 이번 신규 전체 | 7 | 29,313 / 1,513 | 74,652ms |
| Core3 baseline 과거 재사용(FIRST3+repair1) | 4 | 16,721 / 837 | 39,194ms |

동일한 합성 입력2건의 후보 비용은 +166 input/+84 output tokens, +3,040ms였다.
Core3의 과거4회와 후보3회의 시간 차이는 repair 유무와 실행 시점이 섞여 있으므로
전체 제품 지연 개선으로 일반화하지 않는다. 모든 신규 usage 관측 누락0이다.
9B digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`,
실제 Source temperature0.05/seed20260923/ctx16384/thinkfalse/timeout180이다.
과거 baseline 상위 metadata의 temperature0.0과 달리 실제 transport는0.05였으며
이번 비교는 그 실제 값에 맞췄다. 각 Case의 원래 owner reference time도 그대로 유지했다.

**판단: requirements 표현은 유력한 구조 후보로 유지하되 Production 미채택.** 합성2건에서
막혀 있던 서로 다른 정보·scope의 WorkUnit binding을 실제9B가 표현한 근거가 생겼다.
반면 Source 선택 정확도의 수평 개선, 실제 upstream 분해, 반복 안정성은 입증되지 않았다.
특히 한 Route에 `selected SINGULAR + 다른 업무 CRITERIA`가 같이 있는 상태를 실제 Query가
선택 identity 하나로 축소하지 않고 처리하는 연결은 이 모델 실험에서 검증하지 않았다.
앞선 typed component의 shared Route/독립 Output 보존 결과와 이 미검증 구간을 섞지 않는다.
후속 판단은 이 연결 경계의 검증과 잔여 Source 의미 오류 분리를 우선하며, 이번 결과만으로
전체92 또는 Retrieval/Planning 이후의 성공률을 새로 산정하지 않는다.

원본: `evaluation/results/064-source-requirements-owner5-v28-t1/raw.json`, SHA256
`f255b29590a39d667503c652df1347015f5aff78c7177bba843583e6dae4a700`.
원본 raw는 수정하지 않았다. rerun-to-pass0, Provider READ/WRITE0, Product activation0이다.
