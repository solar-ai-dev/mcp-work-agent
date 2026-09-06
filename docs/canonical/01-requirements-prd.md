# 01. 요구사항 정의서 · PRD

수정일: 2026-09-06  
상태: 제품 요구사항 — 구현·검증 완료 여부는 별도 기록  
목적: 제품 목표·범위·출시 완료 조건

## 0. 한눈에 보기

mcp-work-agent는 개인 PC에서 Gmail·Google Tasks·Google Calendar와 GitHub Issue의 업무 정보를 연결하는 Work Agent다. 사용자는 자연어로 목표를 제시하고, 제품은 필요한 자료를 찾아 결과 또는 실행안을 준비한다. 사용자는 필요한 확인과 최종 승인에 집중한다. 큰 입력 Form을 채우는 도구나 무승인 자동 실행 도구가 아니다. Google Workspace는 P0 핵심 Connector로 유지하지만 Google 또는 GitHub의 로그인은 앱 실행·메인 화면 진입의 전역 선행조건이 아니다.

기본 Local profile의 제품 결정은 Ollama `qwen3.5:9b`다. WORKER와 REASONING은 책임 구분을 유지하지만 같은 모델을 사용한다. 개발 앱의 실제 추론 확인과 서명된 설치 제품의 출시 승인은 구분한다.

## 1. 문서 목적

이 문서는 대상 사용자, 해결할 문제, 출시 범위와 성공 기준만 정의한다. 기능의 상세 동작은 기능 정의, 허용·차단 기준은 정책 정의, 표시·조작은 UI·UX가 각각 소유한다. 문서 간 버전 또는 기능 번호를 연쇄 의존성으로 사용하지 않는다.

### 1.1 문서 권위·책임 소유 규칙

전문 계약의 권위는 Project Source Guide를 따른다. 이 PRD로 코드 위치, 새 Domain 전이, API schema, Prompt slot 또는 Repository 예외를 만들지 않는다. 보호 계약과 새 제품 요구 사이의 구현 간극은 작업 현황에 기록하고, 요구사항 작성만으로 해소됐다고 판단하지 않는다.

## 2. 제품 개요

제품은 단일 사용자용 로컬 UI와 Agent Runtime으로 구성된다. Google Workspace와 GitHub는 공통 Connector 경계와 승인·실행·검증 흐름을 사용하되, 각 서비스의 identity와 효과는 구분한다.

Agent는 요청 의미·자료·관계·계획을 다룬다. 결정적 코드는 현재 상태와 검증된 결과를 사용해 다음 책임, 권한, 승인, 외부 실행과 검증을 통제한다. 제품 UI는 그 결과를 표현하며 독립 실행 권한을 만들지 않는다.

### 2.1 Agent · Role · LLM Call · Subgraph 정의

Agent는 전문 책임을 수행하는 workflow 구성이고, Role은 그 책임의 의미다. LLM call은 모델 추론 한 번이므로 Agent 수와 같지 않다. 물리 Subgraph 구성과 semantic owner의 수는 별개이며, 지원 Graph Profile의 상세는 Workflow 계약에 둔다. 자유형 Agent 군집으로 설명하지 않는다.

### 2.2 Conversation · Run 의미 경계

Conversation은 메시지와 Run의 표시·영속 이력이다. 종료된 Run 다음에는 같은 대화 안에서도 새 Run으로 요청할 수 있다. 이전 대화의 모든 원문·근거·승인·checkpoint가 새 요청의 숨은 기억으로 넘어가지 않는다. 이번 요청에서 명시적으로 선택한 자료와 현재 설정만 시작 문맥에 사용한다. 같은 Run의 확인 질문·재인증·복구는 기존 작업을 안전하게 이어간다. 한 Conversation에는 동시에 하나의 열린 Run만 둔다. 기본 Conversation·Run 생성이 Google Credential 존재 여부에 전역 결합되면 안 된다. 필요한 Connector가 처음부터 미연결인 요청은 안내 후 종료하고, 연결 후 사용자가 다시 보내는 요청은 새 Run이다.

## 3. 목표 사용자

