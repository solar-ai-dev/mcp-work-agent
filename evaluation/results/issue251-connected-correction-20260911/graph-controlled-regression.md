# Production Graph 통제 회귀

- 사례/모델: Evidence 재평가·RU 재진입, same-Run Confirmation revision, Task 중복/no-action·비중복/Preview·미표현 관측 재평가, context adjustment, Draft 원본 snapshot / 통제 LLM·MCP
- 실행 코드: `4d8c2ab6c644e559541dcc6c0ee70320cae289ff`
- 최초 검증 노드: `work_analysis.detect_duplicate_conflict_candidates`, `request_understanding.identify_goal`, `retrieval.select_evidence`, `planning`
- 결과: PASS — 선택한 production compiled Graph·인접 계약 검사 30건 통과
- 핵심 현상: 같은 자료의 동일 평가는 stable identity를 유지하고 의미가 달라진 재평가는 새 identity를 만들었다. 새 Evidence는 같은 Run의 Request Understanding revision으로 연결됐고, Task 중복은 no-action, 비중복은 Preview, 미표현 관측은 재평가 뒤 판단으로 연결됐다. context adjustment는 같은 Run의 누적 budget·stale invalidation을 유지했다. Draft snapshot은 관측한 nullable 원본과 미관측 필드를 구분했다.
- 실행 ID/trace: pytest 임시 Domain Run은 종료 후 보존하지 않았고 LangSmith 전송 대상이 아니었다. 실제 외부 Provider effect는 0이며, context-adjustment 안전 경로는 test-only MCP에서만 실행됐다.
