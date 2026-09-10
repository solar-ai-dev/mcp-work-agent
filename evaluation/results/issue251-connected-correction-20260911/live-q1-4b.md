# Q1 READ-only · qwen3.5:4b

- 질문: `Nimbus 출시 날짜만 메일에서 확인해줘.`
- 실행 코드: `4d8c2ab6c644e559541dcc6c0ee70320cae289ff`
- 최초 실패 노드: `retrieval.execute_read` → `retrieval.select_evidence`
- 결과: **FAIL** — 서로 다른 세 Gmail Thread query를 제한 범위에서 실행했지만 모두 후보 0건이어서 Evidence와 날짜 답변을 만들지 못했다. 최종 `COMPLETED/PARTIAL`로 근거 부족을 알렸으며 Provider WRITE는 0이다.
- Run ID: `0e43b719-9d25-4673-a9f1-96a1d89be200`
- LangSmith: [trace `01a08cc7-f22d-7ef3-b122-adf7cba6b870`](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/r/01a08cc7-f22d-7ef3-b122-adf7cba6b870)
