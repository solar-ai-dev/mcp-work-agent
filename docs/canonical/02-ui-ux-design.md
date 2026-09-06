# 02. UI · UX 설계서

> **Authority:** 사용자 화면·상호작용과 UX 상태 표현. Domain/Workflow/API semantics는 해당 전문 owner를 따른다.  
> **수정일:** 2026-09-06 · **상태:** 제품 UX 요구사항 — 구현·E2E 완료 여부는 별도 작업 현황에서 관리

## 1. 문서 목적

이 문서는 mcp-work-agent의 화면·상호작용·표시 상태를 정의한다. 연결과 설정, 자료 탐색, 채팅, 확인·승인·수정, 누적 작업 내역, 실행 결과와 복구를 사용자가 어떻게 보며 조작하는지에 집중한다.

동일 기능의 별도 설명본을 만들지 않고 이 페이지에서 개요와 상세를 함께 제공한다. Policy의 허용 규칙, Domain 전이, API field와 저장 구조를 UI가 재정의하지 않는다. 화면은 기존 Backend가 제공한 상태·허용 동작을 소비한다. 새 요구사항은 승인된 구현·계약 연결과 E2E 검증을 거쳐야 하며 문서만으로 기능 완료를 선언하지 않는다.

## 2. UX 성공 기준

### 2.1 최소 행동

- 정상적인 두 번째 이후 실행은 별도 입력 없이 자동 검사 후 메인 화면에 도달한다.
- 사용자는 기본적으로 자연어 요청 한 번으로 Context 조회와 Action Plan 생성까지 진행할 수 있다.
- 추가 정보가 필요할 때만 한 번의 선택 또는 짧은 입력을 요청한다.
- 여러 Action은 기본적으로 하나의 계획으로 묶어 승인할 수 있고, 필요한 경우에만 Action별로 펼쳐 수정·취소한다.
- 사용자가 지원되는 업무 자료를 보고 있는 위치에서 바로 Agent 행동을 시작할 수 있어야 한다.

### 2.2 화면 이동 최소화

- 승인, 수정, 취소, 재검증, 실행 결과, Recovery는 모두 중앙 채팅 안에서 처리한다.
- Gmail·Tasks·Calendar는 왼쪽 패널에서 탐색하고 현재 채팅 Context로 바로 연결한다.
- 과거 대화는 오른쪽 패널에서 열고 이어서 작업한다.
- 설정과 진단은 상단 버튼에서 Drawer 또는 Dialog로 연다.

### 2.3 자동화와 통제의 균형

- 읽기·검색·분석은 사용자 요청 범위 안에서 자동 진행한다.
- 쓰기 Action만 사용자 승인을 요구한다.
- 앱이 자동으로 판단할 수 있는 값은 먼저 제안하고, 불명확하거나 정책상 필요한 경우에만 질문한다.
- 인증 갱신, 승인 profile의 준비와 상태 점검은 시스템이 조정한다. 사용자가 정한 기본 Resource와 현재 요청의 명시 대상을 존중한다. OAuth 계정 동의, 외부 전송 동의, Secret 입력, Write 승인처럼 사용자 권한이 필요한 값만 입력받는다.
- 진행 중인 한 문장을 교체하지 않고 실제 작업 행을 누적하며, 각 행에서 필요한 상세를 펼친다. 기술 로그 전체를 그대로 노출하지 않는다.

## 3. 실행·화면 구조

### 3.1 실행 구조

```
Launcher 실행
→ Local Agent Service 시작·Health Check
→ React UI Open
→ Local Session과 API Version 확인
→ 시작 검사 또는 메인 화면
```

운영 빌드는 React 정적 파일과 Local API를 같은 `127.0.0.1` Origin에서 제공한다. 사용자는 Vite, Python, 포트 또는 API 주소를 직접 설정하지 않는다.

### 3.2 전체 화면 구조

제품의 독립 화면은 최소화한다.

1. 시작 검사 화면
2. 최초 설정 온보딩 화면
3. 메인 화면
4. 설정·진단 Drawer 또는 Dialog

Context 검토, 계획, 승인, 실행, 검증, 복구는 별도 페이지가 아니라 메인 화면의 채팅 메시지와 Inline Card로 표시한다.

## 4. 전체 사용자 흐름

Core가 정상 시작되면 업무 Connector와 Model Provider가 미연결이어도 메인 화면에 진입한다. 외부 LLM 전송 동의도 진입 조건이 아니다. 연결과 AI 준비는 해당 기능의 사용 가능 상태로 안내한다. 사용자는 자연어 요청을 하거나 탐색 중인 Resource를 명시적으로 선택한다.

이후 경로는 실제 상태에 따라 달라진다. 바로 답할 수 있으면 답변하고, 필요한 자료가 있으면 검색·확인한다. 판단에 필수인 선택만 질문하고, 외부 변경이 필요하면 계획·승인·실행·검증으로 이어진다. 모든 요청에 동일한 단계나 승인 카드를 강제하지 않는다.

Google·GitHub 어느 쪽도 앱 진입의 필수 로그인으로 표시하지 않는다. 필요한 Connector가 처음부터 미연결·미설치·접근 불가이면 현재 요청에 조치 안내를 남기고 종료한다. Settings에서 연결한 뒤 사용자가 다시 요청하도록 안내하며 실행 중 인증 만료의 재개 화면과 구분한다.

## 5. UI-001 시작 검사 화면

### 5.1 목적

앱이 사용 가능한 상태인지 자동 확인하고, 필요한 경우에만 사용자의 행동을 요청한다.

### 5.2 구성

- 앱 로고와 제품명
- 전체 진행 Bar
- 현재 검사 중인 항목을 설명하는 한 문장
- 완료·경고·실패 상태
- `자세히 보기` 접힘 영역

### 5.3 검사 순서

화면은 Backend가 제공하는 검사 상태와 필요한 다음 행동을 표시한다. Frontend가 프로세스나 credential을 직접 검사하지 않는다.

- Core Readiness: 앱/자산/API 호환성, Local Session, DB/migration, 핵심 실행 경계.
- Runtime Availability: 현재 요청에 사용할 Google/GitHub 연결·권한, Gemini API 설정/동의, Local AI 준비 상태.
- Continuation: 저장된 대화와 중단 Run의 복원 가능 상태.

전체 필수 순서는 startup owner가 결정한다. 연결 하나의 미설정을 Core 장애로 묶거나 모든 외부 서비스를 무조건 필수로 만들지 않는다.

### 5.4 상태 문장 예시

- `로컬 데이터를 확인하고 있습니다.`
- `저장된 Google 로그인을 확인하고 있습니다.`
- `Gmail·Tasks·Calendar 연결을 확인하고 있습니다.`
- `API LLM 연결을 확인하고 있습니다.`
- `Ollama와 Local 모델을 확인하고 있습니다.`
- `이전 대화를 복구하고 있습니다.`

### 5.5 이동 규칙

Core가 준비되면 메인 화면에 진입하고 저장된 이력·Settings를 사용할 수 있다. 사용할 연결이 없거나 선택 AI가 준비되지 않았으면 해당 설정 행동을 강조하되 진입 버튼을 잠그지 않는다. Local-only 사용에 외부 전송 동의를 강제하지 않는다. 새 추론 요청을 실행할 모델이 없으면 그 요청에 연결·준비 안내를 표시하고 종료한다. Google/GitHub/API/Local 문제를 각각 분리하고 다른 정상 기능까지 차단 표시하지 않는다.

명시적 Local 모드의 실패를 동의 없는 API 전환으로 숨기지 않는다. 중단 Run은 이전 작업 안내와 서버가 허용한 재개·복구 행동을 표시한다. 마지막 저장 상태를 현재 실행 성공으로 추측하지 않는다.

## 6. UI-002 최초 설정 온보딩

### 6.1 형태

여러 페이지를 넘기는 Wizard가 아니라 하나의 온보딩 화면에서 체크리스트가 순서대로 진행된다. 현재 필요한 행동 하나만 강조하고 완료된 단계는 자동으로 접는다.

### 6.2 진행 순서

업무 Connector와 Model Provider 연결은 `나중에 연결` 또는 `건너뛰고 시작`으로 미루고 메인 화면에 진입할 수 있다. 어느 연결의 미설정이나 외부 전송 미동의를 이유로 다음 단계를 잠그지 않는다. AI 방식과 개인정보 동의·준비 상태는 업무 연결과 구분해 안내한다. Local 지원 환경이면 제품이 승인된 Runtime/모델 준비를 진행하고, API 방식이면 credential과 외부 전송 동의를 구분해 받는다.

기본 Calendar·Task List·GitHub Repository는 설정에서 선택할 수 있지만 모든 값을 최초 진입의 필수 Form으로 요구하지 않는다. 실제 요청의 대상을 정할 수 없을 때 해당 선택만 요청한다.

