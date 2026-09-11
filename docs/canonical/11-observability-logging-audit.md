# 11. 관측성 · 로그 · 감사 설계서

> **Authority:** observability/log/trace/audit projection, sanitization과 retention. Domain/Workflow lifecycle 의미는 관측 event로 재정의하지 않는다.  
> **상태:** Draft v2.26 · **기준일:** 2026-09-07 · **외부 Telemetry:** Production 기본 OFF

## 0. 목적과 읽는 기준

이 문서는 Event·Log·Trace·Audit의 schema, sanitization, retention을 정의한다. **제품 사실의 기준점은 Domain Store**이며, Trace·SSE·Evaluation Report는 제품 상태를 대체하지 않는다.

Audit·Trace Event는 Domain·Workflow·Policy에서 발생한 사실의 관측 projection이다. 이벤트 이름이나 관측 분류로 새 상태·Command·Guard·허용 전이를 정의하지 않는다.

## 1. 채널

| 채널 | 목적 | 저장 |
| --- | --- | --- |
| Operational Log | Process·Adapter·Startup | Sanitized JSONL |
| Trace | 판단·호출 과정, Run·Node·Agent·Tool·성능 | SQLite `trace_events` |
| Audit | 승인·정책·실행·검증·복구의 안전 기록 | SQLite `audit_events` |
| SSE | React 진행 Projection | 제한 Buffer·재생성 |
| Metric | Local 집계 | Trace·Audit 계산 |
| Evaluation Artifact | Candidate·Case·Trial·Grader 결과 | 13 Evaluation artifact store |

Evaluation Artifact의 의미는 `13 Evaluation`, 저장소 내 배치·네이밍은 `16 Repository Architecture`가 소유한다.

### 1.1 SSE Projection ownership

SSE는 durable Domain Event Store가 아니라 bounded process-local replay 채널이다.

| 항목 | 처리 |
| --- | --- |
| 변환·저장 | `sse_event.project_run_event`가 typed fact를 `RunSseEventV1`로 변환하고 `SseEventBufferPort`에 append |
| P0 Buffer | `InMemorySseEventBuffer` 사용. capacity·terminal-retention·query-bound는 `10 Infrastructure`의 configured 값 적용 |
| Cursor 만료·Process 재시작으로 Buffer 유실 | API가 `CURSOR_EXPIRED`를 반환하고 React가 Run Snapshot으로 복구. Cursor는 `Last-Event-ID` 사용 |

### 1.2 기록 시점과 실패 처리

| 기록 | 시점 | 기록 실패 시 처리 |
| --- | --- | --- |
| Required lifecycle Audit | Domain mutation·Receipt와 같은 UoW | Command rollback. 안전 Command의 Audit 저장 실패는 Command 실패 |
| Diagnostic Trace·SSE publish | Commit 이후 | 이미 commit된 Domain mutation을 rollback하지 않음. 외부 Connector Write 재전송 금지 |

## 2. Correlation

### 2.1 제품 Runtime 공통 필드

```
app_instance_id
service_instance_id
request_id
command_id
conversation_id
run_id
langgraph_thread_id
plan_id
action_id
approval_id
execution_attempt_id
verification_id
llm_call_id
mcp_request_id
connector_id?
provider_request_id
```

### 2.2 평가 Runtime 추가 필드

평가 필드는 제품 일반 실행에 강제로 저장하지 않는다. Experiment Runner가 명시적으로 시작한 Run에만 연결한다.

```
main_experiment_id?      # A | B | C | D | E
experiment_id?           # compatibility-only reproduction alias; current decision key is main_experiment_id
dataset_suite_id?        # current 13 Evaluation registered suite ID
episode_variant_id?      # Product Episode variant only
evaluation_item_id
case_id
user_prompt_id
fixture_snapshot_id
candidate_config_hash
trial_index
projection_version
upstream_mode?       # ORACLE | LIVE
target_node_id?
grader_version
evaluation_environment_hash?
runner_version?
hardware_profile_id?
concurrency_limit?
timeout_profile?
```

## 3. Event Envelope

```
schema_version
event_name
event_category
occurred_at_ms
severity
component
environment
release_version
request_id?
command_id?
run_id?
action_id?
result_code?
status?
duration_ms?
attributes
```

Category:

