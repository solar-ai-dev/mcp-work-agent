# 05. Context · Retrieval 설계서

> **Authority:** Context·Retrieval semantics. Tool Route/Workflow/Domain의 전문 의미는 해당 owner를 직접 소비한다.  
> **상태:** Draft v2.18 · **기준일:** 2026-09-05 · **대상:** P0 MVP

## 1. 목적

확정된 Connector Input Route에서 필요한 자료를 최소 호출로 수집하고, 가져온 자료를 그대로 다음 LLM에 전달하지 않고 **관련 Segment를 RAG로 검색·정렬하여 Evidence만 선별**한다. P0에서는 Google Workspace Connector의 Gmail·Tasks·Calendar를 지원한다. 영구 Vector Index는 P0 필수가 아니며 Run-scoped Retrieval/Reranking을 기본 구조로 사용한다.

## 2. 확정 결정

- `CTX-001`: 요청 시점 Connector 원본 연합 검색. P0 Source는 Google Workspace의 Gmail·Tasks·Calendar다.
- `CTX-002`: IN/OUT Tool Route 선택은 Retrieval 이전 `Tool Route Subgraph`가 소유
- `CTX-003`: Retrieval은 고정된 `input_routes`만 사용하고 Resource·Connector·Tool 종류를 재선택하지 않음. `input_routes`에는 사용자 의미상 필요한 READ뿐 아니라 `01-B` Policy Precondition으로 결정적으로 보강된 필수 READ도 포함될 수 있으며 Retrieval은 `required=true`인 Route를 임의 생략하지 않음. 단 사용자 지정 범위를 벗어나는 Policy Precondition Route는 Tool Route의 `SCOPE_EXPANSION_REQUIRED` Confirmation이 완료된 뒤에만 Input Route로 확정될 수 있으며 Retrieval이 스스로 범위를 확대하지 않음
- `CTX-004`: LLM이 Raw Query·Page Token·MCP Arguments를 직접 실행하지 않음
- `CTX-005`: Query 계획 → 결정적 Query Builder → MCP Read → Normalize/Segment → Run-scoped RAG → Evidence → Sufficiency
- `CTX-006`: 가져온 후보 전체를 Work Analysis·Planning Prompt에 직접 전달하지 않음
- `CTX-007`: 부족 시 같은 IN Route 안에서 추가 Retrieval 최대 2회
- `CTX-007A`: Retrieval self-loop의 raw Provider continuation은 **Run Retrieval Cache의 해당 read-result entry만** memory-only로 소유한다. Retrieval Local State에는 raw token을 복제하지 않고 `read_result_handle`만 둔다.
- `CTX-007B`: Follow-up `plan_query`는 현재 round, prior `QueryAttemptV1`, 미해결 `SufficiencyIssueV2`, bounded read-result summary를 입력 Projection으로 사용한다. Raw Page Token·Provider-native Query·MCP Arguments는 LLM 입력에 포함하지 않는다.
- `CTX-007C`: `NEXT_PAGE`는 결정적 Read Node가 prior `read_result_handle`을 Run Retrieval Cache에서 resolve하고 `run_id + route_id + query_identity_hash` binding을 검증한 뒤 opaque continuation을 MCP Read Arguments에 주입한다. unknown/cross-run/mismatched handle은 fail-closed한다.
- `CTX-007D`: 같은 Query와 같은 continuation 상태의 반복은 새 Retrieval round로 인정하지 않는다. 추가 round는 새 Page, 필요한 Detail Fetch, 또는 미해결 Sufficiency Issue에 근거한 변경 Query처럼 **새 정보 획득 가능성이 있는 bounded read**여야 한다.
- `CTX-008`: 새 Resource/Connector Route가 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`를 Parent에 반환
- `CTX-009`: 일반 Retrieval은 Action Row가 아니라 Trace·Checkpoint·Run Cache 대상
- `CTX-010`: RAG는 구조적 필수 단계다. Backend는 deterministic score/lexical retrieval, Embedding, Reranker, Vector Index 등 교체 가능한 구현 capability로 둘 수 있으며 제품에서 활성화할 구성은 `13 Evaluation`의 비교 결과와 `10 Infrastructure`의 Release Config가 결정한다.

## 3. 전체 흐름

```
RequestIntentV2 + ToolRoutePlanV2.input_plan.input_routes
→ Retrieval Subgraph
  → plan_query
  → build_query                         # deterministic
  → execute_read                        # deterministic
  → [Calendar availability 필요 시] resolve_availability  # deterministic supporting operation, independent Edge 아님
  → normalize_segments                  # deterministic
  → rag_retrieve_rerank
  → select_evidence
  → assess_sufficiency
  → finalize_retrieval                  # deterministic