### 6.3 Google 로그인

Google 연결 카드의 CTA는 `Google로 로그인`이며 앱 전체의 필수 다음 버튼이 아니다. `나중에 연결`을 함께 제공하고 Settings에서도 연결할 수 있다. 개발팀 Client 설정은 일반 사용자의 입력 항목이 아니다. 완료 후 실제 표시용 계정과 필요한 권한 상태를 보여준다. 필수 권한이 거절되면 Google 연결 미완료로 안내하되 무관한 GitHub 요청을 같은 오류로 처리하지 않는다. 재실행에서는 기존 연결을 검증하고 재로그인이 필요한 경우만 안내한다.

### 6.4 LLM 연결 방식 선택

- 사용자는 `API LLM | Local LLM` 중 실행 방식을 고를 수 있지만 concrete Local model은 고르지 않는다.
- API LLM은 제품에서 지원하는 Provider·고정 Model과 API Key 입력을 표시한다. API Key 기본 저장 위치는 OS Keyring이며 Secret 원문과 저장 세부는 화면 전환 후 다시 노출하지 않는다.
- Local LLM은 verified Release의 Signed Local Model Profile과 Hardware gate를 교차 검증하고 제품이 승인된 단일 Model을 준비한다.
- 선택 이후의 연결, readiness 검사, 실패 복구는 시스템이 수행하며 사용자가 endpoint·model tag·설치 명령을 입력하지 않는다.
- 기본 Calendar·Task List·Timezone은 최초 설정 완료 조건이 아니며 필요 시 Settings 또는 실제 Action 계획에서 결정한다.

### 6.5 Local AI 자동 준비

- GPU 기준을 충족한 `LOCAL_CAPABLE` 환경에서만 표시한다.
- Local LLM을 선택하면 준비를 자동 시작하며 Settings의 `로컬 AI 준비`는 중단된 준비·repair를 다시 확인하는 단일 진입점이다. 사용자가 Ollama 설치 프로그램이나 터미널 명령을 직접 다루지 않는다.
- 단계는 `환경 확인 → Ollama 준비 → 승인 모델 준비 → 무결성 검증 → 테스트 추론` 순서로 표시한다.
- 각 단계는 `대기 | 다운로드 중 | 설치 중 | 검증 중 | 완료 | 다시 시도 필요` 상태와 진행률·남은 용량을 제공한다.
- 기본 사용자 문구는 `로컬 AI 모델`을 사용하고 model ID/digest는 진단 상세에서만 노출한다.
- 네트워크 단절·앱 재시작 뒤에는 같은 operation을 reconcile하고 완료 Artifact를 다시 다운로드하지 않는다.
- Signature/hash/digest 불일치, 디스크 부족, 기존 Ollama 비호환은 정확한 조치와 `다시 시도`를 표시하며 검증 전 `LOCAL_GPU`를 활성화하지 않는다.
- 기존 호환 Ollama는 보존하고 사용한다. 제품 제거 화면은 기존 Ollama를 자동 삭제하지 않으며 제품이 받은 모델 삭제는 별도 선택으로 제공한다.
- API 사용 가능 시 provisioning 중에도 API_LLM 경로를 함께 표시한다. GPU가 없거나 기준 미달이면 Local provisioning UI와 Local 옵션을 표시하지 않는다.

### 6.6 두 번째 이후 실행

최초 설정 항목을 다시 입력받지 않는다. 시작 검사에서 Credential, API Key, Ollama, 모델, 기본 Resource를 자동 검증하고 문제가 있는 항목만 메인 화면에서 수정 요청한다.

## 7. UI-003 메인 화면

### 7.1 기본 레이아웃

```
┌──────────────────────────────────────────────────────────┐
│ 상단 Bar                                                  │
├──────────────┬────────────────────────────┬───────────────┤
│ 업무 자료    │ Agent 채팅                 │ 대화 내역     │
│ Calendar     │ 누적 작업 내역             │ Conversation 목록 │
│ Tasks        │ 메시지·Inline Action Card  │ 상태·검색     │
│ Gmail        │ 입력창·AI 모드             │               │
└──────────────┴────────────────────────────┴───────────────┘
```

### 7.2 패널 동작

- 왼쪽과 오른쪽 패널은 상단의 간단한 Icon Button으로 각각 열고 닫는다.
- 닫힌 패널은 중앙 채팅 영역을 확장한다.
- 사용자가 선택한 패널 상태와 너비는 로컬에 저장한다.
- 창 폭이 좁아지면 오른쪽 패널부터 자동으로 닫고, 왼쪽 패널은 Overlay 방식으로 연다.

## 8. UI-004 상단 Bar

### 8.1 항상 표시할 항목

- 왼쪽 Google 패널 Toggle
- 제품명 `mcp-work-agent`
- 오른쪽 대화 내역 Toggle
- 설정
- 밝은 모드·야간 모드

### 8.2 연결 상태

상세 상태를 여는 기능이 있을 때만 상태 Control을 사용하며, 열리는 화면은 다음 항목을 간단히 보여준다.

- Local Agent API
- Event Stream
- Google
- MCP
- API LLM
- Ollama
- Local 모델
- 마지막 검사 시간

Google 연결 상태와 현재 계정 이메일은 설정의 Google 영역에서 확인한다. Header에는 정상 연결 chip과 계정 이메일을 중복 표시하지 않는다. 미연결 시 연결 Action과 업무 진행을 막는 오류의 기존 복구 안내는 유지한다.

## 9. UI-005 왼쪽 Google 서비스 패널

Google 미연결이어도 Gmail·Tasks·Calendar 탐색 진입점은 유지한다. 각 영역은 `Google Workspace 연결이 필요합니다`와 Settings 연결 CTA를 표시하며 데이터 0건으로 표시하지 않는다. 연결되면 기존 목록·검색·상세 기능을 같은 경로에서 사용할 수 있다.

### 9.1 목적

Gmail·Tasks·Calendar를 확인하는 동시에 현재 항목에서 바로 Agent 행동을 시작한다.

### 9.2 공통 구성

- `Calendar`, `Tasks`, `Gmail` 탭
- 검색·필터
- 마지막 갱신 시간
- 수동 새로고침
- Gmail·Tasks는 configured `SIDEBAR_PAGE_SIZE` 단위의 Resource 목록을 사용한다. Calendar는 §30.1 Month View contract를 따른다.
- Gmail·Tasks는 이전·다음 목록 페이지 이동, Calendar는 이전·다음 월 이동
- 단일 선택과 다중 선택
- 원본 서비스에서 열기 또는 찾기 — 실제 동작은 Provider capability에 따르며 direct Thread permalink를 보장하지 않는다. Gmail P0는 `Gmail에서 찾기`이며 원본 Thread를 직접 열지 않고 Gmail 검색 결과 화면으로 이동한다.
- 현재 채팅 Context로 추가
- 선택된 항목에서 Agent 요청 시작

### 9.3 행동 안에서 행동

각 Resource Card는 단순 조회에서 끝나지 않고 해당 항목을 기준으로 Agent 요청을 시작할 수 있어야 한다.

#### Gmail Card Action

- `이 메일 정리`
- `해야 할 일 찾기`
- `답장 Draft 제안`
- `채팅에 추가`

#### Task Card Action

- `일정 제안`
- `관련 메일 찾기`
- `관련 마감 확인`
- `채팅에 추가`

#### Calendar Card Action

- `회의 준비`
- `후속 업무 찾기`
- `관련 메일 찾기`
- `채팅에 추가`

이 Action들은 즉시 Google 쓰기를 수행하지 않는다. 선택한 Resource와 의도를 중앙 채팅에 전달해 Agent 분석을 시작하며, 쓰기 결과는 채팅 안에서 승인받는다.

### 9.4 목록 조회와 Pagination