```
LIFECYCLE API WORKFLOW AGENT RETRIEVAL LLM DOMAIN MCP CONNECTOR PROVIDER
VERIFICATION SECURITY PERSISTENCE INSTALLER DIAGNOSTIC EVALUATION
```

Payload·Metadata는 최대 **16 KiB**다. 원문 대신 수량·Hash·상태·지연을 기록한다.

## 4. JSONL Log

```
%LOCALAPPDATA%/GoogleWorkAgent/logs/
launcher-*.jsonl
service-*.jsonl
mcp-*.jsonl
```

| 항목 | 상한 |
| --- | --- |
| 파일 크기 | 파일당 10 MiB |
| Directory 크기 | 200 MiB |

## 5. Trace 관측 범위

| 영역 | 관측 대상 |
| --- | --- |
| Launcher·Installer | lifecycle |
| API | request·command·SSE |
| Workflow | Run·Graph·Node·Interrupt |
| Agent | invocation·repair·handoff |
| Retrieval | page·candidate·detail·budget |
| LLM | runtime·token·latency·fallback |
| MCP | process·handshake·tool |
| Connector·Provider | read·write·verification |
| SQLite | transaction·busy·migration·backup |
| Evaluation | item·candidate·trial·grader·budget stop |

### 5.1 Component Circuit · Run Budget 관측 projection

| Runtime operational event | 인자 |
| --- | --- |
| `COMPONENT_CIRCUIT_OPENED` | `component`, `retry_at_ms`, `failure_code` |
| `COMPONENT_CIRCUIT_PROBE_SUCCEEDED` | `component` |
| `COMPONENT_CIRCUIT_REOPENED` | `component`, `retry_at_ms`, `failure_code` |
| `RUN_BUDGET_EXHAUSTED` | `run_id`, `budget_kind`, `used`, `limit` |

Metric·Diagnostic에는 `circuit_kind + connector_id? + llm_runtime? + state + retry_at_ms`와 bounded used/limit만 노출한다.

`CONNECTOR` key는 `connector_id`로 correlation한다. Provider 이름을 Core circuit enum으로 승격하지 않는다. Circuit event는 Domain truth가 아니라 `06/10` operational control state의 관측값이다.

Event attribute에는 OAuth·LLM secret, raw MCP·Provider payload, Prompt text를 넣지 않는다.

### 5.2 Local Runtime inspection Trace

```text
LOCAL_RUNTIME_INSPECTION_STARTED
LOCAL_RUNTIME_INSPECTION_FAILED
LOCAL_RUNTIME_INSPECTION_COMPLETED
LOCAL_MODEL_SELECTION_CHANGED
LOCAL_MODEL_RESOLVED
```

| 구분 | 기록 범위 |
| --- | --- |
| 허용 | inspection identity, Ollama readiness, 지원 모델 presence, 이전/현재 선택, 실제 resolved model, bounded failure code, duration |
| 금지 | Raw local path, process command, model binary, Prompt·Completion |

Inspection Trace는 Domain lifecycle·Audit authority가 아니다. 검사 실패가 기존 Run binding이나 Domain Write를 바꾸지 않는다.

### 5.3 Run의 실제 Runtime 복원

Run Snapshot의 actual runtime은 해당 Run의 persisted `LLM_CALL_COMPLETED` 관측값으로 복원한다.

| 관측 상황 | 표시·복원 기준 |
| --- | --- |
| 현재 새 Run | Local/Gemini 자동 전환이 없으므로 하나의 runtime만 관측되어야 함 |
| 과거 Run에 `LOCAL_GPU`와 `API_LLM`이 모두 관측됨 | 저장된 history를 다시 쓰지 않고 legacy `MIXED`로 표시 |
| 호출이 없음 | Nullable 관측값 유지 |

현재 Settings로 과거 실행을 추측하지 않는다.

### 5.4 Workflow Handoff · Operational Replay Trace

이 관측 범위의 Trace event identity는 아래 목록으로 한정한다.

```text
WORKFLOW_HANDOFF_STAGED
WORKFLOW_HANDOFF_SUBMIT_RESULT
WORKFLOW_HANDOFF_REDRIVEN
WORKFLOW_HANDOFF_CONSUMED
WORKFLOW_HANDOFF_BINDING_BLOCKED
EXTERNAL_LLM_SCOPE_PUBLISHED
OPERATIONAL_COMMAND_RESERVED
OPERATIONAL_COMMAND_RECOVERY_REQUIRED
OPERATIONAL_COMMAND_RECONCILED
```