→ RetrievalResultV1
```

Main Graph에는 Query 후보·Page Token·전체 후보·RAG score를 올리지 않는다.

## 4. Retrieval Subgraph State

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

규칙:

- `request_intent`, `input_route_ref`, `input_routes`는 Parent Projection이며 Retrieval이 수정하지 않는다. Retrieval Product Prompt는 raw `user_request`를 별도 권위 입력으로 재주입하지 않고 `RequestIntentV2`의 Canonical 의미를 소비한다.
- 사용자 Context Adjustment는 `07`이 검증한 `ContextAdjustmentV1` 한 개만 Retrieval 재진입 입력으로 받을 수 있다. `EXCLUDE_EVIDENCE`는 current Preview membership이 검증된 stable `segment_id`를 `exclusion_obligation_segment_ids`에 materialize한 뒤 새 selection에서 제외한다. `RETRIEVE_MORE`는 validated `RetrievalNeedV1(reason_codes=[USER_CONTEXT_ADJUSTMENT])`를 `pending_user_retrieval_need`에 materialize한다. 두 semantic obligation 모두 **handoff payload clear 전에 같은 checkpoint에 commit**되며 crash/cache-loss/route-reconsideration 재진입에서도 보존된다. `pending_user_retrieval_need`는 해당 Context Adjustment로 시작된 fresh `RetrievalResultV1` revision이 finalize되는 checkpoint에서만 `None`으로 clear한다. 이 입력은 다른 Agent로 전파되는 장기 업무 사실이 아니다.
- Context Adjustment 후 `RetrievalResultV1`은 새 revision을 발급한다. downstream `WorkAnalysisResultV2`, Plan, Review가 이전 retrieval revision을 `meta.based_on`으로 참조하면 stale이며 재사용하지 않는다. current IN Route로 해결할 수 없는 추가 검색은 기존 `RouteReconsiderationRequiredV1` back-edge를 사용한다.
- `query_plan`, `query_attempts`, `source_statuses`, `read_result_handles`, `segment_handles`, `availability_results`, `rag_candidates`, `exclusion_obligation_segment_ids`, `pending_user_retrieval_need`는 Local State다. `exclusion_obligation_segment_ids`와 `pending_user_retrieval_need`가 user Context Adjustment에서 온 crash-safe semantic obligations이며 raw Provider cache/token이 아니다.
- `read_result_handles`는 현재 Run의 Run Retrieval Cache entry를 가리킨다. Cache entry는 `run_id`, `route_id`, validated `query_identity_hash`, Connector-normalized bounded `ConnectorReadResultV1`과 continuation exhaustion 상태를 결합해 보존한다. `ConnectorReadResultV1.next_page_token`의 opaque continuation은 이 entry 밖으로 복제하지 않는다.
- Parent에는 `RetrievalResultV1`만 병합한다.
- 실제 Connector 원문과 raw continuation은 Run Retrieval Cache Handle로 참조하고 Main State·Checkpoint·Prompt·Trace·Audit·Domain DB에 복제하지 않는다. P0 Google Workspace 원문도 동일 규칙을 따른다.


### 4.1 Restart semantics for memory-only Retrieval cache

Raw Provider continuation을 durable storage에 넣지 않는 원칙은 유지한다. 대신 service restart 후 checkpoint에 남은 `read_result_handle`이 현재 Run Retrieval Cache에서 resolve되지 않으면 **그 handle을 추측·재사용하지 않고 deterministic Retrieval restart**를 수행한다.

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

- 이것은 `RecoveryReasonV1`을 새로 만드는 경로가 아니다. frozen Route/Request contract와 checkpoint binding이 유효한 한 same-run Retrieval을 처음부터 다시 실행하는 **workflow-local restart**다. binding/contract 자체가 stale이면 기존 `CHECKPOINT_MISMATCH | CONTRACT_VIOLATION` Recovery를 사용한다.
- raw `next_page_token`과 prior memory-only cache는 복원하지 않는다. Provider 데이터가 restart 사이에 바뀌면 새 조회 결과가 current revision의 authority가 된다.
- `RunRetrievalCacheResolveResultV1.status=FOUND|EXHAUSTED`는 모두 **현재 handle entry와 run/route/query binding이 유효함**을 뜻하므로 resume prerequisite를 충족하고 cache restart를 만들지 않는다. `EXHAUSTED`는 `entry.continuation_exhausted=true`인 유효 read-result이며 `NEXT_PAGE`만 Provider 호출 전 `NO_MORE_PAGE`로 종료한다. `MISSING|CROSS_RUN|BINDING_MISMATCH`만 cache-loss restart 대상이다.
- `RunBudgetV2`의 이미 소비된 LLM/read/page/detail counter는 reset하지 않는다. restart가 새 outbound call을 만들면 일반 budget으로 추가 소비하며 hard cap을 넘기지 않는다.
- `EXCLUDE_EVIDENCE` control이 적용되면 handoff payload clear 전에 stable IDs를 `RetrievalState.exclusion_obligation_segment_ids`에 checkpoint-commit한다. `RETRIEVE_MORE`는 같은 control-patch checkpoint에 `ContextAdjustmentV1.retrieval_need`를 `RetrievalState.pending_user_retrieval_need`로 materialize한다. 이후 cache가 유실되거나 handoff가 이미 CONSUMED여도 fresh retrieval은 exclusion obligation과 pending need를 그대로 사용한다. `pending_user_retrieval_need`는 새 Retrieval revision finalize 전에는 clear하지 않는다.
- Retrieval-dependent checkpoint를 commit할 때 checkpointer adapter는 Local State의 현재 handle dependency를 `GraphCheckpointEnvelopeV1.retrieval_cache_requirements: list[RetrievalCacheRequirementV1]`로 bounded projection한다. Application은 opaque `checkpoint_blob`을 열지 않고 이 metadata만 검사한다. handle dependency가 끝난 checkpoint는 빈 list를 저장하며 Confirmation/Reauth가 Retrieval-local continuation으로 복귀하는 동안에는 requirement를 유지한다.
- Confirmation/Reauth suspend 중 process-memory cache가 사라졌다면 해당 owner resume 전에 같은 handle validation을 수행하고, Retrieval local state가 필요한 target이면 위 RETRIEVAL_ENTRY restart로 정상화한다.
- `RETRIEVAL_CACHE_RESTART` handoff trigger는 `system:retrieval-cache-restart:<run_id>:<checkpoint_generation>` 하나다. staging 전 `WorkflowHandoffRepository.get_by_trigger_command_id(trigger)`로 existing PENDING/DISPATCHED/CONSUMED row를 먼저 resolve하며, 같은 trigger에 두 번째 handoff/control을 만들지 않는다. HTTP command replay 계약을 이 system trigger에 적용하지는 않는다.
- Run Retrieval Cache의 production boundary는 `07 RunRetrievalCachePort` 하나이며 P0 concrete binding은 `adapters/system/memory/run_retrieval_cache.py → InMemoryRunRetrievalCache`다. `retrieval.execute_read`가 entry 저장/resolve를 사용하고, Run terminal cleanup은 `discard_run(run_id)`만 호출한다. module-global dict, LangGraph private cache, Domain/Checkpoint raw continuation 저장은 second authority라서 금지한다.
- Cache-loss restart의 Application semantic owner는 `run.reconcile_retrieval_cache_restart → ReconcileRetrievalCacheRestartHandler` 하나다. 이 Handler만 typed checkpoint의 `retrieval_cache_requirements` 각각을 `RunRetrievalCachePort`로 검사하고, invalid/missing이면 위 deterministic trigger를 dedupe한 뒤 `WorkflowHandoffStageV1(control_kind=RETRIEVAL_CACHE_RESTART, target=MAIN_CONTROL:RETRIEVAL_ENTRY)`를 short UoW로 stage하고 기존 `run.schedule_run_execution`을 호출한다. LangGraph Node/Background adapter는 Repository를 직접 쓰지 않는다.

### 4.2 Exclusion obligation checkpoint lifetime

`EXCLUDE_EVIDENCE`는 one-shot handoff payload 자체를 장기 authority로 사용하지 않는다. Application이 current Preview membership과 `expected_retrieval_revision`을 검증한 뒤 stable `segment_id`를 `RetrievalState.exclusion_obligation_segment_ids`에 materialize하고, **handoff payload clear보다 먼저 checkpoint-commit**한다.

- 이 obligation은 해당 same-Run Retrieval lineage가 새 `RetrievalResultV1`을 finalize할 때까지 crash-safe하게 유지한다.
- cache-loss fresh Retrieval은 checkpoint-local `exclusion_obligation_segment_ids`와 current `RetrievalResultV1.excluded_segment_ids`를 합쳐 `select_evidence`에 적용한다.
- finalize된 `RetrievalResultV1.excluded_segment_ids`는 이후 같은 Run의 `RETRIEVE_MORE` 또는 fresh Retrieval 재진입 시 Local State 초기 projection이 된다.
- Route reconsideration 뒤에도 같은 stable `segment_id`가 다시 나타나면 exclusion을 적용한다. source version/content 또는 chunk schema 변화로 새 ID가 된 Evidence를 fuzzy text matching으로 자동 제외하지 않는다.
- stable `segment_id`의 생성·변경 semantics는 §10.1이 소유한다. 이 절은 checkpoint lifetime만 소유한다.

### 4.3 RETRIEVE_MORE obligation checkpoint lifetime

`RETRIEVE_MORE`는 one-shot handoff payload를 Query Planner까지 직접 들고 가지 않는다. control patch가 `ContextAdjustmentV1.retrieval_need`를 `RetrievalState.pending_user_retrieval_need`에 checkpoint-commit한 뒤에만 handoff payload를 clear한다.

- `retrieval.plan_query`의 user-context-adjustment projection은 raw `ContextAdjustmentV1`이 아니라 `pending_user_retrieval_need`를 읽는다.
- Query/Page/Detail self-loop, Confirmation/Reauth suspend, process-memory cache loss, `RETRIEVAL_CACHE_RESTART`, current-route 실패 후 Route reconsideration/re-entry에서도 같은 need를 보존한다.
- current IN Route로 해결할 수 없으면 기존 `RouteReconsiderationRequiredV1`을 사용하되 pending need는 새 Route가 확정되어 fresh RetrievalResult revision이 finalize될 때까지 유지한다.
- `finalize_retrieval`이 새 `RetrievalResultV1` revision을 checkpoint-commit할 때 `pending_user_retrieval_need=None`을 같은 checkpoint에 기록한다. finalize 전 crash는 need를 잃지 않고, finalize 후 crash는 같은 사용자 need를 다시 적용하지 않는다.
- 두 번째 Context Adjustment는 expected retrieval revision guard를 통과한 경우에만 새로운 pending need를 설정하며 stale request가 current obligation을 덮어쓰지 못한다.

## 5. Retrieval 내부 책임 · LangGraph Node + deterministic Application operation

### 5.1 `retrieval.plan_query`

의미 검색은 exact anchor와 검색 가설을 분리한다. `CONCEPT(concept, manifestations)`는
사용자 `business_concepts`에 결합된 bounded planner 가설이며, 특정 개념의 고정 동의어
목록으로 대체하지 않는다. 새 Planner 출력은 Provider syntax 없는 서로 다른 manifestation을
한 검색에 1~3개만 허용한다. 기존 v2 artifact의 12개 상한은 읽기 호환용이며 기존 query/hash를
잘라서 재해석하지 않는다. literal-only 가설은 bounded semantic revision 대상이지 코드가
날짜 표기나 고정 동의어로 치환할 대상이 아니다. 후보의 concept match는 발견 신호일 뿐
Evidence relevance나 행사 사실이 아니다.

검색 가설은 기존 `RouteQueryIntentV2`의 operation(발견/상세/페이지), semantic constraints,
`reason_codes`(검색 목적과 해결할 insufficiency), `required_information`(성공 조건)으로 표현한다.
`CONCEPT`는 한 가설에 하나만 허용하는 기존 kind uniqueness를 따른다. 복합 개념 요청은
그중 하나를 후보 발견 축으로 선택할 수 있다. 모든 개념은 RequestIntent와 Evidence/Sufficiency의
검증 의무에 남기며 단일 검색에 모두 AND하도록 요구하거나 요청 제약을 삭제하지 않는다.
미해결 사람·시간·업무 의미는 RequestIntent와 SufficiencyIssue에서 소비한다. CHANGED 가설은
같은 route의 성공한 검색 관측과 미해결 issue에 근거해야 하며 실패를 0건 관측으로 보지 않는다.
고정 불용 업무 단어 제거, 자동 ALL→ANY 완화, 날짜 문자열만의 자동 fallback은 금지한다.
Planner가 EVENT_TIME 후보 부재라는 관측에 근거해 요청 기간의 본문 날짜 언급을 다음
discovery 단서로 선택할 수는 있다. 이는 원래 concept/window를 유지하는 가설이며 날짜
표기와 최종 검색어를 코드가 고정 목록으로 제공하지 않는다. 날짜 언급만으로 행사 relevance를
인정하지 않고 detail의 실제 사건/날짜를 검증한다.
같은 가설 반복과 기존 검색/detail budget 상한은 유지한다.

Query semantic revision은 기존 FailureRecord의 `QUERY_USER_CONSTRAINT_MISSING`(요청 개념 누락),
`QUERY_TOO_NARROW`(literal-only concept)로 수정 이유를 구분한다. 모델 재요청에는 원래의
모델 출력 후보만 전달하고, Application이 복원한 exact anchor/기간/container를 모델 출력으로
위조하지 않는다. 수정 후 같은 deterministic binding과 validator를 다시 적용한다.

Request Understanding의 의미 추론은 `search_terms`와 `business_concepts`를 생성한다.
구조화된 검색 필드가 빠져도 원 요청이 남아 있으면 Planner의 bounded KEYWORD 발견을
닫지 않는다. 필드 부재를 exact identity·기간·상태의 근거로 삼지는 않으며, 기존 Route
정책과 Provider 문법 검증을 그대로 적용한다. `SCOPE.search_terms`도 같은 원문 anchor로
소비하며 사용자 값 자체를 새로 추측하지 않는다.
새 Request Goal 출력의 `search_terms/business_concepts/required_information`은
`USER_REQUIREMENT` kind로 검증한다. 기존 typed intent의 `SCOPE.search_terms` 소비는 유지한다.
빈 날짜·상태 placeholder는 검색 제약으로 승격하지 않는다. Temporal 출력 스키마도
기존 validator와 동일하게 적어도 한 개의 유효한 local boundary를 요구한다.
Gmail-only AGENT_SEARCH의 Goal 추론 경계는 `constraints`의 이름이 고정된 슬롯 객체를
사용한다: search_terms, business_concepts, required_information, person, sender, recipient,
subject, period, temporal_axis, status. 모든 슬롯을 응답하되 미언급 값은 빈 배열로 둔다.
새 Goal 추론 계약 v2의 슬롯 객체는 같은 identify_goal owner에서 기존 ConstraintV1 목록으로
변환하며 `RequestIntentV2`와 checkpoint 구조를 바꾸지 않는다. 다른 Connector/WRITE의
목록 표현은 유지한다. 기간과 인물의 명시적 표기는 기존 보존 연산의 값을 재사용한다.
목록형 과거 Goal 출력을 새 Gmail 추론 경계에서 병렬로 허용하지 않는다.
Gmail-only 검색의 period에는 temporal_axis를 함께 출력한다. Gmail 검색 상태는
현재 지원하는 명시적 ANY/DRAFT/SENT 값만 고정하며, 다른 Resource의 OPEN 등의 값으로
임의 메일 상태 필터를 생성하지 않는다.

READ Sufficiency는 같은 Run Cache의 bounded read-result summary에서 미소비 다음 페이지를
확인한다. selected exact resource 조회를 제외한 검색은 미확인 페이지가 남으면 전체 확인으로
판정하지 않고 기존 `source_page_coverage` MISSING issue와 budget 안에서 NEXT_PAGE를 수행한다.
예산상 불가능하면 PARTIAL로 종료한다. raw continuation이나 새 budget authority를 만들지 않는다.
같은 Route의 상세 조회는 검색의 미소비 페이지를 대체하지 않는다. NEXT_PAGE는 현재
검색 제약의 query identity에 결합된 cache handle을 사용하고, 상세 resource의 query identity나
마지막 상세 handle을 pagination authority로 사용하지 않는다.
각 query identity의 최신 page summary만 continuation 상태를 대표한다. 마지막 페이지가
소진되면 이전 페이지의 토큰을 다시 소비하지 않으며, QueryAttempt 이력으로도 이미 소비한
토큰의 재사용을 Provider 호출 전에 차단한다.
Gmail 본문이 없는 검색 preview의 locator는 `is_metadata_only=true`를 보존한다.
이는 실제 query에 일치한 후보이지 업무 사실의 확정 근거가 아니다. 아직 본문을 읽지 않은
preview는 CONTEXT로 유지하고 기존 제한된 detail fetch로 관련성을 판단한다. 제목에
핵심 단어가 없다는 이유만으로 본문 관련성을 부정하지 않는다. 이미 본문을 읽은 후보와
기존 checkpoint의 해당 marker 없는 Evidence는 기존 relevance 판단을 유지한다.
후처리가 업무 단어 사전이나 '메일 앞 단어' 정규식으로 이를 교체하거나 특정 단어를
business concept으로 승격하지 않는다. 명시적 quoted subject/사람 표기/기간의 원문 보존은
유지한다. 예를 들어 사용 방식의 수식어는 명시적 제목이나 업무 anchor가 아니다.

월만 지정한 요청의 검색 연도는 사실 확정과 구분한다. 명시 연도는 그대로 사용하고,
수신 시각 검색은 Run-local 기준 이미 시작된 가장 최근 해당 월, 행사 검색은 인접 연도 중
Run-local 날짜에 가장 가까운 해당 기간을 검색 가설로 사용한다. 이 검색 가설만으로 원문의
생략된 행사 연도를 확정하거나 요일을 만들지 않는다. 본문 행사일과 뉴스레터 발행/대상 기간은
Evidence selection에서 구분하고, 원문에 확정되지 않은 연도는 최종 답변에서도 미확정으로 남긴다.

입력:

```
# 모든 Round
request_intent
input_routes
retrieval_budget

