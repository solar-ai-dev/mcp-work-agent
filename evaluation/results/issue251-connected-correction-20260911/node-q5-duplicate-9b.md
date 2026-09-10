# Q5 · qwen3.5:9b · Task 중복 판단

- 실행 코드: `4d8c2ab6c644e559541dcc6c0ee70320cae289ff`
- 검증 노드: `work_analysis.detect_duplicate_conflict_candidates` 1.0.6
- 조건: temperature 0.2, seed 1729, 최초 호출과 허용된 의미 재검증 1회
- 결과: PASS
- 핵심 현상: 최초 출력은 `NOT_SATISFIED`에 무관한 관측 후보를 matched로 결속했다. 해당 semantic violation만 1회 재검증한 결과 `NOT_SATISFIED`, matched fact 0, matched candidate 0으로 수렴했다. 실제 LLM dispatch는 2회, Connector READ와 Provider WRITE는 0이었다.
- 수정 연결: `4d8c2ab6`에서 모순 출력의 제한 1회 재검증과 durable budget 전달을 추가했다.
- Run ID: `00c33824-bae8-4b24-a020-26df797206e7`
- LangSmith: [trace 01a08ca3-6af7-77f1-8cac-f97eb05965dc](https://smith.langchain.com/o/abfc5c65-0dac-4bab-9116-d6ecb654559d/projects/p/bb148490-6fe2-4a00-9ac6-73ea946231e0/r/01a08ca3-6af7-77f1-8cac-f97eb05965dc)