| 대상 | 기록 범위·시점 |
| --- | --- |
| Handoff | `handoff_id`, `trigger_command_id`, `run_id`, target kind·stage·semantic owner, checkpoint generation, status·reason code, payload hash만 기록 |
| 외부 LLM 전송 범위 | `EXTERNAL_LLM_SCOPE_PUBLISHED`에 scope revision·hash와 bounded source·data-class enum을 Provider 호출 전에 기록 |

Confirmation free text, ContextAdjustment requested text, raw checkpoint·control payload는 기록하지 않는다.

### 5.5 Run Activity 관측 projection

`RUN_ACTIVITY_OBSERVED`는 기존 `trace_events`에 저장하는 schema version 1의 진단 projection이다.

**실행 식별**

| 구분 | 식별 기준 |
| --- | --- |
| 같은 task의 시작·interrupt·재개·결과 | LangGraph checkpoint task namespace를 Run과 함께 해시한 execution ID로 연결 |
| 정상 back-edge | 다른 task ID 사용 |
| 실행 identity로 사용할 수 없는 값 | Callback invocation UUID, Frontend 수신 순서 |

**기록과 복원**

기록·복원은 아래 Application operation이 담당한다.

| 책임 | 처리 |
| --- | --- |
| `trace_event.record_run_activity` | 책임, 관측 상태, 해당 실행의 validated artifact revision, bounded allowlisted detail을 선택. 기존 `emit_trace_event` sanitization·retention 적용 |
| Detail 제한 | 요청 goal, 선택 근거 제목, 계획 title·date·time, 검토·부족 정보 설명은 각 512자 이하. 본문·전체 Answer·Approval·Prompt·Completion 저장 금지 |
| 불확실한 관측 | 누락된 결과나 실패한 관측을 추측하지 않음 |
| `run.project_run_activity` | 기존 Trace·Audit keyset 페이지로 Run별 행 복원. 재조회 시 Provider·LLM I/O와 mutation 없음. 보존 정책 내 행을 임의 최근 N개로 제한하지 않음 |

**행과 상세의 근거**

| 대상 | 표시 규칙 |
| --- | --- |
| 승인·실행·검증 사실 | Committed Domain Audit만 사용 |
| 같은 attempt의 dispatch·result | 같은 실행 행 갱신. Verification은 별도 행 |
| `RUN_REAUTH_RESUMED` | 같은 Run의 재인증 대기 행 갱신 |
| `RECOVERY_RESOLVED` | 같은 action 범위의 복구 대기 행 갱신 |
| 승인 상세 | 해당 Audit·Attempt가 가리키는 immutable Approval snapshot 사용 |
| 검증 상세 | 해당 Verification ID의 expected·actual 허용 필드만 사용 |
| 취소·복구의 사용자용 행 | Domain Audit에서만 생성. 대응하는 workflow callback을 별도 행으로 중복 표시하지 않음 |

재인증·복구의 후속 처리 결정은 외부 효과 성공이나 Verification 완료를 뜻하지 않는다.

### 5.6 Opt-in LangSmith Workflow projection

LangSmith Run의 input/output에는 전체 LangGraph State를 전달하지 않는다. 현재 Run에 존재하는 허용된 State field와 branch·status·route/query 종류, 수량·budget, 명시적 `null` 여부만 16 KiB 이하의 versioned projection으로 전달한다. 사용자 요청·업무 본문·Resource ID·검색어, Prompt·Completion, Connector payload는 제외한다.

이 projection은 Graph·Node 실행을 분석하기 위한 외부 관측값이며 Domain State, routing, checkpoint 또는 실행 성공의 authority가 아니다. 과거 Trace는 소급 변경하지 않는다.

## 6. Audit 필수 Event

P0 Audit는 **Application-level append-only**다. 암호학적 Tamper Evidence는 P1 검토 사항이다.

필수 lifecycle Audit mapping은 다음을 만족해야 한다.

- Command key set은 Domain State Transition Contract의 current lifecycle command-family closed set과 정확히 일치한다.
- `ResolveRecovery`처럼 disposition coverage가 필요한 Command는 해당 State Contract의 current disposition set도 빠짐없이 검증한다. 숫자 count를 별도 authority로 복제하지 않는다.
- 같은 Command replay는 새 Audit를 중복 append하지 않는다.

### Lifecycle Command → Audit Event

