# 제품 작업 현황 · 남은 검증

수정일: 2026-09-06  
문서 역할: 제품 요구사항 정리와 구현·검증 인계 기록. 새로운 Canonical·정책·실행 계약이 아니다.

## 1. 기준과 읽는 방법

최초 정리는 사용자가 제공한 `docs.zip` 전체 48개 파일과 확정된 제품 결정을 기준으로 했다. 당시 Product 기준은 `7120df546dc94afdf9e0e3e25a48469ea836095f`였고 문서 commit `53dd9c8ca7c57d410991adf6bc12d12808d87a59`는 PR 185의 merge `7326f2e6c8abcf4269bb226a2de59df07a8a6247`로 반영됐다. 이번 보정은 로컬 전체본 재검수 결과와 Product `671360c112531c5aa2242c82d5f20418d00da34a`까지의 후속 변경을 대조해 진행한다. 이전 문서 작업의 전체 의미 검수 통과 주장은 철회하고 파일 보존·게시 묶음 일치 검사와 구분한다.

PRD·기능·정책·UI는 **제품이 충족해야 할 요구**를 정의한다. 이 페이지는 구현과 검증의 현재 상태를 구분한다. 문서를 갱신했다고 기능이 구현되거나 기존 실패가 해결된 것으로 보지 않는다. 이후 상태 변경은 실제 commit·실행 증거를 확인한 뒤 이 기록에서 갱신한다.

문서의 기준일·버전을 서로 맞추지 않는다. 각 원문은 수정일로 현재성을 표시하고 Git이 변경 이력을 보존한다. API·artifact·DB schema version과 migration checksum은 별도의 실행 계약이다.

## 2. 이번 문서 정리의 경계

| 구분 | 처리 |
| --- | --- |
| PRD | 제품 목표·범위·완료선만 정리하고 상세 기술 계약의 반복을 줄임 |
| 기능 정의 | 사용자가 할 수 있어야 하는 일과 관찰할 결과를 정의. 기존 기능 ID 유지 |
| 정책 정의 | 허용·금지·승인·무결성·개인정보 조건만 정의. 기능 ID와 정책 ID를 연결하지 않음 |
| UI·UX | 화면·조작·표시 의미만 정리. 기존 UI ID와 업로드본의 Header/Settings 변경 보존 |
| 문서 안내 | 한곳에서 원문과 읽기 순서를 찾도록 정리 |
| 기술 Canonical·구조·매핑 | 읽기 전용. 새 product 요구로 임의 변경하지 않음 |
| SQL·기존 감사/검증 기록 | 원문 보존. 문서 작업으로 migration이나 과거 PASS를 변경하지 않음 |

파일이 `canonical/`에 있다는 이유만으로 모두 수정하거나 모두 금지하지 않는다. 사용자 승인 범위인 제품 PRD·기능·정책·UI만 편집하며, Source Guide, 시스템·Domain·Retrieval·Workflow·Interface·보안·환경·관측·테스트·평가·운영·Prompt 기술 계약과 Repository Architecture 하위 문서는 보존한다.

ZIP과 원격은 동일한 snapshot이 아니다. 원본 ZIP에는 당시 원격보다 앞선 PRD·UI 및 시스템·Domain·Workflow·Interface·보안·인프라·운영 문서의 변경이 있었다. 이를 문서 편집이 만든 변경으로 보거나 당시 원격에 모두 게시됐다고 보고하지 않는다. 보정 대상 6개 문서는 로컬 전체본에 원격 후속 변경을 반영한 뒤 Product `671360c`의 Git blob hash와 일치함을 확인했다. 보호 문서의 후속 구현 변경은 유지하며 이번 보정으로 덮어쓰지 않는다.

`database/migrations/0021_run_repository_default.sql`은 최초 문서 게시 때에는 ZIP에만 있었고 해당 문서 commit에 포함하지 않았다. 이후 Product `671360c`에는 0021과 `0022_local_conversation_actor.sql` 및 대응 코드 변경이 반영된 것이 확인된다. 파일 존재·계약 존재는 실제 DB migration 적용 또는 E2E 통과와 다르다. 이전 전체 ZIP을 현재 원격 tree와 같은 검증본으로 부르거나 저장소에 통째로 덮어쓰지 않는다.

