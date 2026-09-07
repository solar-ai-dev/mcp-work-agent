# 상태 전이 테스트 매트릭스 v1.10

> **선행 읽기:** `00 → 04 Domain·DB → Domain State Transition Contract`  
> **이 문서의 역할:** state-transition normative verification matrix. 선행 문서의 의미를 재정의하지 않는다.  
> **수정일:** 2026-09-07

## Authority boundary

이 문서는 `Domain State Transition Contract`와 `04 Domain·DB`의 lifecycle/persistence invariant를 검증하는 normative matrix다. 새 Command·State·Guard를 발명하지 않으며 migration 파일의 특정 SQL 문법을 behavioral authority로 승격하지 않는다.

## Command Receipt·API Trust Boundary

| 검증 항목 | 기대 결과 |
| --- | --- |
| Commit 경계 | Receipt·Domain·Audit 원자 Commit. |
| 같은 ID·같은 서버 계산 Canonical Hash | 기존 결과 반환. |
| 같은 ID·다른 Hash | 409, Domain 변경 0. |
| `RejectAction` replay/hash/version conflict | child mutation과 Audit 중복 0. |

Browser 제공 `request_hash`·`approval_id`·`idempotency_key`·`source_snapshot`·actor identity는 authority가 아니다.

## Run 시작·Planning Back-edge

| Command·조건 | 기대 전이·검증 |
| --- | --- |
| `StartRun` | Run `CREATED`. |
| `StartAnalysis` | Request Understanding 전에 `CREATED → ANALYZING` 정확히 1회. |
| `BeginRetrieval` | `ANALYZING \| PLANNING → RETRIEVING`. |
| `BeginPlanning` | `ANALYZING \| RETRIEVING → PLANNING`. Published-plan branch는 State Contract의 Review matrix 또는 validated `USER_CONTEXT_ADJUSTMENT` guard에서만 `WAITING_APPROVAL \| VERIFYING → PLANNING` 허용. |
| 이미 target 상태인 Retrieval local loop / Planning revision | 동일 Command 반복 0. |

Workflow 분기 검증:

- Request `COMPLETE → Tool Route` Edge 누락 0.
- `NO_FETCH_NEEDED`는 `SUFFICIENT`와 같은 analysis guard.
- `NEEDS_MORE_DATA + budget`은 bounded local loop. Budget 소진 후 `NEEDS_CONFIRMATION | PARTIAL | BLOCKED`로 정규화.

## Confirmation

1. `RequestConfirmation` 적용 후에만 `WAITING_CONFIRMATION` interrupt를 생성한다.
2. `semantic_owner_id + AgentNodeResumeTargetV2 + interrupt_id`를 checkpoint에 보존한다.
3. 사용자 응답 검증 후 `ResumeConfirmation`으로 발생 전 안전 상태를 복원한다.
4. same owner checkpoint에서 resume한다.

Upstream 의미 변경이 없는 Confirmation에서 Request Understanding 공통 재시작은 0이다.

## BlockRun

**허용 조건:** Claim 전 상태이며 Active/Unknown/미검증 Write Attempt가 없어야 한다.

Plan이 있으면 같은 UoW에서 다음 순서를 검증한다.

1. 미실행 nonterminal Action `PROPOSED|MODIFIED|APPROVED|EXPIRED → BLOCKED`.
2. ACTIVE Approval → `REVOKED`.
3. Plan → `CANCELLED`.
4. Run → `BLOCKED`.

`DEPENDENCY_BLOCKED` 신규 생성은 `RejectAction`만 소유한다. Commit은 `04 Domain·DB`의 `DBI-005` cross-aggregate invariant와 충돌하지 않아야 하며, 실제 migration implementation도 이 invariant를 만족해야 한다.

In-flight Write를 Policy `BLOCKED`로 덮어쓰는 결과는 0이다.

## WRITE 정상·다중 Action

### 승인·실행 시작

| 구간 | 기대 결과 |
| --- | --- |
| `PublishPlan` | Run `WAITING_APPROVAL` + persisted Plan `WAITING_APPROVAL`. |
| `ClaimExecution` | Action `APPROVED → EXECUTING` + Approval `ACTIVE → CONSUMED` + 새 Attempt `CLAIMED`를 원자 Commit. Receipt/Audit까지 같은 UoW. |
| Claim만 Commit된 상태 | MCP Write 0. Claim은 필요조건이지만 dispatch authority가 아님. |
| `BeginExecutionAttempt` | 이 Command만 Attempt `CLAIMED → EXECUTING` 허용. Commit(`applied=true`)가 외부 Write의 유일한 lifecycle pre-dispatch gate이며, 그 전 Connector Write 0. |
| Claim Token 검증 | 유효 Token single-use, Action/Approval/Business Hash/Execution Hash/Nonce 검증. Action/Approval/Hash mismatch 차단. |
| Action 실행 중 | Run은 기본 `WAITING_APPROVAL` 유지. |

