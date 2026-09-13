# Issue 251 confirmed target contract 복구

현재 branch의 제품 변경을 `deed527515dff0e53ef54f2d6bb0baaf9134a85d` 하나로 고정해 검증했다.

## 결론

| Case | 결과 | 핵심 확인 |
| --- | --- | --- |
| 대상 없는 Calendar | PASS | `WAITING_CONFIRMATION → COMPLETED/SUCCESS`, 같은 Run 확인 응답 1회, 근거 2개 |
| Selected Event | PASS | 선택한 `Atlas 인쇄소 슬롯` identity로 정확한 시간 답변 |
| Atlas Draft | PASS | TASK 22 + Calendar 23을 포함한 source page 47/50, 정확한 Draft Preview, `WAITING_APPROVAL` |
| Juniper EXHAUSTIVE | PASS | 검색 2회, 제목 26개/고유 26개, 누락 0/초과 0 |
| Atlas q19 | PASS | 검색 1회 + 상세조회 12회, 근거 9개, 최종 출고 시점과 담당 답변 |
| Quartz Draft | PASS | Draft 검색 1회, exact edit 1회 보존, 기존 snapshot/identity 보존, `WAITING_APPROVAL` |

회귀 복구 판정은 **6/6 PASS**다. rerun-to-pass는 0이며 승인, execution dispatch, Provider WRITE/SEND는 모두 0이다.

## 수정

- `target_resource` confirmation resume이며 selected identity가 없고 prior source가 비었을 때만 source-dependency dynamic output contract에 `SOURCE_REQUIRED` 최소 1개를 요구했다. Resource type은 기존 semantic owner가 선택한다.
- canonical `search_terms`의 `USER_REQUEST`와 `CONFIRMATION_RESPONSE` provenance를 current-Run trusted search provenance로 공통 소비한다.
- stable selected Resource identity가 없고 단일 business-required route가 SEARCH+KEYWORD를 지원할 때, 첫 bounded discovery query에 exact PHRASE anchor와 기존 required `CONTAINER_REF`를 보존한다.
- Calendar/resource 이름이나 자연어 lexical rule은 추가하지 않았다.

Prompt와 Prompt version, canonical Schema version, State, Graph Node/Edge는 변경하지 않았다. 새 LLM 호출도 추가하지 않았다. 변경된 것은 owner-local dynamic output constraint와 deterministic query projection이다.

## 검증

- 직접 관련 unit/component: 408 passed
- Ruff: PASS
- mypy(변경 production 모듈): 3 passed
- Calendar Gate: 1회 PASS
- 최종 Production Smoke: Case당 1회, 6/6 PASS
- LangSmith: 모든 Case에서 실제 Product SHA/모델/Prompt/실험 binding 확인. root → node → LLM/tool span 생성, error span 0
- 전체 pytest: 실행하지 않음(요청 범위)

Calendar Gate Run은 `46df4905-d1ba-4a3c-aacd-8b427d11da26`, 최종 6개 Run과 trace 상세는 `summary.json`과 `langsmith-summary.json`에 있다.

Juniper 실행 직후 임시 판정기는 데이터셋의 `### 메일 N — 제목` 형식을 잘못 읽어 기대 제목을 0개로 만들었다. 추가 Run 없이 저장된 답변을 올바른 데이터셋 heading과 대조해 26개 전체 일치로 판정했다. 이는 제품 실패가 아니다.