# Follow-up Round에서만 추가되는 bounded Local Projection
current_round_no
prior_query_attempts
unresolved_sufficiency_issues
read_result_summaries
```

`read_result_summaries`는 `read_result_handle`, `route_id`, query identity/hash, 이미 확인한 Resource 참조의 bounded summary, `has_next_page`, continuation state hash 같은 **의미·진행 metadata만** 포함한다. Raw `next_page_token`은 포함하지 않는다.

출력:

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

`RouteQueryIntentV2`는 `operation`이 유효 branch를 결정하는 closed discriminated union이다.

- `SEARCH | FREEBUSY`: `search_spec` 필수, `detail_candidate_ref=None`
- `DETAIL_FETCH`: `search_spec=None`, current Run에서 검증된 exact selected-resource ref 또는 bounded candidate ref인 non-empty `detail_candidate_ref` 필수
- `NEXT_PAGE`: `search_spec=None`, `detail_candidate_ref=None`; raw continuation은 Run Retrieval Cache가 소유

서로 다른 branch의 필드를 섞은 출력은 Provider 호출 전에 `QUERY_OPERATION_FIELD_MISMATCH`로 차단하거나 bounded revision한다.

책임:

- 이미 허용된 IN Route 안에서 무엇을 어떤 순서로 찾을지 제안
- 사용자 날짜·사람·선택 Resource·업무 제약을 구조화
- Policy Precondition으로 추가된 필수 Route에서는 해당 검사 목적을 충족할 후보를 수집한다. `TASK + CREATE`의 Tasks Route는 기존 미완료 Task 중복 후보를, `CALENDAR + CREATE`의 Calendar Route는 대상 시간대의 Event/FreeBusy 충돌 근거를 확보한다.
- Page·후보·상세 조회 Budget 제안

초기 `RESOURCE_SELECTED`에서 frozen IN Route가 1개이고 Registry의 exact detail READ Tool과 current-Run 검증 Resource ref가 각각 하나로 결정되면 `plan_query` LLM은 호출하지 않는다. Retrieval owner의 deterministic materialization이 `DETAIL_FETCH` plan을 만들고 동일 validator를 통과시킨다. 복수 Route·복수 ref·일반 검색·follow-up에서는 이 branch를 사용하지 않는다.

정확한 `TASK + CREATE` 요청에서 제목, Policy-required `TASK | TASK_LIST` Route, 검증된 기본 Task List ref가 각각 하나로 고정되면 중복 검사 목적의 초기 Query Plan은 결정적 `SEARCH + CONTAINER_REF`로 materialize하고 동일 validator를 통과시킨다. 실제 Tasks Connector READ와 Work Analysis 중복 판정은 유지한다. 복수 Task List, 일반 Task 검색, 추가 사용자 제약 또는 follow-up Retrieval에는 이 branch를 사용하지 않는다.

금지:

- 새로운 Connector/Resource Route 추가
- OUT Tool 선택
- Provider-native Raw Query·시간 형식·Page Token을 임의 생성해 바로 실행. Gmail Query·RFC3339는 P0 Google Workspace의 구체 예다.
- Write

### 5.2 `retrieval.build_query`

결정적 Application Node다.

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

- `NEXT_PAGE`에서 LLM은 Page Token을 생성·복사·수정하지 않는다.
- 선택된 handle의 `run_id`, `route_id`, query identity/hash가 현재 frozen IN Route와 맞지 않으면 호출하지 않고 fail-closed한다.
- continuation이 소진된 handle에 대해 같은 Page를 재요청하지 않는다.

### 5.2-A Semantic Constraint · changed SEARCH · `SourceFetchPlanV1`

`SEARCH`의 LLM 출력 권위는 Provider Query가 아니라 **typed semantic retrieval constraint**다. Provider-native Gmail query, RFC3339 변환, MCP Arguments, raw continuation은 결정적 Builder/Executor가 소유한다.

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

`SourceFetchPlanV1.resource_type`은 `EMAIL | TASK | CALENDAR` 같은 별도 semantic-family vocabulary가 아니다. 해당 `route_id`의 frozen `InputToolRouteV1.resource_type`을 그대로 복사하며, 그 값은 selected/allowed `SignedToolRegistryEntryV1.resource_type`과 exact match해야 한다. 한 Input Route의 `allowed_read_tool_ids`는 모두 같은 Registry `resource_type`을 가져야 하며 서로 다른 Connector resource를 조회하려면 별도 Input Route를 사용한다. Retrieval은 Tool 이름 parsing이나 local 문자열 mapper로 resource identity를 변환하지 않는다.

Initial SEARCH에서 `constraints`는 값이 포함된 semantic constraint여야 한다. constraint 이름만 반환하거나 Provider-native Query 문자열을 반환하는 것은 invalid contract다.

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

규칙:

- `CHANGED`는 같은 frozen `route_id` 안의 semantic 검색 제약만 바꾼다. Connector·Resource·Tool 재선택이 아니다.
- `upsert_constraints`는 `kind`별로 기존 값을 교체하거나 새 값을 추가한다. P0에서 같은 Route의 effective set은 동일 `kind`를 중복 보유하지 않는다.
- `remove_constraint_kinds`는 해당 `kind` 전체를 제거한다. frozen Route 또는 Policy Precondition이 필수로 요구하는 constraint는 제거할 수 없다.
- CHANGED merge는 기존 temporal role/window, resource/container identity, 상태, 확정 participant 및 lexical anchor 값을 보존한다. CONCEPT의 manifestation만 같은 concept 안에서 변경한다. 이름 discovery KEYWORD를 제거하려면 current-Run typed person candidate의 유일한 identity 또는 검증된 Confirmation 선택과 일치하는 exact PARTICIPANT로 전환해야 한다. LLM reason code만으로 이 예외를 승인하지 않는다.
- follow-up Prompt의 prior attempt projection은 semantic constraint·operation·reason·결과 수·stop reason·query hash만 포함한다. 원본 QueryAttempt의 `query_spec`는 Builder/관측용이고 LLM 입력에서 제외한다.
- 새 Gmail lexical lowering은 각 KEYWORD를 literal quote로 묶어 사용자/모델 문자열의 Provider operator 실행을 막는다. 지원하지 않는 quote/backslash/control delimiter는 Provider 호출 전에 차단한다. QueryAttempt의 retrieval config v3를 기록하되 과거 attempt/query를 수정하지 않는다. 동일 semantic constraints의 이미 수행한 검색은 lowering 표현이 달라져도 반복으로 차단하여 checkpoint 재진입이 새 검색 기회가 되지 않게 한다.
- merge 뒤 effective constraints가 prior와 의미상 동일하면 `QUERY_UNCHANGED_AFTER_FAILURE`로 fail-closed하며 새 Retrieval Round로 인정하지 않는다.
- 같은 delta 안에서 같은 `kind`를 upsert와 remove에 동시에 넣거나, Route가 지원하지 않는 constraint, 값 없는 constraint, 모순 temporal range는 Provider 호출 전에 차단한다.
- 날짜/시간 문자열은 semantic local value이며 Provider RFC3339/Gmail query syntax가 아니다. `start_local/end_local`은 offset 없는 ISO local date 또는 local datetime이고 `timezone`은 IANA timezone ID다. 파싱·Timezone 해석·interval 계산·Provider 표현 변환은 deterministic code가 수행하며 invalid/ambiguous local value는 Provider 호출 전에 차단한다.
- `ParticipantConstraintV1.participants`는 역할별 identity를 함께 보존하므로 `from A + to B`처럼 서로 다른 participant role을 한 constraint 안에서 표현할 수 있다.
- `ResourceRefConstraintV1.resource_refs`와 `ContainerRefConstraintV1.container_refs`는 현재 Run/Route에서 이미 검증된 내부 ref만 허용하며 raw Provider resource ID를 LLM이 새로 발명하는 권위가 아니다.
- `QueryAttemptV1.added_constraints/removed_constraints` 같은 이름 목록은 관측·follow-up summary다. **다음 실행계획의 값 권위가 아니며** `SourceFetchPlanV1.effective_constraints`를 재구성하는 두 번째 source로 사용하지 않는다.

#### GitHub repository container authority

`connector_id="github"`, `resource_type="github_issue"`인 frozen `InputToolRouteV1`은 다음 existing current-run authority만 route-scoped `ContainerRefConstraintV1(container_refs=["owner/repository"])`로 materialize할 수 있다.

1. 검증된 current-run `SelectedResourceRefV1`/`ResourceRef`의 `parent_resource_id`
2. `06`의 deterministic provenance 검증을 통과한 current `RequestIntentV2`의 explicit `owner/repository` constraint

- 두 source가 모두 존재하고 exact match하면 하나의 container constraint로 정규화한다. 불일치하면 어느 쪽에도 precedence를 주지 않고 기존 Confirmation 또는 fail-closed 경로로 보내며 `ConnectorReadPort` 호출은 0이다.
- repository가 필요한 GitHub `SEARCH` Route에 검증된 source가 하나도 없으면 Source Fetch Plan을 실행하지 않고 기존 Confirmation/selection lifecycle을 사용한다. LLM, 연결 계정, organization, 최근 repository 또는 첫 Provider 검색 결과로 owner/repository를 채우지 않으며 `ConnectorReadPort` 호출은 0이다.
- 결정적 `SourceFetchPlanBuilder`는 검증된 container constraint와 frozen Route의 `connector_id="github"`, `resource_type="github_issue"`, `allowed_read_tool_ids`를 그대로 보존하고, 등록된 `github_list_issues` argument의 `repository`로만 lower한다. Retrieval LLM은 repository나 Tool을 다시 선택하지 않는다.
- selected GitHub Issue의 `DETAIL_FETCH`는 검증된 `resource_id="owner/repository#issue_number"`와 `parent_resource_id="owner/repository"`의 결합을 보존한다. 새 GitHub Retrieval DTO, Graph 또는 별도 repository authority를 만들지 않는다.

#### Operation별 권위

| Operation | LLM/Planner가 결정 | deterministic code가 결정 |
| --- | --- | --- |
| `SEARCH` | semantic constraint 값, reason | merge, normalize, query identity, Provider query, MCP args |
| `NEXT_PAGE` | 추가 Page 필요성과 reason | handle binding, raw continuation resolve/injection |
| `DETAIL_FETCH` | bounded `detail_candidate_ref`, reason | target/resource/tool binding, MCP args |
| `FREEBUSY` | 필요한 semantic 시간 범위와 reason | timezone/RFC3339, interval arithmetic, MCP args |

이 절의 `RetrievalQueryPlanV2 → SourceFetchPlanV1`가 Release canonical이다. `RetrievalQueryPlanV1/RouteQueryIntentV1` 또는 name-only delta는 기존 Artifact/테스트를 읽기 위한 호환 의미일 수 있으나 새 Release planner output authority로 사용하지 않는다.

### 5.3 `retrieval.execute_read`

결정적 Application Node다.

- `input_routes[].allowed_read_tool_ids` 안의 Tool만 호출한다.
- Retrieval LLM은 Tool을 다시 선택하지 않는다. Query Plan을 실제 Tool 호출 순서로 변환하는 것은 Registry metadata와 Query Builder의 결정적 책임이다.
- Page·Detail Fetch·FreeBusy는 Query Plan과 Route에 따라 결정적으로 호출한다.
- List/Search MCP Read 결과의 opaque continuation은 Adapter/Application 경계에서 정규화한 뒤 현재 Run의 Run Retrieval Cache entry에만 보관한다. Local State에는 새 `read_result_handle`과 `QueryAttemptV1` metadata만 기록한다.
- 다음 Round의 `NEXT_PAGE`는 prior handle을 resolve해 continuation을 재사용하되, 동일 query + 동일 continuation state를 새 round로 반복하지 않는다.
- 401·429·5xx·Timeout은 LLM Repair가 아니라 일반 Retry/Reauth 계약을 따른다.

### 5.4 `retrieval.resolve_availability`

Calendar FreeBusy 또는 Event busy interval이 필요한 요청에서만 실행하는 **Retrieval 내부 deterministic Application operation**이다. 이 책임은 availability 산술·정규화를 소유하지만 별도 Supervisor routing authority나 독립 LangGraph Edge를 만들지 않는다. `06 Workflow`의 Retrieval graph topology 안에서 현재 Route/Read 결과를 소비해 `availability_results` Local State를 채우는 결정적 책임으로 취급한다.

```
사용자 시간 제약 + Timezone + busy intervals
→ interval normalization
→ deterministic intersection/subtraction
→ AvailableIntervalV1[]
```

- LLM은 가능한 시간 구간의 산술·겹침 계산을 수행하지 않는다.
- LLM은 `1시간`, `8월 16일 전`, `오후` 같은 의미 제약만 구조화할 수 있고 실제 시각 계산은 이 Node가 수행한다.
- 여러 가능한 구간 중 업무 의미상 하나를 추천해야 할 때만 Work Analysis가 `AvailableIntervalV1[]`을 소비한다.

### 5.5 `retrieval.normalize_segments`

- Gmail HTML 안전 텍스트 변환
- 인용·서명 제거
- Tasks·Calendar를 공통 WorkItem/SourceDocument/SourceSegment로 정규화
- 모든 SourceSegment는 `SourceContentSecurityMetaV1`을 가져 Source Content가 `DATA_ONLY`인 비신뢰 입력임을 구조적으로 보존한다.
- Chunking·Dedup
- Attachment bytes 제외

```python
class SourceContentSecurityMetaV1:
    trust_class: Literal["UNTRUSTED_SOURCE_CONTENT"]
    content_role: Literal["DATA_ONLY"]
    instruction_like_content_detected: bool
    sanitization_flags: list[str]
