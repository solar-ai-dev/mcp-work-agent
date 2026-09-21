# 15. Agent Capability · Failure · Prompt 공통 계약

> **Authority:** Agent capability·normalized failure·Prompt runtime contract. 승인/Claim/Write/Verification/Domain lifecycle의 최종 판정은 해당 owner를 따른다.  
> **상태:** Approved v1.35 · **기준일:** 2026-09-07 · **대상:** P0 Product Agent/Prompt Runtime

## 0. 문서 목적

이 문서는 다음 항목을 정의한다.

| 항목 | 범위 |
| --- | --- |
| Agent·Node Capability | 각 책임의 입력 조건과 Typed Result 범위 |
| Failure | 공통 `failure_reason_code`와 실패 분류 |
| Retry·Recovery | 실패 유형별 Repair·Revision·Redirection·Recovery 처리 |
| Prompt Runtime | Prompt Registry·PromptRef·Input Contract와 bounded assembly |
| Query Attempt | Product Prompt가 소비하는 runtime-safe failure/projection 계약 |

`05 Context·Retrieval`과 `06 Agent·Workflow`의 제품 의미를 Prompt·Failure 관점으로 정규화한다. `12 Test`와 `13 Evaluation`은 이 문서의 계약을 검증·평가용으로 소비하며, Dataset·Grader·candidate selection 의미를 역수입하지 않는다.

### 0.1 Product Prompt input boundary

Product Prompt는 **사용자 요청, 허용된 Context, Policy Summary, Failure Record 같은 선언된 Runtime 입력만** 본다.

| 구분 | 입력 경계 |
| --- | --- |
| 평가 정보 | `gold`, `grader`, `expected_route`, benchmark score는 Product Prompt 입력이 아니다. |
| 평가용 분해 | Evaluation diagnostic decomposition에서도 Product Prompt 입력과 Gold/Grader metadata를 파일·schema 수준에서 분리한다. |
| 평가에서 발견한 오류 | Runtime과 동일한 `failure_record` 형태로 투영한 뒤 전달한다. Grader 정보 자체를 입력으로 사용하지 않는다. |

**Ollama structured transport:** 선언된 동일 OutputSchema를 `format`과 모델이 읽는 요청 본문에 함께 전달한다. grammar enforcement만으로 필드 의미가 전달됐다고 간주하지 않는다. 이 provider protocol projection은 새 업무 입력·Prompt authority가 아니며, 허용 enum/필드 의미와 기존 응답 validator를 서로 다르게 만들지 않는다.

### 0.2 Inference tier input boundary

- Product Prompt에는 concrete provider/model 선택 지시나 installed model 목록을 넣지 않는다.
- Runtime caller가 PromptRef와 별도로 closed `InferenceTierV1 = WORKER | REASONING`을 선택한다. Tier는 Prompt semantic input이 아니라 signed runtime binding metadata다.
- Prompt source·failure instruction·LLM output은 tier/model을 변경하거나 더 큰 모델 재호출을 요구할 수 없다.
- `WORKER`는 13에서 해당 Prompt slot의 bounded extraction/classification 안정성이 검증된 경우에만 허용한다. ambiguity, Tool Routing, Retrieval planning/sufficiency, Analysis, Planning, Review는 기본 `REASONING` 후보다.
- Schema Repair/Semantic Revision/Confirmation resume은 원 invocation tier를 유지한다. allowed fallback/substitution은 Router/Release policy가 결과 Metadata로만 투영한다.
- 반복 Confirmation 결함은 `request.detect_ambiguity`의 Projection→candidate→validator→disposition을 각 지원 Local 모델에서 재현·회귀하는 required evaluation case다.

### 0.3 Conversation · Run Prompt 입력 경계

Conversation Timeline은 사용자에게 보여 주는 저장 이력이지 Product Prompt의 자동 Memory가 아니다. `conversation_id`도 Trace·상관관계 식별자이며, 과거 Message나 이전 Run State를 Prompt에 직렬화할 권한을 만들지 않는다.

| 상황 | 허용 입력·처리 | 제한 |
| --- | --- | --- |
| 새 Run | `prompt-runtime-input-contract-v1`이 허용한 현재 Run Typed Projection만 직렬화한다. | 같은 Conversation의 과거 USER/ASSISTANT Message 전체, 이전 Run의 RequestIntent·ToolRoute·Retrieval/Evidence·WorkAnalysis·Plan/Review·PromptContext를 숨은 입력으로 붙이지 않는다. |
| Request Understanding 최초 invocation | 현재 `RunInputV1.user_request + selected_resource_refs`만 의미 입력으로 사용한다. | `RESOURCE_SELECTED`에서는 이미 검증된 `selected_resource_refs`를 포함해 retrievable Resource fact를 user-owned missing choice로 오인하지 않는다. |
| 과거 Resource를 이번 Run에 명시적으로 다시 선택 | 해당 Resource Ref만 current-run Entry Context로 허용한다. | 이전 Run의 Evidence 판정이나 Approval은 가져오지 않는다. |
| 새 Run의 확인 정보 | 이전 Run의 확인 정보를 승계하지 않는다. | `confirmation_response`, Policy Confirmation Receipt, interrupt/checkpoint metadata를 가져오지 않는다. |
| 같은 Run의 Confirmation resume | Controller가 검증·정규화한 bounded `ConfirmationResponseProjectionV1`을 `confirmation_response` optional Root Field로 originating owner의 해당 Product Prompt에만 전달한다. | Raw resume payload, `interrupt_id`, checkpoint metadata, `RegisteredResumeTargetRefV2`은 Prompt 입력이 아니다. 다른 Agent 호출로 응답을 자동 승계하지 않는다. |
| 확인 응답이 upstream Intent 의미를 변경 | 현재 owner가 Typed Back-edge를 반환한다. | Prompt가 다른 Agent 책임을 직접 수행하지 않는다. |
| 이전 Run 없이는 해석되지 않는 요청 | `관련 메일 찾아줘`처럼 current-run explicit Resource가 없으면 Request Understanding의 `NEEDS_CONFIRMATION` 경계로 보낸다. | 과거 Conversation History를 모델에 주입해 해결하지 않는다. |

### 0.4 Node별 입력 Projection

각 Node는 Parent/Main State 전체가 아니라 자기 작업에 필요한 Typed Projection만 받는다.

| Node·호출 상황 | 입력 | 제한 |
| --- | --- | --- |
| Retrieval 초기 Round Query Planner | 현재 Run `user_request + request_intent + input_routes + retrieval_budget` | 원문은 typed intent의 의미 손실을 보완하는 입력이며 별도 State·장기 권위·정책 사실로 승격하지 않는다. |
| Retrieval follow-up Round Query Planner | 초기 입력 + `current_round_no + prior QueryAttemptV1 + unresolved SufficiencyIssueV2 + bounded read-result summary + current-Run selected Evidence projection` | Evidence projection은 `evidence_ref + excerpt + role + resource_ref`로 제한하며 raw Provider payload가 아니다. |
| Evidence Selector | `request_intent + ranked_segments` | 같은 Run의 detail 재평가에서는 유지된 selected Evidence의 bounded projection을 관계 문맥으로 추가한다. |
| Work Analysis atomic node | 각 책임에 필요한 최소 Projection | facts/entity-relations/temporal-dependencies/duplicate-conflict-candidates/gaps/risks를 한 번에 요구하지 않는다. |
| Planning `draft_action_objective_per_output_route` | `user_request + OutputToolRouteV1 1개 + optional work_analysis + evidence_refs` | Tool Schema를 직렬화하지 않는다. |
| Review `inspect_goal_and_evidence` | `request_intent + planning_result + evidence + optional work_analysis` | 초기 `EVENT_TIME` 검토에 필요한 Gmail 수신시각과 본문·요청 기준시각은 다른 역할이다. 정규화 envelope가 확인된 경우에만 수신시각을 이 inspector의 Evidence 입력에서 제외하고 current-Run 기준시각을 optional로 제공한다. State 원본·다른 시각축·사용자 수정/확인 입력은 변경하지 않는다. |
| Review `recheck_affected_dimensions` | `affected_dimensions + request_intent + planning_result + optional same-route proposal_transition + 관련 Evidence/Route/WorkAnalysis` | 이전 issue별 해결 판정과 현재 finding을 분리한다. 전후 Action이 frozen route에서 유일하게 연결되지 않으면 relation을 추측하지 않는다. 이전 이력은 현재 요구·실행 결과가 아니다. |
| Planning `compose_arguments_per_output_route` | 같은 frozen Output Route + validated action objective + 해당 Tool Schema | Arguments 표현만 작성한다. 현재 검증된 `request_intent` 제약의 소비는 Planning ACTION 절에 둔다. |

