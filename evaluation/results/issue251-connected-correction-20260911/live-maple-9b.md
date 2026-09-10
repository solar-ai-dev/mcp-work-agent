# Maple READ-only · qwen3.5:9b

- 질문: `Maple 점검 날짜 최종으로 정해졌어?`
- 실행 코드: `4d8c2ab6c644e559541dcc6c0ee70320cae289ff`
- 최초 실패 노드: 세 번째 `retrieval.plan_query`
- 결과: **FAIL** — Gmail READ 2회 뒤 추가 query 계획의 구조화 출력이 `retrieval-query-plan-v2` 검증을 통과하지 못했다. 저장된 안전 오류는 `OUTPUT_SCHEMA_INVALID`이며 `route_queries[0]`과 검색 제약 manifestation 경로를 가리킨다. Run은 `BLOCKED`로 종료됐고 Provider WRITE는 0이다.
- Run ID: `5acfb6ec-5433-4a5d-b045-6e8e29052b4d`
- LangSmith: [trace `01a08cc3-c140-7df0-b309-21b774bb6974`](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/r/01a08cc3-c140-7df0-b309-21b774bb6974)