```

`instruction_like_content_detected=false`도 신뢰 승격을 뜻하지 않는다. 모든 Google Source Content는 항상 비신뢰 데이터이며 이 필드는 탐지·관측·평가 보조 정보다.

### 5.6 `retrieval.rag_retrieve_rerank`

가져온 Segment를 사용자 요청에 대해 검색·정렬한다. Repository/Workflow mapping에서는 이 책임을 `rag_retrieve_rerank`로 통일한다.

```python
class RagCandidateV1:
    segment_id: str
    resource_ref: str
    retrieval_score: float
    reason_codes: list[str]
```

P0 기본:

1. Exact Resource/participant/date/keyword deterministic score
2. lexical retrieval
3. 선택적 embedding/reranker adapter
4. dedup
5. Context Budget에 맞춘 top candidate

RAG backend는 교체 가능하지만 **“후보 전체를 다음 LLM에 전달”하는 구조는 허용하지 않는다.**

### 5.7 `retrieval.select_evidence`

입력은 `request_intent + top rag candidates`다.

출력:

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

업무 사실의 최종 해석은 하지 않는다. 사용자의 요청을 뒷받침하거나 반박하는 관련 Segment/Evidence를 고르는 것까지만 담당한다.

`excluded_segment_ids`는 **Retrieval 내부 Evidence selection 결과**다. Browser가 이 field를 직접 mutate하는 경로는 금지한다. 다만 current P0의 `FN-050 Context Preview`는 `run.adjust_context → ContextAdjustmentV1`이라는 validated Application 경계를 통해 사용자 주도 `EXCLUDE_EVIDENCE | RETRIEVE_MORE`를 지원한다. 이 external control은 same Run Retrieval owner로만 전달되고 Browser/Agent가 Main State나 Evidence row를 직접 수정하지 않는다.

### 5.8 `retrieval.assess_sufficiency`

입력은 `request_intent + selected evidence`다.

```python
class SufficiencyResultV2:
    schema_version: Literal[2]
    status: Literal[
        "SUFFICIENT", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED", "PARTIAL", "BLOCKED"
    ]
    issues: list[SufficiencyIssueV2]
