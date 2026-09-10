# #251 연결 계약 교정·검증

기준 제품 커밋: `4d8c2ab6c644e559541dcc6c0ee70320cae289ff`

## Node 진단

| 사례 | 모델 | 최초 검증 노드 | 결과 | 기록 |
|---|---|---|---|---|
| Q4 Draft UPDATE | qwen3.5:4b | `request_understanding.identify_goal` | PASS — READ+UPDATE와 Gmail Draft source/output 보존 | [node-q4-identify-4b.md](node-q4-identify-4b.md) |
| Q5 Task CREATE | qwen3.5:4b | `request_understanding.identify_goal` | FAIL — structured inference 오류로 intent 미생성 | [node-q5-identify-4b.md](node-q5-identify-4b.md) |
| Q5 비중복 판단 | qwen3.5:9b | `work_analysis.detect_duplicate_conflict_candidates` | PASS — 최초 의미 모순을 제한 1회 재검증 후 비중복으로 수렴 | [node-q5-duplicate-9b.md](node-q5-duplicate-9b.md) |
| Cobalt 후속 조회 | qwen3.5:9b | `retrieval.plan_query` | PASS — 0건 소진 뒤 비어 있지 않은 후속 조회 계획 생성·검증 | [node-cobalt-followup-9b.md](node-cobalt-followup-9b.md) |

## Production Graph 통제 회귀

production compiled Graph와 통제 LLM/MCP를 사용한 대표 경로 30건이 통과했다. 상세 범위는 [graph-controlled-regression.md](graph-controlled-regression.md)에 기록했다.

## READ-only Live

| 질문 | 모델 | 최초 실패 노드 | 결과 | 기록 |
|---|---|---|---|---|
| Q1 Nimbus 날짜 | qwen3.5:9b | `retrieval.select_evidence` / `retrieval.assess_sufficiency` | FAIL — 첫 검색 후보 2건을 Evidence로 연결하지 못했고 제한 재조회는 0건 | [live-q1-9b.md](live-q1-9b.md) |
| Q4 Quartz Draft | qwen3.5:9b | `review.recheck` | FAIL — 실제 Draft 후보 1건을 읽었지만 정확한 UPDATE Preview 대신 이미 명시한 문구를 다시 묻는 Confirmation으로 종료 | [live-q4-9b.md](live-q4-9b.md) |
| Cobalt 확정 안내 | qwen3.5:9b | 두 번째 `retrieval.build_query` 이후 `retrieval.execute_read` 미진입 | FAIL — 첫 검색 0건 뒤 후속 query는 생성했지만 실제 READ 없이 근거 부족으로 종료 | [live-cobalt-9b.md](live-cobalt-9b.md) |
