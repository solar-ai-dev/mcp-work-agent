# 09. Security · Authentication

**목적:** Local API, Connector credential, external LLM consent, untrusted input, write execution의 보안 경계를 정의한다.

**Authority:** credential lifecycle, consent, trust boundary, secret handling, local session security

**상태:** CANONICAL

**수정일:** 2026-09-07

## 1. Trust boundaries

```text
User
→ React Frontend
→ FastAPI protocol boundary
→ Application / Domain / Policy
→ abstract Port
→ concrete Adapter / Connector MCP child
→ external Provider
```

React, FastAPI Route, LangGraph Node, Agent/LLM은 concrete Provider SDK/API, Keyring, SQLite, Connector runtime을 직접 호출하지 않는다.

Connector Source, LLM output, MCP response는 비신뢰 입력이다. Domain Store가 approval/execution/verification fact의 권위이며 checkpoint와 UI/SSE/Trace는 별도 resume/projection authority다.

## 2. Local API

| 항목 | 보안 규칙 |
| --- | --- |
| Bind | `127.0.0.1` dynamic port만 사용한다. LAN/public bind와 wildcard CORS는 금지한다. |
| Origin | 운영 UI와 `/api/v1`은 same-origin이다. |
| Bootstrap 전달 | Launcher가 high-entropy one-time Bootstrap Secret을 URL fragment로 전달한다. |
| Session 발급 | bootstrap 성공 후 `HttpOnly`, `SameSite=Strict`, host-only Local Session cookie를 발급한다. |
| Bootstrap 폐기 | fragment를 제거하고 secret을 폐기한다. query string, browser storage, SQLite, log 저장은 금지한다. |
| 변경 요청 | Host/Origin/Fetch Metadata, JSON Content-Type, Local Session, versioned request, command identity를 검증한다. |
| Read API | Local Session을 검증한다. |

Browser는 run/message/workflow ID, approval/claim hash, idempotency key, source snapshot 같은 authority 값을 생성하지 않는다. Server/Application/Domain이 current state에서 생성하고 expected version과 receipt를 검증한다.

Resource selection handle은 service instance, session, connector/account/resource identity, expiry에 결속된 opaque 값이다. Browser는 내부 identity를 해석하거나 수정하지 않는다.

## 3. Connector credentials

Google과 GitHub credential은 서로 독립이며 Gemini API key와도 분리한다. 하나를 연결·해제·만료해도 다른 credential을 삭제하거나 실패 상태로 만들지 않는다.

Connector OAuth/token/keyring lifecycle은 해당 Connector credential Adapter가 소유한다. Access/refresh token, device token, API key 원문을 React, SQLite, checkpoint, Trace, Audit, diagnostic payload, process argument에 노출하지 않는다.

### Google

| 항목 | 규칙 |
| --- | --- |
| 인증 방식 | Installed/Desktop OAuth는 Authorization Code + PKCE S256, state, ephemeral loopback callback을 사용한다. |
| Client identity | Production은 signed build configuration의 non-secret client identity만 사용한다. 일반 사용자에게 client ID/secret을 입력받지 않는다. |
| Scope | 필요한 Google scope와 Limited Use 조건을 지킨다. scope 일부가 거절되면 해당 capability 미준비로 표시한다. |

### GitHub

GitHub는 Device Flow를 사용한다. Provider가 반환한 user code, verification URL, interval, expiry와 `PENDING | SLOW_DOWN | APPROVED | EXPIRED | DENIED`를 정확히 처리한다. PAT/client secret 입력을 일반 Settings에 추가하지 않는다.

Repository 사용 가능 상태는 GitHub App installation access, user permission, Settings allowlist의 교집합이다. 연결 성공과 repository 사용 가능을 구분한다. allowlist 선택은 Provider permission을 확대하지 않는다.

## 4. OAuth and Run binding

| 상황 | 처리 경계 |
| --- | --- |
| OAuth/Device Flow callback success | connector credential state이며 Run-neutral이다. callback은 `run_id`를 운반하거나 suspended workflow를 자동 resume하지 않는다. |
| 정상 실행 중 credential 만료 | authenticated resume command가 `ResumeAfterReauth(applied=true)`와 durable handoff를 만든 뒤에만 same-Run workflow를 재개한다. |
| 이미 dispatch된 WRITE | Reauth 때문에 재전송하지 않는다. |
| `UNKNOWN_RESULT` 또는 Verification mismatch | 기존 Verification/Recovery를 우선한다. |
| 초기 미연결 | Run을 durable Reauth wait로 만들지 않는다. 필요한 요청을 중단하고 설정 안내 후 종료하며 연결 뒤 사용자가 새 요청을 보낸다. |

## 5. AI credentials and consent

Gemini API key는 OS Keyring 또는 명시된 session-only memory에 저장한다. Key 존재/검증 상태만 UI에 반환하고 원문은 다시 표시하지 않는다.