```

새 Resource/Connector가 필요하면 `ROUTE_RECONSIDERATION_REQUIRED`를 반환한다. 같은 Route 안에서 Query/Page/Detail을 늘리면 Local Retrieval Round로 처리한다.

분석이나 사용자 모호성이 없는 단일 selected GitHub Issue의 UPDATE/CLOSE/REOPEN은,
exact 대상의 required READ가 COMPLETE이고 같은 identity의 Evidence가 확보됐을 때
기존 `assess_sufficiency`가 source 충분성을 결정적으로 확정할 수 있다.
요청한 변경 후 title/body/state가 현재 Issue와 다르다는 사실은 source 누락이나 충돌이 아니다.
다른 Source/Output, 부분 조회, 미해결 slot에는 이 단축을 적용하지 않는다.
이는 Planning 진입을 위한 source 판정이며, 변경 인자의 완전성·target Evidence binding·Review·
Approval·실행 admission·재조회 Verification을 대체하지 않는다.

### 5.9 `retrieval.finalize_retrieval`

결정적 finalization 책임이다.

```
validated source_statuses
+ selected evidence
+ sufficiency
+ availability_results when applicable
→ RetrievalResultV1
→ final Retrieval disposition
→ optional typed WorkflowSignalV1
```

규칙:

- 새 Query·Resource·Connector·Tool을 선택하지 않는다.
- Evidence를 새로 판단하거나 RAG를 다시 수행하지 않는다.
- `assess_sufficiency`까지 검증된 Local State만 공식 `RetrievalResultV1`으로 조립한다.
- `NEEDS_MORE_DATA`의 same-route bounded loop, `ROUTE_RECONSIDERATION_REQUIRED`, `NEEDS_CONFIRMATION`, `PARTIAL`, `BLOCKED` 의미를 임의로 바꾸지 않는다.
- Parent에는 공식 `RetrievalResultV1`과 필요한 Typed `WorkflowSignalV1`만 반환한다.

## 6. Parent 반환

Connector READ의 `NOT_FOUND`와 `PERMISSION_DENIED`는 정상 빈 조회 결과가 아니다. `execute_read`는 해당 실패를 bounded 실행 결과로 전달하고, 기존 Acquisition Source summary에 `FAILED`와 정규화된 오류를 보존한다. 성공한 다른 Source의 Evidence/cache와 실패한 QueryAttempt 이력은 유지한다. 동일 요청 내 검색 반복으로 해결할 수 없는 대상·접근 실패는 추가 검색을 요청하지 않으며, READ는 확인 범위의 `PARTIAL`, 필수 pre-read가 누락된 WRITE는 기존 안전 Guard를 따른다. Credential 만료의 기존 `REAUTH_REQUIRED` 계약은 이 처리에 합치지 않는다.

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
    availability_results: list[AvailableIntervalV1]
    missing_information: list[MissingInformationV1]
    retrieval_rounds: int
```