- Tasks Sidebar는 기존 Task List 조회 API의 목록 선택·새로고침·추가 페이지 조회를 제공한다. 기본 조회는 설정된 목록(미설정 시 Provider 첫 목록)이며, 다른 목록을 선택하면 그 목록의 미래 예정일을 포함한 미완료 Task를 조회한다. Browse 선택은 생성용 기본 Task List 설정을 변경하지 않는다. 계정·목록 전환 시 완료 항목과 preload까지 이전 조회 상태를 폐기한다.
- Gmail·Tasks Sidebar의 visible page size는 configured `SIDEBAR_PAGE_SIZE`이며 Agent Retrieval의 configured `RETRIEVAL_PAGE_SIZE`와는 별도 계약이다. Local API continuation은 opaque 값으로 취급하고 Frontend가 Provider token이나 page number로 해석하지 않는다.
- Gmail은 아직 방문하지 않은 intermediate page에서 metadata hydration을 생략해 다음 continuation만 확보하고 visible target page만 metadata를 hydrate한다. token-known과 metadata-loaded 상태를 React Client Session Cache에서 구분하며 이미 받은 page 재방문은 API를 호출하지 않는다.
- Tasks는 Provider가 허용하는 metadata batch를 받고 UI에서 configured `SIDEBAR_PAGE_SIZE`로 slice한다. continuation이 있으면 현재 materialized batch에서 계산되는 page 범위만 표시하고 알려진 마지막 page에서만 다음 batch를 가져온다. terminal batch 뒤 누적 수로 exact total과 마지막 page를 확정한다.
- Calendar Sidebar의 exact visible-grid materialization·date interaction·pagination prohibition은 §30.1이 단일 UI authority다.
- Sidebar 최초 진입에서는 Gmail exact count와 Tasks incomplete 첫 batch를 독립적으로 준비한다. 최초 preload UI는 둘이 success/failure로 모두 settle된 뒤 성공한 count만 함께 노출하며 실패·미확정 Source를 `0`으로 표시하지 않는다. Calendar count는 startup preload하지 않고 Calendar tab에는 numeric badge를 표시하지 않는다.
- Gmail 검색 변경은 Browse cache만 바꾸고 기본 `INBOX + PRIMARY` badge count를 유지한다. 수동 Refresh·계정·container·scope·검색/filter/sort 변경은 관련 Session Cache를 무효화한다.

### 9.5 Source별 기본 정렬

- Gmail: 최근 수신 Thread부터 표시한다.
- Tasks: configured/default Task List의 미완료 Task를 Google Tasks Provider 반환 순으로 표시한다. 정렬 옵션은 `기본 순서`와 `날짜순`만 제공하며, 날짜순을 명시한 경우에만 전체 결과를 materialize해 `scheduled_date` 오름차순·날짜 없는 Task 후순위로 정렬한다.
- Calendar의 Sidebar Month View와 별도 generic Upcoming Browse 범위는 §30.1이 단일 UI authority다.
- 과거 Calendar 조회에서는 사용자가 지정한 기간을 우선한다.

### 9.6 React Client Session Cache

- Cache identity는 Google 계정, Source/container, 검색·필터·정렬·scope와 opaque continuation/batch generation으로 구성한다.
- 목록 Metadata, opaque Local API continuation과 Calendar Month cache는 React Client Session Cache에만 유지한다. Provider raw continuation을 저장·해석하지 않는다.
- UI 세션 종료, Google 계정 변경, 해당 Source 수동 새로고침 시 관련 Cache를 삭제한다.
- 사이드바 목록과 사용되지 않은 검색 결과를 SQLite에 영구 저장하지 않는다.
- 수동 새로고침을 누르면 해당 Source Cache를 비우고 첫 페이지를 최신 데이터로 다시 조회한다.

### 9.7 Resource 선택

- 사용자는 하나 또는 여러 개의 Gmail·Task·Event를 선택할 수 있다.
- 한 개를 클릭하면 Preview와 해당 Resource에서 수행할 수 있는 빠른 Agent Action을 표시한다.
- Row click은 Focus Resource와 Preview만 갱신하고, checkbox는 별도의 다중 선택 Context 집합만 변경한다. Focus 변경은 기존 선택 집합을 변경하지 않는다.
- 선택 Resource가 하나 이상이면 Composer 가까이에 선택 수와 사용자 의미 label을 compact하게 표시한다. 별도의 `선택 항목으로 요청`, `채팅에 추가`, `선택 해제` Action Bar는 표시하지 않는다.
- Resource List 응답의 각 Row는 Server가 발급한 opaque `selection_handle`을 가진다. Composer 전송은 선택 집합이 있으면 중복 없는 `selection_handle` 전체를 `RESOURCE_SELECTED` Context로 전달하고, 선택 집합이 없으면 `AGENT_SEARCH`로 시작한다. Browser는 `connector_id`, `resource_type`, parent/container, version token을 만들어 보내지 않는다.
- 선택된 Resource의 ID, Source, 제목과 최소 Metadata는 화면 표시용이며, Run Context identity 전달 권위는 `selection_handle` 하나다.
- 사용자가 이미 선택한 사람·날짜·제목을 채팅에서 다시 입력하도록 요구하지 않는다.

### 9.8 두 가지 Agent 진입 방식

#### 사용자 선택형

사이드바에서 선택한 Resource의 최신 상세를 조회해 초기 Context로 사용한다. 관련 Source 검색은 사용자의 요청을 수행하는 데 필요한 경우에만 확장한다.

#### Agent 검색형

사용자가 Query, 날짜·기간, 사람·이메일, Keyword 또는 복합 요구사항을 채팅에 입력하면 Agent가 Source와 검색 조건을 구조화하고 Google Source-native 검색을 수행한다. 목록 후보를 축소한 뒤 필요한 후보만 상세 조회한다.

## 10. UI-006 중앙 Agent 채팅

### 10.1 역할

사용자 요청, Agent 진행 상태, Context, 확인 질문, 계획, 승인, 수정, 실행, 검증, 복구를 하나의 연속된 대화로 처리한다.

### 10.2 채팅 Header

- 대화 제목
- 현재 선택 AI 방식의 사용자용 표시
- 새 대화

계정 이메일·정상 연결 chip은 Settings에 둔다. 실제 model/runtime 기술 정보는 진단 상세에 두고, 실행 방식이 바뀌거나 사용자 조치가 필요한 경우만 채팅에 알린다.

### 10.3 AI 모드 설정

입력창 가까이에 Compact Selector로 표시한다.

- API_ONLY 환경: `API_LLM`만 표시
- LOCAL_CAPABLE 환경: `AUTO`, `LOCAL_GPU`, `API_LLM`
- Active Run 중에는 모드 변경을 잠근다.
- AUTO가 API로 전환되면 전환 이유를 채팅 상태 문장으로 표시한다.

### 10.4 입력창

- 자연어 입력
- 전송
- 현재 첨부된 Gmail·Task·Event 수
- 실행 중일 때 중단
- Enter 전송, Shift+Enter 줄바꿈
- 기본 상태는 1줄 높이의 compact 입력창이며 입력 내용에 따라 높이가 자동으로 늘어난다. 최대 높이에 도달하면 Composer 전체가 계속 커지지 않고 입력창 내부 scroll로 전환한다. 전송 후 입력값이 비워지면 다시 1줄 높이로 돌아온다.
- 전송 Button은 입력창과 같은 행에 위치하며 Composer는 Center 하단에서 항상 접근 가능하다.
- 하나의 대화에서 동시에 하나의 Active Run만 허용

같은 Conversation에는 여러 번의 USER 요청과 그에 대응하는 여러 Run이 순차적으로 존재할 수 있다. 이전 Run이 종료되면 사용자는 같은 Conversation에서 후속 요청뿐 아니라 이전 요청과 업무적으로 무관한 새 요청도 이어서 입력할 수 있다. Frontend는 새 요청의 업무 관련성을 판단해 새 대화를 강제하거나 자동으로 유도하지 않는다. 대화 맥락을 의도적으로 분리하고 싶을 때는 사용자가 직접 `+ 새 대화`를 선택한다.

다만 P0의 Conversation 이력은 **표시·탐색용 이력**이며 Agent의 암묵적 장기 Memory가 아니다. 새 요청 전송 시 Frontend는 현재 Composer 입력과 이번 Run에 사용자가 명시적으로 선택한 Resource만 StartRun 입력으로 제출하고, 과거 Message 전체나 이전 Run Artifact를 숨은 Context로 덧붙이지 않는다. 이전 요청을 알아야만 의미가 성립하는 표현은 명시적 Resource 선택 또는 Agent 확인 질문으로 해결한다.

## 11. 진행 상태 UX

### 11.1 Agent 실행과 하위 작업 사실

Activity는 Agent 실행별 상위 행과 해당 실행에서 발생한 작업 사실 목록으로 구성한다. 실행 중 의미 있는 결과가 생기면 하위 문장을 추가한다. 마지막 State의 필드 목록이나 한 줄 progress를 교체하는 방식으로 끝내지 않는다.

상위 행은 `요청 이해 에이전트 — 요청을 분석했습니다.`처럼 책임과 실제 상태를 표시한다. 실행 중에는 진행형, 완료 확인 뒤에는 완료형을 사용한다. 하위에는 실제로 무엇을 이해·찾기·작성·검증·복구했는지 짧은 문장으로 표시한다.

같은 실행의 상태 갱신은 상위 행을 갱신하고, 서로 다른 작업 사실은 누적한다. 동일 사실의 재전달은 중복 표시하지 않는다. 새 back-edge는 새 실행 회차로 표시하며 동일 실행의 질문·재인증·재개와 구분한다. 다음 Agent가 시작되거나 부모가 완료돼도 이전 하위 기록은 남는다. 실행되지 않은 단계와 가짜 진행률은 만들지 않는다.

