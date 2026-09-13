# Domain 상태 전이 계약 v1.9

> **선행 읽기:** `00 → 01-B Policy → 03 Architecture → 04 Domain·DB`  
> **이 문서의 역할:** lifecycle command·guard·transition. 선행 문서의 의미를 재정의하지 않는다.  
> **수정일:** 2026-09-07

## 책임

| 책임 주체 | 역할 |
| --- | --- |
| LangGraph Supervisor | Node·Edge·Interrupt·bounded loop 선택 |
| Application | Use Case·Command Receipt·외부 호출 조정, Canonical Request Hash 계산 |
| Domain | Guard와 허용 전이의 유일한 권위 |
| Repository | 조건부 UPDATE·필수 Audit·Receipt Transaction |
| SQLite | 04가 정의한 Constraint·동시성·cross-aggregate invariant의 implementation final defense |

## 공통 Command Result

`applied`, `result_code`, `current_status`, `current_version`, `next_allowed_commands`, `conflict_detail`

`applied=false`를 성공으로 추정하거나 같은 Command를 무조건 재시도하지 않는다. Application은 `current_status + next_allowed_commands`로 재조정한다.

## Command Receipt

모든 상태 변경 Command는 `command_id`와 서버가 Versioned Request Schema에서 계산한 Canonical Request Hash를 사용한다. Receipt 검증은 Domain child mutation보다 먼저 수행하고 Receipt와 Domain 변경은 같은 Transaction으로 완료한다.

| Receipt 비교 | 처리 |
| --- | --- |
| 같은 `command_id + 같은 hash` | 기존 결과 반환 |
| 같은 `command_id + 다른 hash` | Conflict, Domain 변경 0 |

성공한 `RequestCancel` Receipt는 Run이 `CANCELLED`로 닫힐 때까지 durable cancel intent의 기준점이다.

## Closed status vocabulary

Lifecycle implementation may use only the following current status values. Persistence may store them; only commands in this contract may change them.

```text
RunStatusV1 = CREATED | ANALYZING | RETRIEVING | WAITING_CONFIRMATION | PLANNING | WAITING_APPROVAL | EXECUTING | VERIFYING | CANCEL_REQUESTED | REAUTH_REQUIRED | RECOVERY_REQUIRED | COMPLETED | BLOCKED | FAILED | CANCELLED
ActionStatusV1 = PROPOSED | MODIFIED | APPROVED | EXPIRED | EXECUTING | EXECUTED | UNKNOWN_RESULT | FAILED | VERIFIED | MISMATCH | REJECTED | BLOCKED | CANCELLED | DEPENDENCY_BLOCKED
PlanStatusV1 = DRAFT | WAITING_APPROVAL | ACTIVE | SUPERSEDED | CANCELLED | COMPLETED
ApprovalStatusV1 = ACTIVE | EXPIRED | CONSUMED | REVOKED
ExecutionAttemptStatusV1 = CLAIMED | EXECUTING | SUCCEEDED | FAILED | UNKNOWN_RESULT
RecoveryReasonV1 = UNKNOWN_RESULT | VERIFICATION_MISMATCH | CHECKPOINT_MISMATCH | CONTRACT_VIOLATION
```

| 구분 | 규칙 |
| --- | --- |
| Run terminal | Run terminal: `COMPLETED \| BLOCKED \| FAILED \| CANCELLED`. |
| Plan ACTIVE | Plan `ACTIVE` is legacy/compatibility READ-only only. Release approval-gated Write Plan persists as `WAITING_APPROVAL` through Action execution and becomes `COMPLETED \| CANCELLED \| SUPERSEDED` only by the commands described below. |
| Action final fact | Action final fact: `VERIFIED \| MISMATCH \| REJECTED \| BLOCKED \| CANCELLED \| DEPENDENCY_BLOCKED`. `FAILED` is a stable retry-decision state, not successful completion; `UNKNOWN_RESULT` is unresolved and never terminal for execution safety. |
| Run EXECUTING | `EXECUTING` Run status is retained only for the explicit legacy/compatibility READ path. Release approval-gated Write execution keeps Run in `WAITING_APPROVAL` until first Write verification enters `VERIFYING`. |
| 비Terminal | “비Terminal” in this contract means exactly the closed RunStatusV1 set minus the four Run terminal values; it is not an implementation-defined extension point. |

## External-control continuation boundary (non-lifecycle)

이 계약은 lifecycle transition만 소유하며 background scheduling 자체를 새 Command로 만들지 않는다.

다만 external user control을 적용하는 Application handler가 continuation을 요구하면 **해당 lifecycle mutation/Receipt/Audit과 04 durable handoff obligation이 같은 UoW 경계에서 보존되어야 commit 가능**하다.

| 상황 | Continuation 처리 |
| --- | --- |
| 일반 | 일반적으로 새 `workflow_handoffs(PENDING)` row를 stage한다. |
| 첫 checkpoint 전 RequestCancel | 단 `Run=CREATED + first checkpoint 없음 + original START handoff unsettled`에서의 `RequestCancel`은 새 RESUME row를 만들 수 없으므로 cancel intent를 commit하고 existing START obligation을 재사용한다. |
| Initialization | Initialization은 이 cancel intent를 Agent/LLM/Connector보다 먼저 검사해 `CANCEL_RESOLUTION`으로 간다. |

Post-commit sequence/supersession/restart semantics는 04/06/07/08이 소유한다.

Context Adjustment의 `expected_retrieval_revision`은 04/07 `RetrievalHeadV1`의 current revision을 사용한다. Plan revision/Run version/checkpoint blob private field를 대체 authority로 사용하지 않는다.

## Run Command

### 시작·검색·계획

| Command | 허용 전이·조건 |
| --- | --- |
| StartRun | Conversation Open Run 없음 → CREATED |
| StartAnalysis | CREATED → ANALYZING |
| BeginRetrieval | ANALYZING · PLANNING → RETRIEVING. 이미 RETRIEVING인 local loop에서는 반복 호출 금지 |

#### BeginPlanning

| 항목 | 규칙 |
| --- | --- |
| 기본 전이 | ANALYZING · RETRIEVING → PLANNING. |
| Published Plan 재검토 | Published Plan 재검토에서는 `WAITING_APPROVAL \| VERIFYING → PLANNING`을 허용하되 current durable Review disposition이 `REVISE \| RETRIEVE_MORE \| ROUTE_RECONSIDERATION`이고 unresolved in-flight(`EXECUTING \| UNKNOWN_RESULT \| EXECUTED` awaiting verification)와 unresolved MISMATCH가 0이어야 한다. |
| 사용자 Context Adjustment 조건 | **사용자 Context Adjustment branch**는 `WAITING_APPROVAL`에서만 허용하며 current Plan 존재, 모든 current Action=`PROPOSED\|MODIFIED`, ACTIVE Approval=0, unresolved/in-flight external effect=0, expected Run/Retrieval revision 일치를 요구한다. |
| Context Adjustment 전달 | 이 branch는 `EXCLUDE_EVIDENCE \| RETRIEVE_MORE`를 normalized `ContextAdjustmentV1`으로 same Run Retrieval owner에 전달한다. |
| Plan 교체·기존 사실 보존 | 같은 UoW에서 아래 Plan supersession child-authority fence를 적용해 current Plan을 `SUPERSEDED`하고 이미 발생한 외부 Write 및 terminal Action fact는 immutable history로 보존한다. |
| 새 Plan revision | 새 Plan revision은 남은 업무만 계획하며 `VERIFIED \| MISMATCH \| FAILED` Action을 재실행 대상으로 복사하지 않는다. |
| 반복 호출 | 이미 PLANNING인 bounded revision에서는 반복 호출 금지 |

### 확인

