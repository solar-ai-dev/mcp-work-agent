# 01-B. 정책 정의서

> **Authority:** 안전·금지·승인 정책. 시스템·Domain·Interface 구현 세부는 `00 Project Source Guide`의 전문 owner를 따른다.  
> **수정일:** 2026-09-06 · **상태:** 제품 정책 정리본 — 구현·출시 검증 완료를 뜻하지 않음

## 0. 사람이 먼저 볼 핵심 정책

읽기는 허용된 요청 범위 안에서 자동 수행할 수 있지만, 모든 외부 Write에는 명시적인 사용자 승인이 필요하다. 사용자의 편의 설정이나 LLM 제안은 접근 권한·대상 무결성·승인을 대신하지 않는다.

Gmail 원문 삭제와 반복 Event 전체 일괄 수정은 금지한다. GitHub는 현재 허용된 Issue 작업 범위를 넘겨 PR·저장소 관리 작업을 추측 실행하지 않는다. 결과가 불확실한 Write는 재전송하지 않고 기존 결과를 확인한다. Source 본문은 항상 비신뢰 데이터이며 실행 권한을 만들지 않는다.

## 1. 문서 목적

이 문서는 **허용·금지·승인·개인정보·실행 안전의 경계**를 소유한다. 사용자가 할 수 있는 기능 목록, 화면 배치, API field 목록, SQL, Graph topology는 여기서 재정의하지 않는다.

정책은 일반 코드가 강제한다. LLM은 의미·후보를 제안할 수 있지만 정책 Override, 승인 유효성 또는 실행 성공을 확정할 수 없다. Schema 검증은 형식을, 정책 평가는 허용·확인 조건을, Domain guard는 상태·동시성·불변조건을 각각 담당한다. 한 검증의 통과로 다른 검증을 생략하지 않는다.

공통 안전 규칙은 모든 등록 Connector에 동일하게 적용하고, Gmail·Tasks·Calendar·GitHub의 고유 제한만 각 절에서 정의한다. 기술적 강제 방법은 기존 보안·Domain·Interface 계약을 따른다. 이 문서 정리는 보호된 실행 계약이나 실제 권한을 자동 변경하지 않는다.

## 2. 정책 우선순위

정책 충돌 시 다음 순서를 적용한다.

1. 금지·보안 정책
2. 승인·무결성 정책
3. 데이터·개인정보 정책
4. 실행·검증 정책
5. 사용자 설정
6. Agent 추천

메일·Task·Event·Issue 본문에 포함된 지시는 이 정책보다 우선할 수 없다.

## 3. 위험 등급

| 등급 | 정의 | 처리 |
| --- | --- | --- |
| READ | 조회·검색·분석 | 사용자 요청 범위에서 자동 실행 가능 |
| WRITE_LOW | Draft·Task·Event 생성 또는 허용 필드 수정 | 사용자 승인 필수 |
| WRITE_HIGH | 메일 전송·Event 삭제·외부 참석자 변경처럼 외부 영향이 큰 작업 | 정확한 대상·인자를 고정하고 사용자 승인 후 실행. 승인 이후 인자 변경·UNKNOWN_RESULT 자동 재실행 금지 |
| SYSTEM | Credential·환경·DB 변경 | 명시적 설정 화면에서만 수행 |

## 4. Tool 허용 정책

### 4.1 허용되는 읽기 Tool

허용된 계정·범위의 Gmail Thread/Message, Tasks List/Task, Calendar List/Event/FreeBusy, GitHub 접근 가능 저장소와 Issue를 조회할 수 있다. 실행 결과의 재조회도 같은 Connector 접근 경계를 따른다. 등록되지 않은 Tool이나 권한 밖 데이터는 허용 목록에 있다고 추측하지 않는다.

### 4.2 승인 후 허용되는 쓰기 Tool

현재 등록 계약이 지원하는 다음 변경만 승인 후 허용한다.

- Gmail Draft 생성·수정, 새 메일 전송, 기존 Thread Reply.
- Google Task 생성·허용 필드 수정·완료 상태 변경·삭제.
- Calendar Event 생성·허용 필드 수정·삭제 및 참석자 변경.
- GitHub Issue 생성·허용 필드 수정·닫기·다시 열기.

이 목록은 정책상 허용 범위이지 각 작업의 구현·Live 검증 완료 선언이 아니다. 실제 배포는 해당 Tool의 계약·권한·출시 검증을 충족해야 한다.

### 4.3 금지 Tool

Gmail Message/Thread 원문 삭제, Gmail Label/설정 변경, 반복 Event 전체 일괄 수정, 미등록 GitHub PR·저장소 mutation을 허용하지 않는다.

승인·정책·검증을 우회하는 DB/System 직접 변경이나 Connector MCP 경계 밖의 Provider 접근도 금지한다. 금지 Tool은 화면에서 숨기는 데 그치지 않고 실행 가능한 등록·dispatch 대상에서 제외한다. 구체적인 계층·Port 배치는 Repository Architecture를 따른다.

## 5. 승인 정책

### POL-APP-001 쓰기 승인

모든 WRITE_LOW·WRITE_HIGH Action은 실행 전에 사용자의 명시적 승인을 받아야 한다.

### POL-APP-002 승인 단위

- Action별 승인 기본
- 전체 승인과 시스템별 일괄 승인 허용
- 일부 승인 허용
- 거절 Action과 종속 Action은 실행하지 않음

### POL-APP-003 승인 내용

승인 대상의 변경 종류, Connector와 정확한 Resource, 변경할 업무 값, 필요한 근거·위험·외부 영향과 예상 결과를 사용자가 확인할 수 있어야 한다. 단순히 ‘계속’이라는 버튼을 누른 사실만으로 숨겨진 변경 범위까지 승인받았다고 해석하지 않는다. 카드 배치와 상세 펼침은 UI concern이다.

### POL-APP-004 승인 무결성

승인은 당시의 Action revision, 대상 Connector/Resource, 업무 인자, 근거·정책·Tool 계약에 결합한다. 실행 직전까지 그 결합과 최신성·실행 가능 상태를 검증해야 한다.

승인 이후 업무 값·대상·dependency가 달라지면 이전 승인을 재사용하지 않는다. 자연어 수정도 예외가 아니며 재검토·재승인을 거친다. 화면 요약과 저장된 승인 대상이 다르면 실행을 허용하지 않는다.

실행권 예약·Claim Token 발급만으로 외부 Write를 허용하지 않는다. 기존 실행 admission이 실제 적용된 동일 Attempt에만 dispatch를 허용한다. 이미 존재하는 Resource와 bound container/repository가 모순되면 Provider 조회·Write 전에 차단한다. Provider 조회는 틀린 대상 binding을 사후 정당화하는 수단이 아니다.

서명·Hash·Nonce·UoW·상태 전이의 상세는 기존 실행·보안 계약이 소유하며 여기서 별도 변형을 만들지 않는다.

### POL-APP-005 승인 만료

다음 중 하나면 승인을 만료한다.

- 정책에서 정한 승인 유효 시간이 지남
- 원본 Resource가 변경됨
- 사용자가 Arguments를 수정함
- Tool Schema 또는 Policy Version이 변경됨

구체적 유효 시간은 policy invariant가 아니라 `10 Infrastructure`의 운영 설정으로 관리한다.

## 6. Evidence 정책

### POL-EVD-001 최소 Evidence

모든 Action은 최소 1개 Evidence가 필요하다.

### POL-EVD-002 기존 Resource 수정

기존 Draft·Task·Event·Issue 수정은 다음 중 하나가 필요하다.

- 사용자가 Resource를 직접 지정함
- 서로 독립적인 Evidence 2개 이상
- 하나의 명확한 Gmail Thread 또는 Resource 관계

### POL-EVD-003 낮은 신뢰도

조회 가능한 모호성은 허용된 bounded 검색으로 먼저 확인한다. 단, 근거가 약한 후보·별칭·추정 날짜를 확정된 identity나 업무 사실로 승격하지 않는다. 복수의 유효 후보가 남거나 안전한 실행에 필수인 값이 불명확하면 사용자 확인 또는 차단이 필요하다. 부분 READ 답변 허용은 미해결 WRITE 허용이 아니다.

