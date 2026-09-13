# Atlas Draft

## 최초 정상 경계와 실패 입력/출력

- 마지막 동일 정상 경계: `node:tool_route`
- 최종 조립: Source `TASK + CALENDAR_EVENT`, Output `GMAIL_DRAFT/CREATE`, ambiguity confirmation 불필요
- frozen input routes: `CALENDAR_EVENT`, `TASK`, `CALENDAR`, `TASK_LIST`
- frozen output route: `gmail_create_draft`
- 실패 Retrieval 입력의 핵심 차이: `max_source_page_calls=8` (성공 50)
- 실패 Retrieval 출력: `acquisition.status=PARTIAL`, resource handles 0, source summaries 12, `source_page_calls_used=8`

실패 Run은 `calendar_list_events(query="인쇄소")` 8회를 서로 다른 authorized calendar container에 수행했고 각 candidate count는 0이었다. 계획 순서상 뒤의 TASK/CALENDAR/TASK_LIST route는 Provider에 도달하지 못했다.

## reason chain

1. `execute_read`가 아홉 번째 plan 전에 `SOURCE_PAGE_LIMIT`을 반환한다.
2. 남은 네 required route summary가 `termination_kind=BUDGET_STOPPED`, `budget_reason_code=SOURCE_PAGE_LIMIT`로 투영된다.
3. deterministic sufficiency가 네 route를 `REQUIRED_SOURCE_PARTIAL`로 만들고 `BLOCKED`를 낸다.
4. Main supervisor가 최종 reason `CONTEXT_BLOCKED`를 생산한다.

LangSmith root 자체는 callback 실행이 정상 완료되어 `success`지만, Domain Run은 `BLOCKED`다. 마지막 UI 상태만 보고 실패 위치를 LangSmith root로 오인하면 안 된다.

## 관련 코드 위치 (`cfcf1faf`)

- `src/google_work_agent/application/agents/retrieval/build_query.py:101-145`: container plan을 route-major 순서로 확장
- `src/google_work_agent/adapters/langgraph/subgraphs/retrieval/graph.py:1397-1500`: 확장된 순서대로 실행하고 첫 budget stop에서 나머지를 종료
- `src/google_work_agent/application/agents/retrieval/execute_read.py:174-200`: `BUDGET_STOPPED` 생산
- `src/google_work_agent/adapters/langgraph/main/supervisor_retrieval_rules.py:106-110`: `CONTEXT_BLOCKED` 생산

`7afac9f5..cfcf1faf`에는 위 Retrieval/Connector 코드 diff가 없다. 비교 Run의 page 상한이 달라진 것이 먼저다.

## 권장 최소 수정안 (제안, 미적용)

동일 설정 재비교가 선행이다. 제품의 유효 설정으로 page 상한 8을 유지해야 한다면, source cap을 늘리는 대신 container fan-out의 실행 순서만 required route 간 round-robin으로 바꾼다.

```diff
diff --git a/src/google_work_agent/application/agents/retrieval/build_query.py b/src/google_work_agent/application/agents/retrieval/build_query.py
@@ def materialize_container_read_plans(plans):
-    materialized = []
+    expanded_by_route = []
     for plan in plans:
-        for ref in container["container_refs"]:
-            materialized.append(_materialize_one(plan, ref))
-    return materialized
+        expanded_by_route.append([
+            _materialize_one(plan, ref)
+            for ref in container["container_refs"]
+        ])
+    return _round_robin(expanded_by_route)
```

실제 구현 시 기존 inline materialization을 작은 helper로만 추출하고, 다음 회귀 조건을 추가한다: page cap이 required route 수 이상일 때 각 required route가 최소 1회 실행되며, budget stop summary의 `known_scope_count`가 보존되어야 한다.

이 변경이 Atlas Draft의 업무 성공까지 보장한다는 근거는 없다. 확인된 결함 범위는 “첫 route가 전체 budget을 독점해 다른 필수 source READ가 0회가 되는 현상”이다.
