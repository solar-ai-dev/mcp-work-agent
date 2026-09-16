# 05. Context · Retrieval 설계서

> **Authority:** Context·Retrieval의 Query·Evidence·coverage 의미. Tool Route·Workflow·Domain의 전문 계약은 해당 owner를 따른다.  
> **상태:** Draft v2.20 · **기준일:** 2026-09-07 · **대상:** P0 MVP

## 1. 목적

확정된 Connector Input Route에서 필요한 자료를 최소 호출로 수집하고, 관련 Segment를 검색·정렬하여 **다음 단계에 필요한 Evidence만 선별**한다. 가져온 후보 전체를 다음 LLM에 전달하지 않는다.

현재 범위는 Google Workspace의 Gmail·Tasks·Calendar와 GitHub Issue다. 각 Connector의 frozen Route와 allowlist를 보존하며, Run-scoped Retrieval/Reranking을 기본으로 한다. 영구 Vector Index는 P0 필수가 아니다.

이 문서는 검색 제약, 근거 선택, 부족 정보와 조회 범위를 정한다. Graph 구성, Repository 규칙, 평가 프로그램을 새로 정의하지 않는다.

## 2. 확정 결정

| ID | 결정 |
| --- | --- |
| `CTX-001` | 요청 시점에 Connector 원본을 연합 검색한다. |
| `CTX-002` | IN/OUT Tool Route 선택은 Retrieval 이전 Tool Route Subgraph가 소유한다. |
| `CTX-003` | 고정된 `input_routes`만 사용한다. `required=true`인 Policy Precondition Route를 임의 생략하지 않는다. 사용자 범위 밖 필수 조회는 Tool Route의 `SCOPE_EXPANSION_REQUIRED` Confirmation 이후에만 확정할 수 있다. |
| `CTX-004` | LLM이 Raw Query·Page Token·MCP Arguments를 직접 실행하지 않는다. |
| `CTX-005` | 검색 계획, 결정적 조회, 자료 정규화, RAG, Evidence 선택, 충분성 판정을 구분한다. |
| `CTX-006` | 후보 전체를 Work Analysis·Planning Prompt에 직접 전달하지 않는다. |
| `CTX-007` | 최초 Retrieval 이후 같은 IN Route 안의 추가 Retrieval은 최대 2회다. |
| `CTX-007A` | Raw continuation은 Run Retrieval Cache의 read-result entry만 memory-only로 소유한다. Local State는 `read_result_handle`로 참조한다. |
| `CTX-007B` | Follow-up 계획은 이전 시도·미해결 Issue·제한된 조회 요약을 소비한다. Raw Page Token·Provider Query·MCP Arguments는 Prompt에 넣지 않는다. |
| `CTX-007C` | `NEXT_PAGE`는 handle의 Run·Route·query binding을 검증한 뒤 결정적 코드가 continuation을 주입한다. |
| `CTX-007D` | 같은 Query·같은 continuation 상태의 반복은 새 Round가 아니다. 새 정보를 얻을 가능성이 있는 조회만 허용한다. |
| `CTX-008` | 새 Resource/Connector Route가 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`를 Parent에 반환한다. |
| `CTX-009` | 일반 Retrieval은 Action Row가 아니라 Trace·Checkpoint·Run Cache 대상이다. |
| `CTX-010` | RAG는 구조적 필수 단계다. Backend 구성은 교체 가능하며 활성 구성은 평가 결과와 Release Config로 결정한다. |

## 3. 전체 흐름

```text
확정된 RequestIntent와 Input Route
→ 검색 계획 · 결정적 Query 구성과 MCP Read
→ 자료 정규화 · Segment 검색/정렬
→ Evidence 선택 · 충분성 판정
→ 공식 RetrievalResult 반환
```

이 흐름은 필요한 책임을 나타내며 LangGraph의 Node 수나 세부 Edge를 고정하지 않는다. 아래 operation 이름과 책임은 유지하고, Workflow 연결은 `06 Agent·Workflow`, 배치·네이밍은 `16 Repository Architecture`를 따른다.

Main Graph에는 Query 후보·Page Token·전체 후보·RAG score를 올리지 않는다.

## 4. Retrieval Subgraph State

현재 State의 필드 표기는 다음과 같다.

```python
class RetrievalState:
    request_intent: RequestIntentV2
    input_route_ref: StateArtifactRefV1
    input_routes: list[InputToolRouteV1]
    query_plan: RetrievalQueryPlanV2 | None
    query_attempts: list[QueryAttemptV1]
    source_statuses: list[SourceRetrievalStatusV1]
    read_result_handles: list[str]
    segment_handles: list[str]
    availability_results: list[AvailableIntervalV1]
    rag_candidates: list[RagCandidateV1]
    exclusion_obligation_segment_ids: list[str]
    pending_user_retrieval_need: RetrievalNeedV1 | None
    evidence_selection: EvidenceSelectionResultV2 | None
    sufficiency: SufficiencyResultV2 | None
    final_result: RetrievalResultV1 | None
