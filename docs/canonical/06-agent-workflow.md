# 06. Agent · Workflow 설계서

> **목적:** 요청 처리의 책임, 상태 전달, 분기와 안전한 중단·재개를 정의한다.  
> **Authority:** Agent·Workflow orchestration, State projection, Node/Edge/Interrupt와 registered continuation semantics.  
> **상태:** Draft v7.31 · **기준일:** 2026-09-07 · **대상:** P0 MVP

## 0. 먼저 이해할 것

이 문서는 Workflow가 어떤 결과를 받아 어디로 진행하고, 언제 멈추거나 재개하는지 설명한다. Domain lifecycle은 State Contract, Retrieval 의미는 `05`, typed interface는 `07`, Prompt·Failure는 `15`, 네이밍·배치·의존성 규칙은 `16`을 따른다.

세부 Graph 구성과 실험 후보는 확정 제품 요구와 구분한다. 아래의 현재 Profile·Node·Schema 식별자는 기존 binding을 이해하기 위한 참조로 보존하되, 미래의 Agent 수·Node 수·실험 구성을 고정하는 근거로 사용하지 않는다. 이미 시작한 Run의 binding과 안전 조건은 실험을 이유로 임의 변경하지 않는다.

| 개념 | 역할 |
| --- | --- |
| Main Graph / Supervisor | 검증된 상태·결과로 Run의 분기·Interrupt·Back-edge를 결정한다. 업무 내용은 생성하지 않는다. |
| Main State | 다음 책임이 재사용할 Run 입력과 확정된 Versioned Typed Result를 보존한다. |
| Agent Subgraph | 전문 책임을 수행한다. 내부에 여러 LLM·Deterministic Node와 Local State를 둘 수 있다. |
| Subgraph Local State | 해당 invocation의 작업 메모리다. Parent에 자동 승계하지 않는다. |
| Node Input Projection | 현재 Node에 필요한 Typed 필드만 전달한다. |
| Schema / Prompt | Schema는 출력 구조·허용값을, Prompt는 해당 호출의 판단·작성 책임을 제한한다. |
| Edge | Node Result와 공식 State를 코드가 연결한다. LLM 자유 텍스트가 직접 선택하지 않는다. |
| Tool Route | IN의 Connector·Resource·Read Tool과 OUT의 Resource·Effect·Tool을 확정한다. Google Workspace와 GitHub는 같은 connector-neutral 경계를 사용한다. |
| Write | Agent Subgraph가 직접 실행하지 않는다. 승인·실행·검증은 결정적 Application·Domain 경계가 담당한다. |

## 1. Main LangGraph

### 1.1 요청 처리 흐름

다음은 책임 흐름이다. 모든 요청이 모든 Subgraph를 순서대로 실행한다는 뜻은 아니다.

```text
요청 의미·범위 확인
→ 필요한 Tool Route 확정
→ 필요한 자료 수집·업무 분석
→ 답변 또는 실행안 준비
→ 답변 종료 / 실행안 검토·승인·실행·검증
```

| 판단 지점 | 진행 기준 |
| --- | --- |
| 자료 수집 | IN Route가 있으면 Retrieval로 진행한다. 자료가 필요하지 않은 요청은 생략할 수 있다. |
| 업무 분석 | 요청 의미와 결정적 Policy Precondition으로 `effective_analysis_required`를 계산한다. 상세는 §18을 따른다. |
| 추가 정보 | 같은 Route의 추가 검색, Route 재검토, 사용자 확인을 구분한다. |
| 답변 | 근거와 결과 범위를 보존해 종료한다. PARTIAL을 답변이 있다는 이유로 SUCCESS로 바꾸지 않는다. |
| 외부 변경 | Review와 Domain Validation 이후 사용자 승인·Claim·실행·검증을 거친다. |
| 실패·중단 | 현재 Domain 상태와 외부 전달 사실을 먼저 확인한다. 다음 단계로 자동 진행하지 않는다. |

결과별 분기는 §1.3, 실행·검증 경계는 §12에 둔다. 세부 Node 배치와 반복 전략은 이 흐름에서 고정하지 않는다.

### 1.1-A 전역 Domain 상태와 재개

재인증·취소·복구는 업무 흐름과 별도로 현재 안전 checkpoint에 적용한다. `workflow_phase`가 Domain `Run.status`를 대신하지 않는다.

| 상황 | Workflow 처리 |
| --- | --- |
| `REAUTH_REQUIRED` | 현재 checkpoint와 in-flight 사실을 보존하고 suspend한다. 같은 Run의 `RegisteredResumeTargetRefV2 + langgraph_thread_id + checkpoint identity`를 저장한다. |
| 재인증 후 재개 | `ResumeAfterReauth`가 active Registry의 `graph_version`·owner·target을 검증한 뒤 등록된 같은 안전 target으로만 복귀한다. stale/unknown target은 추측 resume하지 않고 Recovery로 보낸다. |
| `CANCEL_REQUESTED` · Claim 전 | 미실행 Action·Approval을 정리하고 `FinalizeCancel`로 닫는다. |
| 취소 · in-flight 존재 | 신규 Claim·Write를 막고 `EXECUTED \| UNKNOWN_RESULT \| FAILED`를 먼저 확정한다. EXECUTED는 Verification, UNKNOWN_RESULT는 Recovery로 보낸다. |
| 취소 중 Recovery | `CREATE_CORRECTIVE_PLAN`과 일반 `ACCEPT_PARTIAL → COMPLETED`는 금지한다. 결과가 확정되면 `ResolveRecovery(CANCEL)` 또는 Verification 후 `FinalizeCancel`로 닫는다. |
| `UNKNOWN_RESULT` lookup | Run이 `WAITING_APPROVAL \| CANCEL_REQUESTED`인 동안에도 새 Write 없이 bounded existing-result lookup을 할 수 있다. 끝내 불명확하거나 명시적 recovery reason이 생길 때 `RequireRecovery`를 적용한다. |
| 이미 `RECOVERY_REQUIRED` | Recovery Node는 등록된 `ResolveRecovery` 결과를 소비해 routing·suspend/resume만 조정한다. |
| `BLOCKED` | Claim 전 `BlockRun`이 적용된 경우에만 Terminal로 취급한다. in-flight Write를 정책 차단으로 덮어쓰지 않는다. |

#### 재인증 시 target 선택

Run 상태만이 아니라 current Action·Attempt·delivery fact를 함께 사용한다. 이미 dispatch된 Write를 재전송하지 않는다.

| 중단 지점·현재 사실 | 등록 target / 처리 |
| --- | --- |
| Retrieval 또는 Agent semantic node의 credential failure | 같은 semantic owner·profile-resolved compiled subgraph·node의 `AGENT_NODE` |
| `WAITING_APPROVAL` + current Write가 EXECUTING/UNKNOWN_RESULT/EXECUTED-awaiting-verification이 아님 + Begin 전 PREFLIGHT credential failure | `MAIN_CONTROL:PREFLIGHT` |
| `WAITING_APPROVAL` + current Write Attempt EXECUTING 또는 전달 여부 불명 | PREFLIGHT 금지. 기존 결과 확인 후 durable EXECUTED이면 `MAIN_CONTROL:VERIFICATION`, 불명확하면 `MAIN_CONTROL:RECOVERY` |
| `EXECUTING` + Legacy READ Action EXECUTING + ExecutionAttempt row 없음 + AUTH_EXPIRED | `MAIN_CONTROL:READ_EXECUTION`; 같은 non-mutating READ의 재개 |
| `VERIFYING` + verification read credential failure | `MAIN_CONTROL:VERIFICATION` |
| `RECOVERY_REQUIRED` + recovery lookup credential failure | `MAIN_CONTROL:RECOVERY` |
| `CANCEL_REQUESTED` | 현재 in-flight 사실을 정리하는 VERIFICATION 또는 RECOVERY. 일반 execution replay 금지 |

`MainResumeStageIdV1`의 closed set은 §2.1의 선언을 사용한다.

| 구분 | 의미 |
| --- | --- |
| `RETRIEVAL_ENTRY / PLANNING_ENTRY / REVIEW_ENTRY / CANCEL_RESOLUTION` | 결정적 external-control 재진입 지점이며 새 Agent가 아니다. |
| `PREFLIGHT` | 승인된 Action의 실행 진입점이다. child-fact Guard를 만족하면 재인증 복귀에도 사용할 수 있다. |
| `READ_EXECUTION` | Legacy/compatibility READ-only 제어 경계다. |
| `INITIALIZE / DOMAIN_VALIDATION / ACTION_EXECUTION / RESPONSE_SYNTHESIS / TERMINAL_COMMIT / FINALIZE` | resume target이 아니다. |

### 1.1-B 응답 준비·종료 Commit·FINALIZE

```text
RESPONSE_SYNTHESIS
→ TERMINAL_COMMIT
→ FINALIZE
```

| 단계 | 책임 | 하지 않는 일 |
| --- | --- | --- |
| `RESPONSE_SYNTHESIS` | terminal command 전에 `TerminalAssistantMessageInputV1`을 작성한다. 종료 가능한 `COMPLETE_WRITE`의 `SUCCESS | PARTIAL`만 검증된 최소 실행 결과를 `run.compose_terminal_response`에 전달해 설명 문장을 만들고, 나머지 종료 종류와 응답 실패는 기존 결정적 formatter를 사용한다. | 상태·정책·승인·실행·검증 결과 변경, Connector/Tool 호출, Planning ANSWER 재작성 |
| `TERMINAL_COMMIT` | `TerminalCommitIntentV1.kind`에 맞는 기존 lifecycle handler를 호출한다. Receipt·Run terminal mutation·final ASSISTANT Message·required Audit는 같은 UoW에 Commit한다. `applied=false`이면 최신 terminal/cancel/recovery 사실을 우선하고, 여전히 종료 가능한 stale snapshot만 최신 사실의 결정적 문장으로 한 번 재조정한다. | 새 Domain 전이 발명, unknown kind/status/version 추측, stale LLM 문장 version만 갱신해 재사용 |
| `FINALIZE` | terminal snapshot 확인 후 `trace_event.emit_trace_event`와 `sse_event.project_run_event`를 호출하고 END로 간다. | Message 재삽입, Domain status 변경, 관측 실패에 따른 rollback·Connector 재실행 |

#### 응답 입력

| 결과 | 사용 입력 |
| --- | --- |
| Answer-only | Planning이 검증한 `AnswerDraftV2` |
| Write | persisted Plan·Action·Attempt·Verification Result의 display-safe 최소 projection. LLM은 `answer`만 작성하며 result kind와 terminal kind는 기존 코드가 고정한다. |
| Recovery / Cancel / Block | typed reason/result |

`BLOCKED | CANCELLED | FAILED`의 result kind와 reason code는 결정적 입력에서 고정한다. 최종 `content`는 현재 Run의 요청 언어와 durable outcome을 반영하며, generic 완료 문장·raw state·reason code만으로 답변을 대신하지 않는다.

결과 설명 LLM은 UoW 밖에서 호출한다. `UNKNOWN_RESULT`, 미검증 `EXECUTED`, 미해결 `MISMATCH`, 실패 결정 대기 상태는 이 경로로 종료하지 않는다. Local 응답 호출은 기존 schema repair 1회까지만 허용하며 이 슬롯에서 Local→API 자동 fallback은 하지 않는다.

#### 종료 종류별 handler

| 종료 종류 | 기존 handler | Run 결과 |
| --- | --- | --- |
| Answer-only·비정책 처리불가 안내 | `CompleteAnswerOnlyRun` | COMPLETED |
| 정책 차단 | `BlockRun` | BLOCKED |
| Write 정상 완료 | `CompleteWriteRun` | COMPLETED |
| Legacy READ 정상·부분 완료 | `CompleteReadOnlyRun` | COMPLETED |
| 취소 완료 | `FinalizeCancel` | CANCELLED |
| Recovery 실패 | `ResolveRecovery(FAIL)` | FAILED |
| Recovery 부분 수용 | `ResolveRecovery(ACCEPT_PARTIAL)` | COMPLETED |
| Recovery 취소 | `ResolveRecovery(CANCEL)` | CANCELLED |

API에서 terminal `ResolveRecovery`가 이미 Commit됐다면, 재개 시 terminal snapshot과 final Message를 확인하고 command를 다시 호출하지 않는다. Legacy READ action의 finalize/fail handler는 Action·Evidence만 확정하고 parent Run은 `CompleteReadOnlyRun`으로 닫는다.

`WAITING_APPROVAL | VERIFYING | REAUTH_REQUIRED | RECOVERY_REQUIRED | CANCEL_REQUESTED` 등 비Terminal 상태에서 대응 Domain Command가 적용되지 않았다면 `FINALIZE → END`로 진행하지 않고 suspend한다.

### 1.1-C External-control handoff target matrix

External HTTP control과 deterministic stale-preflight refresh처럼 background continuation이 필요한 Application lifecycle path는 Domain commit 뒤 LangGraph를 직접 호출하지 않는다. 07의 durable `WorkflowHandoffV1`을 통해 아래 **closed target matrix**를 사용한다.

| Applied control | Continuation classification | Exact registered target / behavior | Typed control |
| --- | --- | --- | --- |
| Confirmation | RESUME_BACKGROUND | saved originating `AGENT_NODE` target | `ConfirmationResumeControlV1` |
| Context Adjustment `EXCLUDE_EVIDENCE` | RESUME_BACKGROUND | `MAIN_CONTROL:RETRIEVAL_ENTRY` → fresh/frozen-route Retrieval → exclusion applied at `retrieval.select_evidence` | `ContextAdjustmentControlV1` |
| Context Adjustment `RETRIEVE_MORE` | RESUME_BACKGROUND | `MAIN_CONTROL:RETRIEVAL_ENTRY` → `retrieval.plan_query` with bounded user need | `ContextAdjustmentControlV1` |
| ApproveAction | RESUME_BACKGROUND | `MAIN_CONTROL:PREFLIGHT` | none |
| ModifyAction | RESUME_BACKGROUND | `MAIN_CONTROL:REVIEW_ENTRY` → Review begins at `review.inspect_goal_and_evidence` over current persisted Plan/Action | none |
| PrepareWriteRetry | RESUME_BACKGROUND | `MAIN_CONTROL:REVIEW_ENTRY` → full current-plan Review before new approval | none |
| RefreshExpiredAction | RESUME_BACKGROUND | `MAIN_CONTROL:REVIEW_ENTRY` → stale approval refresh commit 뒤 current persisted Plan/Action의 fresh Review; new Approval 전 PASS 필요 | none |
| RejectAction | RESUME_BACKGROUND | `MAIN_CONTROL:PREFLIGHT`; stage deterministically chooses next independent executable Action or all-final terminal synthesis/commit | none |
| Reauth completed | RESUME_BACKGROUND | exact target stored by `RequireReauth`, after `ResumeAfterReauth(applied=true)` | none |
| Recovery `RECHECK` | conditional | reason-specific matrix below; `NO_PROGRESS` = STAY_SUSPENDED | none |
| Recovery `CREATE_CORRECTIVE_PLAN` | RESUME_BACKGROUND | `MAIN_CONTROL:PLANNING_ENTRY` | none |
| Recovery `ACCEPT_PARTIAL \| CANCEL \| FAIL` | TERMINAL_NO_RESUME | Domain terminal commit result is projected; no background business continuation | none |
| `SAFE_CHECKPOINT_RESUME` | RESUME_BACKGROUND | exact validated target from current checkpoint/binding; matrix-forbidden state rejects with invocation 0 | none |
| RequestCancel | RESUME_BACKGROUND or Application bootstrap settlement | checkpoint가 있으면 `MAIN_CONTROL:CANCEL_RESOLUTION`; `CREATED + first checkpoint 없음`이면 새 RESUME row 0; START admission 전(PENDING / BLOCKED_BINDING)은 Graphless SUPERSEDED settlement, admission 후(DISPATCHED+admission)는 admission checkpoint 뒤 cancel-intent gate가 CANCEL_RESOLUTION로 전환 | none |

#### 재진입 단계의 책임

| 단계 | 처리 |
| --- | --- |
| `RETRIEVAL_ENTRY` | 현재 Run의 Retrieval 진입 가능성을 검사하고 필요한 경우 기존 `BeginRetrieval`을 적용한다. frozen current input routes에서 시작하며, 사용자 조정은 exclusion 또는 bounded need로 전달한다. 새 Route를 만들지 않는다. |
| `PLANNING_ENTRY` | 기존 결정적 `planning.choose_answer_or_action_from_route`를 통해 Planning에 진입한다. synthetic resume node를 만들지 않는다. |
| `REVIEW_ENTRY` | Modify·PrepareRetry·Refresh 이후 current persisted Plan/Action으로 `review.inspect_goal_and_evidence`에 진입해 registered chain의 aggregate/validate를 수행한다. stale preflight의 Refresh도 direct call이 아니라 같은 handoff를 사용한다. |
| `CANCEL_RESOLUTION` | `run.continue_cancel_resolution`을 호출한다. 기존 `CancelPendingAction / FailReadAction / CompleteReadAction / FinalizeReadAction / BeginVerification / Recovery / FinalizeCancel`만 조정하며 새 lifecycle 전이를 만들지 않는다. |

#### Recovery RECHECK continuation

| 사유·결과 | target / 처리 |
| --- | --- |
| `UNKNOWN_RESULT` | `MAIN_CONTROL:RECOVERY`; recovered EXECUTED는 VERIFICATION, resolved FAILED는 PREFLIGHT 또는 decision suspend |
| `VERIFICATION_MISMATCH` | `MAIN_CONTROL:VERIFICATION` |
| `CHECKPOINT_MISMATCH` | 검증된 `RecoveryContext.registered_resume_target`; invalid이면 RECOVERY_REQUIRED 유지 |
| `CONTRACT_VIOLATION` | 검증된 `RecoveryContext.registered_resume_target/pre_recovery target`; invalid이면 RECOVERY_REQUIRED 유지 |
| `NO_PROGRESS` | handoff 없이 suspend 유지 |
| `CREATE_CORRECTIVE_PLAN` | `MAIN_CONTROL:PLANNING_ENTRY` |

### 1.1-D One-shot control application

