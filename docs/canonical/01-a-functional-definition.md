# 01-A. 기능 정의서

수정일: 2026-09-06  
상태: 제품 기능 요구사항 — P0는 필수 범위이며 구현 완료 표시가 아님  
목적: 사용자 기능의 입력·처리·출력·예외·완료 조건

## 1. 문서 목적

이 문서는 사용자가 사용할 수 있는 기능과 시스템 내부 기능을 식별 가능한 단위로 정의한다. 각 기능은 안정적인 기능 ID와 해당 동작의 입력·처리·출력·예외·완료 조건을 갖는다. 기술 계약을 반복하는 대신 사용자에게 관측되는 기능을 정의한다.

### 1.1 Functional authority 경계

상위 제품 범위 안에서 기능의 의미만 정한다. 허용·차단·Override는 정책, 화면 구성은 UI·UX, operation·상태 전이·wire schema·코드 배치는 각 기술 owner가 소유한다. 이 문서의 수정일은 다른 문서 버전이나 API 버전과 연동하지 않는다. 기능 번호를 정책 번호와 일대일 연결하지 않는다. 기존 기술 계약에 없는 operation이나 schema가 필요한 요구는 구현 전에 별도 정합화하며, 기능을 적었다는 이유로 보호 계약의 예외가 허용되지 않는다.

## 2. 기능 상태

| 상태 | 의미 |
| --- | --- |
| P0 | MVP 필수 |
| P1 | P0 안정화 후 추가 |
| EXP | 제품 기본값 채택 전 평가 Gate가 필요한 구성 후보 (`13`이 평가·채택 근거를 소유) |
| OUT | 제품 범위 제외 |

## 3. 기능 목록 요약

| 영역 | 기능 |
| --- | --- |
| 설정 | 첫 실행, Google·GitHub 연결, GitHub repository 관리, Gemini API credential, Local Runtime 준비, 기본 Resource 선택 |
| 요청 | 자연어 입력, 범위 지정, 실행 취소, Run 재개 |
| Context | Retrieval Source 범위 확정, 검색, 정규화, Evidence, 재검색, Gmail 첨부파일 Metadata 조회·사용자 요청 시 다운로드 |
| 분석 | 관계 연결, 중복, 충돌, 업무 가능성 |
| 계획 | Action Plan, DAG, Draft 생성, 위험 표시 |
| 승인 | 전체·부분 승인, 수정, 거절, 승인 만료 |
| 실행 | MCP Tool 호출, Idempotency, 부분 실행, Gmail Draft·Send 첨부파일 전달 |
| 검증 | Connector Verification Read, 필드 비교, Recovery |
| 관측 | 상태 기반 누적 Activity, 행별 상세, Trace, Audit, 오류 진단 |

## 4. 초기 설정·Local Runtime 기능

### FN-001 첫 실행 Wizard

- **상태:** P0
- **입력:** 앱 첫 실행, 선택적인 Google/GitHub 연결, API 또는 Local 추론 방식과 필요한 동의.
- **처리:** Core 환경 검사와 업무 Connector 연결 안내를 구분한다. Google 연결은 건너뛸 수 있고 Settings 또는 해당 기능이 필요할 때 수행한다. Calendar·Task List·repository 기본값도 이후에 정할 수 있다.
- **출력:** Google·GitHub가 모두 미연결이어도 진입 가능한 메인 화면과 연결·AI 준비 상태.
- **예외·완료 조건:** 필수 Core 오류와 Connector 미연결을 혼동하지 않는다. 일반 사용자는 Client ID/secret/포트/설치 명령을 입력하지 않는다. Google Workspace와 기존 Gmail·Tasks·Calendar 기능은 유지한다.

### FN-002 Google 계정 연결

- **상태:** P0
- **사용자 목적:** 별도 OAuth Client 파일 입력 없이 Google 계정을 연결한다.
- **입력:** `Google로 로그인` 사용자 행동, Google 계정 선택, 필요한 Scope 동의.
- **처리:** 제품이 승인된 OAuth 설정과 안전한 Credential boundary를 사용해 Google 연결을 수행하고, UI/Core에는 계정·연결 서비스·승인 Scope·연결 상태 같은 bounded metadata만 제공한다. OAuth Secret/Token 원문은 UI/API/SQLite가 소유하지 않는다.
- **예외:** 동의 취소, 필수 Scope 일부 거절, 허용되지 않은 테스트/운영 계정 상태, Credential 갱신 실패. 연결 준비 실패는 해당 Connector 상태이며 메인 화면 진입을 막지 않는다.
- **Scope 규칙:** P0 필수 Scope 하나라도 거절되면 연결을 완료 처리하지 않고 Google Workspace 기능 실행을 차단한다.
- **완료 조건:** 모든 P0 필수 Scope가 승인되고 Gmail·Tasks·Calendar 최소 연결 확인이 성공한다.

### FN-003 Google 계정 연결 해제

- **상태:** P0
- **기능:** 사용자가 현재 Google 계정 연결을 해제하면 해당 Connector의 저장된 Credential 권위와 활성 계정 상태가 초기화되어야 한다. 앱·메인 UI와 무관한 GitHub 요청은 계속 사용할 수 있어야 한다.
- **출력:** 다시 Google 기능을 사용하려면 새 연결/재인증이 필요한 상태.
- **완료 조건:** 해제된 Credential로 이후 Google Workspace 접근을 승인할 수 없다.

### FN-004 LLM Runtime 진단

- **상태:** P0
- **입력:** 하드웨어, Ollama 상태, 설치 모델, API Key.
- **처리:** CPU-only 여부, GPU 기준 충족, Ollama 연결, Local 테스트 추론, API 연결을 확인한다.
- **출력:** 사용 가능한 모드, 배포 프로필, 고정된 실행 모드.
- **규칙:** CPU-only 또는 GPU 기준 미달은 API_LLM 고정. Local 제품 Runtime은 Ollama만 지원한다. `LOCAL_CAPABLE` 최초 설정은 Release-approved Ollama와 Signed Local Model Profile을 자동 준비하고, 이후 실행은 Version·모델 digest·Structured Output 상태를 다시 검증한다. Ollama는 별도 Process로 유지하며 제품 종료 시 공유 Runtime을 강제 종료하지 않는다.

### FN-005 LLM 모드 선택

- **상태:** P0
- **선행 조건:** Runtime 진단 완료.
- **처리:** API_ONLY에서는 API_LLM만 표시한다. LOCAL_CAPABLE과 검증된 GPU에서는 AUTO, LOCAL_GPU, API_LLM을 표시한다.
- **출력:** 사용자 선택 모드와 실제 실행 모드.
- **완료 조건:** P0에서 API와 Local 모드를 모두 사용할 수 있다.

### FN-006 배포 프로필 선택

- **상태:** P0 배포 기능
- **프로필:** `API_ONLY`, `LOCAL_CAPABLE`.
- **API_ONLY:** Ollama 의존성 없이 실행하며 GPU가 없는 팀원과 CPU-only 사용자에게 제공한다.
- **LOCAL_CAPABLE:** Local Runtime 진단과 자동 provisioning UI를 제공한다. Windows Installer 본체에는 Ollama 실행 파일·모델 weight·실험 Runner·미승인 후보를 포함하지 않지만, 최초 설정에서 verified Artifact를 다운로드·설치·검증해 사용자가 별도 터미널 작업 없이 Local Runtime을 사용할 수 있게 한다.
- **완료 조건:** 동일 제품 Core/Policy 의미를 유지하면서 배포 Artifact 의존성과 Runtime capability가 프로필별로 분리된다.

### FN-006A Local Runtime 자동 준비

- **상태:** P0 배포 기능
- **사용자 목적:** 별도 CLI 없이 승인된 Local AI를 준비한다.
- **처리:** 환경 확인 → 기존 호환 Ollama 재사용 또는 승인된 설치 → 모델 다운로드 → identity/digest 검증 → 테스트 추론 → 사용 가능 상태 반영.
- **출력:** 준비 항목, 확인 가능한 다운로드량·진행, 중단·재시도 상태와 실패 원인.
- **모델:** WORKER/REASONING 모두 `qwen3.5:9b`를 사용하는 기본 profile이 제품 목표다. 4B는 향후 선택지이며 이번 필수 준비 대상이 아니다. 개발 실행 확인과 signed Release 활성화는 구분한다.
- **완료 조건:** API_ONLY에 설치 부작용이 없고, 공유 Ollama를 훼손하지 않으며, 실패·중단·재시작 후 검증된 상태로 이어간다. 준비 미완료를 READY로 표시하지 않는다.

### FN-007 OAuth 배포 환경 관리

- **상태:** P0 개발·운영 기능
- **처리:** 개발·스테이징·운영 Google Cloud 프로젝트와 OAuth Client를 분리한다.
- **팀 테스트:** Test User 등록, External + Testing Refresh Token 7일 만료 재로그인 안내.
- **운영:** 검증된 OAuth Client와 동의 화면만 사용한다.

### FN-008 Local Agent Service 시작

