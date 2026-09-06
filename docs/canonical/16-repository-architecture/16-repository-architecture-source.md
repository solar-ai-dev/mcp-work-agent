# 16. Repository Architecture Source

**목적:** repository에서 ownership, responsibility, dependency direction, production authority를 일관되게 표현한다.

**Authority:** directory ownership, naming/placement grammar, Port/Adapter boundary, import/export direction, single production authority, 구조 enforcement

**상태:** CANONICAL

**수정일:** 2026-09-07

## Mandatory invariants

```text
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```

현재 파일 배치는 그 자체로 architecture 권위가 아니다. 새 production capability를 만들기 전에 concern owner의 계약과 기존 implementation, caller, test, DI를 검색한다. 같은 capability의 두 번째 live authority가 생기면 구현하지 않고 기존 owner를 수정하거나 완전한 cut-over를 수행한다.

## Layer responsibilities

| Layer | Owns | Must not own |
| --- | --- | --- |
| Domain | invariant, lifecycle/state semantics | Application orchestration, Adapter, Provider SDK |
| Policy | deterministic allow/block/approval/safety | LLM 추정, Provider I/O |
| Application | use case와 transaction orchestration | concrete Adapter 선택·직접 import |
| Workflow/LangGraph | State, Node/Edge/Interrupt/Resume orchestration | Domain transition 재구현, concrete SQLite/Provider I/O |
| Port | boundary contract | concrete integration |
| Adapter/Connector | Provider SDK, SQLite, subprocess 등 concrete realization | 제품 정책·workflow authority |
| API | protocol validation/translation | DB/Adapter concrete와 business decision |
| Frontend | user interaction과 backend projection 표시 | policy, execution, ownership inference |
| Composition Root | construction, DI, lifecycle wiring | business behavior |

금지 dependency는 Domain→Application/Adapter/API, Application→concrete Adapter, FastAPI Route→DB/Adapter concrete, LangGraph→SQLite/Provider SDK, Connector→Application workflow, Product Runtime→Evaluation이다. 외부 I/O 중 SQLite write transaction을 유지하지 않는다.

## Semantic ownership

Domain owner는 `conversation`, `message`, `run`, `plan`, `action`, `approval`, `claim`, `execution_attempt`, `verification`, `recovery`, `resource_ref`, `evidence`, `command_receipt`, `policy_confirmation_receipt`다. Agent owner는 `request_understanding`, `tool_routing`, `retrieval`, `work_analysis`, `planning`, `review`다. 새 synonym owner나 `manager`, `service`, `common`, `utils` 같은 generic bucket을 만들지 않는다.

이 vocabulary는 behavior를 정의하지 않는다. Agent 책임은 `06 Agent Workflow`와 `15 Agent Capability·Failure·Prompt Contract`, lifecycle은 `04-A`, persistence invariant는 `04`, API schema는 `07`이 소유한다.

## Placement and naming grammar

```text
domain/<owner>/model.py
domain/<owner>/transitions/<verb>_<object>.py
domain/<owner>/guards/<verb>_<object>.py

application/use_cases/<owner>/<verb>_<object>.py
application/agents/<agent_owner>/<verb>_<object>.py
application/agents/<agent_owner>/contracts/<artifact_name>.py

ports/persistence/<owner>_repository.py
adapters/persistence/sqlite/repositories/<owner>_repository.py
ports/<boundary>/<capability>_port.py
adapters/connectors/<provider>/<product>/<resource>/<verb>_<resource>.py

api/routes/<plural_resource>.py
api/schemas/<plural_resource>/<verb>_<object>.py
api/dependencies/<concern>.py

adapters/langgraph/main/{state,graph}.py
adapters/langgraph/main/routing/route_after_<stage>.py
adapters/langgraph/main/nodes/<responsibility>_node.py
adapters/langgraph/subgraphs/<agent_owner>/{state,graph}.py
adapters/langgraph/subgraphs/<agent_owner>/routing/route_after_<stage>.py
adapters/langgraph/subgraphs/<agent_owner>/nodes/<responsibility>_node.py

frontend/src/app/                         # shell/startup/session composition
frontend/src/features/<owner>/            # feature-owned UI/API/projection
frontend/src/ui/                          # presentation primitive only
```

Operation-per-file은 실제 독립 책임에 적용한다. cohesive invariant/model을 LOC만으로 분할하지 않는다. 반대로 서로 다른 command/query, semantic Agent responsibility, route, external operation을 broad module에 합치지 않는다.

