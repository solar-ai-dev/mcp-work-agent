# 12. Architecture Enforcement

**상태:** CANONICAL

Architecture 검사는 문서 inventory가 아니라 실제 source/import/caller/contract를 검사한다.

## Required gates

- forbidden generic filename과 version/generation suffix
- Domain→outward, Application→concrete Adapter, LangGraph→SQLite/Provider, Route→DB/Adapter concrete, Product→Evaluation 등 금지 dependency
- Provider SDK·SQLite·subprocess의 Adapter 경계
- operation-per-file naming과 owner-local contract package
- capability당 live production authority 하나, concrete composition root 하나
- migrated capability의 production caller cut-over와 old import/export/authority 0
- Port/Adapter binding uniqueness와 persistence mirror
- LangGraph thin node, registered route/resume target, Domain truth와 checkpoint/projection 분리
- 외부 I/O 중 SQLite write transaction 0
- Approval → Claim → BeginExecutionAttempt commit → WRITE → Verification/Recovery 경계
- `UNKNOWN_RESULT` blind resend와 duplicate dispatch 0
- Frontend의 policy/execution/owner 추론 0
- test 간 private helper import 0, fixture ownership, 적용 migration 보존
- runtime Prompt/Tool/Connector manifest와 schema/hash의 loader·consumer 정합성
- Evaluation→Product internal import와 두 번째 Product authority 0

## Test strategy

검사는 가능한 한 AST/import graph, source tree, runtime manifest/schema와 production composition을 직접 사용한다. Canonical에 파일·심볼·테스트의 거대한 exact 목록을 만들고 이를 parser input으로 사용하지 않는다. 새 operation은 concern contract와 실제 owner/caller/test를 함께 갱신하며, Git diff와 코드 검색으로 closure를 확인한다.

Enforcement를 통과시키기 위해 allowlist를 넓히거나 assertion을 약화하거나 skip/xfail/ignore를 추가하지 않는다. 예외는 `13 Exception Registry`에 구조적 이유와 범위를 먼저 기록한 경우에만 허용한다.

## Structural closure

완료 판정은 다음을 모두 요구한다.

```text
naming/placement
+ dependency direction
+ single production authority
+ production caller cut-over
+ old authority/import/export absence
+ Port/Adapter and transaction boundary
+ owned tests and safety regression
```

이 Gate는 behavioral regression과 실제 제품 검증을 대신하지 않는다. 문서 파일의 존재, Issue 상태, 과거 closure report만으로 구현 완료를 판정하지 않는다.

## Local runtime gate

Architecture 검사는 지원 모델 allowlist/readiness authority와 Runtime Router binding이 하나인지 확인한다. Browser/Prompt/Connector source의 임의 model ID, URL, path, shell fragment가 Adapter 실행으로 이어지지 않아야 한다. 제품에 Ollama 설치, model pull, download/provisioning authority가 존재해서는 안 되며, Local과 Gemini 자동 fallback도 없어야 한다.

## Preservation

문서 정리로 spec-to-code snapshot이나 audit ledger를 제거해도 dependency, ownership, single-authority, write safety 검사는 유지한다. API/wire/checkpoint/migration/manifest 실행 버전과 실제 runtime/test fixture는 문서 버전이나 inventory와 별개로 보존한다.