```

| 구분 | 처리 |
| --- | --- |
| Parent 입력 | `request_intent`, `input_route_ref`, `input_routes`는 read-only다. 현재 Run의 `user_request`는 typed intent의 의미 손실을 보완하는 Prompt 입력으로 함께 읽되, 별도 State·장기 권위·정책 사실로 저장하거나 승격하지 않는다. |
| Local 작업 상태 | Query 계획·시도, Source 상태, 조회·Segment handle, 가용 시간, RAG 후보, 사용자 조정 의무를 보존한다. |
| Cache 참조 | `read_result_handles`는 현재 Run의 read-result entry를 가리킨다. Entry는 `run_id + route_id + query_identity_hash`, 제한된 `ConnectorReadResultV1`, continuation 소진 상태를 결합한다. |
| 사용자 조정 | `07 Interface`가 검증한 `ContextAdjustmentV1` 한 개만 재진입 입력으로 받는다. 아래 §4.2~4.3의 같은 Run 의무로 처리하며 다른 Agent의 장기 업무 사실로 전파하지 않는다. |
| 공식 반환 | Parent에는 `RetrievalResultV1`과 필요한 Typed Workflow Signal만 반환한다. |

실제 Connector 원문과 raw continuation은 Run Retrieval Cache Handle로 참조한다. Main State·Checkpoint·Prompt·Trace·Audit·Domain DB에 원문이나 raw continuation을 복제하지 않는다.

Context Adjustment 뒤에는 새 Retrieval revision을 발급한다. 이전 revision을 `meta.based_on`으로 참조한 `WorkAnalysisResultV2`·Plan·Review는 stale이며 재사용하지 않는다. 현재 IN Route로 해결할 수 없으면 기존 `RouteReconsiderationRequiredV1` 경로를 사용한다.

### 4.1 Cache 유실과 재시작

Process 재시작 뒤 handle이 유효하지 않으면 **추측 복원이나 재사용 없이 같은 Run의 Retrieval을 다시 시작**한다.

```text
RETRIEVING checkpoint load
→ required read_result_handle resolve
→ missing/cross-run/query-binding mismatch
→ current local QueryAttemptV1/read-result/segment handles 폐기
→ durable handoff control = RETRIEVAL_CACHE_RESTART
→ MAIN_CONTROL:RETRIEVAL_ENTRY
→ frozen RequestIntentV2 + current InputRoutePlanV1에서 fresh read 시작
→ 새 RetrievalResultV1 revision 발급
```

`RunRetrievalCacheResolveResultV1.status`는 다음처럼 해석한다.

| Cache resolve 상태 | 의미와 처리 |
| --- | --- |
| `FOUND` | Entry와 Run·Route·query binding이 유효하다. Resume dependency를 충족한다. |
| `EXHAUSTED` | 유효한 entry의 `continuation_exhausted=true` 상태다. Restart하지 않고 `NEXT_PAGE`만 `NO_MORE_PAGE`로 종료한다. Provider 호출은 0이다. |
| `MISSING`, `CROSS_RUN`, `BINDING_MISMATCH` | Cache-loss restart 대상이다. |
| Request·Route·checkpoint 계약 자체가 stale | Cache restart로 우회하지 않고 기존 `CHECKPOINT_MISMATCH` 또는 `CONTRACT_VIOLATION` Recovery를 사용한다. |

재시작 시 처리:

- Raw `next_page_token`과 이전 memory-only cache는 복원하지 않는다. Provider 자료가 바뀌었으면 새 조회 결과가 current revision의 기준이다.
- 이미 소비한 `RunBudgetV2`의 LLM·read·page·detail counter는 초기화하지 않는다. 새 호출도 기존 상한 안에서 추가 소비한다.
- 사용자 제외 의무와 추가 검색 요구는 보존한다. Lifetime은 §4.2~4.3을 따른다.
- Frozen Request·Route와 checkpoint binding이 유효한 cache-loss restart는 Workflow-local 처리이며 새 `RecoveryReasonV1`을 만들지 않는다.

**Checkpoint dependency**

Checkpointer adapter는 필요한 handle만 `GraphCheckpointEnvelopeV1.retrieval_cache_requirements: list[RetrievalCacheRequirementV1]`로 투영한다. Application은 이 metadata만 검사하고 opaque `checkpoint_blob`을 열지 않는다.

Handle dependency가 끝나면 빈 목록을 저장한다. Confirmation/Reauth가 Retrieval-local continuation으로 돌아오는 동안에는 requirement를 유지하고, resume 전에 같은 handle 검증을 수행한다. 필요한 cache가 사라졌으면 `MAIN_CONTROL:RETRIEVAL_ENTRY`로 재시작한다.

**재시작 중복 방지와 실행 소유권**

| 항목 | 계약 |
| --- | --- |
| Trigger | `system:retrieval-cache-restart:<run_id>:<checkpoint_generation>` 하나를 사용한다. |
| 중복 판정 | Stage 전에 `WorkflowHandoffRepository.get_by_trigger_command_id(trigger)`로 기존 `PENDING`, `DISPATCHED`, `CONSUMED` row를 확인한다. 같은 trigger에 두 번째 handoff/control을 만들지 않는다. HTTP command replay 계약과 혼용하지 않는다. |
| Application owner | `run.reconcile_retrieval_cache_restart → ReconcileRetrievalCacheRestartHandler`만 dependency 검사와 restart stage를 수행한다. |
| Stage·실행 | Invalid/missing dependency이면 trigger를 dedupe하고 `WorkflowHandoffStageV1(control_kind=RETRIEVAL_CACHE_RESTART, target=MAIN_CONTROL:RETRIEVAL_ENTRY)`를 short UoW로 stage한 뒤 `run.schedule_run_execution`을 호출한다. |
| 금지 | LangGraph Node·Background adapter는 Repository를 직접 쓰지 않는다. |

Run Retrieval Cache 경계는 `RunRetrievalCachePort` 하나다. P0 binding은 `adapters/system/memory/run_retrieval_cache.py → InMemoryRunRetrievalCache`이며, `retrieval.execute_read`가 entry 저장·resolve를 사용한다. Terminal cleanup은 `discard_run(run_id)`만 호출한다. Module-global dict, LangGraph private cache, Domain/Checkpoint의 raw continuation 저장을 두 번째 권위로 만들지 않는다.

### 4.2 사용자 Evidence 제외 의무

`EXCLUDE_EVIDENCE`는 Application이 `expected_retrieval_revision`과 current Preview membership을 검증한 stable `segment_id`에만 적용한다. 검증된 ID를 `RetrievalState.exclusion_obligation_segment_ids`에 넣고, **handoff payload를 clear하기 전에 checkpoint에 commit**한다.

| 시점 | 유지·반영 규칙 |
| --- | --- |
| 새 결과 확정 전 | 같은 Run의 Retrieval lineage에서 crash-safe하게 의무를 보존한다. |
| Cache-loss fresh Retrieval | Checkpoint-local 제외 ID와 current `RetrievalResultV1.excluded_segment_ids`를 합쳐 selection에 적용한다. |
| 공식 결과 확정 | Selection의 제외 ID와 사용자 제외 의무를 stable dedup하여 결과에 남긴다. |
| 이후 추가 검색·재진입 | 공식 결과의 제외 ID를 Local State 초기 projection으로 사용한다. |
| Route reconsideration | 같은 stable ID가 다시 나타나면 제외한다. |
| Source 내용·version·chunk schema 변경 | 새 ID에 과거 제외를 fuzzy text matching으로 자동 승계하지 않는다. ID 의미는 §10.1을 따른다. |

One-shot handoff payload 자체를 장기 권위로 사용하지 않는다.

### 4.3 사용자 추가 검색 요구의 수명

`RETRIEVE_MORE`는 검증된 `ContextAdjustmentV1.retrieval_need`를 `RetrievalState.pending_user_retrieval_need`에 저장한다. 값은 `RetrievalNeedV1(reason_codes=[USER_CONTEXT_ADJUSTMENT])`다. **같은 control-patch checkpoint의 commit 이후에만 handoff payload를 clear**한다.

| 시점 | 유지·해제 규칙 |
| --- | --- |
| Query Planner 입력 | Raw `ContextAdjustmentV1` 대신 `pending_user_retrieval_need`를 읽는다. |
| Query·Page·Detail 반복, Confirmation/Reauth | 같은 need를 보존한다. |
| Cache 유실·restart, handoff `CONSUMED` 이후 | Need를 잃지 않고 fresh Retrieval에 적용한다. |
| Route reconsideration·재진입 | 새 Route가 확정돼 fresh 결과가 finalize될 때까지 보존한다. |
| 새 결과 확정 | 새 `RetrievalResultV1` revision과 `pending_user_retrieval_need=None`을 같은 checkpoint에 commit한다. 확정 전 crash는 요구를 잃지 않고, 확정 후 crash는 같은 요구를 다시 적용하지 않는다. |
| 다음 Context Adjustment | Expected retrieval revision 검증을 통과한 경우에만 새 need를 설정한다. Stale 요청은 기존 의무를 덮지 못한다. |

## 5. Retrieval 내부 책임

Operation별 책임은 유지하되 검색 전략이나 Graph 세부 순서를 영구 고정하지 않는다.

### 5.1 `retrieval.plan_query`

허용된 IN Route 안에서 무엇을 찾고 어떤 Page·후보·상세 조회가 필요한지 제안한다. 사용자 제약과 Policy Precondition의 필수 조회 목적을 보존한다.

**입력**

```
# 모든 Round
user_request
request_intent
input_routes
required_user_anchors
retrieval_budget

# 검증된 Calendar 기간을 route에 결합할 수 있을 때만
required_route_constraints

# Follow-up Round에서만 추가되는 bounded Local Projection
current_round_no
prior_query_attempts
unresolved_sufficiency_issues
read_result_summaries
```

`read_result_summaries`에는 handle, Route·query identity/hash, 확인한 Resource 참조의 제한된 요약, `has_next_page`, continuation state hash만 포함한다. Raw `next_page_token`은 포함하지 않는다.

Follow-up의 prior attempt projection은 semantic constraint·operation·reason·결과 수·stop reason·query hash만 사용한다. 원본 `QueryAttemptV1.query_spec`는 Builder·관측용이며 LLM 입력이 아니다. 사용자 Context Adjustment 입력은 §4.3을 따른다.

**소비하는 요청 의미**

| 항목 | Retrieval에서 지킬 의미 |
| --- | --- |
| 요청 해석 | 사람·기간·시간축·업무 개념·필요 정보는 Request Understanding의 typed 결과를 소비한다. 일반 코드가 키워드·이름/직급·문장 패턴으로 의미를 추가하거나 교체하지 않는다. |
| 검색어·업무 개념 | `search_terms`, `business_concepts`, `required_information`은 `USER_REQUIREMENT`로 검증된 값을 사용한다. `SCOPE.search_terms`도 원문 anchor로 소비한다. |
| 검색 필드 누락 | Typed intent에 원 요청이 남아 있으면 bounded KEYWORD 발견을 막지 않는다. 누락을 exact identity·기간·상태의 근거로 삼지는 않는다. |
| 기간·시간축 | 원문 기간 `DATE.period`와 의미 역할 `TIME.temporal_axis`를 구분한다. Gmail-only 기간 검색은 시간축을 함께 사용하며 키워드·정규식으로 덮어쓰지 않는다. |
| 추가 명시 제약 | Calendar 값·GitHub repository 등은 Request Understanding이 정규화한 단일 `ConstraintV1` 목록을 소비한다. 검색 슬롯·`additional_constraints`를 별도 요청 권위로 만들지 않는다. |
| 형식 검증 | 빈 날짜·상태 placeholder는 제약이 아니다. Temporal 입력은 유효한 local boundary가 하나 이상 있어야 한다. 형식으로 확정되는 명시 인용 제목·상대 기간·원 요청 anchor는 보존한다. |
| 제목·수식어 | 명시적으로 `제목`/`subject`로 표시한 인용 문자열을 보존한다. 사용 방식의 수식어를 제목·업무 anchor로 승격하거나 '메일 앞 단어' 정규식·업무 단어 사전으로 대체하지 않는다. |
| Gmail 상태 | 현재 지원하는 명시적 `ANY`, `DRAFT`, `SENT`만 사용한다. 다른 Resource의 `OPEN` 등으로 메일 상태 필터를 만들지 않는다. |

**Exact anchor와 검색 가설**

`required_user_anchors`는 `RequestIntentV2`의 명시 검색 필드 중 current-run
`USER_REQUEST | CONFIRMATION_RESPONSE` provenance가 검증된 값과 이를 소비할 Gmail route만
투영한다. `business_concepts`, 시스템 유래 값, 정규식·사전 추측으로 새 anchor를 만들지
않는다. 이 projection은 새 요청 권위가 아니라 기존 typed 의미의 bounded 전달 형식이다.

`required_route_constraints`는 검증된 단일 기간을 Calendar event/availability route에
해석할 수 있을 때만 만든다. 해당 초기 route의 temporal constraint와 이미 존재하는 route
policy의 required constraint를 동적 output schema에 결합하며, 값이 없으면 빈 projection을
모든 호출에 추가하지 않는다.

`CONCEPT(concept, manifestations)`는 사용자 `business_concepts`에 결합된 탐색 가설이다. 고정 동의어 목록이나 사용자 사실을 뜻하지 않는다.

| 항목 | 계획 규칙 |
| --- | --- |
| 가설 구성 | `RouteQueryIntentV2`의 operation·semantic constraints·`reason_codes`와 계획의 `required_information`으로 검색 목적·부족 정보·성공 조건을 표현한다. |
| Manifestation | 새 출력은 Provider syntax 없는 서로 다른 표현을 한 검색에 1~3개 사용한다. V2 artifact의 12개 상한은 읽기 호환용이며 기존 query/hash를 잘라 재해석하지 않는다. |
| 복합 개념 | 한 가설에는 `CONCEPT` 하나만 허용한다. 그중 한 개념을 후보 발견 축으로 삼을 수 있지만 모든 요청 개념은 Evidence·Sufficiency 검증 의무에 남는다. |
| 확장 여부 | 원문 표현만 사용했다는 이유로 확장어를 강제하지 않는다. 확장 표현은 현재 요청과 실제 관측을 바탕으로 Planner가 선택한다. |
| 후속 가설 | 같은 Route의 성공한 검색 관측과 미해결 Issue에 근거한다. 실패를 정상 0건 관측으로 보지 않는다. |
| 날짜를 발견 단서로 사용 | `EVENT_TIME` 후보 부재를 관측한 경우, 원래 concept/window를 유지하며 본문 날짜 언급을 다음 가설로 사용할 수 있다. 날짜 표기·검색어를 코드의 고정 목록으로 공급하지 않는다. |
| 사실 판정 | Concept match나 날짜 언급은 발견 신호다. 실제 관련성과 사건·날짜는 상세 Evidence로 확인한다. |
| 금지 | 복합 개념의 무조건 AND, 요청 제약 삭제, 고정 불용 업무 단어 제거, 자동 `ALL→ANY` 완화, 날짜 문자열만의 자동 fallback. |

사용자 요구 개념이 빠지면 `QUERY_USER_CONSTRAINT_MISSING`으로 구분한다. Bounded semantic revision에는 원래 모델 출력 후보만 전달하며 Application이 복원한 anchor·기간·container를 모델 출력으로 위조하지 않는다. 수정 후 동일 binding과 validator를 적용한다.

**출력 계약**

```python
class TemporalRangeConstraintV1:
    kind: Literal["TEMPORAL_RANGE"]
    axis: Literal["MESSAGE_TIME", "TASK_SCHEDULED_DATE", "EVENT_TIME", "AVAILABILITY_WINDOW"]
    start_local: str | None
    end_local: str | None
    timezone: str

