# 06. LangGraph · State Ownership

**목적:** Workflow 의미를 복제하지 않고 LangGraph 구현의 ownership, placement, dependency와 single-authority 규칙을 정의한다.

**Authority:** Repository Architecture의 LangGraph·State 배치 문법

**상태:** CANONICAL

**수정일:** 2026-09-07

## 1. Semantic owner

Main Graph routing은 결정적이며 전문 의미 owner는 `request_understanding`, `tool_routing`, `retrieval`, `work_analysis`, `planning`, `review`다. Runtime Node ID, State field, edge, interrupt, resume 의미는 `06 Agent·Workflow`, PromptRef는 `15 Agent·Prompt`가 소유한다. 이 문서는 그 목록이나 실행 순서를 재정의하지 않는다.

초기 Connector prerequisite는 하나의 Application use case가 소유한다. Tool Routing과 Request Understanding의 기존 Node는 확정된 Connector/Registry 입력을 전달하고 typed admission 결과만 State에 projection한다. 각 Node가 OAuth 정책을 복제하거나 Provider별 Main branch, Prompt field, Domain auth-wait 상태를 만들지 않는다.

## 2. Placement grammar

```text
application/agents/<semantic_owner>/<verb>_<object>.py
adapters/langgraph/main/routing/route_after_<stage>.py
adapters/langgraph/subgraphs/<semantic_owner>/nodes/<verb>_<object>_node.py
adapters/langgraph/subgraphs/<semantic_owner>/projections/<verb>_<object>_projection.py
adapters/langgraph/subgraphs/<semantic_owner>/routing/route_after_<stage>.py
```

Catch-all production `routing.py`, broad Agent service, generic node manager는 허용하지 않는다. Router symbol은 `route_after_<stage>()`, Node symbol은 의미 operation을 드러내는 이름을 사용한다.

## 3. Thin Node boundary

LangGraph Node는 다음만 수행하는 Adapter다.

```text
typed input projection
→ owner-local Application semantic call
→ typed owner-field patch
→ 필요한 경우 WorkflowSignal
```

Node는 business/policy 의미, concrete persistence, Provider SDK/API, 외부 Write, Domain transition authority를 소유하지 않는다. 외부 I/O가 필요한 deterministic Node는 Application use case를 호출하고 Application은 Port를 사용한다.

Runtime Node와 Application operation은 서로 다른 namespace다. 하나의 deterministic Node가 여러 owner-local validation/assembly operation을 호출할 수 있고, supporting operation이 별도 파일에 있다는 이유만으로 새 Node·router·checkpoint·resume target이 되지 않는다. 반대로 실제로 독립된 semantic Agent execution은 broad Node 하나에 합치지 않는다.

## 4. State ownership

- Main State에는 downstream이 소비할 versioned typed result와 workflow control fact만 둔다.
- invocation-local candidate, LLM intermediate, RAG score, raw continuation은 owning Subgraph Local State 또는 지정 Run cache에 둔다.
- Domain Store는 approval·execution·verification 사실, LangGraph checkpoint는 resume 위치, Activity/SSE는 projection이다.
- Node는 자기 owner field만 patch하며 다른 Agent 결과나 Domain truth를 직접 수정하지 않는다.
- 이전 Run의 Message/Evidence/Plan/Approval/Activity를 새 Run의 hidden semantic memory로 주입하지 않는다.

## 5. Registry single authority

`NodeRegistry`는 compiled graph의 current Node identity와 semantic-owner/profile binding을 조회하는 단일 production authority다. `ResumeTargetRegistry`는 `06 Agent·Workflow`가 허용한 node boundary와 main control stage의 safe-resume reference를 발급·검증하는 단일 authority다.

- graph version/profile/owner/node/stage가 없거나 stale하면 fail-closed한다.
- Subgraph-local lookup dict, profile별 중복 registry, checkpoint Adapter의 별도 target table, free-string resume target을 금지한다.
- supporting deterministic operation은 Workflow owner가 topology를 versioning하지 않는 한 registry target으로 추가하지 않는다.
- external Write dispatch 단계는 임의 resume target이 아니다. 실행 사실을 먼저 Domain에서 reconcile하고 Verification/Recovery 경계를 따른다.

현재 registry set은 문서의 file/symbol/test 표가 아니라 compiled definitions와 production composition에서 생성한다. Architecture test는 실제 source/registry/caller를 비교하고 모든 Node를 열거한 별도 spec-to-code snapshot을 읽지 않는다.

## 6. Activity와 terminal control

Activity callback은 실제 LangGraph execution identity와 typed output을 Application의 Activity 기록 경계로 전달하는 관측 Adapter다. UI 문구, Domain transition, 두 번째 Event Store, 새 Graph node를 소유하지 않으며 기록 실패가 업무 명령을 재실행하거나 실패시키면 안 된다.

Terminal control은 `RESPONSE_SYNTHESIS → TERMINAL_COMMIT → FINALIZE`의 기존 책임 분리를 유지한다. 응답 합성은 terminal intent를 만들고, commit은 owning lifecycle handler를 한 번 적용하며, finalize는 commit 이후 Trace/SSE만 방출한다. 이 control stage를 semantic Agent owner로 표시하지 않는다.

## 7. Enforcement

Architecture gate는 실제 source tree와 import graph를 기준으로 다음을 검사한다.

- Node/Projection/Router의 owner-local naming과 operation-per-file 책임
- Node의 Application Port 경유와 concrete Adapter/Provider/SQLite 의존 0
- Node/Resume registry production authority 하나와 stale/free-string target 0
- production caller cut-over, legacy import/export, duplicate authority
- Activity·terminal callback이 business execution authority를 갖지 않음

Runtime Node나 safe-resume set이 변경되면 owning Workflow contract와 graph/checkpoint compatibility를 먼저 갱신한다. 이 문서에는 현재 파일·심볼·테스트 inventory를 복제하지 않는다.
