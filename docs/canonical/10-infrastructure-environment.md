# 10. Infrastructure · Environment

**목적:** Windows 데스크톱 제품의 process, startup, packaging, configuration, release, migration, backup, recovery 환경을 정의한다.

**Authority:** runtime topology, startup/readiness, installed paths, configuration source, release/signing, operational persistence

**상태:** CANONICAL

**수정일:** 2026-09-07

## 1. Supported environment

- Windows 11 x64 사용자별 설치
- 최신 Chrome 또는 Microsoft Edge
- `127.0.0.1` loopback only
- Launcher가 FastAPI Local Agent Service를 소유하고 Service가 Connector별 MCP child process를 관리
- 운영 React UI와 `/api/v1`은 같은 Origin
- SQLite Domain Store와 LangGraph checkpoint store는 별도 authority

제품은 local single-user application이며 원격 product backend를 요구하지 않는다. 인터넷은 사용하는 Connector, Gemini, 인증 endpoint에만 필요하다.

## 2. Process topology

```text
Launcher
├─ FastAPI Local Agent Service
│  ├─ React static UI / REST / SSE
│  ├─ Application / Domain / LangGraph
│  ├─ SQLite Domain Store / Checkpoint Store
│  └─ ConnectorRuntimeRegistry
│     ├─ Google Workspace MCP child
│     └─ GitHub MCP child
└─ system browser

Optional external runtimes
├─ Ollama on loopback
└─ Gemini API
```

Google, GitHub, Gemini, Ollama는 독립된 optional capability다. 이 중 하나가 준비되지 않아도 Core readiness가 성립하면 Main UI, Settings, 기존 Conversation·Run 이력 조회가 가능하다.

## 3. Startup and readiness

Startup 순서는 다음과 같다.

```text
installed release/signature/hash verification
→ user data directory/ACL and single-instance lock
→ SQLite open + migration/checksum + integrity
→ checkpoint compatibility
→ Local API bootstrap/session setup
→ configured Connector MCP children and schema handshake
→ configured LLM adapters/status inspection
→ bounded orphan execution reconciliation
→ bounded workflow handoff redrive
→ live handoff reconciliation loop start
→ READY
```

| 상황 | 처리 |
| --- | --- |
| Connector/LLM readiness 실패 | 해당 capability 상태로 투영하며 Core를 불필요하게 Safe Mode로 보내지 않는다. |
| Core 안전성 문제 | DB integrity, migration, required runtime artifact 검증 등 Core 자체가 안전하지 않은 경우에만 Safe Mode를 사용한다. |

요청의 초기 미연결과 실행 중 만료는 구분한다.

- **초기 미연결:** 요청 처리 전 readiness에서 중단하고 설정 안내 후 terminal 처리한다. durable auth-wait Run, 초기 `REAUTH_REQUIRED`, OAuth callback auto-resume를 만들지 않는다.
- **실행 중 credential 만료:** 04-A/06의 same-Run Reauth 계약을 사용한다.

## 4. Local AI inspection

Local Runtime은 외부 Ollama process다. 제품은 Ollama 설치, 시작, 종료, update, uninstall, model pull, download/provisioning을 수행하지 않는다.

지원 모델은 정확히 다음 두 개다.

- `qwen3.5:9b`
- `qwen3.5:4b`

앱 시작과 Settings 재검사는 실제 Ollama probe와 설치 모델 목록을 읽는다. 검사 결과 규칙은 다음과 같다.

Local readiness는 기존 GPU profile 또는 CPU profile 중 하나가 통과하면 충족한다. CPU profile은 지원 OS·architecture, CPU·RAM 기준, Ollama availability와 선택 모델의 설치·승인을 요구한다. GPU 부재·VRAM 부족은 CPU profile이 통과한 경우 blocking reason이 아니다.

| 검사 결과 | 선택 |
| --- | --- |
| 9B만 설치 | 9B 자동 사용 |
| 4B만 설치 | 4B 자동 사용; 이전 선택이 9B여도 별도 확인 없음 |
| 둘 다 설치 + 유효한 persisted 선택 | 기존 선택 유지 |
| 둘 다 설치 + 유효한 선택 없음 | 사용자 단일 선택 필요 |
| 지원 모델 없음 | Local unavailable 안내 |
| 검사 자체 실패 | inspection failure로 표시; 모델 없음으로 축약 금지 |