class ParticipantMatchV1:
    role: Literal["ANY", "SENDER", "RECIPIENT", "ATTENDEE"]
    identity: str

class ParticipantConstraintV1:
    kind: Literal["PARTICIPANT"]
    participants: list[ParticipantMatchV1]
    match_mode: Literal["ANY", "ALL"]

class KeywordConstraintV1:
    kind: Literal["KEYWORD"]
    terms: list[str]
    match_mode: Literal["ANY", "ALL", "PHRASE"]

class ResourceRefConstraintV1:
    kind: Literal["RESOURCE_REF"]
    resource_refs: list[str]

class ContainerRefConstraintV1:
    kind: Literal["CONTAINER_REF"]
    container_refs: list[str]

class StatusScopeConstraintV1:
    kind: Literal["STATUS_SCOPE"]
    values: list[Literal["ANY", "INCOMPLETE", "COMPLETED", "DRAFT", "SENT", "CANCELLED", "CONFIRMED", "TENTATIVE"]]

SemanticRetrievalConstraintV1 = (
    TemporalRangeConstraintV1
    | ParticipantConstraintV1
    | KeywordConstraintV1
    | ResourceRefConstraintV1
    | ContainerRefConstraintV1
    | StatusScopeConstraintV1
)

RetrievalConstraintKindV1 = Literal[
    "TEMPORAL_RANGE", "PARTICIPANT", "KEYWORD",
    "RESOURCE_REF", "CONTAINER_REF", "STATUS_SCOPE"
]

class ConstraintDeltaV2:
    upsert_constraints: list[SemanticRetrievalConstraintV1]
    remove_constraint_kinds: list[RetrievalConstraintKindV1]

class InitialSearchSpecV1:
    mode: Literal["INITIAL"]
    constraints: list[SemanticRetrievalConstraintV1]

class ChangedSearchSpecV1:
    mode: Literal["CHANGED"]
    constraint_delta: ConstraintDeltaV2

SearchConstraintSpecV1 = InitialSearchSpecV1 | ChangedSearchSpecV1

class RouteQueryIntentV2:
    route_id: str
    operation: Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]
    reason_codes: list[str]
    search_spec: SearchConstraintSpecV1 | None
    detail_candidate_ref: str | None

class RetrievalQueryPlanV2:
    schema_version: Literal[2]
    route_queries: list[RouteQueryIntentV2]
    required_information: list[str]
    retrieval_order: list[str]
```

`operation`이 유효 branch를 결정한다.

| Operation | `search_spec` | `detail_candidate_ref` |
| --- | --- | --- |
| `SEARCH`, `FREEBUSY` | 필수 | `None` |
| `DETAIL_FETCH` | `None` | 현재 Run의 검증된 exact selected-resource ref 또는 bounded candidate ref. Non-empty 필수. |
| `NEXT_PAGE` | `None` | `None`. Raw continuation은 Cache가 소유한다. |

Branch 필드를 섞으면 Provider 호출 전에 `QUERY_OPERATION_FIELD_MISMATCH`로 차단하거나 bounded revision한다.

**결정적으로 만들 수 있는 초기 계획**

| 적용 조건 | 처리 | 적용하지 않는 경우 |
| --- | --- | --- |
| `RESOURCE_SELECTED`, frozen IN Route 1개, Registry exact detail READ Tool 1개, current-Run 검증 Resource ref 1개 | `plan_query` LLM 없이 `DETAIL_FETCH` 계획을 만들고 동일 validator를 통과시킨다. | 복수 Route/ref, 일반 검색, follow-up |
| 정확한 `TASK + CREATE`, 제목·Policy-required `TASK \| TASK_LIST` Route·allowlist 안의 명시적 Task List ref가 각각 하나로 고정 | 중복 확인용 초기 `SEARCH + CONTAINER_REF`를 결정적으로 만든다. 실제 Tasks READ와 Work Analysis 중복 판정은 유지한다. | 복수 Task List, 미결정 target, 일반 Task 검색, 추가 사용자 제약, follow-up |

Planner는 새 Connector/Resource Route, OUT Tool 또는 Write를 선택하지 않는다. Provider-native Raw Query·시간 형식·Page Token을 만들어 바로 실행하지 않는다. Gmail Query·RFC3339는 결정적 Builder의 책임이다.

### 5.2 `retrieval.build_query`

의미 계획을 검증하고 실제 Read 인자로 바꾸는 결정적 Application 책임이다.

```
RetrievalQueryPlanV2 + InputToolRouteV1
→ RouteQueryIntentV2 semantic validation
→ INITIAL SEARCH: InitialSearchSpecV1.constraints를 effective constraints로 확정
→ CHANGED SEARCH: prior effective constraints + ConstraintDeltaV2를 결정적으로 merge
→ SourceFetchPlanBuilder → SourceFetchPlanV1
→ Source별 typed query / ValidatedReadQuerySpecV1
→ 날짜·이메일·Resource ID·지원 constraint 검증
→ NEXT_PAGE이면 prior read_result_handle resolve + continuation binding 검증
→ opaque Page Token을 결정적 코드가 주입
→ MCP Read Arguments
```

`NEXT_PAGE`에서 LLM은 Page Token을 생성·복사·수정하지 않는다. Handle의 Run·Route·query binding 불일치 또는 continuation 소진은 Provider 호출 전에 차단한다. 상세 pagination 규칙은 §16.2를 따른다.

### 5.2-A Semantic Constraint · changed SEARCH · `SourceFetchPlanV1`

`SEARCH`의 LLM 출력은 **값을 가진 typed semantic constraint**다. Provider Query, RFC3339 변환, MCP Arguments, raw continuation은 결정적 Builder/Executor가 소유한다.

```python
class SourceFetchPlanV1:
    schema_version: Literal[1]
    route_id: str
    connector_id: str
    resource_type: str  # exact connector resource_type copied from the frozen InputToolRouteV1 / SignedToolRegistryEntryV1
    operation_kind: Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]
    effective_constraints: list[SemanticRetrievalConstraintV1]
    query_identity_hash: str
    prior_read_result_handle: str | None
    detail_candidate_ref: str | None