### 검증·다중 Action·완료

Write 후에는 Effect별 결정적 Verification을 수행한다.

| 조건 | 기대 결과 |
| --- | --- |
| `EXECUTED` 후 첫 검증 | `BeginVerification: WAITING_APPROVAL → VERIFYING` 정확히 1회. |
| 다중 Action에서 Run이 이미 `VERIFYING` | `BeginVerification` 재호출 0. |
| dependent Action | predecessor `VERIFIED` 이후에만 Claim. |
| 모든 승인 Action final + unresolved 0 + cancel intent false | `CompleteWriteRun: VERIFYING → COMPLETED`, Plan `COMPLETED`. |
| 외부 Write 0건인 all-rejected/all-cancelled Plan + 모든 Action final + unresolved 0 | `CompleteWriteRun: WAITING_APPROVAL → COMPLETED`, Plan `COMPLETED`. |

### Verification persistence

| 검증 항목 | 기대 결과 |
| --- | --- |
| `StoreVerification` | WRITE Action `EXECUTED → VERIFIED \| MISMATCH`와 immutable Verification append만 같은 UoW로 Commit. |
| `MISMATCH` 후 Run Recovery entry | `StoreVerification(...MISMATCH)` Commit 뒤 별도 `RequireRecovery(VERIFICATION_MISMATCH)`만 `RECOVERY_REQUIRED` 생성. 두 처리를 같은 hidden mutation으로 합치지 않음. |

### Claim V2 Contract Test 경계

Signature·TTL·Process Instance·`execution_arguments_hash`·Nonce·MCP 실제 인자 재해시는 `12 Test` current security/execution regression contract에서 추가 검증한다.

### AbortClaimedExecution matrix cases

| 상태·조건 | 기대 결과 |
| --- | --- |
| Action `EXECUTING` + Attempt `CLAIMED` + no APPLIED `BeginExecutionAttempt` + cancel intent | `AbortClaimedExecution` → Action `CANCELLED` + Attempt `FAILED`. |
| 같은 상태 + cancel 없음 + restart/ClaimContext/credential pre-dispatch failure | `AbortClaimedExecution` → Action `FAILED` + Attempt `FAILED`. |
| APPLIED `BeginExecutionAttempt` 존재 | Abort 금지. In-flight classification path만 허용. |
| Abort APPLIED 이후 | subsequent Begin/Connector Write 0. |

### Published Plan 재검토·Context Adjustment

Published Plan Review는 State Contract의 post-review matrix를 따른다. `WAITING_APPROVAL | VERIFYING`에서 다음을 검증하고, 이미 발생한 external effect와 terminal Action fact는 보존한다.

| Review 결과 | 후속 처리 |
| --- | --- |
| `REVISE \| RETRIEVE_MORE \| ROUTE_RECONSIDERATION` | `BeginPlanning`. |
| `CONFIRM` | `RequestConfirmation`. |
| `BLOCK` | guarded `BlockRun`. |

사용자 Context Adjustment는 다음 두 경우로 나눠 검증한다.

| 조건 | 기대 결과 |
| --- | --- |
| `WAITING_APPROVAL` + current Action 전부 `PROPOSED\|MODIFIED` + ACTIVE Approval 0 + in-flight/unknown/unverified execution 0 | 이 조건에서만 `BeginPlanning(USER_CONTEXT_ADJUSTMENT)` 허용. |
| current Preview에 없는 segment 제외 / stale `expected_retrieval_revision` / 승인·실행 이후 조정 | 모두 `applied=false`, Workflow invoke 0. |

## FAILED·Retry

`FAILED → EXECUTING` 직접 전이는 차단한다. `FAILED + NOT_SENT`는 자동 FINALIZE하지 않는다.

| 남은 작업 | 기대 결과 |
| --- | --- |
| dependency 없는 approved/executable Action이 있음 | 해당 Action 실행 계속. |
| 더 이상 실행할 독립 Action이 없음 | retry/cancel 대기. |

재시도 순서:

```text
PrepareWriteRetry: FAILED → MODIFIED
→ Review → Domain Validation → 새 Approval → 새 Attempt
```

기존 Approval·Idempotency Key·Attempt 재사용은 0이다.

## Coupled Action·Approval·Attempt mutation