| Command | 허용 전이·조건 |
| --- | --- |
| RequestConfirmation | ANALYZING · RETRIEVING · PLANNING · WAITING_APPROVAL · VERIFYING → WAITING_CONFIRMATION; semantic_owner_id + AgentNodeResumeTargetV2 + interrupt_id + `pre_confirmation_status` 저장.<br>`WAITING_APPROVAL \| VERIFYING` source는 current durable Review disposition=`CONFIRM`이고 unresolved in-flight/UNKNOWN_RESULT/MISMATCH가 0일 때만 허용한다 |
| ResumeConfirmation | WAITING_CONFIRMATION → 발생 전 안전 Domain 상태; same owner checkpoint resume |

### 완료·게시·검증

| Command | 허용 전이·조건 |
| --- | --- |
| CompleteAnswerOnlyRun | ANALYZING · RETRIEVING · PLANNING → COMPLETED; Plan·Action 없음 + Open Write/실행 중 READ/미해결 Recovery 없음 |
| CompleteReadOnlyRun | Legacy/호환 READ-only: Run EXECUTING → COMPLETED + current Plan ACTIVE → COMPLETED; 모든 READ Action이 `VERIFIED \| FAILED`이고 실행 중 Action 0. 하나라도 FAILED면 terminal result kind는 PARTIAL, 전부 VERIFIED면 SUCCESS |
| PublishPlan | Run PLANNING → WAITING_APPROVAL + persisted Plan DRAFT → WAITING_APPROVAL |
| PublishReadOnlyPlan | Legacy/호환 READ-only Plan: Run PLANNING → EXECUTING + Plan DRAFT → ACTIVE |
| BeginVerification | WAITING_APPROVAL · CANCEL_REQUESTED → VERIFYING. 정상 승인형 Write는 Action 실행 중 Run을 WAITING_APPROVAL에 유지한다 |
| CompleteWriteRun | WAITING_APPROVAL · VERIFYING → COMPLETED; current Plan → COMPLETED.<br>모든 planned Action이 final fact이거나 사용자 Reject/Cancel/Dependency Block으로 닫혀 있고 unresolved `UNKNOWN_RESULT/MISMATCH` 0 + cancel_intent_active=false 필요.<br>외부 Write가 한 건도 시작되지 않은 all-rejected/all-cancelled plan은 WAITING_APPROVAL에서 닫을 수 있다 |

### 차단

#### BlockRun

| 항목 | 규칙 |
| --- | --- |
| 허용 전이·기본 조건 | CREATED · ANALYZING · RETRIEVING · WAITING_CONFIRMATION · PLANNING · WAITING_APPROVAL · VERIFYING → BLOCKED; Active/Unknown/미검증 Write Attempt 및 unresolved MISMATCH 없음. |
| VERIFYING 추가 조건 | `VERIFYING` source는 published Plan의 current durable Review disposition=`BLOCK`이고 이미 dispatch된 Write가 모두 durable final일 때만 허용한다. |
| Plan 존재 시 정리 순서 | Plan 존재 시 모든 미실행 nonterminal Action(`PROPOSED \| MODIFIED \| APPROVED \| EXPIRED`) → `BLOCKED` → ACTIVE Approval `REVOKED` → Plan `CANCELLED` → Run `BLOCKED` 순서. |
| 보존할 Action fact | `VERIFIED \| MISMATCH \| FAILED \| REJECTED \| CANCELLED \| DEPENDENCY_BLOCKED` 등 이미 확정된 Action fact는 보존 |

### 취소

| Command | 허용 전이·조건 |
| --- | --- |
| RequestCancel | 모든 비Terminal Run → CANCEL_REQUESTED. Receipt/expected_version 판정을 먼저 수행하고 APPLIED Receipt로 durable cancel intent를 활성화한다. 전이와 같은 UoW에서 새 Claim·Write authority 생성은 0이며, 이미 in-flight인 Action 상태는 덮어쓰지 않는다 |

#### FinalizeCancel

| 항목 | 규칙 |
| --- | --- |
| 허용 전이·종료 조건 | CANCEL_REQUESTED · VERIFYING · REAUTH_REQUIRED → CANCELLED; cancel intent가 active이고 Action `EXECUTING \| UNKNOWN_RESULT \| EXECUTED`(verification 미완료)가 0이어야 한다. |
| Pending Action·Approval 정리 | 모든 pending `PROPOSED \| MODIFIED \| APPROVED \| EXPIRED`는 먼저 개별 `CancelPendingAction`으로 `CANCELLED` 처리하고 ACTIVE Approval은 0이어야 한다. |
| 닫힌 사실로 인정하는 Action | `VERIFIED \| MISMATCH \| FAILED \| REJECTED \| BLOCKED \| CANCELLED \| DEPENDENCY_BLOCKED`는 cancel-final guard에서 닫힌 사실로 인정하고 보존한다. |
| Plan 종료 | current nonterminal Plan → CANCELLED |

### 재인증

#### RequireReauth

| 항목 | 규칙 |
| --- | --- |
| 허용 전이·보존 정보 | ANALYZING · RETRIEVING · PLANNING · WAITING_APPROVAL · EXECUTING · VERIFYING · CANCEL_REQUESTED · RECOVERY_REQUIRED → REAUTH_REQUIRED; `pre_reauth_status`와 registered same-run resume target을 checkpoint에 보존한다. |
| Target 검증 | target legality는 **Run status만이 아니라 current child execution fact(Action/ExecutionAttempt/delivery certainty)**까지 검증하는 아래 Reauth matrix를 따른다. |
| 취소 중 Legacy READ | 단 `cancel_intent_active=true`인 Legacy READ Action은 새 Reauth를 시작하지 않고 아래 Legacy READ cancel settlement로 닫는다 |

#### ResumeAfterReauth

| 항목 | 규칙 |
| --- | --- |
| 허용 전이·Binding 검증 | REAUTH_REQUIRED → checkpoint의 `pre_reauth_status`; registered target/graph_version/current Run binding과 Reauth matrix의 child-fact predicate가 모두 유효해야 한다. |
| PREFLIGHT·READ_EXECUTION 조건 | `PREFLIGHT` target은 in-flight Write fact가 0일 때만 허용하고, `READ_EXECUTION`은 **cancel_intent_active=false**인 Legacy READ Action `EXECUTING` + ExecutionAttempt 없음일 때만 허용한다. |
| 취소 중 Legacy READ | cancel intent가 활성화되면 READ_EXECUTION 재개/새 ConnectorRead는 0이며 아래 Legacy READ cancel settlement를 우선한다. |
| 취소 중 승인형 Write | 승인형 Write는 cancel intent가 활성인 경우 새 Claim·Write 0을 유지하고 `CANCEL_REQUESTED \| VERIFYING \| RECOVERY_REQUIRED` 경로의 취소 우선 규칙을 따른다. |
| 재전송 금지 | 이미 dispatch된 Write 재전송 금지 |

### 복구

| Command | 허용 전이·조건 |
| --- | --- |
| RequireRecovery | 비Terminal → RECOVERY_REQUIRED; `RecoveryReasonV1`, `pre_recovery_status`, recovery scope/target, reason-specific required refs, `recovery_fingerprint`, last observed/recheck fingerprint, optional registered resume target을 `RecoveryContextV1`로 durable하게 보존한다.<br>Process-local/private state만으로 resolution legality를 결정하지 않는다 |

#### ResolveRecovery(RECHECK)

| 항목 | 규칙 |
| --- | --- |
| 허용 전이 | RECOVERY_REQUIRED → reason-specific safe target. |
| 진행 조건 | `RecoveryContextV1`의 required recheck input이 직전 round와 달라지고 reason별 success predicate를 만족해야 한다. |
| Reason별 복귀 대상 | `UNKNOWN_RESULT` recovered-to-EXECUTED 또는 `VERIFICATION_MISMATCH`는 VERIFYING, `UNKNOWN_RESULT` resolved-to-FAILED는 `pre_recovery_status`, `CHECKPOINT_MISMATCH \| CONTRACT_VIOLATION`은 검증된 `pre_recovery_status/registered resume target`으로 복귀한다. |
| 새 정보 없음 | Same-input/no-new-information이면 `applied=false / NO_PROGRESS`로 RECOVERY_REQUIRED 유지 |