## 3. 확인된 통합 기준선

Google/GitHub 공통 runtime 의미 통합은 Product에 반영됐다. 상세 원본 증거는 같은 폴더의 [통합 기록](2026-09-06-github-product-semantic-integration.md)에 보존한다.

| 항목 | 확인 기록 |
| --- | --- |
| Product 이전 기준 | `292538b429a93638afc1ba3a59f7efff7fb4c836` |
| 팀원 source | `69848b581e4fbccb88054572e7577c9024ee782f` |
| integration commit | `040b0bcaf82d3c8f8c2799dcc088304e500a3383` |
| Product 반영 | PR 184 / `7120df546dc94afdf9e0e3e25a48469ea836095f` |
| Gmail 실제 READ | Run `56be04e9-75b8-4695-a88d-bf56ac75bdc0` |
| GitHub 실제 READ | Run `676d9a5a-3dc3-403d-9045-fbbd2c4eec92` |
| 실행 환경 | Ollama `qwen3.5:9b`, 실제 Connector. 각 최종 답변 1개, Action 0 |
| 로그인 | GitHub 재시작 후 유지 확인 보고 |
| 미검증 | 실제 GitHub WRITE·권한 거부·토큰 만료 E2E |
| 기존 실패 | 구조 검사 3건, Google 제어 테스트 2건. 통합 이전에도 재현된 baseline이며 전체 GREEN 아님 |

통합 보고의 unit/contract 533, integration/component 158, 제어된 실행·복구 12, persistence 15, Frontend 117은 집계가 겹친다. 합계를 고유 테스트 수로 발표하지 않는다. 이번 문서 작업에서 runtime 테스트나 실제 앱 E2E를 새로 수행한 것은 아니다.

## 4. 이미 진행한 작업과 남은 범위

1~3의 기반은 되돌리거나 다시 만들지 않는다. 최종 Assistant 답변과 상태 기반 Supervisor, 기존 Gmail 조회·Evidence·bounded 검색 경로를 재사용한다. 통합한 Connector identity, repository provenance, CONNECTOR 후속 조회, Claim·Verification·인증의 경계도 유지한다.

3.1은 미완료다. 날짜·수신 시각·요일의 답변 사실성, 예산 소진 후 근거 기반 부분 종료, 사람 후보 해소와 검색 후 Confirmation, 개념/연도 일반성 검증이 남아 있다. 이전 Run이 COMPLETED였다는 사실은 이 품질 항목의 PASS가 아니다.

Connector 초기 연결 전제 분리 코드는 `e944adc08608ac6282f516978d9a6130411defe7`(로컬 workspace 진입)과 `671360c112531c5aa2242c82d5f20418d00da34a`(요청별 prerequisite 종료)로 원격 반영됐다. Settings·repository 연결 변경도 `8fa145a19266d8315582b647742fa517cab0b8fe`에서 확인된다. 이번 문서 작업은 구현 전체 정확성이나 신규 실제 앱 E2E를 증명하지 않았으므로 이를 제품 PASS로 승격하지 않는다.

Task/Calendar 4는 PARKED이며 이 문서 작업이 재개나 완료를 뜻하지 않는다. GitHub 로그인·명시 저장소 READ는 확인됐지만 설정의 저장소 기본값 전체 경로나 WRITE 검증은 별도로 확인해야 한다.

## 5. 확정된 후속 작업 순서