| Command | 함께 검증할 변경·실패 조건 |
| --- | --- |
| `ApproveAction` | Action `PROPOSED\|MODIFIED → APPROVED`와 새 Approval `ACTIVE` 생성을 같은 UoW에서 완료. Action만 APPROVED인데 ACTIVE Approval이 없거나 반대 상태면 실패. |
| `ExpireApproval` | Action `APPROVED → EXPIRED`와 current Approval `ACTIVE → EXPIRED`를 함께 적용. |
| `ModifyAction` / `RejectAction` / `CancelPendingAction` | ACTIVE Approval을 남기면 실패. |
| `StoreSuccess` / `MarkFailed` / `MarkUnknownResult` / `RecoverExistingResult` / `ResolveAsFailed` | Action과 current ExecutionAttempt의 coupled status가 State Contract와 정확히 일치. Partial mutation은 rollback. |

## Approval expiry refresh

| 구간 | 기대 결과 |
| --- | --- |
| 만료 | `ExpireApproval: APPROVED → EXPIRED`. Direct `EXPIRED → APPROVED`는 항상 거절. |
| Refresh | `RefreshExpiredAction: EXPIRED → MODIFIED`. Current Source/Policy/Schema snapshot 재계산, 기존 Approval 재활성화 0. |
| Commit | Refresh mutation/Receipt/Audit과 `workflow_handoffs(PENDING, MAIN_CONTROL:REVIEW_ENTRY)`를 같은 UoW로 Commit. |
| Refresh COMMIT 뒤 process 종료 | restart/redrive가 fresh Review를 exactly once continuation. Fresh PASS 전 새 Approval 0. |
| Review·재승인 | Refresh 뒤 Plan review gate는 `REQUIRED`. Current revision의 fresh Review PASS가 durable하게 기록된 뒤에만 새 `ApproveAction` 가능. |
| Refresh/Review/Approve 사이 version conflict | stale result/Approval 재사용 0. |

## UNKNOWN_RESULT·Recovery

`UNKNOWN_RESULT`에서 새 Attempt·Write는 0이다.

### Effect별 기존 결과 조회

| Effect | 조회 방식 |
| --- | --- |
| CREATE | search. |
| UPDATE | target GET. |
| SEND | Sent lookup. |
| DELETE | target/absent lookup. |

기존 결과 recovered → `EXECUTED`. 이후 Run 상태에 따라 검증한다.

| Run 상태 | 후속 처리 |
| --- | --- |
| `WAITING_APPROVAL \| CANCEL_REQUESTED` | `BeginVerification` → Verification. |
| `RECOVERY_REQUIRED` | changed external-state fingerprint 기반 `ResolveRecovery(RECHECK)` → Verification. |
| 이미 `VERIFYING`인 later-DAG recovered result | `BeginVerification` 재호출 없이 바로 verification reread/`StoreVerification`. |

Lookup이 끝내 불명확할 때만 `RequireRecovery(UNKNOWN_RESULT)`로 Run을 `RECOVERY_REQUIRED`에 둔다. Recovery에서 `VERIFYING` 복귀는 재검증이 필요할 때만 허용한다.

### Recovery resolution

| 검증 항목 | 기대 결과·금지 조건 |
| --- | --- |
| `ResolveRecovery(FAIL)` | `FAILED → FINALIZE` 단일 경로. |
| `ResolveRecovery(ACCEPT_PARTIAL)` | cancel intent false에서만 `COMPLETED + PARTIAL`. |
| `CREATE_CORRECTIVE_PLAN` | cancel intent false에서만 `PLANNING` + 새 Plan Revision. |
| terminal `ResolveRecovery(ACCEPT_PARTIAL\|CANCEL\|FAIL)` | State Contract의 pending Action/Approval/Plan coupled cleanup을 같은 UoW에 반영. |
| 기존 MISMATCH Action/Approval/Attempt/Verification | 재사용 0. |

Recovery reason×resolution은 State Contract의 closed matrix와 exact match해야 한다. 다음은 실패다.

- `CHECKPOINT_MISMATCH|CONTRACT_VIOLATION` RECHECK가 무조건 `VERIFYING`으로 복귀.
- unresolved `UNKNOWN_RESULT`에 ACCEPT_PARTIAL/FAIL 적용.

### Post-Begin process-loss reconciliation

`BeginExecutionAttempt(applied=true)` COMMIT 뒤 `StoreSuccess | MarkFailed | MarkUnknownResult`가 없고 process가 restart된 `Attempt=EXECUTING`은 `NOT_SENT`로 추정하지 않는다.

MCP/LLM readiness 뒤 startup-only `execution_attempt.reconcile_inflight_executions` batch Command가 다음 family를 사용한다.

```text
system:execution-attempt-reconcile:<execution_attempt_id>[:phase]
```