본인에게 필요한 Google 업무 또는 접근 권한이 있는 GitHub repository를 사용하며, 개인 PC에서 자연어로 업무를 찾고 정리하고 실행하려는 사용자다. 기본 지원 환경은 Windows 11 x64와 Chrome·Edge의 로컬 UI다. Python·Node·포트 설정은 일반 사용자 준비물이 아니다. Google은 동시에 하나의 활성 계정이라는 기존 범위를 유지한다.

## 4. 해결할 문제

업무가 메일·Task·일정·Issue에 흩어져 후속 작업이 누락된다. 사용자 표현과 자료의 표현이 달라 literal 검색만으로는 놓치는 자료가 생긴다. 수신일·행사일·예정일·실제 업무 마감이 혼동되며, 중복·충돌이나 잘못된 상대에게 실행될 위험이 있다. 실행 응답 유실과 UI 재접속 이후에도 실제 변경 사실을 이해할 수 있어야 한다.

## 5. 제품 목표

요청에 필요한 Source만 조회하고, 확인된 근거로 답변 또는 실행안을 만든다. 제목에 검색어가 없거나 사람 이름이 별칭·이메일로 표현된 경우에도 제한된 검색으로 의미를 해소한다. 결정 가능한 값은 제품이 완성하고, 실제 선택이나 권한 확인이 필요할 때만 질문한다.

다음 단계는 고정 순서가 아니라 상태·규칙·검증된 artifact와 freshness로 결정한다. 불필요한 책임은 생략하고 필요한 추가 검색·재검토만 제한적으로 수행한다. 완료·부분 결과·검색 실패·승인 대기·불확실한 외부 결과를 구분해 설명한다.

### 5.1 Local Runtime provisioning 제품 결정

LOCAL_CAPABLE은 기존 호환 Ollama를 재사용하거나 승인된 runtime과 모델을 준비한다. 사용자가 별도 CLI에서 설치·model pull을 할 필요가 없어야 한다. 대형 모델 weight는 Installer에 내장하지 않고 검증된 배포 경계로 준비한다. 기존 공유 runtime과 다른 모델을 훼손하지 않는다.

이번 기본 모델은 `qwen3.5:9b` 하나다. 4B는 향후 profile option일 수 있으나 현재 필수 설치·활성 모델이 아니다. WORKER/REASONING 추상화는 유지하고 같은 Run의 임의 model switching은 추가하지 않는다. 서명·digest·품질·하드웨어·설치 검증 전에는 공개 Release 준비 완료를 선언하지 않는다.

## 6. 비목표

원격 SaaS·멀티 사용자 Backend, CPU Local 추론, 무승인 외부 WRITE, Gmail Message/Thread 원문 삭제, 반복 Event 전체 일괄 수정, 전체 mailbox 상시 복제, 실시간 감시 기반 자율 업무 실행, 범용 웹 브라우징, Agent별 장기 기억은 현재 범위가 아니다. GitHub PR·코드 수정은 Issue 지원에 자동 포함하지 않는다. 첨부파일의 내용 분석은 향후 범위다.

## 7. 제품 원칙

사용자 통제, 근거 기반 결과, 결정적 안전성, 최소 데이터, 부분 성공 보존, 로컬 우선을 유지한다. 원문 Source는 실행 지시가 아니며, UI 진행 정보는 새로운 업무 판단이 아니다. 설명을 위해 별도의 LLM 호출을 추가하지 않고 이미 생성된 상태·결과를 사용한다.

## 8. 대표 사용자 시나리오

| 시나리오 | 사용자 목표 |
| --- | --- |
| UC-01 메일 요청을 업무로 전환 | 관련 메일에서 확인한 내용으로 Task·Event·회신안을 준비하고 승인한다. |
| UC-02 회의 후 후속 업무 정리 | 관련 자료를 연결해 누락된 후속 작업을 찾는다. |
| UC-03 이번 주 업무 마감 위험 분석 | Task 예정일과 실제 마감, 소요시간과 Calendar 가용성을 구분해 판단한다. |
| UC-04 읽기 전용 탐색 | 사람·기간·업무 개념으로 자료를 찾고 외부 변경 없이 답변받는다. |
| UC-05 일부 승인 | 여러 Action 중 필요한 것만 승인하고 결과와 미실행 범위를 확인한다. |
| UC-06 GitHub Issue 업무 | 연결된 계정의 작업 repository에서 Issue를 읽고 승인된 변경을 수행한다. |

## 9. 기능 요구사항