`WorkflowControlEnvelopeV1`은 Main State history가 아니라 **한 번 적용되는 external-control input**이다. Workflow가 소유하는 불변조건은 다음이다.

- Background continuation은 durable handoff/admission을 통해서만 시작하고 API/Application이 LangGraph를 직접 invoke하지 않는다. Persistence CAS와 repository method shape는 `04/07`이 소유한다.
- Control patch는 resumed owner I/O보다 먼저 checkpoint에 materialize된다. `EXCLUDE_EVIDENCE`는 `RetrievalState.exclusion_obligation_segment_ids`, `RETRIEVE_MORE`는 `RetrievalState.pending_user_retrieval_need`에 typed fact를 남긴다. Payload가 이후 clear되어도 이 checkpoint fact는 restart-safe하다.
- 동일 handoff가 이미 적용된 checkpoint를 재개할 때 control payload를 다시 주입하지 않는다. Crash 후 owner Node/read/LLM은 idempotent하게 replay될 수 있지만 external control injection과 Write authority는 중복되지 않는다.
- descendant checkpoint는 active handoff lineage를 release boundary까지 이어서 same continuation의 restart 위치를 식별한다. Exact persisted fields와 admission settlement fence는 `04/07`을 따른다.
- raw HTTP request, `interrupt_id`, checkpoint metadata, registered resume-target metadata는 Product Prompt input이 아니다.

Same-Run ordering, admission/release result codes, supersession race, startup/live reconciliation algorithm은 이 절에서 복제하지 않는다. `04`의 durable invariant, `07`의 interface contract, `10`의 process lifecycle을 소비한다.

### 1.2 Main Supervisor 불변조건

#### 결과·책임·freshness

| 항목 | 규칙 |
| --- | --- |
| Controller 책임 | 업무 의미·Tool Arguments·계획 내용을 생성하지 않는다. Agent 간 직접 호출을 연결해 주는 자유형 실행기가 아니다. |
| 결과 분기 | 공식 Result/Disposition은 정확히 하나의 Edge·Interrupt·Terminal 경로로 연결한다. |
| unknown contract | 정의되지 않은 Enum·Version·Disposition은 추측하지 않는다. bounded Schema Repair 후에도 유효하지 않으면 `RequireRecovery(CONTRACT_VIOLATION)`으로 suspend하고, 복구 불가가 확정될 때만 `ResolveRecovery(FAIL)`로 닫는다. |
| 상태 갱신 | Subgraph는 owner field와 허용 signal만 patch merge한다. 누락 필드나 `None`으로 다른 Owner의 State를 지우지 않는다. Owner 표는 §2.3을 따른다. |
| 재판단 | downstream은 upstream Artifact를 read-only로 소비한다. 변경이 필요하면 `*_RECONSIDERATION_REQUIRED`로 해당 Owner에 Back-edge한다. |
| freshness | Artifact 존재 여부만으로 완료를 판단하지 않는다. 현재 active revision과 `meta.based_on`이 맞는 결과만 사용한다. 필요한 downstream 재생성은 §2.4를 따른다. |

#### 진입·실행 분기

| 시점 | 적용 조건과 후속 처리 |
| --- | --- |
| Run 초기화 | `INITIALIZE`가 `StartAnalysis`를 정확히 한 번 적용한 뒤 Request Understanding을 호출한다. `applied=false`이면 Agent 호출 없이 Domain 상태를 재조정한다. |
| 새 Retrieval invocation | Run이 `ANALYZING \| PLANNING`이면 `BeginRetrieval`을 적용한다. 이미 RETRIEVING인 local loop에는 반복 적용하지 않는다. |
| 새 Planning 진입 | Run이 `ANALYZING \| RETRIEVING`이면 `BeginPlanning`을 적용한다. 이미 PLANNING인 bounded revision에는 반복 적용하지 않는다. |
| published Plan 재검토 | durable Review가 `REVISE \| RETRIEVE_MORE \| ROUTE_RECONSIDERATION`이면 State Contract의 Guard와 Plan-supersession fence를 적용한다. 성공·검증된 외부 효과와 immutable final Action fact를 보존하며 unresolved in-flight/UNKNOWN_RESULT/MISMATCH가 있으면 Back-edge하지 않는다. |
| `PREFLIGHT` | Claim/Preflight `applied=true`와 현재 Approval·Policy Confirmation Receipt·Arguments/Execution Hash·State Version을 모두 확인한 경우에만 ACTION_EXECUTION으로 간다. |
| Preflight 실패·경쟁 | 재승인은 WAITING_APPROVAL, 복구는 RECOVERY로 보낸다. 일반 `applied=false` 또는 conflict는 `current_status + next_allowed_commands`를 재조회해 조정한다. 같은 Claim을 무조건 재시도하지 않는다. |
| Policy 차단 | Claim 전 `BlockRun`이 적용돼 실제 BLOCKED가 된 경우에만 종료 처리한다. |
| 실행 결과 | EXECUTED이고 검증 대상이 있을 때만 Verification, UNKNOWN_RESULT이면 Recovery로 간다. FAILED 처리는 아래 기준을 따른다. |
| 첫 Write 검증 | `BeginVerification`을 적용한다. 취소 후 EXECUTED 결과도 `CANCEL_REQUESTED → VERIFYING`으로 검증하되 cancel intent를 유지한다. 이미 VERIFYING인 다중 Action에서는 반복 적용하지 않는다. |
| 완료 판정 | 승인 대상 Action이 모두 final이고 미해결 결과가 없을 때, cancel intent가 없으면 `CompleteWriteRun`, 있으면 취소 종료를 우선한다. |

#### FAILED와 취소

| 상황 | 처리 |
| --- | --- |
| `FAILED + NOT_SENT` + 독립된 approved/executable Action 존재 | 실패 Action의 retry/cancel decision fact를 보존하고 다음 Action의 PREFLIGHT로 진행한다. FAILED predecessor에 의존하는 Action은 Claim하지 않는다. |
| 더 실행할 독립 Action 없음 | `FAILWAIT`에 suspend한다. 다른 Action이 모두 검증됐어도 unresolved FAILED가 남으면 `CompleteWriteRun`하지 않는다. |
| `prepare-retry` 적용 | `FAILED → MODIFIED`와 Plan Review Gate 적용 후 Review부터 재검토한다. PASS·Domain Validation 이후 새 Approval로 진행한다. |
| 실행 중 Cancel | APPLIED RequestCancel Receipt로 신규 Claim·Write를 차단한다. in-flight 결과 확정·Verification/Recovery/필요 Reauth를 거친 뒤 닫는다. |
| 취소 종료 선택 | RECOVERY_REQUIRED이면 `ResolveRecovery(CANCEL)`, 그 외 `VERIFYING \| REAUTH_REQUIRED \| CANCEL_REQUESTED`에서 더 확인할 결과가 없으면 `FinalizeCancel`을 적용한다. 중간 Run 상태가 바뀌어도 Receipt의 cancel intent를 유지한다. |

Recovery는 기존 결과 회수·재검증이 필요할 때만 Verification으로 돌아간다. `CREATE_CORRECTIVE_PLAN`은 기존 Domain 전이에 따라 새 Plan Revision을 준비하고, `ACCEPT_PARTIAL`·실패 확정은 terminal 결과를 준비한다. RECOVERY_REQUIRED에서는 명시적 resolution/재인증을 기다리며 자동 loop하지 않는다.

Confirmation은 §10.2, Tool Route의 필수 READ 보강은 §5.3, Retrieval 내부 반복은 §5.4에 둔다.

### 1.3 Supervisor Disposition → Edge 완전성

아래 표는 현재 Result의 소비 규칙이다. 모든 요청에 고정된 Node 순서를 강제하는 표가 아니다. 분석 필요 여부는 §18의 effective analysis Guard를 적용한다. Terminal 표기는 §1.1-B의 응답·Commit·FINALIZE 절차를 뜻한다.

#### Request Understanding · Tool Route

| 결과·조건 | 다음 책임 / 처리 |
| --- | --- |
| `Request.COMPLETE` | Tool Route |
| `Request.NEEDS_CONFIRMATION` | Request owner에서 interrupt |
| `Request.INVALID` | 비정책 처리불가는 `CompleteAnswerOnlyRun`, 정책 차단은 `BlockRun`을 적용해 종료 |
| `ToolRoute.ROUTE_READY` + IN 있음 | Retrieval. 사용자 의미 Route와 필수 Policy Precondition Route 모두 포함 |
| `ToolRoute.ROUTE_READY` + IN 없음 | effective analysis 필요 여부에 따라 Work Analysis 또는 Planning |
| `ToolRoute.NO_TOOL_NEEDED` | analysis가 필요하면 Work Analysis 후 Planning(Answer), 아니면 Planning(Answer) |
| `ToolRoute.NEEDS_CONFIRMATION` | Tool Route owner에서 interrupt. `SCOPE_EXPANSION_REQUIRED`는 추가 범위·이유를 먼저 확인 |
| `ToolRoute.BLOCKED` | `BlockRun` 적용 후 종료 |

초기 Connector prerequisite 실패는 §5.3의 `PREREQUISITE_UNMET` 종료 경로를 따른다.

#### Retrieval · Work Analysis

| 결과·조건 | 다음 책임 / 처리 |
| --- | --- |
| `Retrieval.SUFFICIENT / NO_FETCH_NEEDED` | Work Analysis 또는 Planning |
| Retrieval 내부 `NEEDS_MORE_DATA` + local budget 있음 | 같은 invocation 안의 bounded local loop |
| Retrieval 내부 `NEEDS_MORE_DATA` + budget 소진 | 결정적 Guard가 `NEEDS_CONFIRMATION \| PARTIAL \| BLOCKED`로 정규화한 뒤 Parent에 반환 |
| `Retrieval.NEEDS_CONFIRMATION` | Retrieval owner에서 interrupt |
| `Retrieval.ROUTE_RECONSIDERATION_REQUIRED` | Tool Route |
| `Retrieval.PARTIAL` + usable Evidence 있음 | coverage=PARTIAL을 유지해 Work Analysis 또는 Planning |
| `Retrieval.PARTIAL` + usable Evidence 없음 | `CompleteAnswerOnlyRun`으로 종료 |
| `Retrieval.BLOCKED` | `BlockRun` 적용 후 종료 |
| `WorkAnalysis.COMPLETE` | Planning |
| `WorkAnalysis.NEEDS_MORE_DATA` + 현재 IN Route로 해결 가능 | `RetrievalRequiredV1`을 전달해 Retrieval 재진입 |
| `WorkAnalysis.REQUEST_RECONSIDERATION_REQUIRED` | 현재 Evidence가 현재 Request Intent를 반증·보완한 경우 기존 Request Understanding owner로 재진입. Intent revision을 만들고 Tool Route 이후 dependent artifact를 fresh하게 다시 생성 |
| Work Analysis의 부족 정보를 현재 Route로 해결 불가 | owner-local finalizer가 `ROUTE_RECONSIDERATION_REQUIRED + RouteReconsiderationRequiredV1`로 정규화해 Tool Route로 전달 |
| `WorkAnalysis.NEEDS_CONFIRMATION` | Work Analysis owner에서 interrupt. 중복·충돌 Override는 각각 `DUPLICATE_OVERRIDE_REQUIRED / CONFLICT_OVERRIDE_REQUIRED`를 사용 |
| `WorkAnalysis.ROUTE_RECONSIDERATION_REQUIRED` | Tool Route |
| `WorkAnalysis.BLOCKED` | `BlockRun` 적용 후 종료 |

no-route 상황을 `NEEDS_MORE_DATA + RetrievalRequiredV1`로 Tool Route에 전달하지 않는다.

#### Planning · Review

| 결과·조건 | 다음 책임 / 처리 |
| --- | --- |
| `Planning.ANSWER_ONLY` | RESPONSE_SYNTHESIS. 최초 terminal projection은 Retrieval의 PARTIAL을 보존하며, 저장된 terminal 결과를 checkpoint coverage로 덮어쓰지 않음 |
| `Planning.PLAN_READY` | Review |
| `Planning.NEEDS_CONFIRMATION` | Planning owner에서 interrupt |
| `Planning.ROUTE_RECONSIDERATION_REQUIRED` | Tool Route |
| `Planning.BLOCKED` | `BlockRun` 적용 후 종료 |
| `Review.PASS` | DOMAIN_VALIDATION |
| `Review.REVISE` | pre-publish는 Planning revision, published Plan은 guarded `BeginPlanning` 후 Planning |
| `Review.RETRIEVE_MORE` + 현재 IN Route로 해결 가능 | pre-publish는 Retrieval, published Plan은 guarded `BeginPlanning`으로 새 Plan revision context를 만든 뒤 Retrieval. `RetrievalRequiredV1` 전달 |
| Review evidence gap을 현재 Route로 해결 불가 | owner-local finalizer가 `ROUTE_RECONSIDERATION + RouteReconsiderationRequiredV1`로 정규화. published Plan은 guarded `BeginPlanning`으로 supersede한 뒤 Tool Route |
| `Review.ROUTE_RECONSIDERATION` | pre-publish는 Tool Route, published Plan은 guarded `BeginPlanning` 후 Tool Route |
| `Review.CONFIRM` | pre-publish 또는 State Contract가 허용한 published `WAITING_APPROVAL \| VERIFYING`에서 `RequestConfirmation` 적용 후 Review owner interrupt |
| `Review.BLOCK` | State Contract의 `BlockRun` Guard를 통과해 적용된 경우만 종료. in-flight/UNKNOWN_RESULT/MISMATCH가 있으면 Recovery·Reauth·Cancel resolution 우선 |

no-route 상황을 `RETRIEVE_MORE + RetrievalRequiredV1`로 Tool Route에 전달하지 않는다. 정의되지 않은 schema version·Enum·disposition은 임의 기본 Edge로 보내지 않는다.

### 1.4 Graph Profile

아래는 현재 문서에 정의된 `GraphProfileIdV1`과 profile binding이다. Interface projection은 `07 WorkflowBindingV1`, repository placement는 `16`을 따른다. 실험의 비교 후보·개수·최종 Graph 구성은 여기서 고정하지 않는다.

```python
GraphProfileIdV1 = Literal["SINGLE_BASELINE", "THREE_STAGE", "SIX_ROLE_BASELINE"]
```

Profile 목록을 모든 후보의 구현·비교 의무로 사용하지 않는다. 선택된 구성의 Service composition은 startup `GraphProfileIdV1`로 compiled graph를 선택하고, StartRun에서 profile과 `graph_version`을 Run binding에 snapshot한다. 동일 Run resume은 저장된 binding과 같은 profile/version만 허용한다.

| Profile | 구조 | 목적 |
| --- | --- | --- |
| `SINGLE_BASELINE` | 통합 Agent Subgraph 1개. 요청 이해·Tool Route·Retrieval·업무 분석·계획·self-review 책임을 한 Subgraph 안에 배치한다. | 단일 Agent Baseline |
| `THREE_STAGE` | Agent Subgraph 3개. ① 요청 이해+Tool Route+Retrieval ② 업무 분석+Planning ③ 독립 Review | 계층형 3-Agent 후보 |
| `SIX_ROLE_BASELINE` | Agent Subgraph 6개. Request Understanding / Tool Route / Retrieval / Work Analysis / Planning / Review | 최대 전문화 Multi-Agent Baseline |

Semantic owner와 physical compiled Subgraph identity는 아래 **exact profile binding**으로만 연결한다.

| semantic owner | SINGLE_BASELINE | THREE_STAGE | SIX_ROLE_BASELINE |
| --- | --- | --- | --- |
| REQUEST_UNDERSTANDING | UNIFIED_AGENT | STAGE_REQUEST_ROUTE_RETRIEVAL | SIX_REQUEST_UNDERSTANDING |
| TOOL_ROUTE | UNIFIED_AGENT | STAGE_REQUEST_ROUTE_RETRIEVAL | SIX_TOOL_ROUTE |
| RETRIEVAL | UNIFIED_AGENT | STAGE_REQUEST_ROUTE_RETRIEVAL | SIX_RETRIEVAL |
| WORK_ANALYSIS | UNIFIED_AGENT | STAGE_ANALYSIS_PLANNING | SIX_WORK_ANALYSIS |
| PLANNING | UNIFIED_AGENT | STAGE_ANALYSIS_PLANNING | SIX_PLANNING |
| REVIEW | UNIFIED_AGENT | STAGE_REVIEW | SIX_REVIEW |

`semantic owner`는 capability/checkpoint ownership 의미이고 `compiled_subgraph_id`는 선택된 Graph Profile의 physical checkpoint namespace다. Profile builder가 이 table을 materialize하며 다른 alias/mapping table을 만들지 않는다.

공통 불변조건:

- Domain과 deterministic Policy·승인·Claim·실행·검증·복구 코드는 모든 Profile에서 동일하다.
- Profile 간 독립변수는 책임의 Subgraph 분해 수준이다. Tool·Policy·Domain 안전 계약은 바꾸지 않는다.
- Profile 품질·비용·지연 비교와 controlled decomposition 평가는 `13 Evaluation`이 소유한다. 06은 평가 Lane/Gold/score를 runtime topology authority로 사용하지 않는다.
- Evaluation-only Oracle/controlled snapshot은 제품 Runtime state나 resume/checkpoint authority가 아니다.

## 2. Main Graph State

### 2.1 Main State 계약

#### Run 입력과 Phase

```python
class RunInputV1:
    entry_mode: Literal["AGENT_SEARCH", "RESOURCE_SELECTED"]
    user_request: str
    selected_resource_refs: list[SelectedResourceRefV1]
    requested_mode: Literal["LOCAL_GPU", "API_LLM"]

WorkflowPhaseV2 = Literal[
    "INITIALIZE", "REQUEST_UNDERSTANDING", "TOOL_ROUTING", "RETRIEVAL",
    "WORK_ANALYSIS", "PLANNING", "REVIEW", "DOMAIN_VALIDATION",
    "WAITING_CONFIRMATION", "WAITING_APPROVAL", "PREFLIGHT", "ACTION_EXECUTION",
    "READ_EXECUTION", "VERIFICATION", "RECOVERY", "RESPONSE_SYNTHESIS", "TERMINAL_COMMIT", "FINALIZE"
]
```

#### 실행·검증 결과