### 11.2 사용자가 펼쳐 보는 내용

```text
✓ 요청 이해 에이전트 — 회의 후속 업무 요청으로 이해했습니다.
  관련 메일에서 해야 할 일을 찾아달라는 목표를 확인했습니다.
  찾을 사람을 ‘김대리’로 정리했습니다. 정확한 인물은 확인 중입니다.

✓ 자료 경로 선택 — 필요한 조회 기능을 선택했습니다.
  관련 Gmail을 조회하기로 했습니다.
  Task 생성 전에 기존 미완료 작업을 확인하기로 했습니다.

✓ 자료 검색 에이전트 — 관련 근거를 확인했습니다.
  발신자 정보에서 요청한 인물의 확인 근거를 찾았습니다.
  회의 일정이 변경된 최신 메일을 확인했습니다.
  이전 제안이 아닌 변경된 내용을 근거로 선택했습니다.

✓ 계획 생성 에이전트 — Task 생성안을 작성했습니다.
  제목을 ‘회의 후속자료 정리’로 작성했습니다.
  생성안의 필수 필드와 출력 형식 검증을 통과했습니다.

✓ 검토 에이전트 — 생성안과 근거를 대조했습니다.
  생성안에 사용한 업무 내용이 선택 근거와 일치함을 확인했습니다.
  검토 결과 사용자 승인 단계로 넘겼습니다.
```

위 문장·이름·업무는 화면 형식의 예시이며 고정 답안이 아니다. 실제 해당 결과가 발생했을 때만 해당 실행의 값을 표시한다. 자료 경로 선택의 예정 행동과 실제 완료한 조회를 구분한다. 아직 선택하지 않은 Tool이나 미해결 인물을 확정한 것으로 표시하지 않는다.

업무 분석은 실제 최신 결정·담당·관계·중복/충돌·부족 정보를, Planning은 실제 Task/Event/Mail/Issue의 핵심 업무 값을 보여준다. 실행·Verification·Recovery는 승인 대상, 실제 효과, 재조회 결과, 불확실성 및 후속 처리의 차이를 표시한다. 내부 상태 이름을 그대로 노출하는 대신 그 값과 행위의 의미를 표현한다.

`출력 형식을 검증했습니다`, `업무 내용과 근거를 대조했습니다`, `실제 생성 결과를 다시 확인했습니다`는 각각 schema 검사, 의미 대조, Provider 재조회의 다른 사실이다. 실제 검사 결과 또는 보장된 검증 성공 경계가 있을 때만 검증 완료라고 쓴다. 단순 Node 종료나 값 존재를 그 근거로 사용하지 않는다. checkpoint 복원도 외부 효과 복구 완료와 구분한다.

revision·checkpoint metadata·관계/사실/반환 수를 기본 상세의 중심으로 표시하지 않는다. 수량은 필요한 보조 정보로만 사용한다. 불필요한 빈 값과 0 항목은 생략하지만 정상 검색 0건, 실제 실패·미확인 상태까지 숨기지는 않는다.

‘이 실행 시점의 기록이며 현재 계획과 다를 수 있습니다’ 같은 문구를 모든 행에 반복하지 않는다. 실제로 대체된 결과만 `수정 전 계획`처럼 짧게 구분한다. 이후의 최신 Plan·Evidence를 과거 행에 소급 표시하지 않는다.

### 11.3 상태 기반 표시와 상호작용

문장은 기존 typed State/result, 검사 결과, committed Domain fact를 결정적으로 선택·형식화한다. 실행 당시 결과와 출처를 대조할 수 있어야 하며, Agent 종료 후 전체 State로 있었을 법한 중간 작업과 순서를 만들어내지 않는다. 모든 함수 호출·State key 변경을 사용자 작업 행으로 늘리지 않는다.

추가 LLM 호출·새 Prompt·요약 Agent는 없다. raw Prompt/Completion·hidden reasoning·전체 Provider payload·secret을 기록·노출하지 않는다. 행 클릭·펼침·복원 때문에 외부 Tool을 다시 호출하지 않는다. 저장된 기록의 Local API 조회는 가능하다. Activity 실패 때문에 업무 명령·Write가 재실행되지 않아야 한다.

진행 중인 Agent는 하위 작업 내역이 추가되는 모습을 볼 수 있게 기본 펼침으로 제공하고 사용자가 접을 수 있다. 완료된 행도 접기·펼치기가 가능하며 사용자가 선택한 상태를 후속 이벤트나 다음 Agent 시작이 임의 초기화하지 않는다. 현재 작업·사용자 대기를 강조하고 과거 완료 행은 덜 강조한다. 키보드 조작과 focus를 지원하며 상세를 읽는 중 자동 scroll로 위치를 빼앗지 않는다.

### 11.4 Conversation의 여러 Run과 복원

같은 Conversation에서 새 요청이 시작돼도 이전 Run의 Agent 행과 하위 작업 사실은 해당 메시지 사이에 남는다.

```text
사용자 요청 A
  Run A의 Agent 행과 하위 작업 내역
최종 답변 A

사용자 요청 B
  Run B의 Agent 행과 하위 작업 내역
최종 답변 B
```

현재 runSnapshot 하나를 바꿔 끼우며 과거 Activity를 숨기지 않는다. 과거 Run은 읽기 전용으로 표시하고 이전 승인·복구 조작을 다시 활성화하지 않는다. 새 Conversation과 이전 Conversation의 기록을 섞지 않는다. 과거 기록을 표시하는 것은 새 요청의 Prompt에 숨은 기억을 전달하는 것과 다르다.

SSE는 실시간 갱신 수단이며 단독 이력 저장소가 아니다. 새로고침·재접속·앱/서버 재실행·다른 대화 이동 후 복귀에서는 기존 저장 이력과 결과·Snapshot으로 각 Run을 복원한다. 최신 phase만으로 과거 실행을 추측하지 않는다. 중복·역순·replay 및 Snapshot/SSE 전환에도 Run·실행 회차별 상위 행과 하위 사실이 중복되거나 과거 상태로 되돌아가지 않아야 한다.

보존은 기존 retention 범위 안에서 제공한다. 긴 이력은 bounded 조회·접기·스크롤·필요한 Local 상세 조회로 제공하고 최근 N행만 남긴 사실을 숨기지 않는다. 기록되지 않았거나 보존 만료된 이력은 한계를 표시하고 새 설명으로 복원하지 않는다.

## 11-A. Local API와 Event Stream UX

### Command 처리

- 사용자 입력, 승인, 수정, 거절, 취소는 REST Command로 제출한다.
- Command 제출 중 Button을 잠그되 UI 잠금만으로 중복 실행을 보장하지 않는다.
- 성공 응답에는 현재 Aggregate Version과 상태를 반영한다.
- Timeout 발생 시 같은 Write를 추정 재실행하지 않고 Run·Action Snapshot을 조회한다.

### SSE 연결

- Run 시작 시 해당 Run Event Stream을 구독한다.
- 연결 상태는 정상일 때 숨기고 재연결 중일 때만 작은 상태 문구로 표시한다.
- 연결이 끊겨도 실행 실패로 표시하지 않는다.
- 마지막 Event Cursor 이후 재구독하고 불가능하면 현재 Snapshot을 다시 조회한다.
- Event 순서가 뒤바뀌거나 중복되면 Event Cursor와 Aggregate Version으로 오래된 화면 갱신을 무시한다.

### Service 장애

Local Agent Service가 응답하지 않으면 화면 전체를 초기화하지 않고 다음을 제공한다.

- 연결 다시 시도
- Launcher 상태 확인
- 진단 정보 보기
- 마지막 저장 상태 표시
- 시스템 재연결·복구 진행 상태

## 12. UI-007 오른쪽 대화 내역 패널

### 12.1 목적

현재 메시지를 반복 표시하는 영역이 아니라 저장된 `Conversation`을 탐색하고 이어서 작업하는 영역이다.

### 12.2 구성

- 새 대화
- 대화 검색
- 오늘·어제·최근 7일·이전 분류
- 실행 중
- 승인 대기
- 실패
- 완료

### 12.3 대화 항목

- 자동 생성 대화 제목
- 마지막 활동 시각
- 현재 상태
- Action 수 또는 실패 수
- 이름 변경 (P1, 27절 참고)
- 삭제 (P1, 27절 참고)

`Conversation.title`은 최초 USER 요청을 기반으로 대화 생성 시 한 번 생성되는 안정적인 식별 제목이다. 같은 Conversation에 후속 요청이나 업무적으로 무관한 새 요청이 여러 Run으로 추가되어도 title을 자동 재생성하거나 최신 USER 메시지로 덮어쓰지 않는다. "마지막 활동 시각"은 `Conversation.updated_at_ms`이며 개별 Message 내용과는 다른 값이다. 최근 USER 메시지 preview 표시는 P0 요구사항이 아니다.