#### ResolveRecovery — 종료·새 계획

| Command | 허용 전이·조건 |
| --- | --- |
| ResolveRecovery(ACCEPT_PARTIAL) | `VERIFICATION_MISMATCH` Recovery에서만 RECOVERY_REQUIRED → COMPLETED + PARTIAL, `cancel_intent_active=false` 필요.<br>pending `PROPOSED \| MODIFIED \| APPROVED \| EXPIRED` → `CANCELLED`, ACTIVE Approval → `REVOKED`, current Plan → `COMPLETED`; 기존 `VERIFIED \| MISMATCH \| FAILED \| REJECTED \| BLOCKED \| CANCELLED \| DEPENDENCY_BLOCKED` fact는 보존 |
| ResolveRecovery(CREATE_CORRECTIVE_PLAN) | RECOVERY_REQUIRED → PLANNING + current Plan → SUPERSEDED + 새 Plan Revision, `cancel_intent_active=false` 필요. Plan supersession은 아래 child-authority fence를 적용해 같은 UoW에서 old ACTIVE Approval을 REVOKED로 닫고 old child execution authority를 제거한다 |
| ResolveRecovery(CANCEL) | RECOVERY_REQUIRED → CANCELLED; `cancel_intent_active=true`, unresolved `EXECUTING \| UNKNOWN_RESULT \| EXECUTED`(verification 미완료)=0 필요.<br>pending `PROPOSED \| MODIFIED \| APPROVED \| EXPIRED` → `CANCELLED`, ACTIVE Approval → `REVOKED`, current nonterminal Plan → `CANCELLED`; 기존 확정 Action fact는 보존 |
| ResolveRecovery(FAIL) | reason matrix가 FAIL을 허용하고 복구 불가가 확정되며 unresolved external-delivery uncertainty가 0일 때 RECOVERY_REQUIRED → FAILED.<br>pending `PROPOSED \| MODIFIED \| APPROVED \| EXPIRED` → `BLOCKED`, ACTIVE Approval → `REVOKED`, current nonterminal Plan → `CANCELLED`; 기존 확정 Action fact는 보존 |

### Bootstrap Cancel ordering

`CREATED + first checkpoint 없음`의 bootstrap cancel은 admission ordering을 따른다.

| 항목 | 처리 |
| --- | --- |
| START admission 이전 | START에 durable execution admission이 아직 없으면 (`PENDING \| BLOCKED_BINDING`) RequestCancel APPLIED와 같은 UoW에서 START를 SUPERSEDED로 retire하고 existing Application `run.continue_cancel_resolution`이 Graph 없이 deterministic settlement를 수행한다. |
| START admission 이후 | START admission이 이미 선형화되어 `DISPATCHED + execution_admission`이면 그 authority를 소급 revoke하지 않는다. |
| Initialization | Initialization은 durable cancel intent를 Agent/LLM/Connector보다 먼저 확인해 CANCEL_RESOLUTION로 향하며 새 external effect는 0이다. |
| 사용자 조작 | 어느 race에서도 두 번째 Cancel click은 요구하지 않는다. |

### Registered resume target scope

Lifecycle commands store/consume `RegisteredResumeTargetRefV2` but do not invent graph identity.

| 항목 | 규칙 |
| --- | --- |
| Confirmation | Confirmation always stores `AgentNodeResumeTargetV2` with `semantic_owner_id`. |
| Global Main Control closed set | 06/16 `ResumeTargetRegistry`의 global Main Control closed set은 `RETRIEVAL_ENTRY \| PLANNING_ENTRY \| REVIEW_ENTRY \| PREFLIGHT \| READ_EXECUTION \| VERIFICATION \| RECOVERY \| CANCEL_RESOLUTION`다. |
| Reauth·Recovery 선택 | Reauth/Recovery는 이 set 전체를 임의 선택하지 않고 suspend 직전 semantics가 허용하는 Agent Node 또는 safe Main Control target만 저장한다. |
| External-control 발급 조건 | `RETRIEVAL_ENTRY \| PLANNING_ENTRY \| REVIEW_ENTRY \| CANCEL_RESOLUTION`은 06 external-control matrix의 owning command가 요구하는 경우에만 발급된다. |
| ACTION_EXECUTION | `ACTION_EXECUTION` is never a replay/resume target after `BeginExecutionAttempt`. |
| 승인형 Write in-flight 판정 | **승인형 Write의 in-flight 여부는 Run.status가 아니라 current ExecutionAttempt/delivery fact로 판정**하고, `WAITING_APPROVAL + Attempt EXECUTING/uncertain`은 preflight rewind 없이 Verification/Recovery reconciliation으로 간다. |
| Legacy READ | `Run=EXECUTING`은 Legacy READ-only 경로이므로 `Action EXECUTING + ExecutionAttempt 없음`일 때만 `MAIN_CONTROL:READ_EXECUTION`을 사용할 수 있다. |

### Reauth source-state + child execution fact matrix

`Run.status`만 보고 Resume target을 정하지 않는다. 승인형 Write와 Legacy READ가 같은 `EXECUTING` vocabulary를 다른 aggregate layer에서 사용하므로 아래 조합을 closed set으로 사용한다.

| pre_reauth_status + current child fact | registered target | 규칙 |
|---|---|---|
| `ANALYZING \| RETRIEVING \| PLANNING` + owner Agent safe node | `AGENT_NODE` | same semantic owner/profile/compiled-subgraph/node만 허용 |
| `WAITING_APPROVAL` + current Write `ExecutionAttempt`가 `EXECUTING \| UNKNOWN_RESULT \| SUCCEEDED`-awaiting-verification이 아님 + BeginExecutionAttempt 전 credential failure | `MAIN_CONTROL:PREFLIGHT` | pre-dispatch only. current in-flight Write fact가 생기면 이 target은 invalid |
| `WAITING_APPROVAL` + current Write Attempt `EXECUTING` 또는 delivery certainty가 불명확 | `MAIN_CONTROL:VERIFICATION \| RECOVERY` | `PREFLIGHT` 금지. delivery/existing-result를 먼저 확정하고 durable `EXECUTED`면 Verification, uncertain/`UNKNOWN_RESULT`면 Recovery |
| `EXECUTING` + Legacy READ Action `EXECUTING` + **ExecutionAttempt row 없음** + `AUTH_EXPIRED` | `MAIN_CONTROL:READ_EXECUTION` | non-mutating READ-only resume. 같은 READ Action/route만 재개하며 Write/Attempt 생성 0 |
| `VERIFYING` + verification read credential failure | `MAIN_CONTROL:VERIFICATION` | verification reread만 재개 |
| `RECOVERY_REQUIRED` + recovery lookup credential failure | `MAIN_CONTROL:RECOVERY` | recovery lookup/recheck만 재개 |
| `CANCEL_REQUESTED` | current fact를 닫는 `VERIFICATION \| RECOVERY` | generic execution replay 금지; cancel intent 유지 |

`Run=WAITING_APPROVAL`이라는 이유만으로 `PREFLIGHT`를 선택하면 안 된다. current Attempt가 이미 `EXECUTING`이면 승인형 Write는 시작된 것이므로 pre-dispatch checkpoint로 rewind하지 않는다. 반대로 `Run=EXECUTING`은 current Release Write의 상태가 아니라 **Legacy/compatibility READ-only Run status**이며, 이 경로는 ExecutionAttempt row를 만들지 않는다.

### Legacy READ cancel settlement

Legacy/compatibility READ-only Run은 `ExecutionAttempt`를 만들지 않지만 `RequestCancel` 이후에도 `FinalizeCancel` guard를 만족하려면 current READ Action을 먼저 terminal fact로 닫아야 한다. **새 lifecycle Command를 만들지 않고 기존 READ/Cancel Command만 사용한다.**

