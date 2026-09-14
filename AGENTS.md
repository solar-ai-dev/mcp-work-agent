# mcp-work-agent — Codex Instructions

이 `AGENTS.md`는 저장소 루트 전체에 적용한다.

하위 `AGENTS.md`는 경로별 규칙을 추가할 수 있지만 이 파일의 현재 제품 요구 우선순위와 안전·ownership 규칙을 약화시키면 안 된다.

## Authority

* Repository는 `solar-ai-dev/google-work-agent`, 작업 브랜치는 `product/issue-181-runtime-closure`다. 모든 작업은 현재 remote/local HEAD와 working tree를 확인한 뒤 그 상태를 기준으로 진행한다.
* 과거 SHA, 이전 완료 보고, 닫힌 Issue는 참고 자료일 뿐 작업 기준점이나 STOP 조건이 아니다. 과거 SHA로 reset/revert하지 않는다.
* 현재 제품 코드와 실제 동작을 우선 확인한다. 기존 Canonical과 현재 제품 요구가 충돌하면 이번 제품 요구를 구현한다. 충돌과 필요한 계약 변경을 명시하고, 문서·계약 갱신 시점은 아래 Contract / Compatibility 규칙을 따른다.
* 항상 `00 Project Source Guide`에서 Concern Owner와 선행 읽기 순서를 먼저 확인한다.
* behavior는 해당 Concern Owner가 소유하고, repository path/file/symbol/import/single-authority 규칙은 `16 Repository Architecture`가 소유한다.
* 현재 구현만으로 새로운 target architecture를 추측하거나 state/transition/edge/resume target, lifecycle, owner, Port, operation, contract/type을 임의로 만들지 않는다.
* 적용된 Migration은 수정하지 않는다. 필요한 DB 변경은 forward Migration으로 추가한다.

## Current Work Mode

현재 작업은 **명시적으로 요청한 기능과 확인된 결함을 닫는 제품 완성 작업**이다.

* 명시적으로 요청한 신규 기능은 구현한다. 요청 밖의 변경은 직접 관련된 실제 결함이 확인된 경우에만 최소 수정하며, 권한이나 범위 확대가 필요하면 먼저 확인한다.
* 기존 owner, Port, typed contract, LangGraph 구조를 최대한 재사용한다. 이미 정상인 기능은 다시 만들거나 불필요하게 rewrite하지 않는다.
* 작업 단위는 파일이 아니라 **semantic capability**다.
* Canonical reconciliation을 이유로 기능 수정을 구조 전체 리팩터링으로 확대하지 않는다. 무관한 cleanup, formatting-only 대형 diff, dependency-wide upgrade를 하지 않는다.

## Work Procedure

각 capability의 구현은 다음 순서로 처리하고, 테스트 실행은 아래 프롬프트 단위 검증 순서로 모은다.

```text
현재 HEAD / working tree / 제품 요구 확인
→ 기존 Owner와 Canonical 계약 확인 (충돌 시 현재 제품 요구 우선)
→ 기존 implementation / caller / test / DI 검색
→ KEEP | MOVE | MERGE | REWRITE | DELETE | CREATE 판정
→ 실행 계약 변경이 있으면 정의와 영향 범위 확인
→ 요청한 기능 / 확인된 결함 구현 (교체가 필요한 경우만 cut-over)
→ production caller / consumer 연결 확인
→ 이번 교체로 불필요해진 old authority / import / export만 제거
→ 직접 영향 검증과 제품 검증 → 필요한 수정 → 재검증
```

규칙:

* 새 production file을 만들기 전에 동일 capability의 기존 구현을 먼저 찾는다.
* capability의 caller·consumer까지 연결한 완결 변경을 우선한다. 기존 owner를 유지한 기능 수정에 불필요한 cut-over를 요구하지 않는다.
* 제공되지 않은 후속 단계의 범위를 임의로 만들거나 자동 진행하지 않는다.

## Architecture / Ownership

```text
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```

* Domain: invariant와 lifecycle/domain semantics
* Policy: deterministic allow/block/approval/safety
* Application: use case와 transaction orchestration
* Workflow/LangGraph: State, Node/Edge/Interrupt/Resume orchestration
* Port: 외부 boundary contract
* Adapter/Connector: concrete integration
* API: protocol validation/translation
* Composition Root: construction/DI/lifecycle wiring only