대화를 선택하면 중앙 채팅에는 해당 Conversation의 저장된 Message·Run Timeline을 복원한다. 비Terminal Open Run이 있으면 그 Run의 `langgraph_thread_id`와 Checkpoint를 복원해 이어갈 수 있지만, Terminal인 과거 Run의 `langgraph_thread_id`/Checkpoint를 새 USER 요청에 재사용하지 않는다. 새 USER 요청은 새 Run·새 `langgraph_thread_id`로 시작하며 과거 승인도 다시 실행에 사용하지 않는다.

## 13. 채팅 내부 UI 유형

중앙 Conversation은 사용자 메시지, 최종 Assistant 답변, Run별 누적 Activity, Context, 확인 질문, Plan/Approval, 수정, 실행·검증·오류/Recovery Card를 같은 흐름에서 표시한다. 별도 설명용 메시지를 반복 INSERT하여 Activity 이력을 만들지 않는다.

### 13.1 사용자 메시지와 Timeline 표시

사용자 메시지는 우측 Bubble로 표시하고 역할 이름을 반복하지 않는다. 저장된 메시지 시각을 사용자 timezone으로 변환하며 현재 시각으로 대체하지 않는다.

Local Calendar Date가 달라질 때만 날짜 구분선을 둔다. 오늘·어제·올해의 다른 날짜·다른 연도를 구분한다. 오래된 대화를 다시 사용해도 과거 날짜 그룹을 유지한다.

대화 복원 시 최신 메시지를 기본 위치로 표시하되, 과거 Activity의 상세를 읽는 중에 새 progress 이벤트마다 화면을 강제로 끌어내리지 않는다. 새 USER 전송 시 최신 흐름을 보여준다. 결정이 끝난 Card의 이전 버튼은 비활성화한다.

## 14. Context 요약과 확인 질문

### 14.1 Context 요약

기본 표시는 실제 Source별 사용 근거 수와 핵심 발췌다. Gmail·Tasks·Calendar·GitHub를 구별하고, 조회 후보 전체 수와 사용 Evidence 수를 같은 숫자로 표현하지 않는다. 원문 전체를 기본 노출하지 않고 필요하면 해당 서비스에서 여는 안전한 링크를 제공한다.

Context 조정은 서버가 허용한 경우에만 `일부 제외` 또는 `추가 검색`으로 표시한다. 현재 Preview에 있는 근거만 제외할 수 있고 새 정보 요청은 현재 Run의 허용된 범위로 전달한다. Frontend가 Approval/Plan 상태를 보고 자체적으로 조정 권한을 만들지 않는다. 수정 후 재계산 상태와 새 Preview를 보여주며 승인·실행 이후의 임의 조정은 제공하지 않는다.

### 14.2 확인 질문

검색으로 해소할 수 있는 모호성은 일반 조회를 먼저 진행한다. 유효 후보가 여러 개 남거나 현재 요청을 안전하게 결정할 수 없을 때 한 번에 필요한 최소 선택을 받는다.

사람·기간·관련 Resource·저장소 충돌·외부 수신자·duplicate/conflict override를 그 이유에 맞게 표현한다. 후보에는 제공된 이름·소속·관련 업무 등 차이를 표시하고 없는 정보를 만들지 않는다. 사용자가 이미 준 날짜·시간·대상을 다시 입력하게 하지 않는다. 응답 후 같은 Run에서 이어지며 이전 Activity는 남는다.

## 15. Action Plan과 승인 UX

### 15.1 계획 요약

여러 Action은 기본적으로 하나의 Plan Card에 묶는다.

```
3개의 작업을 제안합니다.
- Task 생성 1개
- Calendar Event 생성 1개
- Gmail Draft 생성 1개

[승인하고 실행] [내용 수정] [건너뛰기]
```

### 15.2 상세 펼치기

기본 Card에는 대상 서비스·작업 종류와 사용자가 승인해야 할 핵심 값을 보여주고, 근거·변경 전후·위험·종속 관계는 필요한 상세로 펼친다. 알려진 필드 Form을 기본으로 전부 노출하지 않는다.

Task 생성 Preview는 제목, 실제 Task List, **예정일**, 메모, 필요한 근거·경고와 `만들기 / 수정 / 건너뛰기`로 구성한다. 미지정 예정일이나 메모는 ‘없음/미지정’처럼 명확히 표시하고 가짜 기본값을 만들지 않는다. 완료된 Task로 오해할 문구를 사용하지 않는다.

Calendar는 시작/종료·timezone·참석자, Gmail은 실제 수신 범위·제목·본문·Reply 대상, GitHub는 owner/repository와 Issue 대상·변경 내용을 분명히 보여준다. 서비스별로 승인에 중요한 필드를 일반 formatter에서 지워버리지 않는다.

### 15.3 승인

- 승인 시 Card 상태를 `승인됨`으로 고정한다.
- 실행 전 Approval Hash, 현재 Resource, Policy를 다시 검증한다.
- 검증을 통과하면 같은 Card 아래에서 실행 상태를 표시한다.
- 승인 Button은 재클릭할 수 없다.

### 15.4 건너뛰기 · Action 거절

- Action-level `[건너뛰기]`는 `POST /api/v1/actions/{action_id}/reject`의 `RejectAction` 의미 하나만 사용한다.
- 거절한 Action은 `REJECTED`로 닫혀 외부 Write로 실행하지 않으며, 종속 Action이 `DEPENDENCY_BLOCKED` 되는 경우 영향 범위를 바로 표시한다.
- 이 Control은 `CancelPendingAction`이나 `/runs/{run_id}/cancel`을 호출하지 않는다. **Run 전체 중단**은 별도의 Run cancel Control만 사용한다.
- `거절됨` 응답은 같은 Card에 기록한다.

### 15.5 수정

Task는 자연어 수정을 우선한다. `예정일을 9월 8일로 바꾸고 메모는 빼줘`처럼 입력하면 기존 Backend modify·Planning/Review 경로의 처리 상태를 보여주고, 결과를 새 compact Preview로 제시하여 재승인받는다.

언급하지 않은 값의 유지와 명시적 제거를 구분한다. 수정 전·후 값을 비교할 수 있어야 하며, 수정 실패 시 기존 유효 Preview를 성공 수정처럼 덮어쓰지 않는다. 이전 revision의 승인 버튼은 재사용하지 않는다.

정밀 직접 편집은 `직접 편집` 같은 secondary control로 제공할 수 있다. Gmail·Calendar·GitHub는 현재 계약이 허용하는 필드만 편집한다. Frontend가 자연어를 해석해 업무 patch를 독립 생성하거나 별도 승인 경로를 만들지 않는다.

## 16. 실행과 검증 UX

### 16.1 실행 상태

실제 상태에 따라 대기, 승인됨, 실행 중, 실행 결과 수신/검증 대기, 검증 중, 검증 완료, 실패, 차단, 결과 불확실, 검증 불일치를 구별한다. Provider 요청을 보냈다는 사실을 검증된 완료로 표시하지 않는다. 여러 Action은 각각의 결과를 유지한다.

### 16.2 부분 성공

이미 성공한 외부 결과, 실패·미확인 결과, 종속 차단, 사용자가 거절한 항목을 구분한다. READ의 예산 소진은 ‘확인한 범위까지만 정리했습니다’, 일부 조회 실패는 ‘확인하지 못한 자료가 있습니다’처럼 원인에 맞게 표시한다. 모든 PARTIAL을 ‘나머지는 취소되었습니다’로 고정하지 않는다.

### 16.3 검증 성공

해당 Connector에서 재조회한 값이 승인 내용과 일치하면 핵심 필드와 원본 Resource 링크를 표시한다.

### 16.4 검증 불일치

승인한 값과 실제 값의 차이를 보여주고, 기존 Recovery projection이 허용한 행동만 렌더링한다. `수정 제안 만들기`는 새 계획 작성, `현재 결과 유지`는 추가 Write 없는 부분 수용, `원본 서비스에서 열기`는 탐색이라는 서로 다른 의미다. 단순 화면 닫기를 복구 결정으로 기록하지 않는다.

자동 수정·재실행은 하지 않는다. 허용된 복구 선택·취소·재확인의 상세 상태 전이는 Backend 계약을 따른다.

## 17. 중단·오류·Recovery UX

### 17.1 분석 중 중단

중단 요청의 수락과 실제 종료를 구분한다. 외부 변경이 아직 없다고 확인된 경우에만 변경 없음으로 표시하며, 중단 전 Activity와 확보된 결과를 보존 정책 안에서 유지한다.