Retrieval Query Planner는 현재 Run의 raw `user_request`를 의미 보존 입력으로 받지만 별도 권위로 복제하지 않는다. Evidence Selector에는 raw `user_request`를 전달하지 않는다. Raw Page Token·Provider-native Query·RFC3339·MCP Arguments는 어느 Round의 Product Prompt에도 전달하지 않는다.

## 1. 기준 문서와 우선순위

### 1.1 유지하는 확정 계약

| 경계 | 규칙 |
| --- | --- |
| Supervisor | 결정적 Router다. |
| LLM Agent | 외부 Provider API·MCP Write를 직접 호출하지 않는다. P0 Google Workspace도 동일하다. |
| Prompt 선택 | Agent별 단일 문자열이 아니라 Node·상태·목적별 `PromptRef`로 선택한다. |
| 원문 저장 | Prompt·Completion 원문은 Graph State·일반 Trace·Audit에 저장하지 않는다. |
| 최종 판정 | 실행·검증·승인·정책 최종 판정에는 LLM Prompt를 사용하지 않는다. |
| 결과 불명 | `UNKNOWN_RESULT`에서는 새 Write Attempt를 만들지 않는다. |

#### Query·READ·WRITE 책임

| 항목 | 책임·조건 |
| --- | --- |
| Raw Query·Page Token·MCP Read Arguments | 결정적 코드가 생성·검증한다. |
| Retrieval pagination | `05 Retrieval`의 Run Retrieval Cache read-result entry만 raw Provider continuation을 memory-only로 보존한다. Product Prompt·Main State·Checkpoint·Domain DB·Trace·Audit에 복제하지 않는다. |
| Release Graph의 READ | 고정된 IN Route를 사용하는 Retrieval만 소유한다. |
| Policy Precondition READ | Tool Route는 의미 Route 후보 뒤에 결정적 Policy Precondition Resolver를 적용한다. `TASK + CREATE`의 기존 미완료 Task 중복 검사와 `CALENDAR + CREATE`의 Event/FreeBusy 충돌 검사에 필요한 IN READ를 보강한다. 두 번째 Tool 선택이 아니며 OUT Tool을 변경하지 않는다. |
| 사용자 범위 밖 필수 READ | 지정된 Source·기간·Resource를 벗어나면 `SCOPE_EXPANSION_REQUIRED` Confirmation 전에는 materialize하거나 실행하지 않는다. 범위 확장을 거절하면 필수 검사를 생략한 Write로 진행하지 않는다. |
| Policy Confirmation Receipt | 실제 사용자 응답을 검증한 Application/Confirmation Controller만 `PolicyConfirmationReceiptV1`을 만들 수 있다. Agent/LLM은 생성할 수 없다. |
| Write/Action Arguments | Planning LLM은 고정된 OUT Tool Schema 안에서 작성하고 결정적 코드가 검증·조립한다. Tool identity는 Output Route에서 결정적 Assembler가 복사하며 Planning LLM이 다시 선택하지 않는다. |

호출·Repair·Revision·추가 Retrieval 상한은 §8에서 정리한다. Profile budget을 맞추기 위해 서로 다른 semantic responsibility를 거대 Prompt로 합치지 않는다.

### 1.2 Concern Authority 적용

문서 번호를 하나의 global priority chain으로 해석하지 않는다. 충돌은 `01 PRD`의 현재 제품 범위와 `00 Project Source Guide`의 **Concern Owner 규칙**으로 해소한다.

| Concern | Owner |
| --- | --- |
| 제품 목표·범위 | 01 PRD |
| 안전·금지·승인 정책 | 01-B Policy |
| 시스템·레이어 경계 | 03 Architecture |
| Domain lifecycle semantics | Domain State Transition Contract |
| Domain persistence/DB | 04 Domain·DB + 04 Domain·DB required DB invariant contract |
| Retrieval | 05 Context·Retrieval |
| Agent·Workflow runtime | 06 Agent·Workflow |
| Tool·MCP·내부 Interface | 07 Interface |
| Prompt·Failure | 본 문서 15 |

`11 Observability`는 관측 계약, `12 Test`는 제품 회귀 검증, `13 Evaluation`은 후보 비교·실험을 소유하며 위 behavioral/runtime 의미를 재정의하지 않는다. 개별 Prompt·Dataset Artifact도 해당 owner 계약을 따라야 한다. 본 계약은 다른 Concern Owner의 안전·승인·Domain·Tool·Workflow 의미를 완화하거나 대체할 수 없다.

### 1.3 Agent Subgraph 공통 계약

본 문서에서 **Agent**는 단순 Prompt 호출이나 Python 객체 수가 아니라, Main Supervisor가 호출하는 LangGraph Subgraph를 뜻한다.

| 구분 | 필수 속성 |
| --- | --- |
| 책임 | 안정적인 `agent_role` 책임 계약 |
| 입력·작업 상태 | Parent State에서 필요한 입력만 받는 Input Projection과 invocation 범위 Subgraph별 Typed Local State |
| 처리 | PromptRef 기반 LLM Node, 역할상 필요한 결정적 Validation·Read Application Node |
| 검증 | Schema Validation과 허용된 bounded Repair/Revision |
| 반환 | Versioned Typed Result + disposition + 필요한 Typed Workflow Signal |
| 금지 | Agent→Agent 직접 호출, 장기 Memory |

Prompt Slot 수, PromptRef 수, LLM Call 수는 Agent 수와 독립적이다. 같은 Agent 안의 `INITIAL`, `CLARIFY`, `SCHEMA_REPAIR`, `SEMANTIC_REVISION`, `RECHECK`는 하나의 책임 계약을 보조하는 Prompt variant다.

#### State 보존·반환

| 대상 | 규칙 |
| --- | --- |
| 공통 Runtime Envelope | invocation metadata와 failure/repair counter만 보존한다. |
| 업무 데이터 | Subgraph별 Typed Local State에 둔다. |
| 다른 Agent 호출 | invocation 종료 후 Local candidate·Query candidate·RAG score·Prompt 원문을 자동 승계하지 않는다. |
| 제품의 장기 사실·승인·실행·검증 | Main Graph Typed State와 Domain Store 계약을 따른다. |
| 공식 Main State Artifact | 단일 Owner만 새 revision을 만들며 downstream은 upstream Artifact를 read-only로 소비한다. |
| Subgraph 반환 | owner field와 허용된 workflow signal만 patch merge한다. 다른 Main State field를 `None` 또는 누락 값으로 초기화하지 않는다. |

Graph Profile 간 semantic responsibility parity를 유지한다. `SINGLE_BASELINE`은 별도 Review Agent가 없어도 Unified Agent 내부 `self_review`로 계획 품질 점검 책임을 수행한다.

### 1.4 Local SLLM Responsibility·Complexity 계약

지원 Local 모델은 `qwen3.5:9b`, `qwen3.5:4b`다. 한 Run은 선택된 모델 하나를 모든 Prompt class에서 사용하며 역할별 switching을 하지 않는다.

모델 크기를 이유로 업무 의미를 heuristic으로 삭제하거나 등록 Tool을 임의 shortlist하지 않는다. 각 Node의 semantic branching과 Output Schema 복잡도를 작게 유지하고, 실제 허용 한계는 Model·Runtime별 Contract Complexity Gate에서 측정한다.

#### 설계 원칙

| 항목 | 규칙 |
| --- | --- |
| LLM 책임 | 원칙적으로 한 호출은 하나의 의미 판단 또는 하나의 구조화 작성 책임을 가진다. 서로 다른 의미 판단을 하나의 거대 Schema에 합치지 않는다. |
| Schema | 안정적으로 닫을 수 있는 값은 `Literal`/Enum/discriminated union을 사용한다. 자유 `dict` 출력은 금지한다. |
| Branch 표현 | `status + requires_confirmation + blockers`처럼 같은 의미를 상호의존 필드에 중복 표현하지 않는다. 한 discriminator가 유효 branch를 결정한다. |
| 결정적 코드 | 날짜 계산, interval 교집합·차집합, Registry eligibility, Policy Precondition Read 보강, 실제 사용자 Confirmation→`PolicyConfirmationReceiptV1` 생성/Context Hash 검증, 중복·충돌 relation 검증, state freshness, DAG cycle, Policy·Approval·Verification을 소유한다. |
| Tool 후보 | signed Registry 전체를 정보 손실 없이 사용할 수 있으나 LLM에는 현재 판단에 필요한 eligible candidate projection만 전달한다. Eligibility filtering은 Resource·Effect·Schema 적합성의 결정적 규칙이며, 모델 부담 감소만을 이유로 의미 가능한 Tool을 제거하지 않는다. |
| Planning Argument Writer | `OutputToolRouteV1` 하나와 해당 Tool Schema 하나를 소비한다. 여러 Output Route의 Arguments를 하나의 LLM Schema로 동시에 생성하지 않는다. |
| Action Dependency | 생성·정규화·cycle 검증은 deterministic Planning Application Node가 소유한다. `planning.compose_dependencies` PromptRef를 추가하지 않으며 Active PromptRef 수 유지를 위해 atomic responsibility를 합치지 않는다. P0에서는 Business Arguments에 안정적 외부 Resource identity가 이미 있고 그 identity가 같은 Action만 frozen route 순서대로 연결한다. CREATE나 서로 다른 Resource의 dependency를 추정하지 않는다. |
| 문법·의미 검증 | Structured/Constrained Output은 문법 유효성을 높이는 수단이지 의미 정답의 보장이 아니다. Schema Validator와 Semantic Validator의 책임을 분리한다. |
| Deterministic semantic guard | 이미 확정된 Typed State·closed enum·explicit prohibition·selected identity·duplicate kind·canonical fact와의 구조적 모순만 거절한다. Source 누락이나 READ/WRITE 의미를 새로 판단하거나 정답 Candidate를 생성·보정하지 않는다. |
| Runtime 조합 | Tool Calling과 별도 JSON Schema constrained decoding을 함께 쓰는 조합은 독립 Candidate로 검증한 뒤 채택한다. 한쪽 Contract Gate 성공을 다른 조합의 성공으로 간주하지 않는다. |