`RetrievalResultV1.excluded_segment_ids`는 current Retrieval lineage의 stable segment exclusion obligation을 공식 artifact로 보존한다. `finalize_retrieval`은 `EvidenceSelectionResultV2.excluded_segment_ids + RetrievalState.exclusion_obligation_segment_ids`를 stable dedup하여 기록한다. `RetrievalResultV1`은 다음 Work Analysis 또는 Planning이 소비할 최소 공식 Handoff다. 복수 IN Route에서는 `source_statuses`가 각 Source의 확인 성공·부분 성공·실패·미시도를 보존해야 하며, downstream은 전체 `coverage`만 보고 모든 Source를 확인했다고 추론하지 않는다. `NEEDS_MORE_DATA`, `NEEDS_CONFIRMATION`, `ROUTE_RECONSIDERATION_REQUIRED`, `BLOCKED`는 `RetrievalResultV1`의 상태값이 아니라 `SubgraphReturnV2.disposition`과 Typed `WorkflowSignalV1`로 전달한다. 이미 확보한 Evidence가 독립적으로 유효하면 `coverage=PARTIAL` 결과와 redirection signal을 함께 반환할 수 있다.

## 7. 진입 방식

### RESOURCE_SELECTED

- Tool Route의 IN Resource를 사용자 선택 Resource에 고정
- 선택 ID를 검색 Query로 다시 추측하지 않고 최신 상세 GET
- exact direct-read Tool이 Registry에 있으면 선택 Resource의 detail route만 유지하며 같은 Resource 내부 검색을 위한 추측성 dependency route를 추가하지 않는다.
- 후보 점수와 무관하게 강제 포함
- 추가 Resource Route가 필요하면 Tool Route 재검토 또는 사용자 확인

### AGENT_SEARCH

- `RequestIntentV2` + frozen `input_routes` + `retrieval_budget` 기반 Source-native 검색. raw `run_input.user_request`는 Retrieval Local State/Prompt에 별도 Projection하지 않는다.
- Metadata Page에서 후보 축소
- RAG로 관련 Segment를 재선택
- 부족할 때만 같은 Route의 다음 Page·상세 조회 추가

## 8. Connector·Source 전략

Retrieval Core는 `connector_id + resource_type + allowed_read_tool_ids`에 따라 결정적 Query Builder와 `ConnectorReadPort`를 선택하며, Connector별 Source 전략은 Adapter/Tool 계약으로 구체화한다.

P0 Google Workspace Connector:

- Gmail: Thread 검색 → 참여자·제목·시각·Snippet 필터 → 상위 Thread 상세 → Message 시간순 정리 → Segment RAG
- Tasks: Task List 결정 → 목록 → 예정일·상태·Keyword 필터 → 필요한 상세 → Segment RAG
- Calendar: Calendar 결정 → 기간 Event 목록 → 필요한 상세 → 필요할 때 FreeBusy → Segment RAG

추가 Connector는 동일 Retrieval State·Evidence·Sufficiency 계약을 사용하되 Provider-native query/pagination/detail 전략만 Connector별로 확장한다.

### Tasks 시간 의미

- `TASK + CREATE`의 Policy Precondition Route는 기존 미완료 Task를 조회해 중복 판정에 필요한 후보와 Evidence를 Work Analysis에 제공한다. Retrieval 자체는 업무상 최종 중복 여부나 `action_necessity`를 확정하지 않는다.
- Google Task `due`는 Retrieval·WorkItem에서 `scheduled_date`로 정규화한다.
- 실제 업무 `business_deadline`은 Gmail·사용자 요청·Evidence에서 확인한 경우에만 별도 Evidence로 사용한다.
- Task `due`를 업무 마감 Evidence로 승격하거나 둘을 자동 동일시하지 않는다.
- 예정일 경과는 Provider 완료 상태의 근거가 아니다.

### Calendar Typed Query 계약

Calendar Route는 §5의 Release-canonical `RouteQueryIntentV2 + SemanticRetrievalConstraintV1 → SourceFetchPlanV1`을 그대로 사용한다. 별도 `calendar_read_mode`나 `temporal_query` DTO를 current contract로 만들지 않는다.

- Event 조회는 `RouteQueryIntentV2.operation=SEARCH|DETAIL_FETCH`, FreeBusy가 실제로 필요할 때만 `operation=FREEBUSY`를 사용한다. 한 Retrieval round에서 둘 다 필요하면 Query Planner가 typed Route intent를 순서대로 발급하고 deterministic `SourceFetchPlanBuilder`가 각각 materialize한다.
- 시간 범위는 `TemporalRangeConstraintV1(axis=EVENT_TIME|AVAILABILITY_WINDOW, start_local, end_local, timezone)`로 표현한다. relative weekday/daypart 해석은 Request Understanding/typed intent의 bounded semantics를 소비하고 실제 RFC3339 계산·Timezone 적용·interval arithmetic은 deterministic builder가 전담한다.
- Daypart canonical window는 사용자 Timezone 기준 `MORNING 06:00–12:00`, `AFTERNOON 12:00–18:00`, `EVENING 18:00–21:00`이다.
- 다른 Resource의 `business_deadline`을 Calendar Query 기준점으로 쓰려면 Work Analysis 결과를 받아 Additional Retrieval로 재진입해야 한다.

## 9. 후보 점수 초기값

```
정확 Resource·Thread 관계 +40
이메일·참여자 일치       +25
날짜 범위 겹침           +20
제목 정확 구문           +20
Keyword                   최대 +15
상태 적합성               +10
관련 Resource Link        +15
최신성                     최대 +10
```

점수는 Policy가 아니라 중앙 Retrieval Config와 평가 대상이다.

## 10. Segment·Evidence

분석·인물·주제 등 추가 조건이 없는 수신 기간 메일 목록은 provider의 timezone-aware
수신시각과 MESSAGE_TIME 범위를 비교하여 기존 bounded 후보를 선택한다. 본문 행사일이
검색 기간 밖이거나 뉴스레터라는 이유로 수신 조건을 만족하는 메일을 제외하지 않는다.
본문 의미 조건이 있으면 기존 semantic relevance 선택을 사용한다.

### 10.1 Stable SourceSegment identity

`segment_id`는 UI row용 임의 UUID가 아니라 **same provider source version을 다시 normalize/chunk했을 때 동일하게 재생성되는 deterministic Evidence identity**다. `05 Retrieval`이 이 identity semantics의 단일 owner다.

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

`segment_id = "seg_" + SHA256(canonical_json(SourceSegmentIdentityV1))`로 생성한다. `source_version_ref`는 Provider가 stable revision/version/etag를 제공하면 사용하고, 없으면 `normalized_content_sha256 + deterministic chunk_ordinal`이 version evidence를 대신한다. Normalize/Chunk algorithm과 `chunk_schema_version`은 같은 입력에 deterministic해야 한다. Random UUID, retrieval revision 번호, query/page ordinal, process-memory handle을 `segment_id` authority로 사용하지 않는다.

`connector_id + resource_type + resource_id`가 Provider Resource의 canonical identity authority다. `source_kind`는 deterministic normalization/source-family discriminator이며 Connector identity나 `resource_type`을 재선택·재추론하거나 Tool Route를 변경하는 authority가 아니다. 관측된 Connector/Resource에서 결정적 코드가 생성하며 LLM이 만들지 않는다.