### 17.2 쓰기 실행 중 중단

이미 외부 서비스에 전달된 요청이 있을 수 있으므로 즉시 취소 완료로 표시하지 않는다.

```
중단 요청을 받았습니다.
현재 실행 중인 작업의 실제 결과를 확인하고 있습니다.
```

재조회 후 실제 성공·실패·미실행 상태를 확정한다.

### 17.3 오류 Card

원인, 현재까지 확인·완료한 것, 실제 데이터 변경 여부, 필요한 다음 행동을 함께 표시한다. 서버가 제공한 error/recovery action만 사용한다.

- 재시도 가능으로 확정된 실패만 해당 준비/재승인 경로를 제공한다.
- 결과 불확실에는 blind retry 버튼 대신 결과 확인·복구 안내를 제공한다.
- Google와 GitHub 재인증은 실제로 필요한 Connector로 연결한다.
- 안전 재개·Settings·Diagnostics는 각 action 의미를 구분한다.

인증 성공과 특정 Run 재개는 다른 상태다. 연결 완료만으로 다른 대화의 Run을 자동 재개한 것처럼 표시하지 않는다. raw reason code·SQL·stack trace를 일반 본문으로 노출하지 않는다.

### 요청 시작 시 연결·접근 불가

처음부터 필요한 Connector가 미연결이거나 GitHub App 미설치·repository 접근 불가·필수 permission 부족이면 현재 요청을 종료하고 필요한 조치를 안내한다. 진행 spinner·승인 카드·재인증 대기 Run·`이 작업 재개` 버튼을 남기지 않는다.

Google 예: `메일을 확인하려면 Google Workspace 연결이 필요합니다. 설정에서 연결한 뒤 요청을 다시 보내 주세요.`

GitHub 예: `이 저장소의 Issue를 확인하려면 GitHub 연결과 저장소 접근 설정이 필요합니다. 설정 후 요청을 다시 보내 주세요.`

`설정 열기`로 필요한 연결 영역에 안내한다. 요청 입력 보조가 있더라도 재전송은 사용자의 명시적인 행동으로 새 Run을 시작한다. 연결 완료 직후 기존 요청을 자동 전송하지 않는다.

### 실행 중 인증 만료

이미 정상 실행 중이던 Run의 Credential이 만료된 경우에는 기존 재인증·안전 재개 UI를 유지한다. 이전 작업 이력·실행 사실을 보존하고 재인증 완료 후 해당 Run의 명시적 재개를 제공한다. 초기 미연결 안내와 같은 화면·문구로 혼동하지 않는다. in-flight 결과가 있으면 기존 Recovery 표시를 우선한다.

## 18. UI-008 설정·진단 Drawer

2026-09-06 제품 변경: 기존 Drawer 안에 계정 및 연결 / AI / 일반 탭을 둔다. 캘린더·할일 목록·GitHub 저장소는 단일 기본값이 아니라 앱에서 사용할 접근 가능 항목을 다중 선택한다. 빈 선택은 해당 종류의 자료를 사용하지 않는다는 뜻이다. 외부 권한을 변경하지 않는다. 목록 로딩/빈 결과/실패를 구분하고 선택 저장 후 재진입·새로고침에도 복원한다. 아래의 단일 기본값 설명은 이전 데이터 호환에만 해당한다.

Local AI는 `qwen3.5:9b`, `qwen3.5:4b`를 검사하고 준비된 모델 하나를 선택한다. 두 모델 동시 설치를 요구하지 않고 설치 안내/다운로드 CTA를 제공하지 않는다. 배포 manifest/digest 검증은 유지한다. 시간대는 한국 `Asia/Seoul`로 고정하며 업무 시간·AI 동의는 작은 설정 행/체크박스로 제공한다. 진단은 접힌 보조 영역이다.

설정은 메인 화면에서 Drawer/Dialog로 연다. 사용자는 한 설정 진입점에서 Google Workspace·GitHub·Gemini API의 상태와 해당 관리 동작에 접근한다. 같은 설정의 서로 다른 화면에서 값이나 상태가 모순되지 않아야 한다.

### 18.1 일반

Theme과 시작 시 패널 선호 등 기존 표시 설정을 유지한다. 화면의 일시적 펼침/탭 상태와 저장된 사용자 기본값을 구분한다. 별도 persisted language 설정은 P0에서 추가하지 않는다.

### 18.2 Google Workspace

미연결이면 Google 연결 CTA를 제공하되 메인 화면을 잠그지 않는다. 연결 시 현재 표시용 계정, 필요한 권한 상태, 재연결·계정 변경·연결 해제를 제공한다. 기본 Calendar와 Task List는 실제 반환된 container에서 선택하며, 항목이 비어 있는 container도 정상 목록으로 보여준다. 계정 ID를 이메일처럼 표시하지 않는다.

### 18.3 GitHub

연결 전에는 `GitHub 연결`과 Issue 조회·관리 용도를 설명한다. Device Flow 시작 후에는 GitHub가 반환한 실제 user code, `코드 복사`, `인증 페이지 열기`, 대기·거절·만료·재시도를 표시한다. 앱에서 인증 코드를 임의 생성하지 않는다.

Client ID는 제품 구성이다. 일반 사용자 Settings에 Client ID·PAT·client secret 입력을 추가하지 않는다. 제품 설정 누락과 사용자 인증 실패를 구분해 안내한다.

연결 후에는 표시용 GitHub 계정, App/권한 상태, 접근 가능한 owner/repository 목록, 목록 새로고침, 기본 Repository 0/1개 선택·변경·해제, `저장소 접근 관리`를 제공한다. 접근 관리는 GitHub의 해당 App 설치/접근 화면으로 이동하는 안내이며 앱 안의 선택만으로 GitHub 권한을 바꾼다고 표시하지 않는다.

목록 로딩, 정상 빈 목록, 접근 실패를 구분한다. 권한 변경 후 다시 조회할 수 있어야 한다. 기본값 저장은 Settings 재진입·새로고침·재실행 후 복원하며 계정 변경이나 접근 상실 시 유효성을 다시 확인하도록 안내한다.

기본값과 현재 요청의 명시 저장소를 구분하고, selected Issue와 명시 저장소가 충돌하면 어느 쪽을 의미하는지 확인한다. 저장된 기본값으로 그 충돌을 조용히 덮지 않는다. 설정 변경이 진행 중인 Run의 대상을 바꿨다고 표시하지 않는다.

### 18.4 Gemini API

Google Workspace 로그인과 구분되는 외부 AI credential 영역이다. 기존 provider-neutral 계약의 Gemini 설정을 표시하며 별도 credential authority를 만들지 않는다.

설정 상태, API Key 입력·변경·삭제, Keyring/세션 전용 저장 선택, 연결 테스트를 제공한다. 저장된 Key 원문은 다시 표시하지 않는다. 연결 테스트는 최소 진단이며 업무 원문을 임의 전송하지 않는다.

API Key 설정과 외부 업무 Context 전송 동의는 별개 control이다. 외부 AI를 사용하는 Run에는 Backend가 제공한 전송 범위를 보여주고, scope 갱신에 맞춰 표시한다. 매 호출마다 새로운 UI ACK를 요구하지 않는다.

### 18.5 로컬 AI와 업무 기본값

로컬 AI는 Google/GitHub/Gemini 연결 카드와 별도 영역으로 둔다. 선택 AI 방식, Ollama/승인 모델 준비 상태, 준비·재시도·진단을 표시한다. 현재 제품의 기본 Local 방향은 qwen3.5:9b이며 실제 활성 여부는 검증된 runtime 상태로 표시한다.

Timezone·업무 시간·주말·Buffer와 Google 기본 container, GitHub 기본 repository는 기존 설정 경로로 저장한다. Frontend에 별도 Calendar/Repository 판단 표를 만들지 않는다.

### 18.6 데이터·진단·복구

채팅/terminal Run 보존 기간은 기존 허용 범위를 사용하며 기본30일·선택1~30일이다. Audit90일·secret·session cache에 같은 값을 일괄 적용하지 않는다. P0 Settings에 임의 전체 초기화·raw DB 조작 기능을 추가하지 않는다.

Safe Mode의 실제 자동 복구 결과와 가능한 조치만 표시한다. 사용자 raw path 입력, 데이터 삭제·새 DB 생성으로 실패를 숨기지 않는다. 기존 복구 방식·backup 선정·rollback 알고리즘을 UI가 소유하지 않는다.

Diagnostics는 로그인된 Local API의 제한된 상태를 사용한다. Local Session과 API 호환성이 성립하기 전에는 일반 mutation을 활성화하지 않는다. 정확한 transport endpoint와 secret 저장 구현은 Interface/보안 owner가 소유한다.

## 19. 상태 소유권과 저장