| 순서 | 작업 | 닫아야 할 결과 | 인계 시점 상태 |
| --- | --- | --- | --- |
| 선행 Settings | Google·GitHub·Gemini 영역, 기존 연결 UI 경로, 저장소 선택/기본값 | 기존 UI가 있으면 재생성하지 않고 인증→저장→실제 READ까지 연결. 다른 연결 독립성 유지 | 로그인/READ 일부 확인. 설정 코드 반영 확인, 전체 Live 설정 경로는 별도 검증 |
| 선행 연결 전제 | Core readiness와 요청별 Connector availability 분리 | Google/GitHub 미연결로 UI 진입을 막지 않음. 초기 사용 불가는 안내 후 종료·새 요청, 실행 중 만료는 기존 안전 재개 | 코드·관련 계약 반영 확인, 실제 앱 E2E 미확인 |
| 3.1 | Semantic Retrieval 잔여 | 날짜 사실성, bounded 의미 검색, 후보/확정 구분, 검색 후 선택·resume, 부분 답변 | INCOMPLETE |
| 4-A | Task WRITE 재개 | 승인 Preview와 실제 제목·메모·목록·예정일 일치, duplicate와 재조회 검증 | PARKED |
| 4-B | Calendar WRITE 재개 | 직접/메일 기반 생성, 행사일·시간대·충돌·참석자, 재조회 검증 | PARKED |
| 4.5 | Task 승인·수정 UX | compact Preview, 자연어 수정, 명시적 제거와 값 유지, 새 Preview·재승인 | 요구 확정·구현 검증 필요 |
| 5 | Gmail WRITE | Draft 생성/수정, SEND/Reply, Thread·수신 범위, 실제 결과 검증 | 전체 closure 미확인 |
| 5.5 | GitHub 실제 제품 | 테스트 저장소 Issue list/get/create/update/close/reopen, 공통 승인·검증 | Live WRITE 미검증 |
| 6 | 공통 Recovery | refresh/reconnect/reauth/restart/불확실 결과/취소/부분 성공, 중복 효과 방지 | 전체 matrix 미검증 |
| 6.5 | 독립 구조 검수 | 단일 authority, 계층·호출·state 계약, 과도한 책임의 실제 위반만 최소 수정 | 예정 |
| 7 | Local Runtime 준비 | 수동 CLI 없는 Ollama/9B 준비, digest, 기존 설치 보존, 재시도·upgrade·uninstall | 개발 추론과 설치 제품 검증을 구분 |
| 7.5 | 상태 기반 누적 Activity | 이전 행 유지·회차 구분·클릭 상세·복원. 표시용 추가 LLM/외부 Tool 0 | 요구 확정·미완료 |
| 8 | 최종 제품·설치·Release | full regression, 서비스별 Live round trip, clean install, 보안·구조·문서 정합성 | 예정 |

상세 기능·정책·화면 정의를 이 표에 다시 복제하지 않는다. 각 단계는 현재 code와 직전 인계를 먼저 조사하여 이미 되는 기능을 재사용하고 미완료 연결만 닫는다. 필수 선행 blocker는 해결하거나 명시적으로 인계하며 성공으로 덮지 않는다.

### 5.1 추가된 연결 전제 작업의 인계

Google Workspace는 P0 핵심 기능으로 유지한다. 제거하는 것은 Google 로그인이 Core startup·readiness·메인 UI·기본 Run 생성의 필수조건이라는 결합이다. Google과 GitHub 모두 필요한 요청에서 연결·접근 가능 상태를 확인한다.

초기 미연결, GitHub App 미설치, repository 접근 불가, 필수 permission 부족은 필요한 조치를 안내하고 현재 요청을 종료한다. 연결 후 사용자가 새 요청을 보내며 durable auth-wait·callback 자동 resume·설치 watcher를 만들지 않는다. 정상 실행 중 Credential 만료의 기존 REAUTH_REQUIRED·safe resume·in-flight 처리 계약은 유지한다.

구현 검증은 startup/onboarding/대화·Run 생성의 기존 Google 전제, request/route availability 검사 위치, Google Sidebar Connect CTA, Connector 간 독립성을 확인해야 한다. 실제 앱에서 양쪽 모두 미연결 UI 진입, Google 미연결 요청 종료와 연결 후 새 요청, GitHub의 동일 경로, 한쪽만 연결된 각각의 정상 요청, 실행 중 Credential 만료의 기존 안전 재개를 검증한다. 요청 ID가 초기 실패 후 재전송에서 달라지고, 기존 실행 중 만료의 명시적 재개에서는 유지되는지 Backend와 화면을 대조한다.

