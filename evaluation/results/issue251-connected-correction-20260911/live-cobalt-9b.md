# Cobalt READ-only · qwen3.5:9b

- 질문: `메일에서 Cobalt 남극 출장 확정 안내 찾아줘.`
- 실행 코드: `4d8c2ab6c644e559541dcc6c0ee70320cae289ff`
- 최초 실패 노드: 두 번째 `retrieval.build_query` 이후 `retrieval.execute_read` 미진입
- 결과: **FAIL** — 첫 Gmail Thread READ는 후보 0건이었다. 부족 근거로 후속 query를 생성했지만 해당 query의 Connector READ가 실행되지 않아, 최종 `COMPLETED/PARTIAL` 답변은 근거 부족으로 종료했다. Provider WRITE는 0이다.
- Run ID: `26c3152e-f5f8-474a-9cb9-e5193d4e7bd8`
- LangSmith: [trace `01a08cc1-03ed-7f70-830e-b6c7a1b1f9f3`](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/r/01a08cc1-03ed-7f70-830e-b6c7a1b1f9f3)
