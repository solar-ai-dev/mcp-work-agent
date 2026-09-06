# mcp-work-agent — Codex Instructions

이 `AGENTS.md`는 저장소 루트 전체에 적용한다.

하위 `AGENTS.md`는 경로별 규칙을 추가할 수 있지만 이 파일과 `/docs`의 Canonical 계약을 약화시키면 안 된다.

## Authority

* 코딩 기준은 현재 저장소 `/docs`의 Canonical snapshot이다.
* 항상 `00 Project Source Guide`에서 Concern Owner와 선행 읽기 순서를 먼저 확인한다.
* behavior는 해당 Concern Owner가 소유하고, repository path/file/symbol/import/single-authority 규칙은 `16 Repository Architecture`가 소유한다.
* 현재 코드, 기존 테스트, Git history, 기존 파일명은 설계 Authority가 아니다. migration input이다.
* 현재 구현에서 target architecture를 역추론하지 않는다.
* 문서에 없는 state, lifecycle, owner, Port, operation, contract/type을 임의로 만들지 않는다.
* 적용된 Migration은 수정하지 않는다. 필요한 DB 변경은 forward Migration으로 추가한다.

## Current Work Mode

현재 작업은 일반적인 behavior-preserving refactor가 아니라 **Canonical design에 기존 구현을 reconciliation하는 migration**이다.

* 잘못된 기존 구조나 behavior는 기존 코드라는 이유로 보존하지 않는다.
* Canonical과 이미 일치하는 구현은 불필요하게 rewrite하지 않는다.
* 작업 단위는 파일이 아니라 **semantic capability**다.
* 새 구현을 추가하는 것보다 기존 authority를 canonical authority로 교체하는 것을 우선한다.

## Work Procedure

각 capability의 구현은 다음 순서로 처리하고, 테스트 실행은 아래 프롬프트 단위 검증 순서로 모은다.

```text
SPEC
→ Canonical Owner 확인
→ 기존 implementation / caller / test / DI 검색
→ KEEP | MOVE | MERGE | REWRITE | DELETE | CREATE 판정
→ canonical implementation으로 cut-over
→ production caller 전환
→ old authority / import / export 제거
→ 관련 계약·테스트 코드 갱신 (실행은 프롬프트 단위로 일괄)
```

규칙:

* 새 production file을 만들기 전에 동일 capability의 기존 구현을 먼저 찾는다.
* 하나의 capability에는 하나의 production authority만 둔다.
* 가능한 한 capability 하나를 완전히 cut-over한 뒤 다음 capability로 이동한다.
* 기존 구현을 대체하는 새 구현을 만들었다면 불필요한 old path를 남기지 않는다.
* 중복 구현은 MERGE/DELETE한다.
* 작은 diff보다 **가장 작은 완결 capability cut-over**를 우선한다.

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
* Agent → peer Agent direct call
* Agent/LLM → external Write authority
* speculative abstraction
* second live production authority
* 단순 forwarding만 늘리는 wrapper/adapter chain

## Canonical / Compatibility

Canonical은 기존 구조 위에 추가되는 새 계층이 아니다.

* 같은 의미의 V1/V2/Canonical implementation을 동시에 production authority로 유지하지 않는다.
* compatibility는 migration 중 필요한 얇은 delegate/re-export만 허용한다.
* compatibility layer는 business logic을 소유하지 않는다.
* capability cut-over가 끝나면 old caller/path/import/export와 temporary compatibility를 제거한다.
* `R1`, `R2`, `R2.1`, `Wave`, `Phase` 같은 구현 단계는 장기 production architecture로 남기지 않는다.

같은 business fact를 단순 Layer 이동 때문에 별도 DTO/type으로 반복 정의하지 않는다. 새 representation은 실제 boundary가 있을 때만 추가한다.

## State / Workflow / Write Safety

* undocumented state/transition/edge/resume target을 만들지 않는다.
* Domain Store는 승인·실행·검증 사실의 기준점이다.
* LangGraph Checkpoint는 workflow resume 위치다.
* UI/SSE/Trace는 Projection이며 Domain truth가 아니다.
* external MCP/Provider/LLM I/O 중 SQLite write transaction을 유지하지 않는다.
* Write는 Canonical Approval → Claim → BeginExecutionAttempt → Connector Write → Verification/Recovery 경계를 따른다.
* `BeginExecutionAttempt(applied=true)` commit 전 Connector Write는 0이어야 한다.
* `UNKNOWN_RESULT`에서는 blind resend나 새 Write Attempt를 만들지 않는다.
* Agent/LLM이 approval, policy, state transition, execution success를 최종 판정하지 않는다.