```python
class ExecutionSummaryV1:
    schema_version: Literal[1]
    action_id: str
    execution_attempt_id: str
    routing_outcome: Literal["EXECUTED", "FAILED", "UNKNOWN_RESULT"]
    delivery_certainty: Literal["NOT_SENT", "MAY_HAVE_BEEN_SENT", "SENT_RESPONSE_LOST"] | None
    source_action_version: int

class VerificationSummaryV1:
    schema_version: Literal[1]
    action_id: str
    verification_id: str
    routing_outcome: Literal["VERIFIED", "MISMATCH"]
    source_action_version: int
```

#### 호출 예산

```python
class RunBudgetV2:
    schema_version: Literal[2]
    profile: Literal["NORMAL", "RETRIEVAL_HEAVY", "REVISION_HEAVY"]
    started_at_ms: int
    max_execution_ms: int
    llm_calls_used: int
    llm_call_limit: int
    connector_calls_used: int
    max_connector_calls: int
    source_page_calls_used: int
    max_source_page_calls: int
    detail_fetches_used: int
    max_detail_fetches: int
    context_tokens_used: int
    max_context_tokens: int
    retry_attempts_used: int
    max_retry_attempts: int
    absolute_llm_call_limit: Literal[100]
    schema_repairs_used_by_node: dict[str, int]
    semantic_revisions_used_by_failure: dict[str, int]
    planning_revisions_used: int
    review_rechecks_used: int
    additional_retrieval_rounds_used: int
```

#### Prompt·Trace metadata

```python
class PromptContextV1:
    schema_version: Literal[1]
    run_id: str
    prompt_bundle_version: str
    active_prompt_slot_id: str | None
    active_prompt_content_hash: str | None
    failure_reason_code: str | None

class TraceContextV1:
    schema_version: Literal[1]
    request_id: str
    trace_id: str
    conversation_id: str
    run_id: str
    parent_span_id: str | None
```

#### 종료 제어

```python
TerminalCommitKindV1 = Literal[
    "COMPLETE_ANSWER_ONLY", "COMPLETE_READ_ONLY", "COMPLETE_WRITE", "BLOCK_RUN", "FINALIZE_CANCEL",
    "RECOVERY_ACCEPT_PARTIAL", "RECOVERY_CANCEL", "RECOVERY_FAIL"
]

class TerminalCommitIntentV1:
    schema_version: Literal[1]
    kind: TerminalCommitKindV1
    expected_run_version: int
    terminal_message: TerminalAssistantMessageInputV1
    reason_codes: list[str]
```

#### Main State

```python
class GraphState:
    schema_version: Literal[2]
    run_id: str
    conversation_id: str
    langgraph_thread_id: str
    workflow_phase: WorkflowPhaseV2
    graph_profile: GraphProfileIdV1
    run_input: RunInputV1

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    planning_result: AnswerDraftV2 | ActionPlanDraftV2 | None
    plan_review: PlanReviewResultV2 | None

    approved_plan_id: str | None
    execution_summary: ExecutionSummaryV1 | None
    verification_summary: VerificationSummaryV1 | None
    terminal_commit_intent: TerminalCommitIntentV1 | None

    workflow_signal: WorkflowSignalV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    retry_budget: RunBudgetV2
    prompt_context: PromptContextV1
    trace_context: TraceContextV1
```

#### Control·Projection 사용 조건

| 항목 | 조건 |
| --- | --- |
| `graph_profile` | Run 시작 시 WorkflowBinding에 저장한 값의 projection이다. Run 중 변경하지 않으며 compiled profile/version 불일치는 Recovery로 fail closed한다. |
| `WorkflowPhaseV2` | routing/checkpoint 위치다. 도식의 DOMAIN_RECONCILE·SUSPEND·ORIGINATING SUBGRAPH CHECKPOINT는 별도 Phase 값이 아니다. REAUTH_REQUIRED·CANCEL_REQUESTED·CANCELLED 같은 Domain 상태를 복제하지 않는다. |
| `READ_EXECUTION` | PublishReadOnlyPlan이 만든 Legacy/compatibility READ-only Run의 non-mutating phase이며 새 승인형 Write Agent가 아니다. |
| `TerminalCommitIntentV1` | 결정된 Domain/Recovery outcome에서만 만든다. Product LLM이 kind를 고르지 않는다. 성공 Commit 후 clear하며 `run_id + expected_run_version + kind`의 canonical hash로 command idempotency key를 생성한다. |
| `ExecutionSummaryV1 / VerificationSummaryV1` | Domain/Application이 확정한 사실의 routing projection이다. Domain state·guard를 새로 정의하거나 Action/Attempt/Verification 사실을 덮어쓰지 않는다. |
| `RunBudgetV2` | 결정적 budget controller만 갱신한다. snapshot·counter·차단 규칙은 §11을 따른다. |
| `ComponentCircuitStateV1` | `10`의 process-local operational contract다. Main State에 Circuit truth를 복제하지 않고 outbound Application operation이 조회한다. |
| `PromptContextV1` | Registry 선택·추적 metadata만 담는다. Prompt·raw user_request·Conversation History·previous-run Artifact·Tool 원문을 숨은 입력으로 저장하지 않는다. |
| `TraceContextV1` | correlation propagation 전용이다. trace/request/run ID 변경으로 lifecycle·idempotency 권위를 만들지 않는다. |

#### WorkflowSignalV1

`workflow_signal`은 확정 업무 Artifact가 아니라 현재 interrupt/back-edge 요청 하나를 담는 transient field다. 타입은 다음 discriminated union으로 닫고, producer·consumer·clear 시점은 §3.7에서 정의한다.

```python
SemanticAgentOwnerIdV1 = Literal[
    "REQUEST_UNDERSTANDING", "TOOL_ROUTE", "RETRIEVAL",
    "WORK_ANALYSIS", "PLANNING", "REVIEW"
]

CompiledAgentSubgraphIdV1 = Literal[
    "UNIFIED_AGENT",
    "STAGE_REQUEST_ROUTE_RETRIEVAL", "STAGE_ANALYSIS_PLANNING", "STAGE_REVIEW",
    "SIX_REQUEST_UNDERSTANDING", "SIX_TOOL_ROUTE", "SIX_RETRIEVAL",
    "SIX_WORK_ANALYSIS", "SIX_PLANNING", "SIX_REVIEW"
]

MainResumeStageIdV1 = Literal[
    "RETRIEVAL_ENTRY", "PLANNING_ENTRY", "REVIEW_ENTRY",
    "PREFLIGHT", "READ_EXECUTION", "VERIFICATION", "RECOVERY", "CANCEL_RESOLUTION"
]

class AgentNodeResumeTargetV2:
    kind: Literal["AGENT_NODE"]
    semantic_owner_id: SemanticAgentOwnerIdV1
    compiled_subgraph_id: CompiledAgentSubgraphIdV1
    node_id: str
    graph_profile: GraphProfileIdV1
    graph_version: str

class MainControlResumeTargetV2:
    kind: Literal["MAIN_CONTROL"]
    stage_id: MainResumeStageIdV1
    graph_profile: GraphProfileIdV1
    graph_version: str

RegisteredResumeTargetRefV2 = AgentNodeResumeTargetV2 | MainControlResumeTargetV2

class ConfirmationRequiredV1:
    kind: Literal["CONFIRMATION_REQUIRED"]
    interrupt_id: str
    semantic_owner_id: SemanticAgentOwnerIdV1
    resume_target: AgentNodeResumeTargetV2
    question: str
    options: list[str]

# ConfirmationResponseProjectionV1의 exact closed shape는 07 Interface current contract가 소유한다.
# Workflow는 그 타입을 그대로 import/reference하며 독립 재정의하지 않는다.
# 허용 response_kind = OPTION | FREE_TEXT | DECLINE.

class RouteReconsiderationRequiredV1:
    kind: Literal["ROUTE_RECONSIDERATION_REQUIRED"]
    reason_codes: list[str]

class RequestReconsiderationObservationV1:
    evidence_ref: str
    resource_ref: str
    excerpt: str

class RequestReconsiderationRequiredV1:
    kind: Literal["REQUEST_RECONSIDERATION_REQUIRED"]
    reason_codes: list[str]
    based_on_request_intent: StateArtifactMetaV1
    observations: list[RequestReconsiderationObservationV1]

class RetrievalNeedV1:
    required_information: str
    reason_codes: list[str]  # minItems=1

class RetrievalRequiredV1:
    kind: Literal["RETRIEVAL_REQUIRED"]
    reason_codes: list[str]
    needs: list[RetrievalNeedV1]  # minItems=1

class ContextAdjustmentV1:
    kind: Literal["EXCLUDE_EVIDENCE", "RETRIEVE_MORE"]
    based_on_retrieval_revision: int
    excluded_segment_ids: list[str]  # EXCLUDE_EVIDENCE only, minItems=1
    retrieval_need: RetrievalNeedV1 | None  # RETRIEVE_MORE only

class BlockedSignalV1:
    kind: Literal["BLOCKED"]
    reason_codes: list[str]

WorkflowSignalV1 = ConfirmationRequiredV1 | RouteReconsiderationRequiredV1 | RequestReconsiderationRequiredV1 | RetrievalRequiredV1 | BlockedSignalV1
```

#### 추가 Retrieval과 Context Adjustment

| 입력 | 허용값·처리 |
| --- | --- |
| `RetrievalNeedV1` | 비어 있지 않은 단일 `required_information`과 하나 이상의 `reason_codes`. 동일 Signal 안에서 정규화한 두 값으로 stable dedup한다. |
| Need에 넣지 않는 값 | Connector·Resource 종류·Tool ID·Raw Query·Page Token·MCP Arguments |
| Need 소비 범위 | 현재 active InputRoutePlan 안에서만 소비한다. 해결할 수 없으면 `RouteReconsiderationRequiredV1`을 사용한다. |
| Work Analysis의 Need | `assess_information_gaps`가 현재 IN Route로 해결 가능한 부족 정보만 생성한다. NEEDS_MORE_DATA일 때 `RetrievalRequiredV1`으로 투영한다. |
| Review의 Need | RETRIEVE_MORE의 각 `EvidenceGapV1.required_information` 항목을 Need로 만들고 gap code를 reason_codes에 보존한다. |
| Retrieval 자체 반복 | 같은 invocation의 NEEDS_MORE_DATA에는 `RetrievalRequiredV1`을 만들지 않는다. |
| `ContextAdjustmentV1` | Agent Signal이 아니다. `run.adjust_context`가 검증한 same-Run external control이며 Supervisor는 Retrieval owner에만 전달한다. |
| `EXCLUDE_EVIDENCE` | current Preview membership이 검증된 stable segment ID만 허용하고 `retrieval_need=null`. payload clear 전에 `exclusion_obligation_segment_ids`를 checkpoint에 materialize한다. |
| `RETRIEVE_MORE` | `excluded_segment_ids=[]`, reason_codes에 `USER_CONTEXT_ADJUSTMENT` 포함. `pending_user_retrieval_need`에 checkpoint-commit하고 fresh RetrievalResult revision finalize 시에만 clear한다. |

조정 후 downstream 재실행은 `meta.based_on` freshness로 결정한다. Browser나 Agent가 stale Artifact를 직접 삭제·수정하지 않는다.

#### 등록된 Resume Target과 Confirmation

| 항목 | 규칙 |
| --- | --- |
| Target 발급·검증 | active compiled Main Graph의 `ResumeTargetRegistry`만 수행한다. |
| `AGENT_NODE` | semantic owner + selected profile의 exact compiled-subgraph binding과 NodeRegistry entry를 모두 검사한다. |
| `MAIN_CONTROL` | 선언된 `MainResumeStageIdV1`만 허용한다. |
| target 입력 권위 | LLM 자유 문자열·Agent 제안·사용자 입력이 kind/owner/subgraph/stage/node/graph_version을 확정하지 않는다. |
| `graph_version` | compiled Main Graph의 resume-contract version이다. Prompt·Dataset·DB·Tool Registry version과 독립이다. target 또는 interrupt/resume topology가 바뀌면 증가시키며 mismatch checkpoint는 추측 resume하지 않는다. |
| `question/options` | 검증된 Subgraph 결과에서 올 수 있다. |
| `interrupt_id / semantic_owner_id / resume_target` | 결정적 Workflow/Application이 확정해 같은 RequestConfirmation에 bind한다. `applied=true` 이후에만 checkpoint 저장과 interrupt를 생성한다. |
| `options=[]` | 자유 텍스트 응답 |
| options 하나 이상 | 등록된 값 안의 닫힌 선택 응답. 임의 텍스트를 승인·정책 결정으로 해석하지 않는다. |
| pending interrupt 표시 | `07 PendingInterruptResponseV1`로만 one-way projection한다. 정의되지 않은 legacy DTO alias를 current contract로 사용하지 않는다. |

#### PolicyConfirmationReceiptV1

```python
class PolicyConfirmationReceiptV1:
    schema_version: Literal[1]
    meta: StateArtifactMetaV1
    interrupt_id: str
    confirmation_kind: Literal["SCOPE_EXPANSION", "DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"]
    decision: Literal["APPROVED", "DECLINED"]
    semantic_owner_id: Literal["TOOL_ROUTE", "WORK_ANALYSIS"]
    decision_context_hash: str
    affected_route_ids: list[str]
    affected_resource_refs: list[str]
```

| 항목 | 사용 조건 |
| --- | --- |
| 생성·저장 | 실제 사용자 interrupt 응답을 검증한 Application/Confirmation Controller만 생성해 `policy_confirmation_receipts`에 append한다. Agent/LLM은 생성·수정하지 않는다. |
| 적용 대상 | Scope 확장·중복 Override·충돌 Override. 일반 Clarification은 owner Artifact revision으로 흡수할 수 있으며 별도 Receipt 영속 대상이 아니다. |
| 근거 revision | 질문을 발생시킨 current RequestIntent/InputRoute/OutputRoute/Retrieval 등 공식 revision만 `meta.based_on`에 참조한다. `meta.artifact_id`는 Audit의 confirmation_receipt_id다. |
| 허용 근거 | APPROVED이고 decision_context_hash·based_on이 현재 active revision과 일치하는 Receipt만 사용한다. DECLINED는 Audit·설명용이지 허용 근거가 아니다. |
| 후속 결과 | Scope 확장의 InputRoutePlan과 Override 후 WorkAnalysisResult는 사용한 Receipt revision을 based_on에 포함한다. Context가 달라지면 재사용하지 않는다. |
| Write 계획 | Domain Validation이 유효한 APPROVED Receipt를 확인하고 Approval Snapshot에 Receipt ID·Context Hash를 넣는다. 누락·stale이면 Approval로 진행하지 않는다. |

Confirmation은 같은 `semantic_owner_id + AgentNodeResumeTargetV2 + interrupt_id`로 재개한다. 모든 응답을 Request Understanding으로 되돌리거나 Signal로 upstream Artifact를 직접 수정하지 않는다.

### 2.2 Main State에 저장하는 것

Main State는 이번 Run의 입력과 다음 책임이 재사용할 공식 결과를 담는다. `run_input`을 downstream이 임의 변경하지 않는다.

| 구분 | 보존 범위 |
| --- | --- |
| Run 입력 | 사용자가 이번 Run에 제출한 요청과 명시적으로 선택한 Entry Context |
| 공식 결과 | request_intent, tool_route_plan, retrieval_result, work_analysis_result, planning_result, plan_review |
| 실행 관련 | 승인·실행·검증 reference와 허용된 control projection |
| 대용량 원문·검색 후보 | Run Retrieval Cache Handle로 참조한다. Main State에 원문을 복제하지 않는다. |

#### 새 Run과 same-Run resume

`conversation_id`는 Timeline 상관관계 ID이지 State 상속 Key가 아니다. Terminal Run 뒤 새 요청은 새 `langgraph_thread_id + RunInputV1`로 시작한다. 이전 Run의 Request·Route·Retrieval·Analysis·Planning·Review·Receipt·Signal·PromptContext나 Checkpoint를 복사하지 않는다.

새 Run의 Request Understanding Projection은 현재 `run_input.user_request + run_input.selected_resource_refs`만 소비한다. 과거 Conversation Message를 숨은 Prompt Context로 append하지 않는다.

동일 Run의 Confirmation·재인증·Recovery는 기존 owner/thread/checkpoint를 resume한다. 새 Run 격리의 예외가 아니라 동일 Run 연속성이다.

> **표현 확인 필요:** 원문은 `관련 메일 찾아줘`를 NEEDS_CONFIRMATION으로 처리하면서 조건을 “이전 Run 없이는 대상을 결정할 수 있고”라고 적고 있다. 조건의 의도가 불명확해 문장을 반대로 고치거나 새 해석을 확정하지 않는다.

#### 저장하지 않는 것

| 분류 | 제외 대상 |
| --- | --- |
| 추론 중간물 | LLM raw completion, Prompt 원문, Repair candidate, 임시 validation state |
| 검색 중간물 | Query 후보 전체, Page Token, 전체 Gmail·Calendar·Tasks 원문, RAG 후보·내부 score 전체 |
| 미확정 제어 후보 | confirmation/reconsideration 후보를 업무 Artifact로 저장하지 않는다. 허용된 제어 요청만 workflow_signal로 전달한다. |

#### Retrieval cache와 checkpoint

| 상황 | 처리 |
| --- | --- |
| Retrieval-dependent checkpoint | 필요한 handle dependency만 `GraphCheckpointEnvelopeV1.retrieval_cache_requirements`에 투영한다. raw result/token은 넣지 않는다. |
| handle loss | `RunRetrievalCachePort → InMemoryRunRetrievalCache`를 소비하는 `run.reconcile_retrieval_cache_restart`가 durable restart를 소유한다. Background/LangGraph adapter는 Handler를 호출할 뿐 Repository row를 직접 stage하지 않는다. |
| Plan/Evidence가 durable한 WAITING_APPROVAL / EXECUTING / VERIFYING | 이전 Retrieval 원문 cache 유실로 재검색하거나 승인·검증 continuation을 막지 않는다. persisted Action/Approval/Evidence와 fresh preflight/Verification READ를 사용한다. |
| 수정·재계획으로 PLANNING / RETRIEVING 재진입 | 해당 Retrieval cache prerequisite를 다시 적용한다. |