```

#### Initial SEARCH

```
InitialSearchSpecV1.constraints
→ route 지원 constraint 검증
→ normalized effective constraints
→ SourceFetchPlanV1
```

| 항목 | 검증 규칙 |
| --- | --- |
| Constraint | 이름만 나열하거나 Provider-native Query 문자열을 반환하면 invalid contract다. |
| `resource_type` | Frozen `InputToolRouteV1.resource_type`을 그대로 복사한다. 선택·허용된 `SignedToolRegistryEntryV1.resource_type`과 exact match해야 한다. |
| 허용 Tool 집합 | 한 Route의 `allowed_read_tool_ids`는 모두 같은 Registry `resource_type`을 가져야 한다. 다른 Resource는 별도 Input Route가 필요하다. |
| 금지 | `EMAIL \| TASK \| CALENDAR` 같은 별도 family로 identity를 변환하거나 Tool 이름 parsing·local 문자열 mapper로 재해석하지 않는다. |

#### CHANGED SEARCH

```
prior SourceFetchPlanV1.effective_constraints
+ ConstraintDeltaV2.upsert_constraints
- ConstraintDeltaV2.remove_constraint_kinds
→ deterministic normalize / conflict check
→ next effective constraints
→ new query_identity_hash
→ SourceFetchPlanV1
```

**변경 가능한 것과 보존할 것**

| 항목 | 규칙 |
| --- | --- |
| 변경 범위 | 같은 frozen `route_id`의 검색 제약만 변경한다. Connector·Resource·Tool 재선택이 아니다. |
| Upsert | `kind`별 기존 값을 교체하거나 추가한다. 같은 Route의 effective set에 동일 `kind`를 중복 보유하지 않는다. |
| Remove | 해당 `kind` 전체를 제거한다. Frozen Route·Policy Precondition의 필수 constraint는 제거하지 못한다. |
| 사용자 제약 | Temporal role/window, resource/container identity, 상태, 확정 participant, lexical anchor를 보존한다. |
| 보호 제약 변경 | Follow-up이 provenance-validated 상태·identity·lexical anchor를 제거하거나 다른 역할로 바꾸면 `QUERY_PROTECTED_CONSTRAINT_CHANGED`로 차단하고 구체 affected path를 Trace에 보존한다. |
| Concept | 같은 concept 안에서 manifestation만 변경한다. |
| 인물 탐색어 전환 | 이름 discovery KEYWORD를 제거하려면 current-Run typed person candidate의 유일한 identity 또는 검증된 Confirmation 선택과 일치하는 exact PARTICIPANT로 전환해야 한다. LLM reason code만으로 허용하지 않는다. |
| 무변경 | Merge 뒤 의미가 같으면 `QUERY_UNCHANGED_AFTER_FAILURE`로 차단한다. 새 Round로 인정하지 않는다. |

**호출 전 검증**

| 항목 | 규칙 |
| --- | --- |
| Delta 충돌 | 같은 `kind`를 동시에 upsert/remove하거나 지원하지 않는 constraint·값 없는 constraint·모순 시간 범위를 반환하면 차단한다. |
| Local 시간 | `start_local/end_local`은 offset 없는 ISO local date 또는 local datetime이다. 제품 timezone은 `Asia/Seoul`이다. 파싱·Timezone·interval 계산·Provider 변환은 결정적 코드가 수행하며 invalid/ambiguous 값은 차단한다. |
| Participant | 역할별 identity를 유지한다. `from A + to B`도 하나의 constraint 안에서 구분한다. |
| Resource·Container | `resource_refs`와 `container_refs`는 현재 Run/Route에서 검증된 ref만 허용한다. LLM이 raw Provider ID를 발명하지 않는다. |
| Gmail lexical lowering | 각 KEYWORD를 literal quote로 묶어 Provider operator 실행을 막는다. 지원하지 않는 quote/backslash/control delimiter는 호출 전에 차단한다. |
| Query identity | 같은 semantic constraints로 이미 수행한 검색은 lowering 표현이 달라도 반복으로 차단한다. Checkpoint 재진입이 새 검색 기회가 되지 않는다. |
| Attempt 기록 | Gmail lexical lowering의 retrieval config v3를 기록하되 과거 attempt/query는 수정하지 않는다. |
| 관측 필드 | `QueryAttemptV1.added_constraints/removed_constraints`는 이름 목록 요약이다. 다음 계획의 값 권위나 effective constraints를 복원하는 두 번째 source가 아니다. |

#### GitHub repository container authority

`connector_id="github"`, `resource_type="github_issue"`인 frozen Route의 container는 다음 current-Run source만 사용한다.

| 허용 source | 값 |
| --- | --- |
| 검증된 `SelectedResourceRefV1`/`ResourceRef` | `parent_resource_id` |
| `06 Workflow`의 결정적 provenance 검증을 통과한 `RequestIntentV2` | 명시적 `owner/repository` constraint |

둘이 일치하면 하나의 `ContainerRefConstraintV1(container_refs=["owner/repository"])`로 정규화한다. 불일치하면 임의 우선순위를 적용하지 않고 기존 Confirmation 또는 fail-closed 경로로 보낸다. `ConnectorReadPort` 호출은 0이다.

Repository가 필요한 `SEARCH`인데 검증된 source가 없으면 기존 Confirmation/selection 경로를 사용한다. LLM, 연결 계정, organization, 최근 repository, 첫 검색 결과로 값을 채우지 않으며 Read 호출도 하지 않는다.

결정적 `SourceFetchPlanBuilder`는 container와 frozen Route의 Connector·Resource·`allowed_read_tool_ids`를 그대로 보존하고 등록된 `github_list_issues`의 `repository` 인자로만 lower한다. Selected Issue의 `DETAIL_FETCH`는 `resource_id="owner/repository#issue_number"`와 `parent_resource_id="owner/repository"`의 결합을 유지한다. 새 GitHub Retrieval DTO·Graph·repository authority를 만들지 않는다.

#### Operation별 권위

| Operation | Planner | 결정적 코드 |
| --- | --- | --- |
| `SEARCH` | Semantic constraint 값, reason | Merge·normalize·query identity·Provider query·MCP args |
| `NEXT_PAGE` | 추가 Page 필요성, reason | Handle binding·continuation resolve/injection |
| `DETAIL_FETCH` | Bounded `detail_candidate_ref`, reason | Target/resource/tool binding·MCP args |
| `FREEBUSY` | Semantic 시간 범위, reason | Timezone/RFC3339·interval 계산·MCP args |

현재 Release 계획은 `RetrievalQueryPlanV2 → SourceFetchPlanV1`이다. `RetrievalQueryPlanV1/RouteQueryIntentV1`은 기존 Artifact/테스트의 읽기 호환 범위이며 새 출력에 사용하지 않는다. Name-only delta도 새 실행계획의 권위가 아니다.

### 5.3 `retrieval.execute_read`

| 항목 | 결정적 Read 처리 |
| --- | --- |
| Tool | `input_routes[].allowed_read_tool_ids` 안에서만 호출한다. LLM은 Tool을 다시 선택하지 않는다. |
| 호출 순서 | Registry metadata와 Query Builder가 계획을 실제 Page·Detail·FreeBusy 호출로 변환한다. |
| 조회 결과 | 정규화된 List/Search 결과와 continuation은 Run Retrieval Cache entry에 보관한다. Local State에는 handle과 `QueryAttemptV1` metadata만 기록한다. |
| 다음 Page | 이전 handle을 resolve하되 같은 query·같은 continuation 상태를 반복하지 않는다. |
| 401·429·5xx·Timeout | LLM Repair가 아니라 기존 Retry/Reauth 계약으로 처리한다. |

`NOT_FOUND`와 `PERMISSION_DENIED`는 정상 빈 조회 결과가 아니다.

- Bounded 실행 결과와 Acquisition Source summary에 `FAILED` 및 정규화된 오류를 보존한다.
- 다른 Source의 유효 Evidence/cache와 실패한 QueryAttempt 이력은 유지한다.
- 같은 요청의 검색 반복으로 해결할 수 없는 대상·접근 실패에는 추가 검색을 요구하지 않는다.
- READ는 확인 범위의 `PARTIAL`, 필수 pre-read가 누락된 WRITE는 기존 안전 Guard를 따른다. Credential 만료의 `REAUTH_REQUIRED`는 이 처리와 구분한다.

### 5.4 `retrieval.resolve_availability`

Calendar FreeBusy 또는 Event busy interval이 필요한 요청에서만 가용 시간을 계산한다. Retrieval 내부의 결정적 Application operation이며 별도 Supervisor routing authority나 독립 LangGraph Edge를 만들지 않는다.

```
사용자 시간 제약 + Timezone + busy intervals
→ interval normalization
→ deterministic intersection/subtraction
→ AvailableIntervalV1[]
```

LLM은 `1시간`, `8월 16일 전`, `오후` 같은 의미 제약만 구조화한다. 실제 산술·겹침·차집합 계산은 결정적 코드가 수행하고 결과를 `availability_results`에 둔다. 여러 구간 중 업무상 추천이 필요할 때 Work Analysis가 `AvailableIntervalV1[]`을 소비한다.

### 5.5 `retrieval.normalize_segments`

| 처리 | 내용 |
| --- | --- |
| Gmail | HTML을 안전 텍스트로 변환하고 인용·서명을 제거한다. |
| Tasks·Calendar | 공통 WorkItem/SourceDocument/SourceSegment로 정규화한다. |
| Segment | Chunking·dedup을 수행한다. Identity는 §10.1을 따른다. |
| Source 신뢰 | 모든 Segment에 아래 security metadata를 부여한다. |
| Attachment | Bytes를 제외한다. |

```python
class SourceContentSecurityMetaV1:
    trust_class: Literal["UNTRUSTED_SOURCE_CONTENT"]
    content_role: Literal["DATA_ONLY"]
    instruction_like_content_detected: bool
    sanitization_flags: list[str]