관련 코드와 일부 기술 계약 변경은 원격에 반영됐다. 문서 담당은 실제 앱 테스트를 대신 수행했다고 보고하지 않는다. 최초 미연결 종료와 실행 중 재인증의 구분, 데이터 호환, 남은 기술 문서의 정합성은 구현 검증 결과와 함께 확인한다.

## 6. 구현·검증 방식

기존 owner와 production caller를 추적하고 짧은 계획 뒤 수정·영향 테스트·실제 앱 검증을 반복한다. Settings UI/API가 이미 있으면 재생성하지 않고 render/composition/contract의 끊긴 경로를 복구·재사용한다. Column·Index는 실제 조회와 Query Plan을 근거로 필요한 것만 검증하며 이 구현 지침을 기능 정의나 정책의 별도 규칙으로 복제하지 않는다. Canonical의 계층·dependency·operation-per-file·naming을 지키며 UI/LangGraph에 업무 권위를 옮기지 않는다. Schema/Prompt/API/SSE/checkpoint를 바꿔야 하면 허용된 계약 절차로 producer·consumer·validator·호환성을 함께 연결한다.

실제 앱 E2E는 Frontend에서 자연어 요청과 승인·수정·새로고침을 조작하는 경로다. Backend log/Trace를 Run ID로 연결해 실제 runtime/model, Prompt, Stage/Supervisor, Connector 대상, Action/Attempt/Verification과 최종 상태를 비교한다. WRITE는 허용된 테스트 대상에서 승인 Preview·저장 인자·실제 외부 결과·재조회를 대조한다.

Playwright는 실제 UI 조작 수단으로 사용할 수 있으나 fake LLM/Connector, direct API/Graph, fault injection만 수행한 결과는 실제 앱/Provider PASS가 아니다. 각 종류의 증거를 구분한다. 권한·계정·모델·설치 환경이 없으면 PENDING/BLOCKED다.

각 단계에서는 직접 영향 테스트·typing/lint·구조 검사를 수행하고 전체 회귀는 8에서 수행한다. 검사를 약화하거나 테스트를 삭제하여 통과시키지 않는다. coherent commit/push와 local/remote 일치, untracked 포함 작업 상태를 인계한다.

## 7. 기술 계약·구현·검증 상태의 구분

보호 기술 문서는 이번 보정에서 수정하지 않는다. 이전 ZIP에서 발견한 간극과 이후 Product에 반영된 계약을 구분한다. 문서상 해소된 항목을 계속 계약 부재로 기록하지 않고, 반대로 계약 추가만으로 실행 검증까지 끝났다고 보지 않는다.

| 지점 | 확인할 계약 경계 |
| --- | --- |
| Connector 초기 연결 전제 | 과거 ZIP의 Conversation Google FK 간극에 대해 최신 Domain·DB는 local-workspace attribution과 0022 forward migration을 정의한다. 초기 미연결 종료와 기존 REAUTH_REQUIRED 유지도 코드 변경이 있다. 실제 migration 적용·기존 계정 이력·실행 중 만료 회귀는 별도 검증 대상이다. |
| 기본 GitHub repository | 업로드 Workflow·Interface·인프라에 SETTINGS_DEFAULT provenance·Run binding이 이미 있었고 최신 Product에도 0021/관련 코드가 반영됐다. 계정 변경·접근 상실·명시 저장소 override의 실제 앱 검증과 구분한다. |
| 검색 후 사람 선택 | 후보 state·기존 Confirmation/controller·checkpoint의 same-Run 연결 |
| READ budget 종료 | 현재 RunBudget 한도 보존과 terminal result. 증거 없는 성공/Write 우회 금지 |
| 누적 Activity | 관측 계약의 agent_invocation_id/local_attempt_no 등 기존 이력을 우선 사용한다. process-local SSE 버퍼와 최신 Snapshot만으로 과거 상세를 재구성했다고 가정하지 않는다. 회차별 결과 보존·조회·재접속 연결은 7.5에서 검증한다. |
| 자연어 Task 수정 | 기존 modify/review/reapproval와 schema/version 무결성 |
| Local provisioning | 기존 승인 모델/manifest·서명·설치 origin·replay 계약의 실제 구현 |
| Google 개발 OAuth 예외 | 업로드 정책·보안·인프라·테스트의 EXPLICIT_DEVELOPMENT 한정 optional secret 예외는 문서상 일치한다. 실제 저장·redaction·Signed 배포 제외 검증은 별개이며 제품 secret 사용으로 확대하지 않는다. |
| 구 Google-only 설명 | 보호된 기술 문서와 통합된 실제 Connector 계약을 대조한다. 새 코드가 반영됐어도 남은 ERD·과거 lifecycle·검증 설명까지 자동 정합화됐다고 보지 않는다. 무조건 문자열 치환 금지. |
| Header 검증 | 제품 UX는 정상 Google chip/계정을 Settings로 옮기지만 보호 테스트 TST-UI-201의 Header 표시 요구가 남아 있다. 후속 검증 계약에서 정리하며 UI를 되돌리거나 assertion을 약화하지 않는다. |
| Migration 안내 | database/README의 0001 단독 fresh-install 설명과 0019~0022 forward/adoption 파일의 실제 적용 순서를 구현 담당이 대조해야 한다. SQL 재번호·실행으로 문서 보정을 대신하지 않는다. |
| 기존 표 형식 | 보호 문서의 비escape pipe로 인한 열수 불일치 후보는 원본부터 있었으며 이번에 수정하지 않는다. Notion 게시 시 원문 의미를 잃지 않는 표시 변환과 경고를 별도로 검증한다. |

