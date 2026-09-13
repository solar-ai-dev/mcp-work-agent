# Full contract audit — 2026-09-13

## 판정

| 구분 | 결과 |
| --- | --- |
| 전수 조사 | 완료 — inventory 2,306/2,306, 미검수 0 |
| 승인 없이 가능한 계약 재정비 | 완료 — 확정 결함 14건 수정·검증, 즉시 수정 범위 미해결 0 |
| 실제 의미·Graph·E2E 검증 | 실행 완료, 성공 아님 |
| 전체 재정비 성공 | **NO** |

전체 성공이 아닌 이유는 Product 9B Smoke 6건 중 Business PASS가 1건이고, deterministic
production-composition E2E의 두 시나리오가 세 Graph profile 모두에서 현재 LLM-call profile
한도에 도달했으며, 실제 Dataset 115개 Live와 Provider WRITE 검증은 실행 전제·승인 범위가
확정되지 않아 실행하지 않았기 때문이다.

이후 사용자 결정 4건은 제품 SHA `b6c42a75c0f2cbe611e719dfb2f90789cf236cab`에 반영했다. 직접 계약은 통과했지만 동일
production-composition 두 시나리오는 확정된 18/20 한도 안에서 계속 `BLOCKED`이므로 전체
성공 판정은 바꾸지 않았다.

## 실행 기준

- 분석 시작 HEAD: `23e08df05c2679d472dc746d00304185108d15b6`
- Product Smoke SHA: `05d226423b0a6b7295dea0b60ad50b519159d155`
- 결과 작성 전 HEAD: `f8f5ed5d31251afb439404b5aa9c54575cbea9bb`
- 사용자 결정 반영 Product SHA: `b6c42a75c0f2cbe611e719dfb2f90789cf236cab`
- branch: `codex/issue-251-connected-contract`
- Local model: `qwen3.5:9b`
- digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- global temperature / seed: `0.2 / 1729`
- `identify_source_dependencies` owner-local temperature: `0.05`
- LangSmith project / experiment: `google-work-agent-development` /
  `full-contract-audit-post-fixes-20260913`
- Provider WRITE / SEND: `0 / 0`
- rerun-to-pass: `0`

Product Smoke 뒤의 두 commit은 E2E assertion과 로컬 측정 스크립트/README 검증 명령만
고쳤다. Product `src/` 실행 코드는 Smoke SHA와 동일하다.

## Inventory

`inventory.json`은 현재 production file, Connector, projection, validator/guard, exchange
artifact, persistence/checkpoint, Prompt runtime, API entrypoint, LangGraph registration,
semantic owner operation, LLM caller, Prompt source, test, dataset, evaluation artifact에 각각
검수 ID를 부여한다.

| Kind | 수 |
| --- | ---: |
| Production files | 793 |
| Connector files | 63 |
| Projection files | 64 |
| Validator/guard files | 16 |
| Exchange artifact files | 142 |
| Persistence/checkpoint files | 51 |
| Prompt runtime files | 34 |
| API entrypoints | 49 |
| LangGraph registrations | 87 |
| Semantic owner operations | 87 |
| Product LLM callers | 28 |
| Prompt sources | 28 |
| Test artifacts | 685 |
| Dataset artifacts | 33 |
| Evaluation artifacts | 146 |

합계는 2,306개다. 파일 hash/등록 exact-set은 기계적으로 전수 대조했고, 28개 Product
Prompt는 source→caller→input contract→schema→validator/normalizer→consumer를 전수
대조했다. 87개 Graph/semantic operation과 API·Connector·State·Persistence·Write lifecycle은
owner 단위 정적 검사와 전체 회귀로 대조했다. 상세 판정과 증거는 `findings.json`에 있다.

## 수정 요약

- 확정 결함 수정: 14
- 중복 authority/instruction 축소: 1
- 명백한 책임 초과 정리: 2
- owner-local 내부 책임 분리: 1
- 사용자 결정 반영: 4
- 추가 제품 의미 결정 필요: 1 (`DEC-001`의 남은 E2E 지원 방식)
- 근거 부족 또는 별도 품질 문제: 5
- 외부/준비 blocker: 1

기존 주요 Product 수정은 Prompt/Schema binding 정합화, source-status revision의 owner-local화,
source 후보 fact metadata, 명시 날짜 보존, Retrieval current-page continuation, source-status
schema binding, duplicate/conflict 책임을 침범한 relation instruction 제거, cached segment의
동일 materialization 재수화, 한 Product Run당 LangSmith root 하나 보장이다. Main public State,
새 Store, 새 Agent/Node, Connector WRITE 정책, budget 숫자는 변경하지 않았다.

사용자 결정 반영에서는 LLM budget을 `14/20/18/24`로 고정하고 frozen multi-output의 bounded
승격을 연결했으며, 명시적 `CONTRACT_VIOLATION` outcome과 legacy failure-classification 결함을
분리했다. 자연어 target anchor는 identity로 사용하지 않고 selected stable identity 또는 현재
Run의 유일한 eligible stable identity만 Planning/Publication target authority로 허용했다. 새
semantic correction guard, Prompt 변경, 새 State/Store/Agent/Node는 추가하지 않았다.

## Product 9B Smoke