#### Complexity Metadata와 Gate

각 LLM Node는 최소 다음 Metadata를 실험에 노출한다.

```
schema_required_field_count
schema_optional_field_count
schema_max_depth
schema_union_branch_count
schema_max_enum_cardinality
tool_candidate_count
input_projection_estimated_tokens
output_token_budget
```

이 값에 대한 **전역 고정 상한은 문서에 선험적으로 두지 않는다.** `13 Evaluation`의 Complexity Sweep에서 Node·Model·Runtime별 안정 구간을 찾고, Release Candidate Config가 그 측정 범위를 벗어나면 새 Contract Gate를 요구한다.

Local Node Contract Stability의 기본 Gate는 적용 Case N=50에서 `final_contract_valid >= 49/50`, uncaught exception 0, repair budget 초과 0이며, 의미 품질은 별도 Gold/Node Accuracy Gate에서 판정한다. Contract Gate 통과는 업무 정답을 의미하지 않는다.

### 1.5 Evaluation isolation reference

Product Prompt와 Runtime failure/retry contract는 평가 Harness의 Gold·Grader·Simulator·Candidate metadata를 입력 authority로 사용하지 않는다. 구체적인 Evaluation artifact와 Simulator/feedback isolation 규칙은 `13 Evaluation`이 소유하고, 본 문서 §12는 Runtime이 허용하는 소비 경계만 정의한다.

### 1.6 Runtime fixed values

```yaml
llm_budget_policy: ROUTE_PROFILE
normal_max_llm_calls: 14
retrieval_heavy_max_llm_calls: 20
revision_heavy_max_llm_calls: 18
absolute_max_llm_calls: 24
node_holdout: SEPARATE
failure_reason_min_items:
  dev: 3
  holdout: 1
prompt_runtime_activation: VALIDATION_GATED
semantic_revision_same_failure_max: 1
planning_revision_run_max: 2
review_recheck_per_revision_max: 1
additional_retrieval_max: 2
confidence_bands: [HIGH, MEDIUM, LOW, NONE]
threshold_owner: RETRIEVAL_CONFIG
failure_reason_prompt_key: ASSEMBLY_METADATA
prompt_assembly: BASE_PLUS_FAILURE_BLOCK
```

### 1.7 Responsibility-Split Prompt Topology

목표는 LLM authority를 늘리는 것이 아니라 **한 LLM 호출이 담당하는 semantic responsibility를 줄이는 것**이다. 6개 `SemanticAgentOwnerIdV1` 책임 경계는 유지하며 physical compiled Agent Subgraph 수는 selected Graph Profile의 1/3/6 exact binding을 따른다.

Local SLLM 기본 Profile에서는 서로 다른 semantic 판단을 한 Product LLM 호출로 fuse하지 않는다. 역할별 atomic responsibility와 처리 조건은 다음과 같다.

#### Work Analysis

사람·업무·시간·dependency·duplicate/conflict 판단을 atomic responsibility로 분리한다.

| Operation | 처리 | 조건·책임 |
| --- | --- | --- |
| `work_analysis.extract_work_facts` | LLM | 업무 사실 추출 |
| `work_analysis.resolve_entity_relations` | LLM | conditional. 사람·업무·Resource identity·ownership/reference 관계만 소유한다. |
| `work_analysis.resolve_temporal_dependencies` | LLM | conditional. 날짜·기간·선후·dependency 후보만 소유한다. |
| `work_analysis.detect_duplicate_conflict_candidates` | LLM | conditional. fact↔fact duplicate/conflict candidate만 제안한다. |
| `work_analysis.assess_requested_task_satisfaction` | LLM | conditional. 현재 Task 관측이 요청 업무를 이미 만족하는지만 평가한다. |
| `work_analysis.validate_relations` | deterministic | 실제 `DUPLICATES \| CONFLICTS_WITH` 확정은 relation validator가 소유한다. |
| `work_analysis.assess_action_necessity` | LLM/deterministic | frozen Output Route별 적용 여부를 한 번 판단한다. Task CREATE는 앞선 중복 검토 결과에서 결정적으로 파생한다. |
| `work_analysis.assess_information_gaps` | LLM | 부족 정보 평가 |
| `work_analysis.assess_operational_risks` | LLM | conditional |
| `work_analysis.assemble_work_analysis` | deterministic | 분석 결과 조립 |
| `work_analysis.validate_work_analysis` | deterministic | 분석 결과 검증 |

#### Planning 공통·ANSWER

| Operation | 처리 | 범위 |
| --- | --- | --- |
| `planning.choose_answer_or_action_from_route` | deterministic | 공통 |
| `planning.outline_answer` | deterministic/LLM-conditional | Work Analysis·확인 필요가 없는 ANSWER는 현재 Run 원문 + 허용 Evidence ref로 조립. 그 외 ANSWER만 LLM |
| `planning.compose_answer` | LLM | ANSWER |

**Evidence-backed READ answer composition**

| 항목 | 처리·제한 |
| --- | --- |
| 답변 생성 | `compose_answer`는 사람·시간 조건이나 `PARTIAL`이라는 이유만으로 생략하지 않는다. Evidence 원문을 최종 답변으로 대체하지 않는다. 기존 결정적 resource/empty-result projection은 유지하되 의미 요약이 필요한 답변은 기존 Prompt slot을 사용한다. |
| 개요 생성 | Work Analysis와 unresolved confirmation이 모두 없으면 원문을 단일 section으로 보존하고 현재 Evidence ref만 순서대로 전달한다. 자연어 heuristic으로 section이나 ref를 재선택하지 않는다. Work Analysis 또는 confirmation 판단이 필요하면 기존 `planning.outline_answer` Prompt slot을 유지한다. |
| 입력 | 선택된 Evidence와 함께 Retrieval의 `coverage`, `unresolved_event_dates`, `missing_information`, `source_statuses` 중 필요한 bounded projection을 optional input으로 소비한다. 과거 checkpoint에 필드가 없으면 확정 사실을 추측하지 않는다. |
| 사실 표현 | 검색 기간은 행사 날짜의 사실 근거가 아니다. 미확정 연도·인물을 확정 표현으로 승격하지 않는다. 부분 범위·미해결 사실·조회 실패 안내를 보존하고 원문/내부 metadata dump 대신 요청에 대한 간결한 답변을 만든다. |
| 실행 경로 | 기존 RunBudget와 `Planning.ANSWER_ONLY → RESPONSE_SYNTHESIS` 경로를 유지한다. 별도 Review 호출이나 새로운 상태를 추가하지 않는다. |
| Output validation | 알려진 연도 미확정 날짜를 명시적 연도 또는 요일로 승격한 답변은 거절한다. 경고를 덧붙여 모순된 답변을 성공 처리하거나 날짜를 임의 교정하지 않는다. 기존 bounded failure 경로를 유지한다. |

#### Planning ACTION

Frozen Output Route별로 다음 책임을 분리한다.

| Operation | 처리 | 책임 |
| --- | --- | --- |
| `planning.draft_action_objective_per_output_route` | LLM | 사용자 목표와 frozen Output Route의 target semantics만 작성한다. Tool identity/effect/arguments를 변경하지 않는다. |
| `planning.compose_arguments_per_output_route` | LLM/tool-schema | 확정 objective와 selected Tool Schema를 받아 business arguments만 직렬화한다. |
| `planning.build_dependencies` | deterministic | dependency 생성 |
| `planning.assemble_plan` | deterministic | 계획 조립 |
| `planning.validate_plan` | deterministic | 계획 검증 |

