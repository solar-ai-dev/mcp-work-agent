# Contract Audit POST Production Smoke — 2026-09-13

| Case | Contract | Business | Wait/Resume | Terminal | First failure | LLM | READ | WRITE | SEND | Run | Trace |
|---|---|---|---|---|---|---:|---:|---:|---:|---|---|
| 대상 없는 일정 | PASS | PASS | Confirmation 1 / same-Run resume 1 | COMPLETED / PARTIAL | - | 17 | 24 | 0 | 0 | `aac5351a` | [initial](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09762-54ec-7a22-8415-6b2a5207edf7/run/01a09762-54ec-7a22-8415-6b2a5207edf7) / [resume](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09765-15d7-79c3-b081-24d67f5b7384/run/01a09765-15d7-79c3-b081-24d67f5b7384) |
| Selected Event | FAIL | FAIL | - | BLOCKED | `identify_output_responsibilities` | 8 | 1 | 0 | 0 | `41dd4729` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09767-4538-71d0-a170-dcb2a9326f3b/run/01a09767-4538-71d0-a170-dcb2a9326f3b) |
| Atlas Draft | FAIL | FAIL | - | BLOCKED | `identify_source_dependencies` | 7 | 0 | 0 | 0 | `69526203` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a0976a-71ce-74b1-b809-6397d0596b54/run/01a0976a-71ce-74b1-b809-6397d0596b54) |
| Juniper 전체 제목 | PASS | FAIL | - | COMPLETED / SUCCESS | `plan_query` semantic coverage | 9 | 1 | 0 | 0 | `cdf9c5f5` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09768-5020-7f62-8cb2-6ac95e2381ca/run/01a09768-5020-7f62-8cb2-6ac95e2381ca) |
| Atlas q19 | PASS | FAIL | - | COMPLETED / SUCCESS | `plan_query` semantic coverage | 9 | 1 | 0 | 0 | `aa7ad161` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09769-6241-78c2-9a30-aa6f70069fe9/run/01a09769-6241-78c2-9a30-aa6f70069fe9) |
| Quartz Draft | FAIL | FAIL | - | RECOVERY_REQUIRED | `compose_arguments_per_output_route` | 10 | 1 | 0 | 0 | `073daf18` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a0976b-8b08-7873-afbc-e68add80acb1/run/01a0976b-8b08-7873-afbc-e68add80acb1) |

## 실행 기준

- Product SHA: `6a56d48c111b4bb9af00fc3b877a548f464808a6`
- Branch/local/upstream/remote: `codex/issue-251-connected-contract` / 동일 SHA
- Model: `qwen3.5:9b` (`6488c96f…893ea7`), temperature `0.2`, seed `1729`
- Node override: `identify_source_dependencies=0.05`
- Prompt manifest: `a43705c3…8ab61`, 28 slots
- LangSmith: `google-work-agent-development`, experiment `contract-audit-post-smoke-six-20260913`
- Google: CONNECTED, missing scope 0, Task Lists 22, Calendars 23
- 공식 실행: initial Domain Run 6/6, rerun-to-pass 0, same-Run confirmation resume 1
- LangSmith: execution root/node/LLM 6/6, Connector span과 durable READ count 일치
- Provider WRITE 0, SEND 0

## Canonical / Architecture 정리

제품 `src/`는 기존 Canonical architecture gate 370개를 모두 통과했고 중복 production authority나 금지된 legacy naming이 확인되지 않아 변경하지 않았다. 실제 불일치는 테스트가 `tests.support`의 private `_...` 심볼을 공유 API처럼 import하던 부분이었다.

- 공용 test-support helper/harness를 의미가 드러나는 public 이름으로 변경했다.
- architecture gate에 `tests.support*` private-symbol import 금지를 추가했다.
- 현재 node contract와 어긋난 stale fixture 2곳만 최신 typed 입력 위치/shape로 정리했다.
- AST 기준 중복 test body 0, 실증 가능한 obsolete/duplicate test 0이어서 테스트 삭제는 하지 않았다.
- 제품 코드, Prompt, Schema, State, Graph, runtime behavior 변경은 0이다.

검증:

- 직접 영향 + architecture: 513 passed
- 전체 unit/contract/component/integration: 3392 passed, unrelated deprecation warning 1
- Ruff: PASS
- mypy: 1069 files, PASS
- `git diff --check`: PASS

## PRE / POST 비교

| Case | PRE Contract | PRE Business | POST Contract | POST Business | 변경 | 판정 |
|---|---|---|---|---|---|---|
| 대상 없는 일정 | FAIL | FAIL | PASS | PASS | 개선 | 같은 Run 확인 후 grounded partial answer |
| Selected Event | FAIL | FAIL | FAIL | FAIL | 변화 없음 | 불필요한 SEND output 유지 |
| Atlas Draft | FAIL | FAIL | FAIL | FAIL | 변화 없음 | 최초 실패 경계가 source/ambiguity로 이동 |
| Juniper 전체 제목 | FAIL | FAIL | PASS | FAIL | 계약 개선 | coverage typed 의미 보존, query 0건 |
| Atlas q19 | PASS | PASS | PASS | FAIL | **REGRESSION** | valid query가 positive-control 자료를 회수하지 못함 |
| Quartz Draft | FAIL | FAIL | FAIL | FAIL | 변화 없음 | Planning argument binding failure 유지 |

집계:

- Business PASS: PRE 1/6 → POST 1/6
- Contract PASS: PRE 1/6 → POST 3/6
- LLM: PRE 64 → POST 60
- Connector READ: PRE 27 → POST 28
- Unexpected confirmation/write/SEND: PRE 0/0/0 → POST 0/0/0

이번 refactor는 제품 코드를 바꾸지 않았으므로 POST의 stochastic 결과 변화는 refactor 개선 효과로 단정하지 않는다. 특히 Atlas q19의 Business 회귀를 숨기지 않고 그대로 보존한다.

## 관측 메모

첫 launcher에서는 readiness와 descriptor publication 사이 race, 다음 exchange에서는 bootstrap grant 만료가 발생했다. 두 번 모두 공식 Domain Run 생성 전이었고, active handoff 0을 확인한 뒤에만 backend를 교체했다. 공식 6 Run 시작 후 backend 재시작과 제품 변경은 없었다.

상세 raw trace, raw Prompt/completion, Provider payload, Resource identity, credential은 저장하지 않았다.