| Cancel 시점 | Required settlement |
|---|---|
| `READ PROPOSED` / `ClaimReadAction` 전 | `CancelPendingAction → CANCELLED`, 그 뒤 unresolved child=0이면 `FinalizeCancel` |
| `READ EXECUTING` / ConnectorRead 미dispatch | 새 ConnectorRead 0 → `FailReadAction → FAILED` → `FinalizeCancel` |
| `READ EXECUTING` / ConnectorRead 이미 in-flight | 요청을 새로 retry/reauth하지 않는다. typed success가 돌아오면 `CompleteReadAction → FinalizeReadAction → VERIFIED`; failure·`AUTH_EXPIRED`·transport interruption이면 `FailReadAction → FAILED`; 그 뒤 `FinalizeCancel` |
| `READ EXECUTED` / 아직 FinalizeReadAction 전 | `FinalizeReadAction → VERIFIED` → `FinalizeCancel` |
| process crash/restart + durable cancel intent + READ `EXECUTING` | non-mutating READ를 재호출하지 않는다. persisted Action/Receipt만으로 `FailReadAction → FAILED`로 settle한 뒤 `FinalizeCancel` |

`cancel_intent_active=true`인 Legacy READ에서는 `MAIN_CONTROL:READ_EXECUTION` Reauth target을 새로 등록하거나 ResumeAfterReauth로 READ를 재개하지 않는다. 이미 Reauth suspend 중에 `RequestCancel`이 적용되면 cancel coordinator가 READ Action을 위 표로 settle한다. `FAILED | VERIFIED | CANCELLED` READ Action은 `FinalizeCancel` guard의 closed fact이며 Run terminal result는 외부 mutation이 없으므로 `CANCELLED`다.

### Published Plan post-review lifecycle matrix

Published Plan의 Review/Preflight 결과가 첫 승인 전뿐 아니라 다중 Action DAG의 후속 Action에서도 발생할 수 있으므로 source-state별 처리를 다음 closed matrix로 고정한다.

| Current Run | Durable Review disposition | Required lifecycle handling |
|---|---|---|
| `WAITING_APPROVAL \| VERIFYING` | `PASS` | Run transition 없음. current Plan/Action version에 bound된 PASS만 다음 Preflight/Claim으로 진행 |
| `WAITING_APPROVAL \| VERIFYING` | `REVISE \| RETRIEVE_MORE \| ROUTE_RECONSIDERATION` | `BeginPlanning`; 아래 child-authority fence와 같은 UoW로 current Plan `SUPERSEDED`, 이미 발생한 외부 effect/terminal Action fact 보존, 새 revision은 남은 업무만 재계획 |
| `WAITING_APPROVAL \| VERIFYING` | `CONFIRM` | `RequestConfirmation`; `pre_confirmation_status`를 보존하고 응답 후 `ResumeConfirmation`으로 같은 Review owner checkpoint에 복귀 |
| `WAITING_APPROVAL \| VERIFYING` | `BLOCK` | `BlockRun`; 단 unresolved in-flight/UNKNOWN_RESULT/unverified EXECUTED/MISMATCH가 0이어야 하며 이미 성공/실패가 확정된 Action fact는 덮어쓰지 않음 |

`VERIFYING`에서 위 matrix를 사용하는 것은 **첫 Write 이후 남은 Action의 stale/policy/review 변화**에만 해당한다. 이미 dispatch된 Action을 Planning/Confirmation/Block 때문에 재전송하거나 되돌리지 않는다.

### Plan supersession child-authority fence

`BeginPlanning`의 published-Plan branch와 `ResolveRecovery(CREATE_CORRECTIVE_PLAN)`가 current published Plan을 `SUPERSEDED`로 바꾸는 경우, supersession은 child execution authority까지 같은 UoW에서 닫는다.

- Plan status를 `SUPERSEDED`로 쓰기 전에 그 Plan의 Action에 연결된 모든 `ACTIVE` Approval을 `REVOKED`로 전이한다. 이 revoke와 Plan supersession 중 하나만 commit되는 snapshot은 허용하지 않는다.
- 이미 확정된 `VERIFIED | MISMATCH | FAILED | REJECTED | BLOCKED | CANCELLED | DEPENDENCY_BLOCKED` Action fact는 immutable history로 보존한다. 아직 외부 effect가 시작되지 않은 `PROPOSED | MODIFIED | APPROVED | EXPIRED` row도 이전 Plan의 historical proposal로 보존할 수 있으나, supersession commit 이후에는 execution/mutation authority가 아니다.
- `SUPERSEDED` Plan에 속한 Action에 대한 `ApproveAction | ModifyAction | RejectAction | CancelPendingAction | ExpireApproval | RefreshExpiredAction | ClaimExecution | PrepareWriteRetry`는 `applied=false`다. Application은 current Plan/Run snapshot으로 재조정하며 old Plan에 새 Approval/Attempt/Write를 만들지 않는다.
- `ClaimExecution`은 `Action=APPROVED + Approval=ACTIVE`만으로 충분하지 않다. owning Plan이 **current published Plan**이고 `Plan.status=WAITING_APPROVAL`, Run이 `WAITING_APPROVAL | VERIFYING`, `cancel_intent_active=false`여야 한다. 이 parent-authority fence와 Action/Approval/version/hash guard를 같은 Claim UoW에서 재검사한다.
- 새 Plan revision은 superseded Plan의 Approval/idempotency/Attempt authority를 재사용하지 않는다. 남은 업무를 새 Action으로 materialize하고 필요한 Write는 fresh Review/Approval/Claim을 거친다.

Concurrency linearization도 closed다.

| 순서·상황 | 결과 |
| --- | --- |
| Supersession UoW 선행 | Supersession UoW가 먼저 commit되면 늦은 `ClaimExecution`은 parent-plan fence에서 effect 0이다. |
| ClaimExecution UoW 선행 | `ClaimExecution` UoW가 먼저 commit되어 Action=`EXECUTING`/Attempt=`CLAIMED`가 되면 기존 `BeginPlanning`의 unresolved in-flight guard가 supersession을 허용하지 않는다. |
| 늦은 요청·재시작 | 따라서 `Plan SUPERSEDED COMMIT → 늦게 도착한 old approve/modify/claim`은 read-only history 조회 외에는 모두 effect 0이며, process crash/restart 뒤에도 old child authority가 되살아나지 않는다. |

### RecoveryContextV1 closed contract and reason matrix

`RecoveryReasonV1`은 vocabulary만 닫는 것으로 충분하지 않다. `RequireRecovery`가 다음 logical context를 durable하게 보존해야 하며 exact DB column/record shape는 04의 implementation choice다.

```text
RecoveryContextV1
- reason: RecoveryReasonV1
- scope: RUN | ACTION
- action_id?: required when scope=ACTION
- execution_attempt_id?: reason-specific
- verification_id?: reason-specific
- pre_recovery_status: RunStatusV1
- registered_resume_target?: RegisteredResumeTargetRefV2
- recovery_fingerprint
- observed_external_state_fingerprint?
- verification_input_fingerprint?
- contract_or_checkpoint_fingerprint?
- last_recheck_input_hash?
```

#### `UNKNOWN_RESULT`

| 항목 | 계약 |
| --- | --- |
| Scope·보존할 Context | ACTION; Action/Attempt, effect-specific lookup strategy/target, `pre_recovery_status`, lookup fingerprint |
| RECHECK 성공 대상 | lookup + `RecoverExistingResult`로 Action `EXECUTED`면 `VERIFYING`; lookup + `ResolveAsFailed`로 Action `FAILED`면 `pre_recovery_status`; 아직 UNKNOWN이면 `NO_PROGRESS` |
| 허용 resolution | `RECHECK`; cancel intent가 있고 UNKNOWN이 해소된 terminal snapshot이면 `CANCEL` |
| Reason 미해결 동안 금지 | unresolved `UNKNOWN_RESULT` 상태에서 `ACCEPT_PARTIAL`, `CREATE_CORRECTIVE_PLAN`, `FAIL`, blind resend |