```

`instruction_like_content_detected=false`도 신뢰 승격이 아니다. Source Content는 항상 비신뢰 `DATA_ONLY`이며, 이 필드는 탐지·관측·평가 보조 정보다.

### 5.6 `retrieval.rag_retrieve_rerank`

가져온 Segment를 사용자 요청에 대해 검색·정렬하고, 중복을 제거해 Context Budget 안의 상위 후보를 만든다. Repository/Workflow mapping의 책임 이름은 `rag_retrieve_rerank`로 유지한다.

```python
class RagCandidateV1:
    segment_id: str
    resource_ref: str
    retrieval_score: float
    reason_codes: list[str]
```

Exact match, lexical retrieval, embedding, reranker 등 구체적인 조합과 순위 산정 방식은 교체 가능한 구현 선택이다. 필수 결과는 **관련 후보를 제한된 Context로 선별하는 것**이며, 후보 전체를 다음 LLM에 전달하는 방식은 허용하지 않는다. 점수 설정의 범위는 §9를 따른다.

### 5.7 `retrieval.select_evidence`

입력은 `request_intent + top rag candidates`다. 요청을 뒷받침하거나 반박하는 Segment를 고르며 업무 사실의 최종 해석까지 수행하지 않는다.

```python
class EvidenceDraftV1:
    segment_id: str
    role: Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"]
    relevance_reason: str

class EvidenceSelectionResultV2:
    schema_version: Literal[2]
    evidence_drafts: list[EvidenceDraftV1]
    selected_segment_ids: list[str]
    excluded_segment_ids: list[str]
```

| 후보 상태 | Evidence 처리 |
| --- | --- |
| 본문을 읽은 후보 | 기존 semantic relevance 판정을 사용한다. |
| Gmail 본문 없는 검색 preview | Locator의 `is_metadata_only=true`를 유지한다. 검색 일치 후보이지 확정 업무 근거가 아니다. |
| 아직 본문을 읽지 않은 preview | `CONTEXT`로 유지하고 bounded detail fetch로 관련성을 확인한다. 제목에 핵심 단어가 없다는 이유로 본문 관련성을 부정하지 않는다. |
| 기존 checkpoint의 marker 없는 Evidence | 기존 relevance 판단을 유지한다. |

기존 Gmail Draft의 UPDATE를 준비할 때 원본 필드 snapshot은 Evidence locator나 LLM 입력에 넣지 않는다. Retrieval은 같은 Run의 기존 Evidence 저장 경계에 exact source snapshot을 Resource identity로 보관하고, Planning의 결정적 binder만 이를 해석한다. Provider 응답에서 생략된 필드와 명시적 `null`·빈 문자열·빈 목록은 서로 다른 값으로 보존한다.

`excluded_segment_ids`는 Retrieval의 selection 결과다. Browser가 직접 수정하지 않으며 사용자 제외·추가 검색은 기존 `run.adjust_context → ContextAdjustmentV1`을 통해 같은 Run의 Retrieval에만 전달한다. Browser·Agent의 Main State/Evidence row 직접 변경은 금지한다. 사용자 제외의 수명은 §4.2를 따른다.

### 5.8 `retrieval.assess_sufficiency`

입력은 `request_intent + selected evidence`다. 조회 진행·coverage는 같은 Run의 제한된 read-result summary로 확인한다.

```python
class SufficiencyResultV2:
    schema_version: Literal[2]
    status: Literal[
        "SUFFICIENT", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED", "PARTIAL", "BLOCKED"
    ]
    issues: list[SufficiencyIssueV2]
```

같은 Route의 Query·Page·Detail 추가는 Local Round다. 새 Resource/Connector가 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`를 반환한다. 부족 정보와 결정적 종료 Guard는 §18을 따른다.

**단일 selected GitHub Issue의 결정적 충분성 판정**

| 항목 | 조건 |
| --- | --- |
| 적용 | 분석·사용자 모호성이 없는 단일 Issue의 `UPDATE/CLOSE/REOPEN` |
| 필수 조회 | Exact 대상의 required READ가 `COMPLETE`이고 같은 identity의 Evidence가 확보됨 |
| 변경 값 | 요청한 title/body/state가 현재 값과 다르다는 사실은 Source 누락·충돌이 아님 |
| 제외 | 다른 Source/Output, 부분 조회, 미해결 slot |
| 범위 | Planning 진입을 위한 Source 충분성만 판정. 인자 완전성·target Evidence binding·Review·Approval·실행 admission·Verification을 대체하지 않음 |

### 5.9 `retrieval.finalize_retrieval`

검증된 Local 결과를 공식 Handoff로 조립하는 결정적 책임이다.

```
validated source_statuses
+ selected evidence
+ sufficiency
+ availability_results when applicable
→ RetrievalResultV1
→ final Retrieval disposition
→ optional typed WorkflowSignalV1
```

새 Query·Resource·Connector·Tool을 선택하거나 Evidence를 재판단하고 RAG를 다시 수행하지 않는다. Same-route loop, route reconsideration, confirmation, partial, blocked의 의미를 임의 변경하지 않는다.

Parent에는 공식 `RetrievalResultV1`과 필요한 Typed `WorkflowSignalV1`만 반환한다.

## 6. Parent 반환

```python
class MissingInformationV1:
    code: str
    description: str
    required_for: Literal["RETRIEVAL", "ANALYSIS", "PLANNING", "USER_CONFIRMATION"]

class SourceRetrievalStatusV1:
    route_id: str
    resource_type: str
    status: Literal["COMPLETE", "PARTIAL", "FAILED", "NOT_ATTEMPTED"]
    evidence_refs: list[str]
    failure_kind: Literal[
        "AUTH", "SCOPE", "RATE_LIMIT", "TIMEOUT", "PROVIDER",
        "NOT_FOUND", "BUDGET", "OTHER"
    ] | None

class AvailableIntervalV1:
    start: RFC3339
    end: RFC3339
    timezone: str
    derived_from_resource_refs: list[str]

class RetrievalCollectionItemV1:
    resource_ref: str
    resource_type: str
    title: str | None

class RetrievalCollectionResultV1:
    route_id: str
    resource_type: str
    continuation_status: Literal["EXHAUSTED", "HAS_MORE", "UNKNOWN"]
    items: list[RetrievalCollectionItemV1]

class RetrievalResultV1:
    schema_version: Literal[1]
    meta: StateArtifactMetaV1
    coverage: Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"]
    context_bundle_ref: str | None
    evidence_refs: list[str]
    selected_segment_ids: list[str]
    excluded_segment_ids: list[str]
    source_resource_refs: list[str]
    source_statuses: list[SourceRetrievalStatusV1]
    collection_results: list[RetrievalCollectionResultV1]  # current producer; old checkpoints may omit
    availability_results: list[AvailableIntervalV1]
    missing_information: list[MissingInformationV1]
    retrieval_rounds: int
```

| 항목 | 반환 의미 |
| --- | --- |
| 공식 Handoff | 다음 Work Analysis 또는 Planning이 소비할 최소 결과다. |
| Source별 상태 | 복수 IN Route의 성공·부분 성공·실패·미시도를 각각 보존한다. 전체 `coverage`만으로 모든 Source가 완료됐다고 추론하지 않는다. |
| 목록 metadata | `collection_results`는 실제 READ에서 관측한 Resource identity·사용자용 제목과 `EXHAUSTED \| HAS_MORE \| UNKNOWN` continuation만 보존한다. 상세 Evidence의 bounded context와 분리하며, 같은 제목이어도 identity가 다르면 별도 항목이다. 이 값은 Query 의미나 전체 Source coverage를 새로 판정하지 않는다. |
| 제외 의무 | `EvidenceSelectionResultV2.excluded_segment_ids + RetrievalState.exclusion_obligation_segment_ids`를 stable dedup하여 결과에 기록한다. |
| 제어 신호 | `NEEDS_MORE_DATA`, `NEEDS_CONFIRMATION`, `ROUTE_RECONSIDERATION_REQUIRED`, `BLOCKED`는 결과의 coverage 값이 아니라 `SubgraphReturnV2.disposition`과 Typed `WorkflowSignalV1`로 전달한다. |
| 부분 결과와 신호 | 확보한 Evidence가 독립적으로 유효하면 `coverage=PARTIAL`과 redirection signal을 함께 반환할 수 있다. |

## 7. 진입 방식

### RESOURCE_SELECTED

사용자 선택 Resource에 IN Route를 고정하고 최신 상세 GET을 수행한다. 선택 ID를 검색 Query로 다시 추측하지 않으며 후보 점수와 관계없이 포함한다.

Registry에 exact direct-read Tool이 있으면 detail Route만 유지한다. 같은 Resource 내부 검색을 위한 추측성 dependency Route는 추가하지 않는다. 다른 Resource Route가 필요하면 Tool Route 재검토 또는 사용자 확인으로 넘긴다.

### AGENT_SEARCH

`RequestIntentV2 + frozen input_routes + retrieval_budget`으로 Source-native 검색을 시작한다. Raw `run_input.user_request`를 Local State/Prompt에 별도 투영하지 않는다.

Metadata Page에서 후보를 좁히고 RAG로 관련 Segment를 고른다. 부족할 때만 같은 Route의 새 Query·Page·Detail을 선택한다. 검색 후 행동을 Round 번호별로 고정하지 않는다.

## 8. Connector·Source 전략