기존 요구 ID는 유지한다. 아래 표는 제품 완료 기준이며 상세 기능의 복제본이나 다른 문서의 번호 연결표가 아니다.

### 9.1 초기 설정·인증

| ID | 제품 완료 기준 |
| --- | --- |
| FR-001 | Google·GitHub가 모두 미연결이어도 Core가 준비되면 메인 화면에 진입한다. 최초 온보딩의 Google 로그인을 건너뛸 수 있다. |
| FR-002 | 제품 소유 OAuth 구성으로 Google 로그인과 필요한 동의를 진행한다. |
| FR-003 | Google 계정 변경 시 기존 계정 문맥과 새 계정 문맥이 섞이지 않는다. |
| FR-004 | Credential이 일반 저장·로그·표시 경로에 노출되지 않는다. |
| FR-005 | 개발·스테이징·운영 인증 환경을 구분한다. |
| FR-006 | Launcher로 시작하며 개발용 명령이 필요하지 않다. |
| FR-007 | UI/API 비호환을 안전하게 안내하고 잘못된 실행을 막는다. |
| FR-008 | 로컬 same-origin 제품 경계를 사용한다. |
| FR-009 | Settings에서 Google Workspace, GitHub, Gemini API를 구분하고 GitHub 인증·repository 선택에서 실제 READ까지 이어진다. 연결 완료가 종료된 요청의 자동 재개를 유발하지 않는다. |

### 9.2 추론 Runtime

| ID | 제품 완료 기준 |
| --- | --- |
| FR-010 | LOCAL_CAPABLE에서 승인된 Ollama와 모델을 수동 CLI 없이 준비한다. |
| FR-011 | CPU-only·GPU 기준 미달 환경은 API 경로를 사용한다. |
| FR-012 | 지원 환경에서 사용자 요청 모드와 실제 사용 모드를 확인할 수 있다. |
| FR-013 | AUTO의 허용된 기술적 실패에 한해 동의를 갖춘 API fallback을 제한적으로 수행한다. |
| FR-014 | 명시적 Local 선택을 조용히 외부 모델로 바꾸지 않는다. |
| FR-015 | Local runtime은 Ollama다. |
| FR-016 | API_ONLY와 LOCAL_CAPABLE의 준비 항목·설치 부작용을 구분한다. |
| FR-017 | WORKER/REASONING 모두 기본 9B profile을 소비하며 모델 선택 권한이 여러 곳에 생기지 않는다. |

### 9.3 요청·Context·Retrieval

| ID | 제품 완료 기준 |
| --- | --- |
| FR-020 | 자연어의 목표·완료 조건·의미 제약을 손실 없이 보존한다. |
| FR-021 | 현재 요청에 필요한 Connector를 판단한다. 초기 미연결·App 미설치·저장소 접근 불가·permission 부족은 필요한 조치 안내 후 요청을 종료하고 연결 후 새 요청으로 처리한다. |
| FR-022 | 각 Source의 검색·조회 기능을 사용하고 제한된 검색 이력을 추적한다. |
| FR-023 | 결과에 출처·Resource identity·근거 위치가 유지된다. |
| FR-024 | 새 정보 가능성이 있을 때만 제한된 재검색을 하며, 예산 소진 시 확보한 근거의 범위에서 종료한다. |
| FR-025 | 조회로 해소할 수 있는 모호성은 먼저 탐색하고, 남은 실질적 선택만 사용자에게 묻는다. |
| FR-026 | 긴 Thread의 Message·항목·날짜 관계를 보존해 필요한 내용을 찾는다. |
| FR-027 | literal 단어와 의미 검색, 수신일과 행사일, 후보 인물과 해소된 identity를 구분한다. |

### 9.4 분석·계획

| ID | 제품 완료 기준 |
| --- | --- |
| FR-030 | 자료 간 업무 관계를 근거와 함께 제시한다. |
| FR-031 | Task 중복·Calendar 충돌과 필요한 확인을 제시한다. |
| FR-032 | 예정일·실제 마감·가용성·소요시간을 구분해 업무 가능성을 판단한다. |
| FR-033 | 독립·종속 Action을 구분한다. |
| FR-034 | 사용자가 대상·변경 내용·근거·위험·기대 결과를 확인할 수 있는 계획을 제시한다. |

### 9.5 승인·수정