| Lifecycle Command | Required Audit event |
| --- | --- |
| `StartRun` | `RUN_STARTED` |
| `StartAnalysis` | `RUN_ANALYSIS_STARTED` |
| `BeginRetrieval` | `RUN_RETRIEVAL_STARTED` |
| `BeginPlanning` | `RUN_PLANNING_STARTED` |
| `RequestConfirmation` | `CONFIRMATION_REQUESTED` |
| `ResumeConfirmation` | `CONFIRMATION_RESUMED` |
| `CompleteAnswerOnlyRun` | `RUN_COMPLETED(completion_mode=ANSWER_ONLY)` |
| `CompleteReadOnlyRun` | `RUN_COMPLETED(completion_mode=READ_ONLY)` |
| `PublishPlan` | `PLAN_PUBLISHED` |
| `PublishReadOnlyPlan` | `READ_PLAN_PUBLISHED` |
| `BlockRun` | `RUN_BLOCKED` + policy-origin이면 `POLICY_BLOCKED` |
| `BeginVerification` | `RUN_VERIFICATION_STARTED` |
| `CompleteWriteRun` | `RUN_COMPLETED(completion_mode=WRITE)` |
| `RequestCancel` | `RUN_CANCEL_REQUESTED` |
| `FinalizeCancel` | `RUN_CANCELLED` |
| `RequireReauth` | `RUN_REAUTH_REQUIRED` |
| `ResumeAfterReauth` | `RUN_REAUTH_RESUMED` |
| `RequireRecovery` | `RECOVERY_REQUIRED` |
| `ResolveRecovery(RECHECK)` | `RECOVERY_RESOLVED(resolution=RECHECK)` only when applied=true |
| `ResolveRecovery(ACCEPT_PARTIAL)` | `RECOVERY_RESOLVED(resolution=ACCEPT_PARTIAL)` + `RUN_COMPLETED(completion_mode=PARTIAL)` |
| `ResolveRecovery(CREATE_CORRECTIVE_PLAN)` | `RECOVERY_RESOLVED(resolution=CREATE_CORRECTIVE_PLAN)` + `RUN_PLANNING_STARTED` |
| `ResolveRecovery(CANCEL)` | `RECOVERY_RESOLVED(resolution=CANCEL)` + `RUN_CANCELLED` |
| `ResolveRecovery(FAIL)` | `RECOVERY_RESOLVED(resolution=FAIL)` |
| `ApproveAction` | `ACTION_APPROVED` |
| `ModifyAction` | `ACTION_MODIFIED` + ACTIVE Approval revoke 시 `APPROVAL_REVOKED` |
| `RejectAction` | `ACTION_REJECTED` + ACTIVE Approval revoke 시 `APPROVAL_REVOKED` |
| `CancelPendingAction` | `ACTION_CANCELLED` + ACTIVE Approval revoke 시 `APPROVAL_REVOKED` |
| `ExpireApproval` | `ACTION_EXPIRED` + `APPROVAL_EXPIRED` |
| `RefreshExpiredAction` | `ACTION_REFRESHED` |
| `ClaimReadAction` | `ACTION_READ_CLAIMED` |
| `CompleteReadAction` | `ACTION_READ_EXECUTED` |
| `FinalizeReadAction` | `ACTION_READ_VERIFIED` |
| `FailReadAction` | `ACTION_READ_FAILED` |
| `ClaimExecution` | `EXECUTION_CLAIMED` + `APPROVAL_CONSUMED` |
| `BeginExecutionAttempt` | `EXECUTION_DISPATCH_STARTED` |
| `AbortClaimedExecution` | `EXECUTION_CLAIM_ABORTED` |
| `StoreSuccess` | `EXECUTION_SUCCEEDED` |
| `MarkFailed` | `EXECUTION_FAILED` |
| `MarkUnknownResult` | `EXECUTION_UNKNOWN_RESULT` |
| `RecoverExistingResult` | `EXECUTION_RECOVERED` |
| `ResolveAsFailed` | `EXECUTION_FAILED(recovered_from_unknown=true)` |
| `StoreVerification(VERIFIED)` | `VERIFICATION_VERIFIED` |
| `StoreVerification(MISMATCH)` | `VERIFICATION_MISMATCH` |
| `PrepareWriteRetry` | `ACTION_RETRY_PREPARED` |

### 6.1 Reauth Audit mapping