- **상태:** P0
- **사용자 목적:** 별도 개발 명령이나 업무 계정 로그인 없이 앱을 실행한다.
- **입력:** Launcher 실행.
- **처리:** loopback binding, 제품 Asset/API/DB/Migration과 필수 Core 계약을 확인해 Local UI를 제공한다. Connector의 credential/permission 상태는 기능 availability로 따로 표시한다.
- **출력:** Local Service 상태, 메인 UI 진입, 필요한 설정·진단 안내.
- **예외:** local binding 실패, Service 시작 실패, DB Safe Mode, 필수 Asset/contract 실패.
- **완료 조건:** Google·GitHub가 모두 미연결이어도 Core readiness와 메인 UI는 정상이다. Local Session 인증과 외부 업무 계정 로그인은 별개다.

### FN-009 Frontend·API 세션과 버전 확인

- **상태:** P0
- **기능:** 로컬 UI는 현재 Local Service와 안전하게 인증된 세션을 수립하고 Frontend/API 계약이 호환되는지 확인한 뒤에만 상태 변경 요청과 진행 Event 기능을 사용할 수 있어야 한다.
- **예외:** bootstrap/session 검증 실패, 허용되지 않은 Origin/Host, Frontend/API 계약 비호환.
- **완료 조건:** 인증되지 않았거나 호환되지 않는 UI가 상태 변경 기능이나 보호된 Event Stream을 사용할 수 없다.

## 5. 요청 기능

### FN-010 자연어 요청 입력

- **상태:** P0
- **입력:** 한국어 또는 영어 자연어, 선택적 Query·기간·사람·이메일·Keyword, 이번 요청에서 명시적으로 선택한 Gmail·Task·Event·GitHub Issue Resource.
- **처리:** Resource를 먼저 선택하지 않은 Agent 검색형 요청과, 사용자가 Resource를 명시적으로 선택한 요청을 모두 시작할 수 있어야 하며 각각 새 current-run 처리 단위로 시작한다. 기본 요청 생성은 Google Credential을 전역 전제로 삼지 않고, 필요한 Connector가 판단된 시점에 해당 연결·권한을 확인한다.
- **출력:** 요청 진입 유형, 처리 단계, 현재 Source, 진행 상태.
- **예외:** Runtime 미설정은 추론 준비 안내로 구분한다. 필요한 Connector의 초기 미연결·App 미설치·repository 접근 불가·permission 부족은 필요한 설정 조치를 안내한 뒤 현재 요청을 종료한다. 종료한 요청은 연결 대기로 suspend하거나 OAuth 완료 후 자동 resume하지 않는다. 사용자가 연결 후 다시 전송하면 새 Run을 시작한다.
- **완료 조건:** 같은 Conversation에는 여러 USER 요청과 대응 Run이 순차적으로 존재할 수 있지만 동시에 Active Run이 둘 이상 생기지 않는다. 새 사용자 요청은 이전 Run의 Message·Agent Artifact·Evidence·Plan·Confirmation·Checkpoint를 숨은 업무 Context로 자동 승계하지 않고, 사용자가 이번 요청에서 명시적으로 선택한 Resource만 Entry Context로 사용할 수 있다.

### FN-011 요청 범위 제한

- **상태:** P0
- **입력:** 기간, Source 선택, 특정 Resource.
- **처리:** 사용자가 지정한 범위를 검색 계획의 상한으로 적용한다.
- **완료 조건:** 범위 밖 자료가 필요하면 조회 전에 추가 Source·기간과 이유를 제안하고 사용자 확인을 받는다. 사용자 확인 없이 지정 범위를 확대하지 않는다.

### FN-012 실행 취소

- **상태:** P0
- **기능:** 사용자는 진행 중 Run의 아직 시작되지 않은 작업을 취소할 수 있어야 하며, 이미 완료된 외부 Write를 가짜 rollback하지 않아야 한다.
- **처리:** 중단 가능한 읽기/LLM 작업은 더 진행하지 않고, 외부 Write가 이미 dispatch되었거나 결과가 불명확하면 같은 Write를 재전송하지 않은 채 실제 외부 결과를 Verification/Recovery로 먼저 확정한 뒤 취소를 마무리한다.
- **출력:** 취소된 범위, 이미 완료된 Action, 아직 결과 확인이 필요한 Action을 구분한 결과.
- **완료 조건:** 취소 요청 이후 새 외부 Write가 임의로 시작되지 않고, in-flight Write 사실이 CANCELLED로 덮어써지지 않는다.

### FN-013 Run 재개

- **상태:** P0
- **기능:** 확인 질문·정상 실행 중 인증 만료·복구·일시 중단 등으로 멈춘 현재 비Terminal Run은 보존된 안전 진행 상태에서 이어서 처리할 수 있어야 한다. 초기 Connector 미연결로 종료한 요청은 재개 대상이 아니다.
- **처리:** 재개 전에 이미 승인·실행·완료된 Action 사실을 조정해 중복 실행을 막고, Terminal이 된 이전 Run은 새 사용자 요청의 숨은 Context나 resume 대상으로 사용하지 않는다.
- **완료 조건:** same-run resume와 new-run start가 구분되고, 재개 때문에 완료 Action이나 승인된 Effect가 중복 적용되지 않는다.

### FN-014 사이드바 목록 조회

- **상태:** P0
- **입력:** 사용할 Source·container와 검색·필터·정렬·페이지 또는 월 선택.
- **처리:** Gmail은 최근 수신 목록, Tasks는 기본 목록의 미완료·완료 자료, Calendar는 선택 월의 일정을 탐색한다. 표시 범위·정렬·count·Month View 상세는 UI·UX에서 정의한다.
- **출력:** 실제 조회된 목록·구분 가능한 자료·알려진 범위의 개수·추가 조회 가능 여부.
- **예외·완료 조건:** 미연결이면 Gmail·Tasks·Calendar Sidebar를 제거하지 않고 연결 CTA를 표시한다. 연결 후 같은 탐색 기능을 사용할 수 있다. 실패와 빈 목록, 추정 개수와 확정 개수를 구분한다. 탐색 cache는 세션 범위에서 재사용하고 원본 전체를 DB에 복제하지 않는다. GitHub repository·Issue 탐색은 등록된 기능 범위에서 제공한다.

### FN-015 Frontend 페이지 메모리 캐시

- **상태:** P0
- **기능:** 같은 UI 세션에서 이미 조회한 Sidebar 목록/page/batch/month를 불필요하게 다시 외부 조회하지 않고 재사용할 수 있어야 한다.
- **폐기:** 계정·Source container·검색/filter/sort/scope 변경, 명시적 새로고침, UI 세션 종료처럼 결과 의미가 바뀌는 조건에서는 관련 cache를 폐기해야 한다.
- **제한:** UI cache는 승인·중복·충돌·검증의 제품 사실 기준점이 아니며 Secret/OAuth/Local Session 원문을 cache identity로 저장하지 않는다. 장기 Semantic Memory나 Source 원본 복제 저장소로 승격하지 않는다.
- **완료 조건:** 동일 UI 범위 재탐색은 이미 받은 결과를 재사용하면서도 scope/account 변경 뒤 stale 목록을 재사용하지 않는다.

### FN-016 사용자 선택형 요청

- **상태:** P0
- **입력:** Sidebar에서 사용자가 명시적으로 선택한 하나 이상의 등록된 Gmail·Task·Event·GitHub Issue Resource와 자연어 요청 또는 빠른 Action.
- **기능:** 선택된 Resource를 이번 Run의 명시적 Entry Context로 사용하고 최신 상세를 확인해 사용자가 사람·날짜·제목을 다시 입력하지 않아도 요청을 수행할 수 있어야 한다.
- **처리:** 선택 범위 밖 Source/Connector가 필요하면 이 기능이 임의 확장하지 않고 route/scope 재검토 기능으로 넘기며, 사용자 지정 범위를 넘는 확장은 확인을 요구한다. 선택 Resource에 연결된 과거 Run Evidence/Approval을 새 Run으로 자동 승계하지 않는다.
- **출력:** 선택 Resource 기반 current-run Context와 요청 결과/Action Plan.

### FN-017 Agent 검색형 요청

- **상태:** P0
- **입력:** 자료 선택 없이 제출한 사람·기간·업무 개념·키워드·복합 목표.
- **처리:** 요청 의미를 보존하고 필요한 Source 범위에서 후보 검색 → 필요한 상세 → 근거 선택을 수행한다. 제목과 본문, 참여자 metadata와 관련 자료를 구분해 활용한다.
- **출력:** 확인한 자료와 근거 기반 답변 또는 실행안. 검색 표현의 확장은 가설이며 사용자 사실이 아니다.
- **완료 조건:** 사용자 표현이 원문과 정확히 같지 않아도 관련 후보를 발견할 수 있어야 한다. exact 제목·Resource·project anchor는 보존하고, 모든 Source 무조건 조회나 무제한 검색을 하지 않는다.

### FN-018 Run 진행 Event 구독·복구