Arguments Projection에는 현재 검증된 `request_intent` 제약도 포함한다. 정확한 Task/Calendar CREATE가 이 Projection과 frozen Route로 하나로 결정되면 동일 Typed Candidate를 결정적으로 만들 수 있지만, 추가 semantic 판단이 남으면 Product Prompt 호출을 유지한다. 결정적 materialization도 assemble/validate, Review, Domain Validation, Approval, Verification을 우회하지 않는다.

**Task Preview 자연어 수정 준비**

| 항목 | 규칙 |
| --- | --- |
| 사용 경로 | 기존 `planning.compose_arguments_per_output_route`의 optional `modification` projection을 사용한다. |
| 입력 | `request`, persisted `current_arguments`, `reference_time`, `timezone`만 전달한다. supplied Tool schema는 허용된 부분 payload로 좁힌다. |
| 응답 해석 | 누락된 필드는 보존한다. notes 빈 문자열·due null만 명시적 제거로 해석한다. |
| 모호하거나 허용 범위 밖인 요청 | 빈 patch/검증 실패로 기존 Preview를 유지한다. |
| 변경 확정 | 준비 단계는 Domain 사실을 변경하지 않는다. 이후 기존 ModifyAction CAS·Approval revoke·REVIEW_ENTRY handoff가 변경을 확정한다. |
| 금지 | Frontend parsing 또는 새 Prompt/Agent authority를 만들지 않는다. |

#### Review

Goal/evidence/action/route/constraint/policy 검사를 atomic inspector responsibility로 분리한다.

| Operation | 처리 | 조건·책임 |
| --- | --- | --- |
| `review.inspect_goal_and_evidence` | LLM | goal fit, evidence adequacy, unsupported claim/contradiction만 검사한다. |
| `review.inspect_action_scope_and_route` | LLM | conditional, ACTION only. action necessity, frozen Tool Route consistency, scope expansion만 검사한다. |
| `review.inspect_constraints_and_policy_summary` | LLM | conditional. user constraints + supplied policy summary만 검사하며 새 정책을 생성하지 않는다. |
| `review.aggregate_review_findings` | deterministic | typed finding을 deterministic precedence로 합성해 최종 Review disposition을 만든다. LLM finding category 자체가 routing authority가 아니다. |
| `review.validate_review` | deterministic | Review 검증 |
| `review.recheck_affected_dimensions` | LLM | conditional. Revision 후 `affected_dimensions`만 재검사한다. 유일하게 확인된 같은-route 전후 제안 관계는 optional이며 이전 issue별 해결 판정과 현재 finding을 분리한다. dimension-only issue는 action/route identity 없이 보존한다. |

세 inspector는 `06 Workflow`의 `ReviewInspectorResultV1` typed intermediate만 반환한다. free-form dimension/object를 반환하지 않으며 `ReviewDimensionIdV1` closed set 밖 값은 deterministic validator가 거절한다.

#### Fusion·안전 경계

더 강한 Runtime에서 인접 LLM Node를 fuse하려면 위 atomic candidate의 Typed Output 의미를 모두 재현하고 `12 Test / 13 Evaluation`의 parity·failure-isolation gate를 통과해야 한다.

- Subgraph 간 책임과 Tool Route·Policy·Domain·Approval·Claim·external WRITE·Verification·Recovery authority는 바뀌지 않는다.
- LLM 결과는 candidate/finding일 뿐 Domain mutation이나 routing authority가 아니다.
- DEV → Holdout → Safety Gate 전에는 current Prompt manifest를 Runtime Active로 승격하지 않는다.

## 2. Agent Registry

| Agent Role | 주 책임 | 주요 입력 | 주요 출력 | 금지 |
| --- | --- | --- | --- | --- |
| `request_understanding` | 목표·완료 조건·제약·모호성, WorkUnit 경계·binding·사용자 업무 관계 구조화 | 사용자 요청, Entry Mode, 선택 Resource | `RequestIntentV3` | Connector 조회, Action 생성, Action dependency·실행 권한 판단 |
| `tool_route` | IN Resource/Read Tool 범위와 OUT Resource/Effect/Tool 확정 및 WorkUnit binding 전달 | `RequestIntentV3`, Signed Tool Registry | `ToolRoutePlanV2` | Query 작성, Evidence 판단, Arguments 작성 |
| `retrieval` | 고정 IN Route에서 Query·Read·RAG·Evidence·Sufficiency와 route coverage binding 보존 | `RequestIntentV3`, frozen `input_routes`, Retrieval Budget | `RetrievalResultV1` | OUT Tool 변경, Write, Tool 종류 재선택, WorkUnit별 Provider READ 복제 |
| `work_analysis` | 필요한 경우 업무 사실·관계·누락·중복·충돌·일정 위험 분석 | User Request, Intent, optional Evidence | `WorkAnalysisResultV2` 또는 Work Analysis 소유 Confirmation signal | 정책 최종 판정, 실행, LLM 단독 중복·충돌 확정, Confirmation 없는 Override |
| `planning` | 고정 OUT Route의 Answer/Arguments·Dependency 작성 | User Request, Intent, `OutputPlanV1`, optional Analysis, Evidence | `AnswerDraftV2` 또는 `ActionPlanDraftV2` | Tool 재선택, 승인, 실행 |
| `review` | 목표 충족·Evidence·과잉 Action·모순·Route 오류 검토 | Plan Draft, Evidence, Policy Summary | `PlanReviewResultV2` | Route 직접 변경, 실행 허용 최종 판정 |

**Work Analysis의 중복·충돌 처리**

LLM은 관계 후보를 제안할 수 있으나 `DUPLICATES`·`CONFLICTS_WITH`와 그에 따른 no-action 판단은 결정적 relation validator 검증을 거친다. 정확 중복의 추가 생성이나 검증된 일정 충돌 Override는 각각 `DUPLICATE_OVERRIDE_REQUIRED` / `CONFLICT_OVERRIDE_REQUIRED` 2차 Confirmation을 요구한다. 승인 후 결과는 현재 Context에 유효한 Receipt ref를 포함한다.

## 3. Capability 분류 축

서로 다른 개념을 한 Enum에 섞지 않는다.

### 3.1 입력 조건 `input_condition`

```
NORMAL
BOUNDARY
AMBIGUOUS
INSUFFICIENT
LOW_CONFIDENCE
CONFLICTING
NOISY
ADVERSARIAL
```

### 3.2 출력 실패 `output_failure_type`

```
NONE
SCHEMA_INVALID
SEMANTIC_INVALID
```

### 3.3 복구 처분 `recovery_disposition`

```
RETRYABLE
REDIRECT
DETERMINISTIC
TERMINAL
NOT_AVAILABLE
```

### 3.4 실패 감지 주체 `detected_by`

```
RUNTIME_SCHEMA_VALIDATOR
RUNTIME_DOMAIN_VALIDATOR
RUNTIME_POLICY_VALIDATOR
RUNTIME_REVIEW_AGENT
RUNTIME_PROVIDER
EXPERIMENT_DETERMINISTIC_GRADER
EXPERIMENT_SEMANTIC_GRADER
HUMAN_REVIEW
```

실험 Grader가 발견한 실패를 제품 Runtime이 스스로 감지할 수 있다고 가정하지 않는다.

## 4. Node Result Taxonomy

기존 결과 Enum을 유지한다.

| 책임 | 결과 Enum |
| --- | --- |
| Request Understanding | `COMPLETE \| NEEDS_CONFIRMATION \| INVALID` |
| Tool Route | `ROUTE_READY \| NO_TOOL_NEEDED \| NEEDS_CONFIRMATION \| BLOCKED` |
| Retrieval | `SUFFICIENT \| NO_FETCH_NEEDED \| NEEDS_MORE_DATA \| NEEDS_CONFIRMATION \| ROUTE_RECONSIDERATION_REQUIRED \| PARTIAL \| BLOCKED` |
| Work Analysis | `COMPLETE \| NEEDS_MORE_DATA \| NEEDS_CONFIRMATION \| REQUEST_RECONSIDERATION_REQUIRED \| ROUTE_RECONSIDERATION_REQUIRED \| BLOCKED` |
| Planning | `ANSWER_ONLY \| PLAN_READY \| NEEDS_CONFIRMATION \| ROUTE_RECONSIDERATION_REQUIRED \| BLOCKED` |
| Review | `PASS \| REVISE \| RETRIEVE_MORE \| ROUTE_RECONSIDERATION \| CONFIRM \| BLOCK` |
| Domain | `ALLOW_READ \| REQUIRE_APPROVAL \| BLOCK` |

`PARTIAL`은 Run Status가 아니라 결과 종류다.

```yaml
run_status: COMPLETED
result_kind: PARTIAL
```

장애로 종료되면 `FAILED` 또는 `RECOVERY_REQUIRED`와 함께 기록한다.

## 5. Failure Reason Record