### 2.2-A Retrieval head projection

| 항목 | 규칙 |
| --- | --- |
| Application이 읽는 current revision | `07/04 RetrievalHeadV1` typed checkpoint metadata |
| checkpoint 저장 | adapter가 `retrieval_result.meta.revision`과 successful Retrieval checkpoint의 동일 revision/head를 함께 Commit |
| Preview·Adjustment 조회 | `run.project_context_preview`와 `run.adjust_context`는 `CheckpointPort.load_retrieval_head(run_id)` 사용 |
| 금지 | opaque Main State/checkpoint blob을 열어 current revision을 읽거나 추측하지 않음 |

### 2.3 State Owner

| Main State | 유일한 Owner | Downstream 사용 규칙 |
| --- | --- | --- |
| `run_input` | Run 생성 경계 | 읽기 전용. 사용자 새 입력/Interrupt Resume에서만 새 값 또는 명시적 continuation을 만든다 |
| `request_intent` | Request Understanding | 읽기만 가능. 변경 필요 시 Request Subgraph 재진입 |
| `tool_route_plan.input_plan` | Tool Route | Retrieval이 소비하는 독립 revision Artifact. 직접 변경 금지 |
| `tool_route_plan.output_plan` | Tool Route | Planning이 소비하는 독립 revision Artifact. 직접 변경 금지 |
| `retrieval_result` | Retrieval | Analysis·Planning·Review가 Evidence Reference로 소비 |
| `work_analysis_result` | Work Analysis | Planning이 업무 사실·관계로 소비 |
| `planning_result` | Planning | Review·Domain Validation이 소비 |
| `plan_review` | Review | Supervisor·Domain Validation이 소비 |

### 2.3-A Agent Artifact가 아닌 Main State control/reference field

`GraphState`의 모든 필드가 Agent-owned business Artifact는 아니다. 다음 필드는 Agent가 임의 작성하는 의미 권위가 아니라 결정적 Runtime/Application의 control 또는 Domain 사실에 대한 reference/projection이다.

| Main State field | Graph writer / 갱신 경계 | 권위 규칙 |
| --- | --- | --- |
| `approved_plan_id` | Domain Validation/Approval 결과를 반영하는 결정적 Application·Supervisor 경계 | 승인 사실 자체의 권위는 Domain Store. Graph 값만으로 Approval을 성립시키지 않는다. |
| `execution_summary` | Action Execution 결과를 반영하는 결정적 Application·Supervisor 경계 | ExecutionAttempt·Action 상태의 권위는 Domain Store. Summary는 routing용 projection/reference다. |
| `verification_summary` | Verification 결과를 반영하는 결정적 Application·Supervisor 경계 | Verification 사실의 권위는 Domain Store. Summary는 routing/response용 projection/reference다. |
| `workflow_signal` | 현재 Subgraph Return → Supervisor | 일시적 control signal. 해당 Back-edge/Interrupt가 소비하면 clear하며 장기 business fact가 아니다. |
| `policy_confirmation_receipts` | Application/Confirmation Controller만 append | 검증된 실제 사용자 interrupt 응답의 receipt. Agent/LLM은 생성·수정하지 않는다. |
| `retry_budget` | 결정적 Workflow budget controller | Repair/Revision/Retrieval/LLM call 상한을 집행하는 runtime control state. Agent semantic output이 아니다. |
| `prompt_context` | Prompt Runtime/Registry를 호출하는 결정적 runtime 경계 | PromptRef 선택·runtime 입력 계약을 위한 control context. business Artifact나 숨은 Conversation memory가 아니다. |
| `trace_context` | Application/Workflow observability propagation | Correlation/Trace context이며 Domain 또는 Agent business truth가 아니다. |

이 필드들도 patch allowlist를 가진다. Agent의 일반 owner-field patch로 approved_plan_id, execution/verification summary, receipt/budget/prompt/trace context를 변경하지 않는다.

Domain-backed reference/summary는 `applied=true` 또는 이미 확정된 Domain 사실을 결정적으로 projection한 경우에만 갱신한다. Graph State가 Domain Store보다 우선하지 않는다.

### 2.4 Revision·Invalidation

공식 State는 `artifact_id`, `revision`, `based_on`을 가진다.

```python
class StateArtifactRefV1:
    artifact_id: str
    revision: int

class StateArtifactMetaV1:
    artifact_id: str
    revision: int
    based_on: list[StateArtifactRefV1]
```

| 변경·판단 | 처리 |
| --- | --- |
| stale 판정 | 하드코딩된 단계 목록이 아니라 based_on의 upstream artifact_id·revision과 현재 활성 revision의 불일치로 계산한다. |
| InputRoutePlan 변경 | 이를 참조한 Retrieval과 downstream만 stale 처리한다. |
| OutputPlan 변경 | 이를 참조한 Planning·Review 등만 stale 처리한다. Input Route와 Retrieval이 같으면 다시 검색하지 않는다. |
| RequestIntent / Retrieval / WorkAnalysis 변경 | 같은 dependency 원칙으로 필요한 downstream만 재생성한다. |
| Domain 사실 | Graph invalidation으로 승인·실행·검증 사실을 소급 변경하지 않는다. |

#### Planning revision 후 Review RECHECK

| 시점 | 허용되는 사용 |
| --- | --- |
| 새 planning_result revision 생성 | 기존 plan_review는 current PASS·route authority로는 stale이다. |
| 바로 이어지는 RECHECK | 직전 `ReviewReviseV2.issues.affected_dimensions`와 optional action/route IDs만 bounded selector/context로 읽는다. 별도 장기 WorkflowSignal이나 Main State owner field를 만들지 않는다. |
| dimension-only REVISE | affected_dimensions가 non-empty이고 action/route IDs가 빈 값이어도 그대로 전달한다. ID를 임의 생성하지 않는다. |
| 새 PlanReviewResult revision 생성 | 직전 REVISE selector/context를 소비 완료로 폐기한다. |

이 제한적 전달은 stale Review를 current Review로 복권시키지 않는다.

## 3. Typed Schema 계약

### 3.1 RequestIntentV2

Request Understanding은 사용자 요청의 의미를 구조화하며 실제 Tool을 선택하지 않는다.

```python
class ConstraintProvenanceV1:
    source: Literal["USER_REQUEST", "CONFIRMATION_RESPONSE"]
    start_offset: int
    end_offset: int
    source_text: str | None = None

class ConstraintV1:
    kind: Literal["PERSON", "EMAIL", "DATE", "TIME", "RESOURCE", "SCOPE", "USER_REQUIREMENT"]
    field: str
    value: str | list[str]
    provenance: ConstraintProvenanceV1 | None = None
    source_resource_type: str | None = None

class AmbiguityV1:
    requires_confirmation: bool
    reason_codes: list[str]
    missing_fields: list[str]

class SourceResourceResponsibilityV1:
    resource_type: str
    required_information: list[str]

class OutputResourceResponsibilityV1:
    resource_type: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]

class ResourceResponsibilitiesV1:
    source_reads: list[SourceResourceResponsibilityV1]
    outputs: list[OutputResourceResponsibilityV1]

class RequestIntentV2:
    schema_version: Literal[2]
    meta: StateArtifactMetaV1
    goal: str
    completion_conditions: list[str]
    constraints: list[ConstraintV1]
    requested_effect_hints: list[Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]]
    requested_resource_hints: list[str]
    resource_responsibilities: ResourceResponsibilitiesV1 | None = None
    analysis_requirement: Literal["NONE", "REQUIRED"]
    ambiguity: AmbiguityV1
```

| 필드·상황 | 해석 |
| --- | --- |
| requested hints | 사용자 요청의 의미적 힌트다. Registry Tool 이름이 아니며 목표·완료조건·제약 밖의 Route나 Arguments를 허용하지 않는다. |
| resource_responsibilities | 현재 atomic Request Understanding 경로가 source/output 해결 책임을 보존한다. `source_reads`는 Connector가 해결할 기존 사실·identity인 required_information을, `outputs`는 사용자 요청의 Write effect를 가진다. UPDATE/DELETE처럼 기존 Resource를 바꾸는 요청은 같은 Resource type이 source와 output에 함께 있어야 하며, 파생 requested hints와 정확히 일치해야 한다. |
| ambiguity candidate | `missing_information_owner: NONE \| USER \| CONNECTOR`를 반환한다. CONNECTOR는 Retrieval로 해소하고 USER만 Confirmation으로 보낸다. candidate-only 분류를 확정 AmbiguityV1에 저장하지 않는다. |
| RESOURCE_SELECTED | 검증된 selected_resource_refs를 identify_goal·detect_ambiguity에 동일하게 전달한다. READ로 얻을 수 있는 본문·제목·발신자는 user-owned missing choice가 아니다. |
| 실제 사용자 선택 | recipient·시간·범위 등 사용자만 결정할 값은 선택 Resource가 있어도 자동 보완하지 않는다. Write의 필수 선택 누락은 Confirmation을 유지한다. |
| analysis_requirement | 별도 업무 사실·관계 해석 필요 여부다. 단순 조회·요약과 충분한 직접 ACTION은 NONE일 수 있다. 실제 Analysis 적용 조건은 §18을 따른다. |

#### Identity-bearing constraint provenance

**Source 검증**

- Provider identity로 사용되는 constraint는 finalized `RequestIntentV2`에 들어가기 전에 `request.finalize`의 기존 `finalize_intent → validate_intent` 단계에서 deterministic provenance 검증을 통과해야 한다. LLM은 constraint와 source span 후보를 제안할 수 있을 뿐 `provenance`를 확정하는 authority가 아니다.

- `start_offset:end_offset`은 `source`가 가리키는 현재 Run의 정확한 사용자 요청 또는 동일 Run Confirmation 응답 문자열에 대한 half-open span이다. 결정적 validator가 범위와 exact source slice를 constraint 값에 대조한 뒤에만 `ConstraintProvenanceV1`을 부여한다. 대조되지 않은 LLM 선언은 authority가 아니며 identity-bearing constraint로 사용할 수 없다.
- 정규화 값과 원문 표현이 다른 source scope는 `source_text`로 정확한 원문 span을 보존한다. 특히 `SCOPE.status`는 `source_resource_type`을 함께 가져야 하며, 원문 또는 동일 Run Confirmation에 명시된 source Resource 상태만 허용한다. Output effect·완료 후 기대 상태·다른 Resource 상태는 source search scope의 provenance가 아니다. LLM이 제안한 `source_text`와 Resource binding은 `finalize_intent → validate_intent`가 현재 Run source와 대조하며, 단순한 canonical status 문자열 포함 검사로 대체하지 않는다.

#### Source/output resolution responsibility

- 현재 atomic Request Understanding 경로는 단일·교차 Resource 여부와 무관하게 `resource_responsibilities`를 확정한다. nullable 표현은 compatibility 입력을 위한 것이며, 평면 resource/effect 목록을 정상 downstream이 다시 source/output으로 분류하게 두지 않는다.
- `source_reads`의 각 항목은 `resource_type`과 Connector가 해결할 기존 사실 또는 exact resource identity인 `required_information`을 가진다. Retrieval 전 부재는 user-owned missing choice가 아니다.
- `outputs`의 각 항목은 `resource_type`과 `CREATE | UPDATE | SEND | DELETE` 중 하나인 `effect`를 가진다. 같은 Write 결과의 Verification reread는 별도 source read 책임으로 만들지 않는다.
- source/output 책임을 투영한 Resource와 Effect 집합은 `requested_resource_hints`와 `requested_effect_hints`에 정확히 일치해야 한다. 불일치·중복 항목·지원하지 않는 Resource/effect 조합과 같은 Resource UPDATE/DELETE의 source 누락은 Provider 호출 전 Request Understanding validator가 거절한다.
- Tool Route는 검증된 책임을 IN Resource와 OUT Resource/Effect로 결정적으로 투영한다. Tool 이름과 Registry binding은 계속 Tool Route owner가 소유한다.

#### Natural-language target anchor와 identity

- 자연어 target anchor는 검색·discovery constraint이며 그 자체가 target identity authority가 아니다.
- 사용자가 선택한 `SelectedResourceRef`가 있으면 그 stable identity가 우선 authority다.
- 선택 Resource가 없으면 현재 Run Retrieval에서 해당 target scope의 eligible stable `ResourceRef`가 정확히 하나로 결속되고 Action evidence가 그 identity를 참조할 때만 existing-resource target으로 승격한다.
- substring·title similarity·LLM 유사 판단으로 identity를 확정하지 않는다. eligible 후보가 복수면 discovery 또는 confirmation을 유지하며 Planning이 임의의 한 후보를 선택해 Write target으로 만들 수 없다.

**GitHub repository와 선택 Issue**

- GitHub repository identity는 `kind="RESOURCE", field="repository"`인 단일 문자열 `owner/repository`로 표현한다. owner와 repository가 모두 비어 있지 않고 정확히 하나의 `/`로 구분되어야 하며, source에 없는 owner를 연결 계정·organization·최근 사용값·Provider 검색 결과·hard-coded 값 또는 LLM 추측으로 보완하지 않는다.

- `repository`처럼 owner가 없는 bare 값은 기존 deterministic default authority가 없는 한 `AmbiguityV1.requires_confirmation=true`로 처리한다. 기존 Request Understanding nested Confirmation과 동일 Run checkpoint resume를 사용하며 GitHub 전용 node, state, edge 또는 resume target을 추가하지 않는다.

선택된 GitHub Issue는 다음 identity를 보존한다.

| 필드 | 값 |
| --- | --- |
| connector_id | github |
| resource_type | github_issue |
| resource_id | owner/repository#issue_number |
| parent_resource_id | owner/repository |

검증된 parent_resource_id는 repository container authority가 될 수 있다. 같은 Run의 explicit provenance-validated repository가 있으면 exact match해야 한다. 불일치에 silent precedence를 적용하지 않고 기존 Confirmation 또는 fail-closed 경로를 사용한다.

- 이 provenance는 `ConstraintV1`의 선택적 source binding이며 새 Main State field나 장기 repository authority Artifact가 아니다. 권위는 기존 finalized `RequestIntentV2`, `SelectedResourceRefV1`/`ResourceRef`, frozen Route와 immutable Planning arguments 안에만 존재한다.

**Run allowlist와 현재 접근**

- Settings GitHub Repository 목록은 Run 시작 시 account/immutable-ID-bound allowlist로 동결한다. 이는 사용자 문장의 target provenance가 아니며 LLM이 생산하지 않는다. explicit/selected repository는 이 목록 안에서만 범위를 좁힌다.

- allowlist가 여러 개이거나 target이 미결정이면 첫 항목이나 legacy default로 WRITE target을 보정하지 않는다. 필요한 사용자 결정은 기존 Confirmation을 사용한다. 이전 Run/checkpoint는 시작 당시 binding을 유지하고 현재 Settings로 보충하지 않는다.

- `retrieval.execute_read`는 사용 전 current Provider access와 frozen allowlist를 검증한다. 권한 실패는 no-result가 아니며 반복/대체 Repository fallback을 금지한다. 승인, mandatory Write 정보, Claim/Attempt 정책은 변경하지 않는다.

### 3.2 ToolRoutePlanV2

Tool Route는 IN과 OUT을 한 번 결정해 Main State에 저장한다.

```python
class ToolRoutePlanV2:
    schema_version: Literal[2]
    input_plan: InputRoutePlanV1
    output_plan: OutputPlanV1
    tool_registry_version: str

class InputRoutePlanV1:
    meta: StateArtifactMetaV1
    input_routes: list[InputToolRouteV1]

class AnswerOutputPlanV1:
    meta: StateArtifactMetaV1
    output_mode: Literal["ANSWER"]

class ActionOutputPlanV1:
    meta: StateArtifactMetaV1
    output_mode: Literal["ACTION"]
    output_routes: list[OutputToolRouteV1]  # minItems=1

OutputPlanV1 = AnswerOutputPlanV1 | ActionOutputPlanV1
```

| 출력 variant | Schema 조건 |
| --- | --- |
| ANSWER | output_routes 필드 자체가 없어야 한다. 빈 list를 합성해도 contract violation이다. |
| ACTION | output_routes가 하나 이상이고 Registry에 없는 Tool ID는 표현할 수 없다. |

ANSWER + Write Tool처럼 불가능한 조합은 Schema/union 경계에서 먼저 차단한다.

```python

class InputToolRouteV1:
    route_id: str
    resource_type: str
    connector_id: str
    allowed_read_tool_ids: list[str]
    required: bool
    reason_codes: list[str]

class OutputToolRouteV1:
    route_id: str
    resource_type: str
    connector_id: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    selected_tool_id: str
    reason_codes: list[str]
```

규칙:

- Tool 이름·Effect는 Signed Tool Registry의 실제 Entry에서만 선택한다.
- Tool Route의 output effect는 `RequestIntentV2.requested_effect_hints`의 Write subset을 초과할 수 없다. READ-only intent에 LLM이 CREATE/UPDATE/SEND/DELETE 후보를 반환하면 결정적 경계가 `ANSWER`로 축소하며 Write Route는 0이어야 한다.
- `RESOURCE_SELECTED`의 exact resource type은 semantic candidate보다 우선하는 current-Run scope다. 후보가 다른 resource family를 제안하면 bounded semantic revision 또는 fail-closed하며 선택 identity를 새 값으로 교체하지 않는다.
- `input_routes`는 Retrieval이 사용할 허용 Read Tool 범위를 보존한다. Retrieval LLM이 다시 Tool 종류를 고르지 않는다.
- `output_routes`의 실제 Action Tool은 여기서 확정한다. Planning은 Tool을 다시 선택하지 않고 Arguments·내용만 작성한다.
- 후보 수를 임의 shortlisting하여 필요한 Tool을 제거하지 않는다. Main State에는 확정된 Route와 Registry binding을 온전히 보존한다.
- 특정 Node Prompt에는 전체 ToolRoute를 복제하지 않고 필요한 Route Projection만 전달한다.
- `input_routes[].allowed_read_tool_ids`는 Registry에서 READ capability로 등록된 Tool만 포함한다.
- `InputToolRouteV1.resource_type`과 `OutputToolRouteV1.resource_type`은 별도 `EMAIL/TASK/CALENDAR` family가 아니라 `SignedToolRegistryEntryV1.resource_type`의 canonical Connector resource identifier를 그대로 보존한다. 한 Input Route의 모든 `allowed_read_tool_ids`는 동일한 Registry `resource_type`과 exact match해야 하며, 서로 다른 resource type은 별도 Route다.
- `output_routes[].selected_tool_id`의 Registry resource/effect는 해당 Route의 `resource_type/effect`와 정확히 일치해야 한다.
- Tool 이름 parsing 또는 ad-hoc `ResourceTypeMapper`로 resource identity를 재해석하는 경로를 금지한다.