- **상태:** P0
- **기능:** Run에서 실제 발생한 책임별 실행 회차를 순서대로 누적한다. 다음 단계가 시작돼도 이전 행을 지우지 않는다. 각 행을 열어 그 회차의 기존 결과·허용된 근거를 확인할 수 있어야 한다.
- **처리:** 같은 실행의 진행·완료는 같은 행을 갱신하고, 새 back-edge 실행은 새 행을 추가한다. 단순 resume는 재실행과 구분한다. 표시하지 않은 단계를 완료로 꾸미지 않는다.
- **정보:** 이미 생성·검증된 상태·Agent 결과·계획·승인·실행·검증·복구 결과를 사용한다. Activity 전용 LLM 호출·Prompt·요약 Agent를 만들지 않는다. 표시·클릭 때문에 외부 업무 Tool을 재호출하지 않는다.
- **복원:** SSE와 저장된 실행 이력·Snapshot으로 중복·역순 이벤트를 조정하고 refresh/reconnect/restart 후 같은 Run 이력을 복원한다. 최신 상태 하나로 과거 실행을 추정하지 않는다.
- **완료 조건:** 같은 Run의 질문·재인증·복구는 이력을 이어가고, 새 Run은 격리된다. 행별 상세가 해당 시점의 결과와 일치하며 후보·부분 결과·UNKNOWN_RESULT·취소를 성공으로 과장하지 않는다.

### Resource Browser·Sidebar 공통 요구

이 절은 FN-014~FN-018의 사용자 기능을 보조하는 Functional 요구만 정리한다. **구체 UI layout·row/card 표현·페이지 control·Empty State 문구는 `02 UI·UX`, Local API continuation·Connector operation 계약은 `07 Interface`, repository naming은 `16 Repository Architecture`가 소유한다.**

- 사용자는 Gmail·Tasks·Calendar 목록을 탐색하고, 이미 조회한 세션 범위 결과를 재사용하며, 명시적 새로고침·scope/account/container 변경 시 관련 cache를 폐기할 수 있어야 한다.
- 목록 탐색은 Provider continuation을 사용자에게 노출하거나 Frontend가 해석하지 않는 opaque continuation 경계를 가져야 하며, 정확한 source별 page/batch/window 규칙은 FN-014와 02/07의 current contract를 따른다.
- Focus Resource와 Agent 요청에 명시적으로 선택한 Resource 집합은 기능적으로 구분되어야 하며, Focus 변경이 선택 Context를 암묵적으로 바꾸지 않아야 한다.
- `RESOURCE_SELECTED` 진입은 선택 Resource를 current-run Entry Context로 보존하고 최신 상세를 조회한다. 추가 Source/Tool 범위가 필요하면 FN-102에 연결된 runtime route 경계를 통해 재판단하며 사용자 지정 범위를 자동 확장하지 않는다.
- Quick Action은 선택 Resource + 사용자 의도를 Agent 요청으로 제출하는 진입 기능일 뿐 외부 Write를 직접 실행하지 않는다.
- Conversation 선택은 저장 Timeline을 복원하는 기능이며 새 Run의 implicit semantic memory를 만들지 않는다.
- Frontend는 서버가 제공한 projection을 표시하며 실행·승인·검증 사실이나 숨은 count/history를 추정해 만들지 않는다.

### Tasks·Calendar Sidebar/Viewer 공통 요구

이 절은 Source별 사용자 기능 의미만 정의한다. **구체 row 순서·날짜 포맷·label·색상·Empty State 문구·선택 styling은 `02 UI·UX`, Connector operation 이름과 request field는 `07 Interface`, repository operation/path/symbol은 `16 Repository Architecture`가 소유한다.**

- Tasks Sidebar/Viewer는 실제 Task의 제목·메모·`scheduled_date`·Task List·완료 상태를 사용자에게 탐색 가능한 형태로 제공해야 하며, Provider 내부 ID·continuation 같은 구현 세부를 사용자 의미로 노출하거나 임의 priority/category를 생성하지 않는다.
- Calendar Sidebar/Viewer는 Event 제목·시간 범위·all-day 여부·Calendar Context를 사용자에게 식별 가능하게 제공해야 하며, 사용자 지정 기간이 있으면 그 범위를 우선하고 일반 Upcoming 조회 범위는 FN-014/07의 current functional/interface contract와 일치해야 한다.
- Source 전환과 Focus 변경은 다른 Source의 상세나 Agent 선택 Context를 암묵적으로 유지·혼합하지 않아야 한다.
- Task 날짜·상태 의미는 아래 `Google Tasks 날짜·상태 의미`를, 구체 UI 표현은 `02 UI·UX`를 따른다.

### Google Tasks 날짜·상태 의미

#### 예정일과 업무 마감

- `scheduled_date`는 사용자가 Task를 수행할 예정인 날짜다. Google Tasks API Adapter의 `due`와 대응하며 READ/WRITE 가능하다. 시간 정보를 생성·추론하지 않는다.
- `business_deadline`은 업무 자체가 완료되어야 하는 실제 마감이다. Gmail 본문, 사용자 요청, Evidence에서 인식할 수 있으나 Google Tasks API의 `due`와 동일시하지 않는다.
- 업무 마감만 있는 요청은 `scheduled_date`를 만들거나 Google `due`를 채우지 않는다. 필요한 경우 `notes`에 `업무 마감: YYYY년 M월 D일`처럼 의미를 보존하고 Evidence·Approval Summary에도 근거를 남긴다.
- 수행 예정일과 업무 마감이 모두 명시되면 각각 보존한다. 예를 들어 11일 수행·12일 제출은 `scheduled_date=11일`, `business_deadline=12일`이며 Google `due`에는 11일만 사용한다.
- 시간대가 지정된 Task 요청은 현재 Google Tasks API가 정확한 시간 구간을 구조화해 설정했다고 성공 처리하지 않는다. 날짜 예정일만 제안하거나, 정확한 시간 예약이 필요하면 승인형 Calendar Event 대안을 사용자에게 제시한다. 사용자 동의 없이 Event를 추가하지 않는다.

#### 상태와 사용자 Projection

- Provider raw `needsAction`은 제품 상태 `NEEDS_ACTION`, UI 문구 `미완료`로 정규화한다. raw `completed`는 `COMPLETED`, UI 문구 `완료`로 정규화한다.
- 예정일 경과는 상태 전이가 아니다. `scheduled_date`가 지났고 상태가 미완료이면 UI 보조 문구 `예정일 지남`만 사용할 수 있으며, `기한 초과`·`마감 초과` 또는 자동 완료로 표현하지 않는다.
- 완료는 Google Task 실제 status가 `completed`일 때만 표시한다. Provider가 완료 날짜를 제공하면 사용자 친화적인 `완료일`로 표시할 수 있다.
- 목록·상세에는 raw enum, RFC3339 raw `due`, 내부 `due` 필드명, API에 없는 작업 시간·업무 마감을 표시하지 않는다. React는 사용자용 Local API Projection을 소비하며 Provider 의미의 최종 정규화를 담당하지 않는다.

## 6. Context·Retrieval 기능

### FN-020 Retrieval Source 범위 확정

- **상태:** P0
- **입력:** `RequestIntent`, 요청 진입 방식, 이번 Run에 명시적으로 선택된 Resource, FN-011 사용자 범위 제약.
- **처리:** 현재 Run의 Retrieval이 사용할 Connector·Resource·Read capability 범위는 Retrieval 시작 전에 확정되어야 한다. `RESOURCE_SELECTED`에서는 사용자가 이번 Run에 명시적으로 선택한 Resource/Source를 Entry Context로 보존하고, `AGENT_SEARCH`에서는 요청 수행에 필요한 범위만 사용한다. 추가 Source가 사용자 지정 범위를 벗어나면 사용자 확인 없이 자동 확장하지 않는다.
- **출력:** downstream Retrieval이 재선택 없이 소비할 수 있는 frozen input-route 범위.
- **예외:** 선택된 Resource를 근거 없이 재검색해 대체하거나, 모든 Source를 기본 선택하거나, Retrieval이 Source/Tool을 재선택하지 않는다.
- **완료 조건:** Retrieval은 확정된 IN Route만 read-only로 소비한다.

### FN-021 Gmail 검색·조회

- **상태:** P0
- **입력:** 확정된 Gmail 범위, 의미 제약 또는 검증된 selected Resource.
- **처리:** metadata 검색과 필요한 Message/Thread 상세로 자료를 찾는다. 이름·직급·별칭·이메일은 근거 기반 후보로 연결하고, 유일성 근거가 없으면 임의 identity를 확정하지 않는다.
- **시간:** 수신일, 본문 행사일, 뉴스레터에 담긴 개별 기간을 구분한다. 행사 시점을 메일 수신일 filter로 치환하지 않는다. 연도 생략은 Run 기준 시각·timezone·요청 맥락과 자료로 해석하며 불명확한 연도로 요일을 만들어내지 않는다.
- **개념:** ‘일정’을 literal 단어 하나로만 검색하지 않고 회의·행사 등 표현을 제한된 가설로 탐색한다. 특정 이름·예제 정답을 Production Prompt나 고정 사전에 넣어 맞추지 않는다.
- **출력·완료 조건:** Message별 출처와 날짜의 역할이 유지된 Context/Evidence. 최종 답변의 수신 시각·행사일·요일을 실제 근거와 대조할 수 있어야 한다.

