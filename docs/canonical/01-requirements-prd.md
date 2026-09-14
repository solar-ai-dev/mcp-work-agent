# 01. Requirements PRD

**목적:** 데스크톱 Work Agent의 제품 목표, 범위, 사용자 가치와 상위 요구를 정의한다.

**Authority:** 제품 범위와 상위 제품 요구

**상태:** CANONICAL

**수정일:** 2026-09-07

## 1. Product statement

사용자는 한 Conversation 안에서 자연어로 Google Workspace와 GitHub 업무를 조회하고, 계획을 검토·수정·승인한 뒤 안전하게 실행한다. 제품은 실제 근거와 실행 결과를 설명하고, 재연결·재시작·응답 손실에서도 중복 외부 효과를 만들지 않는다.

제품은 Windows 데스크톱 UI, loopback Local API, Python Application/Domain, LangGraph orchestration, connector-neutral MCP/Port 경계로 구성된다. Google은 필수 로그인이 아니라 Connector 하나이며 GitHub, Gemini credential, Local AI와 독립이다.

## 2. Core availability

Core가 정상이면 Google/GitHub/Gemini/Local AI 준비 여부와 무관하게 Main UI, Settings, 기존 Conversation·Run 이력 조회가 가능해야 한다. 필요한 capability가 없는 새 요청만 업무 처리를 시작하지 않고 연결·설정 안내 후 현재 요청을 종료한다. 이를 durable auth-wait Run, 초기 `REAUTH_REQUIRED`, OAuth callback 자동 resume로 만들지 않는다.

정상 실행 중 credential 만료는 기존 same-Run Reauth·Recovery 계약을 따른다. OAuth 성공만으로 재개하지 않고 `ResumeAfterReauth`가 적용된 뒤에만 workflow를 재개한다.

## 3. Settings

Settings는 일반 데스크톱 앱처럼 compact한 현재 상태와 값을 보여주고, 변경에 필요한 상세만 펼친다. 큰 카드·온보딩 체크리스트 중심 화면이나 arbitrary Resource ID/model/server 입력 화면으로 확장하지 않는다.

Google, GitHub, Gemini, Local AI, 일반 설정, 진단을 구분한다. 사용자 조작은 체크/해제, 단일 선택, 목록 선택 중심이며 연결·해제·검사·저장과 Gemini API Key처럼 필요한 입력은 유지한다.

Calendar, Google Task List, GitHub Repository 선택은 기본 Resource 하나가 아니라 복수 접근 allowlist다. Provider permission과 Settings allowlist를 모두 만족해야 하며 Browse, Retrieval, READ, WRITE 모두 범위 밖 업무 데이터에 접근하지 않는다. 빈 선택은 전체 허용이나 임의 default가 아니다. Run의 명시 Resource 선택은 allowlist 안에서만 범위를 좁힌다. 복수 allowlist를 단일 WRITE target으로 해석하지 않는다.

Settings 변경은 시작되거나 승인된 Run의 target을 바꾸지 않는다. container/repository inventory 조회와 선택된 범위의 업무 데이터 조회를 구분한다.

## 4. AI runtime

사용자는 실행 방식을 `Local AI` 또는 `Gemini` 중 하나로 선택한다. 사용자용 `AUTO` 모드와 Local↔Gemini 자동 fallback은 없다. 외부 추론은 credential·consent·전송 범위 계약을 따르며 Local-only 사용에는 외부 LLM 전송 동의를 요구하지 않는다.

지원 Local 모델은 정확히 다음 두 개다.

- `qwen3.5:9b`
- `qwen3.5:4b`