GitHub Issue는 `connector_id="github"`, `resource_type="github_issue"`, `resource_id="owner/repository#issue_number"`를 계속 사용한다. `source_kind="github"`는 이 identity를 대체하지 않는다. `github_list_issues`의 각 Issue는 이 composite `resource_id`를 가진 독립 Resource observation이며 list 전체를 synthetic 단일 Resource로 만들지 않는다.

GitHub Issue의 Evidence 발췌는 Provider가 관측한 repository, issue number, title, state, URL을 본문과 구분해 보존한다. 본문 설명은 이 관측 identity나 존재 사실을 부정하는 authority가 아니다. Normalize는 기존 payload의 값만 표시하며 누락된 metadata를 추측하지 않는다. 이 형식 변경은 GitHub chunk schema를 갱신하고, 이전 Evidence/checkpoint는 기존 발췌와 identity 그대로 유지한다.

- 같은 Provider resource version + 같은 normalized content + 같은 chunk schema/boundary면 fresh Retrieval에서도 같은 `segment_id`를 생성한다.
- Provider source version/content 또는 chunk schema가 바뀌어 Evidence 의미가 달라지면 새 `segment_id`를 발급한다. 과거 exclusion을 변경된 content에 임의 승계하지 않는다.
- `EXCLUDE_EVIDENCE`는 선택 당시 current Preview의 stable `segment_id`만 허용한다. Application은 `expected_retrieval_revision` membership을 검증한다.

### 10.2 Segment·Evidence size · trust boundary

- Gmail Chunk 목표 600 Token, 최대 900 Token, Overlap 80 Token
- Token은 Provider-independent deterministic estimated token 단위다.
- Evidence excerpt UTF-8 8 KiB 이하
- Source 원문은 비신뢰 데이터
- 실제 계획에 사용된 최소 Evidence만 Domain Store에 저장

## 11. Context Budget

- System·Policy·Tool Schema 최대 15%
- 사용자 요청·대화 최대 15%
- 검색 Context 목표 50~55%
- Structured Output Reserve 최소 10%
- Safety Margin 최소 10%

Node Projection 규칙 때문에 Tool Route 전체·Registry 전체·후보 전체를 모든 Retrieval LLM 호출에 반복 삽입하지 않는다.

## 12. 추가 Retrieval

```
Round 0 정확 검색
Round 1 같은 IN Route에서 제약 하나 완화 또는 다음 Page/Detail
Round 2 같은 IN Route의 마지막 표적 확장
```

- 같은 IN Route 내부 확장은 Retrieval Subgraph가 소유한다.
- 사용자 지정 범위를 벗어나는 기간 확장은 확인을 우선한다.
- 새로운 Resource/Connector가 필요하면 `RouteReconsiderationRequiredV1`과 함께 `ROUTE_RECONSIDERATION_REQUIRED`를 Parent에 반환한다.
- 동명이인·대상 복수·사용자만 해결 가능한 정보는 추가 Google 조회보다 확인 질문을 우선한다.

## 13. 초기 API Budget

```
RETRIEVAL_PAGE_SIZE=<configured>
MAX_RETRIEVAL_ROUNDS=3
MAX_ADDITIONAL_RETRIEVAL_ROUNDS=2
MAX_PAGES_PER_SOURCE_PER_ROUND=2
MAX_TOTAL_SOURCE_PAGES=8
MAX_METADATA_CANDIDATES_PER_SOURCE=40
MAX_DETAIL_FETCH_PER_SOURCE=5
MAX_TOTAL_DETAIL_RESOURCES=12
```

## 14. Cache와 영속 경계

- Sidebar Cache: React Session Memory
- Run Retrieval Cache: 현재 Run Memory, Run 종료 시 폐기
- Main Graph State: `RetrievalResultV1`과 Cache/Evidence Reference만 저장
- 강제 최신 조회: RESOURCE_SELECTED 시작, Plan 확정 전, 승인 후 실행 전, 실행 후 Verification
- 저장 금지: 전체 Sidebar 목록, **Main State·Checkpoint·Domain DB·Trace·Audit·Prompt의 Raw Provider Page Token**, 미사용 후보, Gmail 전체 원문, FreeBusy 전체 응답, RAG 후보 전체와 score 전체

예외: Retrieval local pagination을 위한 raw Provider continuation은 **현재 Run의 Run Retrieval Cache read-result entry 내부에서만 memory-only**로 보관할 수 있다. Local State에는 raw token이 아니라 `read_result_handle`과 continuation state hash만 남기며 Run 종료 시 함께 폐기한다.

- 저장 허용: 실제 사용 ResourceRef, 최소 Evidence excerpt, Action 연결

## 15. Evaluation consumption boundary

`05 Retrieval`은 제품 Retrieval semantics와 runtime artifact만 소유한다. Dataset·Case·Fixture·Gold·`evaluation_item_id`·Candidate 비교 schema는 `13 Evaluation`이 소유하며 이 문서에서 복제하지 않는다.

평가가 Retrieval을 비교할 때는 current owner contract의 `ToolRoutePlanV2`, `RetrievalResultV1`, `QueryAttemptV1`, Evidence/Resource reference와 configured Retrieval identity를 소비한다. Backend 비교는 동일한 입력 Route·Fixture 조건을 유지하고 비교하려는 backend/config만 변경한다. Evaluation metadata는 Product Prompt, Main State, Checkpoint, Domain DB의 새로운 authority field가 될 수 없다.

## 16. QueryAttempt·Confidence·재검색 계약

이 절은 `15 Agent Capability · Failure · Prompt` current contract를 적용한다.

### 16.1 QueryAttemptV1

`QueryAttemptV1`은 이 문서가 소유하는 **유일한 Release current schema**다. `15 Prompt/Failure`는 이 타입을 소비·검증할 뿐 별도 `schema_version=1` payload를 정의하지 않는다.

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

- 같은 Query와 새로운 Page Token을 사용하는 `NEXT_PAGE`는 정상 Pagination이다.
- 실패 뒤 같은 Query와 같은 Page 상태로 `SEARCH`를 반복하면 `QUERY_UNCHANGED_AFTER_FAILURE`다.
- `DETAIL_FETCH` 재호출은 Run Cache 또는 Provider 기술 재시도 규칙을 따른다.
- 추가 Retrieval 시 최소 하나의 제약 변경 또는 같은 Route의 Page/Detail 확장이 있어야 한다.
- 새로운 Resource Route를 Local Retry로 몰래 추가하지 않는다.

### 16.3 저신뢰 후보

- Confidence Band는 `HIGH`, `MEDIUM`, `LOW`, `NONE`으로 고정한다.
- 실제 점수와 Threshold는 중앙 Retrieval Config가 소유한다.
- `AGENT_SEARCH`에서 `LOW` 또는 `NONE` 후보만 존재하면 자동 확정하지 않는다.
- `RESOURCE_SELECTED`는 사용자가 고른 Resource ID를 점수와 관계없이 상세 GET한다.
- 후보 1위와 2위의 점수 차이가 설정된 Margin보다 작으면 확인 또는 추가 Retrieval로 전환한다.

### 16.4 결정적 평가

다음 항목은 LLM Judge가 아니라 코드 Grader가 우선한다.

- ToolRoute의 허용 Read Tool 밖 호출 여부
- 사용자 날짜·사람·이메일·선택 Resource가 Query Spec에 반영됐는지
- 같은 실패 Query가 반복됐는지
- 추가 Retrieval 횟수와 Source Page Budget 준수
- 저신뢰 후보를 임의로 확정했는지
- RAG Top Candidate 밖 Evidence를 근거 없이 생성했는지

## 17. Clarification · Overbroad Retrieval