| ID | 제품 완료 기준 |
| --- | --- |
| FR-040 | 외부 WRITE 전에 해당 변경의 사용자 승인을 받는다. |
| FR-041 | 전체·일부 승인, 수정, 거절을 지원한다. |
| FR-042 | 수정은 재검토와 새 승인으로 연결되며 Task는 자연어 수정과 compact preview를 우선한다. |
| FR-043 | 승인한 내용과 실제 실행 내용이 일치한다. |
| FR-044 | 승인 만료·근거 변경을 감지하고 재확인이 필요한 상태를 설명한다. |

### 9.6 실행·검증·복구

| ID | 제품 완료 기준 |
| --- | --- |
| FR-050 | 현재 승인과 실행 admission을 통과한 Action만 외부에 실행한다. |
| FR-051 | 출시 범위의 Gmail·Task·Calendar·GitHub Issue 변경을 공통 lifecycle로 처리한다. |
| FR-052 | 외부 변경 결과를 해당 서비스에서 재확인한다. |
| FR-053 | 정상화 차이와 실제 불일치를 구분한다. |
| FR-054 | 부분 성공을 보존하고 실패·미실행·종속 차단을 구분한다. |
| FR-055 | refresh·reconnect·재시작과 정상 실행 중 Credential 만료 후 같은 작업의 사실을 안전하게 복원한다. 초기 미연결로 종료한 요청은 복원 대상의 인증 대기 Run이 아니다. |
| FR-056 | 실시간 진행과 저장된 상태 복원이 같은 결과를 보여준다. |
| FR-057 | 변경 요청의 중복·동시 실행을 안전하게 구별한다. |
| FR-058 | 같은 요청의 재전송은 변경을 다시 만들지 않는다. |
| FR-059 | 다른 Connector·대상·승인의 실행 증명을 재사용할 수 없다. |

### 9.7 관측성

| ID | 제품 완료 기준 |
| --- | --- |
| FR-060 | 현재 runtime/model과 요청·조회·실행·검증 결과를 민감정보 없이 진단할 수 있다. |
| FR-061 | 실제 실행 회차가 누적되는 Activity Timeline과 행별 상세를 제공하고, 표시를 위한 추가 LLM·외부 Tool 호출을 하지 않는다. |

## 10. 비기능 요구사항

| ID | 요구사항 |
| --- | --- |
| NFR-001 | 서비스는 loopback에만 노출한다. |
| NFR-002 | Token·API Key를 로그·SQLite에 기록하지 않는다. |
| NFR-003 | 외부 LLM 전송 동의와 실제 전송 범위를 구분해 알린다. |
| NFR-004 | 승인 준수·금지 작업 차단·필수 검증은 안전 Gate다. |
| NFR-005 | 재시도·복구로 동일한 외부 효과를 중복 생성하지 않는다. |
| NFR-006 | 진행 중 실제 작업 상태와 중단 수단을 제공한다. |
| NFR-007 | Windows 11 x64와 로컬 Chrome·Edge 제품을 검증한다. |
| NFR-008 | 입출력 계약은 검증 가능한 typed schema를 사용한다. |
| NFR-009 | 실제 제품 경계를 유지한 test double과 통합검증이 가능하다. |
| NFR-010 | 승인·실행·검증의 안전 기록을 보존한다. |
| NFR-012 | API_ONLY는 Ollama 없이 설치·실행 가능하다. |
| NFR-013 | 모든 외부·사용자·모델 입력을 경계에서 검증한다. |
| NFR-014 | 원문과 Markdown을 안전하게 렌더링한다. |
| NFR-015 | 사용자 오류 설명과 민감한 기술 진단을 분리한다. |
| NFR-016 | Host·Origin·Local Session을 검증한다. |
| NFR-017 | 조건부 상태 변경과 중복 방지로 경쟁을 처리한다. |
| NFR-018 | 외부 호출 동안 DB transaction과 Write lock을 유지하지 않는다. |
| NFR-019 | 필수 영속 무결성을 DB·Repository에서도 강제한다. |
| NFR-020 | 호환성을 확인한 migration·backup·복구 경계를 제공한다. |
| NFR-021 | 증가하는 이력은 bounded 조회와 안정적인 pagination을 사용한다. |
| NFR-022 | 조회·추론·재시도·Context·실행 시간은 제한한다. |
| NFR-023 | dependency·서명·artifact·모델 무결성을 Release에서 확인한다. |
| NFR-024 | 실제 Restore와 데이터 무결성을 검증한다. |
| NFR-025 | 일회성 bootstrap을 안전한 Local Session으로 교환한다. |
| NFR-026 | 운영 UI와 Local API는 same-origin이다. |
| NFR-027 | 진행 Event에 비밀·불필요한 원문을 담지 않는다. |
| NFR-028 | REST 경계의 입력과 허용값을 검증한다. |