## 6-A. Run Context 격리 정책

### POL-CTX-001 새 Run의 Context 권위

- 새 Run의 Context 권위는 현재 `RunInputV1`과 그 Run에서 새로 확정된 Typed Artifact다.
- 같은 Conversation의 이전 Run Message·RequestIntent·Tool Route·Retrieval/Evidence·Work Analysis·Plan/Review·Confirmation Receipt·Checkpoint를 현재 Run의 근거·의도·승인·정책 확인으로 자동 재사용하지 않는다.
- 사용자가 이전 화면에서 Resource를 다시 명시적으로 선택해 새 Run에 첨부한 경우에는 그 **Resource reference**만 현재 Run의 Entry Context가 된다. 이전 Run의 Evidence 판정이나 Approval은 함께 승계되지 않으며 필요하면 현재 Run에서 다시 조회·검증한다.
- 이전 Run의 Approval, Claim, Confirmation Receipt는 새 Run의 Write 권한 또는 Scope 확장 근거가 될 수 없다.
- 같은 Run의 Confirmation/재인증/Recovery resume는 새 Run Context 승계가 아니라 동일 Run의 안전 checkpoint 연속성으로 취급한다.
- 현재 요청이 이전 Run 없이는 해석되지 않는 모호한 표현이고 이번 Run에 명시적 Resource가 없으면, 과거 Conversation 내용을 암묵적으로 추론 근거로 사용하지 않고 확인 질문으로 전환한다.

## 7. Gmail 정책

### POL-GML-001 읽기 범위

사용자의 업무 의미에 관련된 Thread/Message만 조회한다. 사람·기간·정확한 제목이나 ID는 명시된 의미를 유지한다. 추상 개념을 찾기 위한 bounded 검색 표현 변경은 허용하지만, 그것이 계정·Source·대상 범위 확대에 대한 동의를 만들지는 않는다. 전체 메일함의 무제한 조회는 허용하지 않는다.

### POL-GML-002 Draft 생성

- Draft는 전송하지 않는다.
- 기존 Thread 회신이면 Thread 연결을 유지한다.
- 수신자·CC·제목·본문을 승인 화면에 표시한다.

### POL-GML-003 외부 주소

외부 도메인 수신자는 다음 경우에만 Draft에 포함할 수 있다.

- 사용자가 직접 지정함
- 기존 Thread 참여자임

그 외에는 확인 질문을 한다.

### POL-GML-004 원문 저장

Gmail 전체 원문은 SQLite에 장기 저장하지 않는다. 사용자가 메일을 열거나 선택하거나 Agent가 후보를 확정했을 때 필요한 Thread·Message 상세만 현재 Run 메모리에서 사용한다. 실제 판단과 승인에 사용된 최소 Evidence excerpt와 생성 Draft만 Run 보존 기간 동안 저장할 수 있다.

## 8. Tasks 정책

### POL-TSK-001 생성 전 중복 검사

Task 생성 전에 기존 미완료 Task를 검사한다.

### POL-TSK-002 중복 처리

- 명확한 중복: 기존 Resource를 보여주고 기본적으로 새 생성을 중단
- 사용자가 중복임을 인지하고 동일 Resource 추가 생성을 명시적으로 요구: 재확인·승인 후 허용
- 유사 후보: 경고 후 사용자 확인
- 관련 없음: 생성 허용

구체적 유사도 임계값은 bounded configuration이며 채택 근거와 calibrated value는 `13 Evaluation`이 관리한다. 이 문서는 threshold 수치 자체를 policy invariant로 소유하지 않는다.

### POL-TSK-003 허용 필드

- 제목
- 메모
- 예정일
- 대상 Task List

Task 완료 상태 변경과 Task 삭제는 정확한 Task 대상과 사용자 승인 후 허용한다. Task 삭제는 `DELETE` Effect로 처리하고 실행 후 대상 부재를 재조회해 검증한다.

### POL-TSK-004 날짜·상태 의미와 금지

- Google Task `due`는 제품 내부 `scheduled_date`에만 대응하는 예정일이다. 이를 실제 업무 `business_deadline`으로 표현·판단·검증하지 않는다.
- Gmail·사용자 요청·Evidence에서 확인한 `business_deadline`을 `scheduled_date` 또는 Google `due`로 자동 변환하지 않는다. Task 생성에서 의미 보존이 필요하면 승인된 notes와 Evidence·Approval Summary를 사용한다.
- API에 없는 deadline 또는 작업 시간을 추정해 Task Write Argument에 만들지 않는다. 정확한 시간 예약은 승인형 Calendar Event 대안을 사용자에게 제시할 수 있으나 자동 생성하지 않는다.
- Provider raw status는 UI에 직접 노출하지 않는다. 예정일 경과는 실제 완료 상태를 변경하지 않으며, Task 완료는 정확한 대상·사용자 승인형 `UPDATE`만 허용한다.

## 9. Calendar 정책

### POL-CAL-001 Event 생성 조건

Event의 대상 Calendar, 시작·종료 또는 확정 가능한 소요시간, 배치 기준, 필요한 충돌 검사 결과가 있어야 한다. 명시된 시작·종료로 소요시간을 계산할 수 있으면 같은 값을 다시 질문할 이유가 없다. 값이 없거나 상충해 안전하게 결정할 수 없으면 확인한다.

충돌 조회 실패를 ‘충돌 없음’으로 간주하지 않는다. 메일 수신일이나 미해결 날짜·인물을 행사일·참석자로 확정해 실행하지 않는다.

### POL-CAL-002 Busy 판정

다음은 Busy로 취급한다.

- Opaque Event
- Out of Office
- Focus Time
- 선택 Calendar의 Busy Interval

Tentative는 경고로 처리하고, Declined 또는 Free Event는 Busy에서 제외한다.

### POL-CAL-003 참석자 변경

내부·외부 참석자 추가·수정을 승인형 Write로 지원한다. 참석자 이메일과 대상 Event를 승인 화면에 명시하며 대상이나 이메일이 모호하면 실행 전에 확인한다.

### POL-CAL-004 작업 시간

일정 자동 배치는 사용자가 설정한 timezone·업무 시간·주말·Buffer를 적용한다. 초기 기준은 평일 09:00~18:00, 주말 제외다. 명시된 사용자 시각을 편의상 다른 시각으로 몰래 바꾸지 않는다. 정확한 설정 field·기본값의 저장 방식은 기존 환경 계약을 따른다.

## 10. 중복·충돌 정책

### POL-DUP-001 결정 방식

중복과 충돌은 LLM 단독 판단으로 확정하지 않는다. 일반 코드 Validator와 Source 데이터로 판단한다.

### POL-DUP-002 Override

- 중복·충돌 경고는 사용자 2차 확인으로 Override 가능
- 명확한 중복도 사용자가 중복 사실을 인지하고 동일 Resource 추가 생성을 명시적으로 요구한 경우 재확인·승인 후 허용 가능
- 금지 작업과 승인 무결성 위반은 Override 불가

## 10-A. Connector 사용 전제 정책

### POL-CON-001 Core와 업무 연결의 분리

Google Workspace는 P0 핵심 Connector지만 Google·GitHub Credential의 존재는 Core startup/readiness·메인 UI·기본 Conversation/Run 생성의 전역 허용 조건이 아니다. 업무 연결을 하지 않은 이유로 앱 자체를 사용 불가로 판정하거나 Google 기능을 제품에서 제거하지 않는다. Local Session·DB 무결성·필수 실행 파일/계약 검사는 이와 별개로 유지한다.

### POL-CON-002 초기 사용 불가 요청의 종료

현재 요청에 필요한 Connector만 확인한다. 필요한 연결이 처음부터 없거나 App 설치·repository 접근·필수 permission이 준비되지 않았으면 해당 업무 처리를 진행하지 않고 조치 안내와 함께 현재 요청을 종료한다. 연결 후 사용자의 재전송은 새로운 요청이다. 이 상태를 자료 없음이나 실행 성공으로 처리하지 않는다.

