# #251 검색 실행 계약 직접 결과

측정 제품: `e9b46415d6e35602c69ef02f8900a2cecb1d7f00`

| 질문/사례 · 모델 | 최초 실패 또는 검증 노드 | 결과와 핵심 현상·원인 | Run / Trace |
|---|---|---|---|
| 연결 계약 직접 검사 | `plan_query → build_query → Gmail argument projection` | **PASS** — verified source provenance, route별 operation/ref, 공통 Gmail literal validator, typed no-progress 오류와 mixed READ 실행 경계를 직접 검사했다. 선택 테스트 176개 + Prompt/manifest/architecture 42개, 변경 production mypy와 Ruff가 통과했다. 수정 커밋은 `e9b46415`이다. | 통제 자동 검사, Provider READ/WRITE 0 |
| Cobalt 후속 조회 · `qwen3.5:9b` (`temperature=0.2`, `seed=1729`) | `retrieval.plan_query` | **FAIL** — 최초 후보와 허용된 revision까지 실제 Local LLM을 호출했으나, 새 Evidence 뒤에 실행 가능한 변경 query로 수렴하지 않아 `QueryUnchangedAfterFailureError` (`RETRIEVAL_QUERY_PLAN_SEMANTIC_INVALID`)로 종료됐다. LLM dispatch 2회, Connector dispatch 0회다. 이번 결과는 통제 upstream을 사용한 Node 계약 측정이며 전체 Graph/Live 성공이 아니다. | `01a08d17-c666-73d1-bcd0-8ab9e932102b` · [LangSmith trace](https://smith.langchain.com/r/01a08d17-c666-73d1-bcd0-8ab9e932102b) |
| Maple 후속 조회 · `qwen3.5:9b` (`temperature=0.2`, `seed=1729`) | `retrieval.plan_query → retrieval.build_query → Gmail argument projection` | **PASS** — 실제 Local LLM 1회로 이전 query와 다른 `SEARCH`를 생성했고, 검증된 사용자 literal을 보존해 `gmail_search_threads` 인자 projection까지 통과했다. Connector dispatch 0회다. 실행 당시 저장소 HEAD는 결과 전용 커밋이 포함된 `083a6ee3`이며 제품 코드는 `e9b46415`와 동일하다. 전체 Graph/Live 성공을 뜻하지 않는다. | `01a08d18-fffd-7361-a7b3-323d173e4db2` · [LangSmith trace](https://smith.langchain.com/r/01a08d18-fffd-7361-a7b3-323d173e4db2) |