#### `VERIFICATION_MISMATCH`

| 항목 | 계약 |
| --- | --- |
| Scope·보존할 Context | ACTION; Action/Attempt/Verification, expected/actual/diff fingerprint, `pre_recovery_status` |
| RECHECK 성공 대상 | changed verification input을 대상으로 `VERIFYING` |
| 허용 resolution | `RECHECK`, `ACCEPT_PARTIAL`, `CREATE_CORRECTIVE_PLAN`, guarded `CANCEL`, unrecoverable `FAIL` |
| Reason 미해결 동안 금지 | cancel intent active일 때 `ACCEPT_PARTIAL`, `CREATE_CORRECTIVE_PLAN` |

#### `CHECKPOINT_MISMATCH`

| 항목 | 계약 |
| --- | --- |
| Scope·보존할 Context | RUN; `pre_recovery_status`, thread/checkpoint/registered-target/graph-version fingerprint |
| RECHECK 성공 대상 | current binding이 다시 유효하면 validated `pre_recovery_status + registered target` |
| 허용 resolution | `RECHECK`, unrecoverable `FAIL`, cancel intent + external unresolved 0이면 `CANCEL` |
| Reason 미해결 동안 금지 | `ACCEPT_PARTIAL`, `CREATE_CORRECTIVE_PLAN`, 임의 checkpoint 추측 resume |

#### `CONTRACT_VIOLATION`

| 항목 | 계약 |
| --- | --- |
| Scope·보존할 Context | RUN; offending schema/enum/disposition/version fingerprint, `pre_recovery_status`, optional registered target |
| RECHECK 성공 대상 | current contract가 정상화되고 route/target이 closed set에 있으면 validated `pre_recovery_status/registered target` |
| 허용 resolution | `RECHECK`, unrecoverable `FAIL`, cancel intent + external unresolved 0이면 `CANCEL` |
| Reason 미해결 동안 금지 | `ACCEPT_PARTIAL`, `CREATE_CORRECTIVE_PLAN`, unknown value 추측 routing |

Reason/disposition 조합이 위 Reason별 계약에 없으면 `ResolveRecovery`는 `applied=false / RESOLUTION_NOT_ALLOWED`다. UI/Workflow/Test가 별도 reason matrix를 만들 수 없다.

### UNKNOWN_RESULT → Verification entry matrix

`RecoverExistingResult` 또는 `ResolveAsFailed` 후 Run status에 따른 처리도 closed set이다.

| Current Run | Recovered Action result | Required Run handling |
|---|---|---|
| `WAITING_APPROVAL \| CANCEL_REQUESTED` | `RecoverExistingResult → EXECUTED` | `BeginVerification` 후 external reread/`StoreVerification` |
| `VERIFYING` | `RecoverExistingResult → EXECUTED` | **Run lifecycle command 없음**; 이미 VERIFYING이므로 바로 external reread/`StoreVerification` |
| `WAITING_APPROVAL \| VERIFYING` | `ResolveAsFailed → FAILED` | **Run lifecycle command 없음, Verification 없음**; FAILED fact를 보존한다. 독립 approved/executable Action이 남아 있으면 scheduler가 계속 실행하고, 더 이상 실행할 독립 Action이 없을 때만 retry/cancel decision으로 suspend |
| `CANCEL_REQUESTED` | `ResolveAsFailed → FAILED` | **Run lifecycle command 없음, Verification 없음**; FAILED는 cancel-final guard의 closed fact이므로 다른 unresolved effect가 0이면 `FinalizeCancel` 진행 |
| `RECOVERY_REQUIRED` | `RecoverExistingResult → EXECUTED` | `ResolveRecovery(RECHECK)` → VERIFYING, 그 뒤 reread/`StoreVerification` |
| `RECOVERY_REQUIRED` | `ResolveAsFailed → FAILED` | `ResolveRecovery(RECHECK)` → saved `pre_recovery_status`; FAILED fact를 보존하고 독립 approved/executable Action이 있으면 계속 진행한다. 더 이상 실행할 독립 Action이 없을 때 retry/cancel decision으로 suspend. saved status가 `CANCEL_REQUESTED`면 cancel resolution 우선 |

동일 Run이 이미 VERIFYING인데 `BeginVerification`을 반복 호출하지 않는다.

### Startup `SAFE_CHECKPOINT_RESUME` source-state gate

`SAFE_CHECKPOINT_RESUME`는 **Domain lifecycle Command가 아니라 상태를 변경하지 않는 Application startup/resume operation**이다. 따라서 current lifecycle **command-family closed set** 및 `ResolveRecovery` disposition을 펼친 command-row set 어느 쪽에도 추가하지 않는다.

Command coverage는 숫자 상수가 아니라 이 문서의 current Command key set과 downstream mapping의 exact set equality로 검증한다. 다만 어떤 durable Run status에서 generic checkpoint resume가 허용되는지는 이 State Contract가 closed set으로 소유한다.

| Current durable Run status | Startup handling | `SAFE_CHECKPOINT_RESUME` |
|---|---|---|
| `CREATED \| ANALYZING \| RETRIEVING \| PLANNING` | Domain/Checkpoint/registered target/active graph version이 모두 일치하고 `cancel_intent_active=false`, unresolved `EXECUTING \| UNKNOWN_RESULT` Write fact가 없을 때 등록된 같은-run checkpoint에서 계속 | **ALLOWED** |
| `WAITING_CONFIRMATION` | Snapshot/interrupt 복원만 수행하고 사용자 응답을 기다린 뒤 전용 `ResumeConfirmation` | **FORBIDDEN** |
| `WAITING_APPROVAL` | Snapshot/Approval UI 복원만 수행하고 approve/modify/reject/cancel Command를 기다림 | **FORBIDDEN** |
| `EXECUTING` | Legacy READ 또는 in-flight 실행 사실을 Domain에서 먼저 reconcile. 외부 effect를 재실행하는 generic checkpoint resume 금지 | **FORBIDDEN** |
| `VERIFYING` | persisted Action/Attempt/Verification fact를 Application verification coordinator가 reconcile하고 필요한 idempotent reread/명시적 lifecycle Command를 수행 | **FORBIDDEN** |
| `CANCEL_REQUESTED` | durable cancel intent를 복원하고 cancel-resolution coordinator만 계속 | **FORBIDDEN** |
| `REAUTH_REQUIRED` | OAuth 완료 뒤 반드시 `ResumeAfterReauth(applied=true)`; 그 전 LangGraph resume 0 | **FORBIDDEN** |
| `RECOVERY_REQUIRED` | persisted `RecoveryContextV1`에 따라 `ResolveRecovery`/Reauth만 허용 | **FORBIDDEN** |
| `COMPLETED \| BLOCKED \| FAILED \| CANCELLED` | terminal Snapshot 반환만 수행 | **FORBIDDEN** |

`SAFE_CHECKPOINT_RESUME`가 FORBIDDEN인 상태에서 checkpoint가 일치한다는 이유만으로 Supervisor/LangGraph를 직접 resume하면 contract violation이다. Checkpoint/registered target/graph version 불일치 자체는 `RequireRecovery(CHECKPOINT_MISMATCH)`로 fail closed한다.

#### CONSUMED handoff continuation recovery

**CONSUMED handoff continuation recovery는 이 generic SAFE operation과 별개다.**