### FN-021A Gmail 첨부파일 조회·다운로드

- **상태:** P0
- **사용자 목적:** Gmail Message의 첨부파일 Metadata를 확인하고, 명시적으로 선택한 원본 파일을 다운로드할 수 있다.
- **처리:** Message 상세에서 사용자가 식별할 수 있는 파일명·MIME Type·크기 Metadata를 제공하고, 다운로드 요청 시 해당 첨부파일 원본 bytes만 안전한 Connector/Local API download 경계를 통해 전달한다.
- **출력:** 검증된 파일 Metadata와 사용자 선택 파일의 원본 bytes.
- **제한:** 첨부파일 bytes·내용을 LLM Prompt·Context·Evidence로 전달하지 않는다.
- **완료 조건:** LLM 호출 없이 선택한 파일을 받을 수 있고, 다른 Message/Attachment bytes가 혼동·노출되지 않는다.

### FN-022 Tasks 검색·조회

- **상태:** P0
- **입력:** current-run에 확정된 Tasks Read 범위, 상태·예정일·Keyword·Task List 제약, 또는 검증된 Task Resource reference.
- **처리:** 필요한 Task 후보·상세만 Source-native Read로 조회하고 제품의 Task 상태와 `scheduled_date` 의미로 정규화한다. Provider의 raw `due/status`를 실제 업무 마감(`business_deadline`)이나 다른 사용자 의미로 임의 변환하지 않는다.
- **출력:** 현재 Run에 귀속된 정규화 Task Context와 Evidence 후보.

### FN-023 Calendar 조회·FreeBusy

- **상태:** P0
- **입력:** current-run에 확정된 Calendar Read 범위, 기간·Calendar·Resource 제약, 또는 검증된 Calendar/Event Resource reference.
- **처리:** 필요한 Event와 FreeBusy 정보를 Source-native Read로 조회하고, 사용자 Timezone과 정책상 Busy/Tentative/Free 의미를 일관되게 적용해 일정 충돌·가용성 판단에 사용할 수 있는 Context를 만든다. LLM이 Provider-native 시간 표현이나 raw API arguments를 직접 작성·실행하지 않는다.
- **출력:** 현재 Run에 귀속된 Event Context, Busy Interval, 가용 Slot 후보와 Evidence.

### FN-024 Context 정규화

- **상태:** P0
- **기능:** Gmail·Task·Event·GitHub Issue의 표현 차이를 정규화하되 서비스별 의미를 유지한다.
- **완료 조건:** Connector·Resource·container identity, 사람·시간·상태·원문 위치가 손실되지 않는다. GitHub Issue에 Gmail 서명 제거를 일괄 적용하거나 같은 숫자의 다른 repository Issue를 하나로 합치지 않는다. direct permalink가 없으면 실제 지원하는 서비스 검색 navigation을 사용한다.

### FN-025 Chunking

- **상태:** P0
- **기능:** 긴 Thread는 Message 경계와 항목·줄바꿈을 보존하면서 처리 가능한 길이로 나눈다.
- **완료 조건:** 앞 Message의 서명·인용 처리가 뒤 Message를 삭제하지 않는다. 날짜와 해당 행사/기간의 관계 및 원문 위치를 추적할 수 있고, 변경된 원문에는 stale segment를 재사용하지 않는다.

### FN-026 추가 Retrieval

- **상태:** P0
- **기능:** 근거가 부족하고 새 정보 가능성이 있을 때만 현재 허용 범위에서 다음 page·추가 detail·변경 검색을 수행한다.
- **처리:** 동일 query와 같은 detail을 의미 없이 반복하지 않는다. 검색 round와 detail hydration의 예산을 구분하며 기존 RunBudget을 준수한다. 새로운 조회가 기존에 선택한 유효 Evidence를 불필요하게 지우지 않는다.
- **출력:** 추가 탐색의 결과 또는 부족한 범위가 표시된 부분 답변. 확인한 근거가 있으면 예산 소진 때문에 답변 자체가 사라지지 않아야 한다.
- **완료 조건:** 필요한 최종 답변 처리도 예산 안에서 가능해야 한다. 정상 no-result, 일부 실패, 인증 불가, 전혀 시도하지 못한 조회를 구분한다. READ 부분 종료를 WRITE 필수정보 충족으로 오인하지 않는다. 범위 확대는 기존 확인 절차를 따른다.

### FN-027 사용자 확인 질문

- **상태:** P0
- **조건:** 허용된 조회로 해결하지 못한 인물·기간·대상·행동 선택, 또는 별도 사용자 결정이 필요한 범위·정책 문제.
- **처리:** Connector로 해소 가능한 모호성은 먼저 제한된 탐색을 수행한다. 실제 후보가 여러 개 남으면 차이를 제시하고 선택을 받는다. 후보가 끝내 없으면 확인하지 못한 상태를 설명하며 필요한 이름·이메일·기간만 질문한다.
- **출력:** 현재 모호성과 연결된 질문·선택지 또는 자유 입력.
- **완료 조건:** 사용자 답변 뒤 같은 Run의 적절한 지점에서 계속한다. 이미 제공한 값을 다시 묻거나 모든 기능을 무조건 처음부터 시작하지 않는다. 확인 응답을 WRITE 승인으로 대신 사용하지 않는다.

### Clarification 공통 요구

질문의 시점은 실제 결손을 발견한 책임에 따른다. 검색 가능한 모호함과 사용자만 결정할 수 있는 선택을 구분한다. 명시적 repository 충돌·범위 확대·외부 영향의 확인을 자동 검색으로 우회하지 않는다. 현재 Run과 선택 자료로 의미가 단일한 축약 요청에는 불필요한 질문을 하지 않는다.

### FN-028 Embedding·Reranking

- **상태:** EXP
- **설명:** Source-native 결과의 재정렬 방식은 `13 Evaluation`의 품질 비교와 Release decision을 통과한 configured capability만 제품 Runtime에 적용한다.

## 7. 분석 기능

### FN-030 Resource 관계 연결

- **상태:** P0
- **기능:** 제목·참여자·Thread·시간·명시적 Resource reference·Evidence를 사용해 Mail·Task·Event 사이의 업무 관계 후보를 찾고, 검증된 관계만 후속 분석/계획에 사용할 수 있어야 한다.
- **출력:** 관계 의미, 신뢰도/근거, Evidence reference.
- **완료 조건:** LLM이 제안한 관계 후보가 검증 없이 durable 사실이나 Action 근거로 확정되지 않는다.

### FN-031 Task 중복 검사

- **상태:** P0
- **기능:** Task CREATE 제안 전에 제목·사람·Thread·`scheduled_date`·현재 상태와 Evidence-backed `business_deadline`을 사용해 기존 Task와의 중복 가능성을 검사해야 한다.
- **처리:** LLM은 중복 후보를 제안할 수 있지만 최종 중복 판정과 생성 허용/차단은 실제 Source 사실과 정책을 재검증하는 결정적 책임을 가져야 한다.
- **출력:** 정확 중복이면 기본 새 생성 중단, 유사 후보면 경고/확인 필요, 중복이 아니면 신규 제안 가능 및 근거.
- **완료 조건:** LLM 단독 중복 판정이 새 Task 생성 허용/차단의 최종 근거가 되지 않으며, 정확 중복 override는 명시적 사용자 확인 없이 진행하지 않는다.

### FN-032 Calendar 충돌 검사

- **상태:** P0
- **기능:** Calendar CREATE/시간 변경 제안 전에 실제 조회한 Busy Interval·사용자 작업 시간·Buffer·기존 Event를 사용해 일정 충돌을 검사해야 한다.
- **처리:** LLM은 위험/interval 후보를 제안할 수 있지만 최종 충돌 판정과 차단/override 가능 여부는 검증된 외부 일정 사실과 정책을 사용하는 결정적 책임을 가져야 한다.
- **출력:** 충돌 없음, 경고/확인 필요, 차단과 근거.
- **완료 조건:** LLM 단독 판단으로 검증된 충돌을 우회하지 않으며, override가 허용되는 경우에도 필요한 사용자 확인/승인 없이 진행하지 않는다.

### FN-033 업무 가능성 판단

- **상태:** P0
- **기능:** Evidence/사용자 요청에서 확인된 업무 마감, 예상 소요시간, Calendar 가용성, 사용자 업무 시간을 함께 고려해 현재 업무가 가능·위험·불가능한지 근거와 함께 판단할 수 있어야 한다.
- **예외:** 필요한 예상 소요시간이나 일정 제약이 없으면 값을 만들어내거나 timed Event를 자동 제안하지 않고 사용자 확인으로 연결한다.
- **완료 조건:** feasibility 결과가 실제 Evidence/검증된 일정 정보에 근거하고, 불충분한 입력을 추측으로 메우지 않는다.

## 8. 계획 기능

### FN-040 Action Plan 생성

