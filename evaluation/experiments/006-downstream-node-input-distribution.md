# 006. Work Analysis·Planning·Review 적용 입력 분포

기준 SHA는 `d9c2c094`, corpus는 `canonical92-v8-5a49aa00-ecf32ffc82`다.
Retrieval 연결에서 `015/021`이 차단됐으므로, 후단 Node 실패와 upstream 미도달을
섞지 않기 위해 Core 60의 저장 checkpoint를 먼저 분류한다. 현재
`RequestIntent`·ToolRoutePlan·RetrievalResult와 policy상 Analysis 필요 여부를
구분하고, WorkAnalysisResult·PlanningResult·PlanReview 존재를 센다.

이 단계는 저장 최종 상태의 **입력 가능성 재고 조사**일 뿐 실제 LLM 첫 호출의
의미 성공률이나 최신 Retrieval 이후의 업무 성과가 아니다. LLM·Connector·WRITE는
실행하지 않는다. 결과에서 이미 도달한 대표·반례·성공 Case를 골라 Work Analysis
단일 Node 및 다음 소비자를 직렬 평가하고, 미도달 Case는 upstream 실패로 남긴다.
follow-up·revision·confirmation resume의 별도 입력은 이 초기 재고에 포함된다고
가정하지 않는다.

## 관측·판정

Core 60 저장 checkpoint 전부를 읽었다. Policy상 Work Analysis가 필요한
Intent·Route는 16건이나, 그 16건 모두 parent RetrievalResult가 없어 Work Analysis
입력으로 도달하지 못했다. WorkAnalysisResult 0건이다. Planning 입력 조건은
15건, 저장 PlanningResult 17건(그중 4건은 현재 checkpoint의 RetrievalResult가
없는 다른 경로·시점), Review 입력은 17건이나 저장 PlanReview는 4건이다.
Stress 20도 Work Analysis 입력·결과 0건, Planning 입력·결과 각 5건,
PlanReview 4건이었다.

이는 Work Analysis가 안정적이라서 0건인 것이 아니라, 적용 요청이 Retrieval
앞에서 멈춘 분포다. 같은 저장 corpus만 재생해 Work Analysis의 첫 호출 성공률을
계산할 수 없으며 0/0을 PASS로 취급하지 않는다. 이 진단에 실제 LLM·Connector는
0회다. 원시 결과는
`evaluation/results/downstream-input-distribution-core60-20260916/` 및
`downstream-input-distribution-stress20-20260916/`에 있다.

다음에는 Retrieval 내부의 `assess_sufficiency`와 Query/selection 첫 호출의
비민감 결과를 Node 경계에서 관측해 여러 분석필요 요청이 같은 이유로
차단되는지 분리한다. Retrieval을 무작정 통과 처리하거나 Work Analysis에
합성된 정답 Evidence를 주입해 제품 성공으로 세지 않는다. Work Analysis
자체의 입력·Prompt 계약은 별도 합성 Node fixture로도 검증하되, 현재 upstream
연결 성공으로 일반화하지 않는다.

## 새 방법: 숨겨진 Retrieval 결정의 비민감 관측

앞의 연결 반복은 Subgraph 종결이 Local sufficiency/selection을 지우므로
같은 `CONTEXT_BLOCKED`만 다시 확인했다. 이제 외부 입력·Prompt를 바꾸지 않고
LLM 첫 structured output의 `status`, issue slot/type/resolution, Query route 수,
Evidence 선택 수와 실제 provider dispatch 수만 호출 경계에서 기록한다. 원문·
completion·Evidence 내용은 추가 기록하지 않는다.

분석필요 요청 `021`(명시 시각)과 `028`(상대 날짜·근무시간)을 고정 시각으로
직렬 연결한다. `021`은 이전 차단의 원인 진단이고 `028`은 다른 표현·동일
Gmail/Task/Calendar 조합의 대조다. `014`의 SUFFICIENT/Planning 전달은
기존 성공 대조로 재사용한다. 같은 Prompt 수정이나 schema 완화는 하지 않는다.
첫 호출 status와 최종 차단이 다르면 중간 guard/validator 경계를 조사하고,
둘 다 동일 issue라면 공통 Query·조회·충분성 의미를 다음 대상에 집중한다.

두 건 모두 `assess_sufficiency` 첫 structured output은 `SUFFICIENT`/issue 0개였지만
최종은 `CONTEXT_BLOCKED`였다. Validator·guard가 LLM 제안을 수정한 것이다.
`_fail_closed_on_empty_required_acquisition`은 access-only 의존성을 제외한
required route마다 조회·Evidence 유무를 검사한다. 첫 두 Trial의 READ 목록에
`calendar_list_calendars`가 없어 Calendar 과잉 선택을 의심했으나, 이를
확정하지 않고 `021` **한 건만** 같은 입력으로 재생하며 frozen route의
정책/access 분류와 각 route의 READ 상태·resource count를 기록했다.

추가 Trial에서 첫 Query는 4개 Route를 제안했고 `GMAIL_THREAD`, `TASK`,
`CALENDAR`, `CALENDAR_FREEBUSY`가 조회됐다. `CALENDAR`의 READ는 `COMPLETE`로
확인됐다. 반면 필수 `POLICY_CALENDAR_CONFLICT_CHECK`의 `CALENDAR_EVENT`
Route는 시도되지 않았다. 첫 Sufficiency는 여전히 `SUFFICIENT`/issue 0개였지만
Guard가 누락된 정책 pre-read를 막아 `CONTEXT_BLOCKED`로 종료했다. 따라서
“Calendar container 미조회 단독 원인” 가설은 기각한다. `CALENDAR`의 Source
과잉 여부는 별도 의미 판정이며 이번 차단의 확정 원인으로 간주하지 않는다.
Guard는 약화하지 않는다.

현재 초기 Query는 follow-up과 달리 required Route 누락 검증이 없고,
Canonical 05의 `CTX-003`은 필수 Policy Precondition Route 생략을 금지한다.
다음 후보는 정책 Route 자체를 새로 추론하지 않고 **이미 frozen된 executable
Policy Route만** 초기 Query 계약·검증에 결합하는 것이다. 비정책 business Route는
모델의 의미 판단에 남긴다. 후보를 적용하기 전에 순수 계약 반례와 기존 성공
사례를 확인하고, 우선 021/028의 작은 연결 재생으로 비교한다. 세 Trial의
원시 결과는 각각 `evaluation/results/request-to-evidence-decision-boundary-core021-028-20260916/`
및 `evaluation/results/request-to-evidence-route-boundary-core021-20260916/`에
분리 보존했다. 모두 synthetic READ이며 실제 Provider/WRITE/Planning은 미실행이다.