| Event | 기록하는 사실 | 허용된 기록 |
| --- | --- | --- |
| `RUN_REAUTH_REQUIRED` | `RequireReauth`가 applied되어 Run이 재인증 suspend 경계에 들어감 | `run_id`, `reason_code`, connector·account reference, checkpoint presence만 기록 |
| `RUN_REAUTH_RESUMED` | `ResumeAfterReauth`가 registered same-run resume target 검증을 통과해 재개됨 | `run_id`, `graph_version`, owner subgraph, resume target ref의 bounded identifier만 기록 |

Token·secret·raw credential은 기록하지 않는다. `08 Sequence`의 `Receipt/Audit` 표기는 위 event에 매핑하며 별도 reauth event 이름을 만들지 않는다.

### 6.2 Review · Policy Confirmation 기록

| Event | 의미·저장 기준 |
| --- | --- |
| `REVIEW_RESULT_RECORDED` | `RecordReviewResult`가 같은 short UoW에 기록. 해당 operation은 lifecycle Command가 아니라 Application persistence operation |
| `POLICY_CONFIRMATION_RECORDED` | Policy Confirmation Receipt persistence event |

이 두 event를 Domain lifecycle Command로 승격하지 않는다.

`POLICY_CONFIRMATION_RECORDED`의 기록 범위는 다음과 같다.

| 항목 | 기준 |
| --- | --- |
| 허용 ID·Hash | `confirmation_receipt_id`, `interrupt_id`, `decision_context_hash`, 관련 Run·Resource·Route ID |
| Confirmation 종류 | `confirmation_kind`: `SCOPE_EXPANSION`, `DUPLICATE_OVERRIDE`, `CONFLICT_OVERRIDE` |
| 결정 | `decision`: `APPROVED`, `DECLINED` |
| 기록 금지 | 질문·응답 원문, Connector Source 본문 |
| APPROVED Receipt의 결합 | LangGraph Checkpoint의 `PolicyConfirmationReceiptV1`과 같은 ID·Context Hash를 가져 Approval Snapshot이 참조할 수 있어야 함 |

### 6.3 그 밖의 필수 Audit Event

위 mapping 외에 다음 event도 필수 목록에 포함한다.

| 대상 | Event |
| --- | --- |
| Action 제안 | `ACTION_PROPOSED` |
| Backup·Restore | `BACKUP_CREATED`, `RESTORE_COMPLETED` |
| Migration·Purge | `MIGRATION_COMPLETED`, `PURGE_COMPLETED` |
| Diagnostic Bundle | `DIAGNOSTIC_BUNDLE_EXPORTED` |

## 7. Sanitization

관측 데이터는 다음 순서로 처리한다.

```
Schema 검증 → Field Allowlist → Secret·PII Redaction → 길이 제한 → Sink Projection
```

일반 Log·Trace·Audit의 기록 금지 대상:

| 구분 | 기록하지 않는 내용 |
| --- | --- |
| Credential·Session | OAuth Token, API Key, Authorization, Cookie, Bootstrap, Session, PKCE |
| 업무 원문 | Connector Source·Draft 전체 본문, Approval Snapshot 전체 |
| 첨부파일 | P0 Gmail 첨부파일 bytes, Staging File 원문, 로컬 파일 경로, filename·전체 content SHA-256 같은 불필요한 식별 정보 |
| 추론 | LLM Prompt·Completion |
| 외부 호출 | MCP 전체 Request·Response |
| 사용자 환경 | Home Path, Windows User Name |
| 평가 정답 | Holdout Gold 원문 |

DEBUG에서도 Secret·원문 금지는 동일하게 적용한다.

평가 Artifact에도 실제 사용자 데이터, Credential, 전체 Prompt·Completion을 포함하지 않는다. 합성 Fixture 원문은 Dataset 디렉터리에서만 관리하고 Trace에는 ID·Hash만 기록한다.

## 8. 보존

| 대상 | 보존 기간 |
| --- | --- |
| App Log | 14일 |
| Terminal Run Trace | Owning Run의 configured `retention_days`와 동일. Default 30일, 허용 범위 `1..30` |
| Audit | 90일 고정 |
| Evaluation Raw Result | Experiment Config에 명시한 기간 |

Purge는 Batch당 최대 500 Row다. Active Write·Migration·Restore 중에는 수행하지 않는다.

## 9. Prompt Registry Trace