| 항목 | 외부 전송 규칙 |
| --- | --- |
| Gemini 호출 조건 | current external LLM consent와 호출 전 게시된 최소 transfer scope를 모두 요구한다. |
| 게시할 scope | 현재 Run의 typed input에서 source kind/data class로 계산한다. raw source text나 secret을 포함하지 않는다. |
| Scope 변경 | 다음 호출 전에 새 hash/revision을 게시한다. |
| Consent authority | Browser paint/ACK, API key 존재, 과거 동의를 추론해 consent authority로 사용하지 않는다. |

Local-only 사용에는 external consent를 요구하지 않는다. Local과 Gemini 사이 자동 fallback은 없으므로 Local 실패를 근거로 외부 전송하지 않는다.

과거 Conversation의 Message, Evidence, Plan, Approval을 새 Run의 외부 LLM context로 자동 전달하지 않는다. 같은 Run의 Confirmation resume도 originating owner에 필요한 bounded response만 전달한다.

## 6. Local AI boundary

제품은 실제 Ollama와 설치된 `qwen3.5:9b | qwen3.5:4b` 상태만 검사한다.

| 구분 | 규칙 |
| --- | --- |
| 허용 | 지원 모델 하나만 있을 때 가용성을 자동 선택할 수 있다. |
| 설치·관리 금지 | Ollama/model install, pull, download/provisioning, update, delete, arbitrary endpoint/model 입력을 수행하지 않는다. |
| 실행 authority 금지 | Prompt, Connector Source, Browser가 URL/path/model tag/shell argument를 실행 authority로 만들 수 없다. |
| 전환·binding 변경 금지 | 역할별 switching, inference 실패 model 교대, Local→Gemini 자동 전환, 진행 중 Run binding 변경은 금지한다. |

## 7. Resource authorization

Calendar, Task List, GitHub Repository는 account/immutable identity에 결속된 복수 Settings allowlist다.

| 항목 | 권한 규칙 |
| --- | --- |
| 업무 I/O | Browse/Retrieval/READ/WRITE/Verification/Recovery read 모두 Provider permission과 allowlist를 만족해야 한다. |
| 빈 선택 | 전체 허용이 아니다. |
| Settings용 container inventory | 접근 가능한 선택 후보를 조회하는 별도 read다. 업무 데이터 read/write 권한으로 재사용하지 않는다. |
| Run의 explicit resource | allowlist 안에서만 좁힌다. 여러 허용 항목 중 첫 번째를 WRITE target으로 고르지 않는다. |
| 접근 철회 | 이후 새 I/O는 차단한다. |
| 이미 dispatch된 외부 effect | 지우거나 다른 target으로 대체하지 않고 기존 Verification/Recovery 경계로 정리한다. |

## 8. Untrusted content and semantic decisions

Connector Source는 항상 `UNTRUSTED_SOURCE_CONTENT`/data-only다. 본문 속 시스템 지시, credential 요구, approval bypass, tool invocation을 RequestIntent, Route, Approval, Domain Command로 승격하지 않는다.

키워드·정규식은 ID/email/JSON 형식, 명시 identity, allowlist, state, approval, date transform 같은 결정적 검증에 사용할 수 있다. 자연어 intent, 사람 역할, 날짜 의미, 업무 결론을 특정 문자열만으로 확정하거나 Agent 결과를 조용히 덮어쓰지 않는다.

## 9. Write security

모든 외부 WRITE는 다음 경계를 지킨다.

```text
validated tool/resource/effect
→ policy and confirmation
→ immutable Approval Snapshot
→ Claim and execution arguments integrity
→ BeginExecutionAttempt commit
→ exactly one connector dispatch for the Action attempt
→ provider reread Verification
→ Recovery when unknown/mismatch
```

| 상황 | 금지·처리 규칙 |
| --- | --- |
| Approval 전 | dispatch 0 |
| snapshot/arguments/target mismatch | dispatch 0 |
| response loss, reconnect, restart, retry | duplicate effect를 만들지 않는다. |
| `UNKNOWN_RESULT` | 새 Attempt/blind resend를 금지한다. |
| Cancel intent 뒤 | 새 Claim/WRITE를 만들지 않는다. in-flight effect는 Verification/Recovery로 정리한다. |

## 10. Data minimization

전체 mailbox/repository나 미사용 검색 후보를 SQLite에 상시 복제하지 않는다. 목적에 필요한 Message, ResourceRef, bounded Evidence, Plan, Approval, execution/verification/recovery fact, required Audit만 저장한다.

Raw Prompt/completion/hidden reasoning, OAuth token/API key/Claim token, Provider payload, arbitrary local path를 Activity/Trace/Audit/diagnostic에 저장하지 않는다.

Secret redaction 실패는 logging failure로 처리하며 plaintext fallback하지 않는다.

## 11. Supply chain and release

Production Installer/executable, release manifest와 runtime-consumed Prompt/Tool/Connector artifacts는 signature/hash 검증을 통과해야 한다. API/wire/checkpoint/manifest/migration version은 문서 version과 구분한다. 검증 실패를 compatibility fallback이나 unsigned environment source로 우회하지 않는다.

Uninstall은 Connector/Gemini credential을 기본 삭제하고 DB/backup은 별도 사용자 선택과 경고를 따른다. shared Ollama나 사용자 모델을 제품 소유로 간주해 삭제하지 않는다.