### 3.3 RetrievalResultV1 — 05 Retrieval owner reference

정확한 field/schema 권위는 `05 Context·Retrieval`이다. 06은 같은 class를 다시 정의하지 않는다.

| Workflow 소비 | 보존 위치 |
| --- | --- |
| coverage, evidence_refs, source_statuses, availability_results 등 필요한 필드 | versioned artifact를 Main State에 read-only로 보존하고 Node Projection으로 좁힘 |
| Raw Query Plan, Page Token, 후보 전체, RAG 내부 score | 05의 Retrieval Local State 또는 Run Cache. Main State에 복제하지 않음 |

### 3.4 WorkAnalysisResultV2

```python
class WorkFactV1:
    fact_id: str
    kind: Literal["TASK", "EVENT", "PERSON", "DATE", "TIME", "DEADLINE", "STATUS", "RESOURCE", "TEXT_CLAIM", "OTHER"]
    subject: str
    value: str
    derivation: Literal["EXPLICIT", "DERIVED"]
    evidence_refs: list[str]

class WorkRelationV1:
    relation_id: str
    kind: Literal["DEPENDS_ON", "ASSIGNED_TO", "DUE_AT", "DUPLICATES", "CONFLICTS_WITH", "RELATED_TO"]
    source_fact_id: str
    target_fact_id: str
    evidence_refs: list[str]

class WorkAmbiguityV1:
    code: str
    description: str
    requires_confirmation: bool
    evidence_refs: list[str]

class WorkRiskV1:
    kind: Literal["SCHEDULE_CONFLICT", "DEADLINE_RISK", "DUPLICATE_RISK", "MISSING_INFORMATION", "OTHER"]
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    description: str
    evidence_refs: list[str]

class RouteActionNecessityV1:
    route_id: str
    status: Literal["REQUIRED", "NOT_REQUIRED", "UNDETERMINED"]
    reason: str
    evidence_refs: list[str]
    candidate_refs: list[str]

class WorkAnalysisResultV2:
    schema_version: Literal[2]
    meta: StateArtifactMetaV1
    work_facts: list[WorkFactV1]
    relations: list[WorkRelationV1]
    ambiguities: list[WorkAmbiguityV1]
    risks: list[WorkRiskV1]
    action_necessity: Literal["REQUIRED", "NOT_REQUIRED", "UNDETERMINED"]
    action_necessity_reason: str | None
    route_action_necessities: list[RouteActionNecessityV1]
    policy_confirmation_receipt_refs: list[StateArtifactRefV1]
    evidence_refs: list[str]
```

업무 분석은 Evidence를 해석하지만 Tool 선택·Arguments 작성·정책 최종 판정은 하지 않는다.

| 결과 | 의미·조건 |
| --- | --- |
| Route별 `NOT_REQUIRED` | 정확한 중복 등 현재 관측이 해당 Route의 요청 효과를 이미 충족해 새 Action이 필요 없다는 업무 사실이다. Output Route는 capability 기록으로 유지한다. |
| Route별 `REQUIRED` | 해당 Route의 실행 후보를 Planning이 작성한다. 다른 Route의 `NOT_REQUIRED`가 이 Route를 제거하지 않는다. |
| Override 후 `REQUIRED` | DUPLICATE_OVERRIDE 또는 CONFLICT_OVERRIDE에 필요한 current APPROVED Receipt를 policy_confirmation_receipt_refs와 based_on에 포함한다. |

aggregate `action_necessity`는 route-scoped 결과에서 결정적으로 파생하는 persisted compatibility 필드이며 별도 의미 판정 authority가 아니다. 현재 Planning은 `route_action_necessities`만 소비해 필요한 Route를 선별한다.

### 3.5 Planning Result

```python
class AnswerDraftV2:
    schema_version: Literal[2]
    meta: StateArtifactMetaV1
    answer: str
    evidence_refs: list[str]

class ActionPlanDraftV2:
    schema_version: Literal[2]
    meta: StateArtifactMetaV1
    actions: list[PlannedActionV2]

class PlannedActionV2:
    action_id: str
    route_id: str
    tool_id: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    arguments: CanonicalArguments
    evidence_refs: list[str]
    depends_on_action_ids: list[str]
```

불변조건:

- `tool_id`와 `effect`는 `tool_route_plan.output_plan`이 `ActionOutputPlanV1`일 때 그 `output_routes`의 선택값에서 복사한다.
- Planning LLM은 새로운 Tool 이름을 만들거나 Route를 변경하지 않는다.
- Tool별 Arguments는 선택된 Tool의 Versioned Schema로 검증한다.
- 여러 Action의 최종 Typed Plan 조립은 결정적 Assembler가 수행한다.

### 3.6 PlanReviewResultV2

Review는 판정 종류에 따라 필요한 필드가 다르므로 하나의 넓은 Object에 nullable field를 섞지 않고 **discriminated union**으로 제한한다.

```python
class ReviewBaseV2:
    schema_version: Literal[2]
    meta: StateArtifactMetaV1

ReviewDimensionIdV1 = Literal[
    "review.inspect_goal_and_evidence",
    "review.inspect_action_scope_and_route",
    "review.inspect_constraints_and_policy_summary",
]

class ReviewIssueV1:
    code: str
    description: str
    affected_dimensions: list[ReviewDimensionIdV1]  # minItems=1; canonical inspector responsibility ID closed set
    affected_action_ids: list[str]   # dimension-only issue에서는 빈 list 허용
    affected_route_ids: list[str]    # dimension-only issue에서는 빈 list 허용
    evidence_refs: list[str]

class EvidenceGapV1:
    code: str
    description: str
    required_information: list[str]

class RouteIssueV1:
    code: str
    description: str
    affected_route_ids: list[str]

class ReviewConfirmationV1:
    question: str
    options: list[str]

class ReviewBlockerV1:
    code: str
    description: str
    affected_action_ids: list[str]

class ReviewPassV2(ReviewBaseV2):
    status: Literal["PASS"]
    summary: str

class ReviewReviseV2(ReviewBaseV2):
    status: Literal["REVISE"]
    issues: list[ReviewIssueV1]

class ReviewRetrieveMoreV2(ReviewBaseV2):
    status: Literal["RETRIEVE_MORE"]
    evidence_gaps: list[EvidenceGapV1]

class ReviewRouteReconsiderationV2(ReviewBaseV2):
    status: Literal["ROUTE_RECONSIDERATION"]
    route_issues: list[RouteIssueV1]

class ReviewConfirmV2(ReviewBaseV2):
    status: Literal["CONFIRM"]
    confirmation: ReviewConfirmationV1

class ReviewBlockV2(ReviewBaseV2):
    status: Literal["BLOCK"]
    blockers: list[ReviewBlockerV1]

PlanReviewResultV2 = (
    ReviewPassV2 | ReviewReviseV2 | ReviewRetrieveMoreV2
    | ReviewRouteReconsiderationV2 | ReviewConfirmV2 | ReviewBlockV2
)
```

- `PASS + confirmation`처럼 계약상 불가능한 조합을 Schema 단계에서 표현할 수 없게 한다.
- Review는 Plan 품질을 검토하지만 실행 허용의 최종 권위가 아니다.

### 3.7 WorkflowSignalV1 사용 계약

`WorkflowSignalV1`의 **유일한 타입 정의는 §2 Main State 계약의 canonical definition**이다. 이 절은 그 타입의 producer/consumer/clear 동작만 정의하며 union을 재정의하지 않는다. 확정 업무 Artifact와 흐름 제어 요청을 분리한다. Subgraph가 성공 Artifact를 만들지 못하고 다른 단계가 필요하면 `typed_result=None`과 함께 Main Supervisor가 소비할 Typed Signal을 반환한다.

- `RetrievalRequiredV1`은 `RetrievalNeedV1[]`로 부족한 정보·Evidence 종류와 추가 조회 목적을 기록한다.
- `RouteReconsiderationRequiredV1`은 `reason_codes`로 현재 Route 재검토 사유를 기록하고 Tool Route를 직접 덮어쓰지 않는다. 영향 Route 상세는 해당 Subgraph의 typed issue/result가 함께 보존한다.
- `RequestReconsiderationRequiredV1`은 현재 Request Intent revision과 이를 반증·보완한 현재 Evidence 관측을 함께 묶는다. local fact repair나 Route 문제에는 사용하지 않는다.
- Review의 계획 수정 요청은 별도 WorkflowSignal 타입을 만들지 않고 `ReviewReviseV2.issues`를 Planning revision Input Projection으로 전달한다.
- Signal은 해당 Back-edge/Interrupt가 소비되면 clear하며 장기 업무 사실로 취급하지 않는다.

#### WorkflowSignal producer → consumer → clear 계약

| Signal | 생성 조건 | 소비 경계 | clear 시점 |
| --- | --- | --- | --- |
| `ConfirmationRequiredV1` | 6개 owner Subgraph의 공식 `NEEDS_CONFIRMATION` finalization | Supervisor → Application `RequestConfirmation` → LangGraph interrupt | 등록된 interrupt/checkpoint가 성립하고 해당 confirmation control path가 signal을 인수한 뒤. Resume 이후 business fact로 유지하지 않는다. |
| `RouteReconsiderationRequiredV1` | Retrieval / Work Analysis / Planning의 `ROUTE_RECONSIDERATION_REQUIRED`, Review의 `ROUTE_RECONSIDERATION` | Supervisor → Tool Route Back-edge | Tool Route owner가 reconsideration input projection으로 인수할 때 |
| `RequestReconsiderationRequiredV1` | Work Analysis가 현재 Evidence로 현재 Request Intent의 의미 재검토 필요를 확정한 경우 | Supervisor → 기존 Request Understanding Back-edge | Request Understanding이 같은 artifact identity의 새 revision을 확정하고 dependent artifact를 invalidate한 뒤 |
| `RetrievalRequiredV1` | Work Analysis `NEEDS_MORE_DATA` 또는 Review `RETRIEVE_MORE`가 **현재 InputRoutePlan으로 해결 가능할 때만** | Supervisor → Retrieval Back-edge | Retrieval owner가 additional-retrieval input projection으로 인수할 때. Retrieval 자체 local `NEEDS_MORE_DATA` self-loop에는 생성하지 않는다. |
| `BlockedSignalV1` | role-local blocked/block finalization이 reason code를 control signal로 전달해야 하는 경우 | Supervisor terminal handler → 필요한 Domain `BlockRun`/terminal reconciliation | terminal/reconcile control path가 reason을 인수한 뒤. Domain terminal 사실의 대체 authority로 남기지 않는다. |

Signal consumer가 해당 signal을 처리한 뒤 동일 signal을 다음 unrelated Agent invocation에 자동 전달하면 실패다. Signal은 upstream Artifact를 직접 수정할 권한도, Domain 상태를 변경할 권한도 갖지 않는다.

### 3.8 Subgraph 반환 Envelope

```python
class SubgraphReturnV2[T]:
    disposition: str
    typed_result: T | None
    workflow_signal: WorkflowSignalV1 | None
```

규칙:

- Schema·Contract가 완결된 공식 `typed_result`만 Main State의 해당 Owner field에 병합한다. 성공 disposition이 아니어도 독립적으로 유효한 `PARTIAL` Retrieval Result나 Review Result는 저장할 수 있다.
- confirmation·route 재검토·block처럼 아직 완결되지 않은 candidate는 업무 Artifact로 저장하지 않고 Typed `workflow_signal`로만 전달한다.
- `workflow_signal`은 다음 Subgraph의 Node Input Projection에 필요한 경우에만 전달한다.

## 4. Agent Subgraph 공통 계약

### 4.1 Agent와 LLM Call

| 개념 | 구분 |
| --- | --- |
| Agent | Main Supervisor가 호출하는 LangGraph Subgraph |
| Role | 공식 결과와 책임 경계 |
| Node | Subgraph 내부 단계. LLM 또는 Deterministic Node |
| LLM Call | 모델 추론 1회. Agent·Node 개수와 같지 않음 |
| Local State | invocation 안의 작업 메모리 |
| Node Projection | 현재 Node에 필요한 Local/Main State의 Typed 입력 |

### 4.2 공통 Runtime Envelope

```python
class AgentRuntimeEnvelopeV2:
    schema_version: Literal[2]
    agent_role: str
    invocation_id: str
    node_state: str
    attempt_no: int
    schema_repair_count: int
    semantic_revision_count: int
    failure_record: AgentFailureRecord | None
    disposition: SubgraphDispositionV2 | None
```

`SubgraphDispositionV2`는 다음 role-specific disposition union의 공통 타입이다.

```python
SubgraphDispositionV2 = Literal[
    "COMPLETE", "INVALID",
    "ROUTE_READY", "NO_TOOL_NEEDED",
    "SUFFICIENT", "NO_FETCH_NEEDED", "NEEDS_MORE_DATA", "PARTIAL",
    "ANSWER_ONLY", "PLAN_READY",
    "PASS", "REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION", "CONFIRM",
    "NEEDS_CONFIRMATION", "REQUEST_RECONSIDERATION_REQUIRED", "ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED", "BLOCK"
]
```

공통 Envelope는 관측·resume metadata를 위해 union을 사용하지만 실제 Subgraph Return Schema는 자기 Role에서 허용한 disposition subset으로 다시 좁힌다. 이 Envelope는 모든 Agent의 공통 실행 metadata만 가진다. 업무 데이터는 범용 `input_projection: dict` 하나에 몰지 않고 **Subgraph별 Typed Local State**에 둔다.

### 4.3 Node Input Projection 원칙

Node는 자신의 Output에 필요한 최소 State만 받는다. Main State에 값이 있다는 이유로 모든 Node에 전달하지 않는다.

| 책임 | 입력 Projection 예 |
| --- | --- |
| Tool Route determine resources | request_intent |
| Retrieval plan_query | 현재 Run user_request + request_intent + input_routes + retrieval_budget (follow-up은 bounded prior QueryAttemptV1·SufficiencyIssue·read-result summary·selected Evidence projection 추가) |
| Retrieval availability | user time constraints + normalized busy intervals (deterministic) |
| Retrieval RAG select | request_intent + ranked/fetched segment handles |
| Retrieval sufficiency | request_intent + selected evidence + retrieval_budget |
| Work Analysis fact extraction | user_request + request_intent + optional evidence |
| Planning compose_answer | user_request + request_intent + optional work_analysis + evidence refs |
| Planning objective writer | user_request + one OutputToolRouteV1 + optional work_analysis + evidence refs |
| Planning argument writer | one OutputToolRouteV1 + validated ActionObjectiveCandidateV1 + Tool Schema |
| Review inspect | request_intent + action_plan + evidence/policy summary. 초기 goal/evidence 검토에서 current-Run `EVENT_TIME`만 적용하고 정규화된 Gmail 수신 envelope를 확인할 수 있으면, Resource 수신 metadata 시각을 본문·업무일과 분리한 Evidence projection 및 optional Run 기준시각을 제공한다. 사용자 수정·확인·RECHECK는 기존 입력을 유지한다. |

Request는 run_input을 projection하고, Back-edge 재진입에서는 해당 Node에 필요한 workflow_signal만 추가한다. 아래 입력은 전체 State의 숨은 승계를 허용하지 않는다.

### 4.4 Local Loop

- Schema Repair는 해당 Node의 Output Shape만 고친다.
- Semantic Revision은 같은 Subgraph 책임 안에서만 수행한다.
- 다른 전문 책임이 필요한 경우 Subgraph 내부에서 다른 Agent를 호출하지 않고 Parent disposition을 반환한다.
- Repair Budget은 호출당 최대 1회를 기본으로 한다.

## 5. 전문 Agent Subgraph

### 5.1 책임 표

| Agent Subgraph | 유일한 책임 | 금지 | Parent 반환 |
| --- | --- | --- | --- |
| Request Understanding | 사용자 목표·완료조건·제약·모호성 구조화 | Tool 선택·Google 조회·Action 작성 | `RequestIntentV2` |
| Tool Route | IN Resource/Read Tool 범위와 OUT Resource/Effect/Tool 결정 | Query 작성·Evidence 판단·Arguments 작성 | `ToolRoutePlanV2` |
| Retrieval | 고정된 IN Route에서 Query→Read→RAG→Evidence→Sufficiency | OUT Tool 변경·업무 의미 최종 해석·Write | `RetrievalResultV1` |
| Work Analysis | Evidence를 업무 사실·관계·모호성·위험으로 해석 | Tool 선택·Arguments 작성·정책 최종 판정 | `WorkAnalysisResultV2` |
| Planning | 고정된 OUT Route를 실제 Answer 또는 Tool Arguments/Action Plan으로 표현 | Tool 재선택·승인·실행 | `AnswerDraftV2` 또는 `ActionPlanDraftV2` |
| Review | 목표·근거·과잉·모순·실행 가능성 검토 | Tool 실행·Domain 허용 최종 판정 | `PlanReviewResultV2` |

### 5.2 Request Understanding Subgraph