앱 시작과 Settings 재검사에서 실제 Ollama 상태와 설치된 지원 모델을 검사한다. 지원 모델이 하나면 그 모델을 자동 사용한다. 이전 선택 모델이 없어지고 다른 지원 모델 하나만 남은 경우 별도 확인 없이 사용 가능한 모델로 전환하고 UI와 Runtime 상태에 실제 선택을 반영한다. 둘 다 설치되어 유효한 기존 선택이 있으면 유지하며, 둘 다 있는데 유효한 선택이 없으면 사용자가 고른다. 검사 실패와 지원 모델 미설치를 다른 상태로 표현한다.

이 가용성 선택은 역할별 4B/9B switching, inference 실패마다 model 교대, 지원 외 모델 선택, Local→Gemini fallback을 허용하지 않는다. 진행 중 Run의 모델 binding, checkpoint, approval을 재검사 결과로 바꾸지 않는다. 과거 Run의 `AUTO` history를 다시 쓰지 않는다.

제품은 Ollama 설치, model pull, 자동 download/provisioning, 설치 Wizard, 사용자 동의 없는 모델 설치·삭제를 수행하지 않는다. 모델이 없으면 간단히 안내하며 Core 진입을 막지 않는다.

## 5. Conversation and time

제품 timezone은 `Asia/Seoul`로 고정한다. 상대 날짜, 일정 계산, 제품 시간 표시는 대한민국 기준이며 사용자가 timezone을 바꾸지 않는다. Working hours는 별도 설정이고 timezone과 혼동하지 않는다. UTC 저장과 Provider 표현은 각 boundary 계약을 유지한다.

한 Conversation에 여러 Run을 순차적으로 둘 수 있다. 새 사용자 요청은 새 Run이며 과거 Run의 Message·Activity는 화면 이력으로 남는다. 이전 Run의 Message/Evidence/Plan/Approval을 새 Run의 숨은 LLM memory로 자동 주입하지 않는다. 같은 Run의 Confirmation/Reauth/Recovery와 checkpoint 복구는 기존 resume 계약을 따른다. 화면 이력 복원과 workflow resume는 다른 동작이다.

## 6. Retrieval and reasoning

Retrieval은 literal keyword 검색 한 번으로 끝내지 않는다. 사람, 기간, 업무 개념, 프로젝트, sender/recipient/body 역할을 구분하고 사용자의 exact title/email/resource anchor를 보존한다. 사용자가 말한 업무 개념은 요구이고 Agent가 만든 확장어·검색 전략은 검증할 가설이다.

첫 결과를 관측한 뒤 bounded 다른 Query, next page, detail fetch를 선택한다. 같은 Query의 무진전 반복을 금지하고 정상 0건, 자료 부족, Provider failure, partial을 구분한다. 후보와 확정 identity, 수신시각/행사일/마감일/집계 기간, 최신 정정·취소와 과거 제안을 구분한다. 최종 답변은 실제 Evidence와 coverage에 맞춘다.

조회로 해소할 수 있는 모호성은 bounded 검색을 먼저 수행하고 실제 복수 후보가 남으면 Confirmation을 사용한다. 안전한 실행에 필요한 사용자 결정이 누락된 경우의 Confirmation은 유지한다.

키워드·정규식으로 자연어 의미를 확정하거나 LLM 판단을 조용히 덮어쓰지 않는다. 일반 코드는 형식, 명시 identity, allowlist, 승인, 상태, 실행 안전과 이미 검증된 사실의 결정적 처리를 담당한다.

## 7. Workflow and Activity

Supervisor는 typed State, fresh validated artifact, durable execution fact와 safety obligation으로 다음 책임을 고른다. 불필요한 Retrieval/Analysis를 skip할 수 있고, 근거 부족은 bounded Retrieval back-edge, route 문제는 Tool Route reconsideration으로 보낸다. Approval, in-flight execution, `UNKNOWN_RESULT`, Verification, Recovery, Reauth, Cancel 의무가 일반 진행보다 우선한다. stale artifact와 무진전 반복을 허용하지 않는다.

