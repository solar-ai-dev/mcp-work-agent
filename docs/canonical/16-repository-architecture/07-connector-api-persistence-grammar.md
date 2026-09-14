# 07. Connector · API · Persistence Grammar

**상태:** CANONICAL

이 문서는 boundary placement grammar를 소유한다. Tool schema와 API field의 의미는 `07 Tool·MCP·Internal Interface`, DB invariant는 `04 Domain·Database Design`이 소유한다.

## Port and Adapter

```text
ports/<boundary>/<capability>_port.py
adapters/<boundary>/<provider-or-technology>/<responsibility>.py

ports/persistence/<owner>_repository.py
adapters/persistence/sqlite/repositories/<owner>_repository.py
```

Port는 Core가 필요한 capability contract만 표현하고 concrete provider, SDK, path, subprocess option을 노출하지 않는다. Application은 Port에 의존하고 composition root만 concrete Adapter를 결속한다. 단순 forwarding adapter chain이나 generic repository/manager를 만들지 않는다.

## Connector

```text
adapters/connectors/<provider>/<product>/<resource>/<verb>_<resource>.py
adapters/connectors/<provider>/<product>/mcp_server/{entrypoint,composition}.py
adapters/connectors/<provider>/<product>/mcp_server/dispatch_tool.py
adapters/connectors/<provider>/<product>/mcp_server/project_registry.py
adapters/connectors/<provider>/<product>/mcp_server/validate_claim_context.py
adapters/connectors/<provider>/<product>/mcp_server/credential_provider.py
```

Provider READ/WRITE, credential application, MCP process/transport는 Connector Adapter가 소유한다. Tool semantic metadata, policy, approval, Claim, lifecycle은 Core owner가 소유한다. READ를 승인형 WRITE lifecycle로 보내지 않으며 WRITE는 validated binding과 committed Claim context 없이는 dispatch하지 않는다.

Google과 GitHub는 같은 connector-neutral Port/Tool/Workflow 구조를 소비한다. provider별 Graph, Main State, lifecycle authority를 만들지 않는다. GitHub Device Flow와 Google OAuth credential은 각각 독립된 Adapter 경계다.

## API

```text
api/routes/<plural_resource>.py
api/schemas/<plural_resource>/<verb>_<object>.py
api/dependencies/<concern>.py
api/security/bootstrap_session.py
api/composition.py
api/app.py
```

Route는 wire validation/translation과 injected handler 호출만 수행한다. API Request/Response와 Application Command/Query를 같은 타입으로 중복 정의하지 않되 실제 boundary가 있으면 명시적으로 변환한다. state transition과 DB/Adapter 호출을 Route에 두지 않는다.

## Persistence and transactions

Repository는 owner aggregate/fact의 필요한 query와 compare-and-set mutation만 제공한다. `UnitOfWork`는 begin/commit/rollback만 소유하며 Domain guard와 외부 I/O 의미를 갖지 않는다. Approval/Claim/Attempt/Verification/Recovery의 coupled fact는 owning Application command의 짧은 transaction에서 기록한다.

Connector/Provider/MCP/LLM/filesystem/subprocess I/O 중 SQLite write transaction을 유지하지 않는다. `BeginExecutionAttempt(applied=true)` commit 전 WRITE는 0이고, dispatch 뒤 결과는 별도의 짧은 UoW로 분류·저장한다. Verification reread와 `UNKNOWN_RESULT` lookup도 transaction 밖에서 수행한다.

## Registries and manifests

Installed Connector manifest, signed Tool registry, Connector tool projection, Prompt manifest/source/input contract, Release/Model manifest는 runtime이 소비하는 실행 artifact다. 각 schema/loader authority를 하나만 두고 release hash/signature chain을 보존한다. 이 문서는 그 row 전체를 복제하지 않는다.

Connector runtime, Tool semantic registry, Prompt registry, Node/resume/profile registry는 scope가 다르므로 분리한다. generic registry/service locator로 합치지 않는다.

## Resource access

Settings inventory 조회와 선택된 업무 데이터 조회를 구분한다. Calendar, Task List, GitHub Repository allowlist는 모든 Browse/Retrieval/READ/WRITE의 상한이다. Run의 명시 Resource는 그 안에서만 좁혀지며, 복수 allowlist에서 WRITE target을 첫 항목으로 고르지 않는다. Adapter는 Provider permission과 Settings allowlist를 모두 검증한다.

## Runtime model boundary

Local AI는 설치된 지원 모델 `qwen3.5:9b`, `qwen3.5:4b`의 상태를 읽는 Adapter를 사용한다. 제품은 Ollama 설치, model pull, download/provisioning을 수행하지 않는다. LLM caller는 concrete model/provider를 직접 선택하지 않고 Runtime Router가 current Run binding과 readiness를 검증한다. Local과 Gemini 사이 자동 전환은 없다.
