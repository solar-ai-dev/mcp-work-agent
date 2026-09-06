# 제품 작업 현황 · 남은 검증

수정일: 2026-09-06  
문서 역할: 제품 요구사항 정리와 구현·검증 인계 기록. 새로운 Canonical·정책·실행 계약이 아니다.

## 1. 기준과 읽는 방법

이번 정리는 사용자가 제공한 `docs.zip` 전체 48개 파일과 이 대화에서 확정한 제품 결정을 기준으로 한다. 원격 비교 기준은 `product/issue-181-runtime-closure`의 `7120df546dc94afdf9e0e3e25a48469ea836095f`다. 문서 편집은 `docs/product-runtime-realignment`에서 수행한다.

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

ZIP과 원격은 동일한 snapshot이라고 가정하지 않는다. 기능·정책 파일은 줄바꿈 정규화 후 기준 원격과 일치한다. PRD의 `mcp-work-agent` 표시명과 UI의 계정별 Settings/간결한 Header 등 업로드본 변경은 이번 제품 정리에 보존한다.

ZIP에만 있는 `database/migrations/0021_run_repository_default.sql`은 대응 코드·적용 이력을 확인하지 않은 로컬 제공 자료다. 원본/전체 편집 ZIP에는 그대로 보존하지만 이번 GitHub 문서 commit에 신규 SQL로 포함하지 않는다. 누락된 원격 파일을 삭제하는 방식으로 ZIP을 통째로 덮어쓰지 않는다.

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

사용자는 Connector 초기 연결 전제를 요청 단위로 분리하는 구현을 진행 중이라고 추가 인계했다. 아직 해당 변경의 code SHA나 실제 앱 E2E 완료 증거를 제공받지 않았으므로 이 문서에서 구현 PASS로 표시하지 않는다.

Task/Calendar 4는 PARKED이며 이 문서 작업이 재개나 완료를 뜻하지 않는다. GitHub 로그인·명시 저장소 READ는 확인됐지만 설정의 저장소 기본값 전체 경로나 WRITE 검증은 별도로 확인해야 한다.

## 5. 확정된 후속 작업 순서

| 순서 | 작업 | 닫아야 할 결과 | 인계 시점 상태 |
| --- | --- | --- | --- |
| 선행 Settings | Google·GitHub·Gemini 영역, 기존 연결 UI 경로, 저장소 선택/기본값 | 기존 UI가 있으면 재생성하지 않고 인증→저장→실제 READ까지 연결. 다른 연결 독립성 유지 | 로그인/READ 일부 확인, 전체 설정 경로 검증 필요 |
| 선행 연결 전제 | Core readiness와 요청별 Connector availability 분리 | Google/GitHub 미연결로 UI 진입을 막지 않음. 초기 사용 불가는 안내 후 종료·새 요청, 실행 중 만료는 기존 안전 재개 | 사용자 보고: 구현 진행 중, E2E 미확인 |
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

이 단계는 구현 담당 작업으로 진행 중이다. 문서 담당은 요구사항만 반영하며 테스트를 대신 수행했다고 보고하지 않는다. 제품 동작 확정 후 관련 기술 계약 정합화는 해당 구현의 후속 작업으로 남긴다.

## 6. 구현·검증 방식

기존 owner와 production caller를 추적하고 짧은 계획 뒤 수정·영향 테스트·실제 앱 검증을 반복한다. Canonical의 계층·dependency·operation-per-file·naming을 지키며 UI/LangGraph에 업무 권위를 옮기지 않는다. Schema/Prompt/API/SSE/checkpoint를 바꿔야 하면 허용된 계약 절차로 producer·consumer·validator·호환성을 함께 연결한다.

실제 앱 E2E는 Frontend에서 자연어 요청과 승인·수정·새로고침을 조작하는 경로다. Backend log/Trace를 Run ID로 연결해 실제 runtime/model, Prompt, Stage/Supervisor, Connector 대상, Action/Attempt/Verification과 최종 상태를 비교한다. WRITE는 허용된 테스트 대상에서 승인 Preview·저장 인자·실제 외부 결과·재조회를 대조한다.