| 책임 | 처리 |
| --- | --- |
| `identify_goal` | 목표·완료조건·일반 제약·분석 필요 후보를 만든다. Resource 역할과 source status를 만들지 않으며 원문 period를 보존한다. |
| `identify_source_dependencies` | Runtime이 제공한 READ 가능 Resource 후보별로 기존 사실·현재 상태·identity가 필요한지 판정한다. Output effect는 판정하지 않는다. |
| `identify_output_responsibilities` | Runtime이 제공한 output 가능 Resource 후보 중 사용자가 요청한 Write effect만 sparse 목록으로 반환한다. 빈 목록은 외부 output 없음이며 `NONE` 항목을 만들지 않는다. Source dependency는 판정하지 않는다. |
| `merge_resource_responsibilities` | 검증된 두 atomic 결정을 기존 `ResourceResponsibilitiesV1.source_reads/outputs`로 결정적으로 조립한다. |
| `identify_source_status` | 확정된 `source_reads.resource_type`만 대상으로 추가 source 상태 범위를 판단한다. output effect·Resource 역할·Tool·Query는 바꾸지 않는다. |
| `identify_temporal_scope` | Gmail period가 있을 때 `MESSAGE_TIME \| EVENT_TIME`을 판단한다. 없으면 pass-through한다. 일반 코드의 키워드·정규식으로 이 의미를 교체하지 않는다. |
| `detect_ambiguity` | 사용자 선택 누락과 Connector READ로 해소할 정보를 구분한다. 입력은 목표·완료조건·제약과 분리 확정된 `resource_responsibilities`만 사용하고, 이를 합친 legacy resource/effect hint는 다시 판단 근거로 쓰지 않는다. 초기 연결 검사에는 §5.3의 같은 Application use case를 사용한다. |
| `finalize_intent → validate_intent` | 실제 current-run source text와 identity-bearing 후보를 대조해 provenance를 부여하고 확정한다. |

각 LLM 호출은 자기 책임만 수행한다. 시간축 operation은 새로운 identity resolver나 Main Agent owner가 아니다. 표는 책임 구분이며 미래 Node 개수나 물리 배치를 고정하지 않는다.

현재 문서의 Local State 참조:

```python
class RequestGoalCandidateV1:
    goal: str
    completion_conditions: list[str]
    constraints: list[ConstraintV1]
    requested_effect_hints: list[Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]]
    requested_resource_hints: list[str]
    resource_responsibilities: ResourceResponsibilitiesV1 | None
    analysis_requirement: Literal["NONE", "REQUIRED"]

class RequestUnderstandingStateV2:
    request_text: str
    entry_mode: Literal["AGENT_SEARCH", "RESOURCE_SELECTED"]
    selected_resource_refs: list[SelectedResourceRefV1]
    goal_candidate: RequestGoalCandidateV1 | None
    ambiguity_candidate: AmbiguityV1 | None
    final_intent: RequestIntentV2 | None
```

### 5.3 Tool Route Subgraph

| 책임 | 처리 |
| --- | --- |
| `determine_io_resources` | 정상 current Intent에서는 확정된 `resource_responsibilities`를 IN Resource와 OUT Resource·Effect로 결정적으로 투영한다. responsibilities가 없는 compatibility Intent에서만 bounded LLM fallback으로 기존 hints의 역할을 복원하며 새 Resource/effect를 고르지 않는다. 실제 Tool 이름은 생성하지 않는다. |
| `bind_registry_candidates` | Signed Tool Registry의 Resource·Effect·Schema 적합성으로 실제 후보를 결정적으로 결합한다. |
| `select_tool_if_needed` | 후보 하나는 결정적으로 확정하고, 여러 후보의 의미 선택이 필요한 경우에만 해당 Route의 후보 안에서 선택한다. |
| `finalize_route / validate_route` | Route와 Registry binding을 확정·검증해 Main State에 병합한다. downstream은 Tool을 재선택하지 않는다. |

모델 부담 감소만을 이유로 heuristic shortlist를 만들거나 등록 Tool을 제거하지 않는다. OUT Route의 Tool identity는 Planning Assembler가 복사한다.

현재 문서의 Local State 참조:

```python
class OutputRouteIntentV1:
    resource_type: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]

class IORouteIntentV1:
    output_mode: Literal["ANSWER", "ACTION"]
    input_resource_types: list[str]
    output_intents: list[OutputRouteIntentV1]

class RegistryCandidateSetV1:
    route_id: str
    resource_type: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    candidate_tool_ids: list[str]

class ToolRouteStateV1:
    request_intent: RequestIntentV2
    registry_snapshot_ref: str
    io_resource_candidate: IORouteIntentV1 | None
    io_resource_failure: FailureRecordV1 | None
    registry_candidates: list[RegistryCandidateSetV1]
    bound_input_routes: list[InputToolRouteV1]
    bound_output_routes: list[OutputToolRouteV1]
    final_route: ToolRoutePlanV2 | None
```

`io_resource_failure`는 `determine_io_resources`의 bounded semantic revision이 소진됐을 때 마지막 typed validation failure를 보존한다. 사용자 확인 interrupt의 reason과 affected path는 이 record에서 투영하며 generic route 상태로 덮어쓰지 않는다.

#### Policy Precondition READ

| 상황 | 처리 |
| --- | --- |
| TASK CREATE | 기존 미완료 Task의 중복 검사용 Tasks READ를 필수 IN Route에 보강한다. |
| CALENDAR CREATE | 대상 Calendar의 충돌 검사용 Event/FreeBusy READ를 보강한다. |
| 공통 | 결정적 PolicyPreconditionResolver의 보강이며 두 번째 의미 Tool 선택이 아니다. OUT Route를 변경하지 않는다. |
| 사용자 지정 Source·기간·Resource 밖의 READ 필요 | `SCOPE_EXPANSION_REQUIRED`로 추가 범위·이유를 먼저 확인한다. 확인 전 materialize/실행하지 않는다. |
| 범위 확장 거절·검사 불가 | 필수 검사를 우회한 Write Plan을 만들지 않고 확인/차단·안내로 처리한다. 같은 Resource의 더 좁은 사용자 IN Route가 있으면 먼저 그 범위에서 검사를 충족한다. |

#### 요청 단위 초기 Connector prerequisite

| 호출 지점 | 검사 |
| --- | --- |
| Tool Routing `validate_route` | Registry로 검증된 IN/OUT Connector ID를 `CheckConnectorPrerequisites`에 전달한다. Application이 OAuth Credential Port의 token-free status·필수 권한을 검사한다. |
| Request Understanding `detect_ambiguity` | 같은 use case를 사용한다. goal resource hint가 Registry에 정확히 등록된 경우에만 Connector로 매핑해, 미연결인데 repository 등 추가 입력을 먼저 묻지 않도록 한다. |
| unknown hint | 이름·문자열·keyword로 추측하지 않는다. 기존 의미 해소와 최종 Route 검증을 유지한다. |
| Main Graph | Google/GitHub 전용 분기나 Provider I/O를 추가하지 않는다. |

| 상황 | 결과·보존 조건 |
| --- | --- |
| 새 Run | `admitted_connector_ids=[]`에서 시작한다. 통과한 ID는 same-Run Back-edge·checkpoint·resume에서 보존한다. Prompt 입력·credential·접근 권위는 아니다. |
| admission 후 인증 만료 | 기존 접근/REAUTH_REQUIRED 안전 경로를 사용한다. |
| 초기 미연결·초기 REAUTH_REQUIRED·권한 부족·구성 실패 | `ToolRouteResultV1.PREREQUISITE_UNMET`과 bounded 안내로 전달한다. Request 쪽 검사 실패도 `finalize_intent → end`의 terminal handoff를 사용하며 ambiguity LLM·Confirmation interrupt를 만들지 않는다. |
| 초기 실패 종료 | `FinalizeIntentV1(intent=COMPLETED, result_kind=PARTIAL, reason_code=CONNECTOR_PREREQUISITE_UNMET, prerequisite_message=...)`에서 `CompleteAnswerOnlyRun`으로 닫는다. 실행하지 않았으며 Settings 조치 후 새 요청이 필요함을 알린다. |
| 종료 금지 조건 | Plan/Action/in-flight 또는 Domain REAUTH_REQUIRED가 이미 있으면 초기 실패 종료를 적용하지 않는다. |
| admitted_connector_ids 없는 배포 전 checkpoint | 초기 admission을 소급 적용하지 않는다. 기존 실행·재인증 계약을 유지한다. |
| Repository 설치·접근 | 기존 `GetRepositoryAccess`/Connector READ owner로 검증한다. 실패를 no-result로 바꾸거나 다른 repository로 fallback하지 않는다. |
| OAuth callback | Run-neutral이다. 초기 실패에서 인증 대기 checkpoint·interrupt·자동 resume를 만들지 않는다. |

> **선언 확인 필요:** 초기 실패 처리에는 `PREREQUISITE_UNMET`이 있지만 §4.2의 `SubgraphDispositionV2`에는 없다. 기존 타입 선언에 값을 임의 추가하거나 다른 disposition으로 치환하지 않는다.

### 5.4 Retrieval Subgraph

Retrieval은 고정된 IN Route에서 자료 수집·관련 Segment 선별·Evidence 구성·충분성 판정을 수행한다. Run-scoped RAG를 포함하되 영구 Vector Index는 필수가 아니다. 가져온 후보 전체를 다음 LLM에 전달하지 않는다.

`RetrievalState`와 `RetrievalResultV1`의 정확한 schema·검색 의미는 `05`를 사용한다. query attempts, source statuses, availability results, read/segment handles, RAG candidates, evidence selection, sufficiency, final result를 별도로 재정의하지 않는다.

raw user_request를 Local State/Prompt의 독립 semantic authority로 추가하지 않는다.

#### 현재 책임별 입력

| 책임 | 입력 |
| --- | --- |
| `plan_query` · 최초 | 현재 Run user_request + request_intent + input_routes + retrieval_budget |
| `plan_query` · 후속 | 최초 입력 + current_round_no + prior QueryAttemptV1 + unresolved SufficiencyIssueV2 + bounded read-result summary |
| `plan_query` · 사용자 추가 검색 | checkpointed pending_user_retrieval_need. raw UI request나 이미 clear한 handoff payload를 다시 읽지 않음 |
| `build_query` | query_plan + input_routes. 결정적 처리 |
| `execute_read` | 검증된 Query + allowed_read_tool_ids. 결정적 Application operation에서 ConnectorReadPort 호출 |
| `normalize_segments` | Read Result Handle. 결정적 처리 |
| `rag_retrieve_rerank` | request_intent + segment_handles |
| `select_evidence` | request_intent + top RAG candidates. EXCLUDE_EVIDENCE는 이 단계의 결정적 exclusion input |
| `assess_sufficiency` | request_intent + selected evidence |

#### 반복·Route 변경

| 상황 | 처리 |
| --- | --- |
| 같은 Route 안의 Query/Page/Detail 추가 | Retrieval invocation 내부의 bounded loop다. Parent signal을 만들지 않고 SufficiencyIssueV2·QueryAttemptV1·read_result_handles의 Local Projection을 사용한다. |
| follow-up SEARCH 변경 | typed ChangedSearchSpecV1을 결정적 SourceFetchPlanBuilder가 materialize한다. LLM은 Provider-native Query·RFC3339·MCP Arguments를 만들지 않는다. |
| raw continuation | `RunRetrievalCachePort → InMemoryRunRetrievalCache`에만 보존한다. Supervisor·Main State·WorkflowSignal은 소유하지 않는다. |
| 다른 Owner가 추가 검색 요청 | Work Analysis·Review가 `RetrievalRequiredV1`으로 부족 정보를 전달한다. |
| 새로운 Provider/Resource Route 필요 | `ROUTE_RECONSIDERATION_REQUIRED`를 Parent에 반환한다. Retrieval이 Tool을 다시 선택하지 않는다. |

FreeBusy interval의 교집합·차집합·가용 시간 계산도 결정적 Retrieval Application 책임이다. LLM Work Analysis에 산술 계산을 맡기지 않는다.

#### 인물 선택 후 같은 Run 검색

05가 제공한 후보 선택은 `retrieval.assess_sufficiency` origin과 finalize interrupt boundary를 사용한다.

| 조건 | 처리 |
| --- | --- |
| 검증된 선택 + acquisition budget 있음 | finalize → plan_query로 같은 frozen Route의 exact identity 검색 |
| 재검색 시 보존 | Query history·Evidence·선택 provenance. 새 Domain 상태/resume target을 만들지 않음 |
| 추가 수집 불가 | 기존 PARTIAL/BLOCKED 종료 규칙 적용 |


`person_candidates`, `selected_person_identities`, `unresolved_event_dates`는 05 소유 typed 결과다. 기존 checkpoint에서 필드가 없으면 빈 값으로 읽고, Workflow가 인물·행사 연도를 재해석하지 않는다.

### 5.5 Work Analysis Subgraph

| 책임 | 생성·검증 범위 |
| --- | --- |
| `extract_work_facts` | Evidence에 명시되거나 근거로 추론 가능한 업무 사실 |
| `resolve_entity_relations` | 사람·업무·Resource identity·ownership/reference 관계 후보. entity_relation_candidates만 갱신 |
| `resolve_temporal_dependencies` | 날짜·기간·선후·dependency 후보. temporal_dependency_candidates만 갱신. Calendar 산술·DAG 검증은 소유하지 않음 |
| `detect_duplicate_conflict_candidates` | fact↔fact duplicate_conflict_candidates 제안. DUPLICATES·CONFLICTS_WITH 최종 판정 아님 |
| `assess_requested_task_satisfaction` | 현재 Task 관측이 요청 업무를 이미 만족하는지 SATISFIED·NOT_SATISFIED·UNDETERMINED로 평가. fact↔fact 관계는 만들지 않음 |
| `validate_relations` | 세 후보 collection을 정규화된 Source·Calendar availability·Task 현재 상태로 검증해 validated_relations·relation_validation_ambiguities 기록 |
| `assess_action_necessity` | frozen Output Route별 현재 적용 여부를 한 번 판단. Task CREATE는 앞선 중복 검토 결과에서 결정적으로 파생 |
| `assess_information_gaps` | 현재 목표의 부족 정보와 해결 가능한 Retrieval Need. ambiguity_candidates·retrieval_needs만 갱신 |
| `assess_operational_risks` | 과잉 실행·일정/업무 위험을 operational_risk_candidates에 기록. 실행 필요성·Policy·Approval·중복·충돌을 다시 판단하지 않음 |
| `assemble_work_analysis / validate_work_analysis` | 검증된 결과를 WorkAnalysisResultV2로 조립·검증 |

서로 다른 의미 판단을 한 LLM 호출에 facts·relations·dependencies·duplicates·gaps·risks로 모두 요구하지 않는다. Tool이나 Action Arguments를 만들지 않는다.

현재 문서의 Local State 참조:

```python
class TemporalDependencyCandidateV1:
    source_fact_ref: str
    target_fact_ref: str
    relation: Literal["BEFORE", "AFTER", "DEPENDS_ON", "SAME_WINDOW", "OTHER"]
    evidence_refs: list[str]

class DuplicateConflictCandidateV1:
    relation_kind: Literal["DUPLICATE", "CONFLICT"]
    subject_ref: str
    candidate_resource_ref: str
    evidence_refs: list[str]

class OperationalRiskCandidateV1:
    code: str
    description: str
    affected_resource_refs: list[str]
    evidence_refs: list[str]

class WorkAnalysisStateV2:
    user_request: str
    request_intent: RequestIntentV2
    evidence_refs: list[str]
    fact_candidates: list[WorkFactV1]
    entity_relation_candidates: list[WorkRelationV1]
    temporal_dependency_candidates: list[TemporalDependencyCandidateV1]
    duplicate_conflict_candidates: list[DuplicateConflictCandidateV1]
    validated_relations: list[WorkRelationV1]
    relation_validation_ambiguities: list[WorkAmbiguityV1]
    ambiguity_candidates: list[WorkAmbiguityV1]
    retrieval_needs: list[RetrievalNeedV1]
    operational_risk_candidates: list[OperationalRiskCandidateV1]
    final_analysis: WorkAnalysisResultV2 | None
```

#### 조건부 적용과 관계 확정

| 상황 | 처리 |
| --- | --- |
| Policy Precondition만으로 진입한 Task/Calendar CREATE | entity/temporal 책임을 우회해 guarded duplicate/conflict 책임을 적용한다. |
| 서로 다른 fact operand가 2개 미만 | relation schema상 후보가 없으므로 빈 candidate를 결정적으로 만든다. validate_relations와 이후 Policy 판단은 생략하지 않는다. |
| analysis_requirement=REQUIRED | 전체 semantic relation 책임을 유지한다. |
| 검증 전 relation 후보 | WorkAnalysisResultV2.relations에 직접 넣지 않는다. |
| 정확 중복 확정 | 해당 Route를 `NOT_REQUIRED`로 두고 기존 Resource를 보여주며 새 Action을 만들지 않는다. |
| 중복을 인지하고도 추가 생성 요청 | 즉시 Planning하지 않는다. WorkAnalysis.NEEDS_CONFIRMATION + DUPLICATE_OVERRIDE_REQUIRED로 2차 확인한 뒤 새 생성 후보를 허용한다. |
| 검증된 Calendar 충돌 | CONFLICT_OVERRIDE_REQUIRED Confirmation 없이 충돌 Action Plan으로 진행하지 않는다. |
| 유사 후보·검증 불가 관계 | ambiguity/risk 또는 추가 확인으로 남긴다. 가능한 관계는 Source ID·Evidence ref 무결성을 검증한 뒤 조립한다. |

### 5.6 Planning Subgraph

Planning 진입 시 Tool Route는 이미 확정되어 있다.

| 현재 입력 | 적용 책임 |
| --- | --- |
| ANSWER Route | Work Analysis·확인 필요가 없으면 현재 Run 원문과 허용 Evidence ref로 outline을 결정적으로 만들고 compose_answer만 호출. 그 외에는 outline_answer · compose_answer |
| 모든 ACTION Route가 `NOT_REQUIRED` | 근거와 no-action reason을 답변으로 작성 |
| 하나 이상의 ACTION Route가 `REQUIRED` | 필요한 Route만 action objective와 Tool Arguments 작성, 결정적 dependency 구성·Plan 조립·검증 |

분기 진입은 `planning.choose_answer_or_action_from_route`의 결정적 Application operation이며 별도 checkpoint/resume Runtime Node가 아니다.

현재 문서의 Local State 참조:

```python
class ActionObjectiveCandidateV1:
    route_id: str
    objective: str
    target_semantics: str
    scope_constraints: list[str]

class ToolArgumentCandidateV1:
    route_id: str
    tool_id: str
    arguments: CanonicalArguments

class ActionDependencyCandidateV1:
    action_id: str
    depends_on_action_id: str
    reason: str

class PlanningStateV2:
    user_request: str
    request_intent: RequestIntentV2
    output_plan: OutputPlanV1
    work_analysis: WorkAnalysisResultV2 | None
    evidence_refs: list[str]
    action_objective_candidates: list[ActionObjectiveCandidateV1]
    argument_candidates: list[ToolArgumentCandidateV1]
    dependency_candidates: list[ActionDependencyCandidateV1]
    final_result: AnswerDraftV2 | ActionPlanDraftV2 | None
```

#### Route와 Action 작성

- `OutputPlanV1`은 사용자가 요구한 **출력 capability와 허용 Tool 경로**를 고정하지만 실제 Action 생성이 항상 필요하다는 보장은 아니다. Retrieval/Analysis에서 현재 상태가 이미 목표를 충족함이 확인되면 Planning은 Route를 변경하지 않고 Evidence 기반 Answer로 종료할 수 있다.
- `draft_action_objective_per_output_route`는 frozen Output Route 하나에 대해 `ActionObjectiveCandidateV1`을 만들고 해당 `route_id`의 `action_objective_candidates`만 갱신한다. 사용자 목표·target semantics·scope constraint만 작성하며 Tool identity/effect/arguments를 바꾸지 않는다.
- `compose_arguments_per_output_route`는 같은 `route_id`의 검증된 `ActionObjectiveCandidateV1` + 현재 Route의 `selected_tool_id` + 해당 Tool Schema + 현재 검증된 Request Intent 제약만 보고 `ToolArgumentCandidateV1`의 business arguments를 직렬화한다. objective가 없거나 route_id가 맞지 않으면 fail closed한다.
#### 대상 Evidence 보존

| 상황 | 보존·검증 조건 |
| --- | --- |
| 선택된 GitHub Issue UPDATE/CLOSE/REOPEN | immutable repository, finalized selected identity, 검증된 인자의 issue number와 exact match하는 이미 확보된 target Evidence reference를 같은 argument composition에서 보존한다. |
| LLM이 사용자 요청 reference만 반환 | 대상 identity provenance를 소실시키지 않는다. |
| 다른 Issue·없는 Evidence | 붙이거나 만들지 않는다. 사업 값과 선택 대상의 충돌을 보정하지 않으며 후속 Domain target binding·Approval 권위를 유지한다. |
| ACTION Review | Planning과 같은 current-Run Action Evidence projection, 즉 확보된 Retrieval Evidence와 persisted USER Message origin을 제공한다. |
| 사용자 요청 Evidence | Review에서 누락하거나 외부 Resource로 위조하지 않는다. 기존 project_current_action_evidence를 사용하고 별도 producer를 만들지 않는다. |

#### 결정적 작성과 검증

- 제목만 지정된 정확한 Task CREATE와 제목·날짜·시작·종료·Timezone이 모두 지정된 정확한 Calendar CREATE는 frozen Output Route와 검증된 Request Intent가 각각 하나로 일치할 때 동일 candidate schema를 결정적으로 materialize할 수 있다. 필드가 부족하거나 복수 제약·추가 의미 판단이 남아 있으면 기존 LLM Node를 유지하며, 결정적 결과도 기존 assemble/validate 경계를 우회하지 않는다.
- current registered Tool catalog 전체를 Planning Node에 다시 노출해 Tool을 재선택하게 하지 않는다. Tool 수는 Registry closed set에서 파생되며 Planning 문서가 별도 numeric authority를 갖지 않는다.
- Tool Candidate shortlisting을 Planning에서 수행하지 않는다. Tool 선택 책임은 Tool Route가 이미 소유한다.
#### Dependency와 최종 조립

Action의 Business Arguments 작성과 Dependency 구성을 구분한다. 다중 Action의 dependency 생성·정규화·cycle 검증은 frozen OutputPlanV1의 route 관계와 검증된 Action 후보를 받는 결정적 Planning Application 책임이다.

| 대상 | 현재 P0 resolver 처리 |
| --- | --- |
| Business Arguments에 같은 안정적 외부 Resource identity가 고정된 Action | frozen route 순서에서 후속 Action을 직전 동일 Resource Action에 연결 |
| CREATE처럼 Provider-generated ID를 실행 전에 모르는 Action | dependency를 추정하지 않음 |
| 서로 다른 Resource Action | 병렬 유지 |

`planning.compose_dependencies` PromptRef/LLM Node는 두지 않는다. 기존 결정적 `planning.build_dependencies`가 소유하며 Prompt Slot을 추가하지 않는다. 최종 ActionPlanDraftV2 조립도 결정적 Application이 수행한다.

### 5.7 Review Subgraph

| 책임 | 검사 범위 |
| --- | --- |
| inspect_goal_and_evidence | 목표 부합, 근거 충분성, unsupported claim·모순 |
| inspect_action_scope_and_route | ACTION의 실행 필요성, frozen Route 일치, scope expansion |
| inspect_constraints_and_policy_summary | 사용자 제약과 supplied policy summary. 새 정책을 만들지 않음 |
| aggregate_review_findings / validate_review | 결정적 precedence로 findings를 합성하고 최종 disposition 검증 |
| recheck_affected_dimensions | REVISE가 지정한 dimension만 재검사한 뒤 aggregate/validate 재통과 |

세 inspector의 intermediate output은 free-form object가 아니라 다음 typed contract로 닫는다.

```python
class ReviewInspectorFindingV1:
    dimension: ReviewDimensionIdV1
    code: str
    finding_kind: Literal["ISSUE", "EVIDENCE_GAP", "ROUTE_ISSUE", "CONFIRMATION", "BLOCKER"]
    description: str
    evidence_refs: list[str]
    affected_action_ids: list[str]
    affected_route_ids: list[str]
    required_information: list[str]

class ReviewInspectorResultV1:
    schema_version: Literal[1]
    dimension: ReviewDimensionIdV1
    findings: list[ReviewInspectorFindingV1]
```

- 각 inspector는 자기 `ReviewDimensionIdV1` 하나만 반환할 수 있고 unknown/free-text dimension은 deterministic validation에서 fail closed한다.
- `affected_action_ids` / `affected_route_ids`는 비어 있을 수 있으며 dimension-only finding을 유효하게 보존한다.
- `finding_kind`는 finding 분류이지 최종 routing disposition이 아니다. 최종 `PASS | REVISE | RETRIEVE_MORE | ROUTE_RECONSIDERATION | CONFIRM | BLOCK`은 `aggregate_review_findings`의 deterministic precedence가 결정한다.

#### 검사 적용·RECHECK

검사 책임을 한 Prompt에 합치지 않는다.

| 상황 | 적용 기준 |
| --- | --- |
| 정확한 Task/Calendar CREATE | 검증된 Intent·frozen Route와 Plan이 일치하고 필수 중복/충돌 분석이 끝났으며 ambiguity·risk·relation·override가 모두 비어 있을 때, inspector 결과를 빈 Finding으로 결정적으로 만들 수 있다. |
| 조건 미충족·Confirmation/Policy 판단 남음 | 해당 inspector LLM을 유지한다. 위 최적화로 Domain Validation·Approval·Verification을 생략하지 않는다. |
| aggregate_review_findings | 세 결과를 deterministic severity/disposition precedence로 합성한다. LLM이 최종 routing authority를 갖지 않는다. |
| recheck_affected_dimensions | REVISE가 표시한 affected_dimensions만 재검사한다. action/route IDs가 있으면 해당 dimension의 bounded context로만 사용한다. |
| dimension-only RECHECK | action/route ID가 없어도 가능해야 한다. 원문의 `null` 표기와 타입의 빈 list 허용은 임의로 치환하지 않는다. Finding 문자열·전체 Plan은 selector가 아니다. |
| RECHECK 후 반환 | aggregate_review_findings → validate_review를 다시 통과한 뒤 최종 disposition을 반환한다. |
| Function/Tool Calling | Adapter는 name + arguments의 일반 계약만 알고 Domain Result 매핑은 Application이 수행한다. |
| Route 오류 발견 | tool_route_plan을 직접 변경하지 않는다. |

최종 PASS·REVISE·RETRIEVE_MORE·ROUTE_RECONSIDERATION·CONFIRM·BLOCK은 닫힌 Schema와 결정적 aggregation으로 제한한다.

## 6. Workflow Phase

`WorkflowPhaseV2`의 값은 §2.1의 선언 한곳에서 정의한다. Phase는 Main routing/checkpoint 위치이며, Query 계획·Read·RAG·Sufficiency는 Retrieval 내부 Node State다.

Domain Run Status는 State Contract를 따른다. Graph에 제어 Node가 추가되거나 화면에 상태가 표시된다는 이유로 Phase·Domain 상태 값을 새로 만들지 않는다.

## 7. Node Result·Edge 계약

role별 Result의 소비 경로는 §1.3, 공통 disposition 타입은 §4.2를 따른다. Node는 자기 Role의 허용 subset만 반환하며 다른 Role의 disposition을 임의 사용하지 않는다.

| Domain Validation 경로 | 결과 경계 |
| --- | --- |
| Release Action Plan | REQUIRE_APPROVAL 또는 BLOCK |
| Legacy/compatibility READ Action | ALLOW_READ는 이 경계에서만 유지 |

사용자 Context Adjustment는 §1.1-C의 등록된 target으로 전달하고, 새로운 Route가 필요하면 기존 Route Reconsideration을 사용한다.

## 8. Tasks 시간 의미

- Request Understanding은 `~까지`를 실제 업무 `business_deadline` 후보로, `~에 하다`를 Task `scheduled_date` 후보로 구분해 의미 힌트로 구조화한다.
- Work Analysis가 Evidence와 사용자 요청을 결합해 실제 `business_deadline`·`scheduled_date` 의미를 확정한다.
- 두 값을 자동 동일시하지 않는다.
- 업무 마감만 확인되면 Task 예정일이나 Google `due`를 생성하지 않는다.
- 정확한 시간 구간이 필요한 요청은 Tasks API가 시간을 설정했다고 성공 선언하지 않는다. 필요한 경우 사용자 확인을 거쳐 Tool Route 재검토로 Calendar Event 대안을 별도 Action으로 제안할 수 있다.
- 예정일 경과는 완료 근거가 아니다. 완료 여부는 실제 Provider status에서만 판단한다.

## 9. Answer-only / READ / WRITE

| 요청·결과 | Workflow 구분 |
| --- | --- |
| Answer-only | output_mode=ANSWER이고 외부 IN Route가 없으면 Retrieval을 생략할 수 있다. Analysis 적용은 §18을 따른다. |
| Read-backed Answer | IN Route에서 Retrieval/RAG로 근거를 확보하고 필요한 경우에만 Analysis를 적용해 답변한다. 일반 Retrieval은 Action Row를 만들지 않는다. |
| WRITE | 고정된 OUT Route의 실행안을 검토·승인한 뒤 §12의 Claim·Begin·실행·검증 경계를 따른다. Retrieval/Analysis를 모든 WRITE에 강제하지 않는다. |

`ALLOW_READ`는 원문이 정의한 명시적 READ Action/Domain 호환 경계의 값이며, 새 표준 Retrieval-backed Answer의 경로가 아니다. 승인 이후 Tool·Effect·Arguments·Target을 LLM이 변경하지 않는다.

## 10. Retry·Recovery·Interrupt

### 10.1 Retry Kind

| 종류 | 처리 범위 |
| --- | --- |
| SCHEMA_REPAIR | 현재 Node의 Output Shape만 교정 |
| SEMANTIC_REVISION | 같은 Subgraph의 의미 책임 안에서 수정 |
| WORKFLOW_REDIRECTION | 다른 전문 책임이 필요한 경우 Parent로 전달 |
| DETERMINISTIC_RETRY | 401·429·5xx·Timeout 등은 일반 코드가 Retry·Reauth 처리 |
| DETERMINISTIC_RECOVERY | UNKNOWN_RESULT·Verification MISMATCH는 LLM 재계획이 아니라 기존 Recovery 처리 |

같은 `recovery_fingerprint + external-state fingerprint + verification input`의 RECHECK를 자동 반복하지 않는다. 새 정보가 없으면 새 Verification round를 만들지 않고 suspend 또는 등록된 다른 resolution을 기다린다. external state나 recovery fingerprint가 달라져야 새 RECHECK round로 인정한다.

### 10.2 Interrupt

중단 대상은 WAITING_CONFIRMATION, WAITING_APPROVAL, REAUTH_REQUIRED, RECOVERY_REQUIRED다. 중단 전에 Main Checkpoint를 저장하고 같은 Thread에서 재개한다.

#### Confirmation 순서

```text
검증된 NEEDS_CONFIRMATION / CONFIRM
→ RequestConfirmation 적용
→ pre_confirmation_status와 registered resume binding 보존
→ semantic_owner_id + AgentNodeResumeTargetV2 + interrupt_id checkpoint 저장
→ LangGraph interrupt
→ 사용자 응답 검증
→ ResumeConfirmation 적용
→ 발생 전 안전 Domain 상태와 같은 owner checkpoint에서 재개
```

| 상황 | 조건 |
| --- | --- |
| pre-publish owner | State Contract의 ANALYZING / RETRIEVING / PLANNING source 사용 |
| published Plan Review CONFIRM | guarded WAITING_APPROVAL / VERIFYING source만 사용 |
| 사용자 응답이 upstream 의미 변경 | 필요한 State Owner로 명시적 Back-edge |
| upstream 의미 변경 없음 | Request Understanding 공통 재시작 없이 같은 owner에서 계속 |

WAITING_CONFIRMATION은 공통 Router가 아니라 interrupt 경계다. Receipt·options·target 검증은 §2.1의 control 계약을 사용한다.

## 11. Budget

```
SCHEMA_REPAIR_PER_NODE_CALL=1
SEMANTIC_REVISION_SAME_FAILURE=1
MAX_ADDITIONAL_RETRIEVAL_ROUNDS=2
PLANNING_REVISION_PER_RUN=2
REVIEW_RECHECK_PER_PLANNING_REVISION=1
NORMAL_MAX_LLM_CALLS=14
RETRIEVAL_HEAVY_MAX_LLM_CALLS=20
REVISION_HEAVY_MAX_LLM_CALLS=18
ABSOLUTE_MAX_LLM_CALLS=100
```

- 책임 분리를 위해 Subgraph 내부 Node 수가 증가해도 모든 Node가 LLM Call일 필요는 없다.
- Query Builder, Registry Binding, Read 실행, Segment Normalize, Plan Assembly, Validator는 결정적 코드 우선이다.
- LLM Call 수가 Agent 수 또는 Node 수와 같다고 가정하지 않는다.

#### Run 예산 집행

| 항목 | 규칙 |
| --- | --- |
| 기준 | Run 시작 시 `10 Settings`의 validated budget snapshot을 고정한다. |
| compatibility | absolute 상한은 100이다. 과거 저장값 24/36은 현재 계약을 읽을 때 100으로 정규화하며 사용량 counter는 reset하지 않는다. |
| Profile 관측값 | `NORMAL=14`, `REVISION_HEAVY=18`, `RETRIEVAL_HEAVY=20`은 실행 특성 관측용이며 LLM dispatch를 차단하지 않는다. |
| counter | 음수가 아니며 단조 증가한다. Profile 승격으로 사용량을 초기화하지 않는다. |
| 집행 범위 | LLM·Repair·Revision·Retrieval 외에도 per-Run Connector call, Context token, Retry, 최대 실행 시간을 검사한다. elapsed time은 ClockPort로 확인한다. |
| Retrieval 상한 | `05`의 Release Default `MAX_TOTAL_SOURCE_PAGES=50`, `MAX_TOTAL_DETAIL_RESOURCES=12`와 source-local detail 제한을 넘지 않는다. Settings는 더 작은 값을 선택할 수 있다. |
| 초과 직전 | 다음 outbound/LLM operation을 막고 bounded failure/recovery result를 반환한다. |

위 수치는 현재 실행 상한이다. 실험 case 수나 최적 성능의 목표값을 뜻하지 않으며, 반복 전략 자체를 고정하지 않는다.

## 12. 실행·검증 경계

### READ

```
InputRoutePlanV1
→ Retrieval subgraph
→ ConnectorReadPort
→ RetrievalResultV1
```

일반 Connector READ는 Retrieval이 소유하며 Action·Approval·ExecutionAttempt·Verification Row를 만들지 않는다.

> **확인 필요:** 원문 이 절은 “별도 READ Action lifecycle과 호환 실행 체인은 존재하지 않는다”고 적고 있지만, §1·§2·§7·§9는 Legacy READ 경로를 정의한다. 이 불일치를 문서 정리만으로 해소하거나 lifecycle·resume target을 삭제하지 않는다.

### WRITE

```
PROPOSED | MODIFIED
→ approve_action
→ APPROVED
→ claim_execution
→ Action EXECUTING + Attempt CLAIMED
→ build_claim_context
→ begin_execution_attempt
→ Attempt EXECUTING
→ MCP Write
→ EXECUTED | FAILED | UNKNOWN_RESULT
→ Google re-read Verification
→ VERIFIED | MISMATCH
```

`ClaimExecution` Commit 전 Write는 물론, Claim Commit만으로도 Write할 수 없다. `BeginExecutionAttempt`가 `applied=true`로 Commit되어 Attempt=`EXECUTING`인 뒤에만 외부 Write를 시작한다. 승인 이후 인자를 LLM이 재생성하지 않는다.

### FAILED

```text
FAILED → prepare_write_retry → MODIFIED → 새 승인 → 새 Attempt
```

새 승인 전 Review·Domain Validation과 독립 Action의 계속 실행 조건은 §1.2를 따른다.

### UNKNOWN_RESULT

```
CREATE → RESOURCE_SEARCH (Recovery Fingerprint 기반 Resource Search)
UPDATE → GET_TARGET
SEND   → MESSAGE_SEARCH → 기존 전송 결과 후보 식별 → SENT_LOOKUP 검증
DELETE → GET_TARGET → 대상 부재/삭제 상태면 GET_ABSENT 검증
ALL    → 새 Attempt·blind repeat 금지
```

## 13. Agent Failure 계약

`15 Agent Capability · Failure · Prompt` current contract를 따른다.