| Phase | 기대 처리 |
| --- | --- |
| `POST_BEGIN_ORPHAN` | exactly-once `MarkUnknownResult(MAY_HAVE_BEEN_SENT)`. |
| `UNKNOWN_RESULT_UNRESOLVED` | existing-result lookup 후 deterministic resolution. |
| `EXECUTED_AWAITING_VERIFICATION` | BeginVerification/RECHECK + `...:verification` handoff. |
| `FAILED_AWAITING_CONTINUATION` | 필요한 `...:post-failed` PREFLIGHT/CANCEL_RESOLUTION handoff. |

Stable FAILED decision wait는 candidate가 아니다. Live loop invocation과 original Connector Write는 각각 0회다.

| Existing-result lookup 결과 | 후속 처리 |
| --- | --- |
| mutation 발견 | `RecoverExistingResult → Verification`. |
| 미실행을 결정적으로 증명 | `ResolveAsFailed`. |
| 불명확 | `RequireRecovery(UNKNOWN_RESULT)`. |

Crash 시점이 Begin 직후, provider 호출 중, provider success 뒤 result persistence 전 중 어디이든 blind resend는 0이고, restart 반복으로 새 Attempt가 생기지 않는다.

## Recovery RECHECK boundedness

| 조건 | 기대 결과 |
| --- | --- |
| 동일 `recovery_fingerprint + external-state fingerprint + verification input`으로 `ResolveRecovery(RECHECK)` 반복 | `NO_PROGRESS`, Run `RECOVERY_REQUIRED` 유지. 새 Verification/Connector read/Domain mutation 0. |
| changed external state/recovery reason/input 있음 | 이 경우에만 새 RECHECK round 허용. |

Recovery RECHECK reason별 target/NO_PROGRESS no-handoff matrix와 정확히 일치해야 한다. Automatic Recovery↔Verification loop는 실패다.

## Cancel

### Receipt·취소 의도

- RequestCancel Version Conflict/다른 Hash Replay → Approval·Plan·Action 변경 0.
- APPLIED RequestCancel Receipt에서 durable cancel intent를 복원한다.
- Cancel intent 활성 이후 신규 Claim·Write 0. Reauth 중에도 cancel intent를 유지한다.
- Cancel intent가 활성인데 `CompleteWriteRun → COMPLETED`로 종료하는 결과는 0이다.

### 미실행 Action

미실행 `PROPOSED|MODIFIED|APPROVED|EXPIRED` Action은 **각각 `CancelPendingAction` Receipt/UoW**로 처리한다.

| 변경·금지 항목 | 기대 결과 |
| --- | --- |
| 해당 Action | `CANCELLED`. |
| 해당 ACTIVE Approval | `REVOKED`. |
| Attempt·Verification | 생성 0. |
| 숨은 plural/batch lifecycle command | 만들지 않음. |

### 승인형 Write

In-flight Action을 취소 요청만으로 `CANCELLED`로 덮어쓰지 않는다. 결과를 `EXECUTED | UNKNOWN_RESULT | FAILED`로 먼저 확정한다.

| 실행 결과 | 취소 후속 처리 |
| --- | --- |
| `EXECUTED` | `CANCEL_REQUESTED → BeginVerification → VERIFYING` + Verification 후 `FinalizeCancel`. |
| `UNKNOWN_RESULT` | `RECOVERY_REQUIRED`. 결과 terminal snapshot이면 `ResolveRecovery(CANCEL)`, recheck면 `VERIFYING` 후 `FinalizeCancel`. |

성공 Write rollback은 0이다. 일부 성공 취소는 Domain `CANCELLED` + Projection `PARTIAL`이 가능하다.

### Legacy READ cancel

| READ Action 상태·조건 | 기대 처리 |
| --- | --- |
| `PROPOSED` | `CancelPendingAction`. |
| `EXECUTING` | RequestCancel 이후 새 ConnectorRead/READ_EXECUTION reauth/retry 0. |
| `EXECUTING` + 미dispatch·failure·AUTH_EXPIRED·restart-uncertain | `FailReadAction → FAILED`. |
| `EXECUTING` + 이미 도착한 typed success | `CompleteReadAction → FinalizeReadAction → VERIFIED`. |
| `EXECUTED` | `FinalizeReadAction`. |

위 처리를 마친 뒤에만 `FinalizeCancel`을 수행한다. ExecutionAttempt row 생성은 항상 0이다.

## Reauth

### Checkpoint·target 선택

`RequireReauth`는 Retrieval/Planning/Approval/Legacy READ/Verification/Cancel/Recovery 안전 checkpoint를 보존하고 `pre_reauth_status`와 registered target을 저장한다. Target은 Run status만이 아니라 current Action/ExecutionAttempt/delivery fact를 함께 보고 선택한다.