```yaml
failure_record:
  schema_version: 1
  failure_id: string
  failure_reason_code: string
  failure_origin: LLM_OUTPUT | QUERY_PLANNING | RETRIEVAL_RESULT | PROVIDER | DOMAIN | POLICY | EXPERIMENT
  detected_by: string
  runtime_disposition: RETRYABLE | REDIRECT | DETERMINISTIC | TERMINAL | NOT_AVAILABLE
  experiment_disposition: COUNT_FAILURE | RUN_REPAIR | RUN_REVISION | REJECT_CANDIDATE | HUMAN_REVIEW
  affected_field_paths: [string]
  evidence_refs: [string]
```

예:

```yaml
failure_reason_code: REVIEW_FALSE_PASS
failure_origin: EXPERIMENT
detected_by: EXPERIMENT_DETERMINISTIC_GRADER
runtime_disposition: NOT_AVAILABLE
experiment_disposition: REJECT_CANDIDATE
```

## 6. Failure Reason Taxonomy

### 6.1 공통 Schema 실패

| Code | 기본 Runtime 처리 |
| --- | --- |
| `SCHEMA_INVALID_JSON` | `SCHEMA_REPAIR` |
| `SCHEMA_REQUIRED_FIELD_MISSING` | `SCHEMA_REPAIR` |
| `SCHEMA_INVALID_ENUM` | `SCHEMA_REPAIR` |
| `SCHEMA_WRONG_TYPE` | `SCHEMA_REPAIR` |
| `SCHEMA_UNSUPPORTED_FIELD` | `SCHEMA_REPAIR` |
| `SCHEMA_VERSION_MISMATCH` | 호출 중단 또는 Schema Repair 1회 |

추가 Local SLLM 운영 실패 코드는 다음을 사용한다.

```
SLLM_SCHEMA_COMPLEXITY_OUT_OF_PROFILE
SLLM_PROJECTION_BUDGET_EXCEEDED
SLLM_TOOL_CANDIDATE_AMBIGUITY
```

이 코드는 모델이 작다는 이유만으로 발생시키지 않는다. 승인된 Candidate Config의 측정 Complexity Profile을 벗어났거나 Contract Gate에서 해당 복잡도 구간의 안정성이 입증되지 않았을 때 실험·배포 Gate에서 사용한다.

### 6.2 요청 이해 실패

```
INTENT_GOAL_MISSING
INTENT_COMPLETION_CRITERIA_MISSING
INTENT_CONSTRAINT_MISSING
INTENT_ENTRY_MODE_WRONG
INTENT_AMBIGUITY_MISSED
INTENT_OVER_CONFIRMATION
INTENT_UNSUPPORTED_SCOPE
INTENT_SOURCE_DEPENDENCY_CONTRADICTION
```

### 6.3 Tool Route 실패

```
TOOL_ROUTE_REQUIRED_INPUT_MISSING
TOOL_ROUTE_FORBIDDEN_INPUT_INCLUDED
TOOL_ROUTE_REQUIRED_OUTPUT_MISSING
TOOL_ROUTE_FORBIDDEN_OUTPUT_INCLUDED
TOOL_ROUTE_UNREGISTERED_TOOL
TOOL_ROUTE_EFFECT_MISMATCH
TOOL_ROUTE_OUTPUT_MODE_WRONG
TOOL_ROUTE_READ_IN_OUTPUT
TOOL_ROUTE_OVERCONFIRMATION
TOOL_ROUTE_CONTRACT_INVALID
SLLM_TOOL_CANDIDATE_AMBIGUITY
```

### 6.4 Retrieval·Query·RAG 실패

```
RETRIEVAL_ROUTE_SCOPE_VIOLATION
RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID
QUERY_OPERATION_FIELD_MISMATCH
QUERY_USER_CONSTRAINT_MISSING
QUERY_TOO_BROAD
QUERY_UNCHANGED_AFTER_FAILURE
QUERY_PROTECTED_CONSTRAINT_CHANGED
QUERY_SCOPE_EXPANSION_REQUIRES_CONFIRMATION
QUERY_LOW_CONFIDENCE_RESULTS
QUERY_NO_RESULTS
QUERY_BUDGET_EXHAUSTED
QUERY_DETAIL_FETCH_FAILED
QUERY_AUTH_REQUIRED
QUERY_RATE_LIMITED
QUERY_PROVIDER_FAILED
RAG_REQUIRED_SEGMENT_MISSING
RAG_HARD_NEGATIVE_SELECTED
RAG_STALE_EVIDENCE_SELECTED
RAG_PROMPT_INJECTION_FOLLOWED
RAG_CONTEXT_BUDGET_EXCEEDED
CTX_CONFLICT_NOT_REPORTED
CTX_LOW_CONFIDENCE_AUTO_SELECTED
CTX_SUFFICIENCY_WRONG
RETRIEVAL_ROUTE_RECONSIDERATION_MISSED
```

### 6.5 업무 분석 실패

```
ANALYSIS_UNSUPPORTED_INFERENCE
ANALYSIS_RELATION_MISSING
ANALYSIS_CONFLICT_MISHANDLED
ANALYSIS_DUPLICATE_MISCLASSIFIED
ANALYSIS_SCHEDULE_RISK_MISCLASSIFIED
ANALYSIS_NEEDS_MORE_DATA_MISSED
```

### 6.6 Planning 실패

```
PLAN_REQUIRED_ACTION_MISSING
PLAN_EXCESS_ACTION
PLAN_ROUTE_TOOL_MISMATCH
PLAN_WRONG_TARGET
PLAN_REQUIRED_EVIDENCE_MISSING
PLAN_DEPENDENCY_INVALID
PLAN_ARGUMENT_CONSTRAINT_VIOLATION
PLAN_USER_SCOPE_VIOLATION
PLAN_POLICY_RISK
PLAN_ANSWER_ONLY_MISROUTED
```

### 6.7 Review 실패

```
REVIEW_FALSE_PASS
REVIEW_FALSE_BLOCK
REVIEW_ROUTE_RECONSIDERATION_MISSED
REVIEW_ERROR_NOT_LOCALIZED
REVIEW_REPEATED_SAME_FAILURE
```

### 6.8 비-LLM 실패

다음은 Prompt로 복구하지 않는다. 비-LLM 실패는 **소유 Concern의 canonical code/state를 그대로 보존**하며, 본 문서가 Provider별 별도 공통 Error Enum을 만들지 않는다.

Connector/MCP 실패는 `07 Interface`의 Error Enum을 사용한다.

```
AUTH_EXPIRED
RATE_LIMITED
UPSTREAM_5XX
NOT_FOUND
INVALID_ARGUMENT
POLICY_BLOCKED
APPROVAL_INVALID
VERSION_CONFLICT
DUPLICATE_COMMAND
TIMEOUT
MCP_UNAVAILABLE
```

`AUTH_EXPIRED`는 Workflow/Domain에서 필요한 경우 `REAUTH_REQUIRED` 흐름으로 조정한다. `UNKNOWN_RESULT`는 Connector 오류 코드가 아니라 `04 Domain`의 실행 결과 불명 상태이며 새 Write Attempt를 만들지 않는다. Provider-specific `GOOGLE_READ_*` / `GOOGLE_WRITE_*` 이름은 공통 `failure_reason_code` 권위를 갖지 않는다.

그 밖의 비-LLM failure/운영 코드는 해당 owner 계약을 따른다.

```
VERIFICATION_MISMATCH
VERIFICATION_TIMEOUT
SQLITE_BUSY
SQLITE_DISK_FULL
AUDIT_PERSIST_FAILED
MCP_EXIT
SSE_LOSS
LAUNCHER_SHUTDOWN_TIMEOUT
```

## 7. Retry Kind와 처리 주체

| Retry Kind | 정의 | LLM 사용 |
| --- | --- | --- |
| `NONE` | 성공·종료 또는 재시도 없는 경로 전환 | 아니오 |
| `SCHEMA_REPAIR` | 의미를 유지하며 구조만 교정 | 예 |
| `SEMANTIC_REVISION` | 실패 이유와 허용 범위 안에서 내용을 재판단 | 예 |
| `WORKFLOW_REDIRECTION` | 다른 Node·Interrupt·종료로 이동 | 아니오 |
| `DETERMINISTIC_RETRY` | 네트워크·Provider Read 기술 재시도 | 아니오 |
| `DETERMINISTIC_RECOVERY` | Reauth·Fingerprint Search·GET Verification | 아니오 |

### 7.1 금지 조합

| 상황 | 금지 |
| --- | --- |
| `AUTH_REQUIRED` | LLM Repair·Revision 호출 |
| 429·5xx·Timeout | 같은 Agent Prompt 재호출 |
| `UNKNOWN_RESULT` | Planning Revision 또는 Write 재호출 |
| Verification `MISMATCH` | LLM 자동 수정·Rollback |
| 사용자 범위 확대 필요 | 자동 Query 확장 |
| Schema Repair | Goal·Evidence·Action 의미 변경 |
| Runtime에서 차단된 Prompt Injection 결과 | Revision Prompt를 통한 우회 |