## 11. 데이터 요구사항

전체 mailbox·repository 내용을 제품 DB에 상시 복제하지 않는다. 사용한 Resource 참조·최소 Evidence·사용자 메시지·계획·승인·실행·검증·복구·필수 감사 기록을 목적에 맞게 보존한다. Sidebar cache와 검색 중간 후보는 제품 사실 저장과 구분한다. Activity는 기존 결과·실행 이력을 소비하며 별도 장기 업무 기억이 아니다. 보존과 credential의 허용 범위는 정책이 정한다.

## 12. Product Runtime configuration boundary

제품 화면에 평가용 Gold·Grader·후보 selector를 노출하지 않는다. Google/GitHub 연결 설정과 Gemini API credential, Local AI 준비를 구분한다. 기본 repository는 사용자 편의 설정이며 접근 권한이나 진행 중 Run의 대상을 바꾸는 권한이 아니다.

## 13. 출시 기준

안전 Gate는 승인 준수·금지 작업 차단·필수 Write Verification·승인 인자 무결성 100%, Credential 노출 0이다. 응답 유실에 따른 중복 외부 실행은 허용 오차로 보지 않는다.

기존 모델 품질 목표인 Source/Tool/argument 정확도 90% 이상, Core BTS 80% 이상을 유지한다. 중복 업무 제안·생성 5% 이하와 충돌 3% 이하라는 품질 지표는 사용자 업무 판단의 평가 지표다. 멱등성 위반, 승인 우회 또는 확인 없이 충돌을 허용하는 안전 실패를 그 비율로 상쇄하지 않는다. 평가 denominator와 scorer는 Evaluation이 소유한다.

출시 기능마다 자동 회귀, 실제 Frontend·Local 모델·Connector 경로, 실제 외부 결과, 설치본 검증을 구분해 증거를 남긴다. 미검증 필수 항목은 PENDING/BLOCKED다. 문서 수정, Run COMPLETED, 테스트 수 합계 또는 Issue 종료만으로 Release GREEN을 선언하지 않는다.

## 14. 단계별 범위

현재 폐쇄 대상은 Google 업무 READ/WRITE, GitHub Issue READ/WRITE, 의미 검색, 상태 기반 Supervisor, 승인·자연어 수정, Recovery, 연결 Settings, 누적 Activity, Local 준비, 설치 제품이다. 범위 결정과 완료 상태는 다르다.

P1에는 대화 이름 변경·삭제, 공개 OAuth 운영 승격과 추가 사용성 개선을 둔다. P2에는 첨부파일 내용 처리, 고급 일정 최적화, 별도 승인된 Provider 확장을 둔다. 공개 배포를 선택하는 경우 해당 인증·보안 Gate는 선행해야 하며 단계 이름으로 면제되지 않는다.

## 15. OAuth 사용자 경험과 배포 단계

제품 개발자가 Google Desktop OAuth Client와 GitHub App Client ID를 구성한다. 일반 사용자는 로그인·동의·GitHub Device code 인증만 수행한다. GitHub 로그인과 App 설치·repository 접근 허용은 별개로 안내한다. 개발 환경 준비 부족을 사용자에게 PAT·secret 입력으로 우회시키지 않는다. 실제 scope·protocol·token 저장과 공개 배포 요건은 보안·인프라 계약에서 관리한다.

### 15.1 요청별 Connector 사용 전제

Core readiness는 앱의 정상 실행 경계이고 Connector availability는 해당 업무에 사용할 계정·권한의 상태다. Google Credential이 없다는 이유로 startup·readiness·메인 UI·기본 요청 생성이 실패하면 안 된다. 기존 Connector/runtime/connection status 경계를 재사용하며 Google·GitHub 특수 규칙을 Core에 계속 추가하지 않는다.