| 항목 | 규칙 |
| --- | --- |
| Continuation lineage | 이미 external control이 Domain/UoW에서 적용되고 handoff가 `CONSUMED`까지 진행한 경우, initial runnable checkpoint부터 descendant checkpoint까지 checkpointer metadata의 `active_handoff_id + active_handoff_run_sequence`가 동일 continuation lineage를 유지한다. |
| Recovery admission 조건 | Startup/live reconciliation은 latest checkpoint가 그 lineage를 보유하고 current Domain/child execution facts가 그 checkpoint target을 여전히 허용할 때만 `CONSUMED_CONTINUATION_RECOVERY` admission을 claim할 수 있다. |
| RESUME binding·CAS | Recovery admission은 original handoff execution을 재사용하지 않고 latest checkpoint를 `RESUME` effective binding으로 고정하며 current Run authority version을 함께 CAS한다. |
| Checkpoint 근거 | Initial `applied_checkpoint_id/generation` exact match는 첫 entry 직후 crash의 충분한 증거지만, later descendant checkpoint에서는 `active_handoff_id` lineage가 authority다. |

#### Domain progress fence

이 recovery는 새 lifecycle command나 source-state transition이 아니며 generic SAFE 금지를 완화하지 않는다.

| 시점·항목 | 규칙 |
| --- | --- |
| Admission claim 전 | **Admission claim 전에는 Domain progress fence가 checkpoint lineage보다 우선한다.** `REAUTH_REQUIRED`, `RECOVERY_REQUIRED`, terminal, cancel-incompatible `CANCEL_REQUESTED`가 먼저 durable이면 recovery admission을 만들지 않는다. |
| Claim 후·owner settlement 전 | Admission이 먼저 claim된 뒤 상태가 바뀌더라도 owner settlement 전이면 settlement CAS가 admission `expected_run_version`과 current Run.version mismatch를 `AUTHORITY_STALE_RETIRED`로 판정한다. 이 결과는 old semantic owner I/O=0을 보장할 뿐 아니라 persistence layer에서 stale NORMAL admitted handoff를 SUPERSEDED로 retire하거나 recovery admission을 clear하므로 lower-sequence stale head가 current Reauth/Recovery/no-resume/CANCEL_RESOLUTION authority를 막지 않는다. |
| Settlement commit 이후 | Settlement가 먼저 commit된 이후의 later control은 다음 durable guard에서 적용한다. |
| In-flight effect | 이미 발생한 in-flight effect verification/reconciliation은 기존 state-specific 규칙을 유지한다. |
| 그 밖의 상태·Target 검증 | 그 밖의 상태에서도 current Action/ExecutionAttempt/delivery certainty와 latest registered target이 기존 target legality matrix를 통과해야 한다. 단순히 오래된 checkpoint identity가 맞는다는 이유만으로 resume 권한을 부여하지 않는다. |

### Terminal result classification

Durable terminal projection의 vocabulary는 `SUCCESS | PARTIAL | BLOCKED | FAILED | CANCELLED` 하나다. `NONE`은 07 Run Snapshot의 **nonterminal projection sentinel**일 뿐 terminal result가 아니다.

| Terminal command/outcome | `terminal_result_kind` |
|---|---|
| `CompleteAnswerOnlyRun` normal validated answer | `SUCCESS` |
| `CompleteAnswerOnlyRun` bounded insufficiency/invalid-nonpolicy path로 완전 수행이 불가능하다고 명시된 answer | `PARTIAL` |
| `CompleteReadOnlyRun` 모든 READ Action `VERIFIED` | `SUCCESS` |
| `CompleteReadOnlyRun` 하나 이상 READ Action `FAILED` | `PARTIAL` |
| `CompleteWriteRun` 모든 planned effect가 `VERIFIED` | `SUCCESS` |
| `CompleteWriteRun` 하나 이상 planned Action이 `REJECTED \| CANCELLED \| DEPENDENCY_BLOCKED \| BLOCKED`로 의도한 effect를 만들지 못함 | `PARTIAL` |
| `BlockRun` | `BLOCKED` |
| `FinalizeCancel` / `ResolveRecovery(CANCEL)` and no durably observed external mutation | `CANCELLED` |
| `FinalizeCancel` / `ResolveRecovery(CANCEL)` and at least one external mutation is durably observed (`Attempt SUCCEEDED` / Action `EXECUTED \| VERIFIED \| MISMATCH`) | `PARTIAL` |
| `ResolveRecovery(ACCEPT_PARTIAL)` | `PARTIAL` |
| `ResolveRecovery(FAIL)` | `FAILED` |

Terminal handler는 이 table과 child facts로 result kind를 결정하고 같은 UoW의 final Message/durable terminal projection에 사용한다. Sequence/UI가 별도 분류 규칙을 만들 수 없다.

### Release Write Run 불변조건

- Action `EXECUTING`을 이유로 Run을 자동 `EXECUTING`으로 바꾸지 않는다.
- 첫 `EXECUTED` 결과 검증에서만 `BeginVerification`을 적용한다.
- 다중 Action DAG에서 Run이 이미 VERIFYING이면 다음 Action마다 BeginVerification을 반복하지 않는다.
- predecessor가 `VERIFIED`되기 전 dependent Action을 Claim하지 않는다.

- `DEPENDENCY_BLOCKED`의 신규 생성 authority는 `RejectAction`의 coupled mutation이다. predecessor `FAILED`는 retry/cancel decision이 남아 있으므로 dependent를 terminalize하지 않고 Claim만 차단한다. `BlockRun`은 아직 pending인 Action을 `BLOCKED`로 닫으며 새 `DEPENDENCY_BLOCKED`를 만들지 않는다.
- cancel intent가 활성인 경우 `CompleteWriteRun`보다 `FinalizeCancel`/Recovery cancel resolution이 우선한다.

## Action·Approval·Attempt Command

아래 Action/Approval command는 모두 위 **Plan supersession child-authority fence**를 선행 guard로 사용한다. owning Plan이 `SUPERSEDED`이면 historical row를 새 실행권으로 되살리는 mutation은 적용하지 않는다. 특히 `ClaimExecution`은 current published Plan/Run parent authority를 Action/Approval guard와 같은 UoW에서 검증한다.

### 승인·수정·만료

| Command | 허용 전이·조건 |
| --- | --- |
| ApproveAction | Action PROPOSED·MODIFIED → APPROVED + 새 Approval ACTIVE 생성; Plan review gate PASSED, current Action/Source/Policy/Tool Schema snapshot 일치 필요. Approval snapshot/idempotency identity는 같은 UoW에서 고정 |
| ModifyAction | Action PROPOSED·APPROVED·EXPIRED·FAILED·MODIFIED → MODIFIED; 인자 또는 approval-relevant snapshot 변경 시 existing ACTIVE/EXPIRED Approval은 재활성화하지 않고 ACTIVE Approval은 REVOKED + Plan review REQUIRED |
| RejectAction | Action PROPOSED·MODIFIED·APPROVED → REJECTED; ACTIVE Approval → REVOKED; 미실행 dependent Action → DEPENDENCY_BLOCKED. Attempt·Verification 신규 생성 0 |
| CancelPendingAction | Action PROPOSED·MODIFIED·APPROVED·EXPIRED → CANCELLED; ACTIVE Approval → REVOKED; Attempt·Verification 신규 생성 0 |
| ExpireApproval | Action APPROVED → EXPIRED + current Approval ACTIVE → EXPIRED; execution authority 0.<br>Trigger는 Approval TTL 만료 또는 Preflight에서 current Source/Policy/Tool-Schema/approval business snapshot binding이 승인 시점과 달라져 기존 Approval을 안전하게 사용할 수 없는 경우다.<br>current deterministic Policy 자체가 `DENY`면 refresh가 아니라 `BlockRun` 경로를 사용한다 |
| RefreshExpiredAction | Action EXPIRED → MODIFIED; expired Approval은 EXPIRED로 immutable하게 보존하고 current Source/Policy/Schema snapshot을 재계산한다. ACTIVE Approval 0 + Plan review REQUIRED. direct EXPIRED→APPROVED 금지, fresh Review PASS 뒤 새 Approval만 허용 |