## 8. Retry Decision Contract

```yaml
retry_decision:
  schema_version: 1
  decision_id: string
  node_call_id: string
  failure_reason_codes: [string]
  retry_kind: NONE | SCHEMA_REPAIR | SEMANTIC_REVISION | WORKFLOW_REDIRECTION | DETERMINISTIC_RETRY | DETERMINISTIC_RECOVERY
  next_prompt_slot_id: string | null
  next_node_id: string | null
  attempt_no: integer
  max_attempts: integer
  changed_fields_allowed: [json_pointer]
  required_route: string | null
  stop_reason: string | null
```

### 8.1 확정 Budget

```
Schema Repair: Node Call당 최대 1회
Semantic Revision: 동일 Node·동일 Failure Signature당 최대 1회
Planning Revision: Run당 최대 2회
Review Recheck: 각 Planning Revision 결과마다 최대 1회
Additional Retrieval: 최초 Retrieval 이후 최대 2회
```

### 8.2 Route별 LLM 호출 Budget Profile

현재 확정 Route Profile Budget을 적용한다.

```
NORMAL_MAX_LLM_CALLS=14
RETRIEVAL_HEAVY_MAX_LLM_CALLS=20
REVISION_HEAVY_MAX_LLM_CALLS=18
ABSOLUTE_MAX_LLM_CALLS=100
```

| Profile·관측값 | 적용 조건 |
| --- | --- |
| `NORMAL` | 기본 Profile |
| `RETRIEVAL_HEAVY` | `NEEDS_MORE_DATA` 또는 Additional Retrieval이 실제 발생한 경우에만 선택 |
| `REVISION_HEAVY` | Review가 허용한 Revision, same-Run confirmation resume, 또는 frozen multi-output contract가 실제로 필요한 경우에만 선택 |
| Profile 승격 | Supervisor의 결정적 규칙으로 수행 |
| `ABSOLUTE_MAX_LLM_CALLS` | 유일한 Run-level hard limit이며 상한을 넘으면 Prompt를 더 호출하지 않음 |

absolute 상한은 100이다. `NORMAL=14`, `RETRIEVAL_HEAVY=20`, `REVISION_HEAVY=18`은 profile 관측값이며 dispatch를 차단하지 않는다. same-Run confirmation 또는 검증된 multi-output은 기존 counter를 유지한 채 `REVISION_HEAVY`까지 승격할 수 있지만, retry를 살리기 위한 자동 승격이나 counter reset은 금지한다. 과거 저장값 24/36은 현재 계약을 읽을 때 100으로 정규화한다.

### 8.3 Budget 소진 처리

Budget 소진을 `COMPLETED`로 숨기지 않는다.

```
result_kind: PARTIAL
또는
run_status: WAITING_CONFIRMATION | BLOCKED | FAILED | RECOVERY_REQUIRED
```

## 9. Prompt Registry Contract

### 9.0 Current runtime gate

- Current Prompt Runtime은 `06 Workflow`의 current LLM responsibility와 이 문서의 PromptRef contract에서 파생한다.
- Runtime 활성화 전 required PromptRef / caller / manifest / source / assembled / input-contract exact-set equality와 DEV → Holdout → Safety Gate를 통과해야 한다.
- Prompt Slot 숫자나 non-current candidate identity는 topology authority가 아니며, Product Prompt assembler는 current slot allowlist만 직렬화한다. Evaluation Projection 전체를 Prompt Input으로 전달하지 않는다.

### 9.1 Prompt Runtime Slot 선택 Key

```
agent_role
subgraph_name
node_name
node_state
purpose
input_schema_version
output_schema_version
```

`failure_reason_code`는 Runtime Prompt Slot 식별 Key가 아니다. 이미 선택된 Base Prompt에 결합할 Failure-specific Instruction Block을 선택하는 metadata다. 조립 완료 후 최종 Prompt의 `content_hash`를 계산한다.

### 9.2 PromptRef

```yaml
prompt_ref:
  prompt_bundle_version: string
  prompt_slot_id: string
  prompt_id: string
  prompt_version: string
  content_hash: string
  agent_role: string
  subgraph_name: string
  node_name: string
  node_state: string
  purpose: string
  failure_reason_code: string | null  # assembly/trace metadata; not Runtime Slot Key
  input_schema_version: integer
  output_schema_version: integer
  activation_status: DRAFT | DEV_VALIDATED | HOLDOUT_VALIDATED | RUNTIME_ACTIVE | RETIRED
```

### 9.3 Prompt 종류

```
INITIAL
CLARIFY
ASSESS
SCHEMA_REPAIR
SEMANTIC_REVISION
RECHECK
```

`WORKFLOW_REDIRECTION`, `DETERMINISTIC_RETRY`, `DETERMINISTIC_RECOVERY`에는 PromptRef가 없어야 한다.

### 9.3-A Current PromptRef exact-set identity

Current Prompt Runtime의 exact-set equality는 **`prompt_slot_id`를 set identity key로 사용**한다.

`prompt_version`, `content_hash`, `activation_status`, per-invocation `failure_reason_code`는 같은 slot의 release/runtime metadata이며 별도 PromptRef set cardinality를 만들지 않는다.

`SCHEMA_REPAIR`·`SEMANTIC_REVISION`은 별도 전체 Prompt source를 복제하지 않고 같은 Base Slot에 Failure/Allowed-Change block을 조립한다.

Current required Product-LLM Prompt Slot set은 아래 29개다. 각 slot에서 `prompt_id == prompt_slot_id`이며, 왼쪽 runtime caller mapping은 `06`의 Node Registry를 소비한다.

| Runtime Node | `prompt_slot_id` (= `prompt_id`) |
| --- | --- |
| `request.identify_goal` | `request_understanding.identify_goal` |
| `request.identify_goal` | `request_understanding.identify_effect_prohibitions` |
| `request.identify_goal` | `request_understanding.identify_source_dependencies` |
| `request.identify_goal` | `request_understanding.identify_output_responsibilities` |
| `request.identify_goal` | `request_understanding.identify_source_status` |
| `request.identify_temporal_scope` | `request_understanding.identify_temporal_scope` |
| `request.detect_ambiguity` | `request_understanding.detect_ambiguity` |
| `route.determine_resources` | `tool_routing.determine_io_resources` |
| `route.select_tool` | `tool_routing.select_tool_if_needed` |
| `retrieval.plan_query` | `retrieval.plan_query` |
| `retrieval.select_evidence` | `retrieval.select_evidence` |
| `retrieval.assess_sufficiency` | `retrieval.assess_sufficiency` |
| `analysis.extract_facts` | `work_analysis.extract_work_facts` |
| `analysis.resolve_entity_relations` | `work_analysis.resolve_entity_relations` |
| `analysis.resolve_temporal_dependencies` | `work_analysis.resolve_temporal_dependencies` |
| `analysis.detect_duplicate_conflict_candidates` | `work_analysis.detect_duplicate_conflict_candidates` |
| `analysis.detect_duplicate_conflict_candidates` | `work_analysis.assess_requested_task_satisfaction` |
| `analysis.assess_action_necessity` | `work_analysis.assess_action_necessity` |
| `analysis.assess_information_gaps` | `work_analysis.assess_information_gaps` |
| `analysis.assess_operational_risks` | `work_analysis.assess_operational_risks` |
| `planning.outline_answer` | `planning.outline_answer` |
| `planning.compose_answer` | `planning.compose_answer` |
| `planning.draft_action_objective_per_output_route` | `planning.draft_action_objective_per_output_route` |
| `planning.compose_arguments_per_output_route` | `planning.compose_arguments_per_output_route` |
| `review.inspect_goal_and_evidence` | `review.inspect_goal_and_evidence` |
| `review.inspect_action_scope_route` | `review.inspect_action_scope_and_route` |
| `review.inspect_constraints_policy` | `review.inspect_constraints_and_policy_summary` |
| `review.recheck` | `review.recheck_affected_dimensions` |
| `run.compose_terminal_response` | `run.compose_terminal_response` |

Current PromptRef 집합은 current LLM responsibility에 실제 caller가 있는 Slot에서 파생한다. Active Slot 수를 별도 설계 상수로 두거나 broad predecessor ID의 수를 보존하기 위해 current 집합을 만들지 않는다. manifest/source/caller/input-contract의 exact-set equality로 계산한다.

**현재 사용하지 않는 broad predecessor PromptRef**

```text
request_understanding.identify_resource_responsibilities
work_analysis.resolve_relations
review.inspect
review.recheck
```