Retrieval의 `PersonCandidateV1(mention, identity, display_names, source_segment_ids)`는
관측 metadata의 표시 이름↔email 결합만 보존한다. 다른 메시지의 같은 email에 붙은 별칭은
합칠 수 있지만 surname/title만으로 서로 다른 email을 합치지 않는다. 이름만 지정한 요청은
metadata의 동일한 전체 이름에 직급이 붙은 경우에도 후보로 연결한다. 이름의 부분 문자열이나
성만으로 다른 전체 이름을 일치시키지 않으며, 동명이인의 email은 별도 후보로 유지한다. 이 bounded 후보는
Retrieval local checkpoint 및 `RetrievalResultV1.person_candidates`에 보존한다. 이전 artifact에
필드가 없으면 빈 후보로 취급하며, 후보의 source segment provenance가 제외된 경우 재사용하지 않는다.
복수 후보는 기존 Retrieval Confirmation 옵션으로 노출하고 선택 email은 해당 후보 집합에서만
수용한다. 유일 후보 또는 사용자 선택 후 같은 frozen Route에서 exact PARTICIPANT 후속 검색을
수행한다. 이것은 RequestIntent의 사용자 원문을 바꾸거나 LLM에게 email 생성 권한을 주지 않는다.

- 요청 자체에서 드러나는 모호성은 Request Understanding에서 확인한다.
- Tool Route가 불명확하면 Tool Route Subgraph가 확인한다.
- 동명이인·복수 Resource·저신뢰 후보처럼 검색 후 드러나는 모호성은 후보·차이와 함께 `NEEDS_CONFIRMATION`으로 보낸다.
- 전체 Mailbox·장기간 무제한 원문·모든 Workspace Source 전체 조회는 `BLOCKED`다.
- Calendar 시간 overlap은 conflict와 분리하며 관계 근거를 Work Analysis에 전달한다.

## 18. 정보 부족 분류와 결정적 종료 Guard

시간 역할은 RequestIntent의 typed 의미를 보존한다. 수신/발송 표현이 명확한 경우만
MESSAGE_TIME으로 보강하며, 알려진 행사 단어 목록에 없다는 이유로 EVENT_TIME을
MESSAGE_TIME으로 바꾸지 않는다. 역할이 미해결이면 received-time lowering을 하지 않는다.

인물 후보는 수집된 SourceSegment의 metadata와 명시적인 이름·이메일 연결을 근거로 만든다.
답변용 Evidence 선택이 다른 사람의 자료를 제외했더라도 실제 복수 후보를 단일 인물로
축소하지 않는다. 사용자 exclusion만 해당 후보 provenance를 철회할 수 있다.
확인된 선택은 `selected_person_identities`로 same-Run에서 보존하며 Planning의 답변
projection은 선택되지 않은 인물만의 근거를 제외한다. 원래 Run Evidence는 삭제하지 않는다.
분석이 필요하지 않은 날짜·인물 lookup도 선택된 근거의 의미를 Planning 답변으로 정리한다.
Evidence 원문 dump는 답변 생성을 대체하지 않는다. 인용된 ISO offset을 임의의 오전/오후·요일로 재계산하지 않는다.
`planning.compose_answer` V2 input의 optional `selected_person_identities`가 이 선택을
전달한다. 기존 호출·checkpoint는 필드 생략이 가능하며 natural-language intent를 위조하지 않는다.

행사 날짜의 연도가 원문에서 확정되지 않았으면 검색 기간의 연도를 사실로 승격하지 않는다.
선택된 Evidence의 연도 미확정 날짜(명시적 보고·집계 기간은 제외)는
`unresolved_event_dates`에 원문·Evidence
참조와 함께 전달한다. 다른 resource의 검색 시간 제약을 전파하지 않는다.
READ의 해당 날짜 범위는 PARTIAL이며 Retrieval finalization은 이를 coverage에 반영한다. Planning은 해당 근거를
요청에 대한 요약과 연도 미확정 안내로 제시하며, 필요한 날짜 원문만 인용할 수 있다. 뉴스레터 CONTEXT의 집계 기간이나 수신시각을
행사일로 사용하지 않는다. 구 checkpoint에서 이 선택 필드가 없으면 빈 목록으로 읽는다.

READ follow-up은 기존 RunBudget 안에서 답변 outline/compose와 bounded repair 여유를
남긴다. `analysis_requirement=REQUIRED`인 READ는 기존 Work Analysis의 여섯 semantic
operation도 같은 상한 안에서 고려한다. 부분 결과도 확보한 답변 예산 안에서 근거를 요약하며
전체 성공을 주장하지 않는다. 정상 no-result의 기존 결정적 projection은 유지한다.
추가 수집이 답변 여유를 침범하면 이미 검증된 Evidence를 보존해 PARTIAL로
닫는다. 결정적으로 종료할 수 있는 sufficiency는 LLM 호출을 요구하지 않으며 사용하지 않은
호출을 counter/Trace에 기록하지 않는다. WRITE의 필수 Target/Argument/Policy Evidence가
미확정인 경우 이 READ 최적화를 적용하지 않는다.

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

`CONNECTOR`는 current frozen Route가 가리키는 non-Google Connector에서 추가 deterministic Retrieval을 수행하면 해결 가능한 정보 부족을 뜻한다. Connector·Tool·Route 재선택, Provider autodiscovery 또는 새 routing authority를 허용하지 않는다. GitHub와 이후 non-Google Connector의 부족 정보는 `CONNECTOR`를 사용하며 `GOOGLE`로 표현하지 않는다.

외부 조회 부족 Issue는 `route_id`로 해당 frozen IN Route에 결합한다. source status와 Evidence도 같은 Route에 결합하며 같은 Connector의 성공 결과로 다른 Route의 실패·미시도를 덮지 않는다. 구 checkpoint의 route 없는 GOOGLE/CONNECTOR Issue는 해당 source의 frozen Route가 하나일 때만 호환 결합한다. 복수 후보 또는 Route 없는 back-edge need는 추측하지 않고 기존 ROUTE reconsideration으로 반환한다. USER/POLICY 전역 Issue는 route_id를 생략할 수 있다. policy 필수 조회의 실패·미시도는 safety-critical이며, 완료된 빈 중복/충돌 확인과 구분한다.

`GOOGLE`은 기존 Google Workspace producer·checkpoint·schema compatibility value로 유지한다. 이번 확장에서 기존 Google producer를 `CONNECTOR`로 migration하거나 `GOOGLE`을 rename·deprecate·remove하지 않는다. 두 값은 producer 범위는 분리되지만 deterministic termination guard에서는 current frozen Route의 추가 external Connector Retrieval로 해결 가능한 같은 class로 처리한다.

Sufficiency/LLM-local projection에서 coarse resource category가 필요하면 GitHub Issue에는 `ISSUE`를 사용할 수 있다. `ISSUE`는 canonical Connector `resource_type`이 아니며 `github_issue`를 대체하거나 `TASK`로 변환하지 않는다. 최종 `RetrievalResultV1.source_statuses[].resource_type`은 frozen Route의 exact `github_issue`를 보존한다.

### 18.2 결정적 종료 Guard

1. `required=true`이면서 safety-critical 또는 `resolution_source=POLICY`면 `BLOCKED`.
2. `resolution_source=USER`면 추가 external Connector 조회보다 `NEEDS_CONFIRMATION` 우선.
3. `resolution_source=ROUTE`면 `ROUTE_RECONSIDERATION_REQUIRED`.
4. `resolution_source`가 `GOOGLE` 또는 `CONNECTOR`이고 current frozen Route의 추가 fetch가 가능하며 Budget·lifecycle guard가 허용하면 `NEEDS_MORE_DATA`.
5. Budget 소진 + Read-only + 근거 있는 부분 답변 가능이면 `PARTIAL`.
6. Write 필수 Target/Argument/Evidence 부족은 사용자 해결 가능하면 `NEEDS_CONFIRMATION`, 아니면 `BLOCKED`.

LLM confidence 하나로 안전 Route를 결정하지 않는다. 모든 Graph Profile은 동일 Guard를 사용한다.

## 19. Gmail Attachment Retrieval 경계

- Gmail Message 상세의 첨부파일은 `filename`, `mime_type`, `size_bytes`, Google `attachment_id` Metadata까지만 Retrieval 후보 정보로 사용할 수 있다.
- `gmail_get_attachment(message_id, attachment_id)`는 사용자 다운로드 또는 결정적 파일 전달 요청에서만 실행한다.
- 첨부파일 bytes는 Retrieval Cache·SourceSegment·EvidenceDraft·ContextBundle에 넣지 않는다.
- 첨부파일 내용을 읽어 Evidence로 만드는 기능은 P0 범위 밖이다.
- Attachment Download는 LLM 재검색·추가 Retrieval Budget과 분리된 결정적 READ I/O다.
