# Contract Audit final POST Production Smoke — 2026-09-13

| Case | Contract | Business | Wait/Resume | Terminal | First failure | LLM | READ | WRITE | SEND | Run | Trace |
|---|---|---|---|---|---|---:|---:|---:|---:|---|---|
| 대상 없는 일정 | PASS | FAIL | confirmation/resume | COMPLETED/PARTIAL | `planning.compose_answer` 시간대 렌더링 | 17 | 23 | 0 | 0 | `7b7cf28f-f598-4eab-a62d-908280119ea4` | [initial](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09805-e1b8-7b12-a603-e5ee96e443fb/run/01a09805-e1b8-7b12-a603-e5ee96e443fb) · [resume](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09807-3829-7a32-b0c0-35bc90b6c82c/run/01a09807-3829-7a32-b0c0-35bc90b6c82c) |
| Selected Event | FAIL | FAIL | none | BLOCKED | `identify_output_responsibilities` | 8 | 0 | 0 | 0 | `70434218-164b-49a4-a5b9-60f1ebed8d3e` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09808-d8c3-7d72-b0f6-c3573baf4526/run/01a09808-d8c3-7d72-b0f6-c3573baf4526) |
| Atlas Draft | FAIL | FAIL | approval 미도달 | BLOCKED | `identify_source_dependencies` 과선택 | 11 | 1 | 0 | 0 | `a11c3589-c1f4-472b-8640-da352d2eca28` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a0980d-d25f-7ff0-8d2a-20bc61fa5fed/run/01a0980d-d25f-7ff0-8d2a-20bc61fa5fed) |
| Juniper 전체 제목 | PASS | FAIL | none | COMPLETED/PARTIAL | `retrieval.plan_query` semantic output | 16 | 13 | 0 | 0 | `b661f715-4d58-4e7f-8be3-688a4b1e3dba` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09809-fe90-7ba1-9b19-68bda727d2f4/run/01a09809-fe90-7ba1-9b19-68bda727d2f4) |
| Atlas q19 | PASS | PASS | none | COMPLETED/SUCCESS | 최종 도달 | 13 | 13 | 0 | 0 | `da7b179f-006c-401d-a0f8-506e5a09a64d` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a0980c-29cc-7750-9258-f88fc8bc0336/run/01a0980c-29cc-7750-9258-f88fc8bc0336) |
| Quartz Draft | FAIL | FAIL | approval 미도달 | RECOVERY_REQUIRED | `planning.compose_arguments_per_output_route` | 10 | 1 | 0 | 0 | `6bb112d2-31c9-4c1e-85ac-174a52915c89` | [trace](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/trace/01a09811-02de-71f1-97d0-d5ecb1a9cdb3/run/01a09811-02de-71f1-97d0-d5ecb1a9cdb3) |

## 집계

- POST Product SHA: `11d1ac1666340c8984ba1afca3c0a9dbc3ff636b`
- Business PASS: 1/6
- Contract PASS: 3/6
- LangSmith execution trace: 6/6, same-Run resume를 포함한 root 7개
- LLM calls: 75
- Connector READ: 51
- Provider WRITE / SEND: 0 / 0
- 공식 initial Domain Run: 6
- same-Run confirmation resume: 1
- rerun-to-pass: 0
- Batch 중 제품·Prompt·Schema·fixture·모델 변경: 0

## PRE 대비

| Case | PRE Contract | PRE Business | POST Contract | POST Business | 변경 | 판정 |
|---|---|---|---|---|---|---|
| 대상 없는 일정 | FAIL | FAIL | PASS | FAIL | CONTRACT_IMPROVED | confirmation/resume는 정상화됐으나 Answer가 `11:00`을 `오후 11시`로 잘못 렌더링 |
| Selected Event | FAIL | FAIL | FAIL | FAIL | UNCHANGED | read-only 요청에 `GMAIL_MESSAGE/SEND`를 생성했고 fast path 이전 차단 |
| Atlas Draft | FAIL | FAIL | FAIL | FAIL | UNCHANGED | 최초 실패가 goal schema에서 source dependency 과선택으로 이동 |
| Juniper 전체 제목 | FAIL | FAIL | PASS | FAIL | CONTRACT_IMPROVED | collection 미완료를 PARTIAL로 보존했으나 초기 query가 `STATUS_SCOPE`만 포함 |
| Atlas q19 | PASS | PASS | PASS | PASS | UNCHANGED_PASS | KEYWORD query와 detail fetch로 정답 Evidence/답변 확보 |
| Quartz Draft | FAIL | FAIL | FAIL | FAIL | UNCHANGED | 정확한 Draft READ 뒤 Planning argument binding 실패 유지 |

PRE/POST Business PASS는 모두 1/6이고 Contract PASS는 1/6에서 3/6으로 증가했다. Business/Contract 기준 regression은 없다. 새로 도달한 후단 실패는 대상 없는 일정의 Answer 시간 표현이며, Atlas Draft의 최초 실패 형태는 source 누락에서 과선택으로 바뀌었다.

상세 판정은 `summary.json`, `comparison.json`, `case-*.json`, `traces/index.json`에 있다. Raw Prompt/completion, Provider payload, credential, Resource identity는 저장하지 않았다.