금지:

* Core → Provider SDK/API direct call
* Application → concrete Adapter
* Domain → Application/Adapter
* FastAPI Route → DB/Adapter concrete
* Agent → Provider API/SDK
* Agent → peer Agent direct call
* Agent/LLM → external Write authority
* speculative abstraction
* second live production authority
* 단순 forwarding만 늘리는 wrapper/adapter chain

## Contract / Compatibility

Canonical은 기존 구조 위에 추가되는 새 계층이 아니다.

* API/schema/state의 실행 계약은 변경 정의와 영향 범위를 먼저 확인하고 producer·consumer·validator·테스트를 같은 변경 단위에서 즉시 갱신한다. Prompt/manifest/hash, persistence migration, checkpoint·호환 처리도 직접 영향이 있으면 함께 갱신한다. 실행 정합성에 필요한 계약 변경을 최종 단계까지 미루지 않는다.
* 전체 Canonical 설명과 문서 간 동기화는 최종 단계에서 현재 제품에 맞춰 수행한다. 문서를 먼저 기준으로 새 제품 요구를 되돌리지 않는다.
* 같은 의미의 V1/V2/Canonical implementation을 동시에 production authority로 유지하지 않는다.
* compatibility는 migration 중 필요한 얇은 delegate/re-export만 허용하며 business logic을 소유하지 않는다.
* 실제로 기존 구현을 교체한 경우에만 old authority/caller/path/import/export와 불필요한 temporary compatibility를 제거한다. 필요한 잔여 compatibility는 명시적 migration dependency로 기록하며 다른 작업의 초안은 삭제하지 않는다.
* `R1`, `R2`, `R2.1`, `Wave`, `Phase` 같은 구현 단계는 장기 production architecture로 남기지 않는다.

같은 business fact를 단순 Layer 이동 때문에 별도 DTO/type으로 반복 정의하지 않는다. 새 representation은 실제 boundary가 있을 때만 추가한다.

## State / Workflow / Write Safety

* Domain Store는 승인·실행·검증 사실의 기준점이다.
* LangGraph Checkpoint는 workflow resume 위치다.
* UI/SSE/Trace는 Projection이며 Domain truth가 아니다.
* external MCP/Provider/LLM I/O 중 SQLite write transaction을 유지하지 않는다.
* Write는 Canonical Approval → Claim → BeginExecutionAttempt → Connector Write → Verification/Recovery 경계를 따른다.
* `BeginExecutionAttempt(applied=true)` commit 전 Connector Write는 0이어야 한다.
* `UNKNOWN_RESULT`에서는 blind resend나 새 Write Attempt를 만들지 않는다.
* Agent/LLM이 approval, policy, state transition, execution success를 최종 판정하지 않는다.

## Tests / Gates