이 ID들은 alias로 유지하지 않는다. Current responsibility의 실제 caller가 있는 PromptRef만 manifest/source/input-contract에 포함한다.

`prompt_version`은 current manifest가 slot별로 선택하는 version identity이고, `content_hash`는 9.4 조립 규칙으로 materialize된 immutable prompt artifact의 SHA-256이다. `activation_status`는 9.5/13 Evaluation Gate가 승격한다.

이 세 값의 **구체 Release 값은 canonical prompt source identity가 아니며** repository/source filename set을 늘리지 않는다. Current manifest는 각 required slot에 정확히 하나의 selected current version row를 가져야 한다.

`prompt-runtime-input-contract-v1`은 위 29개 `prompt_slot_id`와 exact-set equality를 이루며, 각 row가 06/15가 허용한 current Typed Projection의 `input_schema_version`, allowlisted root fields, output schema version을 참조한다.

Conversation history, previous-run artifact, raw Provider/MCP continuation, Gold/Grader metadata를 새 field로 추가할 수 없다. Repository path/loader/test realization은 16 Repository Architecture가 소유한다.

Current input-contract artifact의 logical schema는 다음으로 닫는다.

```yaml
prompt_runtime_input_contract:
  schema_version: 1
  entries:
    - prompt_slot_id: string
      runtime_node_id: string
      input_schema_version: integer
      required_root_fields: [string]
      optional_root_fields: [string]
      output_schema_version: integer
```

`entries[].prompt_slot_id`는 위 29개 exact set과 같고 `runtime_node_id`는 위 caller mapping과 exact match한다. Field allowlist의 semantic 내용은 06/15 current projection contract를 소비하며, 이 JSON artifact가 새로운 Product Prompt 입력 field를 발명할 수 없다.

`run.compose_terminal_response`는 Main Application caller가 종료 가능한 WRITE의 `TerminalResponseInputV1`만 전달한다. 출력은 `{answer}` exact object이며 LLM이 result kind, terminal kind, 실행 여부, 승인·정책을 다시 출력하거나 판정하지 않는다. Planning ANSWER에는 이 슬롯을 호출하지 않는다. 응답 실패는 기존 결정적 formatter로 fallback하고 Local→API 자동 fallback은 허용하지 않는다.

### 9.3-B Tool Routing 선택 Prompt 입력

| 항목 | 규칙 |
| --- | --- |
| `tool_routing.select_tool_if_needed` producer | 같은 Run의 `user_request`를 전달해 동일 effect의 등록 후보 간 업무 의도(내용 수정/닫기/다시 열기 등)를 구분한다. |
| 호환성 | v1 input allowlist의 optional field로 추가하여 기존 projection과 호환한다. route/eligible candidate authority는 변경하지 않는다. |
| Connector | Google 이외의 eligible Connector도 동일하게 취급한다. |
| WRITE 선행 Retrieval | 요청된 미래 상태가 아니라 현재 대상의 근거 충분성을 평가한다. |

### 9.4 조립 규칙

```
Base Role Contract
+ Node Purpose Instruction
+ Failure-specific Instruction Block(optional)
+ Allowed Change Scope
+ Output Schema
```

실패 원인별 Prompt 전체 복제를 금지한다. Base와 Failure Block을 조립하고 최종 조립 결과의 Hash를 기록한다.

### 9.5 Runtime 활성화 Gate

```
DRAFT
→ Node DEV 통과
→ Node HOLDOUT 통과
→ Safety Gate 통과
→ Prompt Manifest 승인
→ RUNTIME_ACTIVE
```

검증되지 않은 Prompt는 Artifact로 존재할 수 있으나 Runtime에서 선택할 수 없다.

### 9.6 Prompt execution scope와 release evidence

Prompt 실행 Scope는 다음 closed vocabulary만 사용한다.

#### PRODUCT_RELEASE

`SIGNED_RELEASE_MANIFEST` composition만 선택한다.

- 모든 current Slot이 `RUNTIME_ACTIVE`이고 DEV·HOLDOUT·Safety·Manifest Approval flag와 immutable evidence metadata가 완전해야 한다.
- `DRAFT`, `DEV_VALIDATED`, `HOLDOUT_VALIDATED`, `RETIRED`는 신규 실행을 fail closed한다.
- 환경 변수로 이 Scope를 변경할 수 없다.

#### DEVELOPMENT_SMOKE

`EXPLICIT_DEVELOPMENT` composition만 선택한다.

- 실험 전 `DRAFT` baseline의 실제 Product workflow smoke를 허용한다. release activation이나 Prompt 품질 통과를 뜻하지 않는다.
- Readiness는 `UNVALIDATED_BASELINE`을 명시한다.
- `RETIRED`는 신규 실행할 수 없다.

#### EVALUATION

Offline candidate evaluation 전용이다. Product user runtime과 분리하고 Gold·Grader·expected output·evaluation identity를 Product Prompt input에 넣지 않는다.

#### Activation evidence

`RUNTIME_ACTIVE`/`RETIRED` entry는 다음 metadata를 포함한다.

| 구분 | 필수 metadata |
| --- | --- |
| 모델 | target model identity와 artifact hash |
| Prompt·Schema | Prompt source hash, input/output schema version |
| Dataset | artifact path/hash |
| Grader | artifact path/hash/version |
| 실행 시점 | UTC timestamp |
| 검증 결과 | Node DEV/HOLDOUT/Safety 결과 artifact path/hash |
| 승인 | Manifest Approval artifact path/hash |

모든 path는 Prompt bundle 내부 상대 경로이며, manifest가 고정한 SHA-256과 실제 bytes가 일치해야 한다. Flag나 status 문자열만으로 release evidence를 주장할 수 없다. Signed Release bundle은 packaging 전에 29개 exact Slot의 source hash와 이 evidence chain을 검증한다.

#### Gate Sampling

| 항목 | 조건 |
| --- | --- |
| 평가 횟수 | Node DEV·Node HOLDOUT·Safety Gate는 고정 Sampling 조건에서 Item당 1회 평가한다(`12` 18.2). |
| Temperature | Gate Configuration에서 명시적으로 고정한다. |
| Seed | Provider가 지원함이 확인된 경우에만 고정한다. |
| 재현성 | 완전한 bit-identical Determinism이 아니라 best-effort 재현성이다. |
| 반복 평가 | Trial Consistency·평균·분산·Bootstrap Confidence Interval은 `13 Evaluation` 소관이며 Gate로 옮기지 않는다. |

## 10. Prompt Execution Record

```yaml
prompt_execution:
  schema_version: 1
  llm_call_id: string
  run_id: string
  evaluation_item_id: string | null
  prompt_ref: object
  attempt_no: integer
  retry_kind: string
  failure_reason_codes: [string]
  previous_llm_call_id: string | null
  validator_codes: [string]
  input_hash: string
  output_hash: string
  changed_field_paths: [string]
  result_status: string
  stop_reason: string | null
```

Prompt·Completion 원문은 Trace에 저장하지 않는다. 합성 Dataset Artifact에서만 원문을 관리한다.

## 11. Query Attempt Contract

`QueryAttemptV1`의 **필드·enum·schema_version·identity authority는 05 Retrieval §16 하나만 소유**한다. 이 문서는 Prompt/Failure consumer로서 그 타입을 복제하지 않는다. Retrieval Prompt/validator가 참조할 수 있는 값은 05의 current `QueryAttemptV1` bounded projection뿐이며 Provider-native query/token/raw response는 포함하지 않는다.

### 11.0 Query Planner 출력·결정적 READ

| 항목 | 계약 |
| --- | --- |
| 외부 READ | Retrieval Subgraph의 결정적 Application Node가 `connector_id`에 맞는 Query Builder와 `ConnectorReadPort`를 호출한다. Retrieval LLM Node는 Raw Query·MCP Arguments를 직접 실행하지 않으며 `ToolRoutePlanV2.input_plan.input_routes` 밖의 Tool을 선택·호출하지 않는다. |
| Planner 출력 타입 | `05 Retrieval`의 current `RetrievalQueryPlanV2 / RouteQueryIntentV2`를 사용한다. |
| `SEARCH` | Provider query 대신 typed `SemanticRetrievalConstraintV1`을 출력한다. |
| Follow-up changed SEARCH | 값이 포함된 `ConstraintDeltaV2`를 반환해야 한다. |
| Contract invalid | constraint 이름만 있는 delta, Provider-native Query 문자열, raw continuation, MCP Arguments를 planner authority로 반환한 경우다. |
| 결정적 Builder | `SourceFetchPlanBuilder`만 prior effective constraints와 delta를 merge하고 `SourceFetchPlanV1` 및 query identity를 materialize한다. |

### 11.1 반복 검색 판정

