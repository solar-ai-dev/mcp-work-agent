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