초기 연결을 기다리는 durable Run, AUTH_WAITING 상태, 인증 대기 checkpoint, callback 기반 자동 resume, background App 설치 polling/watcher를 만들지 않는다. Settings의 정상 Device Flow 인증 polling은 계정 연결 절차이며 중단 Run을 감시·재개하는 기능이 아니다. 필요한 연결의 실패를 무관한 정상 Connector로 전파하지 않는다.

### POL-CON-003 실행 중 인증 만료의 구분

필요한 연결을 갖추고 정상 실행 중이던 Run의 Credential 만료·갱신 실패는 기존 REAUTH_REQUIRED·safe resume 계약을 유지한다. OAuth callback은 특정 Run을 자동 재개하지 않는다. 이미 수행했거나 수행했을 수 있는 외부 효과는 기존 Verification/Recovery로 처리하며, 초기 미연결 종료 규칙으로 in-flight 사실을 덮어쓰지 않는다.

### POL-CON-004 권한 밖 접근과 실패 설명

연결을 안내하는 동안 권한 밖 repository를 탐색하거나 다른 계정·저장소로 자동 대체하지 않는다. 연결 상태·권한·App 설치 여부와 현재 사용자의 필요한 조치를 허용된 metadata로만 설명한다. 조회가 수행되지 않은 상태를 정상 빈 결과로 표현하지 않는다.

## 11. Google Workspace Connector OAuth 정책

### POL-OAUTH-001 사용자 로그인 방식

사용자는 자신의 Google Cloud 프로젝트나 OAuth Client JSON을 준비하지 않는다. 앱은 개발팀이 소유한 Desktop OAuth Client를 사용하고 UI에는 `Google로 로그인` 버튼만 제공한다. Google 연결 선택은 앱 진입의 전제와 구분한다. Google Workspace를 사용할 때는 계정 인증뿐 아니라 필요한 Gmail·Tasks·Calendar Scope 동의가 완료되어야 한다.

### POL-OAUTH-002 OAuth 프로젝트 분리

개발, 스테이징, 운영은 서로 다른 Google Cloud 프로젝트와 OAuth Client를 사용한다. 테스트 Scope나 Redirect 설정을 운영 프로젝트에 직접 추가하지 않는다.

### POL-OAUTH-003 Desktop OAuth 흐름

- OAuth Client 유형: Desktop App
- Redirect: `http://127.0.0.1:<ephemeral-port>` loopback
- PKCE 필수
- `state` 검증 필수
- OOB 수동 코드 복사 방식 금지
- Refresh Token은 OS Keyring 저장
- Signed P0 Installed/Desktop OAuth는 non-secret `oauth_client_id`와 PKCE·`state`·ephemeral loopback만 사용하며 `client_secret`을 요구하지 않는다.
- `EXPLICIT_DEVELOPMENT`에서는 Google token endpoint가 해당 Desktop Client에 요구하는 경우에만 `.env.local`의 optional `GOOGLE_OAUTH_CLIENT_SECRET`을 MCP Credential Provider가 직접 읽어 authorization-code/refresh grant에 사용할 수 있다. 값은 React/Vite, FastAPI wire, SQLite, Log, Trace, Diagnostic, OS Keyring 또는 MCP child environment로 전달·저장하지 않는다.

### POL-OAUTH-004 팀 테스트

- 개발·스테이징 OAuth 앱은 팀 Google 계정을 Test User로 등록한다.
- External + Testing 상태의 Refresh Token 7일 만료를 정상 오류로 처리하고 재로그인을 제공한다.
- Test User가 아닌 계정은 P0 테스트 배포에서 연결하지 않는다.

### POL-OAUTH-005 운영 배포 Gate

공개 운영 배포는 OAuth 브랜드와 데이터 액세스 검증이 완료된 Client만 사용한다. Gmail 본문 읽기와 Draft 관리 Scope는 제한 Scope로 관리하며 검증되지 않은 Client를 일반 사용자 배포에 포함하지 않는다.

### POL-OAUTH-006 최소 Scope

P0 OAuth permission은 **구현된 기능에 필요한 최소 집합만 요청**하고, required permission 일부가 거절되면 연결을 완료 처리하지 않는다.

Exact provider Scope 문자열과 Credential/Auth realization은 `09 Security §P0 Scope`가 소유하고, Tool별 required Scope mapping은 `07 Interface`가 소비한다. Policy 문서에서 같은 Scope 목록을 별도 유지하지 않는다. Gmail Send를 포함한 모든 Write는 Scope 보유 여부와 무관하게 본 문서의 승인·Tool Allowlist·실행 무결성 정책을 그대로 통과해야 한다.

### POL-OAUTH-007 Gmail 데이터 외부 처리

API LLM 모드에서 Gmail Context를 외부 Provider로 전송하는 것은 사용자 기능 제공에 필요한 범위와 사용자 동의 안에서만 허용한다. Provider가 해당 데이터를 광고, 범용 모델 학습, 재판매에 사용하도록 허용하지 않는다. 공개 운영 배포 전 제한 Scope 보안 평가와 Google Limited Use 준수 여부를 확인한다.

## 12. LLM Runtime 정책

### POL-LLM-001 CPU-only

CPU-only 또는 GPU 기준 미달 PC는 API_LLM으로 고정한다. CPU Local LLM은 지원하지 않는다.

### POL-LLM-002 P0 GPU 사용 가능 환경

P0에서 검증된 GPU 환경은 AUTO, LOCAL_GPU, API_LLM을 모두 제공한다. Local 모드는 후속 기능이 아니라 P0 제품 기능이다.

### POL-LLM-003 AUTO fallback

AUTO는 다음 기술 오류에서 API로 최대 1회 fallback할 수 있다.

- Local Runtime 연결 실패
- 모델 없음 또는 로드 실패
- GPU OOM
- Timeout
- 반복된 Structured Output 실패

단순한 답변 품질 불만이나 낮은 자신감만으로 자동 fallback하지 않는다.

### POL-LLM-004 명시 모드

사용자가 LOCAL_GPU 또는 API_LLM을 명시 선택하면 동의 없이 다른 모드로 전환하지 않는다.

### POL-LLM-005 Ollama 고정

제품의 Local LLM Runtime은 Ollama로 고정한다. Release Config에 포함되지 않은 Runtime은 제품 Runtime/UI authority가 아니며 제품 UI에 노출하지 않는다.

### POL-LLM-006 모델 선택·Tier

제품은 출시 검증을 통과한 승인 Local Model Profile만 사용한다. 업무 Agent와 일반 사용자 입력은 임의 model ID/digest를 선택할 수 없다. WORKER/REASONING은 책임 class이며 실제 모델은 검증된 profile에서 결정한다.

확정한 기본 제품 방향은 두 class 모두 `qwen3.5:9b`다. `qwen3.5:4b`는 향후 선택 가능한 profile 후보일 뿐 이번 기본 설치·활성 모델이 아니다. 개발 환경에서 9B 추론에 성공했다고 signed release·hardware·설치 검증을 통과한 것으로 보지 않는다. 이번 문서 변경이 배포 profile을 자동 활성화하지 않는다.

### POL-LLM-007 배포 프로필

- `API_ONLY`: Ollama·GPU·모델 파일 불필요. CPU-only와 GPU 없는 팀원의 기본 프로필.
- `LOCAL_CAPABLE`: Ollama Adapter, automatic provisioning capability, Signed Local Model Profile과 Local 설정을 포함한다. 검증된 GPU에서만 Local 기능을 활성화한다.
- 두 프로필은 동일한 LangGraph, Tool Schema, Policy, Test Suite를 사용한다.

### POL-LLM-008 Local Runtime provisioning 안전