```python
class AgentFailureRecord:
    failure_reason_code: str
    failure_origin: str
    detected_by: str
    runtime_disposition: Literal[
        "RETRYABLE", "REDIRECT", "DETERMINISTIC", "TERMINAL", "NOT_AVAILABLE"
    ]
    experiment_disposition: str
    affected_field_paths: list[str]
```

Tool 관련 실패 Owner:

- `TOOL_ROUTE_WRONG_INPUT`
- `TOOL_ROUTE_WRONG_OUTPUT`
- `TOOL_ROUTE_UNREGISTERED_TOOL`
- `TOOL_ROUTE_EFFECT_MISMATCH`

Planning에서 발견된 Tool 불일치는 `TOOL_ROUTE_EFFECT_MISMATCH` 또는 대응 Route failure로 정규화하고 Tool Route 재검토로 redirect한다.

### 13.1 Runtime Node와 Application operation의 구분

| 구분 | 의미 |
| --- | --- |
| Runtime Node ID | checkpoint·resume 가능한 물리 실행 단위 |
| Application operation ID | Owner 내부의 의미 책임 |
| 이름 관계 | 서로 다른 namespace다. 문자열 equality를 강제하지 않는다. |
| 결정적 Node | 여러 검증 operation을 순서대로 호출할 수 있다. |
| supporting operation | 별도 파일이라는 이유로 Node·checkpoint·resume target이 되지 않는다. |

구체 파일 inventory는 이 문서나 16에 복제하지 않는다. 실제 registry·composition·production caller·architecture test로 확인한다.

## 14. Node Registry

Runtime Node ID는 이 문서가 소유하고, repository owner·naming·placement는 `16`을 따른다. Node Registry는 runtime 책임을 나타내며 PromptRef 개수나 repository operation label과 같지 않다.

| 현재 namespace 예 | 구분 |
| --- | --- |
| request.* / analysis.* | checkpoint/resume topology의 Runtime identity |
| request_understanding.* / work_analysis.* | repository ownership/naming identity |

### 14.0 Work Analysis · Planning · Review

아래는 현재 문서가 정의한 runtime ID와 책임의 대응이다. Request Understanding / Tool Route / Retrieval은 §14.1에 둔다. ID·binding은 보존하되, 표를 미래의 고정 Node 수나 실험 후보 목록으로 사용하지 않는다. 등록되지 않은 broad/legacy ID를 Node·Prompt·resume 권위로 사용하지 않는다.

| node_id | subgraph | type | 단일 책임 |
| --- | --- | --- | --- |
| `analysis.extract_facts` | work_analysis | LLM | Evidence-grounded work facts |
| `analysis.resolve_entity_relations` | work_analysis | LLM/conditional | entity/resource relation candidates only |
| `analysis.resolve_temporal_dependencies` | work_analysis | LLM/conditional | temporal/dependency candidates only |
| `analysis.detect_duplicate_conflict_candidates` | work_analysis | LLM/conditional | fact↔fact duplicate/conflict candidate와 requested Task satisfaction을 서로 다른 atomic Prompt로 평가해 기존 typed assessment로 조립 |
| `analysis.validate_relations` | work_analysis | deterministic | duplicate/conflict/current-state relation validation |
| `analysis.assess_action_necessity` | work_analysis | LLM/conditional | frozen output route별 현재 적용 여부. Task CREATE는 중복 검토에서 결정적으로 파생 |
| `analysis.assess_information_gaps` | work_analysis | LLM | missing information / retrieval needs only |
| `analysis.assess_operational_risks` | work_analysis | LLM/conditional | operational risk only |
| `analysis.finalize` | work_analysis | deterministic | `assemble_work_analysis` → `validate_work_analysis` → `WorkAnalysisResultV2`; 두 deterministic operation은 이 runtime node 안에서 연속 실행 |
| `planning.outline_answer` | planning | deterministic/LLM-conditional | Work Analysis·확인 필요가 없으면 현재 Run 원문 + 허용 Evidence ref의 request-scope outline. 그 외에는 answer evidence/conclusion outline LLM |
| `planning.compose_answer` | planning | LLM | answer prose from approved outline/evidence |
| `planning.draft_action_objective_per_output_route` | planning | LLM/per-route | business mutation objective/target/scope only |
| `planning.compose_arguments_per_output_route` | planning | LLM/tool-schema/per-route | serialize one frozen route objective into Tool Arguments |
| `planning.derive_dependencies` | planning | deterministic | validated dependency DAG |
| `planning.assemble` | planning | deterministic | `assemble_plan` → `validate_plan` → `ActionPlanDraftV2`; validation은 이 runtime node 안에서 실행 |
| `review.inspect_goal_and_evidence` | review | LLM | goal coverage + evidence grounding |
| `review.inspect_action_scope_route` | review | LLM/ACTION | action necessity/overreach/contradiction/route consistency |
| `review.inspect_constraints_policy` | review | LLM/conditional | user constraints + supplied policy summary consistency only |
| `review.aggregate_findings` | review | deterministic | `aggregate_review_findings` → `validate_review` → stable issue codes + final disposition; validation은 이 runtime node 안에서 실행 |
| `review.recheck` | review | LLM/conditional | affected dimensions only |


Runtime-node closure rule:

- `validate_work_analysis`, `validate_plan`, `validate_review`는 각각 독립 Product LLM responsibility가 아니며 **별도 LangGraph Runtime Node ID를 만들지 않는다**. 현재 runtime topology에서는 `analysis.finalize`, `planning.assemble`, `review.aggregate_findings` node 내부의 deterministic Application operation으로 실행한다.
- 따라서 validator operation이 독립 파일에 존재할 수 있지만, 06의 Resume Target Registry/Node Registry에는 위 세 validator를 별도 node/resume target으로 등록하지 않는다.
- `review.recheck` 결과는 반드시 `review.aggregate_findings`로 돌아가 그 node 내부 `aggregate_review_findings → validate_review`를 재통과한 뒤에만 disposition을 반환한다.

registered node/resume target set이 변경되면 compiled Resume Target Registry의 `graph_version`을 반드시 증가시키고, 현재 registry와 일치하지 않는 checkpoint는 추측 resume하지 않는다.

`NodeRegistry`와 `ResumeTargetRegistry`는 runtime lookup의 단일 production authority다. 06은 runtime node/resume semantics만 소유하며 Registry path/file/symbol이나 duplicate code inventory를 정의하지 않는다.

### 14.1 Request Understanding · Tool Route · Retrieval

| node_id | subgraph | type | 주요 입력 | 주요 출력 |
| --- | --- | --- | --- | --- |
| `request.identify_goal` | request_understanding | LLM | request | goal 후보 → resource 책임 → source status를 순서대로 조립한 goal candidate |
| `request.identify_temporal_scope` | request_understanding | LLM/conditional | request + goal period/context | temporal axis를 더한 goal candidate |
| `request.detect_ambiguity` | request_understanding | LLM/conditional | request + goal | ambiguity |
| `request.finalize` | request_understanding | deterministic | local candidates | `finalize_intent → validate_intent → RequestIntentV2` |
| `route.determine_resources` | tool_route | LLM | `RequestIntentV2` | IN/OUT resource·effect candidate |
| `route.bind_candidates` | tool_route | deterministic | resource/effect candidate + Registry | registry candidates |
| `route.select_tool` | tool_route | LLM/conditional | route candidate + registered candidates | selected candidate |
| `route.finalize` | tool_route | deterministic | selected candidate + Registry | `ToolRoutePlanV2` |
| `route.validate` | tool_route | deterministic | final route | validated route |
| `retrieval.plan_query` | retrieval | LLM/conditional | intent + input routes; exact selected detail은 deterministic materialization | `RetrievalQueryPlanV2` |
| `retrieval.build_query` | retrieval | deterministic | query plan + route | validated query |
| `retrieval.execute_read` | retrieval | deterministic | query + allowed read tools | read handles |
| `retrieval.normalize_segments` | retrieval | deterministic | read handles | segment handles |
| `retrieval.rag_retrieve` | retrieval | deterministic/optional model | intent + segments | ranked candidates |
| `retrieval.select_evidence` | retrieval | LLM | intent + ranked candidates | `EvidenceSelectionResultV2` |
| `retrieval.assess_sufficiency` | retrieval | LLM | intent + evidence | `SufficiencyResultV2` |
| `retrieval.finalize` | retrieval | deterministic | local results | `RetrievalResultV1` |

## 15. Workflow 구성 경계

Workflow의 구현 순서나 세부 Node 분해를 고정된 작업 계획으로 두지 않는다. 구성 시에는 정의된 Schema·Application operation을 사용하고, Graph adapter는 아직 없는 Domain·Port·Application 책임을 임시 구현하거나 generic service로 흡수하지 않는다.

네이밍·배치·의존성 규칙은 `16`을 유지한다. supporting operation 파일을 추가했다는 이유로 별도 Node·checkpoint·resume target을 만들지 않는다는 §13.1의 구분도 유지한다.

## 16. Prompt Registry

PromptRef·선택 Key·입력 계약의 상세는 `15 Agent Capability·Failure·Prompt`를 따른다. Workflow에서는 호출 지점과 책임의 연결만 사용한다.

| 항목 | Workflow 규칙 |
| --- | --- |
| Prompt 선택 | Supervisor는 원문을 읽거나 선택하지 않는다. 선택된 LLM Node가 Registry에서 PromptRef를 확정한다. |
| 입력 | 해당 Node의 Projection 밖 State를 가정하지 않는다. |
| 책임 | 다른 Subgraph 책임을 다시 수행하거나 Tool Route 이후 Retrieval·Planning에서 Tool을 재선택하지 않는다. |
| Repair / Revision | 별도 Purpose를 사용하며 현재 bounded Repair 계약을 따른다. |
| 저장 | Prompt·Completion 원문을 Main State·일반 Trace·Audit에 저장하지 않는다. |
| 결정적 경계 | 실행·검증·승인·정책 판정에 LLM Prompt를 사용하지 않는다. |
| 활성화 | 신규·변경 Prompt는 필요한 Node DEV/HOLDOUT·Safety Gate 전 RUNTIME_ACTIVE로 승격하지 않는다. 평가 절차 자체는 여기서 중복 정의하지 않는다. |

## 17. Attachment Agent 경계

- 첨부파일 기능을 별도 Agent Capability로 만들지 않는다.
- Agent는 파일명·MIME Type·크기·Attachment/Stage Descriptor 같은 Metadata만 사용할 수 있다.
- 첨부파일 bytes는 Main State, Agent Local State, ContextBundle, Evidence, Prompt 입력에 포함하지 않는다.
- 실제 Download·Staging·MIME 조립은 결정적 Application·MCP 경계가 수행한다.
- ClaimContextV2 생성·검증은 Agent Node가 아니라 결정적 Application execution responsibility다.

## 18. Effective Analysis와 Planning Binding

`analysis_requirement`은 요청 자체의 업무 관계·파생 의미·위험 해석 필요성이다. ACTION이라는 이유만으로 REQUIRED가 되지 않는다.

```text
request_analysis_required
OR deterministic_policy_precondition_requires_analysis
= effective_analysis_required
```

| 상황 | 적용 기준 |
| --- | --- |
| 단순 조회·충분한 직접 Action | analysis_requirement=NONE일 수 있다. |
| TASK CREATE / CALENDAR CREATE | PolicyPreconditionResolver가 중복·충돌 검사를 위한 effective analysis를 추가한다. Request Understanding이 정책 검사를 대신 결정하지 않는다. |
| analysis_requirement=NONE인 Calendar CREATE | conflict evidence가 필요하면 Retrieval과 Work Analysis를 거친다. |
| 직접 SEND / Task UPDATE | 별도 relation·risk 해석이나 Policy Precondition이 없으면 Analysis를 생략할 수 있다. |
| 외부 자료가 필요 없는 직접 Gmail Draft CREATE/SEND | Retrieval을 생략하고 current-Run USER_MESSAGE Evidence로 Planning·Review·Approval을 진행할 수 있다. 존재하지 않는 Acquisition 결과를 요구하거나 가짜 외부 Evidence를 만들지 않는다. |
| 기존 Draft UPDATE/SEND / Reply | 원본 identity에 필요한 Retrieval·target binding을 유지한다. |

SIX reference route도 같은 effective analysis Guard를 사용하며 output_mode=ACTION만으로 Analysis를 강제하지 않는다.

Planning Argument Writer 전에 `07 DefaultContainerResolver`가 required system/container 필드를 결정적으로 bind한다. LLM은 tasklist_id·calendar_id를 추측·재선택하지 않으며, 해석 불가 시 Argument Writer를 호출하지 않는다.

## 19. Runtime reconstruction · pre-dispatch reconciliation

### 19.1 Per-Run LLM mode reconstruction

| 항목 | binding 기준 |
| --- | --- |
| RunInputV1.requested_mode / WorkflowBindingV1.requested_mode | persisted Run.requested_mode의 projection |
| START/RESUME RunExecutionRefV1 | 같은 requested_mode 전달 |
| StructuredInferencePort.infer caller | per-Run 값을 사용 |
| 덮어쓰기 금지 | Settings preferred_llm_mode 또는 process runtime mode로 same-Run 값을 교체하지 않음 |

### 19.2 Post-Claim pre-dispatch reconciliation

| 현재 사실 | 처리 |
| --- | --- |
| Attempt=CLAIMED + APPLIED Begin 없음 + cancel/restart/invalid ClaimContext/credential failure로 Begin 불가 | 외부 Write 없이 `AbortClaimedExecution`으로 settle한다. hidden CLAIMED→FAILED/CANCELLED mutation을 만들지 않는다. |
| Attempt=EXECUTING + APPLIED Begin + terminal dispatch result 없이 process restart | pre-Begin Abort로 되감지 않는다. startup-only `execution_attempt.reconcile_inflight_executions`가 MAY_HAVE_BEEN_SENT → MarkUnknownResult로 고정한다. |
| UNKNOWN_RESULT 이후 | coordinator는 durable Action·Attempt·Recovery·Verification facts를 phase marker로 사용해 lookup과 recovered EXECUTED의 Verification 진입을 이어간다. Connector Write replay는 0이다. |
| 현재 process의 live EXECUTING | live reconciliation loop가 startup orphan 경로로 분류하지 않는다. |
| cancel 결과 | FinalizeCancel owner로 닫는다. |
| non-cancel FAILED | 독립 executable Action continuation 또는 §1.2의 FAILWAIT 기준을 따른다. |

#### Startup continuation

| 조건 | 처리 |
| --- | --- |
| batch가 limit보다 작음 | 그 이유만으로 drain을 끝내지 않는다. 기존 bounded pass에서 durable progress가 멈출 때까지 UNKNOWN_RESULT → lookup → Verification handoff를 진행한다. |
| handoff가 이미 stage됨 | 새 startup candidate batch를 점유하지 않고 기존 handoff owner가 처리한다. |
| Domain에서 EXECUTED로 복구됨 | Verification handoff가 crash checkpoint의 미완료 ACTION_EXECUTION task를 대체한다. 두 Node를 같은 superstep에서 실행하지 않는다. |

#### 취소 후 최종 응답

Verification으로 Run이 VERIFYING이 돼도 cancellation receipt는 유지한다. RESPONSE_SYNTHESIS는 Supervisor의 cancel_intent_active를 받아 FINALIZE_CANCEL intent로 연결한다. 확인된 외부 효과가 있으면 PARTIAL, 없으면 CANCELLED로 표현하되 최종 판단·저장은 FinalizeCancel owner가 검증한다.

## 19-A. Product LLM inference tier binding

각 Product LLM runtime caller는 PromptRef와 함께 closed `InferenceTierV1 = WORKER | REASONING`을 결정적으로 전달한다. Tier는 모델 이름이 아니라 호출 복잡도·책임 등급이며 Graph Edge, Agent owner, Prompt semantics를 바꾸지 않는다.

- `WORKER`: 13 Gate에서 bounded extraction/classification이 검증된 Prompt slot만 허용한다.
- `REASONING`: ambiguity 판정, Tool Route semantic selection, Retrieval planning/sufficiency, Work Analysis, Planning, Review를 기본으로 한다.
- 동일 Prompt slot의 tier는 signed Prompt/Model release binding에서 고정하며 LLM 출력, free text, Runtime confidence가 바꿀 수 없다.
- Resume/Repair/Revision은 원 호출의 tier와 Run model binding을 유지한다. tier fallback이나 model substitution을 만들지 않는다.
- Agent State와 Checkpoint에는 concrete model name을 실행 권위로 저장하지 않고 PromptRef/tier/release-profile identity와 관측 결과만 보존한다.

지원 모델은 `qwen3.5:9b`, `qwen3.5:4b`이며 새 Run 시작 시 하나를 binding한다. WORKER/REASONING class는 Prompt 책임 metadata일 뿐 역할별 모델 switching 신호가 아니다. 진행 중 Run에서는 재검사나 inference 오류로 concrete model을 바꾸지 않는다.

## 19-B. State-derived conditional execution

| 판단 단위 | 적용 기준 |
| --- | --- |
| 전체 stage/Subgraph | Main Supervisor가 RunInputV1과 current typed artifact에서 조건을 도출한다. LLM 출력이나 별도 장기 skip_* boolean은 routing authority가 아니다. |
| 내부 Node | Subgraph가 자기 Local State·current artifact로 applicability를 판단한다. 새로 만들 정보가 없으면 실행하지 않는다. |
| 결정적 산출 가능 | LLM 호출만 생략하고 같은 Owner의 builder/validator가 canonical artifact를 만든다. Artifact 계약 자체는 생략하지 않는다. |
| 생략 금지 | Validation·Policy·Approval·Domain transition·Write safety·Verification·Recovery·unknown-contract fail-closed는 비용을 이유로 건너뛰지 않는다. |
| RESOURCE_SELECTED의 exact identity | query-planning LLM을 생략할 수 있어도 canonical detail read·Evidence/RAG·Sufficiency는 유지한다. |
| 선택 단일 Resource와 Intent의 단일 output type이 같고 UPDATE/DELETE effect 하나가 확정됨 | 기존 Tool Routing builder가 IN/OUT candidate를 결정적으로 만든다. 다른 Resource 변환·복수 effect·미해결 ambiguity에는 적용하지 않는다. |

같은 effect 안의 concrete Tool 선택, Registry validation, Policy와 Approval은 생략하지 않는다.
