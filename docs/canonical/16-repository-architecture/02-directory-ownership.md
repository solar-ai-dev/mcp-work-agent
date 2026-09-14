# 02. Directory Ownership

**상태:** CANONICAL

Directory는 semantic owner 또는 기술 boundary를 드러낸다. 현재 파일 inventory를 이 문서에 고정하지 않는다.

## Top-level roots

```text
src/google_work_agent/{domain,application,ports,adapters,api}/
launcher/
frontend/
installer/
release/
evaluation/
tests/
docs/
```

- `domain/`: lifecycle와 invariant
- `application/`: use case, Agent semantic operations, 좁은 runtime registry
- `ports/`: persistence와 outbound boundary contract
- `adapters/`: SQLite, Connector, LLM, LangGraph, system concrete realization
- `api/`: FastAPI protocol와 composition entry
- `launcher/`: installed/development process orchestration
- `frontend/`: React application과 feature UI
- `installer/`, `release/`: product runtime이 import하지 않는 build/signing source
- `evaluation/`: public Product boundary의 외부 소비자; Product Python internals import 금지

## Core placement

Domain transition과 guard는 `domain/<owner>/transitions|guards/<operation>.py`, Application use case는 `application/use_cases/<owner>/<operation>.py`, Agent operation은 `application/agents/<agent_owner>/<operation>.py`에 둔다. Agent-local contracts는 해당 owner의 `contracts/`에 둔다. global catch-all `contracts/`, `workflows/`, `services/`, `common/`을 semantic owner로 만들지 않는다.

Cross-Agent Prompt와 Tool registry는 각각 `application/prompt_runtime/`, `application/tool_registry/`의 좁은 구조 authority다. 이들은 Agent semantics, provider selection, policy, lifecycle을 소유하지 않는다.

## Boundary placement

Persistence Port와 SQLite adapter는 owner 이름을 mirror한다. Connector provider operation은 `adapters/connectors/<provider>/<product>/<resource>/`에, LLM leaf는 `adapters/llm/<provider>/`에 둔다. Provider SDK, process, filesystem, keyring 구현은 Adapter 밖으로 나오지 않는다.

Service composition은 `api/composition.py`, FastAPI lifecycle은 `api/app.py`가 소유한다. Route/dependency module은 concrete Adapter를 조립하지 않는다. Launcher는 서비스 process와 browser/session bootstrap을 조정할 뿐 Application handler나 Registry의 두 번째 composition root가 아니다.

## LangGraph placement

Main graph와 각 Agent subgraph는 `{state.py, graph.py, nodes/, routing/, projections/}`로 역할을 구분한다. Node, route, projection은 실제 책임 단위 파일이며 broad `routing.py`나 Agent business service로 합치지 않는다.

## Frontend placement

`frontend/src/app/`은 router, shell, startup, session composition만 소유한다. `frontend/src/features/<owner>/`는 feature interaction/API/projection, `frontend/src/ui/`는 presentation primitive만 소유한다. policy, workflow, execution authority는 backend에 남긴다.

## Tooling and evaluation

Installer/release 파일은 책임별 operation으로 유지하되 이 문서에 모든 filename/symbol/test를 열거하지 않는다. `evaluation/`은 dataset, config, prompt candidate, public client, runner, grader, result를 한 root에서 관리하며 Product Runtime에 두 번째 implementation이나 fake production authority를 만들지 않는다.

## Tests and migrations

Production owner test는 `tests/unit|integration|contract|architecture` 아래 동일 concern을 식별할 수 있게 둔다. fixture는 provider/resource/scenario 또는 기능 owner를 드러낸다. 적용 migration은 기존 번호와 checksum을 유지한다.