- provisioning은 `SYSTEM` 위험 등급의 결정적 Application/System operation이며 LLM Tool이 아니다.
- 다운로드 URL, installer identity, Ollama version, model tag/digest, tier binding은 verified Release Manifest와 Model Manifest에서만 온다.
- Browser·Prompt·Connector Source가 임의 URL, shell argument, model tag 또는 digest를 주입할 수 없다.
- Signature/hash/digest가 맞지 않으면 설치·실행·모델 사용을 fail-closed하고 API 사용 가능 여부와 복구 Action만 표시한다.
- 기존 호환 Ollama는 `PREEXISTING`, 제품이 준비한 항목은 `PRODUCT_PROVISIONED`로 구분한다. Uninstall은 기존 Ollama를 제거하지 않으며 제품 모델 삭제도 사용자의 명시적 선택이 필요하다.
- Runtime 중 silent update는 금지한다. Ollama/Model 변경은 signed product upgrade 또는 명시적 repair provisioning으로만 수행한다.

## 13. API LLM 개인정보 정책

### POL-API-001 전송 고지

API LLM을 사용하면 선택된 업무 Context가 외부 Provider로 전송될 수 있음을 사용자에게 고지한다.

### POL-API-002 최소 전송

- 요청 수행에 필요한 Context만 전송
- OAuth Token·API Key·내부 Hash는 전송 금지
- 불필요한 전체 Gmail Thread·전체 Calendar를 전송하지 않음

### POL-API-003 동의

외부 LLM 호출에는 저장된 외부 전송 동의가 필요하다. API Key 등록·연결 시험·API 모드 선택은 업무 자료 전송 동의를 대신하지 않는다. 동의 철회 이후 새 외부 추론을 시작하지 않는다. Run별 최소 전송 범위는 별도로 고지한다. exact 전송 scope publish 순서는 보안·Interface 계약을 따른다.

## 14. Credential 정책

### POL-SEC-001 저장 위치

- OAuth Refresh Token: OS Keyring
- API Key 기본: OS Keyring
- 사용자 선택: 세션에서만 사용하고 종료 시 폐기
- SQLite·Checkpoint·일반 로그 저장 금지

### POL-SEC-002 마스킹

Credential, Authorization Header, Token, API Key 패턴은 로그 기록 전에 마스킹한다.

### POL-SEC-003 연결 해제

Google/GitHub 연결 해제와 API Key 삭제는 해당 credential의 로컬 저장·세션 사용을 해제한다. 다른 Connector의 credential을 삭제하거나 정상 연결을 실패로 만들지 않는다. 계정 변경 뒤 이전 계정의 기본 Resource와 접근 권한을 무조건 재사용하지 않는다. Provider revoke 가능 여부와 로컬 폐기를 구분한다.

## 15. Prompt Injection 정책

### POL-PI-001 Source 비신뢰

메일·Task·Event·Issue 본문과 그 안의 링크는 모두 비신뢰 데이터로 취급한다.

### POL-PI-002 지시 무시

Source 안의 다음 지시는 실행하지 않는다.

- 정책 변경 요청
- Secret 출력 요청
- Tool Allowlist 우회
- 승인 생략
- 외부 시스템으로 데이터 전송

### POL-PI-003 구조 분리

System Policy, 사용자 요청, Source Context를 Prompt에서 명확히 분리한다.

## 16. 실행 정책

### POL-EXE-001 Idempotency

쓰기 재시도 전 기존 Execution Result와 대상 Resource를 조회한다. 성공 여부가 불명확하면 새로 생성하지 않고 먼저 확인한다.

### POL-EXE-002 부분 실패

- 성공 Action은 보존
- 독립 Action은 계속 실행 가능
- 실패 Action에 종속된 Action은 차단
- 자동 롤백하지 않음

### POL-EXE-003 재시도

현재 Connector 계약이 재시도를 허용하는 일시 오류만 제한적으로 재시도한다. Policy·승인·Schema·identity 오류를 반복 호출로 해결하지 않는다. Write 재시도는 전달 확실성 및 새 승인/Attempt 요건을 따라야 하며 일반 READ retry와 혼용하지 않는다.

## 17. 검증 정책

### POL-VER-001 필수 검증

모든 외부 Write는 Effect에 맞는 동일 Connector의 독립적인 재조회로 검증한다. 생성·수정은 실제 대상 비교, 삭제는 대상 부재/삭제 상태, 전송은 전송 결과 조회로 확인한다. 단순 dispatch 응답이나 UI 전환은 검증 완료 근거가 아니다. 전송 기록 확인을 수신자의 읽음·확인으로 과장하지 않는다.

### POL-VER-002 비교 기준

승인 당시의 expected와 실제 actual을 독립적으로 비교한다. 표현상의 공백·줄바꿈·시간대 정규화는 가능하지만 업무 의미를 바꾸지 않는다. 대상·제목·본문 의미·Task 예정일·Event 시간·GitHub Issue의 승인된 변경 내용이 다르면 mismatch다. 실제 결과에 맞춰 expected를 사후 수정해서 통과시키지 않는다. 부분 UPDATE는 승인된 변경 필드의 의미로 비교한다.

Task CREATE의 비교 범위는 승인한 Task List, 제목, 메모, 예정일, 완료 상태이며 메모·예정일을 지정하지 않은 경우도 그 부재를 확인한다. 별도의 승인된 상태 변경이 없으면 새 Task의 상태는 미완료여야 한다. 재조회한 Task identity는 실행 결과의 ResourceRef와 일치해야 한다. 기존 persisted expected가 일부 필드를 생략했더라도 비교를 생략하지 않고 immutable Approval arguments에서 동일한 deterministic expected projection을 도출한다. Provider actual은 expected 도출에 사용하지 않는다. Task UPDATE는 대상 identity와 승인한 변경 필드만 비교한다.

### POL-VER-003 불일치 처리

Mismatch를 자동 수정하지 않고 사용자에게 차이와 Recovery Action을 보여준다. `MISMATCH` Action과 Verification 사실은 변경하지 않으며 Run은 `RECOVERY_REQUIRED`로 전환한다.

### POL-VER-004 MISMATCH Recovery 선택

현재 결과 유지와 교정 계획 생성은 기존 Recovery 계약이 허용한 상태에서만 선택할 수 있다. 현재 결과 유지는 실제 상태·mismatch 기록을 보존하고 추가 Write 없이 부분 결과로 종료한다. 교정 계획은 최신 실제 상태를 근거로 새 계획·검토·승인·Attempt·Verification을 요구한다.

기존 mismatch Action을 재실행하거나 자동 수정·rollback하지 않는다. Run 전체 취소는 별도 취소 의미이며 현재 결과 유지와 혼동하지 않는다. 정확한 허용 resolution/state matrix는 Domain State Transition Contract가 소유한다.

### POL-VER-005 Write 전달 확실성

Write 실패 분류는 Exception 이름이 아니라 외부 시스템 전달 가능성을 기준으로 한다.

- `NOT_SENT`: 외부 변경이 발생하지 않았음을 확정할 수 있는 경우에만 `FAILED` 후보가 된다.
- `MAY_HAVE_BEEN_SENT`: 요청이 전달됐을 가능성이 있으면 `UNKNOWN_RESULT`로 처리한다.
- `SENT_RESPONSE_LOST`: 요청 전달 후 응답만 유실된 경우 `UNKNOWN_RESULT`로 처리한다.

Dispatch 이후 Timeout·5xx·Transport Disconnect를 Provider가 미전달로 보장하지 않는 한 `FAILED`로 단정하지 않는다.

## 18. 데이터 보존 정책

P0의 persisted `retention_days`는 **기본 30일, 허용 범위 1..30일**이다. 사용자는 30일보다 짧게만 줄일 수 있으며 31일 이상으로 늘리는 기능은 P1 이후 별도 정책 변경으로만 도입한다.