여기서 필요한 보호 계약 변경은 별도 승인된 범위로 처리한다. PRD나 기능 정의를 근거로 새 Port·Domain 전이·operation·enforcement 예외를 몰래 만들지 않는다. 기존 기술 계약 자체의 버전·날짜도 이번 편집에서는 그대로 둔다.

## 8. Notion 게시 원칙

Notion 루트는 `MCP-Work-Agent`이며 주요 현행 문서를 번호순으로 직접 나열한다. 단일 문서는 바로 열고, 실제 독립 원문이 여러 개인 주제만 하위 문서 목록을 둔다. 문서 페이지 안에 사람이 읽는 요약과 원문 전체를 함께 제공한다. PRD와 요구사항이 하나의 원문이면 두 페이지로 복제하지 않는다. Notion 번호는 탐색용이며 원문의 기능·정책 ID나 파일명을 재번호하지 않는다.

제품 정의와 선정된 주요 기술 원문은 현행 번호 목록에 둔다. 변경 이력·선택 이유·작업 현황·과거 안내와 기타 참고 자료는 `90 변경 이력 / 선택 이유 / 참고 자료`에 모은다. 기술 문서라는 이유만으로 현행 원문을 숨기지 않는다. Repository Architecture 하위 매핑·SQL·감사 CSV를 모두 Notion 페이지로 복제하지 않고 필요한 GitHub 원문을 참조한다.

GitHub 수정·전체 로컬 검수·Product 반영을 먼저 완료한다. 이후 Notion 구조를 재배치하고 선정한 원문 전체를 게시한 뒤 같은 페이지 상단에 요약을 추가한다. 기존 페이지 ID와 child page를 가능한 한 재사용·보존하며 본문 원문은 전체본 단위로 교체한다. 요약은 원문에서만 도출하고 정합화 대기는 원문 밖에 구분한다. 원문 수정일을 단순 게시일로 바꾸거나 버전 의존 체인을 만들지 않는다. API 성공과 최종 본문·부모 관계 검증은 구분하고 기존 child를 무단 삭제하지 않는다.

## 9. 완료 판정

이번 문서 작업의 완료는 수정 범위·보호 파일 무변경·자체 ID 보존·문서 목적·링크·중복 정의·버전 결합·구현 상태 표현을 검수하고, docs-only commit의 Product 반영 및 선정한 Notion 전체본 게시를 확인한 시점이다.

제품 출시 완료는 별개다. Semantic Retrieval, 서비스별 WRITE, Recovery, 설치 제품, full regression 등의 미검증 항목은 문서가 정리돼도 그대로 남는다.