### Legacy READ

| Command | 허용 전이·조건 |
| --- | --- |
| ClaimReadAction | READ PROPOSED → EXECUTING; Approval·Attempt 없음 |
| CompleteReadAction | READ EXECUTING → EXECUTED |
| FinalizeReadAction | READ EXECUTED → VERIFIED |
| FailReadAction | READ EXECUTING → FAILED |

### Write 실행권·시작

| Command | 허용 전이·조건 |
| --- | --- |
| ClaimExecution | WRITE Action APPROVED → EXECUTING + current Approval ACTIVE → CONSUMED + 새 ExecutionAttempt CLAIMED. 세 mutation과 Claim Receipt/Audit은 같은 UoW에서 atomic commit |
| BeginExecutionAttempt | current ExecutionAttempt CLAIMED → EXECUTING; committed Claim/Approval snapshot·ClaimContext binding이 current이고 cancel intent가 없어야 한다. 이 Command/Audit commit이 성공한 뒤에만 external Connector Write를 dispatch한다. 외부 호출 자체는 이 Transaction 밖에서 수행 |

#### AbortClaimedExecution

| 항목 | 규칙 |
| --- | --- |
| 적용 범위 | **pre-dispatch only**. |
| 필수 증명 | current Attempt `CLAIMED` + corresponding Action `EXECUTING` + APPLIED `BeginExecutionAttempt` Receipt 없음 + provider Write authority/dispatch 0을 증명해야 한다. |
| Attempt·Action 전이 | Attempt `CLAIMED → FAILED`; cancel intent가 active면 Action `EXECUTING → CANCELLED`, 아니면 Action `EXECUTING → FAILED`. |
| Approval 보존 | Approval `CONSUMED` fact는 되돌리지 않는다. |
| 적용 사유 | cancel/crash/invalid ClaimContext/pre-Begin credential failure를 이 하나의 settlement로 닫는다 |

### 결과·검증·재시도

| Command | 허용 전이·조건 |
| --- | --- |
| StoreSuccess | Action EXECUTING → EXECUTED + current Attempt EXECUTING → SUCCEEDED; provider result identity/delivery evidence를 같은 UoW에 보존 |
| MarkFailed | Action EXECUTING → FAILED + current Attempt EXECUTING → FAILED; `delivery_certainty=NOT_SENT` 필요 |
| MarkUnknownResult | Action EXECUTING → UNKNOWN_RESULT + current Attempt EXECUTING → UNKNOWN_RESULT; 새 Attempt/Approval 생성 금지 |
| RecoverExistingResult | Action UNKNOWN_RESULT → EXECUTED + current Attempt UNKNOWN_RESULT → SUCCEEDED; 기존 외부 mutation이 실제 발생했음을 lookup evidence가 증명해야 하며 새 Write/Attempt 0 |
| ResolveAsFailed | Action UNKNOWN_RESULT → FAILED + current Attempt UNKNOWN_RESULT → FAILED; 외부 mutation 미발생이 결정적으로 확정되어야 하며 새 Write/Attempt 0 |
| StoreVerification | Action EXECUTED → VERIFIED·MISMATCH + immutable Verification append. MISMATCH면 같은 Action/Attempt를 재실행하지 않고 이후 explicit RequireRecovery |
| PrepareWriteRetry | FAILED → MODIFIED; Review → Domain Validation → 새 Approval 필수 |

### Action 결과와 Run 전이의 경계

`MarkUnknownResult` 자체는 Run status를 암묵 변경하지 않는다. Recovery workflow는 새 Write 없이 bounded lookup을 수행할 수 있다.

기존 mutation이 발견되어 `RecoverExistingResult`가 적용된 뒤 Verification에 들어갈 때 Run이 `WAITING_APPROVAL | CANCEL_REQUESTED`이면 `BeginVerification`, 이미 `RECOVERY_REQUIRED`이면 changed external-state fingerprint를 근거로 `ResolveRecovery(RECHECK)`를 먼저 적용한다. lookup이 끝내 불명확할 때만 `RequireRecovery(UNKNOWN_RESULT)`로 suspend한다.

`StoreVerification(...→MISMATCH)`는 Action/Verification 사실만 commit한다. Run을 `RECOVERY_REQUIRED`로 바꾸는 유일한 다음 lifecycle command는 `RequireRecovery(VERIFICATION_MISMATCH)`이며 같은 transaction에 숨겨서 합치지 않는다. 따라서 Verification persistence와 Recovery entry 책임은 서로 다른 Application operation/file이다.

### ClaimContextV2 실행권 검증 경계

`ClaimExecution`의 Domain 상태 전이 의미와 공통 Command Result는 유지한다.

| 항목 | 규칙 |
| --- | --- |
| Context 역할 | `ClaimContextV2`는 Claim Commit 이후 구성되는 실행권 전달·인자 무결성 계약이며, **`BeginExecutionAttempt`의 current Claim/Approval/Attempt binding guard 입력**이다. |
| Dispatch authority | `ClaimContextV2` 자체나 Claim Commit은 외부 dispatch authority가 아니다. |
| MCP 전달 시점 | `BeginExecutionAttempt` Command/Audit가 `applied=true`로 Commit되어 Attempt가 `EXECUTING`이 된 뒤에만 이 Context를 MCP Write에 전달한다. |
| 상세 계약 | 상세 필드와 서명 규칙은 `07 Interface` current contract, 보안 규칙은 `09 Security` current contract가 소유한다. |

### Post-Claim / pre-Begin settlement

| 항목 | 규칙 |
| --- | --- |
| CLAIMED 상태 | `ClaimExecution`과 `BeginExecutionAttempt` 사이의 durable `Attempt=CLAIMED`는 **provider dispatch가 아직 0인 pre-dispatch state**다. |
| Begin 불가 시 처리 | `RequestCancel`, process restart reconciliation, ClaimContext invalidation, pre-Begin credential/security failure로 Begin guard를 통과할 수 없으면 `AbortClaimedExecution`만 사용한다. |
| Begin·Abort 경합 | `BeginExecutionAttempt`와 `AbortClaimedExecution`은 같은 Attempt expected-version/status CAS를 사용하므로 둘 중 하나만 APPLIED 가능하다. |
| Abort 적용 후 | Abort가 APPLIED된 뒤 새 Write는 0이다. |
| 후속 처리 | cancel outcome이면 unresolved child가 0일 때 `FinalizeCancel`; non-cancel FAILED outcome이면 existing retry/cancel decision path를 사용한다. |

## Verification MISMATCH Recovery

- Action `MISMATCH`와 기존 Verification은 terminal·immutable이다.
- `ACCEPT_PARTIAL`: cancel intent가 없을 때만 기존 실제 외부 상태를 수용하고 새 Write 0, Run `COMPLETED + PARTIAL`.
- `CREATE_CORRECTIVE_PLAN`: cancel intent가 없을 때만 실제 외부 상태를 새 Source Snapshot으로 사용해 새 Plan Revision 생성.
- Corrective Write는 새 Approval → `ClaimExecution` → ClaimContext → `BeginExecutionAttempt(applied=true)` → external Write → Verification 전체 경계를 요구한다.
- cancel intent가 활성인 Recovery는 `ResolveRecovery(CANCEL)` 또는 recheck→VERIFYING→`FinalizeCancel`로 닫는다.
- 기존 MISMATCH Action을 재실행·자동 수정·자동 Rollback하지 않는다.

## Recovery RECHECK progress invariant

| 항목 | 규칙 |
| --- | --- |
| Recovery 진입 시 보존 | Application은 Recovery 진입 시 bounded `recovery_fingerprint`와 마지막 external-state/verification input fingerprint를 보존한다. |
| 새 Round 조건 | `ResolveRecovery(RECHECK)`는 사용자 클릭 횟수를 budget으로 보지 않으며 **새 정보가 있는 경우에만** 한 round를 만든다. |
| NO_PROGRESS | `NO_PROGRESS`는 새 Connector read/Verification row/Run version mutation을 만들지 않고 Recovery 선택 상태를 유지한다. |
| RECHECK 재개 | changed external state 또는 changed recovery reason/input이 확인되면 새 RECHECK가 가능하다. |
| 자동 반복 금지 | 이 규칙은 automatic Recovery↔Verification loop를 금지한다. |