| Case | Contract | Business | Level | Terminal | 최초 실패/도달 | LLM | READ | WRITE | Run / Trace |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 대상 없는 일정 | PASS | PASS | PRE-CONFIRMATION | WAITING_CONFIRMATION | 정상 confirmation | 6 | 0 | 0 | `07695080-7abe-40b2-a643-c4a5f39b2875` / `01a097db-f5c5-7082-8772-bdcaa9a1b9d9` |
| Selected Event | FAIL | FAIL | READ | BLOCKED | `identify_output_responsibilities`가 read-only 요청에 SEND 생성 | 8 | 1 | 0 | `61325f85-709c-4de3-9b3f-3c66cd9d250b` / `01a097dc-586a-7eb1-89b9-166bfa1fffd6` |
| Atlas cross-source Draft | FAIL | FAIL | PRE-APPROVAL 미도달 | BLOCKED | `identify_source_dependencies`가 Task/Event 누락 | 12 | 2 | 0 | `ec5d3ac5-5ce5-443e-9baa-3a96b682a746` / `01a097dc-ce07-7f22-83b8-b5905151b1d6` |
| Quartz Draft UPDATE | PASS until Planning | FAIL | PRE-APPROVAL 미도달 | RECOVERY_REQUIRED | `compose_arguments_per_output_route`가 no-op patch 생성 | 10 | 1 | 0 | `c725aa58-e622-4d0c-9399-3b28909aaaa3` / `01a097dd-9d83-78d3-9539-393582b4d116` |
| Juniper 제목 전체 | Contract PASS | FAIL | READ | COMPLETED | 첫 Provider query 결과부터 고유 1건 | 11 | 2 | 0 | `fb18e728-2cab-43d4-b822-a9196b2af3bb` / `01a097de-595d-7061-8e69-b7da4057fa3f` |
| Atlas q19 | Contract PASS | FAIL | READ | COMPLETED/PARTIAL answer | `plan_query`가 status-only broad query 생성 | 16 | 13 | 0 | `3ffca642-793d-45ab-8b0c-5c09d04fc9e9` / `01a097df-00de-71c0-89e5-814c712ad91f` |

모든 Run은 원격 LangSmith에서 root 1개와 실제 node/LLM span을 확인했다. Connector가 호출된
다섯 Run에는 Connector span도 존재한다. Typed projection에는 원문·메일 본문·검색 literal·
Resource identity·credential을 새로 노출하지 않았다. 상세 URL과 안전한 count는
`smoke-summary.json`에 있다.

## 자동 검증

- 전체 pytest batch: `3,874 passed / 9 failed / 1 warning` (479.12s).
  - 3건은 현재 Review owner와 반대인 낡은 assertion으로 확인해 수정했고, 영향 테스트
    `3 passed`.
  - 남은 6건은 `partial approval`, `same-Run restart confirmation` 두 시나리오 × 세 profile로,
    모두 `PROFILE_LLM_LIMIT_EXHAUSTED`다. assertion을 완화하지 않았다.
- Prompt/architecture/compiled/integration 직접 batch: `511 passed`.
- 전체 mypy 공식 명령: `1,723 source files`, 오류 0.
- Ruff: 오류 0.
- compileall: 오류 0.
- Frontend: `266 passed`; typecheck, lint, production build PASS.
- Evaluation workspace: 구조 검사 PASS; unittest `78 passed / 1 skipped`.
- 사용자 결정 직접·인접 회귀: 최종 집중 batch `124 passed`, Prompt manifest/input-contract
  `56 passed`, 추가 broad focused batch `382 + 278 + 74 + 24 passed`.
- 변경 source Ruff, mypy 12개 source, `git diff --check`: PASS.
- 결정 반영 production-composition 직접 batch: `6 passed / 6 failed`. selected-resource 및
  unresolved-target 6개는 PASS, partial approval/restart confirmation 6개는 선택된 18/20 한도
  안에서 `BLOCKED`. assertion 완화·한도 확대·rerun-to-pass는 하지 않았고 외부 WRITE는 0이다.

전체 pytest를 마지막 두 비제품 commit 뒤 다시 한 번 돌려 성공값으로 덮어쓰지 않았다.
실패 batch와 수정한 assertion의 3-profile 직접 재검증을 모두 보존했다.

## 미실행·보류

- 현재 Dataset은 문서 자체가 115개 사용자 질문을 자동 Product Live runner로 연결하지
  않았고 실계정 provisioning도 미확정이라고 명시한다. 전체 115개 실제 Live는 NOT_RUN이다.
- Provider WRITE가 필요한 Case는 현재 요청에서 승인된 실제 effect 범위가 없으므로 BLOCKED다.
- 네 사용자 결정은 반영됐다. 다만 `DEC-001`의 두 deterministic E2E를 현 한도 안에서
  지원하려면 LLM owner 축소 또는 지원 범위 결정이 추가로 필요하다. 새 의미 보정 guard와
  retry 구제 승격은 결정에 따라 구현하지 않았다. `decisions.json` 참고.

## 파일

- `inventory.json`: 전수 대상과 hash/ID
- `findings.json`: owner별 정상·결함·수정·검증·잔여 판정
- `decisions.json`: `RESOLVED_WITH_REMAINING_VALIDATION`
- `test-runs.json`: 실제 실행 명령과 결과
- `progress.md`: 완료·잔여·재개 지점
- `smoke-summary.json`: 안전한 Run/Trace/count 요약