재검사는 **다음 새 Run의 선택**에 반영하며 진행 중 Run의 model/checkpoint/approval binding을 바꾸지 않는다. 상태 projection은 current selected model과 actual model을 일치시킨다.

다음 동작은 금지한다.

- WORKER/REASONING 역할별 switching
- inference 실패 model 교대
- 지원 외 모델 사용
- Local↔Gemini 자동 fallback

## 5. AI runtime selection

사용자 선택은 `LOCAL_GPU`(Local AI) 또는 `API_LLM`(Gemini)다. 사용자용 `AUTO`는 없다.

| 실행 조건 | 규칙 |
| --- | --- |
| 선택 runtime이 준비되지 않음 | 해당 새 요청만 처리하지 않고 안내한다. |
| Gemini 호출 | current credential, external LLM consent, 호출 전 published transfer scope를 모두 요구한다. |
| Local-only 실행 | external consent가 필요하지 않다. |

과거 Run의 legacy `AUTO` 값은 history/resume compatibility를 위해 읽을 수 있다. 새 사용자 선택으로 생성하지 않고 DB history를 재작성하지 않는다.

## 6. Settings configuration

Non-secret settings는 versioned JSON으로 검증한다. 현재 제품 의미는 다음 concern을 포함한다.

```text
selected_calendar_ids
selected_tasklist_ids
selected_github_repositories
google_resource_account_id
preferred_llm_mode            # LOCAL_GPU | API_LLM for new selections
preferred_local_model_id      # qwen3.5:9b | qwen3.5:4b when available
external_llm_consent
retention_days
theme
panel_preferences
working_day_start_local
working_day_end_local
include_weekends
calendar_buffer_minutes
bounded run/retry/circuit budgets
```

| 선택 설정 | 의미 |
| --- | --- |
| `selected_*` | account/immutable identity에 결속된 복수 allowlist다. |
| Partial update에서 필드 누락 | 변경 없음. |
| 빈 배열 | 명시적 미선택. |
| 권한·조회 범위 | Provider permission을 확대하지 않는다. inventory 조회와 업무 데이터 조회를 구분한다. |
| Legacy 단일 default field | 기존 file/Run 호환을 위해 읽을 수 있으나 active allowlist나 WRITE target authority가 아니다. |

- **Timezone:** `Asia/Seoul` 고정이며 사용자 입력 field가 아니다.
- **Working hours·calendar buffer:** 별도 설정이다.
- **보존 기간:** `retention_days`의 현재 허용 범위와 category별 적용은 01-B/04가 소유한다.

Unknown key, invalid identity, unsupported model/mode는 추측 보정하지 않고 migration 또는 validation error로 처리한다. Secret은 Settings에 저장하지 않는다.

## 7. Configuration and secrets

Production configuration precedence는 runtime-overridable field에만 적용한다.

```text
Launcher runtime argument
→ verified Signed Build Config
→ User Settings
→ Product default
```

Release identity/version/OAuth client identity처럼 signed-locked field는 ambient environment나 user Settings로 override하지 않는다. 개발·CI에서만 명시적 development configuration source를 허용한다.

Google/GitHub credential과 Gemini API Key는 각 credential owner의 OS Keyring 또는 허용된 session memory에 둔다. Bootstrap Secret, Local Session, OAuth token, API Key는 SQLite, settings JSON, release manifest, command line, log에 저장하지 않는다.

MCP child에는 connector가 필요한 non-secret config만 allowlist로 주입한다. parent environment, 다른 Connector credential, Gemini key, bootstrap/session secret을 전달하지 않는다.

## 8. Directories and ACL

Program files, user data, logs, backup, temporary staging을 분리한다. 사용자 데이터와 secret namespace는 현재 Windows 사용자만 접근하도록 설정한다. Browser나 요청 payload로 raw local path를 선택하게 하지 않는다.

Temporary 파일은 bounded product-owned staging 아래 두고 crash/restart 시 identity와 owner를 확인한 뒤 정리한다. broad directory delete, shared runtime directory mutation, arbitrary path traversal을 금지한다.