## Write Delivery Classification

`NOT_SENT | MAY_HAVE_BEEN_SENT | SENT_RESPONSE_LOST`

- `NOT_SENT`만 외부 미변경이 확정된 실패로 `FAILED` 처리할 수 있다.
- dispatch 이후 Timeout·5xx·response loss·process exit에서 미전달 보장이 없으면 `UNKNOWN_RESULT`다.
- `UNKNOWN_RESULT`에서 새 Attempt·blind resend를 금지한다.
- `FAILED + NOT_SENT`는 사용자의 명시적 `prepare-retry` 또는 cancel 결정을 기다린다.

### Process restart reconciliation

| 항목 | 규칙 |
| --- | --- |
| Orphan Attempt 분류 | `BeginExecutionAttempt(applied=true)` 뒤 terminal dispatch result persistence 전 **process restart로 orphan `Attempt=EXECUTING`이 발견되면 actual provider call 진입 여부를 추측하지 않고 `delivery_certainty=MAY_HAVE_BEEN_SENT`로 `MarkUnknownResult`를 apply/replay**한다. |
| 호출 범위·Owner | 이 operation은 startup-only batch Command `execution_attempt.reconcile_inflight_executions`이 소유하며 live service pass에서는 호출하지 않는다. |
| Command identity·재전송 금지 | base deterministic command id는 `system:execution-attempt-reconcile:<execution_attempt_id>`이고 original Connector Write 재호출은 0이다. |

Reconciliation obligation은 call stack이 아니라 durable state로 이어진다.

| Durable state | 다음 처리 |
| --- | --- |
| UNKNOWN_RESULT · matching RecoveryContext 없음 | `UNKNOWN_RESULT` + matching RecoveryContext 없음은 다음 startup에서 existing-result lookup candidate이며 mutation을 찾으면 deterministic `RecoverExistingResult`, 결정적 미발견이면 `ResolveAsFailed`, 불명확하면 `RequireRecovery(UNKNOWN_RESULT)`를 apply/replay한다. |
| EXECUTED_AWAITING_VERIFICATION | `RecoverExistingResult → EXECUTED` 뒤 Verification이 없으면 `EXECUTED_AWAITING_VERIFICATION` candidate가 `BeginVerification` 또는 `ResolveRecovery(RECHECK)`를 current Run status에 맞게 apply/replay하고 durable `MAIN_CONTROL:VERIFICATION` handoff를 stage/reuse한다. |
| FAILED_AWAITING_CONTINUATION | deterministic `ResolveAsFailed` 뒤 cancel resolution 또는 다른 approved/executable Action의 자동 진행이 필요하면 `FAILED_AWAITING_CONTINUATION` candidate가 `CANCEL_RESOLUTION \| PREFLIGHT` handoff를 stage/reuse하며, stable retry/user-decision wait는 완료 상태다. |
| Matching RECOVERY_REQUIRED 있음 | matching `RECOVERY_REQUIRED`가 durable해진 UNKNOWN_RESULT는 state-specific Recovery owner가 이기므로 startup batch가 다시 lookup을 소유하지 않는다. |

## 취소 불변조건

| 시점·항목 | 규칙 |
| --- | --- |
| Receipt·Version 판정 전 | RequestCancel의 Receipt/Version 판정 전 Approval revoke·Plan cancel·Action mutation 0. |
| 취소 확정 | APPLIED RequestCancel Receipt가 `cancel_intent_active=true`의 영속 기준이다. APPLIED `RequestCancel`은 current Run status를 `CANCEL_REQUESTED`로 기록한다. |
| 결과 확정을 위한 상태 이동 | 이후 result resolution을 위해 `VERIFYING \| REAUTH_REQUIRED \| RECOVERY_REQUIRED`로 이동할 수 있으나 durable cancel intent는 Receipt에서 복원되며 신규 Claim·Write 0을 유지한다. |
| In-flight Action | in-flight Action은 먼저 `EXECUTED \| UNKNOWN_RESULT \| FAILED`로 확정한다. |
| 결과별 처리 | EXECUTED는 Verification, UNKNOWN_RESULT는 Recovery, Credential 문제는 Reauth를 완료한다. |
| 성공한 외부 Write | 성공한 외부 Write는 rollback하지 않는다. |

## Confirmation 불변조건

| 시점 | 규칙 |
| --- | --- |
| Interrupt 생성 전 | 공식 `NEEDS_CONFIRMATION` 이후 Domain `RequestConfirmation`이 적용되기 전 interrupt를 만들지 않는다. |
| Checkpoint 저장 | checkpoint에는 `semantic_owner_id + AgentNodeResumeTargetV2 + interrupt_id`를 저장한다. |
| 사용자 응답 후 | 응답 검증 후 `ResumeConfirmation`으로 발생 전 안전 Domain 상태를 복원하고 같은 owner checkpoint에서 재개한다. |
| Upstream 의미 변경 | 사용자 응답이 upstream 의미를 바꾸는 경우에만 해당 State Owner로 Back-edge한다. |

## 정보 부족 Supervisor Guard

| 우선순위 | 조건 | 처리 |
| --- | --- | --- |
| 1 | required safety/POLICY issue | BLOCKED |
| 2 | required USER issue | NEEDS_CONFIRMATION |
| 3 | required external-source issue + budget | RETRIEVE_MORE |
| 4 | budget exhausted + usable Evidence | PARTIAL |
| 5 | budget exhausted + usable Evidence 없음 | CompleteAnswerOnlyRun 후 종료 |
| 6 | Write 필수 정보 부족 | USER가 해결 가능하면 NEEDS_CONFIRMATION, 아니면 BLOCKED |

모든 Graph Profile이 동일 Guard를 사용한다.

## Unknown Contract Fail-Closed

알 수 없는 Enum·Schema Version·Disposition은 bounded repair 뒤 추측 Edge로 보내지 않는다. `RequireRecovery(CONTRACT_VIOLATION) → RECOVERY_REQUIRED`로 suspend하고, 복구 불가가 확정된 경우에만 `ResolveRecovery(FAIL) → FAILED`로 닫는다.

`WorkflowOutcome.FAILED`를 일괄적으로 `CONTRACT_VIOLATION` 의미로 해석하지 않는다. 현재 producer는 실제 schema·enum·disposition·version 또는 impossible typed-return 위반을 명시적인 `CONTRACT_VIOLATION`으로 반환해야 한다. legacy `FAILED`처럼 typed failure classification 자체가 없으면 그 분류 누락이 contract defect이며, underlying 업무 실패를 contract failure로 추정하는 근거는 아니다.

## 금지

- `EXPIRED → APPROVED` 직접 전이
- `FAILED → EXECUTING` 직접 전이
- `UNKNOWN_RESULT → EXECUTING`과 새 Attempt
- MISMATCH Action 재실행·자동 수정·자동 Rollback
- 승인형 Write Action 실행 중 Run을 자동 EXECUTING으로 덮어쓰기
- cancel intent 활성 상태에서 새 Claim/Write·CompleteWriteRun
- 비Terminal Run의 Domain Command 없는 FINALIZE
- READ Approval·ExecutionAttempt·Verification Row
- Version 없는 Mutable UPDATE
- Browser 제공 authority metadata 신뢰
- 외부 호출 중 SQLite Transaction
- LangGraph Node·FastAPI Route의 SQL 직접 실행
- `ClaimExecution` Commit만으로 MCP Write
- `BeginExecutionAttempt` Commit(applied=true) 전 Connector Write
- Claim Token 재사용
