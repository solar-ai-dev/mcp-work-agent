# Issue 251 Atlas 최소 수정 후 확인

- 기준 요청 HEAD: `55f85993b1ee08a3a972e48b1bcfaa2f494ede61`
- 수정 전 HEAD: `20835eb30011bd39418ce4a807d1a7f141217b28`
- 실행 제품 SHA: `d89207e4d5cf9f0fa425a00dfa670ae119af8f3f`
- 브랜치: `codex/issue-251-connected-contract`
- 모델: `qwen3.5:9b`
- 모델 digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`
- temperature / seed: `0.0` / `null` (development 기본값 유지)
- entry mode / 선택 Resource: `AGENT_SEARCH` / 없음

## 변경

### Atlas Draft — 저장 설정만 변경

제품 코드와 이미 50인 공통 상수·기본 Settings는 변경하지 않았다. 실제 backend가 사용하는
저장 설정 API로 `max_source_page_calls_per_run`만 `8 → 50`으로 변경했다. 함께 저장된
Calendar 23개, Task list 22개, GitHub Repository 1개의 선택은 전후 동일하다. 기존
Run/checkpoint의 budget은 변경하지 않았다.

### Atlas q19 — 제품 코드 변경

`deterministic_query_plan`에서 다음 조건을 모두 만족하는 경우에만 유효한 미조회 candidate의
`DETAIL_FETCH`를 query expansion보다 먼저 반환한다.

- required Typed sufficiency issue에 `CANDIDATE_DETAIL_REQUIRED`가 있음
- 실제 미조회 detail candidate가 있음
- 요청의 `coverage_requirement`가 `EXHAUSTIVE`가 아님

상세 조회 후에는 기존 Evidence/Sufficiency 흐름을 그대로 사용하고, 상세 후보가 없거나 여전히
부족한 경우 기존 `NEXT_PAGE`/검색 확장 경로를 사용한다. EXHAUSTIVE 목록 요청은 기존
pagination 우선순위를 유지한다.

## 직접 검증

- 일반 사실 조회 + 상세 필요 + 다음 페이지 가능: `DETAIL_FETCH`
- EXHAUSTIVE + 상세 필요 + 다음 페이지 가능: `NEXT_PAGE`
- 기존 operation 기준 retrieval round budget: 통과
- 대상 파일 Ruff lint: 통과
- 대상 파일 mypy: 통과
- 전체 pytest 및 6개 전체 Smoke: 실행하지 않음

## 제품 Run 결과

| Case | Run | 결과 | 실제 조회 | 핵심 결과 |
|---|---|---|---|---|
| Atlas Draft | `6be3c84f-4fa9-4637-94c1-00c563049bb0` | `WAITING_APPROVAL` | Calendar/Task 관련 READ 47회 | 받는 사람과 Task 2건, 8월 13일 14~15시 인쇄소 일정을 포함한 Gmail Draft Preview 1건 |
| Atlas q19 | `a6afa343-2c0d-4e20-9d2b-4e0e508df4cf` | `COMPLETED / SUCCESS` | `gmail_search_threads` 1회 → `gmail_get_thread` 12회 | 최종 출고 8월 19일 오전, 담당 지민 |

두 Run 모두 승인 0, execution attempt 0, Provider WRITE/SEND 0이다.

LangSmith에는 두 Run 모두 `root → node → LLM/tool` span이 존재한다.

- Atlas Draft trace: `01a09c40-40f9-7c73-a116-44642b424736`
- Atlas q19 trace: `01a09c42-f3b3-7693-9752-a2f5c1a8e137`

비밀키, OAuth 토큰, 불필요한 메일 원문은 포함하지 않았다.