Playwright는 실제 UI 조작 수단으로 사용할 수 있으나 fake LLM/Connector, direct API/Graph, fault injection만 수행한 결과는 실제 앱/Provider PASS가 아니다. 각 종류의 증거를 구분한다. 권한·계정·모델·설치 환경이 없으면 PENDING/BLOCKED다.

각 단계에서는 직접 영향 테스트·typing/lint·구조 검사를 수행하고 전체 회귀는 8에서 수행한다. 검사를 약화하거나 테스트를 삭제하여 통과시키지 않는다. coherent commit/push와 local/remote 일치, untracked 포함 작업 상태를 인계한다.

## 7. 보호 계약과의 정합성 확인 대기

다음은 이번 문서 작업에서 기술 계약을 수정하지 않았으므로 후속 구현에서 확인해야 할 지점이다. 단순 문구 변경으로 해결됐다고 보지 않는다.

| 지점 | 확인할 계약 경계 |
| --- | --- |
| Connector 초기 연결 전제 | Core startup/readiness·온보딩·Google account에 결합된 Conversation/Run 생성 경계, 요청 종료 방식, 초기 미연결과 기존 REAUTH_REQUIRED의 구분. 보호 Domain/DB/Workflow/Interface/Security/Infrastructure 계약은 이번에 수정하지 않음 |
| 기본 GitHub repository | 설정 provenance와 Run binding, 계정 변경 검증. ZIP의 단독 migration을 실행 근거로 사용하지 않음 |
| 검색 후 사람 선택 | 후보 state·기존 Confirmation/controller·checkpoint의 same-Run 연결 |
| READ budget 종료 | 현재 RunBudget 한도 보존과 terminal result. 증거 없는 성공/Write 우회 금지 |
| 누적 Activity | 기존 occurrence/history와 SSE/Snapshot 복원 가능성. 최신 상태만으로 이력을 만들지 않음 |
| 자연어 Task 수정 | 기존 modify/review/reapproval와 schema/version 무결성 |
| Local provisioning | 기존 승인 모델/manifest·서명·설치 origin·replay 계약의 실제 구현 |
| Google 개발 OAuth 예외 | 업로드 정책에 있는 개발 전용 optional secret 예외와 보호 보안 계약의 일치 여부. Signed 배포 확대 금지 |
| 구 Google-only 설명 | 보호된 기술 문서와 통합된 실제 Connector 계약의 local consequence. 무조건 문자열 치환 금지 |

여기서 필요한 보호 계약 변경은 별도 승인된 범위로 처리한다. PRD나 기능 정의를 근거로 새 Port·Domain 전이·operation·enforcement 예외를 몰래 만들지 않는다. 기존 기술 계약 자체의 버전·날짜도 이번 편집에서는 그대로 둔다.

## 8. Notion 게시 원칙

Notion의 첫 화면은 제품 목적·기능·정책·UI 원문과 현재 작업 현황을 바로 찾을 수 있게 한다. 원문 한 페이지 안에 개요와 상세를 함께 두며 설명본을 또 다른 정답처럼 만들지 않는다.

새로 갱신하는 본문은 이번 수정 제품 문서와 이 현황의 전체본이다. 기술 계약·매핑표·migration·감사 CSV 전체를 다시 게시하지 않는다. 기존 기술 페이지와 과거 기록은 보존하고 개발용 참고/Archive로 분리한다.

GitHub 문서 commit이 작업 브랜치에 반영된 뒤 같은 확정본으로 Notion을 갱신한다. 페이지 ID와 child page를 보존하고 본문은 전체 교체한다. 여러 페이지의 교체는 API상 여러 호출일 수 있으므로 한 페이지 단위 완료·검증을 기록하며, 전체를 한 원자 transaction처럼 보고하지 않는다. 기존 페이지나 child를 무단 삭제하지 않는다.

## 9. 완료 판정

이번 문서 작업의 완료는 수정 범위·보호 파일 무변경·자체 ID 보존·문서 목적·링크·중복 정의·버전 결합·구현 상태 표현을 검수하고, docs-only commit의 Product 반영 및 선정한 Notion 전체본 게시를 확인한 시점이다.

제품 출시 완료는 별개다. Semantic Retrieval, 서비스별 WRITE, Recovery, 설치 제품, full regression 등의 미검증 항목은 문서가 정리돼도 그대로 남는다.