Retrieval Core는 `connector_id + resource_type + allowed_read_tool_ids`에 따라 결정적 Query Builder와 `ConnectorReadPort`를 사용한다. Provider-native query·pagination·detail은 Connector별 Adapter/Tool 계약으로 구체화한다.

아래는 Source별 조회 대상과 처리다. 모든 요청에 동일한 세부 호출 순서를 강제하지 않는다.

| Source | 조회·정규화 대상 |
| --- | --- |
| Gmail | Thread 검색, 참여자·제목·시각·Snippet, 필요한 Thread 상세와 시간순 Message, Segment RAG |
| Tasks | Task List와 목록, 예정일·상태·Keyword, 필요한 상세, Segment RAG |
| Calendar | Calendar와 기간 Event, 필요한 상세·FreeBusy, Segment RAG |
| GitHub Issue | 검증된 repository 범위의 Issue 목록·상세. Container binding은 §5.2-A를 따른다. |

추가 Connector도 같은 Retrieval State·Evidence·Sufficiency 계약을 사용한다.

### Tasks 시간 의미

| 항목 | 구분 |
| --- | --- |
| `TASK + CREATE` 필수 조회 | 기존 미완료 Task의 bounded 후보와 Evidence를 Work Analysis에 제공한다. 중복 검토 후보는 최종 답변용 selected Evidence와 독립된 현재 조회 projection이며, 정상 0건·무관 후보·후보 정보 유실을 구분한다. Retrieval이 최종 중복 여부나 실행 필요성을 확정하지 않는다. |
| Google `due` | `scheduled_date`로 정규화한다. |
| `business_deadline` | Gmail·사용자 요청·Evidence에서 확인한 경우에만 별도 근거로 사용한다. `due`와 자동 동일시하지 않는다. |
| 완료 상태 | 예정일 경과를 Provider 완료 상태로 해석하지 않는다. |

### Calendar Typed Query 계약

Calendar도 `RouteQueryIntentV2 + SemanticRetrievalConstraintV1 → SourceFetchPlanV1`을 사용한다. 별도 `calendar_read_mode`나 `temporal_query` DTO를 만들지 않는다.

| 항목 | 계약 |
| --- | --- |
| `CALENDAR + CREATE` 필수 조회 | 대상 시간대의 Event/FreeBusy 충돌 근거를 확보한다. |
| Event·FreeBusy | Event는 `SEARCH/DETAIL_FETCH`, 실제 FreeBusy 필요 시 `FREEBUSY`를 사용한다. 둘 다 필요하면 typed Route intent를 순서대로 발급하고 Builder가 각각 구성한다. |
| 시간 범위 | `TemporalRangeConstraintV1(axis=EVENT_TIME\|AVAILABILITY_WINDOW, start_local, end_local, timezone)` |
| 의미·계산 구분 | 상대 요일/daypart는 Request Understanding의 typed 의미를 소비한다. RFC3339·Timezone·interval 계산은 결정적 Builder가 소유한다. |
| Daypart | `Asia/Seoul`: `MORNING 06:00–12:00`, `AFTERNOON 12:00–18:00`, `EVENING 18:00–21:00` |
| 다른 Resource의 업무 마감 | Work Analysis 결과를 받아 Additional Retrieval로 재진입한 경우에만 Calendar Query 기준점으로 사용한다. |

## 9. 후보 점수와 조정 가능한 설정

후보 점수는 Policy나 확정 identity가 아니라 **순위 산정용 설정**이다. 구체적인 가중치·알고리즘·임계값은 중앙 Retrieval Config에서 관리하고 평가로 선택한다. 초기 가중치를 제품의 영구 계약으로 고정하지 않는다.

| 고려 요소 | 내용 |
| --- | --- |
| 대상·관계 | 정확한 Resource·Thread 관계, 관련 Resource Link |
| 사람 | 이메일·참여자 일치 |
| 시간·상태 | 요청 기간과의 관계, 상태 적합성, 최신성 |
| 표현 | 제목의 정확 구문, Keyword·의미 관련성 |

Confidence Band와 낮은 점수의 처리 조건은 §16.3을 따른다.

## 10. Segment·Evidence

**시간 범위와 업무 의미를 구분해 근거를 선택한다.**

| 요청·근거 | 선택 기준 |
| --- | --- |
| 추가 분석·인물·주제 조건 없는 수신 기간 메일 목록 | Provider의 timezone-aware 수신시각을 `MESSAGE_TIME` 범위와 비교해 bounded 후보를 선택한다. |
| 위 수신 조건을 만족하는 뉴스레터·다른 기간 행사 메일 | 본문 행사일이 밖이거나 뉴스레터라는 이유만으로 제외하지 않는다. |
| 본문 의미 조건이 있는 요청 | 기존 semantic relevance 판정을 사용한다. |
| 행사 검색 | 실제 행사일과 뉴스레터 발행·집계·대상 기간을 구분한다. 수신시각이나 집계 기간을 행사일로 쓰지 않는다. |

연도 미확정 행사일의 coverage와 반환은 §18을 따른다.

### 10.1 Stable SourceSegment identity

`segment_id`는 같은 Provider Source version을 다시 normalize/chunk했을 때 동일하게 생성되는 **결정적 Evidence identity**다. UI용 임의 UUID가 아니다.

```python
class SourceSegmentIdentityV1:
    schema_version: Literal[1]
    connector_id: str
    source_kind: Literal["gmail", "tasks", "calendar", "github"]
    resource_type: str
    resource_id: str
    source_version_ref: str | None
    chunk_schema_version: int
    chunk_ordinal: int
    normalized_content_sha256: str
```

```text
segment_id = "seg_" + SHA256(canonical_json(SourceSegmentIdentityV1))
```

| 항목 | Identity 규칙 |
| --- | --- |
| Source version | Provider의 stable revision/version/etag가 있으면 `source_version_ref`에 사용한다. 없으면 content hash와 deterministic chunk ordinal이 version evidence를 대신한다. |
| 재생성 | 같은 Resource version·normalized content·chunk schema/boundary는 fresh Retrieval에서도 같은 ID를 만든다. Normalize/Chunk와 `chunk_schema_version`은 같은 입력에 결정적이어야 한다. |
| 변경 | Source version/content 또는 chunk schema가 바뀌어 Evidence 의미가 달라지면 새 ID를 만든다. 과거 exclusion을 임의 승계하지 않는다. |
| 금지 입력 | Random UUID, retrieval revision 번호, query/page ordinal, process-memory handle을 ID 권위로 사용하지 않는다. |
| Resource identity | `connector_id + resource_type + resource_id`가 기준이다. |
| `source_kind` | 관측된 Source의 normalization discriminator다. 결정적 코드가 생성하며 Connector/Resource identity나 Tool Route를 재선택하는 권위가 아니다. |
| 사용자 제외 | 선택 당시 current Preview의 stable ID만 허용하고 `expected_retrieval_revision` membership을 검증한다. |

**GitHub Issue**

`connector_id="github"`, `resource_type="github_issue"`, `resource_id="owner/repository#issue_number"`를 사용한다. `source_kind="github"`는 이를 대체하지 않는다. `github_list_issues`의 각 Issue는 독립 Resource observation이며 목록 전체를 synthetic 단일 Resource로 만들지 않는다.

Evidence 발췌에는 Provider가 관측한 repository·issue number·title·state·URL을 본문과 구분해 보존한다. 본문은 이 identity나 존재 사실을 부정하는 권위가 아니다. Normalize는 payload에 있는 값만 표시하고 누락된 metadata를 추측하지 않는다.

발췌 형식 변경은 GitHub chunk schema에 반영한다. 과거 Evidence/checkpoint의 발췌와 identity를 소급 변경하지 않는다.

### 10.2 Segment·Evidence 크기와 신뢰 경계

| 항목 | 기준 |
| --- | --- |
| Gmail Chunk | 현재 설정: 목표 600 Token, 최대 900 Token, Overlap 80 Token |
| Token 단위 | Provider-independent deterministic estimated token |
| Evidence excerpt | UTF-8 8 KiB 이하 |
| 신뢰 | Source 원문은 비신뢰 데이터 |
| Domain 저장 | 실제 계획에 사용한 최소 Evidence만 저장 |

Chunk 길이·overlap은 검색 품질과 Context 사용량을 평가할 구현 설정이며, Source 신뢰·identity·Evidence 보존 경계를 바꾸는 근거가 아니다.

## 11. Context Budget

Context는 필요한 입력과 Evidence를 담되, 답변 생성·Structured Output·안전 여유를 남겨야 한다. System/Policy/Tool Schema, 현재 Run의 입력, 검색 Context, Output reserve의 비율은 호출 목적과 평가 결과에 따라 조정한다. 고정 백분율을 모든 Node에 적용하지 않는다.

Node별 Projection에 필요한 필드만 사용한다. Tool Route 전체·Registry 전체·후보 전체를 매 호출에 반복 삽입하지 않으며, 화면의 과거 대화를 Retrieval 입력으로 자동 추가하지 않는다.

## 12. 추가 Retrieval

첫 결과와 미해결 조건을 관측한 뒤 다음 행동을 정한다. Round별로 '정확 검색 → 제약 완화 → 마지막 확장' 순서를 고정하지 않는다.