```
prompt_bundle_version
prompt_semantic_bundle_version
prompt_input_contract_version
prompt_id
prompt_version
content_hash
agent_role
subgraph_name
node_name
node_state
purpose
input_schema_version
output_schema_version
repair_of_llm_call_id?
revision_no?
```

### 9.1 Evaluation Trace 계약

평가 Report는 다음 필드를 연결한다.

```
main_experiment_id       # A | B | C | D | E
experiment_id?           # compatibility-only reproduction alias
dataset_suite_id         # current 13 Evaluation registered suite ID
episode_variant_id?      # Product Episode variant only
experiment_kind
evaluation_item_id
case_id
fixture_snapshot_id
user_prompt_id
projection_version
candidate_config_hash
trial_index
prompt_id
model_id
graph_version
upstream_mode?
target_node_id?
grader_version
scoring_contract_version
```

**호출·비용·지연 집계**

```
llm_call_count
provider_http_request_count
mcp_tool_call_count
provider_api_call_count
input_token_count
output_token_count
cost_usd
p50_latency_ms
p95_latency_ms
repair_count
revision_count
retrieval_round_count
```

**결과 집계**

Evaluation Summary에는 `safety_contract_pass`, `business_outcome_pass`, `business_task_success`, 선택적으로 `end_state_pass`, `semantic_completion_pass`, `denominator_group(CORE|STRESS|HOLDOUT|PRODUCT_EPISODE|SYNTHETIC_MULTI_CONNECTOR)`, `scoring_contract_version`을 기록한다.

Historical result-field alias는 current production Event schema에 추가하지 않고 재현 adapter에서만 변환한다.

| 구분 | 집계·표시 규칙 |
| --- | --- |
| 실행 입력 | `ORACLE`과 `LIVE` Node Run을 같은 결과로 합치지 않음 |
| 후보 | Candidate Config Hash가 다른 결과를 같은 후보 집계에 합치지 않음 |
| 실행 범위 | Budget Stop·Partial Run은 Full Run과 동일 순위로 비교하지 않음 |
| 결과 근거 | Safety·Tool·Argument·End-state는 결정적 Grader 결과를 우선 |
| LLM Judge | `grader_version`과 Human Calibration 상태 기록 |
| 분모 | Core·Stress·Holdout을 하나의 headline denominator로 합치지 않음 |

Architecture 비교의 제품 결정은 `13 Evaluation`이 소유한다. 관측에서는 Profile native cost와 동일 `ContextReadySnapshotV1.context_snapshot_id` 기반 post-retrieval decomposition을 분리한다. Controlled post-retrieval diagnostic의 Connector Read 호출은 0이어야 한다.

**평가 전용 Event 예**

```
EVALUATION_ITEM_STARTED
EVALUATION_ITEM_COMPLETED
NODE_ORACLE_RUN_COMPLETED
NODE_LIVE_RUN_COMPLETED
TRAJECTORY_GRADED
END_STATE_GRADED
GRADER_DISAGREEMENT_RECORDED
EXPERIMENT_BUDGET_STOPPED
```

## 10. Diagnostic Bundle

| 항목 | 내용 |
| --- | --- |
| 포함 | Manifest, System Summary, Health, Sanitized Logs, Trace·Audit·Migration Summary |
| 제외 | DB·Backup 원본, Keyring, Connector 원문, Prompt·Completion, Approval Snapshot, 실험 Gold 원문 |
| 크기 상한 | Configured `DIAGNOSTIC_BUNDLE_MAX_BYTES` |
| 기본 시간 범위 | Configured `DIAGNOSTIC_BUNDLE_DEFAULT_WINDOW_MS` |
| 개별 Run 범위 | 사용자가 명시한 Run 하나를 scope로 선택 가능 |
| 업로드 | 자동 업로드 금지 |

크기·시간의 exact 숫자는 `10 Infrastructure` configuration만 소유한다.

## 11. Local Alert

**제품에서 즉시 표시**

- Service·DB·Migration 실패
- MCP 반복 종료
- OAuth 재인증
- `UNKNOWN_RESULT`·`RECOVERY_REQUIRED`
- Contract Version 불일치
- Signature·Manifest 오류

**Experiment Runner에서 별도로 실패 표시**

- Dataset·Projection Reference 불일치
- Candidate Config 의도 외 Diff
- Holdout 누수
- Grader Version 누락
- Budget 상한 초과

## 12. Command·Claim 관측 계약