- **상태:** P0
- **기능:** 사용자가 검토할 수 있도록 하나 이상의 제안 Action에 대상 capability, 변경 내용/Arguments, 근거, Risk, Dependency, Expected Result를 포함한 Action Plan을 생성한다.
- **처리:** 계획은 FN-102에서 이미 확정된 OUT Resource·Effect·Tool capability를 임의로 바꾸지 않고 사용자 목표와 Evidence를 반영해야 한다. 최종 실행 가능한 Action 구조는 Schema와 결정적 검증을 통과해야 한다.
- **완료 조건:** 모든 외부 Write Action에 승인 판단에 충분한 Evidence가 있고, Planning 단계가 Tool identity/effect를 재선택하지 않는다.

### FN-041 Action Dependency DAG 생성

- **상태:** P0
- **기능:** 여러 Action이 있는 계획은 선행·후행 관계와 서로 독립적으로 실행 가능한 Action을 구분하는 유효한 Dependency DAG를 가져야 한다.
- **구현 책임:** 최종 dependency 관계는 자유형 LLM 판단만으로 확정하지 않고 결정적 검증·구성 책임을 가져야 한다.
- **완료 조건:** cycle, 존재하지 않는 Action 참조, 지원되지 않는 dependency가 있는 계획은 실행 가능 계획으로 확정되지 않으며, 각 Action의 선행 조건과 독립 실행 가능 여부가 모호하지 않다.

### FN-042 Gmail Draft 제안

- **상태:** P0
- **기능:** 사용자의 Gmail 관련 요청이 Write 제안을 필요로 하면 기존 Thread/Evidence·사용자 목표·업무 가능성을 근거로 수신자·CC·제목·본문·Thread 관계를 포함한 Draft 또는 SEND Action을 제안할 수 있어야 한다.
- **규칙:** `초안`, `문구`, `작성만`, `검토용`은 Draft 의미이고, 실제 전송을 요구하는 표현은 SEND 의미로 취급해 최종 수신자·CC·제목·본문·Thread를 사용자가 검토·승인할 수 있어야 한다.
- **완료 조건:** 제안이 이미 확정된 Gmail OUT capability를 임의 변경하지 않고, 승인 화면의 내용과 후속 승인 무결성 대상이 동일하다.

### FN-042A Gmail Draft·Send 첨부파일

- **상태:** P0
- **입력:** 사용자가 명시적으로 선택한 로컬 파일.
- **기능:** Gmail Draft/SEND Action은 사용자가 승인 시 확인한 첨부파일 identity/Metadata와 실제 실행 bytes가 동일하다는 무결성 검증을 가져야 하며, 파일 원문 bytes 자체를 LLM이나 Approval 표시 데이터로 복제하지 않는다.
- **출력:** 승인된 첨부파일이 포함된 Gmail Draft 또는 SEND 결과.
- **예외:** 임시 파일 만료·누락·무결성 불일치가 발생하면 기존 승인을 사용해 실행하지 않고 파일 재선택·Action 재검토·새 승인으로 돌아간다.
- **완료 조건:** 승인되지 않았거나 승인 뒤 변경된 파일 bytes가 전송되지 않으며, 동일 파일 무결성은 실행 직전까지 검증 가능하다.
### FN-043 Task 제안

- **상태:** P0
- **입력:** 사용자 목표·Evidence·중복 검사 결과·현재 기본 Task List.
- **처리:** 결정 가능한 제목·메모·예정일·목록을 완성해 compact 승인안으로 제시한다. 불명확하거나 정책상 필요한 값만 질문한다. 기존 Task와 정확 중복이면 그 결과를 제시하며 임의 추가 생성하지 않는다.
- **날짜:** 수행 예정일과 업무 마감을 별도로 보존한다. 마감만 있는 요청으로 due를 자동 생성하지 않는다.
- **완료 조건:** 승인 Preview와 실제 Task의 목록·제목·메모·예정일이 일치하고 재조회 검증된다. 완료·수정·삭제는 해당 사용자 의도와 별도 승인 범위를 따른다.

### FN-044 작업 Event 제안

- **상태:** P0
- **입력:** 직접 일정 요청 또는 메일 등에서 확인한 행사·업무 근거.
- **처리:** 제목·calendar·시작/종료·timezone·설명·참석자와 충돌 정보를 포함해 생성·허용 변경안을 제시한다. 명시된 시작/종료가 있으면 소요시간을 중복 질문하지 않는다. 설정으로 해소 가능한 기본 calendar는 재입력시키지 않는다.
- **예외:** 시간·대상·참석자가 미해결이면 임의로 채우지 않는다. FreeBusy/기존 Event 조회 실패를 충돌 없음으로 처리하지 않는다. 수신일을 행사일로 쓰지 않는다.
- **완료 조건:** Evidence → 승인 Preview → 실제 Event → 재조회 Verification이 같은 의미를 가진다. 알림·참석자 등 외부 영향도 승인 내용과 일치한다.

## 9. 승인 기능

### FN-050 Context Preview

- **상태:** P0
- **기능:** 현재 Run의 선택 근거·출처·범위를 확인하고, 서버가 조정을 허용한 승인 전 상태에서만 근거 제외 또는 추가 검색을 요청할 수 있다.
- **처리:** 현재 Preview에 속한 근거와 revision을 확인한 뒤 새 검색·분석·계획·검토 결과로 연결한다. 이미 승인되었거나 실행·불확실 결과·미검증 효과가 있으면 근거를 소급 변경하지 않는다.
- **완료 조건:** 과거 계획/승인을 새 근거에 재사용하지 않는다. UI는 서버가 허용한 조작만 제공하며, 상세 전이·wire shape는 기술 계약을 따른다.

### FN-051 Action 승인

- **상태:** P0
- **기능:** 사용자는 여러 Action을 전체·Connector/시스템별·Action별로 검토하고 승인할 수 있어야 한다. 일괄 승인 UI를 사용하더라도 각 Action은 승인 당시 사용자가 본 대상·변경 내용·근거와 무결하게 결합되어야 한다.
- **완료 조건:** 승인하지 않은 Action이나 거절/차단된 종속 Action이 외부 Write로 실행되지 않으며, 일괄 승인 때문에 개별 Action의 승인 범위·내용이 확장되거나 섞이지 않는다.

### FN-052 Action 수정

- **상태:** P0
- **입력:** 현재 제안 Action과 수정 요청. Task는 ‘예정일을 바꾸고 메모는 빼줘’ 같은 자연어 수정을 우선 지원한다.
- **처리:** Backend의 기존 수정·Planning/Review 경계에서 허용된 값을 변경한다. 언급하지 않은 값 유지와 명시적 제거를 구분한다. 직접 필드 편집은 필요한 경우 보조 수단으로 둔다.
- **출력:** 바뀐 내용을 보여주는 새 Preview와 새 승인 요청.
- **예외:** Tool/Effect/대상 자체가 달라지는 수정은 단순 field patch로 숨기지 않는다.
- **완료 조건:** 이전 revision의 승인으로 수정 후 Action을 실행하지 않는다. Frontend에 별도 의미 해석·LLM parsing·Approval authority가 생기지 않는다.

### FN-053 Action 거절

- **상태:** P0
- **처리:** 사용자가 거절한 Action은 외부 Write로 실행되지 않아야 하고, 그 Action에 의존하는 후속 Action도 실행 가능 여부를 다시 판단해야 한다. 독립 Action은 별도 승인·정책 조건을 만족하면 계속될 수 있다. 사용자가 대안을 원하면 거절된 Action을 몰래 되살리지 않고 새 계획/검토 결과로 제안한다.
- **완료 조건:** 거절 Action과 실행 불가능해진 종속 Action은 Write로 진행하지 않으며, 후속 대안이 기존 승인 권위를 재사용하지 않는다.

### FN-054 승인 무결성 Snapshot·만료

- **상태:** P0
- **기능:** 사용자의 승인은 승인 당시 검토한 Action 대상·Tool/Effect·Arguments·근거/Source·적용 정책/Schema 조건과 무결하게 결합되어야 하며 제한된 유효 기간을 가져야 한다.
- **처리:** 승인 이후 유효시간 경과, 원본 Resource 변경, Action 내용 수정, 적용 Tool Schema/Policy 변경처럼 승인 의미를 stale하게 만드는 조건이 생기면 기존 승인을 실행에 사용할 수 없고 재검토·새 승인으로 돌아가야 한다.
- **완료 조건:** 사용자가 보지 않았거나 승인 뒤 의미가 달라진 Action, 만료된 승인으로 외부 Write를 시작할 수 없다.

### 승인형 Write 공통 요구

- `SEND`: Gmail 실제 전송.
- `UPDATE`: Task 완료, Calendar 참석자 변경 포함.
- `DELETE`: 정확한 Google Task 삭제와 Calendar Event 삭제.
- Gmail Message·Thread 원문 삭제는 OUT을 유지한다.

## 10. 실행 기능

### FN-060 승인된 외부 Write 실행