Application use case의 public handler는 `<Verb><Object>Handler`, Agent operation은 filename과 같은 snake_case callable을 사용한다. generic `DTO` 대신 Command, Query, Result, Request/Response, Candidate, Draft, Snapshot, Projection, Receipt, Ref, Policy, Guard, Validator, Resolver, Builder, Assembler, Mapper, Normalizer, Registry, Repository, Port, Adapter로 실제 역할을 드러낸다.

## Ports, adapters, and composition

Application은 Port만 소비한다. Provider SDK, SQLite, filesystem, keyring, subprocess, browser/process control은 concrete Adapter에 둔다. `api/composition.py`의 `build_production_runtime()`이 유일한 concrete binding authority이고 `api/app.py`는 구성된 runtime의 lifecycle만 연결한다. Route와 LangGraph node는 injected Application/Port contract를 호출하는 얇은 adapter다.

Registry는 등록 범위가 다른 경우에만 분리한다. Connector runtime, Tool metadata, Prompt bundle, Graph node/resume/profile registry를 generic service locator로 합치지 않는다.

## LangGraph and state

Domain Store는 승인·실행·검증 사실의 권위, Checkpoint는 workflow resume 위치, UI/SSE/Trace는 projection이다. Node는 입력 projection, owner 호출, 결과 projection만 수행한다. state/transition/approval/write/verification/recovery 의미를 node나 edge에 복제하지 않는다. logical decision은 Agent/Application owner가 하고 physical edge는 등록된 결과를 연결한다.

## Single authority and compatibility

같은 의미의 V1/V2/Canonical implementation을 동시에 live production authority로 유지하지 않는다. Compatibility는 migration 중 필요한 얇은 delegate/re-export만 허용하고 business logic을 소유하지 않는다. 교체 시 production callers와 DI를 먼저 새 owner로 연결한 뒤 old implementation/import/export를 제거한다. 필요한 wire/checkpoint/history compatibility는 owning contract에 이유와 종료 조건을 둔다.

## Frontend boundary

Frontend는 backend가 제공한 typed owner, identity, order, policy/execution state를 표시한다. 텍스트나 SSE 도착 순서로 Agent owner, 승인 상태, 성공, WRITE target을 새로 판정하지 않는다. API module은 `/api/v1` transport와 projection만 소유한다. feature 간 공유를 이유로 business logic을 generic common/service/utils에 옮기지 않는다.

## Refactor and tests

분해는 LOC가 아니라 책임 혼합을 근거로 한다. production caller까지 cut-over하고 old authority를 제거한다. 테스트는 기능/owner/contract 단위로 두며 test 간 private helper import를 금지하고 반복 fixture는 의미 있는 owner 아래 `tests/support` 또는 `tests/fakes`에 둔다.

Obsolete·동일 계약 중복·과거 구현 전용 테스트는 현재 production path와 coverage를 확인한 후 제거할 수 있다. Approval, Claim, write-once, Verification, `UNKNOWN_RESULT`, Recovery, Reauth, architecture safety는 유지한다. assertion/allowlist를 약화하거나 skip/xfail로 실패를 숨기지 않는다.

## Executable contract preservation

Runtime Prompt source, Tool/model/release manifest와 schema/hash, API·typed contract source, checkpoint compatibility, evaluation dataset/runner/grader, fixture, 적용 migration은 문서 inventory가 아니다. 실행 소비 여부를 확인해 보존하며 migration은 수정·재번호·이동·squash하지 않는다.

## Subordinate rules

- [Directory Ownership](02-directory-ownership.md)
- [Naming Grammar](03-naming-grammar.md)
- [Artifact Taxonomy](04-artifact-taxonomy.md)
- [Dependency / Import / Export Rules](05-dependency-import-export-rules.md)
- [LangGraph / State Ownership](06-langgraph-state-ownership.md)
- [Connector / API / Persistence Grammar](07-connector-api-persistence-grammar.md)
- [Single Production Authority / Compatibility](08-single-production-authority-compat.md)
- [Test / Fixture / Migration Grammar](09-test-fixture-migration-grammar.md)
- [Error / Event / Configuration Naming](10-error-event-configuration-naming.md)
- [Structural Refactor Playbook](11-structural-refactor-playbook.md)
- [Architecture Enforcement](12-architecture-enforcement.md)
- [Exception Registry](13-exception-registry.md)

Subordinate 문서는 이 Source를 구체화할 뿐 제품 behavior나 current code inventory를 별도 소유하지 않는다.