현재 conditional edge 구조를 유지하며 새 Supervisor LLM이나 자유 연결 Graph를 요구하지 않는다. Agent 책임 전체 skip과 Agent 내부 LLM 호출 생략을 구분한다.

UI Activity의 parent는 함수 호출이 아니라 실제 semantic Agent execution이다. child는 그 execution에서 실제 완료된 의미 있는 사실을 시간순으로 누적한다. 진행 중 상태와 완료 사실을 구분하고, 발생하지 않은 순서를 최종 State에서 추측 생성하지 않는다. Approval/Write/Verification/Recovery를 특정 Agent에 허위 귀속하지 않으며 Frontend는 backend owner·identity·order를 소비한다.

Agent 종료 뒤 기록을 보존하고 back-edge는 새 execution round, interrupt/resume은 같은 execution identity로 잇는다. 같은 fact replay는 dedupe하되 다른 round/result는 문구가 같아도 합치지 않는다. Activity는 새 Run의 hidden memory가 아니며 별도 LLM, Summary Agent, 두 번째 Event Store, raw Prompt/completion/reasoning/GraphState/Provider payload 저장을 만들지 않는다.

## 8. Reads, writes, and connectors

Google/GitHub READ는 승인형 WRITE lifecycle에 넣지 않는다. 모든 외부 WRITE는 Preview와 Approval Snapshot의 의미·target이 일치한 뒤 Claim, committed BeginExecutionAttempt, connector dispatch, effect-specific reread Verification을 거친다. 승인 전 WRITE는 0이고 승인된 Action의 exact dispatch는 정상 경로에서 1회다. 여러 Action인 Run 전체를 1회로 제한하는 뜻은 아니다.

Provider 응답만으로 성공을 확정하지 않는다. response loss/reconnect/restart/retry가 duplicate effect를 만들지 않아야 하며 `UNKNOWN_RESULT` 중 blind resend나 새 Attempt를 만들지 않는다. 승인 뒤 값이나 target이 달라지면 승인을 재사용하지 않는다. 최종 Assistant Message는 실제 결과, 부분 성공, 미실행, 실패, 결과 불명확을 자연어로 구분한다.

GitHub는 connector-neutral 구조의 두 번째 Connector다. Device Flow, account/repository 접근 확인, GitHub App permission과 Settings allowlist 교집합을 사용한다. Issue READ는 list/get, CREATE/UPDATE/CLOSE/REOPEN은 기존 승인형 write path를 사용한다.

Gmail Draft 생성·수정, 새 SEND, 기존 Thread Reply를 구분한다. Reply는 thread identity를 유지하고 전송 결과를 재조회한다. Task는 필요한 중복 검사, Calendar는 Event/FreeBusy 충돌 검사를 수행한다. Preview 수정과 이미 존재하는 Provider Resource UPDATE를 구분한다.

## 9. Non-functional requirements

- credential과 secret은 OS Keyring 등 owning security boundary에 저장한다.
- Domain Store, checkpoint, UI/SSE/Trace projection의 권위를 분리한다.
- external I/O 중 SQLite write transaction을 유지하지 않는다.
- Domain/Application/Port/Adapter/API/Frontend/LangGraph 책임과 single production authority를 지킨다.
- 구조·안전 regression, type/lint, 직접 영향 테스트와 적합한 실제 제품 검증을 구분해 수행한다.
- 구현·검증 완료 여부는 Issue 상태나 문서 존재가 아니라 production caller와 현재 근거로 판정한다.

## 10. Out of scope

- arbitrary provider/model/server configuration UI
- 사용자 timezone 선택
- 자동 Ollama/model 설치·pull·provisioning
- Local/Gemini 자동 fallback 또는 역할별 Local model switching
- GitHub 전용 Graph/Port/Main State/workflow authority
- raw 업무 원문 전체 상시 복제, hidden reasoning 저장, Activity 전용 summary system
- 문서 계약만으로 미완료 capability를 완료로 간주하는 것