- **상태:** P0
- **기능:** 외부 Write는 사용자가 승인한 현재 Action만 대상으로, 실행 직전에도 승인·정책·dependency·Source 최신성·Tool/Arguments 무결성이 유효한지 확인한 뒤 Connector 경계를 통해 실행되어야 한다.
- **처리:** 실행에 사용되는 Tool/Effect/Arguments가 사용자가 승인한 의미와 달라지지 않아야 하고, Connector/MCP 경계가 실제 실행 요청을 다시 검증해야 한다. Core/Application이 Provider API를 직접 호출하지 않는다.
- **출력:** 외부 Resource 식별자 또는 bounded 실행 결과 Metadata와 실제 실행 상태.
- **완료 조건:** 유효하지 않거나 stale한 승인, 승인 내용과 다른 Arguments, 허용되지 않은 Tool/Effect로 Write를 실행할 수 없고, 실행 결과는 후속 Verification/Recovery가 소비할 수 있어야 한다.

### FN-061 Write Idempotency·기존 결과 조정

- **상태:** P0
- **기능:** UI/네트워크 재시도, 응답 유실, Service 재시작이 같은 승인된 외부 Effect를 중복 적용하지 않아야 한다.
- **처리:** 중복 실행 가능성이 있으면 새 Write를 먼저 보내지 않고 현재 제품 실행 사실과 이미 관측 가능한 외부 결과를 조정해야 한다. 외부 결과가 불명확하면 동일 Write를 자동 재전송하지 않고 기존 결과 확인/Recovery로 전환한다.
- **완료 조건:** 하나의 승인된 실행 의도가 외부 시스템에 중복 생성·수정·전송·삭제를 만들지 않는다.

### FN-062 부분 실행

- **상태:** P0
- **기능:** 여러 Action 중 일부가 실패·거절·중단되어도 dependency가 없는 독립 Action은 별도 승인·정책 조건을 만족하면 계속 실행할 수 있고, 실패한 선행 Action에 의존하는 Action은 실행되지 않아야 한다.
- **출력:** 사용자에게 완료·미실행·실패·복구 필요 Action이 구분된 부분 실행 결과를 제공한다.
- **완료 조건:** 성공한 외부 Write를 가짜 rollback으로 지우지 않고, dependency가 깨진 Action을 실행하지 않으며, partial outcome을 전체 성공처럼 표시하지 않는다.

## 11. 검증·복구 기능

### FN-070 실행 결과 검증

- **상태:** P0
- **기능:** 모든 외부 Write 결과는 해당 Effect에 맞는 독립적인 외부 상태 재조회/검증을 거쳐 실제 결과와 승인·실행 시 기대한 결과를 비교해야 한다.
- **완료 조건:** CREATE/UPDATE/SEND/DELETE 각각의 성공이 Write 응답만으로 확정되지 않고, 검증 가능한 외부 사실을 기준으로 VERIFIED/MISMATCH/불명확 결과를 구분할 수 있다.

### FN-071 정상화 비교

- **상태:** P0
- **기능:** 외부 Write 검증 비교는 표현 차이만 있는 값과 실제 의미 불일치를 구분해야 한다.
- **정상화 대상:** 공백, 줄바꿈, Timezone 표현, 초 단위 정밀도, Connector/Provider가 합법적으로 채우는 기본값처럼 의미를 바꾸지 않는 차이.
- **완료 조건:** 허용된 표현 차이는 false mismatch를 만들지 않고, 사용자 의미를 바꾸는 핵심 필드 차이는 normalization으로 숨기지 않는다.

### FN-072 Mismatch Recovery

- **상태:** P0
- **기능:** 검증 결과 핵심 의미가 기대와 다르면 성공으로 숨기거나 자동으로 추가 Write를 수행하지 않고, 실제 차이와 안전하게 선택 가능한 Recovery 경로를 사용자에게 제시해야 한다.
- **완료 조건:** MISMATCH/불명확 외부 결과가 자동 성공·자동 재전송·자동 corrective Write로 바뀌지 않으며, 사용자의 선택 또는 안전한 결정적 복구 절차를 거쳐 해결된다.

### FN-073 OAuth 재인증 후 재개

- **상태:** P0
- **적용 대상:** 필요한 연결을 갖추고 정상 실행 중이던 Run에서 Credential이 만료되거나 갱신에 실패한 경우.
- **기능:** 기존 REAUTH_REQUIRED·안전 진행 상태를 보존하고, 재인증 뒤 사용자가 해당 Run의 재개를 요청하면 기존 safe resume 계약으로 계속할 수 있어야 한다.
- **처리:** in-flight·불확실한 Write는 재전송하지 않고 저장된 실행 사실과 Verification/Recovery를 우선한다. OAuth callback은 연결 상태만 갱신하고 특정 Run을 자동 재개하지 않는다.
- **완료 조건:** 완료·in-flight Action 중복 실행이 없다. 처음부터 미연결인 요청을 이 기능의 durable 인증 대기로 확대하지 않는다.

## 12. 관측성 기능

### FN-080 Run Trace

- **상태:** P0
- **내용:** Run/Node/Agent/Tool/Connector/Provider correlation, Source·candidate·retrieval 수량, 모델·fallback, Latency, Token/비용, 상태, Command ID, Event Cursor, bounded failure/validator/retry metadata.
- **원칙:** Trace는 판단·호출 설명과 성능 관측용이며 Domain 실행 사실의 기준점이 아니다. 원문 대신 allowlisted ID·Hash·수량·상태·지연을 기록한다.
- **제외:** OAuth/API/Bootstrap/Session/PKCE/Claim Token과 비밀값, Connector Source·Draft 전체 본문, Gmail attachment bytes/Staging 파일 원문·로컬 경로, LLM Prompt/Completion, MCP 전체 Request/Response, Approval Snapshot 전체와 실행 hash/nonce/signature 원문.

### FN-081 Audit Log

- **상태:** P0
- **내용:** Policy Confirmation, Action 제안/수정/승인/거절/만료, Approval consume, Policy 차단, Execution Claim/성공/실패/UNKNOWN_RESULT/복구, Verification, Recovery 및 필수 운영 안전 사건.
- **특성:** Application-level append-only 안전 기록이며 UI에서 수정할 수 없다. 필수 안전 Command의 Audit 저장이 실패하면 해당 Command도 성공으로 확정하지 않는다. 질문/응답·Connector 원문·Token/Claim 원문 등 비허용 payload는 Audit에 저장하지 않는다.

### FN-082 사용자 진단 화면

- **상태:** P0
- **내용:** Launcher/Manifest, React Build, Local Agent API/Session, Google Workspace·GitHub Connector 및 MCP/Credential 상태, LLM Runtime, SQLite/Migration, SSE, 최근 오류와 복구 Action의 **sanitized bounded projection**.
- **제한:** 진단 화면/Bundle은 DB·Backup·Keyring 원본, Connector 원문, Prompt/Completion, Approval Snapshot/Claim Token, Credential/Secret을 노출하지 않으며 자동 외부 업로드하지 않는다.

## 13. 지원·제외 범위

| ID | 기능 | 상태 |
| --- | --- | --- |
| P0-WRITE-001 | Gmail 승인형 전송 | P0 |
| OUT-002 | Gmail Message·Thread 원문 삭제 | OUT |
| P0-WRITE-002 | Google Task·Calendar Event 승인형 삭제 | P0 |
| P0-WRITE-003 | Calendar 참석자 승인형 추가·수정 | P0 |
| OUT-004 | CPU Local LLM | OUT |
| OUT-005 | 원격 SaaS·멀티 사용자·외부 공개 API | OUT |
| OUT-006 | 백그라운드 자동 실행 | OUT |
| OUT-007 | Gmail·Tasks·Calendar 전체 데이터의 로컬 상시 복제 | OUT |
| OUT-008 | 페이지 이동마다 이미 조회한 목록을 다시 호출하는 동작 | OUT |

## 14. Google Source 데이터 수명주기 Functional 요구

1. **목록:** 사용자가 Sidebar에서 탐색하는 목록은 필요한 범위만 조회하고 UI 세션 범위 cache로 재사용하며, Google 원본 전체를 제품 DB에 상시 복제하지 않는다.
2. **상세:** 사용자가 Resource를 focus/선택하거나 현재 Run에서 실제 후보가 확정됐을 때 필요한 상세만 조회한다.
3. **LLM Context:** 현재 Run 수행에 필요한 최소 상세만 LLM Context로 사용할 수 있으며, Source 원문 전체를 장기 Semantic Memory로 축적하지 않는다.
4. **영구 기록:** 실제 판단·승인에 사용된 Resource reference, 최소 Metadata, Evidence excerpt처럼 제품 사실 추적에 필요한 최소 정보만 보존한다.
5. **최신성:** 계획 확정 전, 승인된 Write 실행 직전, 실행 이후에는 관련 외부 Resource 최신성을 다시 확인할 수 있어야 한다.

## 15. Frontend · Local Service Functional 경계

1. 사용자는 로컬 UI에서 요청·선택·승인·수정·복구 행동을 수행하고 현재 상태/진행 Projection을 볼 수 있어야 한다.
2. UI는 서버가 검증한 API 경계를 통해서만 제품 상태를 읽거나 변경하며 Domain/Connector/Workflow 구현에 직접 접근하지 않는다.
3. 화면 cache와 Event/SSE Projection은 사용자 경험을 위한 상태일 뿐 승인·실행·검증의 최종 제품 사실을 대신하지 않는다.
4. UI/네트워크 재시도는 동일한 상태 변경을 두 번 적용하지 않아야 한다.
5. Workflow/Agent 기능은 제품 상태를 임의로 직접 영속 수정하는 별도 authority가 아니며, 상태 변경은 owning Domain/Application 경계를 따라야 한다.