| 현재 상태·실행 사실 | 허용 target·처리 |
| --- | --- |
| `WAITING_APPROVAL` + no in-flight Write Attempt + `BeginExecutionAttempt` 전 credential failure | `MAIN_CONTROL:PREFLIGHT`. |
| `WAITING_APPROVAL` + Attempt EXECUTING/UNKNOWN_RESULT/EXECUTED-awaiting-verification | PREFLIGHT 금지. delivery/existing-result reconciliation 뒤 `VERIFICATION \| RECOVERY`. |
| `EXECUTING` + Legacy READ Action `EXECUTING` + ExecutionAttempt row 0 + `AUTH_EXPIRED` + `cancel_intent_active=false` | `MAIN_CONTROL:READ_EXECUTION`. OAuth 완료 후 같은 non-mutating READ만 재개, Approval/Attempt/Write 생성 0. |
| 위 Legacy READ 경로에서 cancel intent active | READ_EXECUTION/Reauth를 시작하지 않음. Legacy READ cancel settlement로 `FAILED\|VERIFIED` 확정 후 `FinalizeCancel`. |
| `VERIFYING` | `MAIN_CONTROL:VERIFICATION`. |
| `RECOVERY_REQUIRED` | `MAIN_CONTROL:RECOVERY`. |

### 인증 완료·재개

- OAuth callback success alone으로 Run resume 0. Explicit `REAUTH_COMPLETED` command가 필요하다.
- Workflow resume 전에 `ResumeAfterReauth`가 반드시 `applied=true`여야 한다. Domain이 `REAUTH_REQUIRED`인 채 LangGraph만 직접 resume하면 실패다.
- `ResumeAfterReauth`는 저장된 안전 phase와 child execution predicate가 모두 여전히 유효할 때만 복귀한다.
- 이미 dispatch된 Write 재전송 0. Checkpoint 유실 → `RECOVERY_REQUIRED`.
- Cancel intent는 Reauth를 통과해 유지한다. 활성 상태에서 resume 후 신규 Claim·Write가 생기거나 cancel intent가 사라지면 실패다.

## Plan Supersession Child Authority

### Supersession Commit

Published Plan의 `BeginPlanning(REVISE|RETRIEVE_MORE|ROUTE_RECONSIDERATION)`과 `ResolveRecovery(CREATE_CORRECTIVE_PLAN)`은 다음을 같은 UoW에서 수행한다.

1. Old Plan의 `ACTIVE` Approval → `REVOKED`.
2. Plan → `SUPERSEDED` Commit.

둘 중 하나만 Commit되는 snapshot은 0이다. 새 Plan revision은 old Approval/idempotency/Attempt를 재사용하지 않고 fresh Review/Approval/Claim을 요구한다.

### Old Plan의 실행권 차단

Supersession Commit 뒤 old Plan의 `PROPOSED|MODIFIED|APPROVED|EXPIRED` Action은 history-only다. 다음 Command의 replay/late arrival은 `applied=false`, new Approval/Attempt/Write 0이어야 한다.

```text
ApproveAction | ModifyAction | RejectAction | CancelPendingAction
ExpireApproval | RefreshExpiredAction | PrepareWriteRetry | ClaimExecution
```

`ClaimExecution`은 Action/Approval/version/hash 외에 다음 조건도 같은 UoW에서 검증한다.

```text
owning Plan = current published WAITING_APPROVAL
+ Run = WAITING_APPROVAL|VERIFYING
+ cancel intent false
```

`Plan SUPERSEDED COMMIT → crash/restart → stale ClaimExecution(A_old, Approval_old)`에서 Attempt 0, Connector Write 0이다.

### BeginPlanning·ClaimExecution 경쟁

Concurrent `BeginPlanning` vs `ClaimExecution`은 다음 두 linearization만 허용한다. 두 UoW가 모두 성공하는 결과는 0이다.

| 먼저 적용된 처리 | 후속 검증 |
| --- | --- |
| supersession-first | stale Claim `applied=false`, Write 0. |
| claim-first | Action `EXECUTING`/Attempt `CLAIMED`를 BeginPlanning in-flight guard가 관측하여 supersession `applied=false`. |

## External Control Handoff / Crash Contract

### Commit·payload·target

Continuation-required lifecycle mutation과 `workflow_handoffs(PENDING)` insert는 같은 UoW다. 둘 중 하나만 Commit되는 snapshot은 0이다.

Confirmation/ContextAdjustment payload는 typed control envelope으로만 전달한다. Raw HTTP/interrupt/checkpoint metadata의 Prompt injection은 0이다.

| Applied control | Exact target |
| --- | --- |
| Approve | PREFLIGHT |
| Modify / PrepareRetry / RefreshExpiredAction | REVIEW_ENTRY |
| Reject | PREFLIGHT |
| Context Adjustment | RETRIEVAL_ENTRY |
| Cancel | CANCEL_RESOLUTION |