| 데이터 | P0 보존 의미 | `retention_days` 적용 | 사용자 삭제 |
| --- | --- | --- | --- |
| Conversation·Message | 기본 30일. 보존 cutoff가 지난 row는 아래 보호 조건이 없을 때 물리 삭제 | 예 | 예 |
| Terminal Run과 소유 child(Plan·Action·Approval·ExecutionAttempt·Verification·ResourceRef·Evidence·Trace) | Run `finished_at_ms` 기준 기본 30일 | 예 | Conversation 삭제 시 함께 정리 가능 |
| LangGraph Checkpoint | owning Run과 같은 보존 창. resume/recovery가 필요한 동안 선행 삭제 금지 | 예 — owning Run에 종속 | owning Run 삭제와 함께 |
| Command Receipt | 독립 숫자 보존기간 없음. owning Aggregate의 replay/recovery 가능 기간보다 먼저 삭제 금지 | 직접 적용하지 않음 | owning Aggregate purge UoW에서 순서 보장 |
| Audit Log | 90일 고정 | **아니오** | 제품 데이터 삭제 뒤에도 업무 원문 없이 최소 식별·상태만 유지 |
| Sidebar page/batch·opaque Local API continuation·Calendar Month cache | React Client Session Cache, 세션 종료 시 삭제 | 아니오 | 세션 폐기 |
| Agent 검색 중간 후보 | 현재 Run 메모리, Run 종료 시 삭제 | 아니오 | Run 종료 시 폐기 |
| Gmail·Issue 전체 원문 | 영구 저장하지 않음 | 아니오 | 해당 없음 |
| Task·Event 상세 원문 | 기본적으로 영구 저장하지 않음 | 아니오 | 해당 없음 |
| Google Refresh Token | OS Keyring | 아니오 | 연결 해제/Uninstall 정책 |
| Google Access Token | Connector MCP Credential Provider process memory만 | 아니오 | process/session 종료 시 폐기 |
| LLM API Key | `KEYRING` 또는 사용자가 선택한 `SESSION_ONLY` Local Agent process memory | 아니오 | credential delete/session 종료 |

**Purge 보호 규칙:** nonterminal Run, active Confirmation/Reauth/Recovery, replay에 필요한 Command Receipt, 아직 보존 대상인 child를 가진 parent는 retention cutoff가 지났다는 이유만으로 먼저 삭제하지 않는다. Conversation은 retained Message/Run이 모두 정리되고 open Run이 0일 때만 삭제한다. Audit 90일은 `retention_days`로 줄이거나 늘리지 않는다. 정확한 timestamp/cascade/UoW realization은 04가 이 Policy를 그대로 소비한다.

Sidebar page/batch·opaque Local API continuation·Calendar Month cache는 React Client Session Cache에, Agent 검색 중간 후보는 Python Run 메모리에만 유지한다. 외부 업무 자료 목록 전체를 SQLite에 동기화하거나 상시 복제하지 않는다. Activity 이력을 이유로 원문·미사용 후보의 보존 범위를 늘리지 않는다.

## 19. 로그·감사 정책

### 기록

- Run·`langgraph_thread_id`·Action ID
- Node·Tool 이름
- Sanitized Arguments Metadata
- 승인·수정·거절
- 실행·검증 상태
- Provider·모델·fallback
- Latency·Token·오류 코드

### 기록 금지

- 전체 API Key
- OAuth Token
- Authorization Header
- 불필요한 전체 Gmail 원문
- OS·GPU 고유 식별자

## 21. 정책·안전 결과의 의미

| 결과 | 의미 |
| --- | --- |
| ALLOW | 정책상 허용. WRITE의 승인·상태·실행 admission 검증을 대신하지 않음 |
| REQUIRE_APPROVAL | 사용자 승인 필요 |
| REQUIRE_CONFIRMATION | 모호성·경고에 대한 사용자 확인 필요 |
| BLOCK | 정책상 실행 금지 |
| EXPIRED | 승인 또는 Credential 상태 만료 |
| MISMATCH | 실행 결과가 승인 내용과 다름 |

## 22. Source 조회·메모리 캐시 정책

### POL-SRC-001 호출 위치

외부 업무 데이터는 로컬 Connector MCP 경계를 통해 현재 사용자의 유효 credential로 조회한다. Frontend가 Provider credential이나 외부 API를 직접 다루는 우회 경로, 별도의 원격 데이터 동기화 서버는 허용하지 않는다.

### POL-SRC-002 요청 진입 방식

검색형 요청과 사용자가 Resource를 선택한 요청에 같은 접근·개인정보·승인 정책을 적용한다. 화면에 보인 이력이나 선택 label만으로 새로운 계정·Source 접근 권한이 생기지 않는다.

### POL-SRC-003 사이드바 목록

사용자가 허용한 계정·Source·기간·container 범위를 벗어난 조회를 금지한다. Browser가 Provider raw continuation을 생성·해석·수정하지 못하게 한다. 표시 순서·Month View·페이지 크기는 정책에서 중복 정의하지 않는다.

### POL-SRC-004 페이지 메모리 캐시

- 이미 materialize한 Gmail·Tasks page/batch와 opaque Local API continuation, Calendar Month cache만 React Client Session Cache에서 재사용한다.
- Cache identity/invalidation은 02/07의 current contract를 따르며 Provider raw continuation은 Connector/MCP Adapter 내부에 남는다.
- UI 세션 종료, 계정·container·scope·검색·filter·sort 변경 또는 수동 새로고침 시 관련 Cache를 폐기한다.
- Sidebar Cache는 승인·중복·충돌·검증의 기준점이 아니며 SQLite에 영구 저장하지 않는다.

### POL-SRC-005 직접 선택

검증된 선택 identity는 최신 상세 조회의 기준으로 사용하며 다시 검색해 다른 대상으로 바꾸지 않는다. 선택 Resource와 사용자 명시 대상이 모순되면 임의 우선순위로 실행하지 않는다. 추가 Source는 현재 요청과 허용된 범위에 필요한 경우에만 조회한다.

### POL-SRC-006 Agent 검색

Source-native 후보 검색 뒤 필요한 상세만 조회하고 필요한 Context만 모델에 전달한다. semantic hypothesis의 변경과 detail hydration을 구분하되 현재 검색·detail·호출 예산을 모두 지킨다. 기존 재검색 상한을 새 Connector나 back-edge를 이유로 초기화·우회하지 않는다. 동일 검색이나 동일 후보를 새 정보 없이 반복하지 않는다.

### POL-SRC-007 영구 저장 범위

SQLite에는 실제 Run에서 사용된 Resource ID, Source, 원본 링크, 최소 Metadata, Evidence excerpt만 저장할 수 있다. 사용되지 않은 목록 페이지, 검색 중간 후보, Gmail 전체 원문, Task·Event 상세 원문은 영구 저장하지 않는다.

### POL-SRC-008 최신성 기준

- 사이드바 Cache는 탐색과 즉시 표시를 위한 임시 데이터다.
- 선택형 요청 시작 시 선택 Resource의 상세를 다시 조회한다.
- 쓰기 계획 확정 전, 승인 후 실행 직전, 실행 직후에는 관련 Resource를 해당 Connector로 재조회한다.
- 승인·충돌·중복·검증 판단에서 Cache보다 현재의 검증된 Source observation을 우선한다.

### POL-SRC-009 수동 새로고침

사용자가 Source의 새로고침을 실행하면 해당 Source의 materialized Cache와 opaque Local API continuation generation을 폐기하고 current initial scope를 최신 데이터로 다시 조회한다.

## 23. Secure & Resilient 시스템 정책

### 23.1 입력·출력·오류 정책

#### POL-INP-001 중앙 입력 검증

사용자 입력, Connector 응답, LLM Structured Output, Resource ID, opaque Local API continuation, 날짜·시간, 이메일 주소는 해당 typed boundary에서 타입·길이·개수·허용값을 검증한다. Provider raw continuation은 Connector/MCP Adapter 경계에서만 검증한다. UI·Agent·MCP가 서로 다른 검증 규칙을 임의로 가지지 않는다.

#### POL-INP-002 허용 목록 우선

Tool Name, Source, 상태, AI 모드, URL Scheme, 수정 가능 필드는 Allowlist로 검증한다. 검증되지 않은 값은 추정하거나 보정해 실행하지 않고 차단 또는 사용자 확인으로 전환한다.