* 기본 검증 단위는 한 프롬프트의 작업 범위다. 계약·테스트 코드는 구현과 함께 갱신하고, 범위의 구현을 마친 뒤 직접 영향 자동 테스트와 architecture/type/lint 검사를 모아 수행한다. 필요한 pytest·API·노드 테스트는 중간에도 수행할 수 있으나 같은 대형 테스트 묶음이나 앱 재시작을 개별 기능마다 반복하지 않는다.
* 노드 입출력 계약 테스트는 반드시 수행한다. 특히 WRITE는 노드 간 값·형식, 승인 인자와 실행 인자의 보존, 실행 안전 경계를 검증한다.
* 자동 테스트만으로 제품 PASS를 선언하지 않는다. 평소에는 작업에 적합한 production LangGraph 실행 스크립트와 실제 Local LLM/MCP/Provider로 검증한다. 가능하면 production Graph/Node/Router/Application 경계를 유지하고 필요한 외부 의존성만 Fake/Stub 처리한다. 실제 호출 순서·routing/continuation·주요 상태 변화·최종 Typed Result를 근거로 남기며, Fake/Stub 검증과 실제 Provider 검증을 구분한다.
* Browser는 UI 변경 검증, 사용자의 명시적 요청, 최종 전체 E2E에 사용한다. 전체 Browser E2E와 전체 회귀는 지정된 최종 단계로 모으되, UI 검증까지 일괄 금지하지 않는다.
* 일부 Live Provider, Credential, Device Flow, signing key 등의 외부 조건이 없어 특정 검증을 못 해도 작업 전체를 중단하지 않는다. 가능한 구현·테스트·제품 검증은 계속하고, 실제 secret/private key 등 필수 외부 조건이 없어 수행할 수 없는 최종 검증만 BLOCKED로 분리한다. 미수행 검증을 PASS로 쓰지 않는다.
* 실제 검증 실패나 안전성 문제가 확인되면 기능 범위를 확장하지 않고 원인 수정 후 실패 시나리오와 직접 영향 경로를 재검증한다. 관련 safety/contract/state test가 깨진 상태를 완료라고 보고하지 않는다.
* 기존 테스트도 제품 요구의 Authority가 아니다. 현재 제품 요구와 observable behavior, state transition, safety invariant, external effect를 검증한다. 충돌하는 테스트는 KEEP | REWRITE | DELETE를 판정하되 결함을 숨기거나 구조 위반을 정당화하기 위해 검사나 enforcement를 완화하지 않는다.
* production source 문자열이나 private method 내부 구현을 직접 검사하는 테스트는 피한다.
* 테스트 파일끼리 private helper를 import하지 않는다. 반복되는 fixture/fake는 `tests/support` 또는 `tests/fakes`로 이동한다.
* 구조 Gate는 위 Architecture / Ownership의 금지 의존성, 중복 production authority, 외부 I/O 중 SQLite write transaction 유지가 모두 0임을 검증한다.
* 실험·Smoke·진단의 사람이 읽는 보고서, summary/comparison JSON, safe trace projection, 전달용 ZIP은 모두 `evaluation/results/<주제>-<YYYYMMDD>/`와 그 바로 옆 ZIP에 둔다. `.runtime`과 `runtime`은 DB·checkpoint·replay·로그 같은 실행 상태만 소유하며 그 아래 `reports`/`results` 폴더를 만들지 않는다.

## Completion

Capability는 다음을 만족해야 완료다.

* 현재 제품 요구를 만족하는 구현이 production caller·consumer에 연결됨
* 위 ownership·compatibility·state/transaction safety 규칙 준수; 교체한 경우에만 old authority 제거 확인
* 직접 영향 검증과 적합한 제품 검증 수행, 남은 검증은 아래 상태로 분리

## Git / Scope

* 사용자의 상시 승인에 따라 각 프롬프트 작업 완료 시 해당 범위의 검증된 변경을 기능 경계별 coherent commit으로 커밋하고 현재 작업 브랜치에 push한다. 테스트 전 커밋은 검증 대기다. 완료 보고 전에 local/remote HEAD 일치와 untracked를 포함한 working tree를 확인한다.
* 미완료 작업이나 다른 작업자의 변경을 완료 범위에 섞어 커밋하지 않는다. push 실패·remote 충돌은 보고하고, 별도 승인 없이 force push, merge, rebase, branch switch, destructive Git operation을 하지 않는다.
* working tree에 기존 변경이 있으면 먼저 내용을 확인하고 보존한다. 다른 작업자의 변경을 임의 삭제·clean·discard하거나 되돌리지 않는다.
* 저장소에서 확인 가능한 내용을 사용자에게 다시 묻지 않는다.

## Completion Report

완료 보고는 다음만 간결하게 포함한다.

* 변경한 capability
* 실제 교체한 경우 cut-over / 삭제한 legacy authority
* 테스트·Gate 결과
* DONE / TESTED / PENDING / BLOCKED를 구분한다. DONE은 구현 완료, TESTED는 실제 수행한 검증, PENDING은 남은 작업·미검증, BLOCKED는 필수 외부 조건 부재로 수행 불가능한 최종 검증이다.
* commit/push 결과와 local/remote HEAD 일치 여부, 남은 working tree 변경

별도 status/report 문서는 사용자가 요청하지 않으면 만들지 않는다.