| 필요한 정보 | 같은 IN Route 안의 선택 |
| --- | --- |
| 현재 검색의 미확인 결과 | 유효한 continuation으로 `NEXT_PAGE` |
| 후보의 실제 내용 | 필요한 대상의 `DETAIL_FETCH` |
| 다른 발견 가설 | 관측된 부족 정보에 근거한 `CHANGED SEARCH` |

추가 Retrieval은 기존 횟수·Page·Detail·LLM Budget 안에서만 수행한다. 새 Query에서도 사용자 anchor와 필수 제약은 보존한다. 세부 반복 판정은 §16.2를 따른다.

사용자 범위 밖 기간 확장은 먼저 확인받는다. 새 Resource/Connector는 Local Retry로 추가하지 않고 `RouteReconsiderationRequiredV1`과 `ROUTE_RECONSIDERATION_REQUIRED`를 Parent에 반환한다. 조회로 해결할 수 있는 모호성과 사용자만 결정할 수 있는 선택은 구분하며, 후자는 추가 조회보다 Confirmation을 우선한다.

## 13. API Budget

API Budget은 다음 설정으로 제한한다. 검색 전략이나 재진입으로 상한을 우회하거나 사용량을 초기화하지 않는다.

```
RETRIEVAL_PAGE_SIZE=<configured>
MAX_RETRIEVAL_ROUNDS=3
MAX_ADDITIONAL_RETRIEVAL_ROUNDS=2
MAX_PAGES_PER_SOURCE_PER_ROUND=2
MAX_TOTAL_SOURCE_PAGES=50
MAX_METADATA_CANDIDATES_PER_SOURCE=40
MAX_DETAIL_FETCH_PER_SOURCE=5
MAX_TOTAL_DETAIL_RESOURCES=12
```

Task와 Calendar Event READ에서 현재 Run의 명시적 Resource/Container 선택이 없으면,
계정에 결속된 `selected_tasklist_ids` / `selected_calendar_ids` 전체가 검증된 Container
scope다. Semantic Query는 이 scope를 보존하고, Connector 경계에서는 Container 하나당
하나의 concrete READ로 fan-out한다. 명시 선택이 있으면 그 Container만 사용하며, 허용
scope 밖 ID는 dispatch 전에 거절한다.

## 14. Cache와 영속 경계

| 위치 | 보존 범위 |
| --- | --- |
| Sidebar Cache | React Session Memory |
| Run Retrieval Cache | 현재 Run의 조회 원문·중간 후보. Run 종료 시 폐기. Continuation의 유일한 저장 위치와 검증은 §4.1을 따른다. |
| Main Graph State | `RetrievalResultV1`과 Cache/Evidence Reference |
| Domain Store | 실제 사용 ResourceRef, 최소 Evidence excerpt, Action 연결 |

전체 Sidebar 목록, 미사용 후보, Gmail 전체 원문, FreeBusy 전체 응답, RAG 후보·score 전체를 영속하거나 Main State에 복제하지 않는다. Raw Provider Page Token은 Main State·Checkpoint·Domain DB·Trace·Audit·Prompt에 저장하지 않는다.

강제 최신 조회 시점은 `RESOURCE_SELECTED` 시작, Plan 확정 전, 승인 후 실행 전, 실행 후 Verification이다. Cache가 이 확인을 대체하지 않는다.

## 15. Evaluation consumption boundary

이 문서는 제품 Retrieval 의미와 runtime artifact를 소유한다. Dataset·Case·Fixture·Gold·`evaluation_item_id`·후보 비교와 채점 방식은 `13 Evaluation`에 두고 여기서 다시 정의하지 않는다.

평가는 현재 `ToolRoutePlanV2`, `RetrievalResultV1`, `QueryAttemptV1`, Evidence/Resource reference, configured Retrieval identity를 소비한다. 평가 metadata를 Product Prompt·Main State·Checkpoint·Domain DB의 새 권위 필드로 넣지 않는다.

## 16. QueryAttempt·Confidence·재검색 계약

실패 분류는 `15 Prompt·Failure`의 공통 계약을 따른다.

### 16.1 QueryAttemptV1

`QueryAttemptV1`의 현재 schema는 이 문서가 소유한다. `15 Prompt·Failure`는 이를 소비·검증하며 별도 같은 버전의 payload를 정의하지 않는다.

```python
class ValidatedReadQuerySpecV1:
    tool_id: str
    tool_schema_version: str
    canonical_arguments: CanonicalArguments

class QueryAttemptV1:
    schema_version: Literal[1]
    query_attempt_id: str
    run_id: str
    route_id: str
    round_no: int
    attempt_no: int
    resource_type: str  # exact connector resource_type copied from the frozen InputToolRouteV1 / SignedToolRegistryEntryV1
    connector_id: str
    operation_kind: Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]
    normalized_intent_constraints: list[SemanticRetrievalConstraintV1]
    query_spec: ValidatedReadQuerySpecV1
    previous_query_hash: str | None
    page_state_hash: str | None
    added_constraints: list[str]
    removed_constraints: list[str]
    change_reason_code: str | None
    candidate_count: int | None
    top_score: float | None
    score_margin: float | None
    confidence_band: Literal["HIGH", "MEDIUM", "LOW", "NONE"] | None
    retrieval_config_version: str
    score_config_version: str
    threshold_config_version: str
    stop_reason: str | None
```

### 16.2 반복과 Pagination

| 상황 | 처리 |
| --- | --- |
| 같은 Query + 새로운 Page Token | 정상 `NEXT_PAGE`다. |
| 실패 뒤 같은 Query + 같은 Page 상태 | `QUERY_UNCHANGED_AFTER_FAILURE`로 차단한다. |
| `DETAIL_FETCH` 재호출 | Run Cache 또는 Provider 기술 재시도 계약을 따른다. |
| 추가 Retrieval | 최소 하나의 유효한 제약 변경 또는 같은 Route의 Page/Detail 확장이 있어야 한다. |
| 새로운 Resource Route | Local Retry로 추가하지 않는다. |

**검색 페이지의 coverage**

READ Sufficiency는 같은 Run Cache의 bounded read-result summary로 미소비 페이지를 확인한다.

- Selected exact resource 조회를 제외한 검색에 미확인 페이지가 남으면 전체 확인으로 판정하지 않는다. `source_page_coverage`의 `MISSING` Issue를 유지하고 Budget 안에서 `NEXT_PAGE`를 수행한다. 예산상 불가능하면 `PARTIAL`이다.
- 같은 Route의 Detail 조회는 검색의 미소비 페이지를 대신하지 않는다.
- `NEXT_PAGE`는 현재 검색 제약의 query identity에 결합된 handle을 사용한다. Detail resource의 query identity나 마지막 detail handle은 pagination 권위가 아니다.
- Query identity별 최신 page summary만 continuation 상태를 대표한다. 마지막 Page가 소진되면 이전 Page의 token을 다시 소비하지 않는다.
- QueryAttempt 이력으로 이미 소비한 token의 재사용을 Provider 호출 전에 차단한다. Raw continuation 저장소나 Budget 권위를 추가하지 않는다.

### 16.3 저신뢰 후보

| 항목 | 처리 |
| --- | --- |
| Confidence Band | `HIGH`, `MEDIUM`, `LOW`, `NONE` |
| 실제 점수·Threshold | 중앙 Retrieval Config에서 관리 |
| `AGENT_SEARCH`에 `LOW/NONE`만 존재 | 자동 확정하지 않음 |
| `RESOURCE_SELECTED` | 점수와 관계없이 선택 ID의 상세 GET |
| 상위 1·2위 점수 차이가 설정 Margin 미만 | 확인 또는 추가 Retrieval |

### 16.4 관측할 제약

조회와 결과에서 다음 위반 여부를 확인할 수 있어야 한다. 채점 방식은 §15의 평가 경계를 따른다.

| 항목 | 확인 대상 |
| --- | --- |
| 허용 범위 | ToolRoute 밖 Read Tool 호출 |
| 요청 보존 | 날짜·사람·이메일·선택 Resource의 Query Spec 반영 |
| 진행 | 같은 실패 Query의 반복 |
| Budget | 추가 Retrieval 횟수·Source Page 사용량 |
| 불확실성 | 저신뢰 후보의 임의 확정 |
| Evidence | RAG Top Candidate 밖 근거의 무단 생성 |

## 17. Clarification · Overbroad Retrieval

### 17.1 인물 후보와 선택

`PersonCandidateV1(mention, identity, display_names, source_segment_ids)`는 수집한 SourceSegment의 관측 metadata와 명시적인 이름↔email 연결을 보존한다. 후보가 있다는 것과 대상이 확정됐다는 것은 다르다.