#### POL-INP-003 안전한 렌더링

Google·사용자·LLM에서 받은 문자열을 React에서 Raw HTML로 실행하지 않는다. Markdown과 Link는 안전한 Renderer를 통과하며 `javascript:`, `data:` 등 실행 가능한 Scheme은 차단한다. OAuth Loopback을 제외한 링크는 기본적으로 `https`만 허용한다.

#### POL-ERR-001 오류 정보 분리

사용자 화면에는 원인, 현재 상태, 데이터 변경 여부, 다음 행동만 표시한다. Stack Trace, SQL, 로컬 파일 경로, Authorization Header, Token, Keyring Entry 이름은 진단 로그에도 Sanitized 형태로만 기록한다.

### 23.2 로컬 실행 경계 정책

#### POL-LOCAL-001 `Localhost` 바인딩

FastAPI Local Agent Service는 `127.0.0.1`의 동적 포트에만 바인딩한다. P0에서 Public IP, LAN 전체 Interface, 원격 Reverse Proxy에 직접 노출하지 않는다.

#### POL-LOCAL-002 요청 위조 보호

운영 빌드는 React UI와 Local API를 같은 Origin에서 제공한다. State-changing API는 JSON Content-Type, Host·Origin, Local Session, Command ID 검증을 요구한다. 임의 Origin Allowlist, Wildcard CORS, 브라우저 Form POST 기반 Command를 허용하지 않는다.

#### POL-LOCAL-003 외부 Endpoint 제한

외부 통신은 등록된 Google/GitHub Provider, 승인 API LLM, 각 인증 Endpoint와 검증된 제품 provisioning 목적지로 제한한다. 사용자·Source 본문의 URL이 임의 서버 Fetch나 shell 실행을 유발하면 안 된다. Frontend는 제품 API를 통해 업무 연결을 사용하고, 인증·접근 관리 링크는 명시적인 사용자 동작으로 연다.

#### POL-LOCAL-004 Local Session 수립

- Launcher는 앱 시작마다 고엔트로피 일회성 Bootstrap Secret을 생성한다.
- Bootstrap Secret은 URL Query, SQLite, 일반 로그에 기록하지 않는다.
- React Frontend는 Bootstrap을 한 번 교환해 Local Session을 수립하고 즉시 폐기한다.
- Session은 앱 Process 수명과 연결되며 재사용·외부 복사를 허용하지 않는다.

#### POL-LOCAL-005 Local API Command 경계

업무 상태 변경은 Application Command 경계에서 검증하고 Domain에 적용한다. Domain Command의 대상 version과 non-Domain 설정/인증 operation의 replay 계약을 혼용하지 않는다. Endpoint 재호출은 동일 명령의 기존 결과 또는 conflict를 반환하며 실행 사실을 중복 적용하지 않는다. 정확한 wire field는 Interface가 소유한다.

#### POL-LOCAL-006 Event Stream

- Run 진행 전달은 SSE를 기본으로 한다.
- Event는 Run·Action ID, Event Type, 상태, 사용자 표시 Payload와 Cursor를 포함할 수 있다.
- OAuth Token, API Key, Authorization Header, 불필요한 Gmail 원문을 포함하지 않는다.
- SSE 연결 단절은 Run 실패로 간주하지 않으며 Snapshot 재조회 또는 Cursor 재구독으로 복구한다.

#### POL-LOCAL-007 Production same-origin

운영 배포에서 FastAPI가 React 정적 산출물과 `/api/v1`을 같은 Origin으로 제공한다. Vite 개발 서버는 개발 환경에서만 사용하며 Local API Proxy와 제한된 개발 Origin 설정을 적용한다.

### 23.2-A Frontend · API 계약 정책

#### POL-APIX-001 Versioned Contract

통신 계약은 version과 호환성을 검증한다. Frontend와 Backend가 서로 다른 shape를 조용히 보정·추측하여 실행하지 않는다. 이 wire/schema version은 문서의 수정일과 다른 개념이며 문서 정리 때문에 제거하지 않는다.

#### POL-APIX-002 오류 정규화

오류는 공통 Interface 계약으로 정규화하고 사용자용 원인·다음 행동과 진단 정보를 구분한다. stack trace·SQL·raw path·secret은 Frontend 응답에 노출하지 않는다.

#### POL-APIX-003 명령과 조회 분리

조회 Endpoint는 Domain 사실을 변경하지 않는다. 상태 변경 Endpoint는 명시적 Command 이름과 대상 Version을 사용하며 GET 요청으로 변경을 수행하지 않는다.

#### POL-APIX-004 Frontend 비신뢰

React Client State, Browser Storage, URL Parameter와 SSE Payload는 Domain 사실의 기준점이 아니다. 승인·실행·검증 여부는 Local Agent Service가 Domain Store에서 다시 확인한다.

#### POL-APIX-005 상태 변경 권위 Metadata

브라우저는 사용자 의도와 낙관적 동시성에 필요한 `command_id`, 대상 ID, `expected_version`, 허용된 사용자 입력만 전달한다. `request_hash`, `approval_id`, Write `idempotency_key`, `source_snapshot`, 승인 주체, `canonical_arguments_hash`, `claim_token`은 Application·Domain이 현재 상태에서 생성·검증하며 Browser 입력을 실행 권위로 신뢰하지 않는다. `request_hash`는 Endpoint별 Versioned Request Schema를 Canonical JSON으로 정규화한 뒤 서버에서 계산한다.

### 23.3 SQLite 동시성·트랜잭션 정책

#### POL-DB-001 Write Coordination

모든 Domain Write는 Repository와 명시적 transaction boundary를 거친다. React Event Handler, FastAPI Route, LangGraph Node, Audit Writer가 각각 독립적으로 SQL을 실행하지 않는다.

#### POL-DB-002 짧은 Transaction

DB Transaction 안에서 외부 Provider API, LLM 또는 MCP 호출을 기다리지 않는다. 실행권 예약만으로 외부 Write를 허용하지 않으며, 현재 승인·무결성·취소 조건을 확인한 실행 admission이 성공으로 영속 확정된 뒤에만 호출한다. 외부 효과와 결과 저장·검증을 하나의 원자 Transaction으로 간주하지 않는다. 구체 Command·transaction 순서는 Domain·Interface의 실행 계약이 소유한다.

#### POL-DB-003 실행권 Claim

실행권은 현재 승인·Plan·Run·Action의 무결성과 동시성 검사를 통과한 단일 Attempt에만 예약한다. 예약 완료와 실제 외부 호출 admission은 구별하며, 하나의 성공한 검사를 나머지 guard 생략의 근거로 사용하지 않는다. 조건부 갱신·원자성의 구체 구현은 Domain/DB 계약을 따른다.

#### POL-DB-004 DB Constraint 우선

참조 무결성, 허용 상태, 식별자의 유일성, 승인·Attempt의 단일성 및 Connector-aware Resource identity를 DB의 최종 방어와 함께 지킨다. UI 잠금이나 LLM의 정상 출력을 무결성 보장으로 대체하지 않는다. Constraint/column 정의를 이 문서에 중복 유지하지 않는다.

#### POL-DB-005 SQLite Connection

모든 연결에 동일한 검증된 무결성·동시성 설정을 적용한다. Repository마다 임의로 Foreign Key 검사를 끄거나 busy/durability 설정을 완화하지 않는다. 값과 적용 방식은 DB·환경 계약을 따른다.

#### POL-DB-006 Busy 처리

`SQLITE_BUSY`는 짧은 대기 후 제한적으로 재시도할 수 있다. 무제한 Retry, Busy Loop, Transaction 전체 재실행은 금지한다. 반복 실패 시 현재 Run을 안전하게 중단하고 사용자에게 DB 잠김 상태를 표시한다.

#### POL-DB-007 외부 시스템과 ACID 가정 금지

SQLite와 외부 Connector Provider API를 하나의 Transaction으로 취급하지 않는다. Connector Write는 Action Saga와 상태 전이로 관리하고 성공한 외부 Resource를 DB 실패 때문에 자동 Rollback하지 않는다.