## 9. Packaging and release

| 항목 | 조건 |
| --- | --- |
| 배포 형태 | one-folder application bundle과 사용자별 Windows Installer를 사용한다. |
| 서명 | Production Installer와 executable은 code signing과 timestamp를 요구한다. |
| 설치 파일 검증 | `release-manifest.json`과 signature가 installed files의 size/hash를 인증하며 Launcher는 내장 public key로 검증한다. |

Runtime Prompt bundle, Prompt input contract, Connector manifest, signed Tool registry/projection, API/schema compatibility artifact는 release hash chain에 포함한다. 각 artifact의 schema/version/hash는 실행 계약이며 문서 버전과 다르다.

| Installer 구성 | 범위 |
| --- | --- |
| 포함 가능 | Python runtime, React build, Product code와 필요한 connector runtime |
| 포함 금지 | Ollama executable, Local model weight, evaluation runner/result, unapproved candidate |

앱 또한 설치 뒤 위 포함 금지 항목을 내려받지 않는다.

## 10. Database migration

| 단계·상황 | 규칙 |
| --- | --- |
| Migration 적용 | 적용 순서, version, checksum을 검증한 뒤 SQLite에 적용한다. |
| 이미 적용된 migration | 수정·재번호·이동·squash하지 않는다. |
| Schema change | forward migration만 추가한다. |
| Upgrade 전 | backup을 만든다. |
| Migration 실패 | 새 binary 시작을 중단한다. |

DB를 새로 생성해 실패를 숨기거나 applied checksum mismatch를 무시하지 않는다. Domain Store migration과 checkpoint compatibility는 별도로 판정한다.

## 11. Backup and restore

| 단계·상황 | 규칙 |
| --- | --- |
| Backup 생성 | SQLite online backup 등 일관된 snapshot mechanism을 사용한다. backup metadata에 schema/version/integrity를 기록한다. |
| Restore 대상 | raw path input이나 임의 파일을 받지 않는다. |
| Restore 전 | 현재 DB를 보존한다. |
| 자동 복구 후보 선택 | integrity와 schema compatibility를 통과한 backup 중 결정적으로 고른다. |
| Restore 후 readiness 실패 | restore 전 DB를 복원하고 Safe Mode를 유지한다. |

backup/restore I/O 중 Domain transaction이나 Connector I/O를 겹치지 않는다.

## 12. Shutdown and crash recovery

Shutdown 순서는 다음과 같다.

1. 새 command 차단
2. active external effect 안전 상태 확인
3. handoff loop stop/drain
4. MCP child 종료
5. SQLite/checkpoint flush
6. runtime secret 폐기
7. lock 해제

다음 시작에서 적용하는 복구 규칙은 다음과 같다.

- open Run, in-flight Attempt, `UNKNOWN_RESULT`, Verification/Recovery obligation을 검사한다.
- `BeginExecutionAttempt` 이후 dispatch 결과가 불명확하면 새 WRITE를 보내지 않고 기존 외부 결과 조회부터 수행한다.
- 이미 `VERIFIED`인 effect를 재실행하지 않는다.

## 13. Health and diagnostics

Health는 Core, DB, checkpoint, Connector별 credential/schema/process, Gemini credential/network, Ollama probe/model inventory를 분리한다. `LIVE`, `READY`, degraded optional capability, Safe Mode를 혼동하지 않는다.

| Diagnostic bundle | 내용 |
| --- | --- |
| 제공 | version, component status, bounded error code, correlation identity |
| 제외 | secret, raw provider payload, 업무 원문 |

Diagnostic bundle은 Activity/Trace/Audit의 authority를 대체하지 않는다.

## 14. CI and release gates

- Python unit/contract/integration/architecture tests
- Frontend test/type/lint/build
- migration fresh/upgrade/checksum/integrity tests
- release manifest/signature/tamper tests
- startup/shutdown/crash/recovery tests
- Connector child/environment isolation tests
- Local inspection matrix와 single-model availability selection tests
- external consent/scope and no-cross-runtime-fallback tests

실제 credential/provider/device 조건이 없는 Live 검증은 미수행으로 구분한다. 자동 테스트나 signed artifact 존재만으로 실제 provider E2E 완료를 선언하지 않는다.