- `NEXT_PAGE`는 05의 `read_result_handle + page_state_hash`가 새 continuation 상태를 증명할 때만 정상 round다.
- 실패 후 merge/normalize된 effective constraints와 page state가 prior attempt와 동일한 `SEARCH`는 canonical failure code `QUERY_UNCHANGED_AFTER_FAILURE`이며 Provider 호출과 round 증가가 모두 0이다.
- `DETAIL_FETCH` 중복 판정은 05의 current Run Retrieval Cache + bounded candidate reference를 사용한다. Query 변경 여부와 Pagination 여부를 하나의 hash로 합치지 않는다.

### 11.2 사용자 의도·Confidence 소비

- 사용자 날짜·사람·Resource constraint 반영 판정은 `QueryAttemptV1.normalized_intent_constraints + query_spec`를 05 semantics 그대로 읽는다.
- `confidence_band`는 `HIGH | MEDIUM | LOW | NONE`; Threshold 값은 중앙 Retrieval Config authority가 소유한다.
- 이 문서의 legacy `retrieval_round/source/entry_mode/query_hash/page_token_hash/selected_candidate_ids` 형태는 Release schema가 아니며 새 코드·Prompt·Trace 계약에 사용하지 않는다.

## 12. Evaluation consumption boundary

`13 Evaluation`은 본 문서의 current Runtime contract를 **read-only evaluation input contract**로 소비한다. Evaluation artifact가 새로운 Product Prompt field, failure code, retry path, Agent capability, Tool/Policy/Domain authority를 정의할 수 없다.

허용되는 Runtime reference는 06의 current node/owner identity, `FailureReasonRecordV1`, `retry_kind`, PromptRef/manifest/input contract, `QueryAttemptV1`, result/status vocabulary, bounded repair/revision budget과 allowed change scope다. Dataset·Gold·Grader·Simulator·Candidate promotion의 schema와 절차는 13에만 둔다.

## 13. Agent별 Capability Coverage

### 13.1 요청 이해

| 범주 | Coverage |
| --- | --- |
| 요청 유형 | 명확한 Answer-only<br>명확한 Write<br>복합 요청 |
| 입력·모호성 | RESOURCE_SELECTED<br>인물·기간·대상 Resource 모호성<br>제약 누락 위험 |
| 질문·범위·표현 | 불필요한 확인 질문<br>범위 밖·금지 요청<br>Paraphrase·혼합 언어 |

### 13.2 Tool Route

| 범주 | Coverage |
| --- | --- |
| Route·입력 | 단일·복수 IN Route<br>단일·복수 OUT Route<br>ANSWER vs ACTION<br>RESOURCE_SELECTED Resource 고정 |
| Tool 선택·Binding | READ / CREATE / UPDATE / SEND / DELETE Effect<br>Registered Tool Binding<br>후보 1개 deterministic auto-select<br>후보 복수 registered-candidate selection |
| 검증·결과 | Forbidden Route·Tool 배제<br>Unregistered Tool 0<br>Resource·Effect·Tool Schema 일치<br>NEEDS_CONFIRMATION<br>BLOCKED |

### 13.3 Retrieval

| 범주 | Coverage |
| --- | --- |
| Query·직접 조회 | 고정 IN Route 안 Query 계획<br>allowed_read_tool_ids 밖 호출 0<br>RESOURCE_SELECTED 직접 GET<br>날짜·사람·이메일·상태 제약<br>Query 과대·과소·동일 Search 반복 금지 |
| 추가 수집·근거 선택 | 정상 Pagination·Detail Fetch<br>Round 1·2 Additional Retrieval<br>Run-scoped RAG Required Segment Recall<br>Required Evidence 선택<br>Hard Negative 배제<br>최신 합의 선택 |
| 품질·불확실성 | 상충 Evidence<br>긴 Thread·서명·인용 Noise<br>저신뢰 후보<br>NEEDS_MORE_DATA |
| 종료·안전·예산 | NEEDS_CONFIRMATION<br>PARTIAL<br>BLOCKED<br>Prompt Injection<br>Context Budget |

### 13.4 Work Analysis

| 범주 | Coverage |
| --- | --- |
| 관계·업무 | 담당·일정 연결<br>누락 업무<br>Task·Event 중복<br>가용성·충돌 |
| 근거·추가 정보 | 상충 Evidence<br>부분 Source<br>Evidence 없는 추론 차단<br>NEEDS_MORE_DATA<br>NEEDS_CONFIRMATION |

### 13.5 Planning

| 범주 | Coverage |
| --- | --- |
| 결과·Action 구성 | ANSWER_ONLY<br>단일 CREATE<br>단일 UPDATE<br>복합 DAG<br>부분 승인 |
| 근거·대상·제한 | Evidence 연결<br>CREATE·UPDATE Target 규칙<br>불필요 Action 차단<br>금지 Tool 차단 |
| 전환 | 확인 질문 전환<br>BLOCK 전환 |

### 13.6 Review

| 범주 | Coverage |
| --- | --- |
| 결과 | 정상 PASS<br>REVISE<br>RETRIEVE_MORE<br>CONFIRM<br>BLOCK |
| 오류·재검사 | False PASS<br>False Block<br>오류 위치 특정<br>Revision 후 Recheck<br>동일 실패 반복 종료 |

## 14. Capability completeness contract

- 각 Agent가 소유하는 current Result/Disposition vocabulary는 06의 runtime topology와 exact match한다.
- LLM-retryable Failure는 bounded Repair/Revision 경로와 `retry_kind`가 정의되어야 한다.
- Non-retryable Failure는 deterministic Redirection/Stop/Recovery owner가 정의되어야 한다.
- 같은 failure signature의 무한 반복은 금지하고 budget 종료가 결정적이어야 한다.
- Over-confirmation·Overblocking을 막기 위해 정상 PASS/CONTINUE 경계와 CONFIRM/BLOCK 경계를 모두 정의한다.
- Answer-only, compatibility READ-only, WRITE, Additional Retrieval, Confirmation, Approval, Reauth, Recovery의 Prompt/Failure 책임은 각각 owning workflow/domain contract를 침범하지 않는다.
- 실제 Dataset coverage 수량·DEV/HOLDOUT split·trial 반복성은 `13 Evaluation`이 검증한다.

## 15. Prompt release activation boundary

Dataset·Grader·scoring·Candidate 비교와 release evidence는 `13 Evaluation`이 소유한다. 본 문서는 그 결과를 받아 **이미 정의된 PromptRef/manifest/input/failure contract의 activation 상태를 결정하는 경계**만 제공한다.

- Evaluation 결과가 새 Prompt field, failure code, retry path, Agent capability를 직접 생성할 수 없다. 그런 Runtime 의미가 필요하면 먼저 owning 06/15 contract를 수정한다.
- Prompt artifact가 활성화되더라도 Product Prompt는 Gold/Grader/score/expected route/end-state를 입력으로 받지 않는다.
- Prompt Registry는 current manifest/source/input-contract set과 일치하는 artifact만 activation 대상으로 취급한다.

## 16. Trace·Artifact Contract

Trace 추가 필드:

```
failure_reason_codes
failure_origin
detected_by
runtime_disposition
retry_kind
attempt_no
previous_llm_call_id
validator_codes
changed_field_paths
stop_reason
query_attempt_id
budget_profile
```

저장 금지:

```
실제 사용자 Prompt 원문
Google 원문 전체
Prompt Template 원문
LLM Completion 원문
Credential
Holdout Gold 원문
```

## 17. Clarification Capability

`detect_ambiguity` candidate는 `missing_information_owner=NONE | USER | CONNECTOR`를 출력하며 USER branch만 Confirmation을 허용한다.

- 모호성은 기본 BLOCK이 아니라 `NEEDS_CONFIRMATION → ConfirmationRequiredV1 → RequestConfirmation → same-owner interrupt/resume`다.
- 후보가 있으면 후보·차이·선택지를 제공하고, 후보가 없으면 최소 누락 정보만 질문한다.
- `처리/진행/시작/정리/마무리`는 문맥으로 의미가 단일하면 질문하지 않는다.
- `답장/회신/보내줘`는 SEND 의도이며 Draft ambiguity가 아니다.
- 요청/검색/분석 중 실제 모호성이 관측된 단계에서 Redirection한다.

## 18. Attachment Capability 경계

- Gmail 첨부파일 I/O는 Agent Semantic Capability가 아니다.
- Product Prompt에 첨부파일 bytes·파일 내용·Local Path를 넣지 않는다.
- Agent는 필요 시 파일명·MIME Type·크기·Attachment Descriptor만 사용한다.
- Download/Stage/Hash Verification/MIME 조립/Claim V2 검증 실패는 `DETERMINISTIC` 또는 `TERMINAL` Runtime 처리이며 LLM Repair·Semantic Revision 대상으로 바꾸지 않는다.
- Claim V2와 Attachment integrity는 제품 Runtime 안전 계약이므로 Agent Profile 실험의 독립변수로 변경하지 않는다.