요청에 필요한 Connector가 처음부터 준비되지 않았으면 필요한 연결·App 설치·repository 접근·permission 조치를 안내하고 현재 요청을 종료한다. 인증 대기용 durable Run이나 checkpoint를 유지하지 않으며, 연결 완료 후 사용자가 같은 요청을 다시 보내야 한다. 정상 실행 중 Credential이 만료된 Run은 기존 REAUTH_REQUIRED·safe resume와 in-flight 결과 처리 계약을 유지한다. 이 둘을 새 AUTH_WAITING 상태나 callback 자동 resume로 합치지 않는다.

## 16. 배포 프로필

API_ONLY는 외부 API credential과 동의를 사용하며 Ollama 준비 부작용이 없다. LOCAL_CAPABLE은 지원 GPU와 승인된 Local profile을 준비한다. 두 프로필의 업무 의미·승인·실행·검증은 같아야 한다.

## 17. Frontend · Release 경계

설치본에서 source checkout, 개발 가상환경, node_modules, 개발 서버 없이 시작·재실행·인증·대표 READ/WRITE가 가능해야 한다. 실제 제품·빌드·최종 문서의 commit을 연결해 보고한다. 설치·migration·process의 상세 절차를 PRD에 복제하지 않는다.

## 18. Google Source 탐색·목록 요구사항

사용자 선택형과 Agent 검색형을 지원한다. Focus는 상세 미리보기, 명시적 선택은 새 요청의 Context로 구분한다. 이미 받은 UI 범위는 세션에서 재사용하고 계정·범위가 달라지면 섞지 않는다. Tasks 기본 순서·Calendar Month View·count 정확성과 상세 표현은 UI·UX가 소유한다. GitHub는 설정된 repository 또는 요청에 명시한 범위에서 탐색한다. Google Sidebar와 Gmail·Tasks·Calendar 기능은 미연결일 때도 유지하며 연결 CTA를 표시한다. 미연결을 빈 자료 목록이나 제품 기능 제거로 표현하지 않는다.

## 19. Secure & Resilient 비기능 요구사항

입력·출력·동시성·DB 무결성·외부 장애·공급망 검증을 로컬 제품 규모에 맞게 적용한다. 원격 SaaS용 WAF·Kubernetes·분산 Lock을 이번 범위에 도입하지 않는다. 설계에 없는 예외를 편의상 허용하지 않는다.

## 20. Agent Workflow 제품 요구사항

상태 기반 Supervisor는 필요한 책임만 실행하고 skip·bounded back-edge·suspend·종료를 구분한다. upstream 의미가 바뀌면 stale downstream 결과를 현재 결과처럼 사용하지 않는다. 안전·실행·검증 책임은 Agent 구성이나 Connector에 따라 완화되지 않는다. 정확한 topology·schema·revision 규칙은 Workflow 계약에서 정의한다.

## 21. 구현 전제

기존 구현과 의미 통합 결과를 재사용한다. 문서 정리는 제품 코드 수정이나 보호된 기술 계약의 암묵적 변경을 포함하지 않는다. 필요한 schema 변경은 이후 구현 작업에서 producer·consumer·호환성·검증을 함께 닫아야 한다.

## 22. 승인형 Write·Clarification 계약

등록된 범위의 Draft/SEND/Reply, Task/Calendar 변경, GitHub Issue 변경을 구분한다. 확인 질문은 실제 선택이 필요한 시점에 요청한다. 원문에 없는 사람·repository·날짜를 추측해 WRITE 대상으로 확정하지 않는다. 자세한 허용·금지·Override 조건은 정책에만 정의한다.

## 23. Claim V2·Gmail 첨부파일 범위

첨부파일은 선택한 파일의 다운로드·전달만 지원하며 자동 내용 분석을 하지 않는다. 승인 당시 파일과 실제 전송 파일이 일치해야 한다. Claim wire 버전·hash·서명 항목은 이 제품 요구를 구현하는 기술 계약이며 이 문서의 수정일과 연동하지 않는다.

## 24. 문서 관계

PRD는 목표와 범위, 기능 정의는 사용자 동작, 정책은 허용 조건, UI·UX는 표현과 조작을 소유한다. 각 문서의 상세를 다른 문서에 다시 복사하지 않는다. 구현·실제품 검증 현황은 별도 작업 현황에서 관리한다.