### Workflow execution admission linearization

`WorkflowExecutionPort.submit` 전에 durable `WorkflowExecutionAdmissionV1`이 존재해야 한다. Admission claim은 handoff expected version과 owning Run authority version을 **같은 SQLite transaction**에서 검증한다. Continuation legality를 바꾸는 child mutation도 Run version을 increment해야 한다.

| Admission 종류 | WEP 전 저장·상태 |
| --- | --- |
| NORMAL | current PENDING dispatch head를 `claim_execution_admission`으로 `DISPATCHED + admission`으로 claim. |
| CONSUMED recovery | status를 유지하며 latest descendant checkpoint를 RESUME effective binding admission으로 저장. |

Original START/PREFLIGHT/REVIEW binding과 latest descendant recovery binding을 혼동하지 않는다. CONSUMED recovery submission은 always existing-checkpoint RESUME이며 original START replay는 0이다.

### Submit 결과·release

| 결과·조건 | 기대 처리 |
| --- | --- |
| same `admission_id` replay | idempotent `ACCEPTED`, active admission release=0. |
| `ALREADY_RUNNING` | different-admission conflict만 의미. |
| non-ACCEPTED release + current Run authority epoch unchanged | pending latch 보존. `release_execution_admission`은 equal epoch에서만 NORMAL PENDING/BLOCKED 복구. |
| non-ACCEPTED release + newer Cancel/Reauth/Recovery/terminal로 epoch stale | NORMAL old head를 `SUPERSEDED`로 retire하여 후행 authority를 막지 않음. |
| non-ACCEPTED release의 recovery admission | CONSUMED 유지 + admission clear. |
| `SHUTTING_DOWN` + same authority epoch | pending 유지. |
| `BINDING_MISMATCH` | guessed resume 0 + checkpoint mismatch Recovery. |
| valid post-commit handoff의 `NOT_COMMITTED` | invariant failure, Domain replay 0. |

Non-ACCEPTED `release_execution_admission`은 current Run authority epoch도 재검사해야 한다.

### Crash 시점별 복구

WEP `ACCEPTED` 뒤 handoff persistence write는 0이다.

| Crash 시점 | 재시작·복구 검증 |
| --- | --- |
| Commit 후·submit 전 | duplicate control patch/Domain command 0. |
| Submit 후·consume 전 | duplicate control patch/Domain command 0. |
| Control-apply checkpoint 후·owner node 전 | duplicate control patch/Domain command 0. |
| Admission 후·submit 전 | 같은 persisted admission으로 복구. |
| ACCEPTED 후·worker 전 | 같은 persisted admission으로 복구. |
| Worker start 후·어떤 Application callback도 실행되기 전 | 같은 persisted admission으로 복구. |

### Durable multi-handoff ordering

- Same Run의 concurrent Approve/Modify/Reject handoff는 server-owned `run_sequence` commit order를 사용하며 lower unsettled sequence를 건너뛰지 않는다.
- Lower sequence가 CONSUMED/SUPERSEDED이고 current target guard가 여전히 유효할 때만 newer checkpoint generation으로 ordered rebind할 수 있다. Target 변경·rewind는 0이다.

Cancel/terminal resolution의 obsolete handoff 정리는 다음과 같이 검증한다.

| Handoff 상태 | 기대 처리 |
| --- | --- |
| execution admission 없는 PENDING/DISPATCHED/BLOCKED_BINDING | `supersede_unconsumed_for_run`으로 replacement stage 전에 같은 UoW에서 `SUPERSEDED` 처리. |
| admission이 이미 linearize된 row | 소급 revoke하지 않고 next safe boundary까지 먼저 settle. Cancel intent 이후 new Claim/Write=0. |
| admission 없는 BLOCKED_BINDING을 preempt | 별도 CHECKPOINT_MISMATCH Recovery=0. |

### CREATED·no checkpoint에서 취소

| START admission | 기대 처리 |
| --- | --- |
| 아직 없음 | PENDING/BLOCKED_BINDING START를 `SUPERSEDED` 처리. New RESUME=0. `run.continue_cancel_resolution`로 처리하며 Agent/LLM/Connector/LangGraph=0. |
| 이미 linearize된 DISPATCHED branch | row를 소급 supersede하지 않음. Initialization이 cancel intent를 Agent/LLM/Connector보다 먼저 처리. |

두 branch 모두 external effect=0, second click=0이다.

### Binding mismatch·CONSUMED continuation recovery