React는 펼침·입력·focus·표시용 cache를 소유한다. 업무 상태·승인·실행·검증 사실은 Backend에서 받고, Graph 재개 위치와 Domain 실행 사실을 혼동하지 않는다.

Activity는 기존 저장된 실행 이력·결과의 표시다. Frontend-only 배열이나 최신 상태 하나를 완전한 이력으로 취급하지 않는다. Snapshot과 SSE의 의미를 맞추되 실행 성공·복구 방향을 Frontend가 추론하지 않는다.

Secret, 승인/Claim 권위 값, 전체 Provider 원문을 Browser Storage에 저장하지 않는다. 계정·scope·container가 바뀌면 해당 탐색 cache를 분리/무효화하고, 새로고침 시 현재 server snapshot을 조회한다. 저장소별 보존 구현은 Domain·보안·환경 계약이 소유한다.

## 20. API_ONLY와 LOCAL_CAPABLE 차이

### API_ONLY

- API_LLM만 표시
- Ollama·Local 모델 설정·진단 UI 숨김
- API Key 미설정·연결 실패는 추론이 필요한 요청에 안내하며 메인 화면·저장 이력·Settings 진입은 유지
- GPU가 없는 팀원과 CPU-only 사용자 기본 경로

### LOCAL_CAPABLE

- `AUTO`, `LOCAL_GPU`, `API_LLM` 제공
- Local Runtime provisioning 진행·복구 상태와 active single-model Signed Profile readiness 표시
- 명시적 LOCAL_GPU 실패 시 자동 전환하지 않고 API 전환 Action 제공
- AUTO fallback 발생 시 이유와 실제 Runtime 표시

공통 UI, Agent 흐름, 승인 정책, Tool Schema는 두 프로필에서 동일하다.

### 20.1 Provisioning 중단·복구 UX

- 브라우저를 닫아도 Service가 안전하게 진행할 수 있는 단계는 계속되며, 다음 실행에서 persisted operational reservation과 실제 Artifact 상태를 reconcile한다.
- 사용자가 취소하면 아직 시작하지 않은 다운로드만 중단하고 이미 설치된 shared Ollama를 임의 제거하지 않는다.
- 동일 오류가 반복되면 수동 CLI를 안내하지 않고 `진단 열기`, `다시 시도`, `API로 계속` 중 현재 상태에서 허용되는 Action만 제공한다.
- Model Profile이 Release Gate를 통과하지 않았거나 digest가 다르면 `지원되지 않는 로컬 모델`로 표시하고 실행 대상으로 선택하지 않는다.

## 21. P0 반응형 기준

- 기준 환경: Windows 11 x64, 최신 Chrome·Microsoft Edge, `127.0.0.1` same-origin React UI
- 넓은 화면: 3열 레이아웃
- 중간 폭: 오른쪽 패널 자동 접힘
- 좁은 폭: 중앙 채팅 우선, 양쪽 패널 Overlay
- 중앙 입력창과 승인 Button은 항상 접근 가능해야 한다.

## 22. 접근성·표현 규칙

- 상태를 색상만으로 구분하지 않고 Icon과 문구를 함께 사용한다.
- 주요 Button은 동사 중심으로 작성한다.
- 위험 Action은 결과를 함께 표시한다.
- 기술 용어보다 사용자 행동과 결과를 우선 표시한다.
- 오류 메시지는 원인, 현재 상태, 다음 행동을 포함한다.
- Keyboard로 채팅 입력, 후보 선택, 승인·취소가 가능해야 한다.

## 23. 금지 UX

- Context, 계획, 승인, 실행 결과를 각각 별도 페이지로 분리
- 정상 실행에서 매번 Source를 직접 선택하도록 요구
- Agent가 이미 확인한 사람·날짜·Resource를 다시 입력하도록 요구
- 읽기·검색 Action마다 승인 요청
- 같은 Plan을 시스템별로 반복 승인하도록 강제
- 수정 후 별도 화면에서 저장·검증·승인을 반복
- 기술 로그를 기본 화면에 상시 노출
- GPU가 없는 PC에 Local 설치 Action 노출
- 사용자가 한 번 결정한 승인 Button을 다시 실행 가능하게 유지
- Local Agent API·SSE 연결 오류를 Google Write 실패로 단정
- Browser Local Storage를 승인·실행 사실의 기준점으로 사용
- React Frontend에서 Provider API·Keyring·SQLite를 직접 호출
- 실행 중인 쓰기를 결과 확인 없이 취소 완료로 표시

## 24. P0 UX 완료 조건

업무 Connector·Model Provider가 모두 미연결이고 외부 전송에 동의하지 않아도 Core가 정상이면 메인 화면 진입을 제공한다. 실제 요청에 필요한 연결·AI 준비와 값만 안내한다. 초기 연결 부족은 요청 종료 후 재전송으로, 실행 중 인증 만료는 기존 안전 재개로 구분한다. 실제 자료 탐색·선택, compact Task 승인·자연어 수정·재승인, 서비스별 Write·검증·복구가 채팅 안에서 연결돼야 한다.

누적 Activity는 Agent 실행 중 작업 사실 추가, 종료 후 하위 내역 보존, schema/의미/외부 결과 검증의 구분, 같은 Conversation의 요청 A/B 이력 유지와 복원을 충족해야 한다. 화면을 보기 위한 추가 모델/Connector 호출이 없어야 하며, unknown·partial·cancel을 사실에 맞게 설명해야 한다.

실제 앱에서 UI부터 Backend log/저장 상태/외부 결과까지 대조한다. fake UI, 자동 테스트 통과, Run COMPLETED만으로 UX 완료를 선언하지 않는다. 이 절은 검증 기준이며 현재 완료 보고가 아니다.

## 25. Multi-Agent 진행 표시

사용자용 역할 label은 `요청 분석 에이전트`, `자료 검색 에이전트`, `업무 분석 에이전트`, `계획 생성 에이전트`, `검토 에이전트`처럼 이해 가능한 명칭을 사용할 수 있다. `작업 실행`, `결과 확인`, `사용자 확인`, `연결`, `복구`는 실제 책임에 맞게 표시한다.

내부 node/tool/profile 식별자를 그대로 노출하지 않으며, 표시용 Agent label이 새로운 runtime owner를 뜻하지 않는다. 하나의 실제 실행 안의 여러 모델 호출을 모두 별도 Agent 행으로 늘리지 않는다. 그 안의 의미 있는 확인·작성·검증 결과는 해당 실행의 하위 작업 사실로 남긴다. 누적/상세/회차 규칙은 이 문서의 진행 상태 UX에서만 정의한다.

## 26. Agent 진행·결과 UX

최종 Assistant Message는 사용자 요청의 결과이며 Activity를 대신하지 않는다. 반대로 진행 상태·generic 완료 문장도 최종 답변을 대신하지 않는다.

최종 답변은 요청 언어를 존중한 읽기 쉬운 Markdown으로 표시하고 raw HTML을 실행하지 않는다. Snapshot과 Conversation History에 같은 메시지가 있으면 저장된 identity로 한 번만 표시한다.

Answer-only에는 불필요한 승인/실행 카드를 만들지 않는다. Legacy READ Plan을 새 표준 경로처럼 제시하지 않는다. 과거 Run의 답변·Activity는 이력이며 새 Run의 숨은 Context·승인으로 사용하지 않는다.

## 27. UX 실행 계약

### Local Session 전 화면

- `/health/live`, `/health/ready` 결과와 Bootstrap 교환 화면만 표시한다.
- Bootstrap 성공 전 일반 `/api/v1/*` Command를 보내지 않는다.

### OAuth 연결

UI는 기존 연결 시작과 상태 조회를 사용한다. Google 로그인과 GitHub Device Flow의 사용자 상호작용은 구분하되 callback/token 처리 채널을 Frontend에 추가하지 않는다. Device Flow의 인증 대기는 Settings 연결 절차이고 업무 Run의 durable 인증 대기가 아니다. 연결 때문에 종료된 요청을 자동 resume하지 않는다. 실행 중 만료된 Run에 대해서만 기존 명시적 same-Run resume 결과를 구분해 표시한다. 인증 상태 변화 때문에 다른 Connector의 설정을 초기화하지 않는다.

### 중복 Command

- 전송 중 Button 잠금은 UX 보조 수단이다.
- Timeout 후 새 `command_id`를 만들지 않고 기존 ID로 상태를 조회·재전송한다.
- 같은 ID의 기존 결과가 있으면 해당 Snapshot을 반영한다.

### 대화 관리 범위

- P0: 새 대화, 대화 목록·검색·선택·재개.
- P1: 대화 이름 변경·대화 삭제.

## 28. Clarification 선택 UX