## Tests / Gates

* 기본 검증 단위는 개별 기능이나 파일이 아니라 사용자가 전달한 한 프롬프트의 작업 범위다. 구현 전 production path와 기존 테스트를 조사하고, 계약·테스트 코드는 구현과 함께 갱신한다.
* 해당 프롬프트 범위의 구현을 마친 뒤 직접 영향 자동 테스트와 typing/lint/관련 architecture gate를 일괄 실행한다. 통과 후 실제 앱 E2E → 필요한 수정 → 실패 시나리오와 직접 영향 경로 재검증 순서로 진행한다.
* 개별 기능 수정마다 같은 테스트 묶음, 앱 재시작, 전체 E2E를 반복하지 않는다. 전체 회귀는 별도로 지정된 최종 단계에서 수행한다.
* 이미 확인된 검증 실패나 안전성 문제가 있으면 기능 범위를 확장하지 않고 원인 수정에 집중한다. 검증을 뒤로 모으는 것은 검사 기준을 낮추거나 미검증 결과를 PASS로 간주한다는 뜻이 아니다.
* 사용자가 커밋을 허용한 작업에서는 기능 경계별 coherent commit을 유지할 수 있다. 테스트 전 커밋은 검증 대기이며, 필수 검증을 마치기 전에는 기능이나 프롬프트 작업의 완료를 선언하지 않는다.
* 현재 Product Runtime Closure 작업에서는 실제 앱 E2E만 마지막 8/8로 모은다. 노드 입출력 계약 테스트는 반드시 수행하고, 필요한 pytest·API 테스트와 typing/lint·architecture gate는 중간에도 직접 영향 범위로 실행한다. 특히 WRITE는 노드 간 입력값·출력 형식, 승인 인자와 실행 인자의 보존, 실행 안전 경계를 검증한다. 같은 대형 테스트 묶음은 매 수정마다 반복하지 않는다. E2E 전에는 `구현 완료·E2E 검증 대기`로 구분하며, 제공되지 않은 후속 단계의 범위를 임의로 만들지 않는다.
* 기존 테스트도 Authority가 아니다. Canonical behavior와 invariant를 검증해야 한다.
* 기존 테스트가 Canonical과 충돌하면 KEEP | REWRITE | DELETE를 판정한다.
* 테스트는 observable behavior, state transition, safety invariant, external effect를 우선 검증한다.
* production source 문자열이나 private method 내부 구현을 직접 검사하는 테스트는 피한다.
* 테스트 파일끼리 private helper를 import하지 않는다. 반복되는 fixture/fake는 `tests/support` 또는 `tests/fakes`로 이동한다.
* 관련 safety/contract/state test가 깨진 상태에서 완료라고 보고하지 않는다.

필수 구조 Gate 예:

```text
Application → concrete Adapter        = 0
Domain → Application                  = 0
Core → Provider SDK/direct API        = 0
FastAPI Route → Adapter/DB concrete   = 0
Agent → Provider API/SDK              = 0
Agent → peer Agent direct call        = 0
external I/O inside SQLite write tx   = 0
duplicate production authority        = 0
```

## Completion

Capability는 다음을 만족해야 완료다.

* canonical authority 존재
* production caller가 canonical authority 사용
* duplicate writer/authority 0
* 불필요한 old caller/import/export 제거
* temporary compatibility 제거 또는 명시적 미완료 dependency만 존재
* 관련 Canonical tests 통과
* safety/state/transaction invariant 유지

새 구현을 추가한 것만으로 완료가 아니다.

**기존 authority가 제거되었다는 확인까지 필요하다.**

## Git / Scope

* 사용자가 명시하지 않으면 commit, push, merge, rebase, branch switch, destructive Git operation을 하지 않는다.
* 관련 없는 cleanup, formatting-only 대형 diff, dependency-wide upgrade를 만들지 않는다.
* 다른 작업자의 변경을 임의로 되돌리지 않는다.
* 저장소에서 확인 가능한 내용을 사용자에게 다시 묻지 않는다.

## Completion Report

완료 보고는 다음만 간결하게 포함한다.

* 변경한 capability
* cut-over / 삭제한 legacy authority
* 테스트·Gate 결과
* 남은 실제 blocker 또는 명시적 migration dependency

별도 status/report 문서는 사용자가 요청하지 않으면 만들지 않는다.