## 16. Multi-Agent 기능

### FN-100 Supervisor Routing

- **상태:** P0
- **기능:** 현재 typed State, durable fact, artifact freshness와 남은 의무에 따라 필요한 책임을 선택한다. 고정된 Agent 순서를 모두 통과하게 하지 않는다.
- **완료 조건:** 필요한 실행·skip·제한된 back-edge·사용자 대기·재인증·복구·취소·종료가 연결된다. upstream 변경으로 stale해진 결과를 재사용하지 않고 같은 의미 상태의 무한 반복을 막는다. Provider별 의미 판단이나 Write 안전성을 두 번째 Supervisor에 복제하지 않는다.

### FN-101 요청 이해 Agent

- **상태:** P0

사용자 요청에서 목표·완료 조건·제약·모호성과 추가 업무 분석 필요 여부를 구조화할 수 있어야 한다. 이 기능은 Tool identity, Provider-native Query, Action Arguments를 직접 정하지 않는다. 허용된 조회로 해소할 수 있는 모호성은 미해결 의미를 보존하여 조회로 넘기고, 사용자만 결정할 수 있는 필수 선택은 확인한다. 조회 후에도 남는 실제 모호성은 확인 질문으로 연결한다. 특정 Write가 정책상 중복·충돌 사전 검사를 요구하면 그 정책 의존성을 보존해야 한다.

### FN-102 Tool Route Agent

- **상태:** P0

요청을 수행하기 위해 필요한 IN Connector·Resource·Read capability 범위와 OUT Resource·Effect capability를 계획 전에 확정할 수 있어야 한다. 정책상 필요한 사전 중복·충돌 검사는 입력 범위에 포함되어야 하며, 사용자가 제한한 Source·기간·Resource 범위를 넘어야 하면 명시적 확인 없이 확장하지 않는다. 확정된 route capability는 downstream Retrieval/Planning이 재선택하지 않고 소비해야 한다.

### FN-103 Retrieval Agent

- **상태:** P0

확정된 current-run input scope 안에서 필요한 자료를 조회·정규화하고 Evidence를 선택하며 Context 충분성을 판단할 수 있어야 한다. Retrieval은 입력 범위를 임의 확대하거나 OUT capability를 선택하지 않고, 부족한 경우 bounded additional retrieval 또는 route/confirmation 재판단으로 연결해야 한다. FN-109/FN-111은 이 기능을 실제 runtime에서 수행하기 위한 구현 책임 요구이며 별도 Functional capability를 새로 만들지 않는다.

### FN-104 업무 분석 Agent

- **상태:** P0

FN-030~FN-033의 Functional capability로서 현재 요청과 허용 Evidence에서 업무 사실·관계·정보 누락·중복/충돌 후보·일정 제약·업무 가능성·운영 위험을 분석할 수 있어야 한다. 관계·중복·충돌 후보가 LLM 결과만으로 최종 확정되어서는 안 되며, 결정적 검증을 거친 결과만 후속 Planning에 사용할 수 있다. 정확 중복/검증된 충돌을 사용자가 명시적으로 override하려는 경우에는 필요한 사용자 확인을 거쳐야 한다. Tool 선택·Tool Arguments·최종 정책 allow/deny는 이 Functional capability의 책임이 아니다.

### FN-105 Planning Agent

- **상태:** P0

FN-040~FN-044의 Functional capability로서 현재 요청·확정된 OUT capability·허용 Evidence·선택적 업무 분석을 사용해 답변 또는 실행 가능한 Action Plan을 제안할 수 있어야 한다. ACTION 경로에서는 확정된 Tool capability를 바꾸지 않고 필요한 Business Arguments·Evidence·Risk·Expected Result를 준비하며, Action dependency와 최종 Plan 조립·검증은 결정적 구현 책임으로 보장되어야 한다.

### FN-106 계획 검토 Agent

- **상태:** P0

제안된 답변/Action Plan이 사용자 목표를 충족하는지, Evidence가 충분한지, 과잉 작업·모순·Dependency 문제·지원 불가 Action이 없는지 독립적으로 검토할 수 있어야 한다. 검토 결과는 승인 가능한 상태, 수정 필요, 추가 Retrieval, route 재검토, 사용자 확인, 차단 중 필요한 후속 기능으로 연결될 수 있어야 한다.

### FN-107 Typed Handoff·Checkpoint

- **상태:** P0

전문 기능 단계 사이의 Handoff는 current-run 공식 typed 결과와 안정적 Ref/Handle을 사용해야 하며 자유 텍스트 Agent 대화나 Agent별 장기 Semantic Memory에 의존하지 않아야 한다. 중단·확인·재개가 필요한 경우에는 동일 Run의 안전한 진행 정보를 보존하면서 이전 Run 결과를 새 Run에 암묵적으로 승계하지 않아야 한다.

### FN-108 응답 조립

- **상태:** P0
- **기능:** 현재 Run에서 검증된 답변·근거 또는 실제 실행·검증·복구 결과로 사용자용 한국어/요청 언어의 최종 답변을 제공한다. 안전한 Markdown으로 읽기 쉽게 표현한다.
- **완료 조건:** generic 상태 문구가 실제 답변을 대신하지 않고, 같은 terminal 결과에 최종 Assistant Message가 중복 저장·표시되지 않는다. Source와 Connector를 혼동하거나 후보·계획·전송 결과를 확인되지 않은 성공으로 과장하지 않는다. Activity 표시와 최종 답변을 구분한다.

## 17. Agent 실행 기능

### FN-109 Retrieval Subgraph 실행

- **상태:** P0

FN-103 Retrieval capability가 실제 current-run runtime에서 bounded하게 수행되고 공식 결과만 downstream에 전달될 수 있어야 한다. Retrieval 실행 중간 후보·raw continuation·RAG intermediate·Provider payload가 장기 Main State나 별도 제품 사실로 승격되어서는 안 된다.

### FN-110 Answer-only Run 완료

- **상태:** P0

사용자 요청이 조회·분석·답변만으로 충족되고 외부 Write Action이 필요하지 않으면 Action/Approval/Execution artifact를 억지로 만들지 않고 Answer-only로 Run을 완료할 수 있어야 한다.

### FN-111 Retrieval 결정적 READ 실행

- **상태:** P0
- **입력:** 확정된 current-run input-route 범위와 검증된 Retrieval query/fetch intent.
- **처리:** Retrieval Read는 허용된 Connector Read 경계만 사용해야 하며 Provider-native Query·raw continuation·MCP Arguments를 LLM이 직접 생성·실행해서는 안 된다. 일반 Retrieval Read가 Write용 Action·Approval lifecycle을 만들지 않아야 한다.
- **출력:** 현재 Run에 귀속된 bounded Read 결과 참조와 retrieval metadata.
- **완료 조건:** frozen input 범위 밖 Read 없이 후속 Normalize/Evidence 기능이 소비할 수 있는 결과가 제공되고 raw Provider continuation/원문이 불필요한 제품 상태로 복제되지 않는다.

### FN-112 Retrieval READ 실패 처리

- **상태:** P0
- **처리:** query·route·identity·schema·권한 실패를 성공으로 위장하지 않는다. 같은 범위에서 의미 있는 재시도만 허용하고 재인증·사용자 확인·경로 재검토를 구분한다.
- **출력:** 이미 확인한 유효 근거가 있으면 확인된 범위의 부분 답변, 정상 검색 0건이면 no-result, 접근 실패면 접근 불가 안내를 제공한다.
- **완료 조건:** 예산 소진을 거짓 SUFFICIENT로 바꾸지 않고, 답변에 없는 사실을 생성하지 않는다. 안전 위반을 READ 부분 결과로 우회하거나 WRITE를 허용하지 않는다.

### FN-113 Write 재시도 준비

- **상태:** P0

외부 Write가 **실제로 전송되지 않은 실패**로 확인된 경우에만 재시도 준비가 가능해야 하며, 수정/재검토·새 승인과 새 실행 시도를 거쳐야 한다. 외부 결과가 불명확한 `UNKNOWN_RESULT`에서는 같은 Write를 재전송하지 않고 Recovery/Verification으로 실제 결과를 먼저 확정해야 한다.

### FN-114 Supervisor Routing 결정성 보장

- **상태:** P0

FN-100의 중앙 조정 기능은 같은 공식 runtime 조건에서 일관된 다음 단계가 선택되는 결정성을 가져야 한다. LLM 자유 텍스트나 임시 Agent 내부 상태가 임의로 다음 기능을 선택해서는 안 되며, 해석할 수 없는 runtime 결과는 추측하지 않고 fail-closed 또는 안전한 Recovery 기능으로 연결되어야 한다.

- **완료 조건:** 제품 기능 관점에서 동일한 공식 입력 조건이 임의의 서로 다른 다음 단계로 갈라지지 않는다. FN-114는 FN-100과 별개의 routing capability가 아니라 그 결정성 요구다.

---

### FN-115 Agent Subgraph 실행 계약