Trace·Audit Event:

```
COMMAND_RECEIVED
COMMAND_REPLAYED
COMMAND_REJECTED_HASH_MISMATCH
COMMAND_APPLIED
CLAIM_TOKEN_ISSUED
CLAIM_TOKEN_REJECTED
CLAIM_TOKEN_CONSUMED
OAUTH_CONNECTION_STARTED
OAUTH_CONNECTION_COMPLETED
OAUTH_CONNECTION_REVOKED
```

| 구분 | 기록 허용 범위 |
| --- | --- |
| Command·Claim | `command_id`, `command_type`, Request Hash 앞 12자리, Aggregate ID, 결과 코드, Claim Token Version, 거절 사유 |
| Attachment 집계 | Attachment 수·총 byte 수 같은 비식별 집계 |
| Claim V2 검증 Trace | `version`, 검증 단계, 거절 reason code만 기록 |

`approval_arguments_hash`, `execution_arguments_hash`, Nonce, Signature, Attachment content hash 원문은 일반 Log·Trace에 기록하지 않는다.

Claim Token 원문, Service–MCP Session Key, Authorization Code, PKCE Verifier, Access·Refresh Token도 기록하지 않는다.

## 13. Agent Failure·Retry·Query 관측 계약

Failure·Retry 의미는 `15 Agent Capability · Failure · Prompt 공통 계약`을 따른다. 여기서는 다음 Trace 추가 필드를 기록한다.

```
failure_reason_codes
failure_origin
detected_by
runtime_disposition
experiment_disposition
retry_kind
attempt_no
previous_llm_call_id
validator_codes
changed_field_paths
stop_reason
query_attempt_id
budget_profile
```

| 관측 대상 | 기록 기준 |
| --- | --- |
| Prompt | Base PromptRef와 `activation_status` 기록 |
| Failure Block | `failure_reason_code`를 Failure Block assembly metadata로 연결. Runtime Prompt Slot Key로 사용하지 않음 |
| Query 종류 | `SEARCH`, `NEXT_PAGE`, `DETAIL_FETCH`, `FREEBUSY` 구분 |
| Query 설정 | Retrieval·Score·Threshold Config Version 기록 |
| Pagination | `read_result_handle` 식별용 안전 hash, query·page state hash, `has_next_page`, exhaustion·result count 같은 bounded metadata만 기록 |

Raw Provider `next_page_token` 원문은 Log·Trace·Audit에 기록하지 않는다.

## 14. Agent Subgraph 관측 계약

Agent 수와 LLM Call 수를 분리해 기록한다.

```
graph_profile
semantic_agent_owner_id
compiled_subgraph_id
agent_role
agent_invocation_id
parent_agent_invocation_id?
subgraph_namespace
replay_mode?              # NONE | CONTEXT_READY_REPLAY
context_snapshot_id?
controlled_candidate_id?  # B1_INTEGRATED | B2_STAGED | B3_SPECIALIZED
local_attempt_no
schema_repair_count
semantic_revision_count
handoff_from
handoff_to
handoff_disposition
input_state_hash
output_state_hash
llm_call_id
input_token_count
output_token_count
communication_token_count?     # Typed Handoff payload의 token 추정 합계
required_field_preserved_count?
constraint_loss_count?
evidence_id_loss_count?
contradiction_count?
tool_call_count
duplicate_tool_call_count?
mcp_read_tool_call_count
coordination_wait_ms?
```

| 항목 | 집계·관측 기준 |
| --- | --- |
| Agent·LLM | `agent_invocation_count`와 `llm_call_count` 별도 집계 |
| Core의 외부 Connector 호출량 | `connector_id`별 `mcp_tool_call_count`·`mcp_read_tool_call_count` 기준 |
| Provider API 호출량 | `provider_api_call_count`는 각 Connector MCP Server 내부 Adapter가 실제 Provider API를 호출한 횟수. MCP 내부 효율·pagination·N+1 진단용 보조 지표 |
| Connector 구분 | Google Workspace는 `connector_id=google_workspace`, GitHub는 `connector_id=github`로 기록·독립 집계 |
| Handoff | Agent 간 자유 대화가 아니라 Parent Graph의 Typed Result 이동으로 기록 |

Provider API 호출량을 관측한다는 이유로 Core의 Provider API 직접 호출을 허용하지 않는다. Local State 원문은 Trace에 저장하지 않는다.