| 항목 | 처리 |
| --- | --- |
| 별칭 병합 | 같은 email에 붙은 다른 메시지의 별칭은 합칠 수 있다. Surname/title만으로 서로 다른 email을 합치지 않는다. |
| 이름 일치 | 요청의 전체 이름과 같은 metadata 이름에 직급이 붙은 경우 후보로 연결할 수 있다. 부분 문자열·성만으로 다른 전체 이름을 일치시키지 않는다. |
| 동명이인 | Email별 별도 후보로 유지한다. |
| 후보 보존 | 제한된 후보를 Retrieval local checkpoint와 `RetrievalResultV1.person_candidates`에 보존한다. 필드 없는 기존 artifact는 빈 후보로 읽는다. |
| Selection의 `EXCLUDED` | 이것만으로 candidate를 삭제하지 않는다. 후보 목록은 보존한다. |
| 사용자 exclusion | 제외된 source segment의 provenance를 철회한다. 철회된 provenance를 후보 근거로 재사용하지 않는다. |
| 유일한 근거 연결 | Fresh validated Evidence assessment의 `SUPPORTS` provenance가 요청 인물 표현과 후보 하나에만 연결되면 해당 관측 identity를 선택할 수 있다. |
| 복수·미해결 후보 | 복수 `SUPPORTS` 후보 또는 유일한 결합이 없으면 기존 Retrieval Confirmation에 후보·차이를 제시한다. 선택 email은 그 후보 집합 안에서만 수용한다. |
| 선택 후 조회 | 유일하게 확인된 후보 또는 검증된 사용자 선택으로 같은 frozen Route에서 exact PARTICIPANT 후속 검색을 수행한다. |

선택은 `selected_person_identities`로 같은 Run에 보존한다. RequestIntent의 사용자 원문을 바꾸거나 LLM에게 email 생성 권한을 주지 않는다.

Planning Handoff에는 확인된 선택을 전달한다. 답변 projection은 선택되지 않은 인물만의 Evidence를 제외하되 원래 Run Evidence를 삭제하지 않는다. Optional `selected_person_identities`가 없는 기존 호출·checkpoint는 생략을 허용한다.

### 17.2 확인·차단 경계

| 상황 | 처리 |
| --- | --- |
| 요청 자체의 모호성 | Request Understanding에서 확인 |
| Tool Route의 불명확성 | Tool Route Subgraph에서 확인 |
| 검색 뒤 남은 동명이인·복수 Resource·저신뢰 후보 | 후보와 차이를 포함해 `NEEDS_CONFIRMATION` |
| 전체 Mailbox·장기간 무제한 원문·모든 Workspace Source 전체 조회 | `BLOCKED` |
| Calendar 시간 overlap | 업무 conflict와 동일시하지 않고 관계 근거를 Work Analysis에 전달 |

## 18. 정보 부족 분류와 결정적 종료 Guard

**시간축과 검색 연도**

RequestIntent의 typed 시간 의미를 보존한다. 명확한 수신/발송 의미는 `MESSAGE_TIME`으로 사용하되, 알려진 행사 단어 목록에 없다는 이유로 `EVENT_TIME`을 바꾸지 않는다. 시간 역할이 미해결이면 received-time lowering을 하지 않는다.

| 요청 | 검색에 사용할 연도 |
| --- | --- |
| 명시 연도 | 지정한 연도를 그대로 사용 |
| 월만 지정한 수신시각 검색 | Run-local 기준 이미 시작된 가장 최근 해당 월 |
| 월만 지정한 행사 검색 | 인접 연도 중 Run-local 날짜에 가장 가까운 해당 기간 |

월만 지정한 경우의 연도는 **검색 가설**이다. 이를 원문에서 생략된 행사 연도·요일의 확정 근거로 사용하지 않는다.

**연도 미확정 행사일**

| 항목 | 처리 |
| --- | --- |
| 전달 대상 | 선택된 Evidence의 연도 미확정 행사 날짜. 명시적 보고·집계 기간은 제외. |
| 결과 | `unresolved_event_dates`에 원문·Evidence 참조와 함께 전달한다. 다른 Resource의 검색 시간 제약을 전파하지 않는다. |
| Coverage | READ의 해당 날짜 범위는 `PARTIAL`이며 finalization에 반영한다. |
| Downstream 사용 | 요청에 맞는 요약과 연도 미확정 안내로 제시할 수 있다. 필요한 날짜 원문은 인용하되 수신시각·집계 기간을 행사일로 대체하지 않는다. |
| 호환 | 선택 필드가 없는 기존 checkpoint는 빈 목록으로 읽는다. |

분석이 필요하지 않은 날짜·인물 lookup도 근거의 의미를 정리해야 한다. Evidence 원문 dump가 답변 생성을 대신하지 않으며, 인용된 ISO offset을 임의 오전/오후·요일로 재계산하지 않는다.

**답변 예산을 남기는 READ 종료**

READ follow-up은 기존 RunBudget 안에서 답변 outline/compose와 bounded repair 여유를 남긴다. `analysis_requirement=REQUIRED`이면 필요한 Work Analysis도 같은 상한 안에서 고려한다. 이 요구를 특정 operation 개수에 고정하지 않는다.

추가 수집이 답변 여유를 침범하면 검증된 Evidence를 보존해 `PARTIAL`로 닫는다. 부분 답변은 확인된 근거만 요약하고 전체 성공을 주장하지 않는다. 정상 no-result의 기존 결정적 projection은 유지한다.

결정적으로 종료 가능한 sufficiency에 LLM 호출을 요구하지 않으며, 수행하지 않은 호출을 counter/Trace에 기록하지 않는다. WRITE의 필수 Target/Argument/Policy Evidence가 미확정이면 이 READ 최적화를 적용하지 않는다.

### 18.1 Sufficiency Issue

```python
class SufficiencyIssueV2:
    schema_version: Literal[2]
    slot: str
    issue_type: Literal["MISSING", "CONFLICT"]
    required: bool
    resolution_source: Literal["USER", "GOOGLE", "CONNECTOR", "POLICY", "ROUTE"]
    route_id: NotRequired[str]
    safety_critical: bool
    reason_codes: list[str]
```

| Resolution source | 의미 |
| --- | --- |
| `GOOGLE` | 기존 Google Workspace producer·checkpoint·schema의 값으로 유지한다. |
| `CONNECTOR` | Frozen Route의 non-Google Connector에서 추가 결정적 조회로 해결 가능한 부족 정보다. GitHub도 이 값을 사용한다. |
| `USER` | 사용자만 해결할 수 있는 정보·선택 |
| `POLICY` | 정책상 필요한 조건 |
| `ROUTE` | Route 재검토가 필요한 조건 |

`GOOGLE`을 `CONNECTOR`로 migration·rename·제거하지 않는다. 두 값의 producer 범위는 다르지만 종료 Guard에서는 현재 frozen Route의 추가 외부 조회로 해결 가능한 같은 class로 처리한다. `CONNECTOR`가 새 Tool·Route 선택이나 Provider autodiscovery 권한을 만들지는 않는다.

**Route 결합**

| 대상 | 규칙 |
| --- | --- |
| 외부 조회 부족 | `route_id`로 해당 frozen IN Route에 결합한다. Source status·Evidence도 같은 Route에 결합한다. |
| 다른 Route의 성공 | 같은 Connector라는 이유로 실패·미시도를 덮지 않는다. |
| Route 없는 기존 `GOOGLE/CONNECTOR` Issue | 해당 Source의 frozen Route가 하나일 때만 호환 결합한다. |
| 복수 후보·Route 없는 back-edge need | 추측하지 않고 기존 Route reconsideration으로 반환한다. |
| `USER/POLICY` 전역 Issue | `route_id` 생략 가능 |
| Policy 필수 조회 실패·미시도 | Safety-critical로 처리한다. 완료된 빈 중복/충돌 확인과 구분한다. |

Sufficiency/LLM-local projection의 coarse category로 GitHub Issue에 `ISSUE`를 사용할 수 있다. 이는 canonical `resource_type`이 아니며 `github_issue`를 대체하거나 `TASK`로 변환하지 않는다. 최종 `source_statuses[].resource_type`은 frozen Route의 exact `github_issue`를 보존한다.

### 18.2 결정적 종료 Guard

종료 Guard는 다음 순서로 적용한다.

1. `required=true`이면서 safety-critical 또는 `resolution_source=POLICY`면 `BLOCKED`.
2. `resolution_source=USER`면 추가 external Connector 조회보다 `NEEDS_CONFIRMATION` 우선.
3. `resolution_source=ROUTE`면 `ROUTE_RECONSIDERATION_REQUIRED`.
4. `resolution_source`가 `GOOGLE` 또는 `CONNECTOR`이고 current frozen Route의 추가 fetch가 가능하며 Budget·lifecycle guard가 허용하면 `NEEDS_MORE_DATA`.
5. Budget 소진 + Read-only + 근거 있는 부분 답변 가능이면 `PARTIAL`.
6. Write 필수 Target/Argument/Evidence 부족은 사용자 해결 가능하면 `NEEDS_CONFIRMATION`, 아니면 `BLOCKED`.

LLM confidence 하나로 안전 Route를 결정하지 않는다. 모든 Graph Profile은 동일 Guard를 사용한다.

## 19. Gmail Attachment Retrieval 경계

| 항목 | 허용 범위 |
| --- | --- |
| Retrieval 후보 정보 | Message 상세의 `filename`, `mime_type`, `size_bytes`, Google `attachment_id` metadata |
| `gmail_get_attachment(message_id, attachment_id)` | 사용자 다운로드 또는 결정적 파일 전달 요청에서만 실행 |
| Attachment bytes | Retrieval Cache·SourceSegment·EvidenceDraft·ContextBundle에 넣지 않음 |
| 첨부 내용 분석 | Evidence로 만드는 기능은 P0 범위 밖 |
| Download | LLM 재검색·추가 Retrieval Budget과 분리된 결정적 READ I/O |