| 상황 | 기대 복구 |
| --- | --- |
| BLOCKED_BINDING→RequireRecovery 사이 crash 또는 live runtime mismatch | `system:handoff-binding-recovery:<handoff_id>`로 exactly-once reconciliation 후 SUPERSEDED. Process restart가 없어도 live reconciler가 수렴. |
| CONSUMED continuation crash | checkpoint의 `active_handoff_id/run_sequence` lineage를 initial entry와 1+/2+ descendant checkpoint에서 유지하고 `CONSUMED_CONTINUATION_RECOVERY` 사용. Generic SAFE_CHECKPOINT_RESUME가 아니며 payload reinjection 0. |

### Domain-progress fence

| Control·admission·settlement 순서 | 기대 결과 |
| --- | --- |
| Domain Reauth/Recovery/Cancel/terminal Commit이 admission claim보다 먼저 | old admission=0. Domain-progress fence 대상인 `REAUTH_REQUIRED\|RECOVERY_REQUIRED\|terminal\|cancel-incompatible CANCEL_REQUESTED`가 claim 전 durable이면 old admission/resume=0. |
| Admission claim 뒤 later control이 owner settlement 전에 Commit | settlement Run-version CAS는 `AUTHORITY_STALE_RETIRED`, old owner I/O=0. |
| Settlement가 먼저 Commit된 뒤 later control | 이미 linearize된 pure workflow segment를 소급 revoke하지 않음. Later control은 다음 durable guard에서 적용, cancel intent 이후 new Claim/Write=0. |

Settlement의 Run-version CAS는 `mark_consumed_and_clear_payload` / `complete_recovery_admission`에서 검증한다. `AUTHORITY_STALE_RETIRED`이면 다음을 확인한다.

- NORMAL stale admitted handoff는 같은 settlement transaction에서 `SUPERSEDED`로 retire한다.
- Recovery admission은 clear한다.
- Application reconciliation은 state-specific coordinator를 선택하고 후행 state-specific authority가 head blocking 없이 진행된다.

Current Action/Attempt/delivery facts와 registered target guard가 admission 시점에 불일치하면 claim 자체가 실패해야 한다.

## Retrieval Cache 재시작

### Checkpoint·cache 경계

| 검증 항목 | 기대 결과 |
| --- | --- |
| `RetrievalHeadV1` | stale CAS/restart CAS exact. |
| Application의 `checkpoint_blob` | deserialize 0. |
| `GraphCheckpointEnvelopeV1.retrieval_cache_requirements` | required `read_result_handle + route_id + query_identity_hash`만 포함. Raw continuation/content 0. |
| required Retrieval `read_result_handle`의 raw continuation | `RunRetrievalCachePort → InMemoryRunRetrievalCache`에만 존재. Domain/Main State/Checkpoint/Prompt/Trace/Audit에는 없음. |

### Resume prerequisite·restart

| Handle 상태 | 기대 결과 |
| --- | --- |
| `FOUND` | valid dependency. |
| `EXHAUSTED` | valid dependency. Restart 0, NEXT_PAGE Provider call 0. |
| missing / cross-run / route·query binding mismatch | Provider 호출 0. Required handle이 이 상태인 경우에만 cache restart stage. |

`run.reconcile_retrieval_cache_restart`는 아래 trigger를 dedupe하고 `RETRIEVAL_CACHE_RESTART → MAIN_CONTROL:RETRIEVAL_ENTRY`를 stage한다.

```text
system:retrieval-cache-restart:<run_id>:<checkpoint_generation>
```

Background/LangGraph adapter의 direct Repository write와 raw continuation 복원은 0이다.

### Restart 보존·terminal 정리

Cache restart는 다음을 보존하고 새 RetrievalResult revision을 만든다.

- frozen RequestIntent/InputRoute.
- consumed RunBudget.
- `exclusion_obligation_segment_ids`, `pending_user_retrieval_need`.

Terminal `discard_run(run_id)` 뒤 old handle resolve는 `MISSING`이다.

## Startup Safe Checkpoint Resume

`SAFE_CHECKPOINT_RESUME`는 lifecycle Command가 아니라 State Contract의 closed source-state gate를 사용하는 Application operation이다.

**허용 범위:** `CREATED | ANALYZING | RETRIEVING | PLANNING`에서만 다음 조건을 모두 만족해야 한다.

- Domain/Checkpoint/RegisteredResumeTarget/graph_version exact match.
- cancel intent false.
- unresolved `EXECUTING|UNKNOWN_RESULT` Write fact 0.

그 외 상태의 복원·재개 검증:

| Run 상태 | 기대 결과 |
| --- | --- |
| `WAITING_CONFIRMATION` | snapshot/interrupt restore only. 전용 `ResumeConfirmation` 전 LangGraph resume 0. |
| `WAITING_APPROVAL` | snapshot restore only. 사용자 Approval/Modify/Reject/Cancel 전 generic resume 0. |
| `REAUTH_REQUIRED` | `ResumeAfterReauth(applied=true)` 전 SAFE_CHECKPOINT_RESUME 0. |
| `RECOVERY_REQUIRED` | `ResolveRecovery`/Reauth 외 generic resume 0. |
| `CANCEL_REQUESTED` | cancel-resolution coordinator만 계속. Generic resume 0. |
| `EXECUTING \| VERIFYING` | persisted execution/verification fact reconciliation이 먼저. Dispatch/verification node generic replay 0. |
| terminal Run | snapshot 반환만 수행, resume 0. |

Checkpoint/registered target/graph version mismatch는 `RequireRecovery(CHECKPOINT_MISMATCH)`로 fail closed한다.

## Insufficient Data Guard

| 부족 정보·조건 | 기대 결과 |
| --- | --- |
| safety-critical/POLICY required issue | BLOCKED |
| USER required issue | NEEDS_CONFIRMATION |
| external-source required issue + budget | RETRIEVE_MORE |
| budget exhausted + usable Evidence | PARTIAL |
| budget exhausted + usable Evidence 없음 | CompleteAnswerOnlyRun |

Write 필수 정보가 부족하면 PARTIAL로 실행 진행을 허용하지 않는다. SINGLE/THREE/SIX는 동일 semantic guard를 적용한다.

## Retrieval·Answer-only Terminalization

`Retrieval.PARTIAL + usable Evidence 없음`인 비Terminal Run은 직접 FINALIZE로 가지 않는다. 처리 불가 안내를 저장하는 `CompleteAnswerOnlyRun → COMPLETED`가 먼저 적용돼야 한다.

| 저장 경계 | 기대 결과 |
| --- | --- |
| Answer-only terminal UoW | Plan·Action 없이 final ASSISTANT Message + Run terminal mutation + required Audit를 원자 저장. |
| Diagnostic Trace/SSE | post-commit. Terminal UoW rollback 대상이 아님. |

## READ Action lifecycle·Legacy Compatibility

일반 Release Retrieval READ는 Action Row를 생성하지 않는다. Legacy READ-only Plan은 Approval·ExecutionAttempt·Verification Row 0이며, READ Claim 경쟁은 하나만 성공해야 한다.

### Action lifecycle

| Command·조건 | 기대 전이·검증 |
| --- | --- |
| `ClaimReadAction` | READ Action `PROPOSED → EXECUTING`. Approval/ExecutionAttempt/Verification row 생성 0. |
| `CompleteReadAction` | READ Action `EXECUTING → EXECUTED`. Typed Read Output Schema validation 성공 뒤에만 적용. |
| `FinalizeReadAction` | successful READ Action `EXECUTED → VERIFIED`. Write Verification row 생성 0. |
| `FailReadAction` | READ Action `EXECUTING → FAILED`. 같은 Action을 성공으로 위장하거나 무한 자동 retry하지 않음. |
| Output Schema 실패 | `EXECUTING → FAILED`. |

READ `VERIFIED`는 Write Verification 통계에 포함하지 않는다.

### Legacy READ-only completion

`PublishReadOnlyPlan → Run EXECUTING + Plan ACTIVE` 뒤 모든 READ Action이 `VERIFIED | FAILED`가 되면 **`CompleteReadOnlyRun`만** Run/Plan을 `COMPLETED`로 닫는다.

| READ Action 결과 | Run result kind |
| --- | --- |
| 하나라도 FAILED | PARTIAL |
| 전부 VERIFIED | SUCCESS |

`Run EXECUTING`에서 Domain Command 없이 FINALIZE하거나 `CompleteAnswerOnlyRun/CompleteWriteRun`으로 닫으면 실패다.

## Unknown Contract

| 검증 단계 | 기대 결과 |
| --- | --- |
| Unknown Enum/Version/Disposition | bounded repair 1회. |
| Repair 뒤에도 invalid | `RequireRecovery(CONTRACT_VIOLATION) → RECOVERY_REQUIRED`. |
| Invalid contract의 후속 실행 | 추측 Routing·다음 Agent·MCP Write·직접 FINALIZE 0. |
| 복구 불가 확정 | 이때만 `ResolveRecovery(FAIL) → FAILED`. |

## Connector Boundary

React·FastAPI Route·Application·LangGraph·Agent·Domain의 Provider API/SDK 직접 호출은 0이다.

Browse/Count/Detail/Retrieval/Write/Verification/Recovery 조회는 다음 경계를 통과해야 한다.

```text
Application operation
→ Application SignedToolRegistry binding
→ Connector Application Port
→ Core-side Connector Adapter
→ ConnectorRuntimeRegistry + MCPClientPort
→ MCP
```

Application의 adapter-level registry/client 직접 호출은 0이다. Connector MCP unavailable/Schema invalid 때 Core direct Provider fallback도 0이다.
