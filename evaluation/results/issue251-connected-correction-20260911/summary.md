# #251 연결 계약 교정·검증

기준 제품 커밋: `4d8c2ab6c644e559541dcc6c0ee70320cae289ff`

## Node 진단

| 사례 | 모델 | 최초 검증 노드 | 결과 | 기록 |
|---|---|---|---|---|
| Q4 Draft UPDATE | qwen3.5:4b | `request_understanding.identify_goal` | PASS — READ+UPDATE와 Gmail Draft source/output 보존 | [node-q4-identify-4b.md](node-q4-identify-4b.md) |
| Q5 Task CREATE | qwen3.5:4b | `request_understanding.identify_goal` | FAIL — structured inference 오류로 intent 미생성 | [node-q5-identify-4b.md](node-q5-identify-4b.md) |