- **상태:** P0
- **처리:** 각 전문 Agent 기능은 현재 Run에서 필요한 입력만 받아 bounded invocation으로 수행되고, 결과는 downstream이 검증 가능하게 전달되어야 한다. Agent 기능끼리 자유 대화형 peer-to-peer 호출을 하거나 invocation-local 임시 상태를 장기 Semantic Memory/Domain 사실로 승격해서는 안 된다.
- **출력:** 후속 기능이 소비할 수 있는 versioned typed 결과와 필요한 진행 신호.
- **상태 수명:** invocation-local 작업 상태는 해당 invocation 범위를 넘는 제품 사실이 아니다. 동일 Run 재개에 필요한 공식 정보만 owning runtime/domain contract에 따라 보존한다.
- **완료 조건:** 전문 Agent 기능 간 직접 호출 없이 bounded execution과 current-run state isolation이 유지된다.

## 18. Local Command·Connection 기능

이 절은 사용자 기능과 중복 요청의 관측 결과만 정의한다. 전문 기술 계약을 완화하지 않는다.
### FN-019 상태 변경 요청 중복 적용 방지

- **상태:** P0
- **기능:** 브라우저 재시도, 응답 유실, Service 재시작, 중복 클릭처럼 동일한 상태 변경 요청이 다시 도착해도 같은 변경을 두 번 적용하지 않아야 한다.
- **처리:** 동일한 요청 identity와 동일한 요청 내용의 재전송은 이미 확정된 결과를 안전하게 재사용할 수 있어야 하고, 같은 identity에 다른 요청 내용이 결합되면 충돌로 거절해야 한다.
- **완료 조건:** 네트워크·UI 재시도로 동일한 제품 상태 변경이 중복 적용되지 않고, 서로 다른 요청이 같은 identity로 합쳐지지 않는다.

### FN-074 Google OAuth 연결·재인증 Coordination

- **상태:** P0
- **기능:** FN-002 계정 연결과 FN-073 재인증은 동일한 Credential boundary와 보안 규칙을 사용해 Google OAuth를 수행할 수 있어야 한다.
- **처리:** Core/UI는 계정·승인 Scope·연결 상태·재인증 필요 여부 같은 bounded metadata만 소비하고, Refresh/Access Token·Authorization Code·PKCE Verifier 원문을 소유하거나 영속하지 않아야 한다. 실제 OAuth browser flow와 Credential 저장/갱신은 Connector Credential boundary 안에서 수행되어야 한다.
- **완료 조건:** 연결과 재인증이 서로 다른 Credential ownership 규칙으로 구현되지 않고, Secret이 UI/Core/SQLite에 노출되지 않는다.

### FN-075 실행 Claim 증명

- **상태:** P0
- **기능:** 승인된 Action을 실제 외부 Write로 넘길 때는 현재 승인과 실제 실행 요청이 동일한 Action·Tool·Arguments에 대한 것임을 증명하는 서버 발급형, 짧은 수명의 1회용 실행 권위가 필요하다.
- **완료 조건:** 다른 Action/승인/실행 시도/Tool/Arguments에 실행 권위를 재사용할 수 없고, Browser나 LLM이 이 실행 권위를 임의 생성할 수 없다.

### FN-076 대화 이름 변경

- **상태:** P1
- P0에서는 최초 USER 요청을 기반으로 대화 생성 시 한 번 자동 생성한 title을 표시하며 이름 변경 API를 제공하지 않는다. title은 이후 같은 Conversation에 추가되는 후속 요청이나 업무적으로 무관한 새 요청으로 자동 재생성하거나 최신 메시지로 덮어쓰지 않는다.

### FN-077 대화 삭제

- **상태:** P1
- P0에서는 대화·Run 삭제 API를 제공하지 않는다. 보존 기간·완전 삭제는 설정·Uninstall 정책을 따른다.

### FN-078 대화 이력 조회

- **상태:** P0
- **입력:** 사용자가 선택한 Conversation.
- **처리:** 저장된 메시지와 Run 이력을 시간순·bounded 조회로 복원한다. 오래된 자료가 잘리면 그 사실을 알린다.
- **출력:** 저장 시각·내용·Run 상태와 보존된 Activity. 조회 자체는 업무 상태나 checkpoint를 변경하지 않는다.
- **완료 조건:** 과거 이력을 새 Run의 Prompt Context로 자동 전달하지 않는다. terminal Run 뒤 새 요청과 same-Run resume가 구분된다.

## 19. GitHub 및 외부 AI 설정 기능

### FN-120 GitHub 계정 연결·해제

- **상태:** P0
- **입력:** Settings의 연결·재연결·해제 행동과 GitHub에서의 사용자 동의.
- **처리:** 제품 설정의 GitHub App Client ID로 Device Flow를 시작하고 Provider가 발급한 user code·인증 페이지·대기 상태를 제공한다. 사용자는 제품용 Client ID·PAT·secret을 직접 만들지 않는다.
- **출력:** 연결 계정·인증 상태·권한 상태. 제품 설정 누락, 인증 거절, 코드 만료와 연결 해제를 구분한다.
- **완료 조건:** 실제 인증 후 허용된 조회가 가능하고 재시작 시 지원되는 credential 보존이 동작한다. GitHub 미연결이 Core 진입·Google 요청을 막지 않으며 Google 미연결도 GitHub 요청을 막지 않는다. 연결 완료가 이전에 종료한 요청을 재개하지 않는다.

### FN-121 GitHub Repository 조회·기본값 관리

- **상태:** P0
- **입력:** 연결된 계정, 저장소 새로고침·선택·기본값 저장·변경·해제.
- **처리:** 계정과 App이 접근할 수 있는 repository를 표시한다. App 접근 관리 페이지와 앱의 작업 기본값을 구분한다. 기본값은 0 또는 1개이며 소유자/이름이 명확해야 한다.
- **출력:** 선택값과 접근 상태. 목록 실패는 빈 목록이 아니며 권한 제거·계정 변경·repository 변경 후 재검증한다.
- **완료 조건:** refresh/restart 후 선택을 보존하고 요청에 실제 사용한다. 명시 요청과 selected Resource가 일치하면 그것을 우선하며, 서로 충돌하면 임의 우선순위로 해소하지 않는다. 둘 다 없을 때만 사용자 설정을 사용한다. 설정 변경은 진행 중·승인된 Run을 바꾸지 않는다.

### FN-122 GitHub Issue 검색·상세

- **상태:** P0
- **입력:** 검증된 repository 범위, Issue 선택 또는 열린/닫힌 상태 등 요청 조건.
- **처리:** 공통 Retrieval에서 등록된 Issue list/get을 사용하고 필요한 후보·상세·Evidence를 구성한다.
- **완료 조건:** 같은 번호라도 다른 repository의 Issue를 혼동하지 않으며 Source·상태·본문·출처가 보존된다. 초기 미연결·App 미설치·repository 접근 불가·필수 permission 부족은 조치 안내 후 현재 요청을 종료한다. 인증 대기·설치 감시·자동 재개는 만들지 않는다. 미접근·없음·정상 빈 목록을 구분하며 코드·PR 조회를 Issue 지원만으로 가능하다고 주장하지 않는다.

### FN-123 GitHub Issue 변경

- **상태:** P0
- **입력:** 명확한 repository/Issue와 CREATE·UPDATE·CLOSE·REOPEN 의도.
- **처리:** 공통 계획·검토·승인·실행·재조회 검증을 사용한다. Issue의 효과를 등록된 Tool 계약으로 매핑하며 별도 GitHub 승인·복구 체계를 만들지 않는다.
- **완료 조건:** 실제 Issue와 승인 인자가 일치한다. 선택 identity와 repository 불일치를 Provider I/O 전에 차단하고, PR 조작이나 임의 새 repository를 추가하지 않는다. 실제 Provider 검증 전에는 Live 완료를 선언하지 않는다.

### FN-124 Gemini API credential 관리

- **상태:** P0
- **입력:** API Key 입력·변경·연결 테스트·삭제와 저장 방식 및 외부 전송 동의.
- **처리:** 기존 provider-neutral credential 경계의 Gemini 설정을 관리한다. Key 설정과 동의, 실제 서비스 사용 가능 여부는 별도로 표시한다.
- **완료 조건:** 저장 후 Key 원문을 다시 표시하지 않으며 Google/GitHub credential과 섞지 않는다. Local 요청의 조용한 외부 전환이나 새 credential authority를 만들지 않는다.

### FN-125 연결 Settings 분리

- **상태:** P0
- **기능:** Google Workspace, GitHub, Gemini API를 구분하고 Local AI 준비와 업무 기본값은 각 맥락에서 관리한다.
- **완료 조건:** 각 연결 영역에서 상태 확인·연결·재연결·해제와 해당 기본값 관리를 완료할 수 있다. 하나의 서비스 상태가 다른 계정·credential·기본값을 덮어쓰지 않는다. 초기 미연결 안내로 종료된 요청은 Settings 연결 후 사용자가 새로 전송하며, 정상 실행 중 인증 만료로 멈춘 요청은 기존 명시적 안전 재개를 사용한다.