후보가 있으면 의미 있는 차이와 함께 선택지를 보여준다. 이름·직급·소속·최근 관련 업무는 실제 확인한 값만 사용한다. 자유입력은 허용할 수 있지만 이미 제공된 값을 매번 다시 입력시키지 않는다.

일반 검색으로 해결 가능한 모호성을 최초 입력 Form으로 전환하지 않는다. 반대로 저장소 identity 충돌이나 안전한 Write에 필수인 사용자 선택을 기본값으로 숨기지 않는다. 응답 후 같은 Run의 필요한 지점에서 이어가고 누적 Activity를 보존한다.

## 29. Main UI 구현 계약

### 29.1 Desktop 정보 구조

Header는 `mcp-work-agent`, 패널·테마·도움말·Settings로 구성한다. 정상 계정/email/runtime 상태를 반복 노출하지 않는다. Center는 자료 Preview → Conversation과 누적 Activity → Inline Card → Composer가 주 작업 공간이다.

App shell과 Composer는 고정하고 좌·우 패널 및 중앙 이력은 독립적으로 scroll한다. Browser 제품에 가짜 Window 최소화/최대화/닫기 control을 만들지 않는다.

### 29.2 Left Resource Panel

기존 Gmail·Tasks·Calendar 탐색을 보존한다. GitHub 연결/저장소 설정을 위해 두 번째 자료 탐색 앱이나 미요구된 repository dashboard를 만들지 않는다. 현재 제공되는 Issue 탐색·선택 UI가 있으면 기존 Resource 경로와 일치하게 사용한다.

Focus는 중앙 Preview, checkbox 집합은 요청 Context다. 서로를 임의 초기화하지 않는다. Preview는 compact하고 전체 내용은 bounded 영역의 펼침·스크롤로 접근한다. 제공되지 않은 제목·metadata는 추정하지 않는다.

### 29.3 Center Conversation과 Approval

Quick Action은 기존 Agent 요청 진입점이며 직접 Write 버튼이 아니다. 서버가 제공한 승인·수정·거절과 오류 action을 사용한다. 카드 제출 중 잠금과 실제 서버의 중복 방지를 혼동하지 않는다.

### 29.4 Right Panel, Settings, 반응형

대화 목록·검색·복원을 유지한다. Recent Execution은 실제 이력이 있을 때만 표시한다. Settings/Diagnostics는 기존 Drawer/Dialog를 재사용한다. 좁아지면 오른쪽부터 접고, 중앙 입력·승인 버튼 접근을 유지한다.

### 29.5 공통 상태와 접근성

Loading, Empty, Error, Selected, Focus, Disabled, Submitting, 사용자 대기와 완료를 색상 외 문구·icon으로 구분한다. 키보드로 목록·후보·승인·취소·Activity 펼침을 조작할 수 있고 focus가 보여야 한다. 추가 progress 이벤트가 현재 읽는 상세를 숨기거나 초점을 빼앗지 않는다.

## 30. Calendar·Tasks Sidebar 및 Viewer Empty State

### 30.1 Calendar Sidebar

- Calendar Sidebar는 Month View만 제공한다. 월력은 일요일 시작이며 실제 필요한 5/6주 grid를 계산하고 configured user timezone의 `[gridStart, gridEnd)`를 사용한다. `gridStart`는 월 1일 이전/당일의 가장 가까운 일요일 00:00, `gridEnd`는 마지막 렌더 주 다음 일요일 00:00이다.
- visible grid 범위의 Event instance는 `singleEvents=true`, Provider page size 최대 100으로 terminal까지 materialize하며 UI pagination을 만들지 않는다. 현재 월 complete 뒤 이전/다음 월 background prefetch는 한 단계까지만 허용하고 chain prefetch하지 않는다.
- 날짜 cell은 Event 0개면 marker 없음, 1개면 dot 하나, 2개 이상이면 dot+count를 표시한다. 날짜 클릭은 API 호출 없이 selected-date 목록만 변경한다. Month 검색은 완전히 materialize한 cache를 client-side filter하며 marker/count와 selected-date 목록에 함께 적용한다.
- All-day Event는 `[start.date, end.date)`, timed Event는 configured timezone에서 `[start, end)`와 실제로 겹치는 날짜 cell에 표시한다. 정확히 다음 날 00:00에 끝나는 Event는 다음 날 cell에 표시하지 않는다. 반복 Event는 occurrence 단위다.
- Event row는 제목 아래에 시간 범위를 표시한다. 같은 날 시간 Event는 `YYYY년 M월 D일 (요일) 오전/오후 h:mm - 오전/오후 h:mm`, All-day Event는 `YYYY년 M월 D일 (요일) · 하루 종일`로 표시한다. Sidebar에는 `시작`, `종료` label을 표시하지 않고 중앙 Resource Viewer의 상세 필드는 유지한다.
- Calendar tab에는 numeric badge를 표시하지 않는다. 일반 Upcoming Browse는 사용자 Timezone 기준 현재부터 **향후 90일** 기본 범위를 유지하지만 Month View range와 혼용하지 않는다.
- Refresh는 현재 monthAnchor·selected date를 유지하고 현재 visible grid cache만 fresh materialize한다.

### 30.2 Tasks Sidebar

- Tasks는 실제 Google Workspace Source이며 기본 compact row는 **Task 제목 → 예정일** 순서다. 제목, 메모, 예정일, Task List, 완료 상태 중 실제 Projection이 제공한 값만 사용한다.
- 기본 미완료 Browse는 Provider 반환 순을 유지한다. 별도 정렬 row를 두지 않고 `⋮` 메뉴의 `기본 순서 | 날짜순`만 제공하며 날짜순은 전체 materialization 후 `scheduled_date` 오름차순·날짜 없는 Task 후순위로 정렬한다.
- 목록은 `tasks.list` metadata를 사용하고 `tasks.get`은 focus/선택 상세 조회에만 사용한다. Provider metadata batch를 Session Cache에 받고 UI는 configured `SIDEBAR_PAGE_SIZE`로 표시한다.
- 미완료 목록 하단의 `완료됨(N)` section은 기본 접힘이다. completed scope를 background terminal materialization해 실제 `task_status=completed`만 `resource_id`로 dedupe하고 exact `N`과 row cache를 함께 만든다. section 펼침과 `더 보기`는 cache를 configured `SIDEBAR_PAGE_SIZE` 단위로 보여주는 presentation이며 Provider 추가 호출을 만들지 않는다.
- Provider raw `completed` RFC3339은 `completed_at`으로 보존한 경우에만 configured `SettingsViewV1.timezone` 기준 `완료일: M월 D일 (요일)` 보조 텍스트로 표시한다. 값이 없거나 유효하지 않으면 완료일 줄을 생략하고 `scheduled_date`·`due`·`updated`·현재 시각을 fallback으로 사용하지 않는다.
- Refresh는 incomplete와 completed cache를 모두 fresh generation으로 갱신하며 completed 결과는 terminal 성공 시 atomic replace한다.
- Local API Projection은 Provider `needsAction`을 `미완료`, `completed`를 `완료`로 정규화한다. Google `due`는 UI에서 `예정일`로만 표시하고 예정일 경과는 상태 전이가 아니라 `예정일 지남` 보조 문구만 허용한다.
- Task List는 실제 반환 값일 때만 보조 표시하고 priority, 가짜 category·Task List 이름·색상 dot·raw Provider enum/token은 표시하지 않는다.

### 30.3 Resource Viewer Empty State

- 중앙 Viewer 제목은 `자료 상세`로 Source 공통이다. Focus가 없을 때 메일은 `왼쪽 목록에서 메일을 선택하면 상세 내용을 확인할 수 있습니다.`, Tasks는 `왼쪽 목록에서 태스크를 선택하면 상세 내용을 확인할 수 있습니다.`, Calendar는 `왼쪽 목록에서 일정을 선택하면 상세 내용을 확인할 수 있습니다.`를 표시한다.
- Source 전환 시 이전 Source의 Focus 및 상세 정보는 남지 않는다. 새 Source의 Empty State를 먼저 표시하고, 행 Focus 후 해당 Source의 실제 Projection 상세만 표시한다.

## 31. Gmail 첨부파일 UX

- Gmail Message에 첨부파일이 있으면 파일명·유형·크기를 표시한다.
- 사용자가 선택한 파일만 다운로드하며 첨부파일 내용을 Agent가 자동 요약·분석하지 않는다.
- Draft/Send Action에서는 첨부 예정 파일명·유형·크기를 승인 카드에 함께 표시한다.
- 파일이 Staging 만료·Hash mismatch로 무효화되면 기술 오류 대신 “파일을 다시 선택해야 합니다”를 표시하고 기존 승인 버튼을 재사용하지 않는다.
- 첨부파일은 별도 화면을 만들지 않고 기존 Message 상세·Action 승인 흐름 안에서 처리한다.