#### POL-DB-008 정규화와 Snapshot

현재 가변 업무 상태와 승인 당시의 불변 Snapshot을 혼동하지 않는다. 표현 변환·저장 편의를 이유로 승인된 값이나 과거 실행 사실을 덮어쓰지 않는다. Table/JSON 배치는 DB concern이다.

### 23.4 조회·Pagination 정책

#### POL-QRY-001 N+1 방지

제품 조회가 데이터 개수에 비례한 무제한 반복 I/O로 확장되지 않게 한다. 필요한 범위의 bounded/batch 조회를 사용하고, 정확한 query 구조는 persistence owner에서 관리한다.

#### POL-QRY-002 로컬 Cursor Pagination

증가하는 이력 목록은 중복·누락 없는 안정적 페이지 조회를 제공해야 한다. local cursor를 Provider continuation과 혼용하거나 Browser가 임의 생성한 cursor를 검증 없이 신뢰하지 않는다. 구체 정렬·pagination 구현은 Interface/DB가 소유한다.

#### POL-QRY-003 Provider Pagination 분리

Browser는 opaque Local API continuation만 보존·재전송한다. Provider raw continuation은 Connector/MCP Adapter 내부 구현 세부사항이며 SQLite local keyset cursor와 혼용하지 않는다.

#### POL-QRY-004 조회 최적화의 안전 경계

조회 최적화나 추적 편의를 이유로 승인·참조 무결성·보존 정책을 완화하거나 불필요한 데이터를 추가 수집·저장하지 않는다. Column·Index·Query Plan의 선택과 검증은 persistence 구현의 책임이며 정책 규칙으로 중복 정의하지 않는다.

### 23.5 Migration·Backup·복구 정책

#### POL-MIG-001 Schema Version

모든 Migration은 순서가 있는 Version과 적용 결과를 기록한다. 실행 중인 애플리케이션 Schema보다 DB Version이 새롭거나 호환되지 않으면 Write를 차단한다.

#### POL-MIG-002 Migration 전 Backup

파괴적 또는 데이터 변환 Migration 전에는 SQLite Backup API 등 일관된 방식으로 Backup을 생성한다. 실행 중인 DB 파일을 단순 복사하는 방식을 기본 Backup으로 사용하지 않는다.

#### POL-MIG-003 무결성 검사

앱 시작과 Migration 후 빠른 DB 무결성 검사와 Foreign Key 검사를 수행한다. 실패 시 Connector Write와 Domain Write를 차단하고 진단·복구 기능만 허용한다.

#### POL-MIG-004 Restore

Restore는 사용자의 명시적 선택으로 수행한다. 현재 손상 DB를 별도 보존한 뒤 Backup을 복원하고 Schema Version·무결성·Foreign Key 검사를 다시 통과해야 정상 모드로 전환한다.

#### POL-MIG-005 물리 삭제

Conversation·Message와 terminal Run 소유 데이터는 §18의 P0 retention matrix와 사용자 삭제 요청에 따라 실제 삭제한다. `retention_days`는 §18에 명시된 대상에만 적용하고 Audit의 고정 90일·Secret lifecycle·session cache에는 적용하지 않는다. 모든 Table에 일괄 Soft Delete를 적용하지 않으며 Audit에는 업무 원문 없이 필요한 최소 식별·상태 정보만 남긴다.

### 23.6 외부 장애·호출 제한 정책

#### POL-RES-001 Run Budget

각 Run은 Source 페이지·상세 조회·LLM·재검색·Retry·Context·실행 시간에 상한을 둔다. 새 단계·Connector·resume를 핑계로 사용량을 초기화하지 않는다. 남은 유효 근거로 제한된 답변을 만들 수 있어도 미확인 내용을 채우거나 WRITE 필수정보 검사를 우회하지 않는다.

#### POL-RES-002 Retry 제한

재시도는 해당 operation의 전달 확실성과 replay 계약 안에서만 수행한다. 일시 오류가 아닌 Schema·Policy·승인·인증 거절·잘못된 arguments에는 자동 retry하지 않는다. 동일 command replay와 새로운 WRITE 시도를 혼동하지 않으며 새 Write 시도는 기존 재검토·새 승인 계약을 따른다.

#### POL-RES-003 Circuit 상태

등록 Connector, API LLM, Ollama, MCP가 연속 실패하면 Component별 Circuit을 일시적으로 열어 새 호출을 중단한다. Circuit 상태와 재시도 가능 시각을 사용자 진단 화면에 표시한다.

#### POL-RES-004 Degraded Mode

일부 Source의 실패나 조회·LLM 예산 소진 후에도 이미 검증된 근거로 의미 있는 READ 결과를 설명할 수 있으면 확인한 범위의 부분 답변을 허용한다. 요청 시작부터 필수 Connector가 미연결·권한 부족인 경우에는 부분 실행으로 우회하지 않고 연결 전제 정책에 따라 안내 후 종료한다. 접근 실패를 검색 결과 없음으로, 일부 확인을 전체 확인으로 표시하지 않는다.

DB·승인·identity 무결성 실패와 안전한 실행에 필수인 값의 부재를 Degraded Mode로 우회할 수 없다. 사용 가능한 모델이 없을 때 새 의미 판단은 수행하지 않으며, 기존 사실만 표시하는 결정적 종료와 새로운 추론 실행은 구분한다.

### 23.7 공급망·Release 정책

#### POL-SUP-001 Dependency 고정

제품 배포는 Lockfile과 고정 Version을 기준으로 재현 가능해야 한다. 지원 종료 Runtime이나 검증되지 않은 Dependency 자동 업그레이드를 운영 Release에 직접 반영하지 않는다.

#### POL-SUP-002 자동 검사

CI에서 Dependency 취약점, Secret, 금지 파일, License와 테스트 실패를 검사한다. Critical 취약점 또는 Secret 탐지 상태에서는 Release Artifact를 생성하지 않는다.

#### POL-SUP-003 Artifact 무결성

Installer·ZIP·실행 Artifact의 SHA-256을 생성하고 Release Metadata에 기록한다. 배포되는 Test·Production Artifact는 Code Signing·Timestamp·SHA-256 Manifest를 Release Gate로 강제한다.

#### POL-SUP-004 Ollama·모델 고정

LOCAL_CAPABLE Release는 검증된 Ollama Version, Model ID, Model Hash와 Runtime Config를 고정한다. 사용자 환경에서 임의 모델을 제품 기본 모델로 자동 승격하지 않는다.

#### POL-SUP-005 적용 제외

원격 SaaS가 아닌 P0에는 WAF, VPC, Redis 분산 Lock, Kubernetes, ALB, DDoS 완화, 자체 JWT·비밀번호 정책을 적용하지 않는다. 제품 형태가 원격 서비스로 변경되면 별도 Threat Model과 정책을 작성한다.

## 24. Multi-Agent 정책

업무 의미의 해석·분석·계획은 검증된 후보를 만드는 과정이며 승인·권한·외부 실행 사실을 만들지 않는다. LLM은 Tool/계정/대상을 마음대로 재선택하거나 Provider를 직접 호출하지 않는다.

전문 Agent의 Local State는 해당 invocation의 작업 메모리다. 이를 독립 장기 Memory·다른 Run의 승인·권한으로 승격하지 않는다. 자유 Peer-to-Peer 호출과 무제한 Handoff는 금지한다.

Structured Output 실패는 기존 bounded repair 안에서 처리하고, 실패를 정상 결과로 강제 보정하지 않는다. 승인 이후의 업무 값 변경은 LLM 재작성으로 우회하지 않는다. 정확한 역할·노드·상태 topology는 Workflow와 Repository Architecture가 소유한다.

## 25. Agent·Retry 정책

State와 검증된 결과에 따른 결정적 제어를 사용한다. 일반 Retrieval은 승인형 Action이 아니며, 답변만 종료하는 경로가 미확정 Write·Recovery를 숨기면 안 된다. Write 실패 뒤 기존 승인 재사용과 UNKNOWN_RESULT에서 신규 Write는 금지한다.

