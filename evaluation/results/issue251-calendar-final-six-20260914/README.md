# Issue 251 Calendar confirmation 복구 검증

- 브랜치: `codex/issue-251-connected-contract`
- source 재평가 제품 SHA: `493e2f047c6cec210d98d524c96b58493350b32e`
- 모델: `qwen3.5:9b` / digest `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature / seed: `0.0` / `null`
- Prompt: `request_understanding.identify_goal` `1.0.62` / `98fc61337e02e8cc7099f52925bccbbc03e1f5a8b3f821f996c30ea5d592d7aa`
- 자동 LangSmith tracing: 비활성

## 구현

`target_resource` confirmation의 `USER_REQUIREMENT/search_terms` + exact `CONFIRMATION_RESPONSE` provenance 결속을 유지했다.

- prior `source_reads`가 비었을 때: 기존 resume의 `identify_goal` LLM 1회를 기존 `identify_source_dependencies` 호출 1회로 교체
- prior `source_reads`가 있거나 stable selection이 있을 때: source를 다시 판단하지 않고 LLM 호출 0회
- 기존 goal, completion conditions, output responsibilities, status/provenance 보존
- 새 source decision과 보존한 output decision을 기존 `merge_resource_responsibilities`로 결합
- effect/resource hint는 `derive_requested_resource_fields`에서만 재파생

Prompt/Schema/State와 Graph Node/Edge 구조는 변경하지 않았다. lexical rule, Calendar hardcode, validator 완화도 없다.

## 직접 테스트

| 경계 | 결과 |
| --- | --- |
| target confirmation + prior source 0 | source dependency만 1회 재평가 |
| prior source non-empty | 보존, LLM 0회 |
| stable SelectedResourceRef | identity 보존, search term 하향 없음, LLM 0회 |
| prior status/output | 재평가 뒤 동일하게 보존 |

- 관련 pytest: `100 passed`
- Ruff: 통과
- mypy: 변경 source 3개 통과

## Calendar 단발 결과

| 항목 | 결과 |
| --- | --- |
| Run | `79aecaeb-86e8-4bad-a2e6-c581597ba4a5` |
| 최초 요청 | `WAITING_CONFIRMATION` |
| 같은 Run confirmation | `프로젝트 검토 회의`, 1회 |
| 재확인 | 없음 |
| Connector READ | 23 |
| Evidence | 2 |
| 답변 | 2026-08-18 10:00–23:00 |
| terminal | `COMPLETED / PARTIAL` |
| 제품 판정 | **FAIL** |

확인값 결속, Calendar Event source, Retrieval과 근거 기반 답변은 모두 정상이다. 하지만 exact single-target 요청인데도 “전체 범위를 확인하지 못했다”는 PARTIAL 안내가 붙어 정상 답변으로 판정하지 않았다.

이번 실제 initial Run은 LLM이 이미 `CALENDAR_EVENT` source responsibility를 만들었으므로 resume에서 source 재평가 LLM은 필요하지 않았고 실행되지 않았다. prior source 0 경로는 직접 테스트로 검증했다.

## 새 최초 실패

- `CALENDAR_EVENT`: READ 23, observed 1, Evidence 2, `scope_complete=true`, `COMPLETE / EXHAUSTED`
- access-only parent `CALENDAR`: tool route가 discovery route로 추가했지만 source status는 `NOT_ATTEMPTED / UNKNOWN`
- Retrieval coverage: `PARTIAL`, missing information 1

즉 실제 Event source는 완결됐지만 access-only discovery route가 미시도 필수 source처럼 sufficiency에 포함돼 PARTIAL을 만들었다. 이는 confirmation owner가 아니라 Retrieval sufficiency/accounting 경계의 별도 결함이다.

단발 및 rerun-to-pass 금지 조건에 따라 이 결함을 이어서 수정하거나 Calendar를 재실행하지 않았다. Calendar Gate가 PASS가 아니므로 최종 6 Smoke도 실행하지 않았다.

## 안전성 / Trace

- rerun-to-pass: 0
- Provider WRITE/SEND: 0
- approval / execution attempt: 0 / 0
- initial Trace: `01a09cb0-1347-7c73-ad7b-dd6ca9ab9a31` — root/node/LLM/tool `1/6/6/0`
- resume Trace: `01a09cb0-7fe8-7ff2-9b04-bf819d5b7928` — root/node/LLM/tool `1/29/6/23`
- LangSmith code/model/prompt/question binding: 일치