### POL-EXE-004 Command Receipt

동일 command와 동일 입력의 replay는 이전 결과를 재사용한다. 같은 identity에 다른 입력을 보낸 경우에는 conflict로 차단한다. Domain 변경과 필수 Receipt/Audit는 원자적으로 저장하며 non-Domain operation의 replay는 별도 기존 계약을 따른다. 관측 실패나 응답 유실이 외부 Write 재전송을 유발하면 안 된다.

### POL-EXE-005 MCP 실행 Claim

Write는 현재 승인과 실행 admission에 결합된 유효한 single-use Claim을 요구한다. 다른 Connector·Process·Action·Attempt·Tool·대상 인자에 Claim을 교차 사용할 수 없다. 만료·재사용·binding 불일치는 dispatch 전에 차단하고 Token 원문은 저장·노출하지 않는다. exact signed shape와 검증 순서는 보안·MCP 계약을 따른다.

### POL-OAUTH-008 Credential Provider 소유권

- Google Authorization Code 교환, Refresh Token 저장·갱신·폐기는 MCP Credential Provider가 소유한다.
- Signed P0 authorization-code/refresh-token grant는 `oauth_client_id`와 PKCE/state/loopback contract만 소비한다. `EXPLICIT_DEVELOPMENT`만 MCP-owned `.env.local`에서 optional compatibility credential을 로드해 두 grant에 사용할 수 있다.
- FastAPI와 React에는 계정·Scope·연결 상태 Metadata만 반환한다.
- Refresh Token 원문을 FastAPI Process Memory나 React로 복사하는 구현은 금지한다.

## 26. Clarification·조회 범위·일정 관계 정책

전체 Mailbox·장기간 무제한 원문·모든 Source 일괄 조회처럼 허용 범위를 벗어난 요청은 차단한다. 사용자 확인 없이 요청을 허용 범위로 자동 축소해 실행하지 않는다. 승인된 제한 범위만 수행한 경우에도 원래 요구 전체를 완료했다고 표시하지 않는다. 새 bounded 범위 확대에는 이유와 범위를 제시하고 기존 사용자 확인을 받는다.

허용된 검색으로 해소할 수 있는 별칭·기간·업무 개념은 먼저 확인할 수 있다. 검색 후에도 여러 유효 후보가 남거나 안전한 판단을 막는 모순이 있으면 실제 차이를 제시해 확인한다. 근거 없는 identity·연도·시간대·요일을 생성하지 않는다.

시간 overlap과 업무 conflict는 동일하지 않다. 관련 일정의 포함 관계, 실제 busy conflict, tentative/free, 관계 불명을 구분하며 불명을 안전한 충돌 없음으로 처리하지 않는다.

## 27. 승인 인자·첨부파일 정책

### Claim V2

승인한 업무 인자와 서버가 추가하는 전송용 metadata를 구분한다. 후자는 결정적으로 구성할 수 있지만 승인된 의미·대상·Tool을 바꿀 수 없다. 두 무결성 경계와 실행 admission은 기존 보안·MCP 계약 그대로 적용한다. 문서 수정일 갱신이 Claim wire version 변경을 뜻하지 않는다.

### 첨부파일

- Gmail 수신 첨부파일 다운로드와 Draft/SEND 첨부파일 전달을 허용한다.
- 첨부파일 bytes·내용은 Agent/LLM Context·Evidence·Prompt 입력으로 사용하지 않는다.
- 발신 파일은 raw Local Path를 Action Argument로 신뢰하지 않고 Staging Descriptor와 SHA-256으로 승인한다.
- Staging 파일이 바뀌거나 Hash가 불일치하면 기존 Approval·Claim을 사용할 수 없다.
- 기존 Gmail Message/Thread 삭제 금지 정책은 그대로 유지한다.

### External LLM prior-consent exact rule

API_LLM과 AUTO의 외부 fallback은 같은 저장된 동의 guard를 따른다. 전송 scope는 실제 입력의 최소 Source/data-class를 기준으로 호출 전에 server projection에 게시한다. Scope가 달라지면 다음 외부 호출 전에 갱신한다. Browser paint ACK나 추가 버튼을 새로운 동의 authority로 만들지 않는다. Exact wire/publish 순서는 기존 보안·Interface 계약을 따른다.

## 28. GitHub 계정·저장소·Issue 정책

### POL-GH-001 계정 인증과 저장소 권한

계정 인증 성공과 App 설치·저장소 접근 허용은 별개다. 현재 사용자와 App이 모두 접근 가능한 범위만 사용한다. 초기 사용 전제가 충족되지 않은 요청은 공통 Connector 전제 정책으로 종료하며 GitHub 전용 인증 대기·설치 감시 workflow를 추가하지 않는다. 권한 부족·미설치·미연결은 Issue 없음과 구분한다. Client ID는 제품 개발·배포 구성이고, 일반 사용자에게 PAT·client secret 입력을 요구해 제품 인증을 우회하지 않는다.

### POL-GH-002 기본 저장소의 효력

기본 저장소는 사용자가 명시적으로 정한 편의 설정이다. 접근 권한·Write 승인·현재 선택 Resource의 identity를 대신하지 않는다. 현재 요청의 명시 저장소와 selected Issue가 모순되면 임의 우선순위를 적용하지 않는다. 기본값은 명시 대상이 없을 때만 검증 후 사용한다.

### POL-GH-003 Run 대상 고정

유효한 저장소 선택의 출처와 현재 Run 대상 binding을 구분하여 보존한다. 설정 변경은 이미 시작되거나 승인된 Run을 다른 저장소로 옮기지 않는다. 계정 변경·접근 철회·삭제·이름 변경 이후 기존 기본값을 무조건 신뢰하거나 다른 저장소로 silent fallback하지 않는다.

### POL-GH-004 기존 Issue 무결성

기존 Issue mutation은 현재 persisted target과 repository identity가 일치해야 한다. 불일치를 Provider probing으로 해결하지 않으며 사전 검증에서 차단한다. Issue와 PR을 혼동하거나 같은 issue number만으로 다른 repository의 대상을 연결하지 않는다.

### POL-GH-005 공통 실행 안전

Issue 생성·수정·닫기·다시 열기는 기존 공통 승인·Claim·실행·검증·복구 경계를 따른다. GitHub를 이유로 별도 느슨한 승인 경로를 두지 않는다. 실제 결과를 다시 조회하지 않고 완료를 확정하거나 불확실한 생성 요청을 재전송하지 않는다.

### POL-GH-006 연결 격리

GitHub 연결 실패·해제·재인증은 다른 Connector의 credential과 정상 요청을 훼손하지 않는다. Google credential을 GitHub에 사용하거나 반대로 fallback하지 않는다. 해당 Run이 실제로 필요로 하는 연결의 문제를 정확히 표시한다.

## 29. 사용자 표시의 신뢰 경계

### POL-DSP-001 확인된 사실만 표시

사용자에게 제시하는 설명·작업 내역·최종 답변은 이미 검증된 상태·결과·근거에 한정한다. 계획·후보·dispatch 응답·Verification 완료를 동일한 성공으로 취급하지 않는다. 이후 결과를 이전 시점의 판단 사실처럼 소급 표시하지 않는다.

### POL-DSP-002 표시의 비권위성

Activity와 SSE는 업무·권한·승인·성공의 authority가 아니다. 화면 클릭·펼침·이력 복원은 새로운 업무 실행이나 외부 조회를 유발하지 않으며, 설명을 만들기 위한 추가 LLM 호출도 수행하지 않는다. 필요한 저장된 정보의 Local API 조회는 가능하다.

### POL-DSP-003 최소 노출과 보존

작업 설명을 이유로 raw Prompt/Completion, hidden reasoning, credential, Claim, Provider 원문 전체를 노출하거나 새로 장기 보존하지 않는다. 표시할 근거가 없거나 보존 기간이 지나면 생략·제한을 알리며 과거 이력을 생성하지 않는다.
